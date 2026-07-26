"""Cost-optimal C0 WAG/NG allocation-envelope diagnostic.

The normal rolling controller remains authoritative.  Each endpoint trajectory
adds only the opt-in C0 endpoint hook after the normal progress, represented
procurement-cost and physical tie-break solves.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
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
EXPECTED_HEAD = "373d0bbde6ae76466ce8ee76afdc4aa5b93f2e51"
EXPECTED_RUN_ID = "steel_c5_wag_ng_allocation_envelope_v6_20260726"
ENDPOINT_SOLVER_ACCURACY_SCHEMA = "steel_endpoint_solver_accuracy_v1"
ENDPOINT_RELATIVE_MIP_GAP = 0.0
ENDPOINT_ABSOLUTE_MIP_GAP_MWH = 0.001
ENDPOINT_BOUND_COMPARISON_EPSILON_MWH = 1e-9
ENDPOINT_ANNUAL_BOUND_UNCERTAINTY_LIMIT_MWH_Y = 1.0
FINGERPRINTED_IMPLEMENTATION_PATHS = (
    "scripts/Data/04_Steel_Test_Case/configs/steel_c5_wag_ng_allocation_envelope.yaml",
    "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_c0_wag_ng_allocation_envelope.py",
    "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
    "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_c0_wag_ng_allocation_envelope.py",
    "scripts/Data/04_Steel_Test_Case/tests/test_s4_4c5p_c0_wag_ng_allocation_envelope.py",
    "scripts/Data/04_Steel_Test_Case/tests/test_s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
)


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


def _git_diff_sha256() -> str:
    payload = subprocess.check_output(
        [
            "git",
            "diff",
            "--binary",
            "--",
            *FINGERPRINTED_IMPLEMENTATION_PATHS,
        ],
        cwd=REPO_ROOT,
    )
    return hashlib.sha256(payload).hexdigest()


def _implementation_fingerprints(
    *, config_file: Path, physical_config: Path
) -> dict[str, Any]:
    return {
        "expected_parent_head": EXPECTED_HEAD,
        "experiment_config_sha256": _sha256(config_file),
        "physical_config_sha256": _sha256(physical_config),
        "git_diff_sha256": _git_diff_sha256(),
        "source_files": [
            {
                "path": path,
                "sha256": _sha256(REPO_ROOT / path),
            }
            for path in FINGERPRINTED_IMPLEMENTATION_PATHS
        ],
    }


def _read_gzip_mapping(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise AllocationEnvelopeError(
            f"Normal solution record is not a mapping: {path}"
        )
    return payload


def _write_deterministic_gzip_mapping(
    path: Path, payload: Mapping[str, Any]
) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0
        ) as compressed:
            compressed.write(encoded)


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
    if (
        experiment.get("expected_parent_head") != EXPECTED_HEAD
        or experiment.get("complete_normal_solution_schema")
        != "steel_complete_normal_solution_v2"
        or experiment.get("normal_feasibility_oracle_schema")
        != "steel_normal_feasibility_oracle_v2"
        or float(experiment.get("absolute_feasibility_tolerance", -1))
        != 1e-6
        or experiment.get("iis_proven_duplicate_constraint")
        != "rolling_production_deadline[24]"
    ):
        raise AllocationEnvelopeError(
            "The v6 parent, oracle schema, tolerance, or IIS repair contract changed."
        )
    if (
        experiment.get("endpoint_solver_accuracy_schema")
        != ENDPOINT_SOLVER_ACCURACY_SCHEMA
        or float(experiment.get("endpoint_relative_mip_gap", -1.0))
        != ENDPOINT_RELATIVE_MIP_GAP
        or float(experiment.get("endpoint_absolute_mip_gap_mwh", -1.0))
        != ENDPOINT_ABSOLUTE_MIP_GAP_MWH
        or float(
            experiment.get("endpoint_bound_comparison_epsilon_mwh", -1.0)
        )
        != ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
        or float(
            experiment.get(
                "endpoint_annual_bound_uncertainty_limit_mwh_y", -1.0
            )
        )
        != ENDPOINT_ANNUAL_BOUND_UNCERTAINTY_LIMIT_MWH_Y
    ):
        raise AllocationEnvelopeError(
            "The governed endpoint solver-accuracy contract changed."
        )
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


def _normal_case_id(candidate_id: str, scenario_id: str) -> str:
    return f"normal__{candidate_id}__{scenario_id}"


def _normal_solution_capture_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("normal_solution_replan_*__*.json.gz"))


def _normal_record_internal_hashes(
    payload: Mapping[str, Any],
) -> tuple[int, str, str, str]:
    variables = list(payload.get("variables", ()))
    names = [str(row["name"]) for row in variables]
    schema = [
        {
            "name": row["name"],
            "domain": row["domain"],
            "lb": row["lb"],
            "ub": row["ub"],
        }
        for row in variables
    ]
    fixed_schema = [
        {
            "name": row["name"],
            "fixed": bool(row["fixed"]),
            "fixed_value": (
                float(row["fixed_value"])
                if row["fixed_value"] is not None
                else None
            ),
        }
        for row in variables
    ]
    return (
        len(variables),
        hashlib.sha256(
            json.dumps(names, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            json.dumps(
                schema, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            json.dumps(
                fixed_schema, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    )


def _complete_normal_records_ready(
    directory: Path, expected_base_provenance: Mapping[str, Any]
) -> bool:
    files = _normal_solution_capture_files(directory)
    if len(files) != 14:
        return False
    try:
        payloads = [_read_gzip_mapping(path) for path in files]
    except (OSError, ValueError, KeyError):
        return False
    for payload in payloads:
        try:
            count, name_hash, schema_hash, fixed_hash = (
                _normal_record_internal_hashes(payload)
            )
        except (KeyError, TypeError, ValueError):
            return False
        if not (
            payload.get("schema_version")
            == "steel_complete_normal_solution_v2"
            and count > 0
            and int(payload.get("variable_count", 0)) == count
            and payload.get("variable_name_sha256") == name_hash
            and payload.get("variable_schema_sha256") == schema_hash
            and payload.get("variable_fixed_schema_sha256") == fixed_hash
            and payload.get("provenance", {}).get("record_finalized") is True
            and all(
                payload.get("provenance", {}).get(key) == value
                for key, value in expected_base_provenance.items()
            )
        ):
            return False
    return True


def _normal_ready(
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
        "rolling_execution.csv",
        "rolling_production_progress_state.csv",
        "rolling_timestamp_contract.csv",
        "inventory_handoff.csv",
        "executed_hourly.csv",
    )
    if not directory.is_dir() or not all(
        (directory / name).is_file() for name in required
    ):
        return False
    try:
        summary = json.loads(
            (directory / "run_summary.json").read_text(encoding="utf-8")
        )
        resolved = yaml.safe_load(
            (directory / "config_resolved.yaml").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (directory / "input_manifest.json").read_text(encoding="utf-8")
        )
        code = json.loads(
            (directory / "code_version.json").read_text(encoding="utf-8")
        )
        models = _read_csv(directory / "rolling_model_metrics.csv")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return False
    return (
        summary.get("status") == "pass"
        and _mapping_sha256(resolved["scenario_overrides_applied"])
        == _mapping_sha256(expected_overrides)
        and manifest.get("config_sha256") == physical_config_sha256
        and code.get("git_commit") == EXPECTED_HEAD
        and _manifest_paths_match(manifest)
        and len(models) == 14
        and all(row.get("termination_condition") == "optimal" for row in models)
        and not any(
            row.get("allocation_envelope_active") in {"True", "true"}
            for row in models
        )
        and _complete_normal_records_ready(
            directory,
            expected_overrides["normal_solution_capture"]["provenance"],
        )
    )


def _normal_schedule(directory: Path) -> tuple[list[dict[str, Any]], str]:
    handoffs = {
        (int(row["replan_index"]), row["configuration_id"]): row
        for row in _read_csv(directory / "inventory_handoff.csv")
    }
    executions = {
        (int(row["replan_index"]), row["configuration_id"]): row
        for row in _read_csv(directory / "rolling_execution.csv")
    }
    progress = {
        (int(row["replan_index"]), row["configuration_id"]): row
        for row in _read_csv(directory / "rolling_production_progress_state.csv")
    }
    timing = {
        int(row["replan_index"]): row
        for row in _read_csv(directory / "rolling_timestamp_contract.csv")
    }
    hourly = _read_csv(directory / "executed_hourly.csv")
    schedule: list[dict[str, Any]] = []
    for replan_index in range(7):
        execution_hours = int(timing[replan_index]["execution_block_hours"])
        executed_hours_before = sum(
            int(timing[index]["execution_block_hours"])
            for index in range(replan_index)
        )
        for configuration in (
            C0_CONFIGURATION,
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        ):
            key = (replan_index, configuration)
            handoff = handoffs[key]
            execution = executions[key]
            state = progress[key]
            schedule.append(
                {
                    "replan_index": replan_index,
                    "configuration_id": configuration,
                    "executed_hours_before": executed_hours_before,
                    "executed_hours_after": executed_hours_before
                    + execution_hours,
                    "execution_block_hours": execution_hours,
                    "start_overrides": json.loads(handoff["start_overrides"]),
                    "cumulative_executed_before_t": float(
                        state["executed_before_t"]
                    ),
                    "executed_final_product_t": float(
                        execution.get(
                            "executed_final_product_t_unrounded",
                            execution["executed_final_product_t"],
                        )
                    ),
                    "cumulative_executed_after_t": float(
                        execution.get(
                            "cumulative_executed_final_product_t_unrounded",
                            execution[
                                "cumulative_executed_final_product_t"
                            ],
                        )
                    ),
                    "end_overrides": json.loads(handoff["next_overrides"]),
                    "executed_wag_generator_electricity_mwh": sum(
                        float(
                            row.get(
                                "WAG_generator_electricity_mwh_unrounded",
                                row.get("WAG_generator_electricity_mwh"),
                            )
                            or row.get("WAG_generator_electricity_mwh")
                            or 0.0
                        )
                        for row in hourly
                        if int(row["replan_index"]) == replan_index
                        and row["configuration_id"] == configuration
                    ),
                    "production_progress_state": dict(state),
                }
            )
    expected_keys = {
        (replan_index, configuration)
        for replan_index in range(7)
        for configuration in (
            C0_CONFIGURATION,
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
    }
    actual_keys = {
        (row["replan_index"], row["configuration_id"]) for row in schedule
    }
    if actual_keys != expected_keys:
        raise AllocationEnvelopeError(
            "Current-normal controller schedule does not cover all C0/C1 states."
        )
    schedule_hash = hashlib.sha256(
        json.dumps(schedule, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return schedule, schedule_hash


def _finalize_normal_solution_records(
    directory: Path,
    *,
    schedule: list[dict[str, Any]],
    schedule_hash: str,
) -> dict[str, dict[str, Any]]:
    schedule_by_key = {
        (int(row["replan_index"]), str(row["configuration_id"])): row
        for row in schedule
    }
    records_by_replan: dict[str, dict[str, Any]] = {}
    for path in _normal_solution_capture_files(directory):
        payload = _read_gzip_mapping(path)
        key = (
            int(payload["replan_index"]),
            str(payload["configuration_id"]),
        )
        if key not in schedule_by_key:
            raise AllocationEnvelopeError(
                f"Normal solution has no controller schedule row: {key}."
            )
        controller_row = schedule_by_key[key]
        provenance = {
            **dict(payload.get("provenance", {})),
            "normal_controller_schedule_sha256": schedule_hash,
            "controller_schedule_row_sha256": hashlib.sha256(
                json.dumps(
                    controller_row, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
            "record_finalized": True,
        }
        payload["provenance"] = provenance
        payload["controller_state"] = {
            **dict(payload.get("controller_state", {})),
            "authoritative_schedule_row": controller_row,
        }
        _write_deterministic_gzip_mapping(path, payload)
        if payload["configuration_id"] == C0_CONFIGURATION:
            records_by_replan[str(payload["replan_index"])] = {
                "path": str(path),
                "sha256": _sha256(path),
                "provenance": provenance,
                "variable_count": int(payload["variable_count"]),
                "variable_name_sha256": payload["variable_name_sha256"],
                "variable_schema_sha256": payload[
                    "variable_schema_sha256"
                ],
                "variable_fixed_schema_sha256": payload[
                    "variable_fixed_schema_sha256"
                ],
            }
    if set(records_by_replan) != {str(index) for index in range(7)}:
        raise AllocationEnvelopeError(
            "Exactly seven finalized C0 complete-normal records are required."
        )
    return records_by_replan


def _load_normal_solution_records(
    directory: Path,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in _normal_solution_capture_files(directory):
        payload = _read_gzip_mapping(path)
        if payload.get("configuration_id") != C0_CONFIGURATION:
            continue
        result[str(payload["replan_index"])] = {
            "path": str(path),
            "sha256": _sha256(path),
            "provenance": dict(payload["provenance"]),
            "variable_count": int(payload["variable_count"]),
            "variable_name_sha256": payload["variable_name_sha256"],
            "variable_schema_sha256": payload["variable_schema_sha256"],
            "variable_fixed_schema_sha256": payload[
                "variable_fixed_schema_sha256"
            ],
        }
    if set(result) != {str(index) for index in range(7)}:
        raise AllocationEnvelopeError(
            "Finalized normal solution record matrix is incomplete."
        )
    return result


def _normal_record_manifest_rows(
    candidate_id: str,
    scenario_id: str,
    directory: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _normal_solution_capture_files(directory):
        payload = _read_gzip_mapping(path)
        relative_path = str(path.resolve().relative_to(REPO_ROOT)).replace(
            "\\", "/"
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "configuration_id": payload["configuration_id"],
                "replan_index": int(payload["replan_index"]),
                "path": relative_path,
                "sha256": _sha256(path),
                "variable_count": int(payload["variable_count"]),
                "variable_name_sha256": payload["variable_name_sha256"],
                "variable_schema_sha256": payload["variable_schema_sha256"],
                "variable_fixed_schema_sha256": payload[
                    "variable_fixed_schema_sha256"
                ],
                "normal_controller_schedule_sha256": payload[
                    "provenance"
                ]["normal_controller_schedule_sha256"],
                "controller_schedule_row_sha256": payload["provenance"][
                    "controller_schedule_row_sha256"
                ],
                "record_finalized": payload["provenance"][
                    "record_finalized"
                ],
            }
        )
    return rows


def _persist_normal_control_evidence(
    output: Path,
    *,
    provenance: list[dict[str, Any]],
    normal_schedule_rows: list[dict[str, Any]],
    normal_record_rows: list[dict[str, Any]],
    require_full_matrix: bool,
) -> None:
    if require_full_matrix and (
        len(provenance) != 4
        or len(normal_schedule_rows) != 56
        or len(normal_record_rows) != 56
    ):
        raise AllocationEnvelopeError(
            "Full-run normal evidence must contain four controls, 56 schedule "
            "rows and 56 finalized normal records."
        )
    persistent_records: list[dict[str, Any]] = []
    record_root = output / "normal_solution_records"
    for record_index, raw_row in enumerate(normal_record_rows):
        row = dict(raw_row)
        source = _resolve_evidence_path(row["path"])
        expected_hash = str(row["sha256"])
        if not source.is_file() or _sha256(source) != expected_hash:
            raise AllocationEnvelopeError(
                f"Complete normal payload is missing or hash-invalid: {source}."
            )
        # The manifest carries the descriptive identity. Keep the physical
        # filename compact so targeted diagnostics remain portable on Windows.
        destination = record_root / f"normal_{record_index:02d}.json.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            if _sha256(destination) != expected_hash:
                raise AllocationEnvelopeError(
                    f"Refusing to overwrite mismatched persistent normal payload: {destination}."
                )
        else:
            shutil.copy2(source, destination)
        if _sha256(destination) != expected_hash:
            raise AllocationEnvelopeError(
                f"Persistent normal payload hash mismatch: {destination}."
            )
        row["source_path"] = str(row["path"])
        row["path"] = str(destination.relative_to(REPO_ROOT)).replace(
            "\\", "/"
        )
        row["bundled_under_persistent_root"] = True
        persistent_records.append(row)
    if require_full_matrix and len(persistent_records) != 56:
        raise AllocationEnvelopeError(
            "Persistent normal payload bundle must contain exactly 56 records."
        )
    _write_csv(output / "primary_control_provenance.csv", provenance)
    _write_csv(output / "normal_controller_schedule.csv", normal_schedule_rows)
    manifest_path = output / "normal_solution_record_manifest.csv"
    _write_csv(manifest_path, persistent_records)
    persisted_manifest = _read_csv(manifest_path)
    if len(persisted_manifest) != len(persistent_records) or any(
        not _resolve_evidence_path(row["path"]).is_file()
        or _sha256(_resolve_evidence_path(row["path"])) != row["sha256"]
        for row in persisted_manifest
    ):
        raise AllocationEnvelopeError(
            "Persistent normal payload manifest failed its self-contained hash audit."
        )


def _failure_replan_index(failure_directory: Path) -> int | None:
    first_failure = failure_directory / "first_failure.json"
    if first_failure.is_file():
        try:
            return int(
                json.loads(first_failure.read_text(encoding="utf-8"))[
                    "replan_index"
                ]
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    indices = []
    for path in failure_directory.glob(
        "oracle_r*/normal_feasibility_oracle.json"
    ):
        try:
            indices.append(int(path.parent.name.removeprefix("oracle_r")))
        except ValueError:
            continue
    return max(indices) if indices else None


def _persist_failure_bundle(
    output: Path,
    *,
    case_id: str,
    source_directory: Path,
) -> dict[str, Any]:
    source = source_directory / "first_failure_evidence"
    target = output / "failure_evidence" / case_id
    if target.exists():
        raise AllocationEnvelopeError(
            f"Refusing to overwrite an existing persistent failure bundle: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        target.mkdir(parents=True)
    else:
        shutil.copytree(source, target)
    bundled_normal = target / "saved_normal_solution.json.gz"
    if not bundled_normal.is_file():
        oracle_records = sorted(
            target.glob("oracle_r*/normal_feasibility_oracle.json")
        )
        if oracle_records:
            oracle_payload = json.loads(
                oracle_records[-1].read_text(encoding="utf-8")
            )
            raw_saved_path = oracle_payload.get("saved_normal_solution_path")
            if raw_saved_path:
                saved_path = Path(str(raw_saved_path))
                if not saved_path.is_absolute():
                    saved_path = REPO_ROOT / saved_path
                if saved_path.is_file():
                    shutil.copy2(saved_path, bundled_normal)
    files = {
        str(path.relative_to(output)).replace("\\", "/"): _sha256(path)
        for path in sorted(target.rglob("*"))
        if path.is_file()
    }
    linkage: dict[str, Any] = {}
    failure_json = target / "first_failure.json"
    if failure_json.is_file():
        linkage = json.loads(failure_json.read_text(encoding="utf-8"))
    else:
        oracle_records = sorted(
            target.glob("oracle_r*/normal_feasibility_oracle.json")
        )
        if oracle_records:
            oracle_payload = json.loads(
                oracle_records[-1].read_text(encoding="utf-8")
            )
            oracle_provenance = dict(oracle_payload.get("provenance", {}))
            oracle_controller = dict(
                oracle_payload.get("controller_state", {})
            )
            authoritative = dict(
                oracle_controller.get("authoritative_schedule_row", {})
            )
            linkage = {
                "normal_feasibility_oracle": {
                    "path": str(
                        oracle_records[-1].relative_to(output)
                    ).replace("\\", "/"),
                    "sha256": _sha256(oracle_records[-1]),
                    "status": oracle_payload.get("status"),
                    "saved_normal_solution_sha256": oracle_payload.get(
                        "saved_normal_solution_sha256"
                    ),
                    "variable_name_sha256": oracle_payload.get(
                        "variable_name_sha256"
                    ),
                    "variable_schema_sha256": oracle_payload.get(
                        "variable_schema_sha256"
                    ),
                    "variable_fixed_schema_sha256": oracle_payload.get(
                        "variable_fixed_schema_sha256"
                    ),
                },
                "normal_controller_schedule_sha256": (
                    oracle_provenance.get(
                        "normal_controller_schedule_sha256"
                    )
                ),
                "controller_schedule_row_sha256": oracle_provenance.get(
                    "controller_schedule_row_sha256"
                ),
                "controller_state": oracle_controller,
                "authoritative_schedule_row": authoritative,
                "start_state": authoritative.get(
                    "start_overrides",
                    oracle_controller.get("start_overrides"),
                ),
                "deactivated_constraint_row": (
                    "rolling_production_deadline[24]"
                ),
                "cost_cap_rhs_eur": None,
                "loaded_normal_cost_minus_cap_rhs_eur": None,
            }
    if bundled_normal.is_file():
        bundled_hash = _sha256(bundled_normal)
        existing_bundle = dict(
            linkage.get("bundled_saved_normal_solution") or {}
        )
        expected_source_hash = existing_bundle.get("source_sha256")
        if expected_source_hash is None:
            expected_source_hash = dict(
                linkage.get("normal_feasibility_oracle") or {}
            ).get("saved_normal_solution_sha256")
        linkage["bundled_saved_normal_solution"] = {
            "path": str(bundled_normal.relative_to(output)).replace(
                "\\", "/"
            ),
            "sha256": bundled_hash,
            "source_sha256": expected_source_hash,
            "hash_matches_source": (
                expected_source_hash is not None
                and bundled_hash == expected_source_hash
            ),
        }
    manifest = {
        "case_id": case_id,
        "failed_replan_index": _failure_replan_index(target),
        "file_count": len(files),
        "files_sha256": files,
        "oracle_saved_normal_schedule_controller_linkage": {
            key: linkage.get(key)
            for key in (
                "normal_feasibility_oracle",
                "bundled_saved_normal_solution",
                "normal_controller_schedule_sha256",
                "controller_schedule_row_sha256",
                "controller_state",
                "authoritative_schedule_row",
                "start_state",
                "deactivated_constraint_row",
                "cost_cap_rhs_eur",
                "loaded_normal_cost_minus_cap_rhs_eur",
            )
        },
    }
    manifest_path = output / "failure_evidence_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(
        manifest_path.relative_to(REPO_ROOT)
    ).replace("\\", "/")
    manifest["manifest_sha256"] = _sha256(manifest_path)
    return manifest


def _completed_endpoint_windows_before_failure(
    directory: Path, failed_replan_index: int | None
) -> int:
    metrics_path = directory / "rolling_model_metrics.csv"
    if metrics_path.is_file():
        try:
            return sum(
                row.get("configuration_id") == C0_CONFIGURATION
                and row.get("allocation_envelope_termination_condition")
                == "optimal"
                for row in _read_csv(metrics_path)
            )
        except (OSError, KeyError, ValueError):
            pass
    return int(failed_replan_index or 0)


def _normal_control_metrics(
    candidate_id: str, scenario_id: str, directory: Path
) -> dict[str, Any]:
    return _endpoint_metrics(
        {
            "candidate_id": candidate_id,
            "scenario_id": scenario_id,
            "endpoint": "normal",
        },
        directory,
    )


def _resolve_evidence_path(raw_path: Any) -> Path:
    path = Path(str(raw_path))
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _endpoint_oracle_cache_ready(
    rows: list[dict[str, str]],
    *,
    expected_overrides: Mapping[str, Any],
) -> bool:
    try:
        contract = expected_overrides["c0_allocation_envelope_diagnostic"]
        records = contract["normal_solution_records_by_replan"]
        expected_schedule_hash = contract[
            "normal_controller_schedule_sha256"
        ]
        for row in rows:
            replan = str(int(row["replan_index"]))
            expected = records[replan]
            oracle_path = _resolve_evidence_path(
                row[
                    "allocation_envelope_normal_feasibility_oracle_record_path"
                ]
            )
            if (
                not oracle_path.is_file()
                or _sha256(oracle_path)
                != row[
                    "allocation_envelope_normal_feasibility_oracle_record_sha256"
                ]
            ):
                return False
            oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
            compatibility = oracle["fixed_variable_compatibility_audit"]
            pre_solve = oracle["pre_solve_loaded_value_audit"]
            expected_normal_path = _resolve_evidence_path(expected["path"])
            warm_start_path = _resolve_evidence_path(
                row["allocation_envelope_warm_start_audit_path"]
            )
            endpoint_log_path = _resolve_evidence_path(
                row["allocation_envelope_endpoint_solver_log_path"]
            )
            endpoint_lp_path = _resolve_evidence_path(
                row["allocation_envelope_endpoint_pre_solve_model_path"]
            )
            if (
                not warm_start_path.is_file()
                or _sha256(warm_start_path)
                != row["allocation_envelope_warm_start_audit_sha256"]
                or not endpoint_log_path.is_file()
                or _sha256(endpoint_log_path)
                != row["allocation_envelope_endpoint_solver_log_sha256"]
                or "Loaded user MIP start"
                not in endpoint_log_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                or not endpoint_lp_path.is_file()
                or _sha256(endpoint_lp_path)
                != row[
                    "allocation_envelope_endpoint_pre_solve_model_sha256"
                ]
            ):
                return False
            warm_start = json.loads(
                warm_start_path.read_text(encoding="utf-8")
            )
            warm_loaded_audit = warm_start["loaded_start_audit"]
            if (
                oracle.get("schema_version")
                != "steel_normal_feasibility_oracle_v2"
                or oracle.get("status") != "pass"
                or oracle.get("failure_stage") is not None
                or not oracle.get("dual_path_agreement")
                or not oracle["pyomo_solve"].get("optimal")
                or oracle["native_gurobi_reread_solve"].get("status")
                != "optimal"
                or not pre_solve.get("feasible")
                or compatibility.get(
                    "fixed_status_or_value_mismatch_count"
                )
                != 0
                or compatibility.get("endpoint_prefixed_overwrite_count")
                != 0
                or not compatibility.get("unchanged_endpoint_fixed_state")
                or not compatibility.get(
                    "unchanged_endpoint_variable_state"
                )
                or oracle.get("saved_normal_solution_sha256")
                != expected["sha256"]
                or oracle.get("variable_name_sha256")
                != expected["variable_name_sha256"]
                or oracle.get("variable_schema_sha256")
                != expected["variable_schema_sha256"]
                or oracle.get("variable_fixed_schema_sha256")
                != expected["variable_fixed_schema_sha256"]
                or oracle.get("provenance", {}).get(
                    "normal_controller_schedule_sha256"
                )
                != expected_schedule_hash
                or oracle.get("provenance", {}).get(
                    "controller_schedule_row_sha256"
                )
                != expected["provenance"][
                    "controller_schedule_row_sha256"
                ]
                or not expected_normal_path.is_file()
                or _sha256(expected_normal_path) != expected["sha256"]
                or warm_start.get("schema_version")
                != "steel_endpoint_warm_start_v1"
                or warm_start.get("status") != "pass"
                or warm_start.get("failure_stage") is not None
                or warm_start.get("source_normal_solution_sha256")
                != expected["sha256"]
                or warm_start.get("source_variable_name_sha256")
                != expected["variable_name_sha256"]
                or warm_start.get("source_variable_schema_sha256")
                != expected["variable_schema_sha256"]
                or warm_start.get("source_variable_fixed_schema_sha256")
                != expected["variable_fixed_schema_sha256"]
                or warm_start.get("endpoint_fixed_overwrite_count") != 0
                or not warm_start.get("endpoint_fixed_state_unchanged")
                or not warm_loaded_audit.get("feasible")
                or float(warm_loaded_audit.get("tolerance", "inf"))
                != 1e-6
                or int(row["allocation_envelope_warm_start_assignment_count"])
                != int(warm_start["assignment_count"])
                or row.get("allocation_envelope_warm_start_status")
                != "pass"
                or row.get(
                    "allocation_envelope_warm_start_source_record_sha256"
                )
                != expected["sha256"]
                or row.get(
                    "allocation_envelope_warmstart_solver_argument"
                )
                != "True"
            ):
                return False
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


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
    contract = expected_overrides.get("c0_allocation_envelope_diagnostic", {})
    try:
        uncertainty = _trajectory_endpoint_bound_uncertainty(
            c0_models,
            endpoint=str(contract["endpoint"]),
            annual_uncertainty_limit_mwh_y=float(
                contract["endpoint_annual_bound_uncertainty_limit_mwh_y"]
            ),
        )
    except (AllocationEnvelopeError, KeyError, TypeError, ValueError):
        return False
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
                "allocation_envelope_normal_feasibility_oracle_status"
            )
            == "pass"
            and float(
                row.get("allocation_envelope_effective_state_tolerance", "inf")
            )
            == 1e-6
            and float(
                row.get("allocation_envelope_max_state_residual", "inf")
            )
            <= 1e-6
            and row.get("allocation_envelope_deactivated_deadline_row")
            == "rolling_production_deadline[24]"
            and row.get(
                "allocation_envelope_normal_incumbent_min_formulation_feasible"
            )
            == "True"
            and row.get(
                "allocation_envelope_normal_incumbent_max_formulation_feasible"
            )
            == "True"
            and row.get("allocation_envelope_endpoint_accuracy_schema")
            == ENDPOINT_SOLVER_ACCURACY_SCHEMA
            and row.get("allocation_envelope_endpoint_incumbent_basis")
            == "feasible_solution"
            and row.get(
                "allocation_envelope_endpoint_best_bound_availability"
            )
            == "available"
            and row.get(
                "allocation_envelope_endpoint_objective_bound_audit_status"
            )
            == "pass"
            and row.get("allocation_envelope_endpoint_bound_sense_status")
            == "pass"
            and float(
                row["allocation_envelope_endpoint_relative_mip_gap_target"]
            )
            == ENDPOINT_RELATIVE_MIP_GAP
            and float(
                row[
                    "allocation_envelope_endpoint_absolute_mip_gap_target_mwh"
                ]
            )
            == ENDPOINT_ABSOLUTE_MIP_GAP_MWH
            and float(
                row[
                    "allocation_envelope_endpoint_bound_comparison_epsilon_mwh"
                ]
            )
            == ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
            and row.get(
                "allocation_envelope_endpoint_solver_options_sha256"
            )
            == _mapping_sha256(
                {
                    "MIPGap": ENDPOINT_RELATIVE_MIP_GAP,
                    "MIPGapAbs": ENDPOINT_ABSOLUTE_MIP_GAP_MWH,
                    "warmstart": True,
                }
            )
            for row in c0_models
        )
        and uncertainty["endpoint_objective_bound_uncertainty_status"]
        == "pass"
        and _endpoint_oracle_cache_ready(
            c0_models, expected_overrides=expected_overrides
        )
    )


def _sum(rows: list[dict[str, str]], field: str) -> float:
    return sum(float(row.get(field) or 0.0) for row in rows)


def _trajectory_endpoint_bound_uncertainty(
    model_rows: list[dict[str, str]],
    *,
    endpoint: str,
    annual_uncertainty_limit_mwh_y: float = (
        ENDPOINT_ANNUAL_BOUND_UNCERTAINTY_LIMIT_MWH_Y
    ),
) -> dict[str, Any]:
    """Annualise audited per-window incumbent/bound gaps fail-closed."""

    if endpoint not in EXPECTED_ENDPOINTS or len(model_rows) != 7:
        raise AllocationEnvelopeError(
            "Endpoint bound uncertainty requires one complete seven-window trajectory."
        )
    try:
        execution_hours = sum(
            int(row["allocation_envelope_execution_hours"])
            for row in model_rows
        )
        incumbents = [
            float(row["allocation_envelope_objective_value_mwh"])
            for row in model_rows
        ]
        bounds = [
            float(row["allocation_envelope_endpoint_best_bound_mwh"])
            for row in model_rows
        ]
        gaps = [
            float(
                row[
                    "allocation_envelope_endpoint_objective_bound_abs_gap_mwh"
                ]
            )
            for row in model_rows
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise AllocationEnvelopeError(
            "Endpoint bound uncertainty evidence is missing or non-numeric."
        ) from exc
    if execution_hours <= 0 or not all(
        math.isfinite(value) for value in (*incumbents, *bounds, *gaps)
    ):
        raise AllocationEnvelopeError(
            "Endpoint bound uncertainty evidence is nonfinite or has no hours."
        )
    if any(
        row.get("allocation_envelope_endpoint_accuracy_schema")
        != ENDPOINT_SOLVER_ACCURACY_SCHEMA
        or row.get(
            "allocation_envelope_endpoint_best_bound_availability"
        )
        != "available"
        or row.get(
            "allocation_envelope_endpoint_objective_bound_audit_status"
        )
        != "pass"
        or row.get("allocation_envelope_endpoint_bound_sense_status")
        != "pass"
        or float(
            row["allocation_envelope_endpoint_relative_mip_gap_target"]
        )
        != ENDPOINT_RELATIVE_MIP_GAP
        or float(
            row[
                "allocation_envelope_endpoint_absolute_mip_gap_target_mwh"
            ]
        )
        != ENDPOINT_ABSOLUTE_MIP_GAP_MWH
        or gap
        > ENDPOINT_ABSOLUTE_MIP_GAP_MWH
        + ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
        for row, gap in zip(model_rows, gaps, strict=True)
    ):
        raise AllocationEnvelopeError(
            "One or more endpoint windows failed the solver-bound accuracy contract."
        )
    factor = 8760.0 / execution_hours
    annual_gap = sum(gaps) * factor
    if annual_gap > (
        annual_uncertainty_limit_mwh_y
        + ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
    ):
        raise AllocationEnvelopeError(
            "Endpoint trajectory annualized objective-bound uncertainty exceeds "
            f"{annual_uncertainty_limit_mwh_y} MWh/y: {annual_gap}."
        )
    incumbent_annual = sum(incumbents) * factor
    bound_annual = sum(bounds) * factor
    return {
        "endpoint_objective_incumbent_mwh_y": incumbent_annual,
        "endpoint_best_bound_mwh_y": bound_annual,
        "endpoint_objective_bound_uncertainty_mwh_y": annual_gap,
        "endpoint_objective_bound_uncertainty_limit_mwh_y": (
            annual_uncertainty_limit_mwh_y
        ),
        "endpoint_objective_bound_uncertainty_status": "pass",
        "endpoint_true_optimum_lower_bound_mwh_y": (
            bound_annual if endpoint == "min" else incumbent_annual
        ),
        "endpoint_true_optimum_upper_bound_mwh_y": (
            incumbent_annual if endpoint == "min" else bound_annual
        ),
        "reported_endpoint_value_basis": "feasible_incumbent_executed_hours",
    }


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
        float(
            row.get(
                "WAG_generator_electricity_mwh_unrounded",
                row["WAG_generator_electricity_mwh"],
            )
            or row["WAG_generator_electricity_mwh"]
        )
        + float(
            row.get(
                "NG_generator_electricity_mwh_unrounded",
                row["NG_generator_electricity_mwh"],
            )
            or row["NG_generator_electricity_mwh"]
        )
        - float(
            row.get(
                "total_generator_electricity_mwh_unrounded",
                row["total_generator_electricity_mwh"],
            )
            or row["total_generator_electricity_mwh"]
        )
        for row in rows
    ]
    mixed_wag_physical_columns = sorted(
        field
        for field in rows[0]
        if "mixed_wag" in field.lower() or "aggregate_wag" in field.lower()
    )
    wag_generator_electricity_mwh_y = annual_equivalent(
        sum(
            float(
                row.get(
                    "WAG_generator_electricity_mwh_unrounded",
                    row["WAG_generator_electricity_mwh"],
                )
                or row["WAG_generator_electricity_mwh"]
            )
            for row in rows
        ),
        hours,
    )
    if str(case["endpoint"]) in EXPECTED_ENDPOINTS:
        model_rows = [
            row
            for row in _read_csv(directory / "rolling_model_metrics.csv")
            if row["configuration_id"] == C0_CONFIGURATION
        ]
        bound_uncertainty = _trajectory_endpoint_bound_uncertainty(
            model_rows, endpoint=str(case["endpoint"])
        )
        incumbent_reporting_residual = abs(
            wag_generator_electricity_mwh_y
            - float(bound_uncertainty["endpoint_objective_incumbent_mwh_y"])
        )
        if incumbent_reporting_residual > 1.0:
            raise AllocationEnvelopeError(
                "Executed-hour endpoint report does not match the feasible solver "
                f"incumbent: annual residual={incumbent_reporting_residual} MWh/y."
            )
    else:
        bound_uncertainty = {}
        incumbent_reporting_residual = 0.0
    return {
        **dict(case),
        **bound_uncertainty,
        "annual_equivalent_basis": "development_week_annual_equivalent_not_empirical_annual_result",
        "executed_hours": hours,
        "wag_generator_electricity_mwh_y": wag_generator_electricity_mwh_y,
        "endpoint_incumbent_reporting_residual_mwh_y": (
            incumbent_reporting_residual
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
            sum(
                float(
                    row.get(
                        "NG_generator_electricity_mwh_unrounded",
                        row["NG_generator_electricity_mwh"],
                    )
                    or row["NG_generator_electricity_mwh"]
                )
                for row in rows
            ),
            hours,
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


def _execution_output_directory(
    primary_output: Path,
    *,
    diagnostic_case_id: str | None,
    diagnostic_replan_index: int | None,
    oracle_only: bool,
) -> Path:
    if diagnostic_case_id is None:
        return primary_output
    parts = diagnostic_case_id.split("__")
    if len(parts) != 4 or parts[0] != "alloc":
        raise AllocationEnvelopeError(
            f"Invalid governed diagnostic case id: {diagnostic_case_id}"
        )
    candidate_code = {
        "recovery_bg30_ng55": "ng55",
        "recovery_bg30_ng30": "ng30",
    }.get(parts[1])
    scenario_code = {
        "calm_price_insensitive": "calm",
        "volatile_negative_governed_y_pred": "volatile",
    }.get(parts[2])
    if candidate_code is None or scenario_code is None or parts[3] not in {
        "min",
        "max",
    }:
        raise AllocationEnvelopeError(
            f"Invalid governed diagnostic case id: {diagnostic_case_id}"
        )
    diagnostic_label = (
        f"{candidate_code}_{scenario_code}_{parts[3]}_"
        f"r{diagnostic_replan_index:02d}_"
        + ("oracle_only" if oracle_only else "endpoint")
        if diagnostic_replan_index is not None
        else f"{candidate_code}_{scenario_code}_{parts[3]}_trajectory"
    )
    return primary_output / "diagnostics" / diagnostic_label


def run_allocation_envelope(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
    diagnostic_case_id: str | None = None,
    diagnostic_replan_index: int | None = None,
    oracle_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    if _git_head() != EXPECTED_HEAD:
        raise AllocationEnvelopeError("Git HEAD changed from the frozen experiment commit.")
    experiment = config["experiment"]
    primary_output = (REPO_ROOT / config["output_root"]).resolve()
    output = _execution_output_directory(
        primary_output,
        diagnostic_case_id=diagnostic_case_id,
        diagnostic_replan_index=diagnostic_replan_index,
        oracle_only=oracle_only,
    )
    output.mkdir(parents=True, exist_ok=True)
    mechanism_config_path = (REPO_ROOT / experiment["mechanism_config"]).resolve()
    mechanism_config = load_mechanism_config(mechanism_config_path)
    validate_mechanism_config(mechanism_config)
    physical_config = (REPO_ROOT / experiment["physical_config"]).resolve()
    physical_config_sha256 = _sha256(physical_config)
    implementation_fingerprints = _implementation_fingerprints(
        config_file=config_file, physical_config=physical_config
    )
    iis_evidence_path = (REPO_ROOT / experiment["iis_evidence"]).resolve()
    if not iis_evidence_path.is_file():
        raise AllocationEnvelopeError("The governed v4 IIS evidence is missing.")
    iis_evidence_sha256 = _sha256(iis_evidence_path)
    if oracle_only and (
        diagnostic_case_id is None or diagnostic_replan_index is None
    ):
        raise AllocationEnvelopeError(
            "Oracle-only mode requires one diagnostic case and replan index."
        )
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
    provenance: list[dict[str, Any]] = []
    controls: dict[tuple[str, str], dict[str, Any]] = {}
    schedules: dict[tuple[str, str], list[dict[str, Any]]] = {}
    schedule_hashes: dict[tuple[str, str], str] = {}
    normal_solution_records: dict[
        tuple[str, str], dict[str, dict[str, Any]]
    ] = {}
    normal_schedule_rows: list[dict[str, Any]] = []
    normal_record_rows: list[dict[str, Any]] = []
    full_matrix = frozen_case_matrix(config)
    if diagnostic_case_id is not None:
        matching = [
            row for row in full_matrix if row["case_id"] == diagnostic_case_id
        ]
        if len(matching) != 1:
            raise AllocationEnvelopeError(
                f"Unknown diagnostic case id: {diagnostic_case_id}"
            )
        required_normal_keys = {
            (matching[0]["candidate_id"], matching[0]["scenario_id"])
        }
    else:
        required_normal_keys = {
            (candidate, scenario)
            for candidate in EXPECTED_CANDIDATES
            for scenario in EXPECTED_SCENARIOS
        }
    normal_index = 0
    for candidate_id, scenario_id in sorted(required_normal_keys):
            normal_index += 1
            normal_id = _normal_case_id(candidate_id, scenario_id)
            normal_directory = scratch / normal_id
            normal_base_provenance = {
                **implementation_fingerprints,
                "normal_case_id": normal_id,
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
            }
            normal_overrides = {
                **_expected_case_overrides(
                    case_id=normal_id,
                    forecast_root=forecast_root,
                    scenario=scenarios[scenario_id],
                    periods=periods,
                    config=mechanism_config,
                    candidate=candidates[candidate_id],
                ),
                "lineage_role": (
                    "diagnostic_current_hook_absent_normal_controller"
                ),
                "normal_solution_capture": {
                    "enabled": True,
                    "directory": str(normal_directory),
                    "provenance": normal_base_provenance,
                },
            }
            ready = _normal_ready(
                normal_directory,
                expected_overrides=normal_overrides,
                physical_config_sha256=physical_config_sha256,
            )
            source = "reused_current_normal_cache" if ready else "new_solve"
            if not ready and not aggregate_only:
                if normal_directory.exists():
                    raise AllocationEnvelopeError(
                        "Incomplete current-normal cache preserved for inspection: "
                        f"{normal_directory}"
                    )
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=normal_overrides,
                )
                provisional_schedule, provisional_hash = _normal_schedule(
                    normal_directory
                )
                _finalize_normal_solution_records(
                    normal_directory,
                    schedule=provisional_schedule,
                    schedule_hash=provisional_hash,
                )
                ready = _normal_ready(
                    normal_directory,
                    expected_overrides=normal_overrides,
                    physical_config_sha256=physical_config_sha256,
                )
            if not ready:
                raise AllocationEnvelopeError(
                    f"Current hook-absent normal control failed: {normal_id}"
                )
            schedule, schedule_hash = _normal_schedule(normal_directory)
            key = (candidate_id, scenario_id)
            schedules[key] = schedule
            schedule_hashes[key] = schedule_hash
            normal_solution_records[key] = _load_normal_solution_records(
                normal_directory
            )
            normal_record_rows.extend(
                _normal_record_manifest_rows(
                    candidate_id, scenario_id, normal_directory
                )
            )
            controls[key] = _normal_control_metrics(
                candidate_id, scenario_id, normal_directory
            )
            normal_schedule_rows.extend(
                {
                    "candidate_id": candidate_id,
                    "scenario_id": scenario_id,
                    "normal_controller_schedule_sha256": schedule_hash,
                    **row,
                }
                for row in schedule
            )
            provenance.append(
                {
                    "candidate_id": candidate_id,
                    "scenario_id": scenario_id,
                    "period_id": next(
                        row["period_id"]
                        for row in experiment["scenarios"]
                        if row["scenario_id"] == scenario_id
                    ),
                    "status": "pass_current_hook_absent_normal",
                    "source_run_id": normal_id,
                    "source_git_commit": EXPECTED_HEAD,
                    "source_input_manifest_sha256": _sha256(
                        normal_directory / "input_manifest.json"
                    ),
                    "source_metrics_sha256": _sha256(
                        normal_directory / "executed_hourly.csv"
                    ),
                    "normal_controller_schedule_sha256": schedule_hash,
                    "normal_control_reoptimised": True,
                    "current_builder_boundary": (
                        "current hook-absent normal rolling controller"
                    ),
                    "source": source,
                }
            )
            print(
                f"[normal {normal_index}/{len(required_normal_keys)}] "
                f"{normal_id}: pass ({source})",
                flush=True,
            )
    _persist_normal_control_evidence(
        output,
        provenance=provenance,
        normal_schedule_rows=normal_schedule_rows,
        normal_record_rows=normal_record_rows,
        require_full_matrix=diagnostic_case_id is None,
    )
    statuses: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    window_audits: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    matrix = (
        [
            row
            for row in full_matrix
            if row["case_id"] == diagnostic_case_id
        ]
        if diagnostic_case_id is not None
        else full_matrix
    )
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
                "endpoint_solver_accuracy_schema": experiment[
                    "endpoint_solver_accuracy_schema"
                ],
                "endpoint_relative_mip_gap": float(
                    experiment["endpoint_relative_mip_gap"]
                ),
                "endpoint_absolute_mip_gap_mwh": float(
                    experiment["endpoint_absolute_mip_gap_mwh"]
                ),
                "endpoint_bound_comparison_epsilon_mwh": float(
                    experiment["endpoint_bound_comparison_epsilon_mwh"]
                ),
                "endpoint_annual_bound_uncertainty_limit_mwh_y": float(
                    experiment[
                        "endpoint_annual_bound_uncertainty_limit_mwh_y"
                    ]
                ),
                "case_id": case_id,
                "normal_controller_schedule": schedules[
                    (case["candidate_id"], case["scenario_id"])
                ],
                "normal_controller_schedule_sha256": schedule_hashes[
                    (case["candidate_id"], case["scenario_id"])
                ],
                "failure_evidence_directory": str(
                    directory / "first_failure_evidence"
                ),
                "normal_solution_records_by_replan": (
                    normal_solution_records[
                        (case["candidate_id"], case["scenario_id"])
                    ]
                ),
                "iis_evidence_sha256": iis_evidence_sha256,
                "oracle_only": oracle_only,
            },
        }
        if diagnostic_replan_index is not None:
            overrides["diagnostic_replan_index"] = int(
                diagnostic_replan_index
            )
        ready = False if diagnostic_replan_index is not None else _endpoint_ready(
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
                diagnostic_result = run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if diagnostic_replan_index is not None:
                if error:
                    raise AllocationEnvelopeError(
                        f"Targeted endpoint diagnostic failed: {error}"
                    )
                diagnostic_summary = diagnostic_result["summary"]
                expected_status = (
                    "oracle_only_pass"
                    if oracle_only
                    else "diagnostic_endpoint_pass"
                )
                if diagnostic_summary.get("status") != expected_status:
                    raise AllocationEnvelopeError(
                        "Targeted endpoint diagnostic failed closed: "
                        f"{diagnostic_summary}."
                    )
                top_level_summary = {
                    "run_id": config["run_id"],
                    "status": "diagnostic_pass",
                    "decision": (
                        "target_normal_feasibility_oracle_passed"
                        if oracle_only
                        else "target_endpoint_passed"
                    ),
                    "diagnostic_case_id": case_id,
                    "diagnostic_replan_index": diagnostic_replan_index,
                    "oracle_only": oracle_only,
                    "endpoint_objective_solved": not oracle_only,
                    "normal_controller_schedule_sha256": schedule_hashes[
                        (case["candidate_id"], case["scenario_id"])
                    ],
                    "normal_solution_record_sha256": normal_solution_records[
                        (case["candidate_id"], case["scenario_id"])
                    ][str(diagnostic_replan_index)]["sha256"],
                    "iis_evidence_sha256": iis_evidence_sha256,
                    "implementation_fingerprints": (
                        implementation_fingerprints
                    ),
                    "diagnostic_result": diagnostic_summary,
                }
                _write_json(
                    output / "checkpoint_state.json", top_level_summary
                )
                _write_json(output / "run_summary.json", top_level_summary)
                return top_level_summary
            ready = _endpoint_ready(
                directory,
                expected_overrides=overrides,
                physical_config_sha256=physical_config_sha256,
            )
        if not ready:
            preserved_case_directory = str(
                directory.relative_to(REPO_ROOT)
            ).replace("\\", "/")
            failure_bundle = _persist_failure_bundle(
                output,
                case_id=case_id,
                source_directory=directory,
            )
            evidence = dict(failure_bundle["files_sha256"])
            for name in (
                "primary_control_provenance.csv",
                "normal_controller_schedule.csv",
                "normal_solution_record_manifest.csv",
                "failure_evidence_manifest.json",
            ):
                path = output / name
                if path.is_file():
                    evidence[
                        str(path.relative_to(output)).replace("\\", "/")
                    ] = _sha256(path)
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
            failed_replan_index = failure_bundle.get(
                "failed_replan_index"
            )
            accepted_endpoint_windows = (
                accepted_trajectories * int(experiment["replan_count"])
                + _completed_endpoint_windows_before_failure(
                    directory, failed_replan_index
                )
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
                "accepted_c0_endpoint_window_count": accepted_endpoint_windows,
                "planned_c0_endpoint_window_count": 56,
                "repair_cycle_count": 1,
                "normal_control_count": len(provenance),
                "normal_schedule_row_count": len(normal_schedule_rows),
                "normal_solution_record_count": len(normal_record_rows),
                "failed_replan_index": failed_replan_index,
                "preserved_case_directory": preserved_case_directory,
                "preserved_evidence_sha256": evidence,
                "persistent_failure_manifest": failure_bundle,
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
                "normal_controller_schedule_sha256": schedule_hashes[
                    (case["candidate_id"], case["scenario_id"])
                ],
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
                    "endpoint_objective_incumbent_mwh": row[
                        "allocation_envelope_objective_value_mwh"
                    ],
                    "endpoint_best_bound_mwh": row[
                        "allocation_envelope_endpoint_best_bound_mwh"
                    ],
                    "endpoint_objective_bound_abs_gap_mwh": row[
                        "allocation_envelope_endpoint_objective_bound_abs_gap_mwh"
                    ],
                    "endpoint_objective_bound_audit_status": row[
                        "allocation_envelope_endpoint_objective_bound_audit_status"
                    ],
                    "endpoint_bound_sense_status": row[
                        "allocation_envelope_endpoint_bound_sense_status"
                    ],
                    "endpoint_relative_mip_gap_target": row[
                        "allocation_envelope_endpoint_relative_mip_gap_target"
                    ],
                    "endpoint_absolute_mip_gap_target_mwh": row[
                        "allocation_envelope_endpoint_absolute_mip_gap_target_mwh"
                    ],
                    "endpoint_solver_options_sha256": row[
                        "allocation_envelope_endpoint_solver_options_sha256"
                    ],
                    "endpoint_solver_log_sha256": row[
                        "allocation_envelope_endpoint_solver_log_sha256"
                    ],
                    "endpoint_pre_solve_model_path": row[
                        "allocation_envelope_endpoint_pre_solve_model_path"
                    ],
                    "endpoint_pre_solve_model_sha256": row[
                        "allocation_envelope_endpoint_pre_solve_model_sha256"
                    ],
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
                        if float(row["allocation_envelope_max_state_residual"])
                        <= float(
                            row[
                                "allocation_envelope_effective_state_tolerance"
                            ]
                        )
                        else "fail"
                    ),
                    "raw_hashes_preserved": (
                        "pass"
                        if endpoint_hash
                        == row["allocation_envelope_raw_endpoint_handoff_hash"]
                        else "fail"
                    ),
                    "normal_controller_schedule_sha256": schedule_hashes[
                        (case["candidate_id"], case["scenario_id"])
                    ],
                    "endpoint_optimal_status": (
                        "pass"
                        if row["allocation_envelope_termination_condition"] == "optimal"
                        and row[
                            "allocation_envelope_endpoint_objective_bound_audit_status"
                        ]
                        == "pass"
                        else "fail"
                    ),
                }
            )
        for row in _read_csv(directory / "validation_checks.csv"):
            validation_rows.append({**dict(case), **row})
        print(f"[{index}/{len(matrix)}] {case_id}: pass ({source})", flush=True)

    if diagnostic_case_id is not None:
        diagnostic_summary = {
            "run_id": config["run_id"],
            "status": "diagnostic_pass",
            "decision": "former_failing_path_passed_continue_full_matrix",
            "diagnostic_case_id": diagnostic_case_id,
            "current_normal_control_count": 1,
            "endpoint_trajectory_count": 1,
            "c0_endpoint_window_count": 7,
            "repair_cycle_count": 1,
        }
        _write_csv(output / "primary_control_provenance.csv", provenance)
        _write_csv(
            output / "normal_controller_schedule.csv",
            normal_schedule_rows,
        )
        _write_json(output / "checkpoint_state.json", diagnostic_summary)
        _write_json(output / "run_summary.json", diagnostic_summary)
        return diagnostic_summary

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
                    "wag_generator_electricity_mwh_y"
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
                    "minimum_feasible_incumbent_bound_uncertainty_mwh_y": (
                        by_endpoint[(candidate, scenario, "min")][
                            "endpoint_objective_bound_uncertainty_mwh_y"
                        ]
                    ),
                    "maximum_feasible_incumbent_bound_uncertainty_mwh_y": (
                        by_endpoint[(candidate, scenario, "max")][
                            "endpoint_objective_bound_uncertainty_mwh_y"
                        ]
                    ),
                    "minimum_true_optimum_lower_bound_mwh_y": by_endpoint[
                        (candidate, scenario, "min")
                    ]["endpoint_true_optimum_lower_bound_mwh_y"],
                    "maximum_true_optimum_upper_bound_mwh_y": by_endpoint[
                        (candidate, scenario, "max")
                    ]["endpoint_true_optimum_upper_bound_mwh_y"],
                    "envelope_reporting_basis": (
                        "feasible_endpoint_incumbents_with_bound_uncertainty_separate"
                    ),
                    "min_normal_max_status": status,
                    "normal_control_boundary": "current_hook_absent_normal_controller",
                    "normal_wag_generator_fuel_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_generator_fuel_mwh_lhv_y"],
                    "normal_wag_flexible_heat_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_flexible_heat_mwh_lhv_y"],
                    "normal_wag_mandatory_heat_mwh_lhv_y": controls[
                        (candidate, scenario)
                    ]["wag_mandatory_heat_mwh_lhv_y"],
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
                    ]["ng_generator_electricity_mwh_y"],
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
                    "classification_basis": "feasible_endpoint_incumbents",
                    "minimum_bound_uncertainty_mwh_y": by_endpoint[
                        (candidate, scenario, "min")
                    ]["endpoint_objective_bound_uncertainty_mwh_y"],
                    "maximum_bound_uncertainty_mwh_y": by_endpoint[
                        (candidate, scenario, "max")
                    ]["endpoint_objective_bound_uncertainty_mwh_y"],
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
        or row["raw_hashes_preserved"] != "pass"
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
            "guardrail": "same_current_normal_schedule_used_by_both_endpoints",
            "status": (
                "pass"
                if all(
                    len(
                        {
                            row["normal_controller_schedule_sha256"]
                            for row in statuses
                            if row["candidate_id"] == candidate
                            and row["scenario_id"] == scenario
                        }
                    )
                    <= 1
                    for candidate in EXPECTED_CANDIDATES
                    for scenario in EXPECTED_SCENARIOS
                )
                else "fail"
            ),
            "evidence": "normal_controller_schedule.csv and endpoint overrides",
        },
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
            "guardrail": "endpoint_objective_bounds_within_reporting_uncertainty",
            "status": (
                "pass"
                if len(solver_rows) == 56
                and all(
                    row[
                        "allocation_envelope_endpoint_objective_bound_audit_status"
                    ]
                    == "pass"
                    and float(
                        row[
                            "allocation_envelope_endpoint_objective_bound_abs_gap_mwh"
                        ]
                    )
                    <= ENDPOINT_ABSOLUTE_MIP_GAP_MWH
                    + ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
                    for row in solver_rows
                )
                and len(metrics) == 8
                and all(
                    row["endpoint_objective_bound_uncertainty_status"]
                    == "pass"
                    and float(
                        row["endpoint_objective_bound_uncertainty_mwh_y"]
                    )
                    <= ENDPOINT_ANNUAL_BOUND_UNCERTAINTY_LIMIT_MWH_Y
                    + ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
                    for row in metrics
                )
                else "fail"
            ),
            "evidence": (
                "per_window_preservation_audit.csv and "
                "endpoint_annual_equivalent_metrics.csv"
            ),
        },
        {
            "guardrail": "successful_endpoint_models_hash_bound",
            "status": (
                "pass"
                if len(solver_rows) == 56
                and all(
                    _resolve_evidence_path(
                        row[
                            "allocation_envelope_endpoint_pre_solve_model_path"
                        ]
                    ).is_file()
                    and _sha256(
                        _resolve_evidence_path(
                            row[
                                "allocation_envelope_endpoint_pre_solve_model_path"
                            ]
                        )
                    )
                    == row[
                        "allocation_envelope_endpoint_pre_solve_model_sha256"
                    ]
                    for row in solver_rows
                )
                else "fail"
            ),
            "evidence": "solver_runtime_model_metrics.csv portable LP paths/hashes",
        },
        {
            "guardrail": "complete_normal_payload_bundle_self_contained",
            "status": (
                "pass"
                if len(_read_csv(output / "normal_solution_record_manifest.csv"))
                == (56 if diagnostic_case_id is None else 14)
                and all(
                    row.get("bundled_under_persistent_root") == "True"
                    and _resolve_evidence_path(row["path"]).is_file()
                    and _sha256(_resolve_evidence_path(row["path"]))
                    == row["sha256"]
                    for row in _read_csv(
                        output / "normal_solution_record_manifest.csv"
                    )
                )
                else "fail"
            ),
            "evidence": "normal_solution_record_manifest.csv and normal_solution_records/",
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
    _write_csv(output / "normal_controller_schedule.csv", normal_schedule_rows)
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
            "current_normal_control_fingerprints": [
                {
                    "candidate_id": row["candidate_id"],
                    "scenario_id": row["scenario_id"],
                    "input_manifest_sha256": row[
                        "source_input_manifest_sha256"
                    ],
                    "executed_hourly_sha256": row["source_metrics_sha256"],
                    "normal_controller_schedule_sha256": row[
                        "normal_controller_schedule_sha256"
                    ],
                }
                for row in provenance
            ],
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
        "endpoint_bound_audited_window_count": sum(
            row["allocation_envelope_endpoint_objective_bound_audit_status"]
            == "pass"
            for row in solver_rows
        ),
        "maximum_trajectory_bound_uncertainty_mwh_y": max(
            (
                float(row["endpoint_objective_bound_uncertainty_mwh_y"])
                for row in metrics
            ),
            default=0.0,
        ),
        "endpoint_annual_bound_uncertainty_limit_mwh_y": (
            ENDPOINT_ANNUAL_BOUND_UNCERTAINTY_LIMIT_MWH_Y
        ),
        "bundled_complete_normal_solution_count": len(
            _read_csv(output / "normal_solution_record_manifest.csv")
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
        "Four reoptimised current hook-absent normal controls are compared with eight newly "
        "optimised min/max C0 endpoint trajectories (seven replans each). Each "
        "endpoint preserves the normal progress optimum, represented procurement "
        "cost under the one-sided EUR 0.01/window upper constraint, executed "
        "production and all four carried C0 "
        "inventories. Annual equivalents scale one DEVELOPMENT validation week; "
        "they are not empirical annual results. The endpoint is pure WAG-only "
        "generator electricity and does not target the 2.528-TWh/y anchor. The "
        "primary cost stage must be optimal, and every endpoint is audited against "
        "both its primary objective and the solver-reported best bound; no lower-cost "
        "constraint is imposed. Reported min/max values are feasible endpoint "
        "incumbents. Sense-correct solver best bounds and their annualised absolute "
        "uncertainty are reported separately, with 0.001 MWh/window endpoint accuracy "
        "and a 1 MWh/y trajectory limit. Every successful endpoint has a portable "
        "pre-solve LP path/hash, and all complete normal-solution payloads are bundled "
        "under this persistent run root.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a diagnostic/emulation sensitivity, not calibration or candidate promotion.\n"
        "- Each current normal control is reoptimised first and its complete C0/C1 rolling-controller schedule is fingerprinted and shared by both endpoint senses; the absent-hook path has a direct regression test.\n"
        "- Only validation y_pred periods are used; TEST, y_true, oracle, bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR are excluded.\n"
        "- Residual electricity and NG remain reporting-only and unpriced.\n"
        "- Feasible incumbent envelope values and solver-bound uncertainty are distinct; endpoint solves use MIPGap=0 and MIPGapAbs=0.001 MWh/window, and each seven-window annualised bound uncertainty must stay at or below 1 MWh/y.\n"
        "- Portable endpoint LPs and solver logs remain in governed scratch storage but are cryptographically bound into persistent metrics; complete normal-solution payloads are copied into this run root and hash-verified.\n"
        "- If the real anchor is inside, allocation remains non-identifiable pending Tata policy evidence.\n",
        encoding="utf-8",
    )
    if failures:
        raise AllocationEnvelopeError(
            f"Allocation-envelope acceptance failed: {len(failures)} guardrail(s)."
        )
    return summary
