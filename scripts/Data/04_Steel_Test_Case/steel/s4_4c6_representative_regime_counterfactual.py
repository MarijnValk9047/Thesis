"""Governed executor for the four-regime D-only hourly/QH steel study.

The executor consumes only frozen study artifacts.  It refuses blocked manifest
rows, preserves the shared Phase-6D internal quarter-hour physics, and writes
one resumable checkpoint per executed delivery day.  It does not implement
mFRR, CVaR, annualisation, or historical-quarter-hour claims.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    MIP_GAP_LIMIT,
    SteelActualPriceBundle,
    SteelPriceInformationBundle,
    SteelRollingState,
    _git_head,
    _scenario_inputs,
    _write_csv,
    clear_hourly_da_bids,
    expected_origin_utc,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import (
    EXPECTED_COST_INCUMBENT,
    FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
    IMBALANCE_ZERO_TOLERANCE_MWH,
    Phase6DEmergencyRecourse,
    Phase6DError,
    Phase6DPerformanceIncomplete,
    REDISPATCH_PHYSICAL_TIEBREAK_TIER,
    PLANNING_SOLVER_SEQUENTIAL,
    _context_for_market,
    _gurobi_version,
    solve_grouped_actual_redispatch,
    solve_grouped_da_bid_plan,
    validate_phase6d_trajectory,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


REPRESENTATIVE_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_representative_regime_counterfactual.yaml"
)
STRICT_MODEL_ID = "lear_lago_direct_dplus4_strict_no_future_1092"
LOCAL_TZ = "Europe/Amsterdam"
CONFIGURATIONS = {"C0": C0_CONFIGURATION, "C1": C1_CONFIGURATION}
CENTRAL_CLASSES = {"central", "central_benchmark"}
REQUIRED_STUDY_FILES = (
    "run_summary.json",
    "resolved_config.yaml",
    "steel_execution_readiness.json",
    "steel_experiment_manifest.csv",
    "selected_regime_weeks.csv",
    "counterfactual_qh_overlay.parquet",
)


class RepresentativeRegimeError(RuntimeError):
    """Raised when a frozen input, timing, or experiment contract fails."""


def _representative_run_contract(config: Mapping[str, Any]) -> dict[str, Any]:
    contract = config.get("experiment_contract", {})
    mode = contract.get("planning_physical_tiebreak_mode")
    if mode != EXPECTED_COST_INCUMBENT:
        raise RepresentativeRegimeError(
            "The representative study requires the explicit "
            "planning_physical_tiebreak_mode=expected_cost_incumbent contract."
        )
    if contract.get("planning_physical_tiebreak_solve_performed") is not False:
        raise RepresentativeRegimeError(
            "The representative V1 contract must skip the planning physical tie-break solve."
        )
    if (
        contract.get("feasibility_bid_selection_mode")
        != FEASIBILITY_BID_EXPECTED_COST_INCUMBENT
    ):
        raise RepresentativeRegimeError(
            "The feasibility-aware plan must retain the signature-broken expected-cost incumbent."
        )
    if contract.get("bid_signature_symmetry_breaking") is not True:
        raise RepresentativeRegimeError(
            "The canonical acceptance-signature symmetry break must remain active."
        )
    expected_parent_bridge = {
        "parent_round_restricted_bridge_active": True,
        "parent_round_bridge_fixed_scope": "economic_scenario_binaries_only",
        "parent_round_bridge_final_result_eligible": False,
        "parent_round_bridge_preservation_constraint_allowed": False,
        "parent_round_bridge_requires_full_expected_cost_resolve": True,
    }
    if any(contract.get(key) != value_ for key, value_ in expected_parent_bridge.items()):
        raise RepresentativeRegimeError(
            "The restricted parent-round warm-start bridge contract changed."
        )
    if contract.get("planning_solver_execution_mode") != PLANNING_SOLVER_SEQUENTIAL:
        raise RepresentativeRegimeError(
            "The governed planner must use sequential_pyomo tier orchestration."
        )
    if contract.get("gurobi_performance_options") != {"MIPFocus": 1}:
        raise RepresentativeRegimeError(
            "The governed runtime contract requires exactly MIPFocus=1."
        )
    path_contract = contract.get("path_feasibility_augmentation", {})
    expected_path_contract = {
        "active": True,
        "planner_scope": "C1_responsive_S10_only",
        "source_scope": "frozen_non_final_validation_only",
        "economic_scenario_probability_allowed": False,
        "expected_cost_weight_allowed": False,
        "final_test_source_allowed": False,
        "maximum_augmentation_rounds": 3,
        "maximum_patterns_added_per_round": 1,
    }
    if any(
        path_contract.get(key) != value_
        for key, value_ in expected_path_contract.items()
    ):
        raise RepresentativeRegimeError(
            "The frozen validation-derived path-feasibility contract changed."
        )
    if not str(path_contract.get("behavioural_config", "")).strip() or not str(
        path_contract.get("frozen_pattern_manifest", "")
    ).strip():
        raise RepresentativeRegimeError(
            "The final executor requires pinned behavioural and pattern artifacts."
        )
    manifest_sha256 = str(
        path_contract.get("frozen_pattern_manifest_sha256", "")
    )
    if len(manifest_sha256) != 64:
        raise RepresentativeRegimeError(
            "The path-feasibility pattern manifest needs a SHA-256 pin."
        )
    if contract.get("redispatch_physical_tiebreak_solve_performed") is not True:
        raise RepresentativeRegimeError(
            "The redispatch physical tie-break must remain active."
        )
    recourse = contract.get("execution_recourse", {})
    if (
        set(recourse)
        != {
            "active",
            "penalty_eur_per_mwh",
            "settlement_semantics",
            "e_program_compliance_claim_requires_zero_imbalance",
        }
        or recourse.get("active") is not True
        or float(recourse.get("penalty_eur_per_mwh", -1.0)) != 5000.0
        or recourse.get("settlement_semantics")
        != "artificial_symmetric_absolute_deviation_penalty"
        or recourse.get("e_program_compliance_claim_requires_zero_imbalance") is not True
    ):
        raise RepresentativeRegimeError(
            "The authorised EUR 5,000/MWh execution-recourse contract changed."
        )
    return {
        "planning_physical_tiebreak_mode": EXPECTED_COST_INCUMBENT,
        "planning_physical_tiebreak_solve_performed": False,
        "feasibility_bid_selection_mode": FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
        "bid_signature_symmetry_breaking": True,
        **expected_parent_bridge,
        "planning_solver_execution_mode": PLANNING_SOLVER_SEQUENTIAL,
        "gurobi_performance_options": {"MIPFocus": 1},
        **{
            f"path_feasibility_{key}": value_
            for key, value_ in expected_path_contract.items()
        },
        "path_feasibility_pattern_manifest_sha256": manifest_sha256,
        "redispatch_physical_tiebreak_solve_performed": True,
        "redispatch_physical_tiebreak_tier": REDISPATCH_PHYSICAL_TIEBREAK_TIER,
        "imbalance_recourse_active": True,
        "imbalance_penalty_eur_per_mwh": 5000.0,
        "e_program_compliance_claim_requires_zero_imbalance": True,
        "solver_name": "gurobi",
        "solver_version": _gurobi_version(),
        "solver_time_limit_seconds": float(contract["solver_time_limit_seconds"]),
        "solver_mip_gap_limit": float(contract["mip_gap_limit"]),
        "solver_economic_mip_gap_limit": float(
            contract["economic_mip_gap_limit"]
        ),
        "solver_integer_feasibility_tolerance": float(
            contract["integer_feasibility_tolerance"]
        ),
        "solver_seed": int(contract["solver_seed"]),
        "planning_selection_semantics": (
            "different_incumbent_within_preserved_production_and_expected_cost_optima"
        ),
    }


def _validate_execution_authorization(
    config: Mapping[str, Any], selected: pd.DataFrame, *, all_ready: bool
) -> None:
    authorization = config.get("execution_authorization", {})
    expected_trial_contract = {
        "maximum_trial_week_count": 1,
        "maximum_selected_experiments": 3,
        "allowed_configuration": "C1",
        "allowed_experiment_class": "central",
        "allowed_arms": ["A_hourly", "B_qh_flat", "C_qh_shape"],
        "scenario_count": 10,
        "horizon_hours": 24,
    }
    expected_full_contract = {
        "required_ready_scope": "central",
        "required_week_count": 4,
        "required_experiment_count": 56,
        "required_central_stochastic_count": 24,
        "required_benchmark_count": 32,
        "allowed_configurations": ["C0", "C1"],
        "allowed_experiment_classes": ["central", "central_benchmark"],
        "allowed_arms": [
            "A_hourly",
            "B_qh_flat",
            "C_qh_shape",
            "BC_qh_shared",
        ],
        "scenario_count": 10,
        "horizon_hours": 24,
        "maintenance_policy": "maintenance_free_normal_operation_week",
    }
    if any(
        authorization.get(key) != value
        for key, value in expected_trial_contract.items()
    ) or authorization.get("full_matrix_contract") != expected_full_contract:
        raise RepresentativeRegimeError(
            "The frozen trial/full-matrix authorization contract changed."
        )
    full_authorized = authorization.get("full_four_week_matrix_authorized")
    if full_authorized not in {True, False}:
        raise RepresentativeRegimeError(
            "The full-matrix authorization flag must be explicitly boolean."
        )
    receipt = authorization.get("authorization_receipt")
    timestamp = authorization.get("authorization_timestamp_utc")
    if full_authorized:
        if not all_ready:
            raise RepresentativeRegimeError(
                "A full-matrix receipt only authorizes the exact all-central-ready set."
            )
        if not str(receipt or "").strip() or not str(timestamp or "").strip():
            raise RepresentativeRegimeError(
                "Full-matrix execution requires an explicit authorization receipt and timestamp."
            )
        try:
            parsed_timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RepresentativeRegimeError(
                "The full-matrix authorization timestamp is invalid."
            ) from exc
        if parsed_timestamp.tzinfo is None:
            raise RepresentativeRegimeError(
                "The full-matrix authorization timestamp must be timezone-aware."
            )
        checks = {
            "experiment_count": len(selected)
            == int(expected_full_contract["required_experiment_count"]),
            "week_count": selected["week_id"].astype(str).nunique()
            == int(expected_full_contract["required_week_count"]),
            "central_stochastic_count": int(
                selected["experiment_class"].astype(str).eq("central").sum()
            )
            == int(expected_full_contract["required_central_stochastic_count"]),
            "benchmark_count": int(
                selected["experiment_class"]
                .astype(str)
                .eq("central_benchmark")
                .sum()
            )
            == int(expected_full_contract["required_benchmark_count"]),
            "configurations": set(selected["configuration"].astype(str))
            == set(expected_full_contract["allowed_configurations"]),
            "experiment_classes": set(selected["experiment_class"].astype(str))
            == set(expected_full_contract["allowed_experiment_classes"]),
            "arms": set(selected["arm"].astype(str))
            == set(expected_full_contract["allowed_arms"]),
            "scenario_count": selected["scenario_count"]
            .astype(int)
            .eq(int(expected_full_contract["scenario_count"]))
            .all(),
            "horizon_hours": selected["horizon_hours"]
            .astype(int)
            .eq(int(expected_full_contract["horizon_hours"]))
            .all(),
            "maintenance_policy": selected["maintenance_policy"]
            .astype(str)
            .eq(expected_full_contract["maintenance_policy"])
            .all(),
            "weekly_maintenance_inactive": not bool(
                selected["weekly_eaf_maintenance_active"].astype(bool).any()
            ),
            "annual_outage_inactive": not bool(
                selected["annual_outage_active"].astype(bool).any()
            ),
        }
        failed = [name for name, passed in checks.items() if not bool(passed)]
        if failed:
            raise RepresentativeRegimeError(
                "The selected full-matrix set differs from the frozen 56-row "
                f"contract: {failed}."
            )
        return
    if receipt is not None or timestamp is not None:
        raise RepresentativeRegimeError(
            "An inactive full-matrix authorization may not retain a receipt."
        )
    if all_ready:
        raise RepresentativeRegimeError(
            "The full four-week matrix is not authorized; --all-central-ready is blocked."
        )
    if len(selected) > int(authorization["maximum_selected_experiments"]):
        raise RepresentativeRegimeError("More than three trial experiments were selected.")
    if selected["week_id"].astype(str).nunique() > int(
        authorization["maximum_trial_week_count"]
    ):
        raise RepresentativeRegimeError("More than one trial week was selected.")
    checks = {
        "configuration": selected["configuration"].astype(str).eq("C1").all(),
        "experiment_class": selected["experiment_class"]
        .astype(str)
        .eq("central")
        .all(),
        "arm": set(selected["arm"].astype(str)).issubset(
            set(authorization["allowed_arms"])
        ),
        "scenario_count": selected["scenario_count"].astype(int).eq(10).all(),
        "horizon_hours": selected["horizon_hours"].astype(int).eq(24).all(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RepresentativeRegimeError(
            f"Selected experiments exceed the one-week C1 S10 D-only authorization: {failed}."
        )


@dataclass(frozen=True)
class StudyFrames:
    study_root: Path
    family_root: Path
    experiment_manifest: pd.DataFrame
    selected_weeks: pd.DataFrame
    hourly_points: pd.DataFrame
    hourly_scenarios_10: pd.DataFrame
    hourly_scenarios_30: pd.DataFrame
    qh_overlay: pd.DataFrame


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_frozen_path_feasibility_patterns(
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Path]:
    """Load and validate the pinned probability-free non-final pattern pool."""

    path_contract = config["experiment_contract"][
        "path_feasibility_augmentation"
    ]
    manifest_path = _resolve(path_contract["frozen_pattern_manifest"])
    if not manifest_path.exists():
        raise RepresentativeRegimeError(
            "The frozen path-feasibility pattern manifest is unavailable."
        )
    expected_sha256 = str(path_contract["frozen_pattern_manifest_sha256"])
    if _sha256(manifest_path) != expected_sha256:
        raise RepresentativeRegimeError(
            "The frozen path-feasibility pattern manifest hash changed."
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    patterns = [dict(item) for item in payload.get("patterns", [])]
    if (
        not patterns
        or int(payload.get("pattern_count", -1)) != len(patterns)
        or payload.get("probability_assigned") is not False
        or payload.get("expected_cost_weight_assigned") is not False
        or int(payload.get("final_test_source_count", -1)) != 0
    ):
        raise RepresentativeRegimeError(
            "The path manifest lost its feasibility-only lineage contract."
        )
    forbidden_price_fields = {"raw_prices", "actual_prices", "scenario_prices"}
    for pattern in patterns:
        if (
            pattern.get("economic_scenario") is not False
            or pattern.get("settlement_eligible") is not False
            or pattern.get("forecast_metric_eligible") is not False
            or pattern.get("final_test_case") is not False
            or pattern.get("cutoff_status") != "D_minus_1_compliant"
            or forbidden_price_fields.intersection(pattern)
            or "probability" in pattern
            or "expected_cost_weight" in pattern
        ):
            raise RepresentativeRegimeError(
                "A frozen feasibility pattern acquired economic weight, final input, "
                "raw prices, or an invalid cutoff."
            )
    if {str(item["market_grid"]) for item in patterns} != {
        "hourly",
        "quarterhour",
    }:
        raise RepresentativeRegimeError(
            "The frozen pattern pool must cover hourly and quarter-hour grids."
        )
    return sorted(patterns, key=lambda item: str(item["path_id"])), manifest_path


def _solve_final_c1_path_feasible_plan(
    config: Mapping[str, Any],
    frames: StudyFrames,
    row: Mapping[str, Any],
    *,
    delivery_day: date,
    state: SteelRollingState,
    experiment_root: Path,
    bundle: SteelPriceInformationBundle,
) -> tuple[Any, dict[str, Any]]:
    """Use the validated constraint-generation planner for a final C1 S10 day."""

    from .s4_4c6_behavioural_validation import (
        load_behavioural_config,
        solve_constraint_generated_bid_plan,
    )

    path_contract = config["experiment_contract"][
        "path_feasibility_augmentation"
    ]
    patterns, manifest_path = _load_frozen_path_feasibility_patterns(config)
    behavioural_config = load_behavioural_config(
        path_contract["behavioural_config"]
    )
    behavioural_path_contract = behavioural_config["frozen_contract"][
        "path_feasibility_augmentation"
    ]
    if (
        int(behavioural_path_contract["maximum_augmentation_rounds"])
        != int(path_contract["maximum_augmentation_rounds"])
        or int(behavioural_path_contract["maximum_patterns_added_per_round"])
        != int(path_contract["maximum_patterns_added_per_round"])
    ):
        raise RepresentativeRegimeError(
            "Representative and validated augmentation governance differ."
        )
    arm = str(row["arm"])
    granularity = "hourly" if arm == "A_hourly" else "quarterhour"
    case = {
        "case_id": f"{row['experiment_id']}__{delivery_day.isoformat()}",
        "phase": "final_representative",
        "profile_id": str(row["regime_role"]),
        "day_id": str(row["week_id"]),
        "delivery_day": delivery_day.isoformat(),
        "configuration": "C1",
        "policy": "responsive",
        "arm": arm,
        "granularity": granularity,
        "final_test_case": True,
    }
    prepared = {
        "config": behavioural_config,
        "representative": config,
        "shadow_frames": frames,
        "output": experiment_root,
    }
    generated = solve_constraint_generated_bid_plan(
        prepared, case, patterns, state
    )
    if generated.get("status") != "pass":
        raise RepresentativeRegimeError(
            "Final C1 path-feasibility augmentation did not pass."
        )
    plan = generated["plan"]
    scenario_prices, probabilities = _scenario_inputs(plan.policy, bundle, None)
    expected_s10_sha256 = _canonical_payload_sha256(
        {
            "scenario_ids": tuple(sorted(scenario_prices)),
            "scenario_prices": scenario_prices,
            "scenario_probabilities": probabilities,
        }
    )
    if (
        len(scenario_prices) != 10
        or abs(sum(probabilities.values()) - 1.0) > 1e-12
        or plan.solver.get("economic_s10_contract_sha256")
        != expected_s10_sha256
    ):
        raise RepresentativeRegimeError(
            "Path augmentation changed the frozen economic S10 contract."
        )
    metadata = {
        "status": "pass",
        "candidate_pattern_count": len(patterns),
        "selected_pattern_count": len(generated["selected_paths"]),
        "selected_path_ids": [
            str(item["path_id"]) for item in generated["selected_paths"]
        ],
        "rounds": generated["rounds"],
        "pattern_manifest": manifest_path.relative_to(REPO_ROOT).as_posix(),
        "pattern_manifest_sha256": _sha256(manifest_path),
        "economic_s10_contract_sha256": expected_s10_sha256,
        "probability_assigned_to_feasibility_paths": False,
        "expected_cost_weight_assigned_to_feasibility_paths": False,
    }
    return plan, metadata


def _experiment_directory_name(experiment_id: str) -> str:
    """Keep governed Windows paths bounded while preserving identity in-file."""

    return hashlib.sha256(experiment_id.encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resume_blockers(run_root: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name in (
        "run_control.json",
        "termination_addendum.json",
        "manual_stop_summary.json",
    ):
        path = run_root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(
                {
                    "source": name,
                    "reason": "unreadable_stop_contract",
                    "error": str(exc),
                }
            )
            continue
        if payload.get("resume_authorized") is False:
            blockers.append(
                {
                    "source": name,
                    "reason": "resume_authorized_false",
                    "status": payload.get("status"),
                }
            )
    return blockers


def _assert_run_execution_authorized(run_root: Path, *, resume: bool) -> None:
    blockers = _resume_blockers(run_root)
    if blockers:
        action = "resume" if resume else "continue"
        raise RepresentativeRegimeError(
            f"Run {action} refused by fail-closed stop sentinel: {blockers}."
        )


def _write_run_control(
    run_root: Path,
    *,
    status: str,
    resume_authorized: bool,
    reason: str,
    diagnostic: Mapping[str, Any] | None = None,
) -> None:
    existing_path = run_root / "run_control.json"
    existing: dict[str, Any] = {}
    if existing_path.exists():
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
    _write_json(
        existing_path,
        {
            **existing,
            "status": status,
            "resume_authorized": bool(resume_authorized),
            "reason": reason,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "superseded_by_conditional_minimum_imbalance_gate": True,
            "diagnostic": dict(diagnostic or {}),
        },
    )


def _solver_progress_callback(
    run_root: Path,
    *,
    experiment_id: str,
    delivery_day: date,
    solve_stage: str,
) -> Callable[[Mapping[str, Any]], None]:
    def record(event: Mapping[str, Any]) -> None:
        if event.get("event") == "solver_tier_started":
            _assert_run_execution_authorized(run_root, resume=False)
        enriched = {
            "experiment_id": experiment_id,
            "delivery_day": delivery_day.isoformat(),
            "solve_stage": solve_stage,
            "flushed_at_utc": datetime.now(timezone.utc).isoformat(),
            **dict(event),
        }
        ledger_path = run_root / "solver_tier_progress.json"
        ledger: list[dict[str, Any]] = []
        if ledger_path.exists():
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger = list(payload.get("events", []))
        ledger.append(enriched)
        _write_json(
            ledger_path,
            {
                "event_count": len(ledger),
                "events": ledger,
                "latest": enriched,
            },
        )
        _write_json(run_root / "progress_current.json", enriched)

    return record


def load_representative_config(
    path: str | Path = REPRESENTATIVE_CONFIG,
) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RepresentativeRegimeError("Representative-regime config must be a mapping.")
    if payload.get("output_policy") != "minimal":
        raise RepresentativeRegimeError("The representative study requires output_policy=minimal.")
    contract = payload.get("experiment_contract", {})
    exact = {
        "main_horizon_hours": 24,
        "execution_hours": 24,
        "main_scenario_count": 10,
        "solver_time_limit_seconds": 900,
        "solver_seed": 0,
    }
    for key, expected in exact.items():
        if int(contract.get(key, -1)) != expected:
            raise RepresentativeRegimeError(f"Frozen experiment contract changed: {key}.")
    forbidden_false = (
        "weekly_eaf_maintenance_active",
        "annual_outage_active",
        "mfrr_active",
        "annualisation_allowed",
        "historical_qh_claim_allowed",
        "positive_economic_effect_required",
    )
    if any(bool(contract.get(key, True)) for key in forbidden_false):
        raise RepresentativeRegimeError("A forbidden scope or claim was activated.")
    if contract.get("maintenance_policy") != "maintenance_free_normal_operation_week":
        raise RepresentativeRegimeError("The four weeks must remain maintenance-free.")
    if float(contract.get("mip_gap_limit", -1.0)) != MIP_GAP_LIMIT:
        raise RepresentativeRegimeError("Frozen experiment contract changed: mip_gap_limit.")
    if float(contract.get("economic_mip_gap_limit", -1.0)) != 0.002:
        raise RepresentativeRegimeError(
            "Frozen experiment contract changed: economic_mip_gap_limit."
        )
    if float(contract.get("integer_feasibility_tolerance", -1.0)) != 1e-9:
        raise RepresentativeRegimeError(
            "Frozen experiment contract changed: integer_feasibility_tolerance."
        )
    _representative_run_contract(payload)
    return payload


def load_study_frames(config: Mapping[str, Any]) -> StudyFrames:
    study_root = _resolve(config["study_run_root"])
    for name in REQUIRED_STUDY_FILES:
        if not (study_root / name).exists():
            raise RepresentativeRegimeError(f"Missing frozen study artifact: {name}")
    summary = json.loads((study_root / "run_summary.json").read_text(encoding="utf-8"))
    accepted_statuses = {
        "prepared_but_steel_execution_blocked",
        "donly_split_horizon_ready_long_price_horizons_blocked",
    }
    if summary.get("status") not in accepted_statuses:
        raise RepresentativeRegimeError("Study input status is not a governed readiness state.")
    readiness = json.loads(
        (study_root / "steel_execution_readiness.json").read_text(encoding="utf-8")
    )
    if readiness.get("status") not in {"blocked", "partially_ready"} or not readiness.get(
        "scenario_30_support_available"
    ):
        raise RepresentativeRegimeError("Frozen S10/S30 inputs or readiness are inconsistent.")
    legacy_blocked = readiness.get("c1_donly_24h_feasible") is False
    split_ready = readiness.get("c1_split_horizon_feasible") is True
    if not (legacy_blocked or split_ready):
        raise RepresentativeRegimeError("No governed C1 D-only physical-horizon state is active.")
    resolved = yaml.safe_load((study_root / "resolved_config.yaml").read_text(encoding="utf-8"))
    family_root = _resolve(resolved["forecast_family_audit"]["accepted_run_root"])
    family_files = {
        "points": family_root / "common_point_forecasts_with_actuals.parquet",
        "s10": family_root / "scenario_prices_long.parquet",
        "s30": family_root / "strict_scenario_prices_30.parquet",
    }
    for path in family_files.values():
        if not path.exists():
            raise RepresentativeRegimeError(f"Missing accepted family artifact: {path.name}")
    return StudyFrames(
        study_root=study_root,
        family_root=family_root,
        experiment_manifest=pd.read_csv(study_root / "steel_experiment_manifest.csv"),
        selected_weeks=pd.read_csv(study_root / "selected_regime_weeks.csv"),
        hourly_points=pd.read_parquet(family_files["points"]),
        hourly_scenarios_10=pd.read_parquet(family_files["s10"]),
        hourly_scenarios_30=pd.read_parquet(family_files["s30"]),
        qh_overlay=pd.read_parquet(study_root / "counterfactual_qh_overlay.parquet"),
    )


def _local_day_mask(timestamps: pd.Series, delivery_day: date) -> pd.Series:
    return pd.to_datetime(timestamps, utc=True).dt.tz_convert(LOCAL_TZ).dt.date.eq(delivery_day)


def _scenario_maps(
    rows: pd.DataFrame,
    *,
    timestamp_column: str,
    price_column: str,
    source_column: str,
    scenario_count: int,
) -> tuple[dict[str, tuple[float, ...]], dict[str, float], dict[str, str]]:
    scenario_prices: dict[str, tuple[float, ...]] = {}
    probabilities: dict[str, float] = {}
    sources: dict[str, str] = {}
    for scenario_id, path in rows.groupby("scenario_id", sort=True):
        path = path.sort_values(timestamp_column)
        probabilities_seen = path["scenario_probability"].drop_duplicates().tolist()
        if len(probabilities_seen) != 1:
            raise RepresentativeRegimeError(f"Scenario probability varies within {scenario_id}.")
        scenario_prices[str(scenario_id)] = tuple(path[price_column].astype(float))
        probabilities[str(scenario_id)] = float(probabilities_seen[0])
        sources[str(scenario_id)] = "|".join(sorted(path[source_column].astype(str).unique()))
    if len(scenario_prices) != scenario_count:
        raise RepresentativeRegimeError(
            f"Expected {scenario_count} scenarios, found {len(scenario_prices)}."
        )
    if abs(sum(probabilities.values()) - 1.0) > 1e-10:
        raise RepresentativeRegimeError("Scenario probability mass differs from one.")
    return scenario_prices, probabilities, sources


def build_price_bundles(
    frames: StudyFrames,
    *,
    week_id: str,
    delivery_day: date,
    arm: str,
    scenario_count: int,
) -> tuple[SteelPriceInformationBundle, SteelActualPriceBundle]:
    if scenario_count not in {10, 30}:
        raise RepresentativeRegimeError("Only the frozen S10 and nested S30 sets are supported.")
    origin = expected_origin_utc(delivery_day)
    if arm == "A_hourly":
        points = frames.hourly_points[
            frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
            & frames.hourly_points["delivery_date_local"].eq(delivery_day.isoformat())
        ].sort_values("target_timestamp_utc")
        scenario_frame = (
            frames.hourly_scenarios_10 if scenario_count == 10 else frames.hourly_scenarios_30
        )
        scenarios = scenario_frame[
            scenario_frame["model_id"].eq(STRICT_MODEL_ID)
            & scenario_frame["delivery_date_local"].eq(delivery_day.isoformat())
        ].copy()
        if len(points) != 24 or points["target_timestamp_utc"].nunique() != 24:
            raise RepresentativeRegimeError("Hourly delivery support is not one complete non-DST day.")
        origins = pd.to_datetime(points["forecast_origin_utc"], utc=True).drop_duplicates()
        if len(origins) != 1 or origins.iloc[0] != origin:
            raise RepresentativeRegimeError("Hourly origin differs from D-1 08:00 local.")
        scenario_prices, probabilities, sources = _scenario_maps(
            scenarios,
            timestamp_column="target_timestamp_utc",
            price_column="scenario_price",
            source_column="source_residual_block_id",
            scenario_count=scenario_count,
        )
        timestamps = tuple(pd.to_datetime(points["target_timestamp_utc"], utc=True))
        bundle = SteelPriceInformationBundle(
            delivery_day=delivery_day,
            forecast_origin_utc=origin,
            timestamps_utc=timestamps,
            point_prices=tuple(points["point_forecast"].astype(float)),
            scenario_prices=scenario_prices,
            scenario_probabilities=probabilities,
            scenario_source_blocks=sources,
            model_id=STRICT_MODEL_ID,
            granularity="hourly",
            time_step_hours=1.0,
        )
        actuals = SteelActualPriceBundle(
            delivery_day=delivery_day,
            timestamps_utc=timestamps,
            prices=tuple(points["actual_price"].astype(float)),
            granularity="hourly",
            time_step_hours=1.0,
        )
    elif arm in {"B_qh_flat", "C_qh_shape", "BC_qh_shared"}:
        point_kind = "point_flat" if arm == "B_qh_flat" else "point_shape"
        scenario_kind = "scenario_flat" if arm == "B_qh_flat" else "scenario_shape"
        selected = frames.qh_overlay[
            frames.qh_overlay["week_id"].eq(week_id)
            & _local_day_mask(frames.qh_overlay["target_timestamp_utc"], delivery_day)
        ].copy()
        points = selected[selected["path_kind"].eq(point_kind)].sort_values(
            "target_timestamp_utc"
        )
        scenarios = selected[
            selected["path_kind"].eq(scenario_kind)
            & selected["scenario_set_size"].eq(scenario_count)
        ].copy()
        actual_rows = selected[selected["path_kind"].eq("counterfactual_actual")].sort_values(
            "target_timestamp_utc"
        )
        if any(len(rows) != 96 for rows in (points, actual_rows)):
            raise RepresentativeRegimeError("Quarter-hour point/actual support is not one complete day.")
        scenario_prices, probabilities, sources = _scenario_maps(
            scenarios,
            timestamp_column="target_timestamp_utc",
            price_column="quarterhour_price",
            source_column="source_profile_id",
            scenario_count=scenario_count,
        )
        timestamps = tuple(pd.to_datetime(points["target_timestamp_utc"], utc=True))
        actual_timestamps = tuple(pd.to_datetime(actual_rows["target_timestamp_utc"], utc=True))
        if timestamps != actual_timestamps:
            raise RepresentativeRegimeError("Quarter-hour point and actual timestamps differ.")
        bundle = SteelPriceInformationBundle(
            delivery_day=delivery_day,
            forecast_origin_utc=origin,
            timestamps_utc=timestamps,
            point_prices=tuple(points["quarterhour_price"].astype(float)),
            scenario_prices=scenario_prices,
            scenario_probabilities=probabilities,
            scenario_source_blocks=sources,
            model_id=f"{STRICT_MODEL_ID}__counterfactual_{point_kind}",
            granularity="quarterhour",
            time_step_hours=0.25,
        )
        actuals = SteelActualPriceBundle(
            delivery_day=delivery_day,
            timestamps_utc=actual_timestamps,
            prices=tuple(actual_rows["quarterhour_price"].astype(float)),
            granularity="quarterhour",
            time_step_hours=0.25,
        )
    else:
        raise RepresentativeRegimeError(f"Unsupported arm: {arm}")
    bundle.assert_actual_free()
    expected_steps = int(round(24 / bundle.time_step_hours))
    if len(bundle.timestamps_utc) != expected_steps:
        raise RepresentativeRegimeError("Bundle is not exactly D-only.")
    if any(len(path) != expected_steps for path in bundle.scenario_prices.values()):
        raise RepresentativeRegimeError("At least one scenario path has incomplete support.")
    return bundle, actuals


def _base_context_config(
    config: Mapping[str, Any], *, market_granularity: str, horizon_hours: int
) -> dict[str, Any]:
    base_path = _resolve(config["base_phase6d_config"])
    payload = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    phase = payload["phase6d"]
    contract = config["experiment_contract"]
    tail = contract.get("physical_feasibility_tail", {})
    tail_active = bool(tail.get("active", False)) and int(horizon_hours) == int(
        contract["main_horizon_hours"]
    )
    physical_horizon_hours = (
        int(tail["physical_horizon_hours"])
        if tail_active
        else int(horizon_hours)
    )
    phase["planning_horizon_hours"] = physical_horizon_hours
    phase["execution_hours"] = 24
    run_contract = _representative_run_contract(config)
    phase["solver_time_limit_seconds"] = run_contract["solver_time_limit_seconds"]
    phase["mip_gap_limit"] = run_contract["solver_mip_gap_limit"]
    phase["economic_mip_gap_limit"] = run_contract[
        "solver_economic_mip_gap_limit"
    ]
    phase["integer_feasibility_tolerance"] = run_contract[
        "solver_integer_feasibility_tolerance"
    ]
    phase["solver_seed"] = run_contract["solver_seed"]
    phase["planning_physical_tiebreak_mode"] = run_contract[
        "planning_physical_tiebreak_mode"
    ]
    phase["feasibility_bid_selection_mode"] = run_contract[
        "feasibility_bid_selection_mode"
    ]
    phase["bid_signature_symmetry_breaking"] = run_contract[
        "bid_signature_symmetry_breaking"
    ]
    phase["parent_round_restricted_bridge_active"] = run_contract[
        "parent_round_restricted_bridge_active"
    ]
    phase["planning_solver_execution_mode"] = run_contract[
        "planning_solver_execution_mode"
    ]
    phase["gurobi_performance_options"] = dict(
        run_contract["gurobi_performance_options"]
    )
    phase["economic_horizon_hours"] = (
        int(tail["economic_horizon_hours"])
        if tail_active
        else None
    )
    phase["physical_feasibility_tail_active"] = tail_active
    phase["eaf_heat_state"]["maintenance_intervals"] = []
    phase["eaf_heat_state"]["normal_operation_day_no_planned_maintenance"] = True
    context = _context_for_market(payload, market_granularity)
    context.config.update(
        {
            "planning_physical_tiebreak_mode": run_contract[
                "planning_physical_tiebreak_mode"
            ],
            "feasibility_bid_selection_mode": run_contract[
                "feasibility_bid_selection_mode"
            ],
            "bid_signature_symmetry_breaking": run_contract[
                "bid_signature_symmetry_breaking"
            ],
            "parent_round_restricted_bridge_active": run_contract[
                "parent_round_restricted_bridge_active"
            ],
            "planning_solver_execution_mode": run_contract[
                "planning_solver_execution_mode"
            ],
            "gurobi_performance_options": dict(
                run_contract["gurobi_performance_options"]
            ),
            "solver_time_limit_seconds": run_contract["solver_time_limit_seconds"],
            "mip_gap_limit": run_contract["solver_mip_gap_limit"],
            "economic_mip_gap_limit": run_contract[
                "solver_economic_mip_gap_limit"
            ],
            "integer_feasibility_tolerance": run_contract[
                "solver_integer_feasibility_tolerance"
            ],
            "solver_seed": run_contract["solver_seed"],
        }
    )
    return context


def preflight(
    config_path: str | Path = REPRESENTATIVE_CONFIG,
) -> dict[str, Any]:
    config = load_representative_config(config_path)
    frames = load_study_frames(config)
    manifest = frames.experiment_manifest
    if manifest["experiment_id"].duplicated().any():
        raise RepresentativeRegimeError("Experiment IDs are not unique.")
    if manifest["weekly_eaf_maintenance_active"].astype(bool).any() or manifest[
        "annual_outage_active"
    ].astype(bool).any():
        raise RepresentativeRegimeError("A manifest row activates maintenance.")
    ready = manifest[manifest["economic_execution_ready"].astype(bool)]
    blocked = manifest[~manifest["economic_execution_ready"].astype(bool)]
    sample_week = frames.selected_weeks.iloc[0]
    sample_day = date.fromisoformat(str(sample_week["week_start"]))
    bundle_checks = {}
    for arm, count in (("A_hourly", 10), ("B_qh_flat", 10), ("C_qh_shape", 30)):
        bundle, actuals = build_price_bundles(
            frames,
            week_id=str(sample_week["week_id"]),
            delivery_day=sample_day,
            arm=arm,
            scenario_count=count,
        )
        bundle_checks[f"{arm}_S{count}"] = {
            "timestamps": len(bundle.timestamps_utc),
            "scenario_count": len(bundle.scenario_prices),
            "probability_mass": sum(bundle.scenario_probabilities.values()),
            "actual_timestamps": len(actuals.timestamps_utc),
            "origin_utc": bundle.forecast_origin_utc.isoformat(),
        }
    return {
        "status": "pass",
        "study_run_id": frames.study_root.name,
        "experiment_rows": int(len(manifest)),
        "ready_rows": int(len(ready)),
        "blocked_rows": int(len(blocked)),
        "blocked_horizons": sorted(blocked["horizon_hours"].astype(int).unique().tolist()),
        "selected_week_count": int(len(frames.selected_weeks)),
        "maintenance_free": True,
        "mFRR_active": False,
        **_representative_run_contract(config),
        "bundle_checks": bundle_checks,
    }


def select_experiments(
    manifest: pd.DataFrame,
    experiment_ids: Sequence[str],
    *,
    all_ready: bool = False,
    ready_scope: str | None = None,
) -> pd.DataFrame:
    if ready_scope not in {None, "central", "sensitivity"}:
        raise RepresentativeRegimeError("Unsupported ready experiment scope.")
    if not experiment_ids and not all_ready:
        raise RepresentativeRegimeError("Choose at least one --experiment-id or use --all-ready.")
    if all_ready:
        mask = manifest["economic_execution_ready"].astype(bool)
        if ready_scope == "central":
            mask &= manifest["experiment_class"].isin(CENTRAL_CLASSES)
        elif ready_scope == "sensitivity":
            mask &= ~manifest["experiment_class"].isin(CENTRAL_CLASSES)
        selected = manifest[mask].copy()
    else:
        selected = manifest[manifest["experiment_id"].isin(experiment_ids)].copy()
    missing = sorted(set(experiment_ids) - set(selected["experiment_id"]))
    if missing:
        raise RepresentativeRegimeError(f"Unknown experiment IDs: {missing}")
    blocked = selected[~selected["economic_execution_ready"].astype(bool)]
    if not blocked.empty:
        details = blocked[["experiment_id", "blockers"]].to_dict(orient="records")
        raise RepresentativeRegimeError(f"Fail-closed experiment rows selected: {details}")
    if selected.empty:
        raise RepresentativeRegimeError("No executable experiment rows were selected.")
    central = selected["experiment_class"].isin(CENTRAL_CLASSES)
    if central.any() and not central.all():
        raise RepresentativeRegimeError("Central and sensitivity rows require separate governed runs.")
    return selected.sort_values("experiment_id").reset_index(drop=True)


def _policy(row: Mapping[str, Any], granularity: str) -> str:
    benchmark = str(row["benchmark"])
    if benchmark == "price_insensitive":
        return "price-insensitive"
    if benchmark == "true_perfect_foresight":
        return "true-PF"
    prefix = "H" if granularity == "hourly" else "QH"
    return f"{prefix}-S{int(row['scenario_count'])}"


def _state_from_snapshot(snapshot: Mapping[str, Any]) -> SteelRollingState:
    return SteelRollingState(
        episode_id=str(snapshot["episode_id"]),
        configuration_id=str(snapshot["configuration_id"]),
        inventory_overrides=dict(snapshot.get("inventory_overrides", {})),
        cumulative_production_t=float(snapshot.get("cumulative_production_t", 0.0)),
        executed_hours=int(snapshot.get("executed_hours", 0)),
        executed_intervals=int(snapshot.get("executed_intervals", 0)),
        last_executed_timestamp_utc=snapshot.get("last_executed_timestamp_utc"),
        cumulative_route_progress_t=dict(snapshot.get("cumulative_route_progress_t", {})),
        eaf_start_lag1=int(snapshot.get("eaf_start_lag1", 0)),
        eaf_start_lag2=int(snapshot.get("eaf_start_lag2", 0)),
        drp_last_pellet_input_t=snapshot.get("drp_last_pellet_input_t"),
    )


def run_experiment(
    config: Mapping[str, Any],
    frames: StudyFrames,
    row: Mapping[str, Any],
    experiment_root: Path,
    *,
    resume: bool,
    day_limit: int = 7,
) -> dict[str, Any]:
    experiment_id = str(row["experiment_id"])
    horizon_hours = int(row["horizon_hours"])
    if horizon_hours != 24:
        raise RepresentativeRegimeError(
            "Long-horizon execution is unavailable until causal Strict D+1...D+4 support exists."
        )
    arm = str(row["arm"])
    bundle_arm = "C_qh_shape" if arm == "BC_qh_shared" else arm
    granularity = "hourly" if arm == "A_hourly" else "quarterhour"
    configuration = CONFIGURATIONS[str(row["configuration"])]
    policy = _policy(row, granularity)
    run_contract = _representative_run_contract(config)
    context = _base_context_config(
        config, market_granularity=granularity, horizon_hours=horizon_hours
    )
    if int(day_limit) < 1 or int(day_limit) > 7:
        raise RepresentativeRegimeError("day_limit must stay inside one complete week.")
    week_start = date.fromisoformat(str(row["week_start"]))
    days = [week_start + timedelta(days=offset) for offset in range(int(day_limit))]
    output_dir = experiment_root / "experiments" / _experiment_directory_name(experiment_id)
    checkpoint_path = output_dir / "checkpoint.json"
    input_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "row": dict(row),
                "day_limit": int(day_limit),
                "study_summary_sha256": _sha256(frames.study_root / "run_summary.json"),
                "overlay_sha256": _sha256(frames.study_root / "counterfactual_qh_overlay.parquet"),
                "run_contract": run_contract,
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    daily: list[dict[str, Any]] = []
    submitted_bids: list[dict[str, Any]] = []
    realised_clearing: list[dict[str, Any]] = []
    executed_physical: list[dict[str, Any]] = []
    solver_records: list[dict[str, Any]] = []
    state = SteelRollingState(episode_id=experiment_id, configuration_id=configuration)
    _assert_run_execution_authorized(experiment_root, resume=resume)
    if resume and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("input_fingerprint") != input_fingerprint:
            raise RepresentativeRegimeError("Checkpoint fingerprint differs from frozen inputs.")
        daily = list(checkpoint.get("daily_results", []))
        submitted_bids = list(checkpoint.get("submitted_bids", []))
        realised_clearing = list(checkpoint.get("realised_clearing", []))
        executed_physical = list(checkpoint.get("executed_physical", []))
        solver_records = list(checkpoint.get("solver_records", []))
        state = _state_from_snapshot(checkpoint["state"])
    elif checkpoint_path.exists():
        raise RepresentativeRegimeError("Output exists; use --resume or choose a new run ID.")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "experiment_identity.json",
        {"experiment_id": experiment_id, "directory_key": output_dir.name},
    )
    started = time.perf_counter()
    for delivery_day in days[len(daily) :]:
        _assert_run_execution_authorized(experiment_root, resume=False)
        before = state.snapshot()
        bundle, actuals = build_price_bundles(
            frames,
            week_id=str(row["week_id"]),
            delivery_day=delivery_day,
            arm=bundle_arm,
            scenario_count=int(row["scenario_count"]),
        )
        oracle = actuals if policy == "true-PF" else None
        if (
            configuration == C1_CONFIGURATION
            and str(row["experiment_class"]) == "central"
            and policy in {"H-S10", "QH-S10"}
        ):
            plan, path_generation = _solve_final_c1_path_feasible_plan(
                config,
                frames,
                row,
                delivery_day=delivery_day,
                state=state,
                experiment_root=experiment_root,
                bundle=bundle,
            )
        else:
            path_generation = {
                "status": "not_applicable",
                "candidate_pattern_count": 0,
                "selected_pattern_count": 0,
                "selected_path_ids": [],
                "rounds": [],
                "probability_assigned_to_feasibility_paths": False,
                "expected_cost_weight_assigned_to_feasibility_paths": False,
            }
            plan = solve_grouped_da_bid_plan(
                context,
                configuration,
                bundle,
                state,
                policy,
                actuals_oracle=oracle,
                progress_callback=_solver_progress_callback(
                    experiment_root,
                    experiment_id=experiment_id,
                    delivery_day=delivery_day,
                    solve_stage="planning",
                ),
            )
        if abs(float(plan.solver["expected_cost_reconstruction_error_eur"])) > (
            float(plan.solver["expected_cost_reconstruction_tolerance_eur"]) + 1e-6
        ):
            raise RepresentativeRegimeError(
                "Independent expected-objective reconstruction failed."
            )
        if plan.solver["planning_physical_tiebreak_mode"] != run_contract[
            "planning_physical_tiebreak_mode"
        ] or bool(plan.solver["physical_tiebreak_solve_performed"]):
            raise RepresentativeRegimeError(
                "The planning solve did not preserve the promoted V1 selection contract."
            )
        clearing = clear_hourly_da_bids(plan.bids, actuals)
        redispatch = solve_grouped_actual_redispatch(
            context,
            configuration,
            clearing,
            state,
            bundle.point_prices,
            oracle_execute_D_cost_only=policy == "true-PF",
            imbalance_penalty_eur_per_mwh=float(
                config["experiment_contract"]["execution_recourse"][
                    "penalty_eur_per_mwh"
                ]
            ),
            progress_callback=_solver_progress_callback(
                experiment_root,
                experiment_id=experiment_id,
                delivery_day=delivery_day,
                solve_stage="redispatch",
            ),
        )
        if not bool(redispatch.solver["physical_tiebreak_solve_performed"]):
            raise RepresentativeRegimeError(
                "The redispatch physical tie-break contract was not executed."
            )
        redispatch_tiers = {
            str(item["tier"]) for item in redispatch.solver["tier_solves"]
        }
        if REDISPATCH_PHYSICAL_TIEBREAK_TIER not in redispatch_tiers:
            raise RepresentativeRegimeError(
                "The redispatch solver record omits its physical tie-break tier."
            )
        allocated_settlement = sum(
            float(item["allocated_pay_as_cleared_settlement_eur"])
            for item in redispatch.physical_intervals
        )
        if abs(allocated_settlement - clearing.settlement_cost_eur) > 1e-4:
            raise RepresentativeRegimeError("Independent settlement reconstruction failed.")
        state = redispatch.next_state
        submitted_bids.extend(
            {"experiment_id": experiment_id, **item} for item in plan.bids
        )
        realised_clearing.extend(
            {"experiment_id": experiment_id, **item} for item in clearing.hourly
        )
        executed_physical.extend(
            {"experiment_id": experiment_id, **item}
            for item in redispatch.physical_intervals
        )
        solver_records.extend(
            [
                {
                    "experiment_id": experiment_id,
                    "delivery_day": delivery_day.isoformat(),
                    "solve_stage": "planning",
                    "path_feasibility_constraint_generation": path_generation,
                    **plan.solver,
                },
                {
                    "experiment_id": experiment_id,
                    "delivery_day": delivery_day.isoformat(),
                    "solve_stage": "redispatch",
                    **redispatch.solver,
                },
            ]
        )
        if state.executed_hours != int(before["executed_hours"]) + 24:
            raise RepresentativeRegimeError("Daily rolling-state handoff did not advance 24 hours.")
        daily.append(
            {
                "experiment_id": experiment_id,
                "delivery_day": delivery_day.isoformat(),
                "week_id": row["week_id"],
                "regime_role": row["regime_role"],
                "arm": arm,
                "configuration": row["configuration"],
                "policy": policy,
                "scenario_count": int(row["scenario_count"]),
                "horizon_hours": horizon_hours,
                "maintenance_policy": "maintenance_free_normal_operation_week",
                "counterfactual_qh": granularity == "quarterhour",
                "expected_objective_eur": float(plan.expected_cost_eur),
                "expected_objective_lower_bound_eur": float(
                    plan.solver["economic_objective_lower_bound_eur"]
                ),
                "expected_objective_upper_bound_eur": float(
                    plan.solver["economic_objective_upper_bound_eur"]
                ),
                "expected_objective_absolute_band_eur": float(
                    plan.solver["economic_absolute_objective_band_eur"]
                ),
                "expected_objective_certified_relative_gap": float(
                    plan.solver["economic_certified_relative_gap"]
                ),
                "planning_economic_optimality_class": plan.solver[
                    "economic_optimality_class"
                ],
                "realised_settlement_eur": float(clearing.settlement_cost_eur),
                "realised_other_represented_cost_eur": float(
                    redispatch.other_represented_cost_eur
                ),
                "imbalance_penalty_eur": float(
                    redispatch.imbalance_penalty_eur
                ),
                "absolute_imbalance_mwh": float(
                    redispatch.absolute_imbalance_mwh
                ),
                "upward_consumption_imbalance_mwh": float(
                    redispatch.upward_consumption_imbalance_mwh
                ),
                "downward_consumption_imbalance_mwh": float(
                    redispatch.downward_consumption_imbalance_mwh
                ),
                "imbalance_affected_market_interval_count": int(
                    redispatch.imbalance_affected_market_interval_count
                ),
                "maximum_market_interval_imbalance_mwh": float(
                    redispatch.maximum_market_interval_imbalance_mwh
                ),
                "imbalance_gate_status": redispatch.solver[
                    "imbalance_gate_status"
                ],
                "conditional_minimum_imbalance_solve_performed": bool(
                    redispatch.solver[
                        "conditional_minimum_imbalance_solve_performed"
                    ]
                ),
                "hard_zero_economic_resolve_performed": bool(
                    redispatch.solver["hard_zero_economic_resolve_performed"]
                ),
                "minimum_imbalance_mwh": float(
                    redispatch.solver["conditional_imbalance_gate"][
                        "minimum_imbalance_mwh"
                    ]
                ),
                "realised_total_cost_eur": float(
                    clearing.settlement_cost_eur
                    + redispatch.other_represented_cost_eur
                    + redispatch.imbalance_penalty_eur
                ),
                "produced_t": float(redispatch.produced_t),
                "planning_solver_status": plan.solver["solver_status"],
                "planning_termination_condition": plan.solver["termination_condition"],
                "planning_mip_gap": plan.solver["mip_gap"],
                "planning_solver_seconds": plan.solver["total_solver_seconds"],
                "planning_variables": plan.solver["variable_count"],
                "planning_binaries": plan.solver["binary_count"],
                "planning_constraints": plan.solver["constraint_count"],
                "planning_solver_version": plan.solver["solver_version"],
                "planning_physical_tiebreak_mode": plan.solver[
                    "planning_physical_tiebreak_mode"
                ],
                "planning_physical_tiebreak_solve_performed": plan.solver[
                    "physical_tiebreak_solve_performed"
                ],
                "planning_production_progress_optimum_t": plan.solver[
                    "production_progress_optimum_t"
                ],
                "planning_expected_cost_optimum_eur": plan.solver[
                    "expected_cost_optimum_eur"
                ],
                "planning_selected_incumbent_expected_cost_eur": plan.solver[
                    "selected_incumbent_expected_cost_eur"
                ],
                "path_feasibility_augmentation_status": path_generation[
                    "status"
                ],
                "path_feasibility_candidate_pattern_count": path_generation[
                    "candidate_pattern_count"
                ],
                "path_feasibility_added_pattern_count": path_generation[
                    "selected_pattern_count"
                ],
                "path_feasibility_added_path_ids": json.dumps(
                    path_generation["selected_path_ids"]
                ),
                "path_feasibility_round_count": max(
                    0, len(path_generation["rounds"]) - 1
                ),
                "feasibility_path_probability_assigned": path_generation[
                    "probability_assigned_to_feasibility_paths"
                ],
                "feasibility_path_expected_cost_weight_assigned": (
                    path_generation[
                        "expected_cost_weight_assigned_to_feasibility_paths"
                    ]
                ),
                "redispatch_solver_status": redispatch.solver["solver_status"],
                "redispatch_termination_condition": redispatch.solver[
                    "termination_condition"
                ],
                "redispatch_mip_gap": redispatch.solver["mip_gap"],
                "redispatch_economic_optimality_class": redispatch.solver[
                    "economic_optimality_class"
                ],
                "redispatch_economic_objective_lower_bound_eur": (
                    redispatch.solver["economic_objective_lower_bound_eur"]
                ),
                "redispatch_economic_objective_upper_bound_eur": (
                    redispatch.solver["economic_objective_upper_bound_eur"]
                ),
                "redispatch_economic_absolute_objective_band_eur": (
                    redispatch.solver["economic_absolute_objective_band_eur"]
                ),
                "redispatch_economic_certified_relative_gap": (
                    redispatch.solver["economic_certified_relative_gap"]
                ),
                "redispatch_solver_seconds": redispatch.solver["total_solver_seconds"],
                "redispatch_solver_version": redispatch.solver["solver_version"],
                "redispatch_physical_tiebreak_solve_performed": redispatch.solver[
                    "physical_tiebreak_solve_performed"
                ],
                "solver_seed": plan.solver["solver_seed"],
                "solver_time_limit_seconds": plan.solver[
                    "solver_time_limit_seconds"
                ],
                "solver_mip_gap_limit": plan.solver["solver_mip_gap_limit"],
                "solver_economic_mip_gap_limit": plan.solver[
                    "solver_economic_mip_gap_limit"
                ],
                "solver_integer_feasibility_tolerance": plan.solver[
                    "solver_integer_feasibility_tolerance"
                ],
                "state_handoff_pass": True,
                "settlement_reconstruction_pass": True,
                "redispatch_economic_objective_reconstruction_pass": True,
                "redispatch_economic_objective_reconstruction_error_eur": (
                    redispatch.solver[
                        "economic_objective_reconstruction_error_eur"
                    ]
                ),
                "expected_objective_reconstruction_pass": True,
                "expected_objective_reconstruction_error_eur": plan.solver[
                    "expected_cost_reconstruction_error_eur"
                ],
                "economic_horizon_hours": plan.solver["economic_horizon_hours"],
                "physical_horizon_hours": plan.solver["planning_hours"],
                "physical_feasibility_tail_active": plan.solver[
                    "physical_feasibility_tail_active"
                ],
                "tail_market_binding": plan.solver["tail_market_binding"],
                "tail_price_information": plan.solver["tail_price_information"],
                "tail_executed_or_settled": plan.solver["tail_executed_or_settled"],
            }
        )
        _write_json(
            checkpoint_path,
            {
                "input_fingerprint": input_fingerprint,
                "state": state.snapshot(),
                "daily_results": daily,
                "submitted_bids": submitted_bids,
                "realised_clearing": realised_clearing,
                "executed_physical": executed_physical,
                "solver_records": solver_records,
                "complete": len(daily) == len(days),
            },
        )
    solver_versions = sorted(
        {
            str(item[version_field])
            for item in daily
            for version_field in ("planning_solver_version", "redispatch_solver_version")
        }
    )
    result = {
        "experiment_id": experiment_id,
        "status": "pass",
        "day_count": len(daily),
        "realised_total_cost_eur": sum(float(item["realised_total_cost_eur"]) for item in daily),
        "imbalance_penalty_eur": sum(float(item["imbalance_penalty_eur"]) for item in daily),
        "absolute_imbalance_mwh": sum(float(item["absolute_imbalance_mwh"]) for item in daily),
        "upward_consumption_imbalance_mwh": sum(
            float(item["upward_consumption_imbalance_mwh"]) for item in daily
        ),
        "downward_consumption_imbalance_mwh": sum(
            float(item["downward_consumption_imbalance_mwh"]) for item in daily
        ),
        "imbalance_affected_market_interval_count": sum(
            int(item["imbalance_affected_market_interval_count"]) for item in daily
        ),
        "maximum_market_interval_imbalance_mwh": max(
            float(item["maximum_market_interval_imbalance_mwh"]) for item in daily
        ),
        "expected_objective_eur": sum(float(item["expected_objective_eur"]) for item in daily),
        "expected_objective_lower_bound_eur": sum(
            float(item["expected_objective_lower_bound_eur"]) for item in daily
        ),
        "expected_objective_upper_bound_eur": sum(
            float(item["expected_objective_upper_bound_eur"]) for item in daily
        ),
        "expected_objective_absolute_band_eur": sum(
            float(item["expected_objective_absolute_band_eur"]) for item in daily
        ),
        "expected_objective_max_certified_relative_gap": max(
            float(item["expected_objective_certified_relative_gap"])
            for item in daily
        ),
        "produced_t": sum(float(item["produced_t"]) for item in daily),
        "runtime_seconds_this_invocation": time.perf_counter() - started,
        "maintenance_policy": "maintenance_free_normal_operation_week",
        "annualised": False,
        "historical_qh_claim": False,
        **run_contract,
        "solver_versions": solver_versions,
        "planning_production_progress_optimum_t_by_day": [
            float(item["planning_production_progress_optimum_t"]) for item in daily
        ],
        "planning_expected_cost_optimum_eur_by_day": [
            float(item["planning_expected_cost_optimum_eur"]) for item in daily
        ],
        "planning_selected_incumbent_expected_cost_eur_by_day": [
            float(item["planning_selected_incumbent_expected_cost_eur"])
            for item in daily
        ],
        "path_feasibility_added_pattern_count_by_day": [
            int(item["path_feasibility_added_pattern_count"])
            for item in daily
        ],
        "path_feasibility_added_path_ids_by_day": [
            json.loads(item["path_feasibility_added_path_ids"])
            for item in daily
        ],
        "conditional_minimum_imbalance_solve_trigger_count": sum(
            bool(item["conditional_minimum_imbalance_solve_performed"])
            for item in daily
        ),
        "final_state": state.snapshot(),
    }
    _write_csv(output_dir / "daily_results.csv", daily)
    _write_csv(output_dir / "submitted_bids.csv", submitted_bids)
    _write_csv(output_dir / "realised_clearing.csv", realised_clearing)
    _write_csv(output_dir / "executed_physical_intervals.csv", executed_physical)
    _write_json(output_dir / "solver_diagnostics.json", solver_records)
    _write_json(output_dir / "run_summary.json", result)
    return result


def realised_cost_comparisons(results: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    if results.empty:
        return pd.DataFrame()
    merged = results.merge(
        manifest[["experiment_id", "week_id", "configuration", "arm", "benchmark"]],
        on="experiment_id",
        how="left",
        validate="one_to_one",
    )
    central = merged[merged["benchmark"].eq("stochastic_policy")]
    rows: list[dict[str, Any]] = []
    for (week_id, configuration), group in central.groupby(["week_id", "configuration"]):
        costs = group.set_index("arm")["realised_total_cost_eur"].to_dict()
        expected_lb = group.set_index("arm")[
            "expected_objective_lower_bound_eur"
        ].to_dict()
        expected_ub = group.set_index("arm")[
            "expected_objective_upper_bound_eur"
        ].to_dict()
        if not {"A_hourly", "B_qh_flat", "C_qh_shape"}.issubset(costs):
            continue
        rows.append(
            {
                "week_id": week_id,
                "configuration": configuration,
                "cost_A_hourly_eur": costs["A_hourly"],
                "cost_B_qh_flat_eur": costs["B_qh_flat"],
                "cost_C_qh_shape_eur": costs["C_qh_shape"],
                "delta_qh_market_eur": costs["A_hourly"] - costs["B_qh_flat"],
                "delta_shape_eur": costs["B_qh_flat"] - costs["C_qh_shape"],
                "delta_total_eur": costs["A_hourly"] - costs["C_qh_shape"],
                "expected_delta_qh_market_interval_lower_eur": (
                    expected_lb["A_hourly"] - expected_ub["B_qh_flat"]
                ),
                "expected_delta_qh_market_interval_upper_eur": (
                    expected_ub["A_hourly"] - expected_lb["B_qh_flat"]
                ),
                "expected_delta_shape_interval_lower_eur": (
                    expected_lb["B_qh_flat"] - expected_ub["C_qh_shape"]
                ),
                "expected_delta_shape_interval_upper_eur": (
                    expected_ub["B_qh_flat"] - expected_lb["C_qh_shape"]
                ),
                "expected_delta_total_interval_lower_eur": (
                    expected_lb["A_hourly"] - expected_ub["C_qh_shape"]
                ),
                "expected_delta_total_interval_upper_eur": (
                    expected_ub["A_hourly"] - expected_lb["C_qh_shape"]
                ),
                "positive_means_saving": True,
                "maintenance_policy": "maintenance_free_normal_operation_week",
            }
        )
    return pd.DataFrame(rows)


def _completed_run_contract_metadata(
    config: Mapping[str, Any], results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    contract = _representative_run_contract(config)
    return {
        **contract,
        "solver_versions": sorted(
            {
                str(version)
                for result in results
                for version in result.get("solver_versions", [])
            }
        ),
        "planning_optima_by_experiment": [
            {
                "experiment_id": str(result["experiment_id"]),
                "production_progress_optimum_t_by_day": result.get(
                    "planning_production_progress_optimum_t_by_day", []
                ),
                "expected_cost_optimum_eur_by_day": result.get(
                    "planning_expected_cost_optimum_eur_by_day", []
                ),
                "selected_incumbent_expected_cost_eur_by_day": result.get(
                    "planning_selected_incumbent_expected_cost_eur_by_day", []
                ),
            }
            for result in results
        ],
    }


def _gate_experiment_rows(frames: StudyFrames) -> pd.DataFrame:
    week = frames.selected_weeks.loc[
        frames.selected_weeks["regime_role"].eq("typical_winter")
    ].iloc[0]
    manifest = frames.experiment_manifest
    selectors = (
        ("central_benchmark", "A_hourly", "C0", "price_insensitive"),
        ("central_benchmark", "BC_qh_shared", "C0", "price_insensitive"),
        ("central_benchmark", "A_hourly", "C1", "price_insensitive"),
        ("central_benchmark", "BC_qh_shared", "C1", "price_insensitive"),
        ("central", "A_hourly", "C1", "stochastic_policy"),
        ("central", "C_qh_shape", "C1", "stochastic_policy"),
    )
    rows: list[pd.Series] = []
    for experiment_class, arm, configuration, benchmark in selectors:
        match = manifest[
            manifest["week_id"].eq(week["week_id"])
            & manifest["experiment_class"].eq(experiment_class)
            & manifest["arm"].eq(arm)
            & manifest["configuration"].eq(configuration)
            & manifest["benchmark"].eq(benchmark)
            & manifest["horizon_hours"].eq(24)
            & manifest["scenario_count"].eq(10)
        ]
        if len(match) != 1:
            raise RepresentativeRegimeError(
                f"Split-horizon gate selector is not unique: {selectors}."
            )
        rows.append(match.iloc[0])
    return pd.DataFrame(rows).reset_index(drop=True)


def _load_gate_trajectory(run_root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    output_dir = run_root / "experiments" / _experiment_directory_name(
        str(row["experiment_id"])
    )
    checkpoint = json.loads((output_dir / "checkpoint.json").read_text(encoding="utf-8"))
    daily = checkpoint["daily_results"]
    if len(daily) != 1:
        raise RepresentativeRegimeError("A split-horizon gate trajectory must execute one day.")
    physical = checkpoint["executed_physical"]
    if len(physical) != 96:
        raise RepresentativeRegimeError("The physical tail leaked into executed output.")
    return {
        "experiment_id": row["experiment_id"],
        "market_granularity": "hourly" if row["arm"] == "A_hourly" else "quarterhour",
        "configuration_id": CONFIGURATIONS[str(row["configuration"])],
        "policy": daily[0]["policy"],
        "physical_dispatch": physical,
        "solver": checkpoint["solver_records"],
        "state": {"settlement_cost_eur": daily[0]["realised_settlement_eur"]},
        "daily": daily[0],
    }


def _flat_physical_parity_check(
    trajectories: Sequence[Mapping[str, Any]], configuration: str
) -> dict[str, Any]:
    selected = {
        item["market_granularity"]: item
        for item in trajectories
        if item["configuration_id"] == CONFIGURATIONS[configuration]
        and item["policy"] == "price-insensitive"
    }
    if set(selected) != {"hourly", "quarterhour"}:
        return {
            "check_id": f"{configuration.lower()}_flat_hourly_qh_physical_parity",
            "status": "fail",
            "observed": sorted(selected),
            "expected": ["hourly", "quarterhour"],
        }
    aggregate_fields = (
        "redispatched_net_grid_import_mwh",
        "final_product_output_t",
        "gross_electricity_mwh",
        "total_internal_generation_mwh",
        "total_named_ng_procurement_mwh",
        "eaf_liquid_steel_output_t",
    )
    hourly = selected["hourly"]["physical_dispatch"]
    quarterhour = selected["quarterhour"]["physical_dispatch"]
    aggregate_comparisons = []
    for field in aggregate_fields:
        hourly_total = sum(float(item[field]) for item in hourly)
        qh_total = sum(float(item[field]) for item in quarterhour)
        absolute = abs(hourly_total - qh_total)
        relative = absolute / max(abs(hourly_total), 1.0)
        aggregate_comparisons.append(
            {
                "field": field,
                "hourly_total": hourly_total,
                "quarterhour_total": qh_total,
                "absolute_difference": absolute,
                "relative_difference": relative,
            }
        )
    maximum_relative = max(
        item["relative_difference"] for item in aggregate_comparisons
    )
    production_error = next(
        item["absolute_difference"]
        for item in aggregate_comparisons
        if item["field"] == "final_product_output_t"
    )
    hourly_objective = float(selected["hourly"]["daily"]["expected_objective_eur"])
    qh_objective = float(selected["quarterhour"]["daily"]["expected_objective_eur"])
    objective_error = abs(hourly_objective - qh_objective)
    objective_tolerance = max(abs(hourly_objective), abs(qh_objective), 1.0) * MIP_GAP_LIMIT
    timestamps_equal = [item["target_timestamp_utc"] for item in hourly] == [
        item["target_timestamp_utc"] for item in quarterhour
    ]
    passed = (
        production_error <= 1e-4
        and objective_error <= objective_tolerance + 0.01
        and timestamps_equal
    )
    return {
        "check_id": f"{configuration.lower()}_flat_hourly_qh_physical_parity",
        "status": "pass" if passed else "fail",
        "observed": objective_error,
        "expected": objective_tolerance,
        "timestamps_equal": timestamps_equal,
        "production_error_t": production_error,
        "expected_objective_error_eur": objective_error,
        "expected_objective_tolerance_eur": objective_tolerance,
        "maximum_aggregate_ledger_relative_difference": maximum_relative,
        "aggregate_ledger_differences_are_diagnostic_not_identity_gate": True,
        "aggregate_comparisons_json": json.dumps(
            aggregate_comparisons, sort_keys=True
        ),
    }


def run_split_horizon_gate(
    config_path: str | Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Run the bounded one-day C0/C1 prerequisite before economic release."""

    config = load_representative_config(config_path)
    frames = load_study_frames(config)
    selected = _gate_experiment_rows(frames)
    output_spec = config["outputs"]["gate"]
    run_root = _resolve(output_spec["root"]) / run_id
    if run_root.exists():
        raise RepresentativeRegimeError("Split-horizon gate run ID already exists.")
    run_contract = _representative_run_contract(config)
    declaration = {
        "output_root": str(run_root.relative_to(REPO_ROOT)),
        "experiment_count": int(len(selected)),
        "estimated_solver_builds": int(len(selected) * 2),
        "estimated_size": "normally <10 MB excluding failure solver logs",
        "output_policy": "minimal",
        "run_class": output_spec["run_class"],
        "lineage_role": output_spec["lineage_role"],
        "retention_status": "ignored governed diagnostic run",
        "git_eligible": False,
        **run_contract,
    }
    run_root.mkdir(parents=True)
    _write_json(run_root / "output_declaration.json", declaration)
    (run_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    input_manifest = {
        "study_run_id": frames.study_root.name,
        "study_run_summary_sha256": _sha256(frames.study_root / "run_summary.json"),
        "counterfactual_overlay_sha256": _sha256(
            frames.study_root / "counterfactual_qh_overlay.parquet"
        ),
        "selected_week_id": str(selected.iloc[0]["week_id"]),
        "forecast_information_horizon_hours": 24,
        "physical_horizon_hours": 48,
        "physical_tail_price_information": "none",
        **run_contract,
    }
    _write_json(run_root / "input_manifest.json", input_manifest)
    _write_json(
        run_root / "code_version.json",
        {
            "git_head": _git_head(),
            "source_sha256": {
                "representative_executor": _sha256(Path(__file__).resolve()),
                "phase6d_engine": _sha256(
                    Path(__file__).with_name("s4_4c6_phase6d_eaf_heat_state_one_day.py")
                ),
                "phase6b_interface": _sha256(
                    Path(__file__).with_name(
                        "s4_4c6_phase6b_hourly_da_bid_clear_redispatch.py"
                    )
                ),
                "config": _sha256(_resolve(config_path)),
            },
        },
    )
    _write_csv(run_root / "selected_experiments.csv", selected.to_dict(orient="records"))
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        try:
            results.append(
                run_experiment(
                    config,
                    frames,
                    row.to_dict(),
                    run_root,
                    resume=False,
                    day_limit=1,
                )
            )
        except Phase6DPerformanceIncomplete as exc:
            failures.append(
                {
                    "experiment_id": row["experiment_id"],
                    "classification": "performance_incomplete",
                    "error": str(exc),
                }
            )
        except (Phase6DError, RepresentativeRegimeError) as exc:
            failures.append(
                {
                    "experiment_id": row["experiment_id"],
                    "classification": "execution_failure",
                    "error": str(exc),
                }
            )
        _write_csv(run_root / "experiment_results_in_progress.csv", results)
        _write_csv(run_root / "failures_in_progress.csv", failures)
        _write_json(
            run_root / "progress_current.json",
            {
                "run_id": run_id,
                "selected_experiment_count": int(len(selected)),
                "completed_experiment_count_this_invocation": len(results),
                "failure_count_this_invocation": len(failures),
                "last_experiment_id": str(row["experiment_id"]),
                "status": "running",
            },
        )

    checks: list[dict[str, Any]] = []
    trajectories: list[dict[str, Any]] = []
    completed_ids = {str(item["experiment_id"]) for item in results}
    for _, row in selected[selected["experiment_id"].isin(completed_ids)].iterrows():
        trajectory = _load_gate_trajectory(run_root, row.to_dict())
        trajectories.append(trajectory)
        checks.extend(validate_phase6d_trajectory(trajectory))
        daily = trajectory["daily"]
        split_pass = (
            int(daily["economic_horizon_hours"]) == 24
            and int(daily["physical_horizon_hours"]) == 48
            and bool(daily["physical_feasibility_tail_active"])
            and not bool(daily["tail_market_binding"])
            and str(daily["tail_price_information"]) == "none"
            and not bool(daily["tail_executed_or_settled"])
        )
        checks.append(
            {
                "market_granularity": trajectory["market_granularity"],
                "configuration_id": trajectory["configuration_id"],
                "policy": trajectory["policy"],
                "check_id": "split_horizon_no_future_price_or_settlement",
                "observed": split_pass,
                "expected": True,
                "status": "pass" if split_pass else "fail",
            }
        )
    checks.append(_flat_physical_parity_check(trajectories, "C0"))
    checks.append(_flat_physical_parity_check(trajectories, "C1"))
    _write_csv(run_root / "experiment_results.csv", results)
    _write_csv(run_root / "failures.csv", failures)
    _write_csv(run_root / "validation_checks.csv", checks)
    failed_checks = [item for item in checks if item.get("status") != "pass"]
    passed = not failures and len(results) == len(selected) and not failed_checks
    summary = {
        "run_id": run_id,
        "status": "pass" if passed else "blocked",
        "decision": (
            "c1_split_horizon_prerequisite_pass"
            if passed
            else "c1_split_horizon_prerequisite_blocked"
        ),
        "experiment_count": int(len(selected)),
        "completed_count": len(results),
        "failure_count": len(failures),
        "validation_check_count": len(checks),
        "validation_failure_count": len(failed_checks),
        "economic_horizon_hours": 24,
        "physical_horizon_hours": 48,
        "tail_price_information": "none",
        "tail_market_binding": False,
        "tail_executed_or_settled": False,
        "maintenance_policy": "maintenance_free_normal_operation_week",
        "economic_result": False,
        "output_policy": "minimal",
        "run_class": output_spec["run_class"],
        "lineage_role": output_spec["lineage_role"],
        **_completed_run_contract_metadata(config, results),
    }
    _write_json(run_root / "run_summary.json", summary)
    _write_json(
        run_root / "registry_entry.json",
        {
            "run_id": run_id,
            "status": summary["status"],
            "decision": summary["decision"],
            "run_class": output_spec["run_class"],
            "lineage_role": output_spec["lineage_role"],
            "parent_study_run_id": frames.study_root.name,
            **_completed_run_contract_metadata(config, results),
        },
    )
    (run_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a one-day physical and timing prerequisite, not an economic result.\n"
        "- The second 24 hours contain no market price, bid, clearing, execution or settlement.\n"
        "- Passing does not create causal D+1--D+4 forecast support.\n"
        "- Planning uses V1: a different incumbent within the preserved production and expected-cost optima; redispatch retains its physical tie-break.\n"
        "- Every C1 claim assumes maintenance-free normal operation.\n",
        encoding="utf-8",
    )
    return {"declaration": declaration, "summary": summary}


def run_selected_experiments(
    config_path: str | Path,
    experiment_ids: Sequence[str],
    *,
    all_ready: bool,
    ready_scope: str | None = None,
    run_id: str,
    resume: bool,
) -> dict[str, Any]:
    config = load_representative_config(config_path)
    frames = load_study_frames(config)
    selected = select_experiments(
        frames.experiment_manifest,
        experiment_ids,
        all_ready=all_ready,
        ready_scope=ready_scope,
    )
    _validate_execution_authorization(config, selected, all_ready=all_ready)
    execution_authorization = config["execution_authorization"]
    full_matrix_authorized = bool(
        execution_authorization["full_four_week_matrix_authorized"]
    )
    central = selected["experiment_class"].isin(CENTRAL_CLASSES).all()
    output_spec = config["outputs"]["central" if central else "sensitivity"]
    run_root = _resolve(output_spec["root"]) / run_id
    run_contract = _representative_run_contract(config)
    feasibility_patterns, feasibility_pattern_manifest = (
        _load_frozen_path_feasibility_patterns(config)
    )
    declaration = {
        "output_root": str(run_root.relative_to(REPO_ROOT)),
        "experiment_count": int(len(selected)),
        "estimated_solver_tier_solves_minimum": int(len(selected) * 7 * 5),
        "estimated_solver_tier_solves_maximum": int(
            len(selected) * 7 * (7 + 4 * len(feasibility_patterns))
        ),
        "estimated_size": (
            "minimal bids, clearing, executed-QH paths, tier progress and checkpoints; "
            + (
                "normally <100 MB for the frozen 56-experiment matrix"
                if full_matrix_authorized
                else "normally <50 MB for the authorized three-arm trial"
            )
        ),
        "output_policy": "minimal",
        "run_class": output_spec["run_class"],
        "lineage_role": output_spec["lineage_role"],
        "retention_status": "ignored governed optimisation run",
        "git_eligible": False,
        "full_four_week_matrix_authorized": full_matrix_authorized,
        "authorization_receipt": execution_authorization[
            "authorization_receipt"
        ],
        "authorization_timestamp_utc": execution_authorization[
            "authorization_timestamp_utc"
        ],
        **run_contract,
    }
    if run_root.exists() and not resume:
        raise RepresentativeRegimeError("Run ID already exists; use --resume or a new run ID.")
    if run_root.exists() and resume:
        _assert_run_execution_authorized(run_root, resume=True)
    run_root.mkdir(parents=True, exist_ok=True)
    if not (run_root / "run_control.json").exists():
        _write_run_control(
            run_root,
            status="running",
            resume_authorized=True,
            reason=(
                "authorized_frozen_four_week_central_matrix"
                if full_matrix_authorized
                else "authorized_single_week_conditional_imbalance_gate"
            ),
        )
    _write_json(run_root / "output_declaration.json", declaration)
    (run_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        run_root / "input_manifest.json",
        {
            "study_run_id": frames.study_root.name,
            "study_run_summary_sha256": _sha256(frames.study_root / "run_summary.json"),
            "counterfactual_overlay_sha256": _sha256(
                frames.study_root / "counterfactual_qh_overlay.parquet"
            ),
            "forecast_family_run_id": frames.family_root.name,
            "path_feasibility_pattern_manifest": (
                feasibility_pattern_manifest.relative_to(REPO_ROOT).as_posix()
            ),
            "path_feasibility_pattern_manifest_sha256": _sha256(
                feasibility_pattern_manifest
            ),
            "path_feasibility_candidate_pattern_count": len(
                feasibility_patterns
            ),
            "path_feasibility_probability_assigned": False,
            "path_feasibility_expected_cost_weight_assigned": False,
            "full_four_week_matrix_authorized": full_matrix_authorized,
            "authorization_receipt": execution_authorization[
                "authorization_receipt"
            ],
            "authorization_timestamp_utc": execution_authorization[
                "authorization_timestamp_utc"
            ],
            "economic_horizon_hours": 24,
            "physical_horizon_hours": 48,
            "tail_price_information": "none",
            **run_contract,
        },
    )
    _write_json(
        run_root / "code_version.json",
        {
            "git_head": _git_head(),
            "source_sha256": {
                "representative_executor": _sha256(Path(__file__).resolve()),
                "phase6d_engine": _sha256(
                    Path(__file__).with_name("s4_4c6_phase6d_eaf_heat_state_one_day.py")
                ),
                "phase6b_interface": _sha256(
                    Path(__file__).with_name(
                        "s4_4c6_phase6b_hourly_da_bid_clear_redispatch.py"
                    )
                ),
                "behavioural_path_planner": _sha256(
                    Path(__file__).with_name("s4_4c6_behavioural_validation.py")
                ),
                "config": _sha256(_resolve(config_path)),
            },
        },
    )
    _write_json(
        run_root / "frozen_path_feasibility_pattern_manifest.json",
        {
            "source_manifest": feasibility_pattern_manifest.relative_to(
                REPO_ROOT
            ).as_posix(),
            "source_manifest_sha256": _sha256(feasibility_pattern_manifest),
            "pattern_count": len(feasibility_patterns),
            "probability_assigned": False,
            "expected_cost_weight_assigned": False,
            "final_test_source_count": 0,
            "patterns": feasibility_patterns,
        },
    )
    (run_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These are four maintenance-free representative regime cases, not an annual backtest.\n"
        "- All 2024/25 quarter-hour paths are synthetic counterfactual overlays.\n"
        "- The physical plan is 48 hours, but only the causal first 24 hours have prices and are executed and settled.\n"
        "- Planning uses V1: a different incumbent within the preserved production and expected-cost optima; internal inventory, flaring and commitments may therefore differ from V0.\n"
        "- C1 central S10 plans use at most three one-pattern constraint-generation rounds from the pinned non-final validation mask pool; these paths have no probability, settlement or expected-cost weight.\n"
        "- Redispatch retains the physical tie-break; A/B/C claims remain realised-cost differences and selection sensitivity is a limitation.\n"
        "- mFRR, CVaR, ETS, export, product revenue and emergency import are inactive.\n"
        "- Symmetric deviation variables use the single fixed EUR 5,000/MWh penalty; DA settlement remains separate on the cleared E-program.\n"
        "- Positive minimum imbalance is emergency recourse only, is never an A/B/C result and stops the complete invocation.\n"
        "- A trajectory is E-program compliant only when final reported absolute imbalance is numerically zero.\n",
        encoding="utf-8",
    )
    _write_csv(run_root / "selected_experiments.csv", selected.to_dict(orient="records"))
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stop_classification: str | None = None
    for _, row in selected.iterrows():
        _assert_run_execution_authorized(run_root, resume=False)
        try:
            results.append(
                run_experiment(
                    config, frames, row.to_dict(), run_root, resume=resume
                )
            )
        except Phase6DEmergencyRecourse as exc:
            stop_classification = "emergency_recourse"
            failures.append(
                {
                    "experiment_id": row["experiment_id"],
                    "classification": stop_classification,
                    "error": str(exc),
                    "diagnostic": exc.diagnostic,
                    "abc_comparison_eligible": False,
                }
            )
            _write_run_control(
                run_root,
                status=stop_classification,
                resume_authorized=False,
                reason="positive_minimum_imbalance",
                diagnostic=exc.diagnostic,
            )
            break
        except Phase6DPerformanceIncomplete as exc:
            stop_classification = "performance_incomplete"
            failures.append(
                {
                    "experiment_id": row["experiment_id"],
                    "classification": stop_classification,
                    "error": str(exc),
                    "diagnostic": exc.diagnostic,
                }
            )
            _write_run_control(
                run_root,
                status=stop_classification,
                resume_authorized=False,
                reason="solver_optimality_not_proven",
                diagnostic=exc.diagnostic,
            )
            break
        except (Phase6DError, RepresentativeRegimeError) as exc:
            stop_classification = "execution_failure"
            failures.append(
                {
                    "experiment_id": row["experiment_id"],
                    "classification": stop_classification,
                    "error": str(exc),
                    "diagnostic": getattr(exc, "diagnostic", {}),
                }
            )
            _write_run_control(
                run_root,
                status=stop_classification,
                resume_authorized=False,
                reason="fail_closed_execution_or_reconstruction_gate",
                diagnostic=getattr(exc, "diagnostic", {}),
            )
            break
    result_frame = pd.DataFrame(results)
    _write_csv(run_root / "experiment_results.csv", results)
    _write_csv(run_root / "failures.csv", failures)
    comparisons = realised_cost_comparisons(result_frame, frames.experiment_manifest)
    _write_csv(run_root / "realised_cost_comparisons.csv", comparisons.to_dict(orient="records"))
    summary = {
        "run_id": run_id,
        "status": "pass" if not failures else stop_classification,
        "experiment_count": int(len(selected)),
        "completed_count": len(results),
        "failure_count": len(failures),
        "cost_comparison_count": int(len(comparisons)),
        "output_policy": "minimal",
        "run_class": output_spec["run_class"],
        "lineage_role": output_spec["lineage_role"],
        "maintenance_policy": "maintenance_free_normal_operation_week",
        "annualisation_allowed": False,
        "historical_qh_claim_allowed": False,
        "mFRR_active": False,
        "resume_authorized": False,
        "full_four_week_matrix_authorized": full_matrix_authorized,
        "authorization_receipt": execution_authorization[
            "authorization_receipt"
        ],
        "abc_comparison_eligible": not failures,
        **_completed_run_contract_metadata(config, results),
    }
    _write_json(run_root / "run_summary.json", summary)
    _write_json(
        run_root / "registry_entry.json",
        {
            "run_id": run_id,
            "status": summary["status"],
            "run_class": output_spec["run_class"],
            "lineage_role": output_spec["lineage_role"],
            "study_run_id": frames.study_root.name,
            "experiment_count": int(len(selected)),
            "completed_count": len(results),
            "failure_count": len(failures),
            "full_four_week_matrix_authorized": full_matrix_authorized,
            "authorization_receipt": execution_authorization[
                "authorization_receipt"
            ],
            **_completed_run_contract_metadata(config, results),
        },
    )
    if not failures:
        _write_run_control(
            run_root,
            status="completed",
            resume_authorized=False,
            reason=(
                "frozen_four_week_central_matrix_completed"
                if full_matrix_authorized
                else "authorized_trial_completed_and_requires_new_user_authorization"
            ),
        )
    return {"declaration": declaration, "summary": summary}


def run_checkpoint_seeded_high_price_day_gate(
    config_path: str | Path = REPRESENTATIVE_CONFIG,
    *,
    run_id: str,
    source_checkpoint_path: str | Path,
    experiment_id: str = (
        "high_prices__2025-01-13__central__B_qh_flat__C1__h24__s10__"
        "stochastic_policy"
    ),
    delivery_day: date = date(2025, 1, 15),
) -> dict[str, Any]:
    """Run only 15 January from the preserved two-day high-price checkpoint."""

    expected_experiment = (
        "high_prices__2025-01-13__central__B_qh_flat__C1__h24__s10__"
        "stochastic_policy"
    )
    if experiment_id != expected_experiment or delivery_day != date(2025, 1, 15):
        raise RepresentativeRegimeError(
            "The checkpoint-seeded gate is restricted to frozen C1 B on 15 January 2025."
        )
    config = load_representative_config(config_path)
    frames = load_study_frames(config)
    manifest = frames.experiment_manifest
    selected = manifest.loc[manifest["experiment_id"].eq(experiment_id)]
    if len(selected) != 1:
        raise RepresentativeRegimeError("Frozen high-price experiment is missing or duplicated.")
    row = selected.iloc[0].to_dict()
    _validate_execution_authorization(config, selected, all_ready=False)
    checkpoint_path = _resolve(source_checkpoint_path)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    source_run_root = checkpoint_path.parents[2]
    termination_path = source_run_root / "termination_addendum.json"
    if not termination_path.exists():
        raise RepresentativeRegimeError(
            "The source checkpoint lacks its required termination addendum."
        )
    termination = json.loads(termination_path.read_text(encoding="utf-8"))
    if (
        termination.get("resume_authorized") is not False
        or termination.get("thesis_result_usable") is not False
        or termination.get("superseded_by_conditional_minimum_imbalance_gate")
        is not True
    ):
        raise RepresentativeRegimeError("Source-run termination contract changed.")
    prior_days = list(checkpoint.get("daily_results", []))
    if (
        len(prior_days) != 2
        or prior_days[-1].get("delivery_day") != "2025-01-14"
        or checkpoint.get("complete") is not False
    ):
        raise RepresentativeRegimeError(
            "The diagnostic source must be the preserved two-day 13-14 January checkpoint."
        )
    output_spec = config["outputs"]["conditional_gate"]
    run_root = _resolve(output_spec["root"]) / run_id
    if run_root.exists():
        raise RepresentativeRegimeError("Targeted high-price gate run ID already exists.")
    run_root.mkdir(parents=True)
    _write_run_control(
        run_root,
        status="running",
        resume_authorized=True,
        reason="checkpoint_seeded_high_price_day_conditional_gate",
    )
    declaration = {
        "output_root": str(run_root.relative_to(REPO_ROOT)),
        "run_class": "diagnostic_validation",
        "lineage_role": output_spec["lineage_role"],
        "output_policy": "minimal",
        "experiment_count": 1,
        "delivery_day_count": 1,
        "estimated_solver_tier_solves_minimum": 5,
        "estimated_solver_tier_solves_maximum": 7,
        "estimated_size": "minimal one-day diagnostic, normally below 10 MB",
        "source_checkpoint": str(checkpoint_path.relative_to(REPO_ROOT)),
        "source_checkpoint_state_only": True,
        "source_run_resumed": False,
        "full_four_week_matrix_authorized": False,
        "git_eligible": False,
        **_representative_run_contract(config),
    }
    _write_json(run_root / "output_declaration.json", declaration)
    (run_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        run_root / "code_version.json",
        {
            "git_head": _git_head(),
            "representative_executor_sha256": _sha256(Path(__file__).resolve()),
            "phase6d_engine_sha256": _sha256(
                Path(__file__).with_name("s4_4c6_phase6d_eaf_heat_state_one_day.py")
            ),
            "config_sha256": _sha256(_resolve(config_path)),
        },
    )
    _write_json(
        run_root / "input_manifest.json",
        {
            "experiment_id": experiment_id,
            "delivery_day": delivery_day.isoformat(),
            "source_checkpoint_sha256": _sha256(checkpoint_path),
            "source_termination_addendum_sha256": _sha256(termination_path),
            "study_run_id": frames.study_root.name,
            "state_seed_only": True,
        },
    )
    state = _state_from_snapshot(checkpoint["state"])
    state.episode_id = f"{run_id}__{experiment_id}"
    before_executed_hours = state.executed_hours
    bundle, actuals = build_price_bundles(
        frames,
        week_id=str(row["week_id"]),
        delivery_day=delivery_day,
        arm=str(row["arm"]),
        scenario_count=10,
    )
    context = _base_context_config(
        config, market_granularity="quarterhour", horizon_hours=24
    )
    policy = _policy(row, "quarterhour")
    failure_status: str | None = None
    diagnostic: dict[str, Any] = {}
    try:
        plan = solve_grouped_da_bid_plan(
            context,
            C1_CONFIGURATION,
            bundle,
            state,
            policy,
            progress_callback=_solver_progress_callback(
                run_root,
                experiment_id=experiment_id,
                delivery_day=delivery_day,
                solve_stage="planning",
            ),
        )
        clearing = clear_hourly_da_bids(plan.bids, actuals)
        redispatch = solve_grouped_actual_redispatch(
            context,
            C1_CONFIGURATION,
            clearing,
            state,
            bundle.point_prices,
            imbalance_penalty_eur_per_mwh=5000.0,
            progress_callback=_solver_progress_callback(
                run_root,
                experiment_id=experiment_id,
                delivery_day=delivery_day,
                solve_stage="redispatch",
            ),
        )
        if redispatch.absolute_imbalance_mwh > IMBALANCE_ZERO_TOLERANCE_MWH:
            raise RepresentativeRegimeError(
                "Checkpoint-seeded gate returned positive accepted imbalance."
            )
        if redispatch.next_state.executed_hours != before_executed_hours + 24:
            raise RepresentativeRegimeError("One-day rolling state did not advance 24 hours.")
    except Exception as exc:
        if isinstance(exc, Phase6DEmergencyRecourse):
            failure_status = "emergency_recourse"
            reason = "positive_minimum_imbalance"
        elif isinstance(exc, Phase6DPerformanceIncomplete):
            failure_status = "performance_incomplete"
            reason = "solver_optimality_not_proven"
        else:
            failure_status = "execution_failure"
            reason = "physical_or_reconstruction_gate_failed"
        diagnostic = dict(getattr(exc, "diagnostic", {}))
        diagnostic.setdefault("error_type", type(exc).__name__)
        diagnostic.setdefault("error", str(exc))
        _write_run_control(
            run_root,
            status=failure_status,
            resume_authorized=False,
            reason=reason,
            diagnostic=diagnostic,
        )
    if failure_status is None:
        _write_csv(run_root / "submitted_bids.csv", plan.bids)
        _write_csv(run_root / "realised_clearing.csv", clearing.hourly)
        _write_csv(
            run_root / "executed_physical_intervals.csv",
            redispatch.physical_intervals,
        )
        _write_json(
            run_root / "solver_diagnostics.json",
            {"planning": plan.solver, "redispatch": redispatch.solver},
        )
        summary = {
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "experiment_id": experiment_id,
            "delivery_day": delivery_day.isoformat(),
            "absolute_imbalance_mwh": redispatch.absolute_imbalance_mwh,
            "imbalance_penalty_eur": redispatch.imbalance_penalty_eur,
            "imbalance_gate_status": redispatch.solver["imbalance_gate_status"],
            "conditional_minimum_imbalance_solve_performed": redispatch.solver[
                "conditional_minimum_imbalance_solve_performed"
            ],
            "planning_tier_solves": plan.solver["tier_solves"],
            "redispatch_tier_solves": redispatch.solver["tier_solves"],
            "state_handoff_pass": True,
            "resume_authorized": False,
            "abc_comparison_eligible": False,
        }
        _write_run_control(
            run_root,
            status="completed",
            resume_authorized=False,
            reason="one_day_gate_completed_and_requires_next_phase_authorization",
        )
    else:
        summary = {
            "run_id": run_id,
            "status": failure_status,
            "decision": "BLOCK",
            "experiment_id": experiment_id,
            "delivery_day": delivery_day.isoformat(),
            "diagnostic": diagnostic,
            "resume_authorized": False,
            "abc_comparison_eligible": False,
        }
    summary.update(
        {
            "run_class": "diagnostic_validation",
            "lineage_role": output_spec["lineage_role"],
            "output_policy": "minimal",
            "source_run_resumed": False,
            "full_four_week_matrix_run": False,
        }
    )
    _write_json(run_root / "run_summary.json", summary)
    _write_json(
        run_root / "registry_entry.json",
        {
            "run_id": run_id,
            "status": summary["status"],
            "decision": summary["decision"],
            "run_class": "diagnostic_validation",
            "lineage_role": output_spec["lineage_role"],
            "resume_authorized": False,
            "git_eligible": False,
        },
    )
    (run_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is one checkpoint-seeded C1 diagnostic day, not an A/B/C result.\n"
        "- The source run remains non-resumable and non-thesis-usable; only its "
        "two-day physical state seeds this new run.\n"
        "- Positive minimum imbalance is emergency recourse and blocks all further runs.\n"
        "- No annualisation, mFRR, CVaR, S30, horizon or penalty sensitivity is active.\n",
        encoding="utf-8",
    )
    return {"declaration": declaration, "summary": summary}


__all__ = [
    "REPRESENTATIVE_CONFIG",
    "RepresentativeRegimeError",
    "StudyFrames",
    "build_price_bundles",
    "load_representative_config",
    "load_study_frames",
    "preflight",
    "realised_cost_comparisons",
    "run_split_horizon_gate",
    "run_selected_experiments",
    "select_experiments",
]
