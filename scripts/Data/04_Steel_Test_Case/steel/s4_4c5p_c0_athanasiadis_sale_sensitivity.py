"""Bounded Phase-2 C0 electricity-sale sensitivity.

This is an opt-in DEVELOPMENT diagnostic.  The accepted no-export path is the
comparator, C1 is untouched, WAG has no direct value, and the only export value
is the same governed ``y_pred`` electricity series used for import procurement.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Collection, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    HANDOFF_STATE_SCHEMA_BY_CONFIGURATION,
    _validate_inventory_handoff_contract,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_c0_real_anchor_mechanism_experiment import (
    _scenario_overrides,
    candidate_overrides,
    load_mechanism_config,
    validate_mechanism_config,
)
from .validation_tolerance_policy import (
    ELECTRICITY_BALANCE_TOLERANCE_MWH,
    ELECTRICITY_TRAJECTORY_MAX_PURPOSES,
    HOURLY_MONEY_IDENTITY_TOLERANCE_EUR,
    MATERIAL_BALANCE_TOLERANCE_T,
    POLICY_FINGERPRINT as VALIDATION_TOLERANCE_POLICY_FINGERPRINT,
    POLICY_ID as VALIDATION_TOLERANCE_POLICY_ID,
    POLICY_VERSION as VALIDATION_TOLERANCE_POLICY_VERSION,
    SOLVER_NUMERICAL_TOLERANCE,
    TERMINAL_STATE_TOLERANCE_T,
    ValidationTolerancePolicyError,
    exact_input_fingerprint,
    policy_contract as validation_tolerance_policy_contract,
    require_exact_input_fingerprint,
    resolve_policy_contract,
    threshold_comparison_record,
    trajectory_cost_record,
    validation_record,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_athanasiadis_sale_sensitivity.yaml"
)
EXPECTED_RUN_ID = "steel_c5_athanasiadis_sale_sensitivity_v1_20260726"
EXPECTED_HEAD = "f2c4126b216707b132ca9bab43291b345e49b939"
EXPECTED_CANDIDATES = ("recovery_bg30_ng55", "recovery_bg30_ng30")
EXPECTED_SCENARIOS = (
    "calm_price_insensitive",
    "volatile_negative_governed_y_pred",
)
EXPECTED_POLICIES = (
    "accepted_no_export_comparator",
    "athanasiadis_sale_enabled",
)
FULL_MATRIX_AUTHORIZATION_FIELDS = (
    "full_matrix_execution_authorized",
    "full_matrix_post_review_token_sha256",
)
FULL_MATRIX_AUTHORIZATION_SENTINELS = {
    "full_matrix_execution_authorized": "<authorization-excluded:boolean>",
    "full_matrix_post_review_token_sha256": "<authorization-excluded:sha256>",
}
VOLATILE_PREFIX_REPLAN_COUNT = 5
VOLATILE_PREFIX_TARGET_REPLAN = 4
SUPPORTED_EXECUTION_MODES = (
    "aggregate_only",
    "preflight_absent_disabled",
    "preflight_containment",
    "preflight_calm",
    "preflight_volatile_containment",
    "preflight_volatile",
    "full_matrix",
)
POSTHOC_REAUDIT_EXECUTION_MODE = "posthoc_full_matrix_guardrail_reaudit"
POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID = "440726f6b81eaec6__086275eaa30b"
POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256 = (
    "440726f6b81eaec6530b2199a6e5e212ebba43091f70122ee58ab9dabf63c650"
)
POSTHOC_REAUDIT_SOURCE_CONFIG_SHA256 = (
    "c4d2167199f2fcb6d3f3d302fc23e80564a024c948949c1f44b0d87bf6a341dd"
)
POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256 = (
    "e1a23424d71d4522aebc68feaaa7daeeb9e7e149a8d2674b834edab4bc3447f9"
)
POSTHOC_REAUDIT_SOURCE_POLICY_CONTRACT = {
    "policy_id": "steel_unit_purpose_validation_tolerance",
    "policy_version": "v1_20260726",
    "policy_fingerprint_sha256": (
        "30d746921f9b7d92efbd8f7834d4ca7b9ea860f60beddc54ad46aaf2e5ebbf50"
    ),
}
POSTHOC_REAUDIT_AUTHORIZATION_PHRASE = (
    f"{POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID}:"
    "posthoc_full_matrix_guardrail_reaudit_no_solve"
)
POSTHOC_REAUDIT_SOURCE_FILES = (
    "run_summary.json",
    "physical_guardrails.csv",
    "case_status.csv",
    "child_solver_summary.csv",
    "implementation_fingerprints.json",
    "resolved_config.yaml",
    "run_identity.json",
    "code_version.json",
)
POSTHOC_REAUDIT_SOURCE_FILE_CONTRACT = {
    "run_summary.json": {
        "size_bytes": 944,
        "sha256": "bd7dda1058e47ff3156eabacfe1db545bf5def4cbecd790eb9a4b980ce898007",
    },
    "physical_guardrails.csv": {
        "size_bytes": 17_820,
        "sha256": "863fbc2f1a9064580f072bbe0f238549f5411e5b3fbb03dd8b9f20622bdb32ca",
    },
    "case_status.csv": {
        "size_bytes": 3_591,
        "sha256": "8b50e2d151db30bd17545d63d17e4492761402c5250c42ad8e7cbe9369639a98",
    },
    "child_solver_summary.csv": {
        "size_bytes": 731_926,
        "sha256": "7742b45954c85a55436ab142eb92dd34ea873986ba242191b3ea97f8cdf04dbf",
    },
    "implementation_fingerprints.json": {
        "size_bytes": 4_629,
        "sha256": "390befa3152e3420d7ec1ddaf9e4c60a11d7528d4e2308161d03938cba516415",
    },
    "resolved_config.yaml": {
        "size_bytes": 3_390,
        "sha256": "b59162f0d23459ec5f6a44e63d57be3a69fa910b6a3ccb9c9c4cba7419777a2e",
    },
    "run_identity.json": {
        "size_bytes": 639,
        "sha256": "032ce02cf0e0d409403bbbb3718b67b59263b5f1fe6658128bd3b07bc5037332",
    },
    "code_version.json": {
        "size_bytes": 482,
        "sha256": "0ad63a34821f251eb2f4a0eae86281c74075f402b4202e15a75ba58f3ba0acc3",
    },
}
HANDOFF_FIELDS = (
    "coke_inventory_t",
    "sinter_inventory_t",
    "hot_iron_inventory_t",
    "cold_slab_inventory_t",
    "dri_inventory_t",
    "cumulative_executed_final_product_t",
)


class SaleSensitivityError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in materialized for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            "scripts/Data/04_Steel_Test_Case",
            ":(exclude)scripts/Data/04_Steel_Test_Case/configs/steel_c5_athanasiadis_sale_sensitivity.yaml",
        ],
        cwd=REPO_ROOT,
    )
    return hashlib.sha256(payload).hexdigest()


def _full_matrix_authorization_metadata(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if any(field not in config for field in FULL_MATRIX_AUTHORIZATION_FIELDS):
        raise SaleSensitivityError(
            "Full-matrix authorization metadata is missing."
        )
    authorized = config["full_matrix_execution_authorized"]
    token_sha256 = config["full_matrix_post_review_token_sha256"]
    if type(authorized) is not bool:
        raise SaleSensitivityError(
            "Full-matrix authorization flag must be exactly boolean."
        )
    valid_hash = bool(
        isinstance(token_sha256, str)
        and len(token_sha256) == 64
        and token_sha256 == token_sha256.lower()
        and all(character in "0123456789abcdef" for character in token_sha256)
    )
    if (authorized and not valid_hash) or (
        not authorized and token_sha256 is not None
    ):
        raise SaleSensitivityError(
            "Full-matrix authorization flag/token-hash metadata is contradictory or malformed."
        )
    return {
        "full_matrix_execution_authorized": authorized,
        "full_matrix_post_review_token_sha256": token_sha256,
    }


def _semantic_config_fingerprint(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).resolve()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SaleSensitivityError("Phase-2 configuration must be a mapping.")
    _full_matrix_authorization_metadata(payload)
    semantic = dict(payload)
    semantic.update(FULL_MATRIX_AUTHORIZATION_SENTINELS)
    return {
        "schema_version": "steel_phase2_semantic_config_fingerprint_v1",
        "config_role": "c0_athanasiadis_sale_sensitivity",
        "semantic_config_sha256": _mapping_sha256(semantic),
        "authorization_exclusion_contract": {
            "excluded_fields": list(FULL_MATRIX_AUTHORIZATION_FIELDS),
            "fixed_sentinels": dict(FULL_MATRIX_AUTHORIZATION_SENTINELS),
            "all_other_config_fields_semantic": True,
        },
    }


def _portable_persistent_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError as exc:
        raise SaleSensitivityError(
            f"Persistent Phase-2 paths must remain below the repository root: {resolved}"
        ) from exc


def _portableize_persistent_payload(
    payload: Any, *, forecast_root: Path | None = None
) -> Any:
    if isinstance(payload, Mapping):
        return {
            str(key): _portableize_persistent_payload(
                value, forecast_root=forecast_root
            )
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [
            _portableize_persistent_payload(value, forecast_root=forecast_root)
            for value in payload
        ]
    if isinstance(payload, str) and Path(payload).is_absolute():
        resolved = Path(payload).resolve()
        try:
            return str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            if forecast_root is not None:
                try:
                    relative = resolved.relative_to(forecast_root.resolve())
                    suffix = str(relative).replace("\\", "/")
                    return f"governed_forecast_root:{suffix or '.'}"
                except ValueError:
                    pass
            raise SaleSensitivityError(
                f"Unportable absolute path in persistent payload: {resolved}"
            )
    return payload


def _normalize_child_persistent_paths(
    directory: Path, *, forecast_root: Path
) -> None:
    resolved_path = directory / "config_resolved.yaml"
    payload = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    portable = _portableize_persistent_payload(
        payload, forecast_root=forecast_root
    )
    resolved_path.write_text(
        yaml.safe_dump(portable, sort_keys=False), encoding="utf-8"
    )


def _bound_audit_from_exception(exc: BaseException) -> Mapping[str, Any] | None:
    current: BaseException | None = exc
    while current is not None:
        audit = getattr(current, "bound_audit", None)
        if isinstance(audit, Mapping):
            return audit
        current = current.__cause__
    return None


def _portable_exception_message(exc: BaseException) -> str:
    """Keep persistent diagnostics useful without recording workstation paths."""

    message = str(exc).replace(str(REPO_ROOT) + "\\", "").replace(
        str(REPO_ROOT) + "/", ""
    )
    message = message.replace("\\", "/")
    return re.sub(
        r"(?i)[a-z]:/[^'\"\r\n]+",
        "<absolute_path_redacted>",
        message,
    )


def _persist_failure_evidence(
    output: Path,
    *,
    statuses: list[dict[str, Any]],
    exc: BaseException,
    stage: str,
    started: float,
    load_runtime_seconds: float,
    build_runtime_seconds: float = 0.0,
    solve_runtime_seconds: float = 0.0,
    write_runtime_seconds: float = 0.0,
    execution_mode: str | None = None,
) -> None:
    write_started = time.perf_counter()
    bound_audit = _bound_audit_from_exception(exc)
    if bound_audit is not None:
        _write_json(output / "grid_import_bound_failure_audit.json", bound_audit)
    persistent_statuses = [
        {
            **row,
            "exception_message": _portable_exception_message(
                RuntimeError(str(row["exception_message"]))
            ),
        }
        if row.get("exception_message")
        else dict(row)
        for row in statuses
    ]
    _write_csv(output / "case_status.csv", persistent_statuses)
    elapsed_write = write_runtime_seconds + time.perf_counter() - write_started
    _write_json(
        output / "run_summary.json",
        {
            "run_id": EXPECTED_RUN_ID,
            "status": "fail",
            "completed_trajectory_count": sum(
                row.get("status") == "pass" for row in statuses
            ),
            "failed_case_count": sum(
                row.get("status") == "fail" for row in statuses
            ),
            "failed_case_ids": [
                str(row.get("case_id"))
                for row in statuses
                if row.get("status") == "fail"
            ],
            "child_failure_checks": sorted(
                {
                    check_id
                    for row in statuses
                    for check_id in str(row.get("child_failure_checks") or "").split(";")
                    if check_id
                }
            ),
            "failed_child_artifacts": [
                {
                    "case_id": str(row.get("case_id")),
                    "cache_directory": row.get("cache_directory"),
                    "run_summary_path": row.get("child_run_summary_path"),
                    "validation_checks_path": row.get(
                        "child_validation_checks_path"
                    ),
                }
                for row in statuses
                if row.get("status") == "fail"
            ],
            "execution_mode": execution_mode,
            "exception_stage": stage,
            "exception_type": type(exc).__name__,
            "exception_message": _portable_exception_message(exc),
            "bound_audit_present": bound_audit is not None,
            "load_runtime_seconds": load_runtime_seconds,
            "build_runtime_seconds": build_runtime_seconds,
            "solve_runtime_seconds": solve_runtime_seconds,
            "write_runtime_seconds": elapsed_write,
            "runtime_seconds": time.perf_counter() - started,
        },
    )


def _child_failure_evidence(directory: Path) -> dict[str, Any]:
    """Collect durable evidence when a completed child reports failure."""

    summary_path = directory / "run_summary.json"
    checks_path = directory / "validation_checks.csv"
    metrics_path = directory / "rolling_model_metrics.csv"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else {}
    )
    checks = _read_csv(checks_path) if checks_path.is_file() else []
    failed_checks = sorted(
        str(row.get("check_id") or row.get("validation_id") or "unknown_check")
        for row in checks
        if str(row.get("status", "")).lower() == "fail"
    )
    metrics = _read_csv(metrics_path) if metrics_path.is_file() else []
    return {
        "child_run_status": str(summary.get("status", "missing")),
        "child_failure_checks": ";".join(failed_checks),
        "child_run_summary_path": _portable_persistent_path(summary_path),
        "child_validation_checks_path": _portable_persistent_path(checks_path),
        "build_runtime_seconds": sum(
            float(row.get("build_runtime_seconds") or 0.0) for row in metrics
        ),
        "solve_runtime_seconds": sum(
            float(row.get("runtime_seconds") or 0.0) for row in metrics
        ),
    }


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate_config(config: Mapping[str, Any]) -> None:
    _full_matrix_authorization_metadata(config)
    if config.get("run_id") != EXPECTED_RUN_ID:
        raise SaleSensitivityError("Unexpected Phase-2 run_id.")
    if config.get("mode") != "c0_athanasiadis_electricity_sale_sensitivity":
        raise SaleSensitivityError("Unexpected Phase-2 mode.")
    if config.get("output_policy") != "minimal":
        raise SaleSensitivityError("Phase 2 requires output_policy=minimal.")
    experiment = config["experiment"]
    if experiment.get("expected_parent_head") != EXPECTED_HEAD:
        raise SaleSensitivityError("The Phase-2 parent fingerprint changed.")
    candidates = tuple(row["candidate_id"] for row in experiment["candidates"])
    scenarios = tuple(row["scenario_id"] for row in experiment["scenarios"])
    policies = tuple(row["policy_id"] for row in experiment["policies"])
    if candidates != EXPECTED_CANDIDATES or scenarios != EXPECTED_SCENARIOS:
        raise SaleSensitivityError("The frozen candidate/scenario matrix changed.")
    if policies != EXPECTED_POLICIES:
        raise SaleSensitivityError("The frozen sale-policy pair changed.")
    if (
        int(experiment["trajectory_count"]) != 8
        or int(experiment["replan_count"]) != 7
        or int(experiment["solver_model_count"]) != 112
    ):
        raise SaleSensitivityError("Phase 2 requires 8 trajectories, 7 replans and 112 C0/C1 models.")
    if experiment.get("held_out_periods_used") is not False or any(
        row["dataset_split"] != "validation"
        or row["price_field"] != "y_pred"
        or bool(row["perfect_foresight_oracle"])
        for row in experiment["scenarios"]
    ):
        raise SaleSensitivityError("Only governed validation y_pred is allowed.")
    try:
        resolve_policy_contract(experiment["validation_tolerance_policy"])
    except (KeyError, TypeError, ValidationTolerancePolicyError) as exc:
        raise SaleSensitivityError(
            "Phase 2 requires the canonical steel validation-tolerance "
            "policy identity."
        ) from exc
    immutable = experiment["immutable_phase1_contract"]
    expected = {
        "c0_background_percent": 30.0,
        "generator_electricity_efficiency": 0.345,
        "generator_electrical_capacity_mw": 770.0,
        "generator_total_fuel_volume_cap_nm3_h": 900000.0,
        "fixed_full_site_ng_pj_y": 8.005,
        "flexible_other_site_heat_service_min_pj_y": 0.0,
        "flexible_other_site_heat_service_max_pj_y": 3.07,
    }
    observed_immutable = {key: immutable[key] for key in expected}
    try:
        require_exact_input_fingerprint(
            observed_immutable,
            expected_fingerprint=exact_input_fingerprint(expected),
            purpose="Phase-1 immutable numeric inputs including NG",
        )
    except ValidationTolerancePolicyError as exc:
        raise SaleSensitivityError(
            "A frozen Phase-1 input fingerprint changed."
        ) from exc
    if immutable["wag_generation_yield_overrides_by_configuration"] != {} or any(
        bool(immutable[key])
        for key in (
            "carrier_mixing_allowed",
            "route_logic_changed",
            "operating_rules_changed",
            "initial_state_changed",
            "production_progress_contract_changed",
        )
    ):
        raise SaleSensitivityError("A frozen Phase-1 structural value changed.")
    authoritative_phase1_contract(config)


def frozen_case_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_config(config)
    return [
        {
            "case_id": f"sale__{candidate['candidate_id']}__{scenario['scenario_id']}__{policy['policy_id']}",
            "candidate_id": candidate["candidate_id"],
            "scenario_id": scenario["scenario_id"],
            "period_id": scenario["period_id"],
            "policy_id": policy["policy_id"],
            "sale_enabled": bool(policy["sale_enabled"]),
            "dataset_split": scenario["dataset_split"],
            "price_field": scenario["price_field"],
            "perfect_foresight_oracle": bool(scenario["perfect_foresight_oracle"]),
        }
        for candidate in config["experiment"]["candidates"]
        for scenario in config["experiment"]["scenarios"]
        for policy in config["experiment"]["policies"]
    ]


def execution_plan(
    config: Mapping[str, Any], execution_mode: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select cases and bounded rolling overrides without altering full-matrix scope."""

    full_matrix = frozen_case_matrix(config)
    if execution_mode == "full_matrix" or execution_mode == "aggregate_only":
        return list(full_matrix), {}
    first_candidate = EXPECTED_CANDIDATES[0]
    calm = EXPECTED_SCENARIOS[0]
    if execution_mode == "preflight_absent_disabled":
        base = next(
            row
            for row in full_matrix
            if row["candidate_id"] == first_candidate
            and row["scenario_id"] == calm
            and row["policy_id"] == "accepted_no_export_comparator"
        )
        cases = [
            base,
            {
                **base,
                "case_id": base["case_id"] + "__explicit_disabled",
                "policy_id": "explicit_disabled_preflight",
                "sale_enabled": False,
            },
        ]
    elif execution_mode in {"preflight_containment", "preflight_calm"}:
        cases = [
            row
            for row in full_matrix
            if row["candidate_id"] == first_candidate
            and row["scenario_id"] == calm
        ]
    elif execution_mode == "preflight_volatile_containment":
        cases = [
            row
            for row in full_matrix
            if row["candidate_id"] == first_candidate
            and row["scenario_id"] == EXPECTED_SCENARIOS[1]
        ]
    elif execution_mode == "preflight_volatile":
        cases = [
            row
            for row in full_matrix
            if row["candidate_id"] == first_candidate
            and row["scenario_id"] == EXPECTED_SCENARIOS[1]
        ]
        return cases, {
            "replan_count": VOLATILE_PREFIX_REPLAN_COUNT,
            "phase2_bounded_prefix_preflight": True,
            "phase2_bounded_prefix_target_replan": (
                VOLATILE_PREFIX_TARGET_REPLAN
            ),
            "phase2_bounded_prefix_preflight_mode": execution_mode,
        }
    else:
        raise SaleSensitivityError(f"Unknown execution mode: {execution_mode}")
    return cases, {
        "replan_count": 1,
        "phase2_single_window_preflight": True,
        "phase2_single_window_preflight_mode": execution_mode,
    }


def _prepare_attempt_output(
    output_root: Path,
    *,
    run_identity: Mapping[str, Any],
    execution_mode: str,
    diagnostic_case_id: str | None,
) -> tuple[Path, dict[str, Any]]:
    """Create an identity-scoped attempt without touching older root evidence."""

    scope = {
        **dict(run_identity),
        "execution_mode": execution_mode,
        "diagnostic_case_id": diagnostic_case_id,
    }
    attempt_id = (
        f"{str(run_identity['implementation_sha256'])[:16]}__"
        f"{_mapping_sha256(scope)[:12]}"
    )
    identity = {**scope, "attempt_id": attempt_id}
    attempt = output_root / "attempts" / attempt_id
    identity_path = attempt / "run_identity.json"
    if attempt.exists():
        if not identity_path.is_file() or json.loads(
            identity_path.read_text(encoding="utf-8")
        ) != identity:
            raise SaleSensitivityError(
                f"Existing attempt directory has unrelated identity: {attempt}"
            )
    else:
        attempt.mkdir(parents=True)
        _write_json(identity_path, identity)
    return attempt, identity


def policy_overrides(policy_id: str) -> dict[str, Any]:
    if policy_id == "accepted_no_export_comparator":
        return {}
    if policy_id != "athanasiadis_sale_enabled":
        raise SaleSensitivityError(f"Unknown sale policy: {policy_id}")
    return {
        "c0_electricity_sale_sensitivity": {
            "enabled": True,
            "policy_id": policy_id,
            "price_basis": "same_governed_y_pred_as_import",
            "revenue_scope": "gross_grid_export_only",
            "carrier_attribution": "not_invented",
            "settlement_claim": False,
        }
    }


def implementation_fingerprints(config_path: str | Path) -> dict[str, Any]:
    paths = (
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_hourly_da_dplus4_point_forecast_integration.yaml",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_real_anchor_mechanism_experiment.yaml",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/validation_tolerance_policy.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_c0_athanasiadis_sale_sensitivity.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/tests/test_s4_4c5p_c0_athanasiadis_sale_sensitivity.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/tests/test_s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/tests/test_validation_tolerance_policy.py",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/baseline_freeze.json",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/user_authorized_emulation_anchor_overlay.csv",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/user_authorized_emulation_parameter_overlay.csv",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md",
    )
    return {
        "expected_parent_head": EXPECTED_HEAD,
        "current_head": _git_head(),
        "supported_execution_modes": list(SUPPORTED_EXECUTION_MODES),
        "working_tree_diff_sha256": _git_diff_sha256(),
        "semantic_config_fingerprint": _semantic_config_fingerprint(
            config_path
        ),
        "sale_state_preservation_specification": {
            "schema_version": "steel_phase2_sale_state_preservation_v3",
            "configuration_id": "C0_current_BF_BOF_reference",
            "operational_constraint": "full_precision_exact_equality",
            "final_validation": "independent_state_acceptance",
            "allowed_tolerance_t": TERMINAL_STATE_TOLERANCE_T,
            "target_schema": [
                "executed_final_product_t",
                "coke_inventory_t",
                "sinter_inventory_t",
                "hot_iron_inventory_t",
                "cold_slab_inventory_t",
            ],
        },
        "files": [
            {"path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(path)}
            for path in paths
        ],
    }


def authoritative_phase1_contract(config: Mapping[str, Any]) -> dict[str, Any]:
    root = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract"
    anchors = {row["overlay_id"]: row for row in _read_csv(root / "user_authorized_emulation_anchor_overlay.csv")}
    parameters = {row["parameter_id"]: row for row in _read_csv(root / "user_authorized_emulation_parameter_overlay.csv")}
    observed = {
        "c0_background_percent": 100.0 * float(anchors["phase1_c0_background_central"]["value_central"]),
        "generator_electricity_efficiency": float(parameters["uae_c0_generator_efficiency"]["baseline_central"]),
        "generator_electrical_capacity_mw": float(parameters["real_anchor_c0_generator_electrical_capacity"]["baseline_central"]),
        "generator_total_fuel_volume_cap_nm3_h": float(parameters["real_anchor_c0_generator_mixed_volume_envelope"]["baseline_central"]),
        "fixed_full_site_ng_pj_y": float(anchors["real_anchor_c0_inferred_low_case_ng_floor"]["value_central"]),
        "flexible_other_site_heat_service_min_pj_y": float(anchors["phase1_c0_flexible_heat_ng_allocation_envelope"]["value_low"]),
        "flexible_other_site_heat_service_max_pj_y": float(anchors["phase1_c0_flexible_heat_ng_allocation_envelope"]["value_high"]),
        "total_wag_low_pj_y": float(anchors["phase1_c0_total_wag_current"]["value_low"]),
        "total_wag_high_pj_y": float(anchors["phase1_c0_total_wag_current"]["value_high"]),
    }
    frozen = config["experiment"]["immutable_phase1_contract"]
    authoritative_keys = (
        "c0_background_percent", "generator_electricity_efficiency",
        "generator_electrical_capacity_mw", "generator_total_fuel_volume_cap_nm3_h",
        "fixed_full_site_ng_pj_y", "flexible_other_site_heat_service_min_pj_y",
        "flexible_other_site_heat_service_max_pj_y",
    )
    observed_inputs = {key: observed[key] for key in authoritative_keys}
    frozen_inputs = {key: float(frozen[key]) for key in authoritative_keys}
    try:
        require_exact_input_fingerprint(
            frozen_inputs,
            expected_fingerprint=exact_input_fingerprint(observed_inputs),
            purpose="authoritative Phase-1 source/YAML inputs including NG",
        )
    except ValidationTolerancePolicyError as exc:
        raise SaleSensitivityError(
            "Phase-1 YAML/authoritative input fingerprint mismatch."
        ) from exc
    return observed


def electricity_guardrails(
    rows: Iterable[Mapping[str, Any]],
    *,
    sale_enabled: bool,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if str(row.get("configuration_id", "")).startswith("C0_")
    ]
    def maximum(fn: Any) -> float:
        return max((float(fn(row)) for row in selected), default=float("inf"))

    identity = maximum(
        lambda row: abs(
            float(row.get("WAG_generator_electricity_mwh") or 0.0)
            + float(row.get("NG_generator_electricity_mwh") or 0.0)
            + float(row.get("gross_grid_import_mwh") or 0.0)
            - float(row.get("gross_total_electricity_mwh") or 0.0)
            - float(row.get("gross_grid_export_mwh") or 0.0)
        )
    )
    simultaneous = maximum(
        lambda row: min(
            float(row.get("gross_grid_import_mwh") or 0.0),
            float(row.get("gross_grid_export_mwh") or 0.0),
        )
    )
    reexport = maximum(
        lambda row: max(
            0.0,
            float(row.get("gross_grid_import_mwh") or 0.0)
            - float(row.get("gross_total_electricity_mwh") or 0.0),
        )
    )
    export_bound = maximum(
        lambda row: max(
            0.0,
            float(row.get("gross_grid_export_mwh") or 0.0)
            - float(row.get("total_generator_electricity_mwh") or 0.0),
        )
    )
    generator_split = maximum(
        lambda row: abs(
            float(row.get("WAG_generator_electricity_mwh") or 0.0)
            + float(row.get("NG_generator_electricity_mwh") or 0.0)
            - float(row.get("total_generator_electricity_mwh") or 0.0)
        )
    )
    comparator_export = maximum(
        lambda row: abs(float(row.get("gross_grid_export_mwh") or 0.0))
    )
    checks = {
        "electricity_identity": identity,
        "no_simultaneous_import_export": simultaneous,
        "no_grid_reexport": reexport,
        "export_bounded_by_internal_generation": export_bound,
        "wag_and_ng_generation_exactly_separate": generator_split,
        "accepted_comparator_export_zero": (
            0.0 if sale_enabled else comparator_export
        ),
    }
    records: list[dict[str, Any]] = []
    for name, residual in checks.items():
        comparison = threshold_comparison_record(
            validation_id=f"trajectory_max[{name}]",
            purpose=name,
            raw_residual=residual,
        )
        records.append(
            {
                "guardrail": name,
                "max_residual": residual,
                **comparison,
            }
        )
    return records


def executed_sale_accounting(
    rows: Iterable[Mapping[str, Any]],
    prices: Mapping[tuple[int, int], float],
) -> dict[str, float]:
    import_cost = 0.0
    export_revenue = 0.0
    generation = 0.0
    for row in rows:
        if not str(row.get("configuration_id", "")).startswith("C0_"):
            continue
        key = (int(row["replan_index"]), int(row["hour_index"]))
        price = float(prices[key])
        imported = float(row.get("gross_grid_import_mwh") or 0.0)
        exported = float(row.get("gross_grid_export_mwh") or 0.0)
        import_cost += imported * price
        export_revenue += exported * price
        generation += float(row.get("total_generator_electricity_mwh") or 0.0)
    return {
        "executed_import_cost_eur": import_cost,
        "executed_export_revenue_eur": export_revenue,
        "executed_net_electricity_cost_eur": import_cost - export_revenue,
        "executed_internal_generation_mwh": generation,
    }


def negative_price_export_coherence(
    rows: Iterable[Mapping[str, Any]],
    *,
    require_negative_hour: bool,
    target_replan: int | None,
    validation_scope: str,
    tolerance: float = ELECTRICITY_BALANCE_TOLERANCE_MWH,
) -> dict[str, Any]:
    """Audit every executed C0 negative-price hour without an empty-set pass."""

    failures: list[str] = []
    c0_rows: list[Mapping[str, Any]] = []
    for row in rows:
        configuration = row.get("configuration_id")
        if configuration in {None, ""}:
            failures.append("missing_configuration_id")
            continue
        if str(configuration).startswith("C0_"):
            c0_rows.append(row)
    if not c0_rows:
        failures.append("missing_c0_executed_rows")

    valid_prices: list[float] = []
    negative_rows: list[tuple[int, float, float]] = []
    for row_index, row in enumerate(c0_rows):
        try:
            raw_replan = row["replan_index"]
            replan = int(raw_replan)
            if (
                isinstance(raw_replan, bool)
                or float(raw_replan) != float(replan)
                or replan < 0
            ):
                raise ValueError("invalid replan")
            raw_price = row["electricity_sale_price_eur_per_mwh"]
            raw_export = row["gross_grid_export_mwh"]
            if raw_price in {None, ""} or raw_export in {None, ""}:
                raise ValueError("missing price/export")
            price = float(raw_price)
            exported = float(raw_export)
            if not math.isfinite(price) or not math.isfinite(exported):
                raise ValueError("nonfinite price/export")
            if exported < -tolerance:
                raise ValueError("negative gross export")
        except (KeyError, TypeError, ValueError):
            failures.append(f"malformed_c0_executed_row:{row_index}")
            continue
        valid_prices.append(price)
        if price < 0.0:
            negative_rows.append((replan, price, exported))

    negative_replans = sorted({row[0] for row in negative_rows})
    max_negative_export = max(
        (row[2] for row in negative_rows), default=0.0
    )
    if require_negative_hour and not negative_rows:
        failures.append("required_negative_executed_hour_absent")
    if target_replan is not None and target_replan not in negative_replans:
        failures.append("target_replan_has_no_negative_executed_hour")
    if any(row[2] > tolerance for row in negative_rows):
        failures.append("export_above_tolerance_at_negative_price")
    return {
        "guardrail": "negative_price_export_coherence",
        "status": "pass" if not failures else "fail",
        "validation_scope": validation_scope,
        "failure_reasons": ";".join(sorted(set(failures))),
        "negative_hour_count": len(negative_rows),
        "negative_replan_indices": ";".join(
            str(index) for index in negative_replans
        ),
        "target_replan": "" if target_replan is None else target_replan,
        "min_executed_price": min(valid_prices) if valid_prices else "",
        "max_negative_hour_export": max_negative_export,
        "max_residual": max_negative_export,
    }


def _negative_price_validation_contract(
    execution_mode: str, *, volatile: bool
) -> dict[str, Any]:
    """Scope negative-price claims independently from containment smoke tests."""

    evaluate = execution_mode in {
        "preflight_containment",
        "preflight_calm",
        "preflight_volatile",
        "full_matrix",
    }
    claim_eligible = execution_mode in {"preflight_volatile", "full_matrix"}
    if not evaluate:
        return {
            "claimed": False,
            "evaluate": False,
            "require_negative_hour": False,
            "target_replan": None,
            "validation_scope": (
                "not_evaluated_volatile_replan_0_containment_only"
                if execution_mode == "preflight_volatile_containment"
                else "not_evaluated_no_sale_trajectory"
            ),
        }
    return {
        "claimed": claim_eligible,
        "evaluate": True,
        "require_negative_hour": volatile and claim_eligible,
        "target_replan": (
            VOLATILE_PREFIX_TARGET_REPLAN
            if execution_mode == "preflight_volatile"
            else None
        ),
        "validation_scope": (
            "volatile_bounded_prefix_replans_0_through_4"
            if execution_mode == "preflight_volatile"
            else "volatile_full_trajectory_all_executed_hours"
            if volatile
            else "calm_all_executed_hours_if_any_negative"
        ),
    }


def _negative_price_validation_claimed(
    execution_mode: str,
    guardrails: Iterable[Mapping[str, Any]],
) -> bool:
    """Return a negative-price claim only from complete, non-vacuous evidence."""

    if execution_mode not in {"preflight_volatile", "full_matrix"}:
        return False
    rows = [
        row
        for row in guardrails
        if row.get("guardrail") == "negative_price_export_coherence"
    ]
    expected_count = (
        1
        if execution_mode == "preflight_volatile"
        else len(EXPECTED_CANDIDATES) * len(EXPECTED_SCENARIOS)
    )
    required_rows = [row for row in rows if row.get("negative_hour_required") is True]
    return bool(
        len(rows) == expected_count
        and required_rows
        and all(row.get("status") == "pass" for row in rows)
        and all(int(row.get("negative_hour_count") or 0) > 0 for row in required_rows)
    )


def handoff_continuity(
    rows: Iterable[Mapping[str, Any]],
    tolerance: float = TERMINAL_STATE_TOLERANCE_T,
    *,
    phase2_single_window_preflight: bool = False,
    expected_replan_count: int | None = None,
) -> dict[str, Any]:
    materialized = list(rows)
    if expected_replan_count is None:
        expected_replan_count = (
            max((int(row["replan_index"]) for row in materialized), default=-1) + 1
        )
    return _validate_inventory_handoff_contract(
        materialized,
        replan_count=expected_replan_count,
        phase2_single_window_preflight=phase2_single_window_preflight,
        tolerance=tolerance,
    )


def _expected_containment_replan_indices(
    experiment: Mapping[str, Any],
    bounded_preflight_overrides: Mapping[str, Any],
) -> tuple[int, ...]:
    """Resolve containment scope only from the explicit execution contract."""

    try:
        frozen_count = int(experiment["replan_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SaleSensitivityError(
            "Containment requires the frozen full-matrix replan count."
        ) from exc
    if frozen_count != 7:
        raise SaleSensitivityError(
            "Containment full-matrix scope changed from exact replans 0..6."
        )
    overrides = dict(bounded_preflight_overrides)
    if not overrides:
        return tuple(range(frozen_count))
    single_keys = {
        "replan_count",
        "phase2_single_window_preflight",
        "phase2_single_window_preflight_mode",
    }
    prefix_keys = {
        "replan_count",
        "phase2_bounded_prefix_preflight",
        "phase2_bounded_prefix_target_replan",
        "phase2_bounded_prefix_preflight_mode",
    }
    single_modes = {
        "preflight_absent_disabled",
        "preflight_containment",
        "preflight_calm",
        "preflight_volatile_containment",
    }
    try:
        if set(overrides) == single_keys:
            valid_single = bool(
                overrides["phase2_single_window_preflight"] is True
                and int(overrides["replan_count"]) == 1
                and overrides["phase2_single_window_preflight_mode"]
                in single_modes
            )
            if valid_single:
                return (0,)
        elif set(overrides) == prefix_keys:
            valid_prefix = bool(
                overrides["phase2_bounded_prefix_preflight"] is True
                and int(overrides["replan_count"])
                == VOLATILE_PREFIX_REPLAN_COUNT
                and int(overrides["phase2_bounded_prefix_target_replan"])
                == VOLATILE_PREFIX_TARGET_REPLAN
                and overrides["phase2_bounded_prefix_preflight_mode"]
                == "preflight_volatile"
            )
            if valid_prefix:
                return tuple(range(VOLATILE_PREFIX_REPLAN_COUNT))
    except (TypeError, ValueError):
        pass
    raise SaleSensitivityError(
        "Containment scope is contradictory, shortened without an explicit "
        "contract, or differs from the governed single-window/prefix/full scope."
    )


def _validate_containment_records(
    containment_root: Path,
    *,
    expected_replan_indices: Collection[int],
) -> dict[str, Any]:
    """Require one passing governed containment record for every expected replan."""

    expected = tuple(sorted(int(index) for index in expected_replan_indices))
    if (
        not expected
        or len(set(expected)) != len(expected)
        or any(index < 0 for index in expected)
    ):
        raise SaleSensitivityError(
            "Expected containment replan indices must be nonempty, unique, and nonnegative."
        )
    expected_relative_paths = {
        f"replan_{index:02d}/sale_incumbent_containment.json": index
        for index in expected
    }
    record_paths = sorted(
        containment_root.rglob("sale_incumbent_containment.json"),
        key=lambda path: path.relative_to(containment_root).as_posix(),
    ) if containment_root.is_dir() else []
    actual_relative_paths = [
        path.relative_to(containment_root).as_posix() for path in record_paths
    ]
    parsed_indices: list[int] = []
    passed_record_count = 0
    failed_or_malformed_paths: list[str] = []
    for path, relative in zip(record_paths, actual_relative_paths, strict=True):
        parts = Path(relative).parts
        directory = parts[0] if len(parts) == 2 else ""
        suffix = directory.removeprefix("replan_")
        if directory.startswith("replan_") and suffix.isdigit():
            parsed_indices.append(int(suffix))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failed_or_malformed_paths.append(relative)
            continue
        if not isinstance(payload, Mapping) or payload.get("status") != "pass":
            failed_or_malformed_paths.append(relative)
            continue
        passed_record_count += 1
    actual_path_set = set(actual_relative_paths)
    missing_paths = sorted(set(expected_relative_paths).difference(actual_path_set))
    extra_paths = sorted(actual_path_set.difference(expected_relative_paths))
    duplicate_indices = sorted(
        index for index in set(parsed_indices) if parsed_indices.count(index) > 1
    )
    checked_indices = sorted(set(parsed_indices))
    preservation_missing_paths: list[str] = []
    preservation_failed_paths: list[str] = []
    preservation_passed_count = 0
    preservation_max_residual = 0.0
    target_schema = (
        "executed_final_product_t",
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    )
    state_schema = [
        {
            "target_id": target_id,
            "model_component": (
                "final_product_output"
                if target_id == "executed_final_product_t"
                else target_id.removesuffix("_t")
            ),
            "selection": (
                "sum_executed_hours"
                if target_id == "executed_final_product_t"
                else "handoff_hour"
            ),
            "unit": "t",
            "operational_constraint": "full_precision_exact_equality",
            "final_validation": "independent_state_acceptance",
            "allowed_tolerance_t": TERMINAL_STATE_TOLERANCE_T,
        }
        for target_id in target_schema
    ]
    constraint_names = {
        target_id: f"sale_state_{stem}_preservation_exact"
        for target_id, stem in {
            "executed_final_product_t": "executed_final_product",
            "coke_inventory_t": "coke_inventory",
            "sinter_inventory_t": "sinter_inventory",
            "hot_iron_inventory_t": "hot_iron_inventory",
            "cold_slab_inventory_t": "cold_slab_inventory",
        }.items()
    }
    target_bounds = {
        target_id: {
            "lower_bound_t": None,
            "upper_bound_t": None,
        }
        for target_id in target_schema
    }
    for index in expected:
        directory = containment_root / f"replan_{index:02d}"
        containment_path = directory / "sale_incumbent_containment.json"
        pre_path = directory / "sale_state_preservation_pre_solve.json"
        final_path = directory / "sale_state_preservation_final.json"
        economic_overlay_path = (
            directory / "sale_economic_validation_overlay.json"
        )
        for path in (pre_path, final_path, economic_overlay_path):
            if not path.is_file():
                preservation_missing_paths.append(
                    path.relative_to(containment_root).as_posix()
                )
        if (
            not containment_path.is_file()
            or not pre_path.is_file()
            or not final_path.is_file()
            or not economic_overlay_path.is_file()
        ):
            continue
        try:
            pre = json.loads(pre_path.read_text(encoding="utf-8"))
            final = json.loads(final_path.read_text(encoding="utf-8"))
            economic_overlay = json.loads(
                economic_overlay_path.read_text(encoding="utf-8")
            )
            targets = {key: float(pre["targets"][key]) for key in target_schema}
            target_bounds = {
                key: {
                    "lower_bound_t": float(
                        pre["target_bounds"][key]["lower_bound_t"]
                    ),
                    "upper_bound_t": float(
                        pre["target_bounds"][key]["upper_bound_t"]
                    ),
                }
                for key in target_schema
            }
            actuals = {key: float(final["actual_values"][key]) for key in target_schema}
            signed_residuals = {
                key: float(final["signed_residuals"][key])
                for key in target_schema
            }
            residuals = {
                key: float(final["absolute_residuals"][key])
                for key in target_schema
            }
            normalized_residuals = {
                key: float(final["normalized_residuals"][key])
                for key in target_schema
            }
            calculated_residuals = {
                key: abs(actuals[key] - targets[key]) for key in target_schema
            }
            calculated_signed_residuals = {
                key: actuals[key] - targets[key] for key in target_schema
            }
            expected_target_bounds = {
                key: {
                    "lower_bound_t": targets[key] - TERMINAL_STATE_TOLERANCE_T,
                    "upper_bound_t": targets[key] + TERMINAL_STATE_TOLERANCE_T,
                }
                for key in target_schema
            }
            per_state = dict(final["per_state_validation"])
            economic_rows = list(economic_overlay["rows"])
            max_residual = max(calculated_residuals.values(), default=math.inf)
            implementation_sha = str(pre["implementation_sha256"])
            provenance = dict(pre["source_capture_provenance"])
            valid = bool(
                pre.get("schema_version") == "steel_phase2_sale_state_preservation_v3"
                and final.get("schema_version") == pre.get("schema_version")
                and pre.get("status") == "targets_applied_pending_economic_solve"
                and final.get("status") == "pass"
                and pre.get("configuration_id") == "C0_current_BF_BOF_reference"
                and final.get("configuration_id") == pre.get("configuration_id")
                and int(pre.get("replan_index", -1)) == index
                and int(final.get("replan_index", -1)) == index
                and tuple(pre.get("target_schema", ())) == target_schema
                and tuple(final.get("target_schema", ())) == target_schema
                and set(pre.get("targets", {})) == set(target_schema)
                and set(final.get("actual_values", {})) == set(target_schema)
                and set(final.get("signed_residuals", {})) == set(target_schema)
                and set(final.get("absolute_residuals", {})) == set(target_schema)
                and set(final.get("normalized_residuals", {})) == set(target_schema)
                and set(per_state) == set(target_schema)
                and all(math.isfinite(value) for value in (*targets.values(), *actuals.values(), *signed_residuals.values(), *residuals.values(), *normalized_residuals.values()))
                and target_bounds == expected_target_bounds
                and pre.get("target_bounds_sha256") == _mapping_sha256(target_bounds)
                and final.get("target_bounds_sha256") == pre.get("target_bounds_sha256")
                and all(signed_residuals[key] == calculated_signed_residuals[key] for key in target_schema)
                and all(residuals[key] == calculated_residuals[key] for key in target_schema)
                and all(normalized_residuals[key] == calculated_residuals[key] / TERMINAL_STATE_TOLERANCE_T for key in target_schema)
                and all(
                    per_state[key].get("status") == "pass"
                    and per_state[key].get("aggregation") == "independent_state_no_accumulation"
                    and float(per_state[key].get("allowed_tolerance_t", math.inf)) == TERMINAL_STATE_TOLERANCE_T
                    and float(per_state[key].get("signed_residual_t", math.inf)) == calculated_signed_residuals[key]
                    and float(per_state[key].get("absolute_residual_t", math.inf)) == calculated_residuals[key]
                    and float(per_state[key].get("normalized_residual", math.inf)) == normalized_residuals[key]
                    for key in target_schema
                )
                and max_residual <= TERMINAL_STATE_TOLERANCE_T
                and float(final.get("max_residual", math.inf)) == max_residual
                and pre.get("targets_sha256") == _mapping_sha256(targets)
                and final.get("targets_sha256") == pre.get("targets_sha256")
                and pre.get("state_schema") == state_schema
                and pre.get("state_schema_sha256") == _mapping_sha256(state_schema)
                and final.get("state_schema_sha256") == pre.get("state_schema_sha256")
                and pre.get("constraint_names") == constraint_names
                and pre.get("constraint_names_sha256") == _mapping_sha256(constraint_names)
                and final.get("constraint_names_sha256") == pre.get("constraint_names_sha256")
                and pre.get("containment_record_sha256") == _sha256(containment_path)
                and final.get("containment_record_sha256") == pre.get("containment_record_sha256")
                and final.get("pre_solve_evidence_sha256") == _sha256(pre_path)
                and len(implementation_sha) == 64
                and provenance.get("implementation_sha256") == implementation_sha
                and len(str(pre.get("source_capture_sha256", ""))) == 64
                and economic_overlay.get("schema_version")
                == "steel_sale_economic_validation_overlay_v2"
                and economic_overlay.get("status") == "pass"
                and economic_overlay.get("policy")
                == {
                    "policy_id": VALIDATION_TOLERANCE_POLICY_ID,
                    "policy_version": VALIDATION_TOLERANCE_POLICY_VERSION,
                    "policy_fingerprint_sha256": (
                        VALIDATION_TOLERANCE_POLICY_FINGERPRINT
                    ),
                }
                and economic_overlay.get("underlying_core_unchanged") is True
                and economic_overlay.get("underlying_core_sha256_before")
                == economic_overlay.get("underlying_core_sha256_after_install")
                and int(
                    economic_overlay.get("registered_acceptance_row_count", -1)
                )
                == len(economic_rows)
                and int(
                    economic_overlay.get("failed_validation_row_count", -1)
                )
                == 0
                and economic_overlay.get("rows_sha256")
                == _mapping_sha256(economic_rows)
                and all(_valid_sale_economic_overlay_row(row) for row in economic_rows)
            )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            valid = False
            max_residual = math.inf
        if not valid:
            preservation_failed_paths.extend(
                path.relative_to(containment_root).as_posix()
                for path in (pre_path, final_path, economic_overlay_path)
            )
            continue
        preservation_passed_count += 1
        preservation_max_residual = max(
            preservation_max_residual, max_residual
        )
    failure_reasons: list[str] = []
    if missing_paths:
        failure_reasons.append("missing_expected_record")
    if extra_paths:
        failure_reasons.append("extra_or_wrong_directory_record")
    if duplicate_indices:
        failure_reasons.append("duplicate_equivalent_replan_index")
    if failed_or_malformed_paths:
        failure_reasons.append("failed_or_malformed_record")
    if len(record_paths) != len(expected):
        failure_reasons.append("record_count_mismatch")
    if preservation_missing_paths:
        failure_reasons.append("missing_state_preservation_evidence")
    if preservation_failed_paths:
        failure_reasons.append("failed_state_preservation_evidence")
    if preservation_passed_count != len(expected):
        failure_reasons.append("state_preservation_record_count_mismatch")
    passed = bool(
        not failure_reasons
        and passed_record_count == len(expected)
        and preservation_passed_count == len(expected)
    )
    return {
        "status": "pass" if passed else "fail",
        "max_residual": (
            preservation_max_residual
            if passed
            else "missing_or_failed_record"
        ),
        "expected_record_count": len(expected),
        "checked_record_count": len(record_paths),
        "passed_record_count": passed_record_count,
        "expected_replan_indices": ";".join(str(index) for index in expected),
        "checked_replan_indices": ";".join(
            str(index) for index in checked_indices
        ),
        "record_paths": ";".join(actual_relative_paths),
        "missing_record_paths": ";".join(missing_paths),
        "extra_record_paths": ";".join(extra_paths),
        "failed_or_malformed_record_paths": ";".join(
            failed_or_malformed_paths
        ),
        "duplicate_replan_indices": ";".join(
            str(index) for index in duplicate_indices
        ),
        "failure_reasons": ";".join(failure_reasons),
        "state_preservation_passed_record_count": (
            preservation_passed_count
        ),
        "state_preservation_missing_paths": ";".join(
            preservation_missing_paths
        ),
        "state_preservation_failed_paths": ";".join(
            preservation_failed_paths
        ),
    }


def cross_policy_state_guardrails(
    comparator_execution: Iterable[Mapping[str, Any]],
    sale_execution: Iterable[Mapping[str, Any]],
    comparator_handoff: Iterable[Mapping[str, Any]],
    sale_handoff: Iterable[Mapping[str, Any]],
    comparator_progress: Iterable[Mapping[str, Any]],
    sale_progress: Iterable[Mapping[str, Any]],
    *,
    tolerance: float = TERMINAL_STATE_TOLERANCE_T,
) -> list[dict[str, Any]]:
    def keyed(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], Mapping[str, Any]]:
        return {
            (str(row["configuration_id"]), int(row["replan_index"])): row
            for row in rows
        }

    comp_exec, sale_exec = keyed(comparator_execution), keyed(sale_execution)
    comp_handoff, sale_handoff_rows = keyed(comparator_handoff), keyed(sale_handoff)
    comp_progress, sale_progress_rows = keyed(comparator_progress), keyed(sale_progress)
    if not (
        set(comp_exec) == set(sale_exec)
        and set(comp_handoff) == set(sale_handoff_rows)
        and set(comp_progress) == set(sale_progress_rows)
    ):
        return [{"guardrail": "cross_policy_key_set", "status": "fail", "max_residual": "key_mismatch"}]
    production_residual = 0.0
    progress_residual = 0.0
    handoff_residual = 0.0
    terminal_handoff_residual = 0.0
    handoff_fields: set[str] = set()
    for key in comp_exec:
        for field in ("executed_final_product_t", "cumulative_executed_final_product_t"):
            production_residual = max(
                production_residual,
                abs(float(comp_exec[key][field]) - float(sale_exec[key][field])),
            )
    for key in comp_progress:
        required_progress_fields = (
            "executed_before_t", "cumulative_executed_after_t",
            "carried_credit_before_t", "carried_credit_after_t",
            "executed_block_t",
        )
        if any(
            field not in comp_progress[key] or field not in sale_progress_rows[key]
            for field in required_progress_fields
        ):
            return [{"guardrail": "cross_policy_cumulative_progress_schema", "status": "fail", "max_residual": "missing_field"}]
        for field in required_progress_fields:
            progress_residual = max(
                progress_residual,
                abs(float(comp_progress[key][field]) - float(sale_progress_rows[key][field])),
            )
    for key in comp_handoff:
        expected_terminal_schema = HANDOFF_STATE_SCHEMA_BY_CONFIGURATION[key[0]]
        for container in ("start_overrides", "next_overrides"):
            left = json.loads(str(comp_handoff[key][container]))
            right = json.loads(str(sale_handoff_rows[key][container]))
            if set(left) != set(right):
                return [{"guardrail": "cross_policy_dynamic_handoff_schema", "status": "fail", "max_residual": "key_mismatch"}]
            if container == "next_overrides" and (
                set(left) != expected_terminal_schema
                or not all(math.isfinite(float(value)) for value in left.values())
                or not all(math.isfinite(float(value)) for value in right.values())
            ):
                return [{"guardrail": "cross_policy_terminal_handoff_schema", "status": "fail", "max_residual": "incomplete_or_nonfinite"}]
            handoff_fields.update(left)
            for field in left:
                residual = abs(float(left[field]) - float(right[field]))
                handoff_residual = max(handoff_residual, residual)
                if container == "next_overrides":
                    terminal_handoff_residual = max(
                        terminal_handoff_residual, residual
                    )
    return [
        {"guardrail": "cross_policy_executed_and_cumulative_production", "status": "pass" if production_residual <= tolerance else "fail", "max_residual": production_residual},
        {"guardrail": "cross_policy_cumulative_progress_state", "status": "pass" if progress_residual <= tolerance else "fail", "max_residual": progress_residual},
        {"guardrail": "cross_policy_terminal_handoff_snapshot_every_dynamic_state", "status": "pass" if terminal_handoff_residual <= tolerance and handoff_fields else "fail", "max_residual": terminal_handoff_residual},
        {"guardrail": "cross_policy_every_dynamic_handoff_state", "status": "pass" if handoff_residual <= tolerance and handoff_fields else "fail", "max_residual": handoff_residual, "fields": ";".join(sorted(handoff_fields))},
    ]


def absent_disabled_result_equivalence(
    comparator_rows: Iterable[Mapping[str, Any]],
    disabled_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare genuine closed-loop solve results, excluding runtime noise."""

    def keyed(
        rows: Iterable[Mapping[str, Any]],
    ) -> dict[tuple[str, int], Mapping[str, Any]]:
        result: dict[tuple[str, int], Mapping[str, Any]] = {}
        for row in rows:
            key = (str(row["configuration_id"]), int(row["replan_index"]))
            if key in result:
                raise SaleSensitivityError(
                    "Absent/disabled result evidence has duplicate model keys."
                )
            result[key] = row
        return result

    try:
        comparator = keyed(comparator_rows)
        disabled = keyed(disabled_rows)
    except (KeyError, TypeError, ValueError, SaleSensitivityError) as exc:
        return {
            "guardrail": "absent_vs_explicit_disabled_result_equivalence",
            "status": "fail",
            "max_residual": "malformed_model_result",
            "checked_model_count": 0,
            "failure_reasons": type(exc).__name__,
        }
    if not comparator or set(comparator) != set(disabled):
        return {
            "guardrail": "absent_vs_explicit_disabled_result_equivalence",
            "status": "fail",
            "max_residual": "key_mismatch",
            "checked_model_count": 0,
            "failure_reasons": "model_result_key_mismatch",
        }
    text_fields = ("solver_status", "termination_condition")
    numeric_fields = (
        "objective_value",
        "primary_cost_objective_eur",
        "production_progress_actual_t",
        "production_progress_surplus_t",
        "production_progress_deficit_t",
    )
    failures: list[str] = []
    max_residual = 0.0
    for key in sorted(comparator):
        left, right = comparator[key], disabled[key]
        for field in text_fields:
            if field not in left or field not in right or str(left[field]) != str(
                right[field]
            ):
                failures.append(f"text_mismatch:{key}:{field}")
        for field in numeric_fields:
            if field not in left or field not in right:
                failures.append(f"missing_numeric:{key}:{field}")
                continue
            left_value, right_value = left[field], right[field]
            if left_value in {None, ""} and right_value in {None, ""}:
                continue
            try:
                residual = abs(float(left_value) - float(right_value))
            except (TypeError, ValueError):
                failures.append(f"nonnumeric:{key}:{field}")
                continue
            if not math.isfinite(residual):
                failures.append(f"nonfinite:{key}:{field}")
                continue
            if field in {"objective_value", "primary_cost_objective_eur"}:
                comparison = trajectory_cost_record(
                    f"absent_disabled[{key},{field}]",
                    residual,
                    comparison_scale_eur=max(
                        abs(float(left_value)), abs(float(right_value))
                    ),
                )
            else:
                comparison = validation_record(
                    validation_id=f"absent_disabled[{key},{field}]",
                    purpose="cumulative_production_or_carried_state",
                    unit="t",
                    raw_residual=residual,
                    allowed_tolerance=TERMINAL_STATE_TOLERANCE_T,
                    aggregation="per_state_no_accumulation",
                )
            max_residual = max(max_residual, residual)
            if comparison["status"] != "pass":
                failures.append(f"numeric_mismatch:{key}:{field}")
    return {
        "guardrail": "absent_vs_explicit_disabled_result_equivalence",
        "status": "pass" if not failures else "fail",
        "max_residual": max_residual,
        "checked_model_count": len(comparator),
        "failure_reasons": ";".join(failures),
    }


def trajectory_metrics(
    hourly_rows: Iterable[Mapping[str, Any]],
    cost_rows: Iterable[Mapping[str, Any]],
) -> dict[str, float]:
    hourly = [row for row in hourly_rows if str(row.get("configuration_id", "")).startswith("C0_")]
    costs = [row for row in cost_rows if str(row.get("configuration_id", "")).startswith("C0_")]
    total = lambda field: sum(float(row.get(field) or 0.0) for row in hourly)
    wag_only = total("WAG_generator_electricity_mwh")
    executed_hours = len(hourly)
    import_cost = sum(float(row["cost_eur"]) for row in costs if row["flow_id"] == "C0_EL_GRID")
    export_revenue = -sum(float(row["cost_eur"]) for row in costs if row["flow_id"] == "C0_EL_EXPORT")
    named_ng_cost = sum(
        float(row["cost_eur"])
        for row in costs
        if "NG" in str(row["flow_id"]).upper() and row["flow_id"] != "C0_EL_EXPORT"
    )
    represented_net = sum(float(row["cost_eur"]) for row in costs)
    annual_wag_twh = wag_only * 8760.0 / executed_hours / 1_000_000.0 if executed_hours else 0.0
    return {
        "executed_hours": float(executed_hours),
        "wag_only_generator_electricity_mwh": wag_only,
        "ng_generator_electricity_mwh": total("NG_generator_electricity_mwh"),
        "gross_grid_import_mwh": total("gross_grid_import_mwh"),
        "gross_grid_export_mwh": total("gross_grid_export_mwh"),
        "signed_net_grid_exchange_mwh": total("net_grid_exchange_mwh"),
        "export_revenue_eur": export_revenue,
        "import_cost_eur": import_cost,
        "named_ng_cost_eur": named_ng_cost,
        "represented_net_cost_eur": represented_net,
        "wag_allocation_mwh": total("WAG_used"),
        "generator_ng_mwh": total("generator_named_ng_mwh"),
        "flexible_heat_ng_mwh": total("flexible_other_site_heat_ng_mwh"),
        "fixed_ng_mwh": total("full_site_fixed_ng_component_mwh"),
        "total_wag_mwh": total("WAG_generated"),
        "wag_anchor_annual_twh": annual_wag_twh,
        "wag_anchor_deviation_twh": annual_wag_twh - 2.528,
        "final_product_t": total("final_product_output_t"),
    }


def _trajectory_metric_equivalence(
    comparator_metrics: Mapping[str, float],
    disabled_metrics: Mapping[str, float],
) -> dict[str, Any]:
    if set(comparator_metrics) != set(disabled_metrics):
        return {
            "status": "fail",
            "max_residual": "key_mismatch",
            "failure_metrics": "metric_schema",
        }
    records: list[dict[str, Any]] = []
    for metric in sorted(comparator_metrics):
        left = float(comparator_metrics[metric])
        right = float(disabled_metrics[metric])
        residual = abs(left - right)
        if metric.endswith("_eur"):
            record = trajectory_cost_record(
                f"absent_disabled_metric[{metric}]",
                residual,
                comparison_scale_eur=max(abs(left), abs(right)),
            )
        elif metric == "final_product_t":
            record = validation_record(
                validation_id=f"absent_disabled_metric[{metric}]",
                purpose="cumulative_production_or_carried_state",
                unit="t",
                raw_residual=residual,
                allowed_tolerance=TERMINAL_STATE_TOLERANCE_T,
                aggregation="trajectory_total_no_accumulation",
            )
        else:
            record = validation_record(
                validation_id=f"absent_disabled_metric[{metric}]",
                purpose="trajectory_physical_metric_equivalence",
                unit="reported_metric_unit",
                raw_residual=residual,
                allowed_tolerance=MATERIAL_BALANCE_TOLERANCE_T,
                aggregation="trajectory_metric_no_accumulation",
            )
        records.append({"metric": metric, **record})
    failures = [row["metric"] for row in records if row["status"] != "pass"]
    return {
        "status": "pass" if not failures else "fail",
        "max_residual": max((row["raw_residual"] for row in records), default=0.0),
        "max_normalized_residual": max(
            (row["normalized_residual"] for row in records), default=0.0
        ),
        "failure_metrics": ";".join(failures),
        "validation_record_count": len(records),
    }


def _mapping_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _valid_sale_economic_overlay_row(row: Mapping[str, Any]) -> bool:
    try:
        raw_residual = float(row["raw_residual"])
        governed_tolerance = float(row["governed_tolerance"])
        allowed_tolerance = float(row["allowed_tolerance"])
        excess = float(row["excess_beyond_governed_tolerance"])
        solver_allowance = float(row["solver_numerical_allowance"])
        overlay_residual = float(row["overlay_residual"])
        overlay_raw_residual = float(row["overlay_raw_residual"])
        normalized_residual = float(row["normalized_residual"])
    except (KeyError, TypeError, ValueError):
        return False
    expected_normalized = (
        raw_residual / governed_tolerance
        if governed_tolerance > 0.0
        else (0.0 if raw_residual == 0.0 else math.inf)
    )
    return bool(
        all(
            math.isfinite(value)
            for value in (
                raw_residual,
                governed_tolerance,
                allowed_tolerance,
                excess,
                solver_allowance,
                overlay_residual,
                overlay_raw_residual,
                normalized_residual,
            )
        )
        and row.get("relaxation_allowed") is True
        and row.get("status") == "pass"
        and governed_tolerance == allowed_tolerance
        and solver_allowance == SOLVER_NUMERICAL_TOLERANCE
        and excess == max(0.0, raw_residual - governed_tolerance)
        and excess <= solver_allowance
        and overlay_residual == overlay_raw_residual
        and overlay_residual <= solver_allowance
        and normalized_residual == expected_normalized
        and bool(row.get("original_expression"))
        and bool(row.get("overlay_expression"))
    )


_POSTHOC_NON_ELECTRIC_GUARDRAIL_COUNTS = {
    "cross_policy_cumulative_progress_state": 4,
    "cross_policy_every_dynamic_handoff_state": 4,
    "cross_policy_executed_and_cumulative_production": 4,
    "cross_policy_terminal_handoff_snapshot_every_dynamic_state": 4,
    "inter_window_handoff_continuity": 8,
    "negative_price_export_coherence": 4,
    "ng_price_0_345_break_even_direction": 2,
    "real_model_containment_oracle_all_replans": 4,
    "sale_net_optimum_no_worse_than_identical_state_comparator": 4,
    "terminal_handoff_snapshot_complete": 8,
}
_POSTHOC_ABSOLUTE_GUARDRAIL_TOLERANCES = {
    "cross_policy_cumulative_progress_state": TERMINAL_STATE_TOLERANCE_T,
    "cross_policy_every_dynamic_handoff_state": TERMINAL_STATE_TOLERANCE_T,
    "cross_policy_executed_and_cumulative_production": TERMINAL_STATE_TOLERANCE_T,
    "cross_policy_terminal_handoff_snapshot_every_dynamic_state": (
        TERMINAL_STATE_TOLERANCE_T
    ),
    "inter_window_handoff_continuity": TERMINAL_STATE_TOLERANCE_T,
    "negative_price_export_coherence": ELECTRICITY_BALANCE_TOLERANCE_MWH,
    "real_model_containment_oracle_all_replans": TERMINAL_STATE_TOLERANCE_T,
    "terminal_handoff_snapshot_complete": TERMINAL_STATE_TOLERANCE_T,
}
_POSTHOC_ONE_SIDED_GUARDRAILS = {
    "ng_price_0_345_break_even_direction": ELECTRICITY_BALANCE_TOLERANCE_MWH,
    "sale_net_optimum_no_worse_than_identical_state_comparator": 1.0,
}


def _posthoc_require(condition: bool, message: str) -> None:
    if not condition:
        raise SaleSensitivityError(
            f"Posthoc full-matrix guardrail re-audit failed closed: {message}"
        )


def _posthoc_source_attempt_path(
    config: Mapping[str, Any], source_attempt: str | Path
) -> Path:
    expected = (
        REPO_ROOT
        / str(config["output_root"])
        / "attempts"
        / POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID
    ).resolve()
    supplied_text = str(source_attempt)
    supplied = (
        expected
        if supplied_text == POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID
        else Path(source_attempt).resolve()
    )
    _posthoc_require(
        supplied == expected,
        "source attempt must be the exact governed preserved attempt path",
    )
    return supplied


def _posthoc_reaudit_guardrail_row(row: Mapping[str, Any]) -> dict[str, Any]:
    guardrail = str(row.get("guardrail", ""))
    source_status = str(row.get("status", ""))
    raw_value = float(row.get("max_residual", math.inf))
    if guardrail in ELECTRICITY_TRAJECTORY_MAX_PURPOSES:
        evidence = threshold_comparison_record(
            validation_id=(
                f"posthoc[{row.get('case_id', '')}][{guardrail}]"
            ),
            purpose=guardrail,
            raw_residual=raw_value,
        )
    elif guardrail in _POSTHOC_ABSOLUTE_GUARDRAIL_TOLERANCES:
        tolerance = _POSTHOC_ABSOLUTE_GUARDRAIL_TOLERANCES[guardrail]
        evidence = validation_record(
            validation_id=(
                f"posthoc[{row.get('case_id', '')}][{guardrail}]"
            ),
            purpose=f"posthoc_preserved_{guardrail}",
            unit=(
                "MWh_e"
                if guardrail == "negative_price_export_coherence"
                else "t"
            ),
            raw_residual=raw_value,
            allowed_tolerance=tolerance,
            aggregation="preserved_guardrail_row_no_accumulation",
        )
    elif guardrail in _POSTHOC_ONE_SIDED_GUARDRAILS:
        governed_tolerance = _POSTHOC_ONE_SIDED_GUARDRAILS[guardrail]
        source_allowed = float(row.get("allowed_tolerance", math.inf))
        _posthoc_require(
            source_allowed == governed_tolerance,
            f"unexpected source tolerance for {guardrail}",
        )
        positive_excess = max(0.0, raw_value - governed_tolerance)
        evidence = {
            "validation_id": (
                f"posthoc[{row.get('case_id', '')}][{guardrail}]"
            ),
            "validation_purpose": f"posthoc_preserved_{guardrail}",
            "unit": "EUR" if guardrail.startswith("sale_net_") else "MWh_e",
            "aggregation": "preserved_one_sided_guardrail_no_accumulation",
            "raw_residual": raw_value,
            "allowed_tolerance": governed_tolerance,
            "governed_tolerance": governed_tolerance,
            "positive_excess": positive_excess,
            "normalized_residual": (
                positive_excess / governed_tolerance
                if governed_tolerance > 0.0
                else (0.0 if positive_excess == 0.0 else math.inf)
            ),
            "tolerance_accumulation_allowed": False,
            "status": "pass" if positive_excess <= 0.0 else "fail",
        }
    else:
        raise SaleSensitivityError(
            "Posthoc full-matrix guardrail re-audit failed closed: "
            f"unregistered preserved guardrail purpose {guardrail!r}"
        )
    return {
        **dict(row),
        "source_status": source_status,
        **evidence,
        "max_residual": raw_value,
        "reaudit_changed_status": source_status != evidence["status"],
    }


def run_posthoc_full_matrix_guardrail_reaudit(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    source_attempt: str | Path,
    posthoc_reaudit_authorization: str,
    posthoc_reaudit_reviewer_decision: str,
) -> dict[str, Any]:
    """Re-audit one frozen full-matrix artifact bundle without any solve."""

    started = time.perf_counter()
    config = load_config(config_path)
    validate_config(config)
    _posthoc_require(
        posthoc_reaudit_authorization == POSTHOC_REAUDIT_AUTHORIZATION_PHRASE,
        "explicit no-solve re-audit authorization phrase mismatch",
    )
    _posthoc_require(
        posthoc_reaudit_reviewer_decision == "PASS",
        "reviewer decision must be PASS",
    )
    _posthoc_require(_git_head() == EXPECTED_HEAD, "current HEAD mismatch")
    source = _posthoc_source_attempt_path(config, source_attempt)
    _posthoc_require(source.is_dir(), "source attempt directory is missing")

    source_bindings: list[dict[str, Any]] = []
    for filename in POSTHOC_REAUDIT_SOURCE_FILES:
        path = source / filename
        _posthoc_require(path.is_file(), f"missing source artifact {filename}")
        binding = {
            "path": _portable_persistent_path(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        expected_binding = POSTHOC_REAUDIT_SOURCE_FILE_CONTRACT[filename]
        _posthoc_require(
            binding["size_bytes"] == expected_binding["size_bytes"]
            and binding["sha256"] == expected_binding["sha256"],
            f"source artifact hash/size mismatch for {filename}",
        )
        source_bindings.append(binding)

    run_summary = json.loads((source / "run_summary.json").read_text(encoding="utf-8"))
    run_identity = json.loads((source / "run_identity.json").read_text(encoding="utf-8"))
    code_version = json.loads((source / "code_version.json").read_text(encoding="utf-8"))
    source_fingerprints = json.loads(
        (source / "implementation_fingerprints.json").read_text(encoding="utf-8")
    )
    source_config = yaml.safe_load(
        (source / "resolved_config.yaml").read_text(encoding="utf-8")
    )
    case_rows = _read_csv(source / "case_status.csv")
    solver_rows = _read_csv(source / "child_solver_summary.csv")
    source_guardrails = _read_csv(source / "physical_guardrails.csv")
    for name, payload in (
        ("run_summary", run_summary),
        ("run_identity", run_identity),
        ("code_version", code_version),
        ("implementation_fingerprints", source_fingerprints),
        ("resolved_config", source_config),
    ):
        _posthoc_require(isinstance(payload, Mapping), f"invalid {name} schema")

    _posthoc_require(
        run_summary.get("status") == "fail"
        and run_summary.get("execution_mode") == "full_matrix"
        and int(run_summary.get("completed_trajectory_count", -1)) == 8
        and int(run_summary.get("solver_model_count", -1)) == 112
        and int(run_summary.get("guardrail_failure_count", -1)) == 2
        and run_summary.get("held_out_periods_used") is False
        and run_summary.get("candidate_promoted") is False,
        "source run summary is not the exact failed full matrix",
    )
    _posthoc_require(
        run_identity.get("attempt_id") == POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID
        and run_identity.get("execution_mode") == "full_matrix"
        and run_identity.get("diagnostic_case_id") is None
        and run_identity.get("full_matrix_reviewer_decision") == "PASS"
        and run_identity.get("implementation_sha256")
        == POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
        and run_identity.get("config_sha256")
        == POSTHOC_REAUDIT_SOURCE_CONFIG_SHA256
        and run_identity.get("full_matrix_authorization_metadata_sha256")
        == POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256,
        "source run identity mismatch",
    )
    _posthoc_require(
        run_summary.get("implementation_sha256")
        == POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
        and code_version.get("implementation_sha256")
        == POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
        and code_version.get("git_commit") == EXPECTED_HEAD
        and source_fingerprints.get("current_head") == EXPECTED_HEAD
        and source_fingerprints.get("expected_parent_head") == EXPECTED_HEAD
        and code_version.get("full_matrix_authorization_metadata_sha256")
        == POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256,
        "source implementation or HEAD metadata mismatch",
    )
    source_authorization = _mapping_sha256(
        _full_matrix_authorization_metadata(source_config)
    )
    _posthoc_require(
        source_authorization
        == POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256
        and source_config.get("full_matrix_execution_authorized") is True
        and source_config.get("full_matrix_reviewer_decision") == "PASS"
        and source_config.get("execution_mode") == "full_matrix"
        and source_config.get("experiment", {}).get(
            "validation_tolerance_policy"
        )
        == POSTHOC_REAUDIT_SOURCE_POLICY_CONTRACT,
        "source config or authorization contract mismatch",
    )

    expected_case_ids = {
        f"sale__{candidate}__{scenario}__{policy}"
        for candidate in EXPECTED_CANDIDATES
        for scenario in EXPECTED_SCENARIOS
        for policy in EXPECTED_POLICIES
    }
    _posthoc_require(
        len(case_rows) == 8
        and {row.get("case_id") for row in case_rows} == expected_case_ids
        and all(row.get("status") == "pass" for row in case_rows)
        and all(row.get("execution_mode") == "full_matrix" for row in case_rows)
        and all(row.get("dataset_split") == "validation" for row in case_rows)
        and all(row.get("price_field") == "y_pred" for row in case_rows)
        and all(row.get("perfect_foresight_oracle") == "False" for row in case_rows),
        "source case-status scope or statuses mismatch",
    )
    expected_solver_keys = {
        (candidate, scenario, policy, configuration, str(replan))
        for candidate in EXPECTED_CANDIDATES
        for scenario in EXPECTED_SCENARIOS
        for policy in EXPECTED_POLICIES
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
        for replan in range(7)
    }
    observed_solver_keys = {
        (
            row.get("candidate_id"),
            row.get("scenario_id"),
            row.get("policy_id"),
            row.get("configuration_id"),
            row.get("replan_index"),
        )
        for row in solver_rows
    }
    _posthoc_require(
        len(solver_rows) == 112
        and observed_solver_keys == expected_solver_keys
        and all(row.get("solver_status") == "ok" for row in solver_rows)
        and all(row.get("termination_condition") == "optimal" for row in solver_rows),
        "source solver summary is not 112/112 ok and optimal over the full matrix",
    )

    expected_guardrail_counts = {
        **{purpose: 8 for purpose in ELECTRICITY_TRAJECTORY_MAX_PURPOSES},
        **_POSTHOC_NON_ELECTRIC_GUARDRAIL_COUNTS,
    }
    observed_guardrail_counts = {
        name: sum(row.get("guardrail") == name for row in source_guardrails)
        for name in {row.get("guardrail", "") for row in source_guardrails}
    }
    source_failures = [
        row for row in source_guardrails if row.get("status") != "pass"
    ]
    expected_failure_keys = {
        (
            "sale__recovery_bg30_ng30__volatile_negative_governed_y_pred__accepted_no_export_comparator",
            "electricity_identity",
        ),
        (
            "sale__recovery_bg30_ng30__volatile_negative_governed_y_pred__accepted_no_export_comparator",
            "wag_and_ng_generation_exactly_separate",
        ),
    }
    _posthoc_require(
        len(source_guardrails) == 94
        and observed_guardrail_counts == expected_guardrail_counts
        and {
            (row.get("case_id"), row.get("guardrail"))
            for row in source_failures
        }
        == expected_failure_keys
        and all(
            float(row.get("max_residual", math.inf))
            == 1.0000000543186616e-6
            for row in source_failures
        ),
        "source physical-guardrail schema or exact failures mismatch",
    )

    reaudited_guardrails = [
        _posthoc_reaudit_guardrail_row(row) for row in source_guardrails
    ]
    reaudit_failures = [
        row for row in reaudited_guardrails if row.get("status") != "pass"
    ]
    changed = [
        row for row in reaudited_guardrails if row["reaudit_changed_status"]
    ]
    _posthoc_require(
        not reaudit_failures
        and {
            (row.get("case_id"), row.get("guardrail")) for row in changed
        }
        == expected_failure_keys,
        "current registered policy did not yield the exact two-row supersession",
    )

    fingerprints = implementation_fingerprints(config_path)
    implementation_sha = _mapping_sha256(fingerprints)
    current_policy = validation_tolerance_policy_contract()
    authorization_metadata = {
        "posthoc_reaudit_authorized": True,
        "posthoc_reaudit_authorization_sha256": hashlib.sha256(
            posthoc_reaudit_authorization.encode("utf-8")
        ).hexdigest(),
        "posthoc_reaudit_reviewer_decision": posthoc_reaudit_reviewer_decision,
    }
    source_bindings_sha = _mapping_sha256(source_bindings)
    identity_scope = {
        "execution_mode": POSTHOC_REAUDIT_EXECUTION_MODE,
        "source_attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
        "source_bindings_sha256": source_bindings_sha,
        "current_implementation_sha256": implementation_sha,
        "current_policy": current_policy,
        "authorization_metadata": authorization_metadata,
    }
    reaudit_attempt_id = (
        f"{implementation_sha[:16]}__{_mapping_sha256(identity_scope)[:12]}"
    )
    output = (
        REPO_ROOT
        / str(config["output_root"])
        / "posthoc_reaudits"
        / reaudit_attempt_id
    ).resolve()
    _posthoc_require(not output.exists(), "identity-scoped re-audit attempt already exists")
    output.mkdir(parents=True)

    run_identity_out = {
        "schema_version": "steel_phase2_posthoc_guardrail_reaudit_identity_v1",
        "attempt_id": reaudit_attempt_id,
        **identity_scope,
    }
    _write_json(output / "run_identity.json", run_identity_out)
    resolved = {
        **config,
        "execution_mode": POSTHOC_REAUDIT_EXECUTION_MODE,
        "source_attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
        **authorization_metadata,
        "implementation_sha256": implementation_sha,
    }
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        output / "input_manifest.json",
        {
            "schema_version": "steel_phase2_posthoc_guardrail_reaudit_input_v1",
            "source_attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
            "source_bindings_sha256": source_bindings_sha,
            "source_files": source_bindings,
            "source_implementation_sha256": (
                POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
            ),
            "source_config_sha256": POSTHOC_REAUDIT_SOURCE_CONFIG_SHA256,
            "source_authorization_metadata_sha256": (
                POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256
            ),
            "current_implementation": fingerprints,
        },
    )
    _write_json(
        output / "code_version.json",
        {
            "git_commit": _git_head(),
            "implementation_sha256": implementation_sha,
            "working_tree_diff_sha256": fingerprints["working_tree_diff_sha256"],
            "validation_tolerance_policy": current_policy,
        },
    )
    _write_csv(output / "physical_guardrails_reaudited.csv", reaudited_guardrails)
    supersession = {
        "schema_version": "steel_phase2_posthoc_guardrail_supersession_v1",
        "status": "pass",
        "supersession_scope": "guardrail_interpretation_only",
        "source_attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
        "source_run_status": "fail",
        "source_artifacts_modified": False,
        "source_guardrail_row_count": len(source_guardrails),
        "source_guardrail_failure_count": len(source_failures),
        "reaudited_guardrail_row_count": len(reaudited_guardrails),
        "reaudited_guardrail_failure_count": len(reaudit_failures),
        "superseded_guardrail_rows": [
            {
                "case_id": row["case_id"],
                "guardrail": row["guardrail"],
                "source_status": row["source_status"],
                "reaudited_status": row["status"],
                "raw_residual": row["raw_residual"],
                "governed_tolerance": row["governed_tolerance"],
                "positive_excess": row["positive_excess"],
                "comparison_roundoff_allowance": row[
                    "comparison_roundoff_allowance"
                ],
                "comparison_roundoff_method": row[
                    "comparison_roundoff_method"
                ],
            }
            for row in changed
        ],
        "source_bindings_sha256": source_bindings_sha,
        "source_validation_tolerance_policy": (
            POSTHOC_REAUDIT_SOURCE_POLICY_CONTRACT
        ),
        "reaudit_validation_tolerance_policy": current_policy,
        "solver_model_count": 0,
        "source_solver_model_count": 112,
        "no_solve_claim": True,
    }
    _write_json(output / "supersession_manifest.json", supersession)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "lineage_role": "diagnostic supersession of guardrail interpretation",
            "run_class": "posthoc_full_matrix_guardrail_reaudit_no_solve",
            "output_policy": "minimal",
            "retention_status": "local",
            "git_eligible": False,
            "candidate_promoted": False,
        },
    )
    _write_csv(
        output / "metrics_summary.csv",
        [
            {
                "completed_trajectory_count": 8,
                "solver_model_count": 0,
                "source_solver_model_count": 112,
                "source_guardrail_failure_count": 2,
                "reaudited_guardrail_failure_count": 0,
                "superseded_guardrail_row_count": 2,
            }
        ],
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a posthoc, no-solve guardrail re-audit of one exact preserved full-matrix attempt.\n"
        "- The original source attempt remains failed and byte-for-byte unchanged.\n"
        "- Supersession is limited to guardrail interpretation under the registered threshold-comparison policy.\n"
        "- No optimisation model was built or solved; source solver results are referenced only by hash.\n"
        "- No candidate is promoted and no held-out period, settlement, bidding, ETS, stochastic, CVaR, or mFRR claim is made.\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": config["run_id"],
        "attempt_id": reaudit_attempt_id,
        "attempt_output_root": _portable_persistent_path(output),
        "status": "pass",
        "execution_mode": POSTHOC_REAUDIT_EXECUTION_MODE,
        "source_attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
        "source_run_status": "fail",
        "source_superseded_for_guardrail_interpretation": True,
        "source_artifacts_modified": False,
        "completed_trajectory_count": 8,
        "guardrail_failure_count": 0,
        "source_guardrail_failure_count": 2,
        "solver_model_count": 0,
        "source_solver_model_count": 112,
        "no_solve_reaudit": True,
        "held_out_periods_used": False,
        "candidate_promoted": False,
        "market_settlement_claim": False,
        "implementation_sha256": implementation_sha,
        "source_bindings_sha256": source_bindings_sha,
        "runtime_seconds": time.perf_counter() - started,
    }
    _write_json(output / "run_summary.json", summary)
    return summary


def _case_ready(
    directory: Path,
    *,
    expected_overrides: Mapping[str, Any],
    implementation_sha256: str,
    preservation_sha256: str,
    authorization_metadata_sha256: str,
) -> bool:
    required = (
        "run_summary.json",
        "config_resolved.yaml",
        "executed_hourly.csv",
        "inventory_handoff.csv",
        "rolling_model_metrics.csv",
        "input_manifest.json",
        "code_version.json",
        "case_cache_manifest.json",
    )
    if not all((directory / name).is_file() for name in required):
        return False
    try:
        summary = json.loads((directory / "run_summary.json").read_text(encoding="utf-8"))
        resolved = yaml.safe_load((directory / "config_resolved.yaml").read_text(encoding="utf-8"))
        code = json.loads((directory / "code_version.json").read_text(encoding="utf-8"))
        input_manifest = json.loads((directory / "input_manifest.json").read_text(encoding="utf-8"))
        cache = json.loads((directory / "case_cache_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, json.JSONDecodeError):
        return False
    forecast_root = Path(str(expected_overrides["forecast_run_root"])).resolve()
    portable_expected_overrides = _portableize_persistent_payload(
        dict(expected_overrides), forecast_root=forecast_root
    )
    if (
        summary.get("status") != "pass"
        or resolved.get("scenario_overrides_applied") != portable_expected_overrides
        or code.get("git_commit") != _git_head()
        or cache.get("implementation_sha256") != implementation_sha256
        or cache.get("sale_state_preservation_sha256")
        != preservation_sha256
        or cache.get("full_matrix_authorization_metadata_sha256")
        != authorization_metadata_sha256
        or cache.get("scenario_overrides_sha256")
        != _mapping_sha256(portable_expected_overrides)
    ):
        return False
    fingerprint_rows = list(input_manifest.get("active_model_input_files", []))
    fingerprint_rows.extend(input_manifest.get("direct_source_evidence_files", []))
    for row in fingerprint_rows:
        path = REPO_ROOT / str(row.get("path", ""))
        if not path.is_file() or _sha256(path) != row.get("sha256"):
            return False
    for row in cache.get("files", []):
        path = (directory / str(row["path"])).resolve()
        if not path.is_file() or _sha256(path) != row["sha256"]:
            return False
    return bool(fingerprint_rows and cache.get("files"))


def _write_case_cache_manifest(
    directory: Path,
    *,
    expected_overrides: Mapping[str, Any],
    implementation_sha256: str,
    preservation_sha256: str,
    authorization_metadata_sha256: str,
) -> None:
    names = (
        "run_summary.json", "config_resolved.yaml", "executed_hourly.csv",
        "inventory_handoff.csv", "rolling_execution.csv",
        "rolling_production_progress_state.csv", "rolling_model_metrics.csv",
        "executed_procurement_cost_ledger.csv", "input_manifest.json",
        "code_version.json", "rolling_timestamp_ledger.csv",
    )
    files = [
        {"path": name, "sha256": _sha256(directory / name)}
        for name in names if (directory / name).is_file()
    ]
    for evidence_root in ("normal_solution_capture", "sale_containment"):
        root = directory / evidence_root
        if root.is_dir():
            files.extend(
                {
                    "path": str(path.relative_to(directory)).replace("\\", "/"),
                    "sha256": _sha256(path),
                }
                for path in sorted(root.rglob("*"))
                if path.is_file()
            )
    capture = expected_overrides.get("normal_solution_capture")
    if isinstance(capture, Mapping) and capture.get("directory"):
        capture_root = Path(str(capture["directory"])).resolve()
        files.extend(
            {
                "path": os.path.relpath(path, directory).replace("\\", "/"),
                "sha256": _sha256(path),
            }
            for path in sorted(capture_root.rglob("*"))
            if path.is_file()
        )
    _write_json(
        directory / "case_cache_manifest.json",
        {
            "schema_version": "steel_phase2_case_cache_v2",
            "implementation_sha256": implementation_sha256,
            "sale_state_preservation_sha256": preservation_sha256,
            "full_matrix_authorization_metadata_sha256": (
                authorization_metadata_sha256
            ),
            "scenario_overrides_sha256": _mapping_sha256(
                _portableize_persistent_payload(
                    dict(expected_overrides),
                    forecast_root=Path(
                        str(expected_overrides["forecast_run_root"])
                    ).resolve(),
                )
            ),
            "files": files,
        },
    )


def run_sale_sensitivity(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
    diagnostic_case_id: str | None = None,
    execution_mode: str = "aggregate_only",
    full_matrix_authorization: str | None = None,
    full_matrix_reviewer_decision: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = load_config(config_path)
    validate_config(config)
    authorization_metadata = _full_matrix_authorization_metadata(config)
    authorization_metadata_sha = _mapping_sha256(authorization_metadata)
    if _git_head() != EXPECTED_HEAD:
        raise SaleSensitivityError("Phase-2 execution requires the frozen parent HEAD.")
    allowed_modes = set(SUPPORTED_EXECUTION_MODES)
    if execution_mode not in allowed_modes:
        raise SaleSensitivityError(f"Unknown execution mode: {execution_mode}")
    aggregate_only = aggregate_only or execution_mode == "aggregate_only"
    if not aggregate_only and execution_mode.startswith("preflight_") and config.get(
        "prevalidation_execution_authorized"
    ) is not True:
        raise SaleSensitivityError("Prevalidation execution is not authorized by config.")
    if execution_mode == "full_matrix":
        configured_hash = config.get("full_matrix_post_review_token_sha256")
        supplied_hash = (
            hashlib.sha256(full_matrix_authorization.encode("utf-8")).hexdigest()
            if full_matrix_authorization
            else None
        )
        if (
            full_matrix_reviewer_decision != "PASS"
            or config.get("full_matrix_execution_authorized") is not True
            or not isinstance(configured_hash, str)
            or len(configured_hash) != 64
            or supplied_hash != configured_hash
        ):
            raise SaleSensitivityError(
                "Full matrix requires reviewer decision PASS, YAML "
                "authorization=true, a configured token hash, and the "
                "matching root-provided authorization value."
            )
    experiment = config["experiment"]
    mechanism = load_mechanism_config(REPO_ROOT / experiment["mechanism_config"])
    validate_mechanism_config(mechanism)
    mechanism_experiment = mechanism["experiment"]
    candidates = {row["candidate_id"]: row for row in mechanism_experiment["candidates"]}
    scenarios = {row["scenario_id"]: row for row in mechanism_experiment["scenarios"]}
    periods = {row["period_id"]: row for row in mechanism_experiment["development_periods"]}
    matrix, bounded_preflight_overrides = execution_plan(config, execution_mode)
    if diagnostic_case_id is not None:
        matrix = [row for row in matrix if row["case_id"] == diagnostic_case_id]
        if len(matrix) != 1:
            raise SaleSensitivityError("Unknown diagnostic case id.")
    scratch_base = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / experiment["scratch_root"]).resolve()
    )
    output_root = (REPO_ROOT / config["output_root"]).resolve()
    _portable_persistent_path(scratch_base)
    _portable_persistent_path(output_root)
    physical_config = (REPO_ROOT / experiment["physical_config"]).resolve()
    fingerprints = implementation_fingerprints(config_path)
    implementation_sha = _mapping_sha256(fingerprints)
    preservation_sha = _mapping_sha256(
        {
            **fingerprints["sale_state_preservation_specification"],
            "implementation_sha256": implementation_sha,
        }
    )
    run_identity = {
        "run_id": config["run_id"],
        "config_sha256": _sha256(Path(config_path).resolve()),
        "full_matrix_authorization_metadata_sha256": (
            authorization_metadata_sha
        ),
        "full_matrix_reviewer_decision": full_matrix_reviewer_decision,
        "implementation_sha256": implementation_sha,
        "sale_state_preservation_sha256": preservation_sha,
    }
    output, attempt_identity = _prepare_attempt_output(
        output_root,
        run_identity=run_identity,
        execution_mode=execution_mode,
        diagnostic_case_id=diagnostic_case_id,
    )
    scratch = scratch_base / "attempts" / attempt_identity["attempt_id"]
    scratch.mkdir(parents=True, exist_ok=True)
    load_runtime_seconds = time.perf_counter() - started
    statuses: list[dict[str, Any]] = []
    guardrails: list[dict[str, Any]] = []
    artifacts: dict[tuple[str, str, str], dict[str, Any]] = {}
    for case in matrix:
        case_started = time.perf_counter()
        directory = scratch / case["case_id"]
        pair_key = (case["candidate_id"], case["scenario_id"])
        capture_directory = scratch / (
            f"normal_capture__{case['candidate_id']}__{case['scenario_id']}"
        )
        provenance = {
            "schema_version": "steel_phase2_no_export_capture_v1",
            "candidate_id": case["candidate_id"],
            "scenario_id": case["scenario_id"],
            "implementation_sha256": implementation_sha,
        }
        if case["policy_id"] == "accepted_no_export_comparator":
            capture_directory.mkdir(parents=True, exist_ok=True)
            policy_runtime_overrides = {
                "normal_solution_capture": {
                    "enabled": True,
                    "structural_inactive_exclusion_enabled": True,
                    "directory": str(capture_directory),
                    "provenance": provenance,
                }
            }
        elif case["policy_id"] == "explicit_disabled_preflight":
            policy_runtime_overrides = {
                "c0_electricity_sale_sensitivity": {"enabled": False}
            }
        else:
            policy_runtime_overrides = policy_overrides(case["policy_id"])
            policy_runtime_overrides["c0_electricity_sale_sensitivity"].update(
                {
                    "incumbent_capture_directory": str(capture_directory),
                    "incumbent_provenance": provenance,
                    "containment_oracle_root": str(directory / "sale_containment"),
                }
            )
        overrides = {
            "run_id": case["case_id"],
            "lineage_role": "bounded_phase2_sale_sensitivity_case_cache",
            "forecast_run_root": str(Path(forecast_run_root).resolve()),
            **_scenario_overrides(scenarios[case["scenario_id"]], periods),
            **candidate_overrides(mechanism, candidates[case["candidate_id"]]),
            "phase2_implementation_sha256": implementation_sha,
            **bounded_preflight_overrides,
            **policy_runtime_overrides,
        }
        cached = _case_ready(
            directory,
            expected_overrides=overrides,
            implementation_sha256=implementation_sha,
            preservation_sha256=preservation_sha,
            authorization_metadata_sha256=authorization_metadata_sha,
        )
        build_call_runtime = 0.0
        cache_write_runtime = 0.0
        if not cached and not aggregate_only:
            if directory.exists():
                raise SaleSensitivityError(
                    f"Incomplete case cache preserved for inspection: {directory}"
                )
            child_started = time.perf_counter()
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                build_call_runtime = time.perf_counter() - child_started
                failure_row = {
                    **case,
                    "status": "fail",
                    "execution_mode": execution_mode,
                    "cache_directory": _portable_persistent_path(directory),
                    "exception_stage": getattr(
                        exc, "phase2_stage", "child_model_load_build_or_solve"
                    ),
                    "exception_type": type(exc).__name__,
                    "exception_message": _portable_exception_message(exc),
                    "load_runtime_seconds": time.perf_counter() - case_started,
                    "build_runtime_seconds": build_call_runtime,
                    "solve_runtime_seconds": 0.0,
                    "write_runtime_seconds": 0.0,
                }
                statuses.append(failure_row)
                _persist_failure_evidence(
                    output,
                    statuses=statuses,
                    exc=exc,
                    stage=str(failure_row["exception_stage"]),
                    started=started,
                    load_runtime_seconds=load_runtime_seconds,
                    build_runtime_seconds=build_call_runtime,
                    execution_mode=execution_mode,
                )
                raise SaleSensitivityError(
                    f"Phase-2 case failed during {failure_row['exception_stage']}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            build_call_runtime = time.perf_counter() - child_started
            write_started = time.perf_counter()
            _normalize_child_persistent_paths(
                directory,
                forecast_root=Path(forecast_run_root).resolve(),
            )
            _write_case_cache_manifest(
                directory,
                expected_overrides=overrides,
                implementation_sha256=implementation_sha,
                preservation_sha256=preservation_sha,
                authorization_metadata_sha256=authorization_metadata_sha,
            )
            cache_write_runtime = time.perf_counter() - write_started
            cached = _case_ready(
                directory,
                expected_overrides=overrides,
                implementation_sha256=implementation_sha,
                preservation_sha256=preservation_sha,
                authorization_metadata_sha256=authorization_metadata_sha,
            )
        status = "pass" if cached else "fail"
        status_row = {
            **case,
            "status": status,
            "execution_mode": execution_mode,
            "cache_directory": _portable_persistent_path(directory),
            "load_runtime_seconds": time.perf_counter() - case_started,
            "build_runtime_seconds": build_call_runtime,
            "solve_runtime_seconds": 0.0,
            "write_runtime_seconds": cache_write_runtime,
        }
        statuses.append(status_row)
        if status != "pass":
            child_failure = _child_failure_evidence(directory)
            status_row.update(child_failure)
            status_row["exception_stage"] = "child_validation_status"
            status_row["exception_type"] = "ChildRunStatusFailure"
            status_row["exception_message"] = (
                "Completed child run returned status="
                f"{child_failure['child_run_status']}; failing checks: "
                f"{child_failure['child_failure_checks'] or 'not_recorded'}"
            )
            status_row["load_runtime_seconds"] = time.perf_counter() - case_started
            status_row["write_runtime_seconds"] = cache_write_runtime
            child_error = SaleSensitivityError(status_row["exception_message"])
            _persist_failure_evidence(
                output,
                statuses=statuses,
                exc=child_error,
                stage="child_validation_status",
                started=started,
                load_runtime_seconds=load_runtime_seconds,
                build_runtime_seconds=float(
                    child_failure["build_runtime_seconds"]
                ),
                solve_runtime_seconds=float(
                    child_failure["solve_runtime_seconds"]
                ),
                write_runtime_seconds=cache_write_runtime,
                execution_mode=execution_mode,
            )
            if case["policy_id"] == "accepted_no_export_comparator":
                raise SaleSensitivityError(
                    "No-export comparator failed; preserve the exact case and IIS, then stop."
                )
            raise SaleSensitivityError(f"Phase-2 case failed: {case['case_id']}")
        hourly = _read_csv(directory / "executed_hourly.csv")
        case_guardrails = electricity_guardrails(
            hourly, sale_enabled=case["sale_enabled"]
        )
        guardrails.extend({"case_id": case["case_id"], **row} for row in case_guardrails)
        continuity = handoff_continuity(
            _read_csv(directory / "inventory_handoff.csv"),
            phase2_single_window_preflight=(
                bounded_preflight_overrides.get(
                    "phase2_single_window_preflight"
                )
                is True
            ),
            expected_replan_count=int(
                bounded_preflight_overrides.get(
                    "replan_count", experiment["replan_count"]
                )
            ),
        )
        guardrails.extend(
            [
                {
                    "case_id": case["case_id"],
                    "guardrail": "terminal_handoff_snapshot_complete",
                    "status": (
                        "pass"
                        if continuity["terminal_handoff_snapshot_complete"]
                        else "fail"
                    ),
                    "validation_scope": continuity["validation_scope"],
                    "checked_transition_count": continuity[
                        "checked_transition_count"
                    ],
                    "max_residual": continuity["max_state_residual"],
                },
                {
                    "case_id": case["case_id"],
                    "guardrail": "inter_window_handoff_continuity",
                    "status": continuity["status"],
                    "result": continuity[
                        "inter_window_handoff_continuity"
                    ],
                    "validation_scope": continuity["validation_scope"],
                    "checked_transition_count": continuity[
                        "checked_transition_count"
                    ],
                    "max_residual": continuity["max_state_residual"],
                },
            ]
        )
        model_rows = _read_csv(directory / "rolling_model_metrics.csv")
        status_row["build_runtime_seconds"] = sum(
            float(row.get("build_runtime_seconds") or 0.0) for row in model_rows
        )
        status_row["solve_runtime_seconds"] = sum(
            float(row.get("runtime_seconds") or 0.0) for row in model_rows
        )
        status_row["load_runtime_seconds"] = time.perf_counter() - case_started
        artifacts[(case["candidate_id"], case["scenario_id"], case["policy_id"])] = {
            "directory": directory,
            "hourly": hourly,
            "execution": _read_csv(directory / "rolling_execution.csv"),
            "handoff": _read_csv(directory / "inventory_handoff.csv"),
            "progress": _read_csv(directory / "rolling_production_progress_state.csv"),
            "costs": _read_csv(directory / "executed_procurement_cost_ledger.csv"),
            "models": model_rows,
        }
    metrics_rows: list[dict[str, Any]] = []
    expected_containment_replan_indices = _expected_containment_replan_indices(
        experiment, bounded_preflight_overrides
    )
    for (candidate, scenario, policy), artifact in sorted(artifacts.items()):
        metrics_rows.append(
            {"candidate_id": candidate, "scenario_id": scenario, "policy_id": policy,
             **trajectory_metrics(artifact["hourly"], artifact["costs"])}
        )
    pair_ids = sorted({(key[0], key[1]) for key in artifacts})
    for candidate, scenario in pair_ids:
        comparator = artifacts.get((candidate, scenario, "accepted_no_export_comparator"))
        sale = artifacts.get((candidate, scenario, "athanasiadis_sale_enabled"))
        disabled = artifacts.get((candidate, scenario, "explicit_disabled_preflight"))
        for label, other in (("sale", sale), ("explicit_disabled", disabled)):
            if comparator is None or other is None:
                continue
            guardrails.extend(
                {
                    "case_id": f"{candidate}__{scenario}__{label}", **row
                }
                for row in cross_policy_state_guardrails(
                    comparator["execution"], other["execution"],
                    comparator["handoff"], other["handoff"],
                    comparator["progress"], other["progress"],
                )
            )
        if comparator is not None and disabled is not None:
            comparator_metrics = trajectory_metrics(comparator["hourly"], comparator["costs"])
            disabled_metrics = trajectory_metrics(disabled["hourly"], disabled["costs"])
            metric_equivalence = _trajectory_metric_equivalence(
                comparator_metrics, disabled_metrics
            )
            guardrails.append({
                "case_id": f"{candidate}__{scenario}__explicit_disabled",
                "guardrail": "absent_vs_explicit_disabled_full_metric_equivalence",
                **metric_equivalence,
            })
            guardrails.append(
                {
                    "case_id": (
                        f"{candidate}__{scenario}__explicit_disabled"
                    ),
                    **absent_disabled_result_equivalence(
                        comparator["models"], disabled["models"]
                    ),
                }
            )
        if comparator is not None and sale is not None:
            comp_models = {
                int(row["replan_index"]): row for row in comparator["models"]
                if str(row["configuration_id"]).startswith("C0_")
            }
            sale_models = {
                int(row["replan_index"]): row for row in sale["models"]
                if str(row["configuration_id"]).startswith("C0_")
            }
            cost_residual = max(
                float(sale_models[index]["primary_cost_objective_eur"])
                - float(comp_models[index]["primary_cost_objective_eur"])
                for index in comp_models
            )
            comparison_scale = max(
                abs(float(row["primary_cost_objective_eur"]))
                for row in (*comp_models.values(), *sale_models.values())
            )
            cost_validation = trajectory_cost_record(
                "sale_net_optimum_no_worse_than_identical_state_comparator",
                max(0.0, cost_residual),
                comparison_scale_eur=comparison_scale,
            )
            guardrails.append({
                "case_id": f"{candidate}__{scenario}__sale",
                "guardrail": "sale_net_optimum_no_worse_than_identical_state_comparator",
                "status": cost_validation["status"],
                "max_residual": cost_residual,
                "allowed_tolerance": cost_validation["allowed_tolerance"],
                "validation_purpose": cost_validation["purpose"],
            })
            containment_validation = _validate_containment_records(
                sale["directory"] / "sale_containment",
                expected_replan_indices=expected_containment_replan_indices,
            )
            volatile_replan_zero_only = (
                execution_mode == "preflight_volatile_containment"
            )
            guardrails.append({
                "case_id": f"{candidate}__{scenario}__sale",
                "guardrail": (
                    "real_model_containment_oracle_replan_0_only"
                    if volatile_replan_zero_only
                    else "real_model_containment_oracle_all_replans"
                ),
                "validation_scope": (
                    "volatile_replan_0_containment_only"
                    if volatile_replan_zero_only
                    else "all_execution_contract_replans"
                ),
                "negative_price_validation_claimed": False,
                **containment_validation,
            })
            volatile = scenario == EXPECTED_SCENARIOS[1]
            negative_contract = _negative_price_validation_contract(
                execution_mode, volatile=volatile
            )
            if negative_contract["evaluate"]:
                negative_guardrail = negative_price_export_coherence(
                    sale["hourly"],
                    require_negative_hour=bool(
                        negative_contract["require_negative_hour"]
                    ),
                    target_replan=negative_contract["target_replan"],
                    validation_scope=str(
                        negative_contract["validation_scope"]
                    ),
                )
                guardrails.append(
                    {
                        "case_id": f"{candidate}__{scenario}__sale",
                        "negative_price_claim_eligible": negative_contract[
                            "claimed"
                        ],
                        "negative_hour_required": negative_contract[
                            "require_negative_hour"
                        ],
                        **negative_guardrail,
                    }
                )
    by_metric_key = {
        (row["candidate_id"], row["scenario_id"], row["policy_id"]): row
        for row in metrics_rows
    }
    for scenario in EXPECTED_SCENARIOS:
        low = by_metric_key.get(("recovery_bg30_ng30", scenario, "athanasiadis_sale_enabled"))
        high = by_metric_key.get(("recovery_bg30_ng55", scenario, "athanasiadis_sale_enabled"))
        if low and high:
            residual = float(high["generator_ng_mwh"]) - float(low["generator_ng_mwh"])
            ng_direction = validation_record(
                validation_id=f"ng_price_0_345_break_even_direction[{scenario}]",
                purpose="energy_direction_guardrail",
                unit="MWh_LHV",
                raw_residual=max(0.0, residual),
                allowed_tolerance=MATERIAL_BALANCE_TOLERANCE_T,
                aggregation="trajectory_total_no_accumulation",
            )
            guardrails.append({
                "case_id": f"ng_break_even__{scenario}",
                "guardrail": "ng_price_0_345_break_even_direction",
                "status": ng_direction["status"],
                "max_residual": residual,
                "allowed_tolerance": ng_direction["allowed_tolerance"],
            })
    failures = [row for row in guardrails if row["status"] != "pass"]
    _write_csv(output / "scenario_matrix.csv", frozen_case_matrix(config))
    _write_csv(output / "case_status.csv", statuses)
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "metrics_summary.csv", metrics_rows)
    _write_json(output / "implementation_fingerprints.json", fingerprints)
    solver_rows = [
        {
            "candidate_id": candidate,
            "scenario_id": scenario,
            "policy_id": policy,
            "replan_index": row["replan_index"],
            "configuration_id": row["configuration_id"],
            "solver_status": row.get("solver_status", ""),
            "termination_condition": row.get("termination_condition", ""),
            "primary_objective_eur": row.get("primary_cost_objective_eur", ""),
            "runtime_seconds": row.get("runtime_seconds", ""),
            "mip_gap": row.get("mip_gap", ""),
            "variable_count": row.get("variable_count", ""),
            "binary_count": row.get("binary_count", ""),
            "constraint_count": row.get("constraint_count", ""),
            "grid_import_bound_audit_status": row.get(
                "grid_import_bound_audit_status", ""
            ),
            "grid_import_bound_derivation_method": row.get(
                "grid_import_bound_derivation_method", ""
            ),
            "grid_import_bound_audit_runtime_seconds": row.get(
                "grid_import_bound_audit_runtime_seconds", ""
            ),
            "grid_import_hourly_upper_bounds_json": row.get(
                "grid_import_hourly_upper_bounds_json", ""
            ),
        }
        for (candidate, scenario, policy), artifact in sorted(artifacts.items())
        for row in artifact["models"]
    ]
    _write_csv(output / "child_solver_summary.csv", solver_rows)
    resolved_config = {
        **config,
        "execution_mode": execution_mode,
        "attempt_id": attempt_identity["attempt_id"],
        "attempt_output_root": _portable_persistent_path(output),
        "bounded_preflight_overrides": bounded_preflight_overrides,
        "full_matrix_authorization_supplied": bool(full_matrix_authorization),
        "full_matrix_reviewer_decision": full_matrix_reviewer_decision,
        "full_matrix_authorization_metadata_sha256": (
            authorization_metadata_sha
        ),
        "implementation_sha256": implementation_sha,
        "sale_state_preservation_sha256": preservation_sha,
    }
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(resolved_config, sort_keys=False), encoding="utf-8"
    )
    child_manifests = [
        {
            "case_id": row["case_id"],
            "cache_manifest": str(
                Path(row["cache_directory"]) / "case_cache_manifest.json"
            ).replace("\\", "/"),
            "cache_manifest_sha256": _sha256(
                REPO_ROOT / row["cache_directory"] / "case_cache_manifest.json"
            ),
        }
        for row in statuses
    ]
    _write_json(
        output / "input_manifest.json",
        {
            "schema_version": "steel_phase2_input_manifest_v1",
            "implementation": fingerprints,
            "full_matrix_authorization_metadata_sha256": (
                authorization_metadata_sha
            ),
            "authoritative_phase1_contract": authoritative_phase1_contract(config),
            "child_case_manifests": child_manifests,
        },
    )
    _write_json(
        output / "code_version.json",
        {
            "git_commit": _git_head(),
            "working_tree_diff_sha256": fingerprints["working_tree_diff_sha256"],
            "implementation_sha256": implementation_sha,
            "sale_state_preservation_sha256": preservation_sha,
            "full_matrix_authorization_metadata_sha256": (
                authorization_metadata_sha
            ),
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "lineage_role": config["lineage_role"],
            "run_class": config["run_class"],
            "output_policy": "minimal",
            "retention_status": "local",
            "git_eligible": False,
            "candidate_promoted": False,
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- DEVELOPMENT diagnostic/emulation sensitivity only; not a base case or market-settlement result.\n"
        "- Export has no invented WAG/NG carrier attribution; only total internal generation bounds it.\n"
        "- The sale value is the same governed validation `y_pred` used for import, not `y_true`, TEST, bidding or settlement.\n"
        "- WAG has no purchase credit or profit term; revenue applies only to gross exported electricity.\n"
        "- No candidate is promoted and the Phase-1 target/parameter overlays remain immutable.\n",
        encoding="utf-8",
    )
    write_started = time.perf_counter()
    summary = {
        "run_id": config["run_id"],
        "attempt_id": attempt_identity["attempt_id"],
        "attempt_output_root": _portable_persistent_path(output),
        "status": (
            "diagnostic_pass" if execution_mode.startswith("preflight_") and not failures
            else "pass" if not failures and len(statuses) == 8
            else "fail"
        ),
        "completed_trajectory_count": len(statuses),
        "guardrail_failure_count": len(failures),
        "held_out_periods_used": False,
        "candidate_promoted": False,
        "market_settlement_claim": False,
        "runtime_seconds": time.perf_counter() - started,
        "load_runtime_seconds": load_runtime_seconds,
        "build_runtime_seconds": sum(
            float(row.get("build_runtime_seconds") or 0.0) for row in statuses
        ),
        "solve_runtime_seconds": sum(
            float(row.get("solve_runtime_seconds") or 0.0) for row in statuses
        ),
        "write_runtime_seconds": sum(
            float(row.get("write_runtime_seconds") or 0.0) for row in statuses
        ),
        "execution_mode": execution_mode,
        "validation_claim_scope": (
            "volatile_replan_0_containment_only"
            if execution_mode == "preflight_volatile_containment"
            else "execution_mode_guardrails"
        ),
        "negative_price_validation_claimed": _negative_price_validation_claimed(
            execution_mode, guardrails
        ),
        "solver_model_count": len(solver_rows),
        "implementation_sha256": implementation_sha,
    }
    summary["write_runtime_seconds"] += time.perf_counter() - write_started
    _write_json(output / "run_summary.json", summary)
    if failures:
        raise SaleSensitivityError(f"Phase-2 guardrails failed: {len(failures)}")
    return summary
