"""Cost-optimal C0 WAG/NG allocation-envelope diagnostic.

The normal rolling controller remains authoritative.  Each endpoint trajectory
adds only the opt-in C0 endpoint hook after the normal progress, represented
procurement-cost and physical tie-break solves.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_c0_real_anchor_mechanism_experiment import (
    _expected_case_overrides,
    _manifest_paths_match,
    candidate_overrides,
    load_mechanism_config,
    validate_mechanism_config,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs"
    / "steel_c5_wag_ng_allocation_envelope.yaml"
)
EXPECTED_CANDIDATES = ("recovery_bg30_ng55", "recovery_bg30_ng30")
EXPECTED_SCENARIOS = (
    "calm_price_insensitive",
    "volatile_negative_governed_y_pred",
)
EXPECTED_ENDPOINTS = ("min", "max")
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
EXPECTED_HEAD = "5e25ec0c7c356d1b8773b0a25271f9b60bbdf057"
EXPECTED_RUN_ID = "steel_c5_wag_ng_allocation_envelope_v2_20260725"


class AllocationEnvelopeError(RuntimeError):
    """Raised when the frozen envelope contract or an acceptance gate fails."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    if not materialized:
        raise AllocationEnvelopeError(f"Refusing to write empty output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AllocationEnvelopeError("Allocation-envelope config must be a mapping.")
    validate_config(payload)
    return payload


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("run_id") != EXPECTED_RUN_ID:
        raise AllocationEnvelopeError("The allocation-envelope repair run id changed.")
    if config.get("mode") != "c0_wag_ng_cost_optimal_allocation_envelope":
        raise AllocationEnvelopeError("Unexpected allocation-envelope mode.")
    if config.get("output_policy") != "minimal":
        raise AllocationEnvelopeError("Allocation envelope requires output_policy=minimal.")
    if (
        config.get("run_class")
        != "bounded deterministic DEVELOPMENT allocation-envelope repair"
        or config.get("lineage_role") != "diagnostic/emulation sensitivity"
        or config.get("retention_status") != "local"
        or config.get("git_eligible") is not False
    ):
        raise AllocationEnvelopeError("The governed output classification changed.")
    experiment = config["experiment"]
    candidates = tuple(row["candidate_id"] for row in experiment["candidates"])
    scenarios = tuple(row["scenario_id"] for row in experiment["scenarios"])
    endpoints = tuple(experiment["endpoints"])
    if candidates != EXPECTED_CANDIDATES:
        raise AllocationEnvelopeError(f"Frozen candidates differ: {candidates}.")
    if scenarios != EXPECTED_SCENARIOS:
        raise AllocationEnvelopeError(f"Frozen scenarios differ: {scenarios}.")
    if endpoints != EXPECTED_ENDPOINTS:
        raise AllocationEnvelopeError(f"Frozen endpoints differ: {endpoints}.")
    if tuple(row["period_id"] for row in experiment["scenarios"]) != EXPECTED_PERIODS:
        raise AllocationEnvelopeError("Frozen validation timestamps/periods differ.")
    if any(
        row["dataset_split"] != "validation"
        or row["price_field"] != "y_pred"
        or bool(row["perfect_foresight_oracle"])
        for row in experiment["scenarios"]
    ):
        raise AllocationEnvelopeError("Held-out, TEST, y_true and oracle cases are prohibited.")
    expected_counts = {
        "candidate_count": 2,
        "scenario_count": 2,
        "endpoint_count": 2,
        "primary_control_count": 4,
        "endpoint_trajectory_count": 8,
        "replan_count": 7,
    }
    for key, expected in expected_counts.items():
        if int(experiment[key]) != expected:
            raise AllocationEnvelopeError(f"{key} must remain {expected}.")
    if bool(experiment["held_out_periods_used"]):
        raise AllocationEnvelopeError("Held-out periods must remain unused.")
    if (
        float(experiment["state_tolerance"]) != 1e-6
        or float(experiment["governed_cost_tolerance_eur_per_window"]) != 0.01
    ):
        raise AllocationEnvelopeError("Frozen numerical tolerances changed.")
    if "lower_cost_audit_tolerance_eur" in experiment:
        raise AllocationEnvelopeError(
            "The invalid lower-cost audit tolerance must remain absent."
        )
    physical = experiment["immutable_physical_contract"]
    expected_physical = {
        "electricity_background_percent": 30.0,
        "generator_electricity_efficiency": 0.345,
        "generator_electrical_capacity_mw": 770.0,
        "generator_total_fuel_volume_cap_nm3_h": 900000.0,
        "fixed_full_site_ng_pj_y": 8.005,
        "flexible_other_site_heat_service_envelope_pj_y": 3.07,
    }
    if any(float(physical[key]) != value for key, value in expected_physical.items()):
        raise AllocationEnvelopeError("The frozen physical allocation contract changed.")
    if (
        physical["wag_generation_yield_overrides_by_configuration"] != {}
        or bool(physical["export_allowed"])
        or bool(physical["physical_ng_bridge_changed"])
        or bool(physical["operating_rules_changed"])
        or bool(physical["route_logic_changed"])
    ):
        raise AllocationEnvelopeError("A prohibited physical or export change was enabled.")
    anchor = experiment["anchor"]
    if (
        anchor["metric_id"] != "actual_WAG_only_generator_electricity"
        or float(anchor["value_twh_y"]) != 2.528
        or "WAG_generator_electricity_mwh" not in anchor["definition"]
    ):
        raise AllocationEnvelopeError("The 2.528-TWh/y WAG-only metric changed.")


def frozen_case_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    experiment = config["experiment"]
    return [
        {
            "candidate_id": candidate["candidate_id"],
            "scenario_id": scenario["scenario_id"],
            "period_id": scenario["period_id"],
            "dataset_split": scenario["dataset_split"],
            "price_field": scenario["price_field"],
            "perfect_foresight_oracle": scenario["perfect_foresight_oracle"],
            "endpoint": endpoint,
            "case_id": (
                f"alloc__{candidate['candidate_id']}__"
                f"{scenario['scenario_id']}__{endpoint}"
            ),
        }
        for candidate in experiment["candidates"]
        for scenario in experiment["scenarios"]
        for endpoint in experiment["endpoints"]
    ]


def annual_equivalent(executed_mwh: float, executed_hours: int) -> float:
    if executed_hours <= 0:
        raise AllocationEnvelopeError("Executed hours must be positive.")
    return float(executed_mwh) * 8760.0 / float(executed_hours)


def min_normal_max_status(
    minimum: float, normal: float, maximum: float, tolerance: float
) -> str:
    return (
        "pass"
        if minimum <= normal + tolerance and normal <= maximum + tolerance
        else "fail"
    )


def _control_provenance(
    config: Mapping[str, Any],
    mechanism_config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, str]]]:
    root = (REPO_ROOT / config["experiment"]["mechanism_result_root"]).resolve()
    required = (
        "run_summary.json",
        "code_version.json",
        "input_manifest.json",
        "resolved_config.yaml",
        "scenario_matrix.csv",
        "case_status.csv",
        "candidate_scenario_metrics.csv",
    )
    if not all((root / name).is_file() for name in required):
        raise AllocationEnvelopeError("Fingerprint mechanism control output is incomplete.")
    summary = json.loads((root / "run_summary.json").read_text(encoding="utf-8"))
    code = json.loads((root / "code_version.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "input_manifest.json").read_text(encoding="utf-8"))
    resolved = yaml.safe_load((root / "resolved_config.yaml").read_text(encoding="utf-8"))
    if (
        summary.get("status") != "pass"
        or int(summary.get("model_count", -1)) != 210
        or code.get("git_commit") != EXPECTED_HEAD
        or bool(manifest.get("held_out_periods_used"))
        or resolved.get("run_id") != "steel_c5_real_anchor_mechanism_experiment_v1_20260723"
    ):
        raise AllocationEnvelopeError("Mechanism control provenance failed closed.")
    matrix = _read_csv(root / "scenario_matrix.csv")
    statuses = _read_csv(root / "case_status.csv")
    metrics = _read_csv(root / "candidate_scenario_metrics.csv")
    selected = {
        (candidate, scenario)
        for candidate in EXPECTED_CANDIDATES
        for scenario in EXPECTED_SCENARIOS
    }
    matrix_rows = [
        row for row in matrix if (row["candidate_id"], row["scenario_id"]) in selected
    ]
    if len(matrix_rows) != 4 or any(
        row["period_id"] not in EXPECTED_PERIODS
        or row["price_field"] != "y_pred"
        or row["final_held_out_selection_eligible"].lower() == "true"
        for row in matrix_rows
    ):
        raise AllocationEnvelopeError("Control matrix timestamps or split changed.")
    status_rows = [
        row for row in statuses if (row["candidate_id"], row["scenario_id"]) in selected
    ]
    if len(status_rows) != 4 or any(row["status"] != "pass" for row in status_rows):
        raise AllocationEnvelopeError("Selected mechanism controls are not passing.")
    controls = {
        (row["candidate_id"], row["scenario_id"]): row
        for row in metrics
        if (row["candidate_id"], row["scenario_id"]) in selected
        and row["configuration_id"] == C0_CONFIGURATION
    }
    if set(controls) != selected:
        raise AllocationEnvelopeError("Exactly four C0 control metrics are required.")
    repository_hashes = manifest.get("repository_files", [])
    if not repository_hashes or any(
        len(str(row.get("sha256", ""))) != 64 for row in repository_hashes
    ):
        raise AllocationEnvelopeError("Mechanism source fingerprint rows are incomplete.")
    provenance = [
        {
            "candidate_id": candidate,
            "scenario_id": scenario,
            "period_id": next(
                row["period_id"]
                for row in matrix_rows
                if row["candidate_id"] == candidate
                and row["scenario_id"] == scenario
            ),
            "status": "pass_historical_fingerprinted_control",
            "source_run_id": summary["run_id"],
            "source_git_commit": code["git_commit"],
            "source_input_manifest_sha256": _sha256(root / "input_manifest.json"),
            "source_metrics_sha256": _sha256(root / "candidate_scenario_metrics.csv"),
            "exact_mechanism_config_sha256": _sha256(
                REPO_ROOT / config["experiment"]["mechanism_config"]
            ),
            "normal_control_reoptimised": False,
            "current_builder_boundary": (
                "historical_control_cache; absent-hook semantic regression separately tested"
            ),
        }
        for candidate, scenario in sorted(selected)
    ]
    validate_mechanism_config(mechanism_config)
    return provenance, controls


def _endpoint_ready(
    directory: Path,
    *,
    expected_overrides: Mapping[str, Any],
    physical_config_sha256: str,
) -> bool:
    required = (
        "run_summary.json",
        "config_resolved.yaml",
        "input_manifest.json",
        "code_version.json",
        "rolling_model_metrics.csv",
        "executed_hourly.csv",
        "validation_checks.csv",
    )
    if not directory.is_dir() or not all((directory / name).is_file() for name in required):
        return False
    try:
        summary = json.loads((directory / "run_summary.json").read_text(encoding="utf-8"))
        resolved = yaml.safe_load((directory / "config_resolved.yaml").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "input_manifest.json").read_text(encoding="utf-8"))
        code = json.loads((directory / "code_version.json").read_text(encoding="utf-8"))
        models = _read_csv(directory / "rolling_model_metrics.csv")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return False
    c0_models = [row for row in models if row["configuration_id"] == C0_CONFIGURATION]
    return (
        summary.get("status") == "pass"
        and _mapping_sha256(resolved["scenario_overrides_applied"])
        == _mapping_sha256(expected_overrides)
        and manifest.get("config_sha256") == physical_config_sha256
        and code.get("git_commit") == EXPECTED_HEAD
        and _manifest_paths_match(manifest)
        and len(c0_models) == 7
        and all(row.get("termination_condition") == "optimal" for row in c0_models)
        and all(
            row.get("primary_cost_termination_condition") == "optimal"
            for row in c0_models
        )
        and all(
            row.get("primary_cost_best_bound_availability") == "available"
            for row in c0_models
        )
        and all(
            row.get("allocation_envelope_termination_condition") == "optimal"
            for row in c0_models
        )
        and all(
            float(row.get("allocation_envelope_cost_minus_primary_eur", "inf"))
            <= 0.01 + 1e-6
            and row.get("allocation_envelope_best_bound_audit_status") == "pass"
            and row.get(
                "allocation_envelope_normal_incumbent_min_formulation_feasible"
            )
            == "True"
            and row.get(
                "allocation_envelope_normal_incumbent_max_formulation_feasible"
            )
            == "True"
            for row in c0_models
        )
    )


def _sum(rows: list[dict[str, str]], field: str) -> float:
    return sum(float(row.get(field) or 0.0) for row in rows)


def _endpoint_metrics(
    case: Mapping[str, Any], directory: Path
) -> dict[str, Any]:
    rows = [
        row
        for row in _read_csv(directory / "executed_hourly.csv")
        if row["configuration_id"] == C0_CONFIGURATION
    ]
    hours = len(rows)
    factor = 8760.0 / hours
    wag_generator_fuel = sum(
        _sum(rows, field)
        for field in (
            "BFG_to_vattenfall_mwh",
            "COG_to_vattenfall_mwh",
            "BOFG_to_vattenfall_mwh",
        )
    )
    wag_flexible = sum(
        _sum(rows, field)
        for field in (
            "BFG_to_flexible_other_site_heat_mwh",
            "COG_to_flexible_other_site_heat_mwh",
            "BOFG_to_flexible_other_site_heat_mwh",
        )
    )
    wag_used = _sum(rows, "WAG_used")
    generator_ng = _sum(rows, "generator_named_ng_mwh")
    flexible_ng = _sum(rows, "flexible_other_site_heat_ng_mwh")
    fixed_ng = _sum(rows, "full_site_fixed_ng_component_mwh")
    exports = _sum(rows, "gross_grid_export_mwh")
    generator_electricity_separation_residuals = [
        float(row["WAG_generator_electricity_mwh"])
        + float(row["NG_generator_electricity_mwh"])
        - float(row["total_generator_electricity_mwh"])
        for row in rows
    ]
    mixed_wag_physical_columns = sorted(
        field
        for field in rows[0]
        if "mixed_wag" in field.lower() or "aggregate_wag" in field.lower()
    )
    return {
        **dict(case),
        "annual_equivalent_basis": "development_week_annual_equivalent_not_empirical_annual_result",
        "executed_hours": hours,
        "wag_generator_electricity_mwh_y": annual_equivalent(
            _sum(rows, "WAG_generator_electricity_mwh"), hours
        ),
        "wag_generator_fuel_mwh_lhv_y": wag_generator_fuel * factor,
        "wag_flexible_heat_mwh_lhv_y": wag_flexible * factor,
        "wag_mandatory_heat_mwh_lhv_y": (
            wag_used - wag_generator_fuel - wag_flexible
        )
        * factor,
        "generator_named_ng_mwh_lhv_y": generator_ng * factor,
        "flexible_named_ng_mwh_lhv_y": flexible_ng * factor,
        "fixed_named_ng_mwh_lhv_y": fixed_ng * factor,
        "total_named_ng_mwh_lhv_y": (
            generator_ng + flexible_ng + fixed_ng
        )
        * factor,
        "ng_generator_electricity_mwh_y": annual_equivalent(
            _sum(rows, "NG_generator_electricity_mwh"), hours
        ),
        "gross_electricity_demand_mwh_y": annual_equivalent(
            _sum(rows, "gross_electricity_mwh"), hours
        ),
        "internal_generation_mwh_y": annual_equivalent(
            _sum(rows, "total_generator_electricity_mwh"), hours
        ),
        "grid_import_mwh_y": annual_equivalent(
            _sum(rows, "net_grid_import_mwh"), hours
        ),
        "flare_mwh_lhv_y": annual_equivalent(_sum(rows, "WAG_flared"), hours),
        "grid_export_mwh_y": annual_equivalent(exports, hours),
        "no_export_status": "pass" if abs(exports) <= 1e-6 else "fail",
        "no_export_binding_hours": sum(
            abs(float(row.get("gross_grid_export_mwh") or 0.0)) <= 1e-9
            for row in rows
        ),
        "generator_electricity_separation_max_abs_residual_mwh": max(
            abs(value) for value in generator_electricity_separation_residuals
        ),
        "mixed_wag_physical_column_count": len(mixed_wag_physical_columns),
        "mixed_wag_physical_columns": ";".join(mixed_wag_physical_columns),
    }


def run_allocation_envelope(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    if _git_head() != EXPECTED_HEAD:
        raise AllocationEnvelopeError("Git HEAD changed from the frozen experiment commit.")
    experiment = config["experiment"]
    output = (REPO_ROOT / config["output_root"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    mechanism_config_path = (REPO_ROOT / experiment["mechanism_config"]).resolve()
    mechanism_config = load_mechanism_config(mechanism_config_path)
    provenance, controls = _control_provenance(config, mechanism_config)
    physical_config = (REPO_ROOT / experiment["physical_config"]).resolve()
    physical_config_sha256 = _sha256(physical_config)
    scratch = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / experiment["scratch_root"]).resolve()
    )
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    mechanism_experiment = mechanism_config["experiment"]
    candidates = {
        row["candidate_id"]: row for row in mechanism_experiment["candidates"]
    }
    scenarios = {
        row["scenario_id"]: row for row in mechanism_experiment["scenarios"]
    }
    periods = {
        row["period_id"]: row for row in mechanism_experiment["development_periods"]
    }
    statuses: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    window_audits: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    matrix = frozen_case_matrix(config)
    for index, case in enumerate(matrix, start=1):
        case_id = case["case_id"]
        directory = scratch / case_id
        base_overrides = _expected_case_overrides(
            case_id=case_id,
            forecast_root=forecast_root,
            scenario=scenarios[case["scenario_id"]],
            periods=periods,
            config=mechanism_config,
            candidate=candidates[case["candidate_id"]],
        )
        overrides = {
            **base_overrides,
            "lineage_role": "diagnostic_c0_cost_optimal_allocation_envelope_endpoint",
            "c0_allocation_envelope_diagnostic": {
                "enabled": True,
                "endpoint": case["endpoint"],
                "state_tolerance": float(experiment["state_tolerance"]),
            },
        }
        ready = _endpoint_ready(
            directory,
            expected_overrides=overrides,
            physical_config_sha256=physical_config_sha256,
        )
        source = "reused_current_endpoint_cache" if ready else "new_solve"
        error = ""
        case_started = time.perf_counter()
        if not ready and not aggregate_only:
            if directory.exists():
                raise AllocationEnvelopeError(
                    f"Incomplete endpoint cache preserved for inspection: {directory}"
                )
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            ready = _endpoint_ready(
                directory,
                expected_overrides=overrides,
                physical_config_sha256=physical_config_sha256,
            )
        if not ready:
            preserved_case_directory = str(
                directory.relative_to(REPO_ROOT)
            ).replace("\\", "/")
            evidence_files = (
                "run_summary.json",
                "rolling_model_metrics.csv",
                "validation_checks.csv",
                "config_resolved.yaml",
                "input_manifest.json",
                "code_version.json",
            )
            evidence = {
                name: _sha256(directory / name)
                for name in evidence_files
                if (directory / name).is_file()
            }
            statuses.append(
                {
                    **dict(case),
                    "status": "fail_closed",
                    "source": source,
                    "runtime_seconds_this_invocation": (
                        time.perf_counter() - case_started
                    ),
                    "error": error or "endpoint cache missing or failed audit",
                    "preserved_case_directory": preserved_case_directory,
                    "preserved_evidence_sha256": json.dumps(
                        evidence, sort_keys=True
                    ),
                }
            )
            _write_csv(output / "case_endpoint_status.csv", statuses)
            accepted_trajectories = sum(
                row["status"] == "pass" for row in statuses
            )
            failure_record = {
                "run_id": config["run_id"],
                "status": "incomplete_fail_closed",
                "decision": "stop_no_formulation_search",
                "failed_case_id": case_id,
                "failed_endpoint": case["endpoint"],
                "error": error or "endpoint cache missing or failed audit",
                "accepted_endpoint_trajectory_count": accepted_trajectories,
                "planned_endpoint_trajectory_count": len(matrix),
                "accepted_c0_endpoint_window_count": (
                    accepted_trajectories * int(experiment["replan_count"])
                ),
                "planned_c0_endpoint_window_count": 56,
                "repair_cycle_count": 1,
                "preserved_case_directory": preserved_case_directory,
                "preserved_evidence_sha256": evidence,
            }
            _write_json(output / "checkpoint_state.json", failure_record)
            _write_json(output / "run_summary.json", failure_record)
            raise AllocationEnvelopeError(
                f"Endpoint case failed closed: {case_id}; {error or 'cache missing'}"
            )
        statuses.append(
            {
                **dict(case),
                "status": "pass",
                "source": source,
                "runtime_seconds_this_invocation": time.perf_counter() - case_started,
                "error": "",
                "input_manifest_sha256": _sha256(
                    directory / "input_manifest.json"
                ),
                "resolved_config_sha256": _sha256(
                    directory / "config_resolved.yaml"
                ),
                "rolling_model_metrics_sha256": _sha256(
                    directory / "rolling_model_metrics.csv"
                ),
                "executed_hourly_sha256": _sha256(
                    directory / "executed_hourly.csv"
                ),
            }
        )
        _write_csv(output / "case_endpoint_status.csv", statuses)
        case_metrics = _endpoint_metrics(case, directory)
        metrics.append(case_metrics)
        models = _read_csv(directory / "rolling_model_metrics.csv")
        for row in models:
            if row["configuration_id"] != C0_CONFIGURATION:
                continue
            solver_rows.append({**dict(case), **row})
            normal_hash = row["allocation_envelope_normal_handoff_hash"]
            endpoint_hash = row["allocation_envelope_endpoint_handoff_hash"]
            window_audits.append(
                {
                    **dict(case),
                    "replan_index": row["replan_index"],
                    "primary_cost_objective_eur": row["primary_cost_objective_eur"],
                    "primary_cost_termination_condition": row[
                        "primary_cost_termination_condition"
                    ],
                    "primary_cost_best_bound_eur": row[
                        "primary_cost_best_bound_eur"
                    ],
                    "primary_cost_best_bound_availability": row[
                        "primary_cost_best_bound_availability"
                    ],
                    "normal_tie_break_cost_eur": row["tie_break_cost_objective_eur"],
                    "endpoint_cost_eur": row["allocation_envelope_cost_eur"],
                    "endpoint_minus_primary_cost_eur": row[
                        "allocation_envelope_cost_minus_primary_eur"
                    ],
                    "endpoint_minus_primary_best_bound_eur": row[
                        "allocation_envelope_cost_minus_primary_best_bound_eur"
                    ],
                    "allowed_upper_cost_tolerance_eur": 0.01,
                    "primary_objective_audit_status": (
                        "pass"
                        if float(
                            row["allocation_envelope_cost_minus_primary_eur"]
                        )
                        <= 0.01 + 1e-6
                        else "fail"
                    ),
                    "best_bound_audit_status": row[
                        "allocation_envelope_best_bound_audit_status"
                    ],
                    "normal_incumbent_min_formulation_feasible": row[
                        "allocation_envelope_normal_incumbent_min_formulation_feasible"
                    ],
                    "normal_incumbent_max_formulation_feasible": row[
                        "allocation_envelope_normal_incumbent_max_formulation_feasible"
                    ],
                    "normal_cost_minus_upper_limit_eur": row[
                        "allocation_envelope_normal_cost_minus_upper_limit_eur"
                    ],
                    "progress_optimum_deviation_t": row[
                        "production_progress_optimum_deviation_t"
                    ],
                    "normal_handoff_hash": normal_hash,
                    "endpoint_handoff_hash": endpoint_hash,
                    "max_state_residual": row[
                        "allocation_envelope_max_state_residual"
                    ],
                    "model_state_band_tolerance": row[
                        "allocation_envelope_state_tolerance"
                    ],
                    "solver_state_feasibility_tolerance": row[
                        "allocation_envelope_solver_state_feasibility_tolerance"
                    ],
                    "effective_state_tolerance": row[
                        "allocation_envelope_effective_state_tolerance"
                    ],
                    "cost_preservation_status": (
                        "pass"
                        if float(row["allocation_envelope_cost_minus_primary_eur"])
                        <= 0.01 + 1e-6
                        and row["allocation_envelope_best_bound_audit_status"]
                        == "pass"
                        else "fail"
                    ),
                    "normal_incumbent_feasibility_status": (
                        "pass"
                        if row[
                            "allocation_envelope_normal_incumbent_min_formulation_feasible"
                        ]
                        == "True"
                        and row[
                            "allocation_envelope_normal_incumbent_max_formulation_feasible"
                        ]
                        == "True"
                        else "fail"
                    ),
                    "state_preservation_status": (
                        "pass"
                        if normal_hash == endpoint_hash
                        and float(row["allocation_envelope_max_state_residual"])
                        <= float(
                            row[
                                "allocation_envelope_effective_state_tolerance"
                            ]
                        )
                        + 1e-9
                        else "fail"
                    ),
                    "endpoint_optimal_status": (
                        "pass"
                        if row["allocation_envelope_termination_condition"] == "optimal"
                        else "fail"
                    ),
                }
            )
        for row in _read_csv(directory / "validation_checks.csv"):
            validation_rows.append({**dict(case), **row})
        print(f"[{index}/{len(matrix)}] {case_id}: pass ({source})", flush=True)

    by_endpoint = {
        (row["candidate_id"], row["scenario_id"], row["endpoint"]): row
        for row in metrics
    }
    comparisons: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    tolerance = float(experiment["reporting_tolerance_mwh_y"])
    anchor_mwh_y = float(experiment["anchor"]["value_twh_y"]) * 1_000_000.0
    for candidate in EXPECTED_CANDIDATES:
        for scenario in EXPECTED_SCENARIOS:
            minimum = float(
                by_endpoint[(candidate, scenario, "min")][
                    "wag_generator_electricity_mwh_y"
                ]
            )
            maximum = float(
                by_endpoint[(candidate, scenario, "max")][
                    "wag_generator_electricity_mwh_y"
                ]
            )
            normal = float(
                controls[(candidate, scenario)][
                    "actual_wag_only_generator_electricity_mwh_y"
                ]
            )
            status = min_normal_max_status(minimum, normal, maximum, tolerance)
            comparisons.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "min_wag_generator_electricity_mwh_y": minimum,
                    "normal_control_wag_generator_electricity_mwh_y": normal,
                    "max_wag_generator_electricity_mwh_y": maximum,
                    "min_normal_max_status": status,
                    "normal_control_boundary": "historical_fingerprinted_mechanism_cache",
                    "normal_wag_generator_fuel_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_to_generators_mwh_lhv_y"],
                    "normal_wag_flexible_heat_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_to_flexible_heat_mwh_lhv_y"],
                    "normal_wag_mandatory_heat_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_to_mandatory_process_heat_mwh_lhv_y"],
                    "normal_generator_named_ng_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["generator_named_ng_mwh_lhv_y"],
                    "normal_flexible_named_ng_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["flexible_named_ng_mwh_lhv_y"],
                    "normal_fixed_named_ng_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["fixed_named_ng_mwh_lhv_y"],
                    "normal_ng_generator_electricity_mwh_y": controls[
                        (candidate, scenario)
                    ]["ng_generated_electricity_mwh_y"],
                    "reporting_tolerance_mwh_y": tolerance,
                }
            )
            inside = minimum - tolerance <= anchor_mwh_y <= maximum + tolerance
            anchor_position = (
                "inside_cost_optimal_envelope"
                if inside
                else "below_minimum"
                if anchor_mwh_y < minimum - tolerance
                else "above_maximum"
            )
            anchors.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "metric_id": experiment["anchor"]["metric_id"],
                    "anchor_mwh_y": anchor_mwh_y,
                    "minimum_mwh_y": minimum,
                    "maximum_mwh_y": maximum,
                    "inside_cost_optimal_allocation_envelope": inside,
                    "position_relative_to_cost_optimal_envelope": anchor_position,
                    "gap_below_minimum_mwh_y": max(
                        0.0, minimum - anchor_mwh_y
                    ),
                    "gap_above_maximum_mwh_y": max(0.0, anchor_mwh_y - maximum),
                    "status": anchor_position,
                }
            )
    endpoint_validation_failures = [
        row for row in validation_rows if row.get("status") not in {"pass", "not_applicable"}
    ]
    preservation_failures = [
        row
        for row in window_audits
        if row["cost_preservation_status"] != "pass"
        or row["state_preservation_status"] != "pass"
        or row["normal_incumbent_feasibility_status"] != "pass"
        or row["endpoint_optimal_status"] != "pass"
        or row["primary_cost_termination_condition"] != "optimal"
        or row["primary_cost_best_bound_availability"] != "available"
    ]
    comparison_failures = [
        row for row in comparisons if row["min_normal_max_status"] != "pass"
    ]
    guardrails = [
        {
            "guardrail": "all_primary_procurement_cost_models_optimal_with_bound",
            "status": (
                "pass"
                if len(solver_rows) == 56
                and all(
                    row["primary_cost_termination_condition"] == "optimal"
                    and row["primary_cost_best_bound_availability"] == "available"
                    for row in solver_rows
                )
                else "fail"
            ),
            "evidence": "per_window_preservation_audit.csv",
        },
        {
            "guardrail": "all_endpoint_models_optimal",
            "status": (
                "pass"
                if len(solver_rows) == 56
                and all(
                    row["allocation_envelope_termination_condition"] == "optimal"
                    for row in solver_rows
                )
                else "fail"
            ),
            "evidence": "56 C0 endpoint windows",
        },
        {
            "guardrail": "cost_progress_and_all_carried_states_preserved",
            "status": "pass" if not preservation_failures else "fail",
            "evidence": f"failure_count={len(preservation_failures)}",
        },
        {
            "guardrail": "existing_physical_validation_checks",
            "status": "pass" if not endpoint_validation_failures else "fail",
            "evidence": f"failure_count={len(endpoint_validation_failures)}",
        },
        {
            "guardrail": "no_export_all_endpoints",
            "status": (
                "pass"
                if all(row["no_export_status"] == "pass" for row in metrics)
                else "fail"
            ),
            "evidence": "endpoint_annual_equivalent_metrics.csv",
        },
        {
            "guardrail": "wag_only_and_ng_generated_electricity_exactly_separate",
            "status": (
                "pass"
                if all(
                    row[
                        "generator_electricity_separation_max_abs_residual_mwh"
                    ]
                    <= 1e-9
                    for row in metrics
                )
                else "fail"
            ),
            "evidence": "WAG_generator_electricity + NG_generator_electricity = total_generator_electricity",
        },
        {
            "guardrail": "no_mixed_wag_physical_use",
            "status": (
                "pass"
                if all(row["mixed_wag_physical_column_count"] == 0 for row in metrics)
                else "fail"
            ),
            "evidence": "executed_hourly.csv schema remains carrier-specific BFG/COG/BOFG",
        },
        {
            "guardrail": "residual_energy_not_a_physical_or_cost_input",
            "status": (
                "pass"
                if sum(
                    row.get("check_id")
                    == "residual_energy_excluded_from_future_objective"
                    and row.get("status") == "pass"
                    for row in validation_rows
                )
                == len(matrix)
                else "fail"
            ),
            "evidence": "validation_checks.csv",
        },
        {
            "guardrail": "min_normal_max_order",
            "status": "pass" if not comparison_failures else "fail",
            "evidence": f"failure_count={len(comparison_failures)}",
        },
        {
            "guardrail": "held_out_or_oracle_excluded",
            "status": "pass",
            "evidence": "4 validation/y_pred primary cases; no TEST/y_true/oracle",
        },
        {
            "guardrail": "exact_frozen_case_matrix",
            "status": "pass" if len(matrix) == 8 else "fail",
            "evidence": "2 candidates x 2 validation cases x 2 endpoints",
        },
    ]
    failures = [row for row in guardrails if row["status"] != "pass"]
    _write_csv(output / "primary_control_provenance.csv", provenance)
    _write_csv(output / "per_window_preservation_audit.csv", window_audits)
    _write_csv(output / "endpoint_annual_equivalent_metrics.csv", metrics)
    _write_csv(output / "allocation_envelope_comparison.csv", comparisons)
    _write_csv(output / "anchor_coverage.csv", anchors)
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "solver_runtime_model_metrics.csv", solver_rows)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    repository_files = (
        config_file,
        mechanism_config_path,
        physical_config,
        Path(__file__).resolve(),
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_c0_wag_ng_allocation_envelope.py",
    )
    _write_json(
        output / "input_manifest.json",
        {
            "run_id": config["run_id"],
            "candidate_count": 2,
            "scenario_count": 2,
            "endpoint_count": 2,
            "endpoint_trajectory_count": 8,
            "c0_endpoint_window_count": 56,
            "held_out_periods_used": False,
            "forecast_run_root_persisted": False,
            "repository_files": [
                {
                    "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "sha256": _sha256(path),
                }
                for path in repository_files
            ],
            "mechanism_control_output_fingerprints": {
                "input_manifest_sha256": provenance[0][
                    "source_input_manifest_sha256"
                ],
                "metrics_sha256": provenance[0]["source_metrics_sha256"],
            },
            "endpoint_cache_fingerprints": [
                {
                    "case_id": row["case_id"],
                    "input_manifest_sha256": row["input_manifest_sha256"],
                    "resolved_config_sha256": row["resolved_config_sha256"],
                    "rolling_model_metrics_sha256": row[
                        "rolling_model_metrics_sha256"
                    ],
                    "executed_hourly_sha256": row["executed_hourly_sha256"],
                }
                for row in statuses
            ],
        },
    )
    _write_json(
        output / "code_version.json",
        {"git_commit": _git_head(), "working_tree_fingerprinted": True},
    )
    status = "pass" if not failures else "fail"
    decision = (
        "anchor_inside_all_primary_cost_optimal_allocation_envelopes_pending_Tata_policy"
        if all(row["inside_cost_optimal_allocation_envelope"] for row in anchors)
        else "anchor_outside_one_or_more_cost_optimal_allocation_envelopes"
    )
    summary = {
        "run_id": config["run_id"],
        "status": status,
        "decision": decision,
        "primary_control_count": 4,
        "endpoint_trajectory_count": 8,
        "replans_per_trajectory": 7,
        "c0_endpoint_window_count": len(solver_rows),
        "optimal_c0_endpoint_window_count": sum(
            row["allocation_envelope_termination_condition"] == "optimal"
            for row in solver_rows
        ),
        "guardrail_failure_count": len(failures),
        "anchor_inside_case_count": sum(
            row["inside_cost_optimal_allocation_envelope"] for row in anchors
        ),
        "repair_cycle_count": 1,
        "candidate_promotion_status": "not_promoted_diagnostic_only",
        "runtime_seconds_this_invocation": time.perf_counter() - started,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": status,
            "completed_endpoint_trajectory_count": len(statuses),
            "failed_endpoint_trajectory_count": 0 if status == "pass" else len(failures),
            "held_out_periods_used": False,
            "solver_invoked": any(row["source"] == "new_solve" for row in statuses),
            "repair_cycle_count": 1,
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "status": status,
            "retention_status": "local",
            "git_eligible": False,
        },
    )
    (output / "README.md").write_text(
        "# C0 WAG/NG cost-optimal allocation envelope\n\n"
        "Four fingerprinted mechanism controls are compared with eight newly "
        "optimised min/max C0 endpoint trajectories (seven replans each). Each "
        "endpoint preserves the normal progress optimum, represented procurement "
        "cost under the one-sided EUR 0.01/window upper constraint, executed "
        "production and all four carried C0 "
        "inventories. Annual equivalents scale one DEVELOPMENT validation week; "
        "they are not empirical annual results. The endpoint is pure WAG-only "
        "generator electricity and does not target the 2.528-TWh/y anchor. The "
        "primary cost stage must be optimal, and every endpoint is audited against "
        "both its primary objective and the solver-reported best bound; no lower-cost "
        "constraint is imposed.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a diagnostic/emulation sensitivity, not calibration or candidate promotion.\n"
        "- Controls are fingerprinted historical mechanism outputs, not reoptimisable models; the absent-hook path has a direct regression test.\n"
        "- Only validation y_pred periods are used; TEST, y_true, oracle, bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR are excluded.\n"
        "- Residual electricity and NG remain reporting-only and unpriced.\n"
        "- If the real anchor is inside, allocation remains non-identifiable pending Tata policy evidence.\n",
        encoding="utf-8",
    )
    if failures:
        raise AllocationEnvelopeError(
            f"Allocation-envelope acceptance failed: {len(failures)} guardrail(s)."
        )
    return summary
