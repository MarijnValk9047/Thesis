"""Resource-capped Phase-5B physical and economic export breakthrough tests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_c0_athanasiadis_sale_sensitivity import (
    _validate_containment_records,
    policy_overrides,
)
from .s4_4c5p_c0_wag_ng_allocation_envelope import (
    _load_normal_solution_records,
    _normal_schedule,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import (
    _case_overrides,
    load_phase4_config,
)
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    MATERIAL_THRESHOLD_TWH_E_Y,
    _git_head,
    _read_csv,
    _resolve,
    _sha256,
    frozen_case_matrix,
    install_terminal_validation_extension,
    load_config as load_parent_config,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT, _select_solver


RUN_ID = "steel_c5_phase5b_breakthrough_tests_v1_20260727"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5b_breakthrough_tests.yaml"
)
NG_FIELDS = (
    "NG_to_HSM_mwh",
    "NG_to_PEFA_malerij_mwh",
    "NG_to_PEFA_branderij_mwh",
    "natural_gas_boiler_mwh",
    "generator_named_ng_mwh",
    "full_site_energy_bridge_named_ng_mwh",
)


class Phase5BBreakthroughError(RuntimeError):
    pass


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5BBreakthroughError(
            f"Persistent path must be repository-relative: {path.resolve()}"
        ) from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(rows)
    fields = sorted({key for row in materialized for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal":
        raise Phase5BBreakthroughError("Breakthrough run identity or output policy changed.")
    test = payload.get("breakthrough", {})
    if (
        test.get("physical_oracle_mode") != "phase5b_physical_wag_upper_bound_v1"
        or test.get("clean_economic_mode") != "phase5b_clean_economic_export_v1"
        or float(test.get("material_threshold_twh_e_y", -1.0))
        != MATERIAL_THRESHOLD_TWH_E_Y
        or any(
            bool(test.get(key))
            for key in (
                "emissions_costs_added",
                "export_price_floor_added",
                "physics_changed",
                "held_out_periods_used",
            )
        )
    ):
        raise Phase5BBreakthroughError("The frozen breakthrough-test contract changed.")
    return payload


def _reference_metrics_by_replan(
    hourly: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    rows = [
        row for row in hourly if str(row["configuration_id"]) == C0_CONFIGURATION
    ]
    result: dict[str, dict[str, float]] = {}
    for replan_index in range(7):
        block = [row for row in rows if int(row["replan_index"]) == replan_index]
        if not block:
            raise Phase5BBreakthroughError(
                f"Comparator C0 execution block {replan_index} is missing."
            )
        result[str(replan_index)] = {
            "gross_grid_import_mwh": sum(
                float(row["gross_grid_import_mwh"]) for row in block
            ),
            "named_ng_mwh_lhv": sum(
                float(row[field]) for row in block for field in NG_FIELDS
            ),
            "wag_generator_electricity_mwh": sum(
                float(
                    row.get("WAG_generator_electricity_mwh_unrounded")
                    or row["WAG_generator_electricity_mwh"]
                )
                for row in block
            ),
        }
    return result


def _artifact(directory: Path) -> dict[str, Any]:
    return {
        "directory": directory,
        "summary": json.loads((directory / "run_summary.json").read_text(encoding="utf-8")),
        "hourly": _read_csv(directory / "executed_hourly.csv"),
        "models": _read_csv(directory / "rolling_model_metrics.csv"),
        "validation": _read_csv(directory / "validation_checks.csv"),
    }


def _case_pass(artifact: Mapping[str, Any]) -> bool:
    return bool(
        len(artifact["models"]) == 14
        and all(
            row.get("termination_condition", "").lower() == "optimal"
            for row in artifact["models"]
        )
        and all(row.get("status") == "pass" for row in artifact["validation"])
    )


def _wag_total(artifact: Mapping[str, Any]) -> float:
    return sum(
        float(
            row.get("WAG_generator_electricity_mwh_unrounded")
            or row["WAG_generator_electricity_mwh"]
        )
        for row in artifact["hourly"]
        if row["configuration_id"] == C0_CONFIGURATION
    )


def _run_comparator(
    *,
    parent: Mapping[str, Any],
    phase4: Mapping[str, Any],
    case: Mapping[str, Any],
    target: Mapping[str, Any],
    scratch: Path,
    implementation_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any], Path]:
    case_id = f"breakthrough__{case['period_id'].replace('-', '_')}__no_export"
    capture = scratch / f"capture__{case['period_id'].replace('-', '_')}"
    provenance = {
        "schema_version": "steel_phase5b_breakthrough_comparator_capture_v1",
        "period_id": case["period_id"],
        "implementation_sha256": implementation_sha256,
        "terminal_band_fingerprint_sha256": target[
            "terminal_band_fingerprint_sha256"
        ],
    }
    overrides = _case_overrides(
        phase4,
        {**case, "case_id": case_id},
        _resolve(parent["phase5b"]["forecast_run_root"]),
        int(target["campaign_terminal_executed_hours"]),
        target["terminal_band"],
    )
    overrides.update(
        {
            "run_id": case_id,
            "lineage_role": "phase5b_breakthrough_no_export_comparator",
            "phase2_implementation_sha256": implementation_sha256,
            "normal_solution_capture": {
                "enabled": True,
                "structural_inactive_exclusion_enabled": True,
                "directory": str(capture),
                "provenance": provenance,
            },
        }
    )
    run_closed_loop_feasibility_anchor_reconciliation(
        config_path=_resolve(phase4["phase4"]["physical_config"]),
        output_root=scratch,
        scenario_overrides=overrides,
    )
    artifact = _artifact(scratch / case_id)
    schedule, schedule_hash = _normal_schedule(artifact["directory"])
    records = _load_normal_solution_records(capture)
    return artifact, schedule, schedule_hash, records, capture


def _run_sale(
    *,
    parent: Mapping[str, Any],
    phase4: Mapping[str, Any],
    case: Mapping[str, Any],
    target: Mapping[str, Any],
    scratch: Path,
    implementation_sha256: str,
    comparator_schedule: list[dict[str, Any]],
    comparator_schedule_hash: str,
    comparator_records: Mapping[str, Any],
    capture: Path,
    references: Mapping[str, Any],
    mode: str,
) -> dict[str, Any]:
    label = "physical_upper_bound" if mode.endswith("upper_bound_v1") else "clean_economic"
    case_id = f"breakthrough__{case['period_id'].replace('-', '_')}__{label}"
    overrides = _case_overrides(
        phase4,
        {**case, "case_id": case_id, "sale_enabled": True},
        _resolve(parent["phase5b"]["forecast_run_root"]),
        int(target["campaign_terminal_executed_hours"]),
        target["terminal_band"],
    )
    sale = policy_overrides("athanasiadis_sale_enabled")[
        "c0_electricity_sale_sensitivity"
    ]
    sale.update(
        {
            "incumbent_capture_directory": str(capture),
            "incumbent_provenance_by_replan": {
                key: dict(record["provenance"])
                for key, record in comparator_records.items()
            },
            "containment_oracle_root": str(scratch / case_id / "sale_containment"),
            "breakthrough_test": {
                "mode": mode,
                "reference_metrics_by_replan": dict(references),
            },
        }
    )
    overrides.update(
        {
            "run_id": case_id,
            "lineage_role": f"phase5b_breakthrough_{label}",
            "phase2_implementation_sha256": implementation_sha256,
            "c0_electricity_sale_sensitivity": sale,
        }
    )
    if mode == "phase5b_physical_wag_upper_bound_v1":
        overrides["c0_allocation_envelope_diagnostic"] = {
            "enabled": True,
            "endpoint": "max",
            "breakthrough_mode": mode,
            "state_tolerance": 1e-6,
            "endpoint_solver_accuracy_schema": "steel_endpoint_solver_accuracy_v1",
            "endpoint_relative_mip_gap": 0.0,
            "endpoint_absolute_mip_gap_mwh": 0.001,
            "endpoint_bound_comparison_epsilon_mwh": 1e-9,
            "endpoint_annual_bound_uncertainty_limit_mwh_y": 1.0,
            "normal_controller_schedule": comparator_schedule,
            "normal_controller_schedule_sha256": comparator_schedule_hash,
            "normal_solution_records_by_replan": dict(comparator_records),
            "failure_evidence_directory": str(scratch / case_id / "endpoint_oracles"),
            "iis_evidence_sha256": "743021602174ee6faf9d148ab0773c61b94f6aaba47eb7e2a23961ec4eff1b26",
        }
    run_closed_loop_feasibility_anchor_reconciliation(
        config_path=_resolve(phase4["phase4"]["physical_config"]),
        output_root=scratch,
        scenario_overrides=overrides,
    )
    return _artifact(scratch / case_id)


def run_breakthrough_tests(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config = load_config(config_path)
    test = config["breakthrough"]
    parent = load_parent_config(_resolve(test["parent_phase5b_config"]))
    phase4 = load_phase4_config(_resolve(parent["phase5b"]["phase4_config"]))
    targets_payload = json.loads(
        _resolve(parent["phase5b"]["phase4_target_contract"]).read_text(encoding="utf-8")
    )
    targets = {row["period_id"]: row for row in targets_payload["targets"]}
    output = _resolve(config["output_root"])
    scratch = _resolve(test["scratch_root"])
    if output.exists() or scratch.exists():
        raise Phase5BBreakthroughError("Breakthrough output or scratch root already exists.")
    _, solver = _select_solver()
    if solver is None:
        raise Phase5BBreakthroughError("Gurobi is unavailable before the first solve.")
    install_terminal_validation_extension()
    output.mkdir(parents=True)
    scratch.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    implementation_files = (
        Path(config_path).resolve(),
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_phase5b_breakthrough_tests.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    )
    implementation_manifest = [
        {"path": _portable(path), "sha256": _sha256(path)} for path in implementation_files
    ]
    implementation_sha256 = _payload_sha256(implementation_manifest)
    cases = {
        row["period_id"]: row
        for row in frozen_case_matrix(parent)
        if row["policy_id"] == "accepted_no_export_comparator"
    }
    case_rows: list[dict[str, Any]] = []
    oracle_rows: list[dict[str, Any]] = []
    economic_rows: list[dict[str, Any]] = []
    resource_cap_rows: list[dict[str, Any]] = []
    completed_periods: list[str] = []
    clean_economic_run = False
    period_contexts: dict[str, dict[str, Any]] = {}

    def execute_period(period_id: str, *, physical: bool, clean: bool) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
        comparator, schedule, schedule_hash, records, capture = _run_comparator(
            parent=parent,
            phase4=phase4,
            case=cases[period_id],
            target=targets[period_id],
            scratch=scratch,
            implementation_sha256=implementation_sha256,
        )
        references = _reference_metrics_by_replan(comparator["hourly"])
        period_contexts[period_id] = {
            "comparator": comparator,
            "schedule": schedule,
            "schedule_hash": schedule_hash,
            "records": records,
            "capture": capture,
            "references": references,
        }
        case_rows.append(
            {"period_id": period_id, "case": "no_export_comparator", "status": "pass" if _case_pass(comparator) else "fail"}
        )
        physical_artifact = None
        clean_artifact = None
        if physical:
            physical_artifact = _run_sale(
                parent=parent, phase4=phase4, case=cases[period_id], target=targets[period_id],
                scratch=scratch, implementation_sha256=implementation_sha256,
                comparator_schedule=schedule, comparator_schedule_hash=schedule_hash,
                comparator_records=records, capture=capture, references=references,
                mode=test["physical_oracle_mode"],
            )
            containment = _validate_containment_records(
                physical_artifact["directory"] / "sale_containment",
                expected_replan_indices=range(7),
            )
            comparator_wag = _wag_total(comparator)
            physical_wag = _wag_total(physical_artifact)
            gain = physical_wag - comparator_wag
            annual_gain = gain * 8760.0 / 168.0 / 1_000_000.0
            oracle_rows.append(
                {
                    "period_id": period_id,
                    "comparator_wag_generator_electricity_mwh": comparator_wag,
                    "physical_upper_bound_wag_generator_electricity_mwh": physical_wag,
                    "physical_upper_bound_gain_mwh": gain,
                    "annual_equivalent_gain_twh_e_y": annual_gain,
                    "material_threshold_twh_e_y": MATERIAL_THRESHOLD_TWH_E_Y,
                    "threshold_pass": annual_gain >= MATERIAL_THRESHOLD_TWH_E_Y,
                    "containment_status": containment["status"],
                    "resource_caps_status": "pass" if all(
                        row.get("sale_breakthrough_resource_caps_status") in {"pass", ""}
                        for row in physical_artifact["models"]
                    ) else "fail",
                }
            )
            for replan_index in range(7):
                model_row = next(
                    row
                    for row in physical_artifact["models"]
                    if row["configuration_id"] == C0_CONFIGURATION
                    and int(row["replan_index"]) == replan_index
                )
                reference = references[str(replan_index)]
                actual_import = float(
                    model_row["sale_breakthrough_actual_gross_grid_import_mwh"]
                )
                actual_ng = float(
                    model_row["sale_breakthrough_actual_named_ng_mwh_lhv"]
                )
                resource_cap_rows.append(
                    {
                        "period_id": period_id,
                        "replan_index": replan_index,
                        "reference_gross_grid_import_mwh": reference[
                            "gross_grid_import_mwh"
                        ],
                        "actual_gross_grid_import_mwh": actual_import,
                        "gross_grid_import_residual_mwh": actual_import
                        - reference["gross_grid_import_mwh"],
                        "reference_named_ng_mwh_lhv": reference[
                            "named_ng_mwh_lhv"
                        ],
                        "actual_named_ng_mwh_lhv": actual_ng,
                        "named_ng_residual_mwh_lhv": actual_ng
                        - reference["named_ng_mwh_lhv"],
                        "status": model_row[
                            "sale_breakthrough_resource_caps_status"
                        ],
                    }
                )
            case_rows.append(
                {"period_id": period_id, "case": "physical_wag_upper_bound", "status": "pass" if _case_pass(physical_artifact) and containment["status"] == "pass" else "fail"}
            )
        if clean:
            clean_artifact = _run_sale(
                parent=parent, phase4=phase4, case=cases[period_id], target=targets[period_id],
                scratch=scratch, implementation_sha256=implementation_sha256,
                comparator_schedule=schedule, comparator_schedule_hash=schedule_hash,
                comparator_records=records, capture=capture, references=references,
                mode=test["clean_economic_mode"],
            )
            containment = _validate_containment_records(
                clean_artifact["directory"] / "sale_containment",
                expected_replan_indices=range(7),
            )
            case_rows.append(
                {"period_id": period_id, "case": "clean_economic_export", "status": "pass" if _case_pass(clean_artifact) and containment["status"] == "pass" else "fail"}
            )
            clean_gain = _wag_total(clean_artifact) - _wag_total(comparator)
            economic_rows.append(
                {
                    "period_id": period_id,
                    "clean_economic_wag_gain_mwh": clean_gain,
                    "annual_equivalent_gain_twh_e_y": clean_gain * 8760.0 / 168.0 / 1_000_000.0,
                    "containment_status": containment["status"],
                }
            )
        completed_periods.append(period_id)
        return comparator, physical_artifact, clean_artifact

    first = str(test["first_gate_period_id"])
    execute_period(first, physical=True, clean=False)
    first_oracle = oracle_rows[0]
    first_gate_pass = bool(
        first_oracle["threshold_pass"]
        and first_oracle["containment_status"] == "pass"
        and first_oracle["resource_caps_status"] == "pass"
        and all(row["status"] == "pass" for row in case_rows)
    )
    if first_gate_pass:
        # The clean economic solve and July remain strictly downstream of the
        # physical possibility proof.
        context = period_contexts[first]
        clean_artifact = _run_sale(
            parent=parent, phase4=phase4, case=cases[first], target=targets[first],
            scratch=scratch, implementation_sha256=implementation_sha256,
            comparator_schedule=context["schedule"],
            comparator_schedule_hash=context["schedule_hash"],
            comparator_records=context["records"], capture=context["capture"],
            references=context["references"], mode=test["clean_economic_mode"],
        )
        clean_containment = _validate_containment_records(
            clean_artifact["directory"] / "sale_containment",
            expected_replan_indices=range(7),
        )
        clean_gain = _wag_total(clean_artifact) - _wag_total(context["comparator"])
        economic_rows.append(
            {
                "period_id": first,
                "clean_economic_wag_gain_mwh": clean_gain,
                "annual_equivalent_gain_twh_e_y": clean_gain * 8760.0 / 168.0 / 1_000_000.0,
                "containment_status": clean_containment["status"],
            }
        )
        case_rows.append(
            {
                "period_id": first,
                "case": "clean_economic_export",
                "status": "pass" if _case_pass(clean_artifact) and clean_containment["status"] == "pass" else "fail",
            }
        )
        clean_economic_run = True
        if case_rows[-1]["status"] == "pass":
            execute_period(str(test["second_period_id"]), physical=True, clean=True)

    full_continuation_success = bool(
        first_gate_pass
        and len(economic_rows) == 2
        and all(row["status"] == "pass" for row in case_rows)
        and all(
            row["annual_equivalent_gain_twh_e_y"] >= MATERIAL_THRESHOLD_TWH_E_Y
            for row in economic_rows
        )
    )
    decision = (
        "resource_capped_clean_economic_export_material_both_periods_sensitivity_only"
        if full_continuation_success
        else "physical_upper_bound_below_material_threshold_stop_no_clean_economic_or_july"
        if not first_gate_pass
        else "resource_capped_breakthrough_continuation_failed_retain_no_export"
    )
    checkpoint = {
        "run_id": RUN_ID,
        "status": "pass" if full_continuation_success else "stop",
        "decision": decision,
        "february_physical_gate_pass": first_gate_pass,
        "clean_economic_run": clean_economic_run,
        "july_run": str(test["second_period_id"]) in completed_periods,
        "central_model_boundary": "accepted_no_export_retained_and_frozen",
        "emissions_costs_present": False,
        "minimum_export_price_or_market_friction_present": False,
        "held_out_validation_authorized": False,
        "oracle_results": oracle_rows,
        "clean_economic_results": economic_rows,
    }
    _write_csv(output / "case_status.csv", case_rows)
    _write_csv(output / "physical_upper_bound_summary.csv", oracle_rows)
    _write_csv(output / "resource_cap_audit.csv", resource_cap_rows)
    _write_csv(output / "clean_economic_summary.csv", economic_rows)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    _write_json(
        output / "input_manifest.json",
        {
            "schema_version": "steel_phase5b_breakthrough_input_manifest_v1",
            "parent_phase5b_config": {
                "path": _portable(_resolve(test["parent_phase5b_config"])),
                "sha256": _sha256(_resolve(test["parent_phase5b_config"])),
            },
            "implementation": implementation_manifest,
            "implementation_sha256": implementation_sha256,
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "retention_status": "local_ignored",
            "git_eligible": False,
            "status": "pass" if full_continuation_success else "stop",
            "decision": decision,
        },
    )
    _write_json(output / "code_version.json", {"git_commit": _git_head(), "implementation_sha256": implementation_sha256})
    (output / "README.md").write_text(
        "# Phase 5B breakthrough tests\n\n"
        "February first tests the maximum physically possible WAG-generator electricity while preserving the corrected eight-state no-export trajectory and prohibiting any increase in executed gross grid import or named natural gas. The clean economic export solve and July are downstream gates only. No emissions cost, export-price floor, transaction spread, physics, target, terminal band, or tolerance was changed.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "- DEVELOPMENT-week physical upper bound; not annual or held-out evidence.\n"
        "- Export remains a frictionless same-price upper-bound interface. ETS, fees, spreads, imbalance and minimum bid prices remain outside this test.\n",
        encoding="utf-8",
    )
    _write_json(
        output / "run_summary.json",
        {
            "run_id": RUN_ID,
            "status": "pass" if full_continuation_success else "stop",
            "decision": decision,
            "case_count": len(case_rows),
            "wall_time_seconds": time.perf_counter() - started,
        },
    )
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()
    print(json.dumps(run_breakthrough_tests(args.config), indent=2, sort_keys=True))
