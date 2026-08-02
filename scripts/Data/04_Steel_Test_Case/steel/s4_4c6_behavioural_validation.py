"""Pre-matrix behavioural validation for the frozen C0/C1 V1 steel model.

The module is deliberately a thin orchestration layer.  It consumes the
accepted Strict/S10 and quarter-hour shape artifacts and calls the existing
Phase-6D plan--bid--clear--redispatch engine without changing its physics.
"""

from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import replace
from datetime import date, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    ENERGY_TOLERANCE_MWH,
    STEEL_BID_GRID,
    SteelActualPriceBundle,
    SteelBidPlan,
    SteelPriceInformationBundle,
    SteelRollingState,
    clear_hourly_da_bids,
    expected_origin_utc,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import (
    ECONOMIC_MIP_GAP_LIMIT,
    EXPECTED_COST_INCUMBENT,
    FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
    IMBALANCE_ZERO_TOLERANCE_MWH,
    MAX_PATH_FEASIBILITY_AUGMENTATION_ROUNDS,
    PHASE6D_GRID_IDS,
    PHYSICAL_INTERVALS_PER_DAY,
    PLANNING_SOLVER_SEQUENTIAL,
    REDISPATCH_PHYSICAL_TIEBREAK_TIER,
    Phase6DEmergencyRecourse,
    Phase6DPathFeasibilityIncomplete,
    Phase6DPerformanceIncomplete,
    Phase6DError,
    actual_bundle_from_feasibility_pattern,
    build_validation_feasibility_clearing_pattern,
    diagnose_feasibility_path_minimum_imbalance,
    run_limited_path_feasibility_constraint_generation,
    solve_grouped_actual_redispatch,
    solve_grouped_da_bid_plan,
    validate_phase6d_trajectory,
)
from .s4_4c6_representative_regime_counterfactual import (
    LOCAL_TZ,
    STRICT_MODEL_ID,
    StudyFrames,
    _assert_run_execution_authorized,
    _base_context_config,
    _representative_run_contract,
    _solver_progress_callback,
    _write_run_control,
    build_price_bundles,
    load_representative_config,
    load_study_frames,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


FORECAST_PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
if str(FORECAST_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(FORECAST_PACKAGE_ROOT))

from quarterhour_da.representative_regime_study import (  # noqa: E402
    apply_counterfactual_shape_overlay,
    build_shape_library,
    stable_seed,
)


BEHAVIOURAL_CONFIG = Path(
    "scripts/Data/04_Steel_Test_Case/configs/steel_c6_behavioural_validation.yaml"
)
CONFIGURATION_IDS = {
    "C0": C0_CONFIGURATION,
    "C1": C1_CONFIGURATION,
}
MONEY_NUMERICAL_SLACK_EUR = 1e-6
VN25_ELECTRICITY_EFFICIENCY = 0.345
NAMED_NG_PRICE_EUR_PER_MWH_LHV = 55.0
VN25_BREAK_EVEN_EUR_PER_MWH = (
    NAMED_NG_PRICE_EUR_PER_MWH_LHV / VN25_ELECTRICITY_EFFICIENCY
)
OUTPUT_FILES = (
    "output_declaration.json",
    "resolved_config.yaml",
    "input_manifest.json",
    "code_version.json",
    "shadow_day_selection.csv",
    "case_manifest.csv",
    "forecast_diagnostics.csv",
    "behavioural_metrics.csv",
    "physical_validation_checks.csv",
    "economic_rationality_checks.csv",
    "solver_diagnostics.json",
    "case_results.csv",
    "gate_summary.json",
    "registry_entry.json",
    "warnings_and_limitations.md",
)


class BehaviouralValidationError(RuntimeError):
    """Raised when the behavioural gate contract cannot be honoured."""


class BehaviouralRedispatchInfeasible(BehaviouralValidationError):
    """Carries compact plan/clearing evidence for an infeasible redispatch."""

    def __init__(self, message: str, diagnostic: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic)


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["status"])
        writer.writeheader()
        writer.writerows(materialized)


def _write_warnings_and_limitations(
    output: Path, summary: Mapping[str, Any] | None = None
) -> None:
    lines = [
        "# Warnings and limitations",
        "",
        "- Diagnostic development evidence only; no annualisation or final-regime claim.",
        "- Final regime weeks were excluded from selection, tuning and solver execution.",
        "- Quarter-hour prices are counterfactual mean-preserving overlays, not observed 2024/25 QH prices.",
        "- F18/F19 expectations are directional and are not numerical calibration targets.",
        "- The optional NG-price cross-check is not run because the frozen interface exposes no source-faithful runtime NG-price variant.",
        "- The normal one-day `24e48p` contract uses a shared non-terminal continuation policy at physical hour 48; reference-band distance is diagnostic only.",
    ]
    if summary and summary.get("decision") == "BLOCK":
        active_phase = "synthetic" if "synthetic" in summary else "shadow"
        phase_summary = summary.get(active_phase, {})
        diagnostics = phase_summary.get("blocking_case_diagnostics", [])
        for diagnostic in diagnostics:
            lines.extend(
                [
                    "- The gate is BLOCK at "
                    f"`{diagnostic.get('failure_stage', 'trajectory_execution')}` "
                    f"for `{diagnostic.get('case_id')}` "
                    f"({diagnostic.get('error_type')}).",
                    "- The blocked clearing has "
                    f"{diagnostic.get('cleared_intervals_outside_scenario_import_envelope', 'unknown')} "
                    "interval(s) outside the scenario-import envelope; the nearest "
                    "complete planned path RMSE is "
                    f"{diagnostic.get('nearest_complete_planned_scenario_import_path_rmse_mwh', 'unknown')} MWh.",
                ]
            )
        lines.extend(
            [
                (
                    "- Later shadow cases and all four final regime weeks were deliberately not solved after the hard failure."
                    if active_phase == "shadow"
                    else "- Later synthetic/shadow cases and all four final regime weeks were deliberately not solved after the hard failure."
                ),
                "- No emergency import, physical-bound relaxation or realised-price/scenario alteration was introduced to force feasibility.",
                "- Physical execution may deviate from the DA E-program only through symmetric recourse penalised at EUR 5,000/MWh; DA settlement and the artificial penalty are reported separately.",
            ]
        )
    (output / "warnings_and_limitations.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return pd.read_csv(path).to_dict(orient="records")


def load_behavioural_config(
    path: str | Path = BEHAVIOURAL_CONFIG,
) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BehaviouralValidationError("Behavioural config must be a mapping.")
    if (
        payload.get("output_policy") != "minimal"
        or payload.get("run_class") != "diagnostic_validation"
        or payload.get("git_eligible") is not False
    ):
        raise BehaviouralValidationError("Behavioural output classification changed.")
    contract = payload.get("frozen_contract", {})
    exact = {
        "planning_physical_tiebreak_mode": EXPECTED_COST_INCUMBENT,
        "planning_physical_tiebreak_solve_performed": False,
        "bid_signature_symmetry_breaking": True,
        "planning_solver_execution_mode": PLANNING_SOLVER_SEQUENTIAL,
        "gurobi_performance_options": {"MIPFocus": 1},
        "redispatch_physical_tiebreak_solve_performed": True,
        "forecast_horizon": "D_only",
        "scenario_count": 10,
        "risk_policy": "risk_neutral",
        "price_insensitive_comparison_basis": (
            "frozen_flat80_dispatch_revalued_on_common_s10_without_replanning"
        ),
        "economic_horizon_hours": 24,
        "execution_hours": 24,
        "physical_horizon_hours": 48,
        "internal_physics_grid": "quarterhour",
        "solver_seed": 0,
        "solver_time_limit_seconds": 900,
        "output_policy": "minimal",
    }
    for key, expected in exact.items():
        if contract.get(key) != expected:
            raise BehaviouralValidationError(f"Frozen contract changed: {key}.")
    if float(contract.get("mip_gap_limit", -1.0)) != 0.001:
        raise BehaviouralValidationError("Frozen physical MIP gap changed.")
    if float(contract.get("economic_mip_gap_limit", -1.0)) != 0.002:
        raise BehaviouralValidationError("Frozen economic MIP gap changed.")
    if float(contract.get("integer_feasibility_tolerance", -1.0)) != 1e-9:
        raise BehaviouralValidationError("Frozen IntFeasTol changed.")
    if float(contract.get("cvar_gamma", -1.0)) != 0.0:
        raise BehaviouralValidationError("CVaR was activated.")
    forbidden = contract.get("forbidden_scope", {})
    if forbidden.get("imbalance_optimisation") is not False or any(
        value is not True
        for key, value in forbidden.items()
        if key != "imbalance_optimisation"
    ):
        raise BehaviouralValidationError("The authorised recourse or forbidden scope changed.")
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
        raise BehaviouralValidationError(
            "The authorised EUR 5,000/MWh execution-recourse contract changed."
        )
    augmentation = contract.get("path_feasibility_augmentation", {})
    expected_augmentation = {
        "active": True,
        "lineage_role": "validation_derived_feasibility_only",
        "acceptance_contract": "canonical_bid_step_rank_mask_by_lead_position",
        "maximum_augmentation_rounds": MAX_PATH_FEASIBILITY_AUGMENTATION_ROUNDS,
        "maximum_patterns_added_per_round": 1,
        "bid_selection_mode": FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
        "unused_bid_step_fill": "analytical_zero_if_reconstruction_preserved",
        "additional_full_canonical_bid_milp_allowed": False,
        "economic_scenario_binary_incumbent_fix_required": False,
        "parent_round_restricted_bridge_active": True,
        "parent_round_bridge_fixed_scope": "economic_scenario_binaries_only",
        "parent_round_bridge_final_result_eligible": False,
        "parent_round_bridge_preservation_constraint_allowed": False,
        "parent_round_bridge_requires_full_expected_cost_resolve": True,
        "probability_allowed": False,
        "expected_cost_weight_allowed": False,
        "raw_shadow_price_transport_allowed": False,
        "final_test_period_source_allowed": False,
        "allowed_source_classes": [
            "development_shadow",
            "controlled_synthetic_validation",
        ],
        "controlled_synthetic_profiles_frozen_before_solve": True,
        "controlled_synthetic_pattern_application_scope": (
            "same_profile_development_only"
        ),
        "exact_zero_imbalance_required": True,
    }
    if augmentation != expected_augmentation:
        raise BehaviouralValidationError(
            "The bounded path-feasibility augmentation contract changed."
        )
    if payload["directional_hypotheses"].get(
        "numerical_source_calibration_targets_allowed"
    ) is not False:
        raise BehaviouralValidationError("Source results may only be directional.")
    eligibility = payload.get("plant_eligibility_contract", {})
    expected_eligibility = {
        "determined_before_solve": True,
        "materiality_threshold": (
            "max_1_mwh_per_day_or_0.1_percent_of_relevant_daily_energy"
        ),
        "eaf_requires_c1_responsive_nonflat_profile": True,
        "drp_buffer_requires_eligible_eaf_timing": True,
        "route_substitution_authorized": False,
        "route_substitution_not_applicable_reason": (
            "frozen_one_day_route_quota_contract_does_not_prove_"
            "substitution_headroom"
        ),
        "vn25_efficiency": VN25_ELECTRICITY_EFFICIENCY,
        "named_ng_price_eur_per_mwh_lhv": NAMED_NG_PRICE_EUR_PER_MWH_LHV,
        "vn25_requires_break_even_crossing_and_c1_responsive_mode": True,
        "boiler_and_flare_follow_vn25_wag_allocation_eligibility": True,
        "not_applicable_must_be_pre_solve": True,
    }
    if eligibility != expected_eligibility:
        raise BehaviouralValidationError("Plant eligibility contract changed.")
    rolling_week = payload.get("non_final_rolling_week", {})
    expected_rolling_week = {
        "week_id": "validation_week_2025-06-16",
        "week_start": "2025-06-16",
        "week_end": "2025-06-22",
        "selection_rule": (
            "earliest_complete_monday_sunday_after_three_frozen_shadow_sources"
        ),
        "minimum_prior_shadow_source_count": 3,
        "require_every_feasibility_pattern_source_before_week": True,
        "configurations": ["C0", "C1"],
        "arms": ["A_hourly", "B_qh_flat", "C_qh_shape"],
        "scenario_count": 10,
        "horizon_hours": 24,
        "execution_hours": 24,
        "day_count": 7,
        "maintenance_policy": "maintenance_free_normal_operation_week",
        "final_test_period_overlap_allowed": False,
        "output_policy": "minimal",
    }
    if rolling_week != expected_rolling_week:
        raise BehaviouralValidationError(
            "The bounded non-final rolling-week contract changed."
        )
    rolling_start = date.fromisoformat(str(rolling_week["week_start"]))
    rolling_end = date.fromisoformat(str(rolling_week["week_end"]))
    if (
        rolling_start.weekday() != 0
        or (rolling_end - rolling_start).days != 6
        or any(
            _inside_period(day, _final_periods(payload))
            for day in pd.date_range(rolling_start, rolling_end, freq="D").date
        )
    ):
        raise BehaviouralValidationError(
            "The rolling validation week is not a complete non-final Monday-Sunday."
        )
    return payload


def _final_periods(config: Mapping[str, Any]) -> list[tuple[date, date]]:
    return [
        (date.fromisoformat(row["start"]), date.fromisoformat(row["end"]))
        for row in config["final_test_periods"]
    ]


def _inside_period(day: date, periods: Sequence[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in periods)


def _distance_to_period(day: date, period: tuple[date, date]) -> int:
    start, end = period
    if start <= day <= end:
        return 0
    if day < start:
        return (start - day).days
    return (day - end).days


def audit_phase0_evidence(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and fingerprint accepted prerequisites without rerunning them."""

    rows: list[dict[str, Any]] = []
    for item in config["phase0_evidence"]:
        root = _resolve(item["root"])
        artifact = root / item["artifact"]
        reusable = artifact.exists()
        observed_status = "missing"
        reason = "artifact_missing"
        if reusable and artifact.suffix.lower() == ".json":
            data = json.loads(artifact.read_text(encoding="utf-8"))
            if "accepted_variant" in item:
                variants = {
                    str(row.get("variant")): row
                    for row in data.get("variant_results", [])
                }
                variant = variants.get(str(item["accepted_variant"]), {})
                reusable = bool(
                    variant.get("three_process_reproducibility_pass")
                    and str(variant.get("termination", "")).lower() == "optimal"
                )
                observed_status = (
                    "reproducible_optimal" if reusable else "variant_not_reusable"
                )
            else:
                observed_status = str(data.get("status", data.get("decision", "unknown")))
                reusable = observed_status == str(item["accepted_status"])
            reason = "accepted_existing_evidence" if reusable else "status_mismatch"
        elif reusable:
            frame = pd.read_csv(artifact)
            if item.get("accepted_all_checks"):
                reusable = not frame.empty and frame["status"].astype(str).str.lower().eq(
                    "pass"
                ).all()
                observed_status = "all_pass" if reusable else "failed_checks_present"
            else:
                selected = frame[
                    frame["check_id"].astype(str).eq(str(item["accepted_check_id"]))
                ]
                reusable = not selected.empty and selected["status"].astype(str).str.lower().eq(
                    "pass"
                ).all()
                observed_status = "pass" if reusable else "missing_or_failed_check"
            reason = "accepted_existing_evidence" if reusable else "check_mismatch"
        rows.append(
            {
                "prerequisite_id": item["prerequisite_id"],
                "run_id": root.name,
                "artifact": artifact.relative_to(REPO_ROOT).as_posix()
                if artifact.is_relative_to(REPO_ROOT)
                else artifact.name,
                "status": observed_status,
                "sha256": _sha256(artifact) if artifact.exists() else None,
                "reusable": bool(reusable),
                "new_solve_required": False,
                "reason": reason,
            }
        )
    return rows


def _load_shape_library(frames: StudyFrames) -> dict[str, pd.DataFrame]:
    study_config = yaml.safe_load(
        (frames.study_root / "resolved_config.yaml").read_text(encoding="utf-8")
    )
    shape_root = _resolve(study_config["shape_overlay"]["strict_qh_run_root"])
    optimisation = shape_root / "optimisation_inputs"
    return build_shape_library(
        pd.read_parquet(optimisation / "hourly_point_forecasts.parquet"),
        pd.read_parquet(optimisation / "quarterhour_point_forecasts.parquet"),
        pd.read_parquet(optimisation / "hourly_scenarios_10.parquet"),
        pd.read_parquet(optimisation / "quarterhour_scenarios_10.parquet"),
        pd.read_parquet(shape_root / "evaluation_actuals.parquet"),
    )


def _actual_shape_prices(
    day: date,
    hourly_actuals: Sequence[float],
    shape_library: Mapping[str, pd.DataFrame],
    *,
    random_seed: int,
    week_id: str,
) -> np.ndarray:
    profiles = [
        (key, group.sort_values("target_timestamp_utc"))
        for key, group in shape_library["actual"].groupby(
            ["source_local_date", "weekend"]
        )
        if len(group) == PHYSICAL_INTERVALS_PER_DAY
    ]
    weekend = day.weekday() >= 5
    candidates = [(key, profile) for key, profile in profiles if bool(key[1]) == weekend]
    if not candidates:
        raise BehaviouralValidationError("No complete QH actual shape for the day type.")
    choice = stable_seed(random_seed, week_id, day, "actual_shape") % len(candidates)
    _, source = candidates[choice]
    source_by_hour = {
        int(hour): group.sort_values("quarter_index")["quarterhour_delta"].to_numpy(
            dtype=float
        )
        for hour, group in source.groupby("local_hour")
    }
    values: list[float] = []
    for hour, anchor in enumerate(hourly_actuals):
        deltas = source_by_hour[hour]
        centred = deltas - float(np.mean(deltas))
        values.extend(float(anchor + delta) for delta in centred)
    return np.asarray(values, dtype=float)


def _robust_z(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for column in columns:
        values = frame[column].astype(float)
        median = float(values.median())
        mad = float((values - median).abs().median()) * 1.4826
        if mad <= 1e-12:
            mad = float(values.quantile(0.75) - values.quantile(0.25)) / 1.349
        result[column] = (values - median) / (mad if mad > 1e-12 else 1.0)
    return result


def _eligible_day_features(
    config: Mapping[str, Any],
    frames: StudyFrames,
    shape_library: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    selection = config["shadow_selection"]
    periods = _final_periods(config)
    buffer_days = int(selection["final_period_buffer_days"])
    seed = int(config["shape_overlay"]["random_seed"])
    points = frames.hourly_points[
        frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
        & frames.hourly_points["dataset_split"].eq("test")
    ].copy()
    points["target_timestamp_utc"] = pd.to_datetime(
        points["target_timestamp_utc"], utc=True
    )
    scenarios = frames.hourly_scenarios_10[
        frames.hourly_scenarios_10["model_id"].eq(STRICT_MODEL_ID)
    ].copy()
    start = date.fromisoformat(selection["development_start"])
    end = date.fromisoformat(selection["development_end"])
    rows: list[dict[str, Any]] = []
    for day_text, group in points.groupby("delivery_date_local", sort=True):
        day = date.fromisoformat(str(day_text))
        if day < start or day > end:
            continue
        final_distance = min(_distance_to_period(day, period) for period in periods)
        naive_day = day - timedelta(days=7)
        naive_group = points[
            points["delivery_date_local"].eq(naive_day.isoformat())
        ].sort_values("target_timestamp_utc")
        naive_local = naive_group["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ)
        naive_support_ok = bool(
            len(naive_group) == 24
            and naive_group["target_timestamp_utc"].nunique() == 24
            and naive_group["actual_price"].notna().all()
            and naive_local.dt.date.nunique() == 1
            and naive_local.dt.date.iloc[0] == naive_day
        )
        final_overlap = _inside_period(day, periods)
        naive_final_overlap = _inside_period(naive_day, periods)
        group = group.sort_values("target_timestamp_utc")
        scenario_day = scenarios[
            scenarios["delivery_date_local"].eq(day.isoformat())
        ].copy()
        counts = scenario_day.groupby("scenario_id").size()
        probability = scenario_day.groupby("scenario_id")[
            "scenario_probability"
        ].first()
        local = group["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ)
        origin = pd.to_datetime(group["forecast_origin_utc"], utc=True).drop_duplicates()
        support_ok = bool(
            len(group) == 24
            and group["target_timestamp_utc"].nunique() == 24
            and local.dt.date.nunique() == 1
            and local.dt.date.iloc[0] == day
            and len(origin) == 1
            and origin.iloc[0] == expected_origin_utc(day)
            and group["actual_price"].notna().all()
            and len(counts) == 10
            and counts.eq(24).all()
            and abs(float(probability.sum()) - 1.0) <= 1e-10
            and naive_support_ok
        )
        exclusion_ok = bool(
            not final_overlap
            and final_distance >= buffer_days
            and not (
                bool(selection["require_previous_week_naive_outside_final_periods"])
                and naive_final_overlap
            )
        )
        if not support_ok or not exclusion_ok:
            continue
        actual_hourly = group["actual_price"].astype(float).to_numpy()
        qh_actual = _actual_shape_prices(
            day,
            actual_hourly,
            shape_library,
            random_seed=seed,
            week_id=f"shadow__{day.isoformat()}",
        )
        ramps = np.diff(qh_actual)
        rows.append(
            {
                "day": day.isoformat(),
                "mean_price_eur_per_mwh": float(np.mean(qh_actual)),
                "std_price_eur_per_mwh": float(np.std(qh_actual, ddof=0)),
                "iqr_price_eur_per_mwh": float(
                    np.quantile(qh_actual, 0.75) - np.quantile(qh_actual, 0.25)
                ),
                "p05_p95_range_eur_per_mwh": float(
                    np.quantile(qh_actual, 0.95) - np.quantile(qh_actual, 0.05)
                ),
                "mean_abs_ramp_eur_per_mwh": float(np.mean(np.abs(ramps))),
                "negative_qh_share": float(np.mean(qh_actual < 0.0)),
                "minimum_qh_price_eur_per_mwh": float(np.min(qh_actual)),
                "maximum_qh_price_eur_per_mwh": float(np.max(qh_actual)),
                "distance_to_final_period_days": final_distance,
                "previous_week_naive_day": naive_day.isoformat(),
                "d_only_strict_support": True,
                "s10_support": True,
                "hourly_actual_support": True,
                "qh_overlay_support": True,
                "economic_24h_support": True,
                "physical_48h_price_free_tail_support": True,
                "dst_complete_24h": True,
                "interpolated": False,
                "final_period_overlap": False,
                "previous_week_final_period_overlap": False,
                "previous_week_naive_complete_24h": True,
            }
        )
    features = pd.DataFrame(rows)
    if features.empty:
        raise BehaviouralValidationError("No eligible shadow development days.")
    typical_columns = selection["typical_feature_columns"]
    robust = _robust_z(features, typical_columns)
    features["typical_robust_distance"] = np.sqrt((robust**2).sum(axis=1))
    volatility_columns = selection["volatility_feature_columns"]
    percentile_parts = [
        features[column].rank(method="average", pct=True)
        for column in volatility_columns
    ]
    features["volatility_composite_percentile"] = pd.concat(
        percentile_parts, axis=1
    ).mean(axis=1)
    for column in (
        "mean_price_eur_per_mwh",
        "std_price_eur_per_mwh",
        "iqr_price_eur_per_mwh",
        "p05_p95_range_eur_per_mwh",
        "mean_abs_ramp_eur_per_mwh",
        "negative_qh_share",
    ):
        features[f"{column}_percentile"] = features[column].rank(
            method="average", pct=True
        )
    return features.sort_values("day").reset_index(drop=True)


def select_shadow_days(
    config: Mapping[str, Any],
    frames: StudyFrames,
    shape_library: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Select four development days deterministically without model outcomes."""

    features = _eligible_day_features(config, frames, shape_library)
    selection = config["shadow_selection"]
    price_cut = float(features["mean_price_eur_per_mwh"].quantile(0.90))
    volatility_cut = float(
        features["volatility_composite_percentile"].quantile(0.90)
    )
    rankings = {
        "typical_calm": features.sort_values(
            ["typical_robust_distance", "day"], ascending=[True, True]
        ),
        "high_price": features[
            features["mean_price_eur_per_mwh"].ge(price_cut)
        ].sort_values(
            ["mean_price_eur_per_mwh", "day"], ascending=[False, True]
        ),
        "high_volatility": features[
            features["volatility_composite_percentile"].ge(volatility_cut)
        ].sort_values(
            ["volatility_composite_percentile", "day"], ascending=[False, True]
        ),
        "negative_low_price": features.sort_values(
            ["negative_qh_share", "mean_price_eur_per_mwh", "day"],
            ascending=[False, True, True],
        ),
    }
    minimum = int(selection["minimum_pairwise_separation_days"])
    selected: list[dict[str, Any]] = []
    selected_days: list[date] = []
    for role in selection["regime_order"]:
        ranked = rankings[role].reset_index(drop=True)
        chosen: dict[str, Any] | None = None
        for rank, row in ranked.iterrows():
            candidate = date.fromisoformat(str(row["day"]))
            if all(abs((candidate - prior).days) >= minimum for prior in selected_days):
                chosen = row.to_dict()
                chosen["selection_rank_within_role"] = int(rank + 1)
                break
        if chosen is None:
            raise BehaviouralValidationError(
                f"No {role} day satisfies the frozen {minimum}-day separation."
            )
        chosen_day = date.fromisoformat(str(chosen["day"]))
        selected_days.append(chosen_day)
        chosen.update(
            {
                "day_id": f"shadow__{role}__{chosen_day.isoformat()}",
                "regime_role": role,
                "selection_frozen_before_solve": True,
                "development_shadow_case": True,
                "final_test_case": False,
                "minimum_pairwise_separation_days": minimum,
                "selection_uses_economic_model_outputs": False,
            }
        )
        selected.append(chosen)
    result = pd.DataFrame(selected)
    pairwise = [
        abs((left - right).days)
        for index, left in enumerate(selected_days)
        for right in selected_days[index + 1 :]
    ]
    if min(pairwise, default=minimum) < minimum:
        raise BehaviouralValidationError("Shadow selection separation failed.")
    return result.sort_values("regime_role").reset_index(drop=True)


def _day_rows(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    return frame[frame["delivery_date_local"].eq(day.isoformat())].copy()


def build_shadow_overlay(
    config: Mapping[str, Any],
    frames: StudyFrames,
    shape_library: Mapping[str, pd.DataFrame],
    selection: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    overlays: list[pd.DataFrame] = []
    manifests: list[dict[str, Any]] = []
    seed = int(config["shape_overlay"]["random_seed"])
    tolerance = float(config["shape_overlay"]["mean_preservation_tolerance"])
    strict_points = frames.hourly_points[
        frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
    ]
    strict_scenarios = frames.hourly_scenarios_10[
        frames.hourly_scenarios_10["model_id"].eq(STRICT_MODEL_ID)
    ]
    for row in selection.to_dict(orient="records"):
        day = date.fromisoformat(str(row["day"]))
        points = _day_rows(strict_points, day).sort_values("target_timestamp_utc")
        scenarios = _day_rows(strict_scenarios, day).sort_values(
            ["scenario_id", "target_timestamp_utc"]
        )
        actuals = points[
            ["target_timestamp_utc", "delivery_date_local", "actual_price"]
        ].copy()
        overlay, manifest = apply_counterfactual_shape_overlay(
            week_id=str(row["day_id"]),
            hourly_points=points,
            hourly_scenarios=scenarios,
            hourly_actuals=actuals,
            shape_library=dict(shape_library),
            random_seed=seed,
            tolerance=tolerance,
        )
        manifest["day"] = day.isoformat()
        manifest["development_shadow_case"] = True
        manifest["final_test_case"] = False
        overlays.append(overlay)
        manifests.append(manifest)
    combined = pd.concat(overlays, ignore_index=True)
    if not bool(combined["counterfactual"].all()):
        raise BehaviouralValidationError("Shadow overlay lost its counterfactual flag.")
    return combined, manifests


def _bundle_from_overlay(
    overlay: pd.DataFrame,
    *,
    delivery_day: date,
    point_kind: str,
    scenario_kind: str,
    model_id: str,
    scenario_count: int = 10,
    source_blocks: Mapping[str, str] | None = None,
) -> tuple[SteelPriceInformationBundle, SteelActualPriceBundle]:
    if scenario_count not in {10, 30}:
        raise BehaviouralValidationError("Only governed S10/S30 bundles are supported.")
    point = overlay[overlay["path_kind"].eq(point_kind)].sort_values(
        "target_timestamp_utc"
    )
    scenarios = overlay[
        overlay["path_kind"].eq(scenario_kind)
        & overlay["scenario_set_size"].eq(scenario_count)
    ].copy()
    actual = overlay[overlay["path_kind"].eq("counterfactual_actual")].sort_values(
        "target_timestamp_utc"
    )
    if len(point) != 96 or len(actual) != 96:
        raise BehaviouralValidationError("QH point/actual bundle is incomplete.")
    scenario_prices: dict[str, tuple[float, ...]] = {}
    probabilities: dict[str, float] = {}
    sources: dict[str, str] = {}
    for scenario_id, group in scenarios.groupby("scenario_id", sort=True):
        ordered = group.sort_values("target_timestamp_utc")
        if len(ordered) != 96:
            raise BehaviouralValidationError("Synthetic/shadow scenario is incomplete.")
        scenario_prices[str(scenario_id)] = tuple(
            ordered["quarterhour_price"].astype(float)
        )
        probability_values = ordered["scenario_probability"].drop_duplicates()
        if len(probability_values) != 1:
            raise BehaviouralValidationError("Scenario probability varies within path.")
        probabilities[str(scenario_id)] = float(probability_values.iloc[0])
        overlay_sources = "|".join(sorted(ordered["source_profile_id"].astype(str).unique()))
        sources[str(scenario_id)] = (
            f"{source_blocks[str(scenario_id)]}|{overlay_sources}"
            if source_blocks is not None
            else overlay_sources
        )
    if (
        len(scenario_prices) != scenario_count
        or abs(sum(probabilities.values()) - 1.0) > 1e-10
    ):
        raise BehaviouralValidationError(
            f"S{scenario_count} probability contract failed."
        )
    timestamps = tuple(pd.to_datetime(point["target_timestamp_utc"], utc=True))
    actual_timestamps = tuple(pd.to_datetime(actual["target_timestamp_utc"], utc=True))
    if timestamps != actual_timestamps:
        raise BehaviouralValidationError("Point and actual QH timestamps differ.")
    price_bundle = SteelPriceInformationBundle(
        delivery_day=delivery_day,
        forecast_origin_utc=expected_origin_utc(delivery_day),
        timestamps_utc=timestamps,
        point_prices=tuple(point["quarterhour_price"].astype(float)),
        scenario_prices=scenario_prices,
        scenario_probabilities=probabilities,
        scenario_source_blocks=sources,
        model_id=model_id,
        granularity="quarterhour",
        time_step_hours=0.25,
    )
    actual_bundle = SteelActualPriceBundle(
        delivery_day=delivery_day,
        timestamps_utc=actual_timestamps,
        prices=tuple(actual["quarterhour_price"].astype(float)),
        granularity="quarterhour",
        time_step_hours=0.25,
    )
    price_bundle.assert_actual_free()
    return price_bundle, actual_bundle


def build_synthetic_bundles(
    config: Mapping[str, Any],
    frames: StudyFrames,
    shape_library: Mapping[str, pd.DataFrame],
    *,
    scenario_count: int = 10,
) -> dict[str, tuple[SteelPriceInformationBundle, SteelActualPriceBundle]]:
    """Create paired S0--S3 inputs with governed common residuals and QH shapes."""

    if scenario_count not in {10, 30}:
        raise BehaviouralValidationError("Synthetic diagnostics support only S10/S30.")

    synthetic = config["synthetic"]
    scenario_day = date.fromisoformat(synthetic["scenario_residual_source_date"])
    actual_day = date.fromisoformat(synthetic["actual_residual_source_date"])
    periods = _final_periods(config)
    if _inside_period(scenario_day, periods) or _inside_period(actual_day, periods):
        raise BehaviouralValidationError("A synthetic residual source touches a final week.")
    points_all = frames.hourly_points[
        frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
    ]
    scenario_frame = (
        frames.hourly_scenarios_10
        if scenario_count == 10
        else frames.hourly_scenarios_30
    )
    scenarios_all = scenario_frame[
        scenario_frame["model_id"].eq(STRICT_MODEL_ID)
    ]
    source_points = _day_rows(points_all, scenario_day).sort_values(
        "target_timestamp_utc"
    )
    source_scenarios = _day_rows(scenarios_all, scenario_day).sort_values(
        ["scenario_id", "target_timestamp_utc"]
    )
    actual_source = _day_rows(points_all, actual_day).sort_values(
        "target_timestamp_utc"
    )
    if len(source_points) != 24 or len(actual_source) != 24:
        raise BehaviouralValidationError("Synthetic residual source support is incomplete.")
    point_anchor = source_points.set_index("target_timestamp_utc")["point_forecast"]
    source_scenarios["residual"] = source_scenarios.apply(
        lambda row: float(row["scenario_price"])
        - float(point_anchor[pd.Timestamp(row["target_timestamp_utc"])]),
        axis=1,
    )
    source_scenarios["residual"] = source_scenarios.groupby("scenario_id")[
        "residual"
    ].transform(lambda values: values - values.mean())
    errors = (
        actual_source["actual_price"].astype(float).to_numpy()
        - actual_source["point_forecast"].astype(float).to_numpy()
    )
    errors = errors - float(np.mean(errors))
    source_blocks = {
        str(scenario_id): "|".join(
            sorted(group["source_residual_block_id"].astype(str).unique())
        )
        for scenario_id, group in source_scenarios.groupby("scenario_id")
    }
    bundles: dict[
        str, tuple[SteelPriceInformationBundle, SteelActualPriceBundle]
    ] = {}
    common_overlay_id = "synthetic_common_random_numbers"
    for profile_id, values in synthetic["point_profiles_eur_per_mwh"].items():
        central = np.asarray(values, dtype=float)
        if len(central) != 24:
            raise BehaviouralValidationError(f"{profile_id} is not a 24-hour profile.")
        points = source_points.copy()
        points["point_forecast"] = central
        scenarios = source_scenarios.copy()
        hour_lookup = {
            timestamp: float(central[index])
            for index, timestamp in enumerate(points["target_timestamp_utc"])
        }
        scenarios["scenario_price"] = scenarios.apply(
            lambda row: hour_lookup[row["target_timestamp_utc"]]
            + float(row["residual"]),
            axis=1,
        )
        actuals = points[
            ["target_timestamp_utc", "delivery_date_local"]
        ].copy()
        actuals["actual_price"] = central + errors
        overlay, _ = apply_counterfactual_shape_overlay(
            week_id=common_overlay_id,
            hourly_points=points,
            hourly_scenarios=scenarios,
            hourly_actuals=actuals,
            shape_library=dict(shape_library),
            random_seed=int(config["shape_overlay"]["random_seed"]),
            tolerance=float(config["shape_overlay"]["mean_preservation_tolerance"]),
        )
        overlay["week_id"] = profile_id
        bundles[profile_id] = _bundle_from_overlay(
            overlay,
            delivery_day=scenario_day,
            point_kind="point_shape",
            scenario_kind="scenario_shape",
            model_id=(
                f"synthetic_controlled_{profile_id}_strict_s{scenario_count}_crn"
            ),
            scenario_count=scenario_count,
            source_blocks=source_blocks,
        )
    reference = bundles["S0_flat_reference"][0]
    for profile_id, (bundle, actual) in bundles.items():
        if tuple(bundle.scenario_probabilities) != tuple(reference.scenario_probabilities):
            raise BehaviouralValidationError("Synthetic scenario IDs are not common.")
        if bundle.scenario_probabilities != reference.scenario_probabilities:
            raise BehaviouralValidationError("Synthetic probabilities are not common.")
        central = np.repeat(
            np.asarray(synthetic["point_profiles_eur_per_mwh"][profile_id], dtype=float),
            4,
        )
        reference_central = np.repeat(
            np.asarray(
                synthetic["point_profiles_eur_per_mwh"]["S0_flat_reference"],
                dtype=float,
            ),
            4,
        )
        for scenario_id in bundle.scenario_prices:
            residual = np.asarray(bundle.scenario_prices[scenario_id]) - central
            reference_residual = (
                np.asarray(reference.scenario_prices[scenario_id]) - reference_central
            )
            if not np.allclose(residual, reference_residual, atol=1e-10, rtol=0.0):
                raise BehaviouralValidationError(
                    "Synthetic common-random-number identity failed."
                )
        actual_residual = np.asarray(actual.prices) - central
        reference_actual_residual = np.asarray(bundles["S0_flat_reference"][1].prices) - (
            reference_central
        )
        if not np.allclose(actual_residual, reference_actual_residual, atol=1e-10):
            raise BehaviouralValidationError("Synthetic actual residual identity failed.")
    return bundles


def build_case_manifest(config: Mapping[str, Any], selection: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for case in config["synthetic"]["cases"]:
        rows.append(
            {
                **case,
                "phase": "synthetic",
                "day_id": "synthetic_common_random_numbers",
                "delivery_day": config["synthetic"]["scenario_residual_source_date"],
                "arm": "C_qh_shape",
                "granularity": "quarterhour",
                "scenario_count": 10,
                "development_shadow_case": False,
                "final_test_case": False,
                "solve_sequence": len(rows) + 1,
            }
        )
    high_volatility = selection[
        selection["regime_role"].eq("high_volatility")
    ].iloc[0]
    for shadow in selection.to_dict(orient="records"):
        for configuration in ("C0", "C1"):
            rows.append(
                {
                    "case_id": f"{shadow['day_id']}__C__{configuration}__responsive",
                    "profile_id": shadow["regime_role"],
                    "configuration": configuration,
                    "policy": "responsive",
                    "phase": "shadow",
                    "day_id": shadow["day_id"],
                    "delivery_day": shadow["day"],
                    "arm": "C_qh_shape",
                    "granularity": "quarterhour",
                    "scenario_count": 10,
                    "development_shadow_case": True,
                    "final_test_case": False,
                    "solve_sequence": len(rows) + 1,
                }
            )
    additions = (
        ("C0", "price_insensitive", "C_qh_shape", "quarterhour"),
        ("C1", "price_insensitive", "C_qh_shape", "quarterhour"),
        ("C1", "true_pf", "C_qh_shape", "quarterhour"),
        ("C1", "responsive", "A_hourly", "hourly"),
        ("C1", "responsive", "B_qh_flat", "quarterhour"),
    )
    for configuration, policy, arm, granularity in additions:
        rows.append(
            {
                "case_id": (
                    f"{high_volatility['day_id']}__{arm}__{configuration}__{policy}"
                ),
                "profile_id": "high_volatility",
                "configuration": configuration,
                "policy": policy,
                "phase": "shadow",
                "day_id": high_volatility["day_id"],
                "delivery_day": high_volatility["day"],
                "arm": arm,
                "granularity": granularity,
                "scenario_count": 10,
                "development_shadow_case": True,
                "final_test_case": False,
                "solve_sequence": len(rows) + 1,
            }
        )
    manifest = pd.DataFrame(rows)
    if manifest["case_id"].duplicated().any():
        raise BehaviouralValidationError("Behavioural case IDs are not unique.")
    if len(manifest[manifest["phase"].eq("synthetic")]) != 9:
        raise BehaviouralValidationError("Synthetic matrix is not exactly nine trajectories.")
    if len(manifest[manifest["phase"].eq("shadow")]) != 13:
        raise BehaviouralValidationError("Shadow matrix is not exactly 13 trajectories.")
    return manifest.sort_values("solve_sequence").reset_index(drop=True)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights) - 0.5 * sorted_weights
    cumulative = cumulative / float(np.sum(sorted_weights))
    return float(np.interp(q, cumulative, sorted_values))


def forecast_diagnostics(
    *,
    case_scope_id: str,
    regime_role: str,
    arm: str,
    bundle: SteelPriceInformationBundle,
    actual: SteelActualPriceBundle,
    naive_prices: Sequence[float],
) -> dict[str, Any]:
    point = np.asarray(bundle.point_prices, dtype=float)
    observed = np.asarray(actual.prices, dtype=float)
    naive = np.asarray(naive_prices, dtype=float)
    if point.shape != observed.shape or point.shape != naive.shape:
        raise BehaviouralValidationError("Forecast diagnostic supports differ.")
    scenario_ids = tuple(sorted(bundle.scenario_prices))
    paths = np.asarray([bundle.scenario_prices[key] for key in scenario_ids], dtype=float)
    probability = np.asarray(
        [bundle.scenario_probabilities[key] for key in scenario_ids], dtype=float
    )
    quantiles: dict[float, np.ndarray] = {}
    for level in (0.05, 0.10, 0.25, 0.75, 0.90, 0.95):
        quantiles[level] = np.asarray(
            [_weighted_quantile(paths[:, index], probability, level) for index in range(paths.shape[1])]
        )
    errors = point - observed
    naive_mae = float(np.mean(np.abs(naive - observed)))
    scenario_mean = np.average(paths, axis=0, weights=probability)
    spread = np.sqrt(
        np.average((paths - scenario_mean) ** 2, axis=0, weights=probability)
    )
    actual_ramps = np.diff(observed)
    scenario_ramps = np.diff(paths, axis=1)
    ramp_low = np.asarray(
        [
            _weighted_quantile(scenario_ramps[:, index], probability, 0.05)
            for index in range(scenario_ramps.shape[1])
        ]
    )
    ramp_high = np.asarray(
        [
            _weighted_quantile(scenario_ramps[:, index], probability, 0.95)
            for index in range(scenario_ramps.shape[1])
        ]
    )
    negative = observed < 0.0
    return {
        "case_scope_id": case_scope_id,
        "diagnostic_stage": "predispatch",
        "regime_role": regime_role,
        "arm": arm,
        "model_id": bundle.model_id,
        "delivery_day": bundle.delivery_day.isoformat(),
        "granularity": bundle.granularity,
        "point_mae_eur_per_mwh": float(np.mean(np.abs(errors))),
        "point_bias_eur_per_mwh": float(np.mean(errors)),
        "naive_mae_eur_per_mwh": naive_mae,
        "rmae_previous_week_naive": (
            float(np.mean(np.abs(errors))) / naive_mae if naive_mae > 1e-12 else None
        ),
        "coverage_50": float(np.mean((observed >= quantiles[0.25]) & (observed <= quantiles[0.75]))),
        "coverage_80": float(np.mean((observed >= quantiles[0.10]) & (observed <= quantiles[0.90]))),
        "coverage_90": float(np.mean((observed >= quantiles[0.05]) & (observed <= quantiles[0.95]))),
        "interval_width_50_eur_per_mwh": float(np.mean(quantiles[0.75] - quantiles[0.25])),
        "interval_width_80_eur_per_mwh": float(np.mean(quantiles[0.90] - quantiles[0.10])),
        "interval_width_90_eur_per_mwh": float(np.mean(quantiles[0.95] - quantiles[0.05])),
        "mean_scenario_spread_eur_per_mwh": float(np.mean(spread)),
        "mean_actual_rank_fraction": float(np.mean(np.sum(paths <= observed, axis=0) / len(paths))),
        "ramp_coverage_90": float(np.mean((actual_ramps >= ramp_low) & (actual_ramps <= ramp_high))),
        "negative_actual_interval_count": int(np.sum(negative)),
        "negative_price_coverage": (
            float(
                np.mean(
                    (observed[negative] >= quantiles[0.05][negative])
                    & (observed[negative] <= quantiles[0.95][negative])
                )
            )
            if negative.any()
            else None
        ),
        "unique_complete_scenario_paths": int(np.unique(paths, axis=0).shape[0]),
        "scenario_count": len(paths),
        "probability_mass": float(np.sum(probability)),
        "forecast_errors_around_eaf_starts_eur_per_mwh": None,
        "forecast_errors_around_generator_activation_eur_per_mwh": None,
        "forecast_errors_around_large_net_import_eur_per_mwh": None,
    }


def _solve_tier_count(configuration: str, policy: str) -> int:
    return _planning_tier_count(configuration, policy) + _redispatch_tier_count(
        configuration, policy
    )


def _planning_tier_count(configuration: str, policy: str) -> int:
    planning = 2
    if policy == "price_insensitive":
        planning += 1
        if configuration == "C1":
            planning += 1
    return planning


def _redispatch_tier_count(configuration: str, policy: str) -> int:
    redispatch = 3
    if policy == "price_insensitive":
        redispatch += 1
        if configuration == "C1":
            redispatch += 1
    return redispatch


def _input_manifest(
    config_path: Path,
    config: Mapping[str, Any],
    frames: StudyFrames,
    evidence: Sequence[Mapping[str, Any]],
    shape_library: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    representative_path = _resolve(config["representative_config"])
    inputs = [config_path, representative_path, frames.study_root / "run_summary.json"]
    inputs.extend(_resolve(path) for path in config["source_cards"])
    inputs.extend(
        _resolve(path) for path in config.get("reusable_planning_cache", {}).values()
    )
    entries = [
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "read_only_upstream": path not in {config_path},
        }
        for path in inputs
    ]
    return {
        "inputs": entries,
        "phase0_evidence": list(evidence),
        "shape_library": {
            key: {
                "rows": int(len(value)),
                "content_sha256": _payload_sha256(
                    value[
                        [
                            "forecast_origin_utc",
                            "target_timestamp_utc",
                            "quarterhour_delta",
                        ]
                    ].astype(str).to_dict(orient="records")
                ),
            }
            for key, value in shape_library.items()
        },
        "final_test_periods_read_or_solved": False,
        "prior_final_week_evidence_referenced_only_in_phase0": True,
    }


def _previous_week_naive_prices(
    frames: StudyFrames,
    shape_library: Mapping[str, pd.DataFrame],
    *,
    delivery_day: date,
    granularity: str,
    random_seed: int,
) -> tuple[float, ...]:
    naive_day = delivery_day - timedelta(days=7)
    points = frames.hourly_points[
        frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
        & frames.hourly_points["delivery_date_local"].eq(naive_day.isoformat())
    ].sort_values("target_timestamp_utc")
    if len(points) != 24:
        raise BehaviouralValidationError("Previous-week naive support is incomplete.")
    hourly = tuple(points["actual_price"].astype(float))
    if granularity == "hourly":
        return hourly
    qh = _actual_shape_prices(
        naive_day,
        hourly,
        shape_library,
        random_seed=random_seed,
        week_id=f"shadow__{naive_day.isoformat()}",
    )
    return tuple(float(value) for value in qh)


def prepare_behavioural_run(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Freeze evidence, selection, hypotheses and the entire case manifest."""

    path = _resolve(config_path)
    config = load_behavioural_config(path)
    representative = load_representative_config(config["representative_config"])
    _representative_run_contract(representative)
    frames = load_study_frames(representative)
    evidence = audit_phase0_evidence(config)
    if not all(bool(row["reusable"]) for row in evidence):
        failed = [row for row in evidence if not bool(row["reusable"])]
        raise BehaviouralValidationError(f"Phase-0 evidence failed closed: {failed}")
    shape_library = _load_shape_library(frames)
    selection = select_shadow_days(config, frames, shape_library)
    final_days = {
        day
        for start, end in _final_periods(config)
        for day in pd.date_range(start, end, freq="D").date
    }
    if any(date.fromisoformat(day) in final_days for day in selection["day"]):
        raise BehaviouralValidationError("A final-test date entered shadow selection.")
    overlay, overlay_manifests = build_shadow_overlay(
        config, frames, shape_library, selection
    )
    synthetic_bundles = build_synthetic_bundles(config, frames, shape_library)
    manifest = build_case_manifest(config, selection)
    output = _resolve(output_root or config["output_root"]) / run_id
    if output.exists() and not resume:
        existing = [path for path in output.iterdir()]
        if existing:
            raise BehaviouralValidationError(
                "Behavioural output exists; use resume or choose a new run ID."
            )
    if output.exists() and resume:
        _assert_run_execution_authorized(output, resume=True)
    output.mkdir(parents=True, exist_ok=True)
    if not (output / "run_control.json").exists():
        _write_run_control(
            output,
            status="running",
            resume_authorized=True,
            reason="conditional_minimum_imbalance_behavioural_gate",
        )
    synthetic_cases = manifest[manifest["phase"].eq("synthetic")]
    shadow_cases = manifest[manifest["phase"].eq("shadow")]
    reusable_case_ids = set(config.get("reusable_planning_cache", {}))
    synthetic_case_ids = set(synthetic_cases["case_id"].astype(str))
    invalid_reusable_case_ids = reusable_case_ids - synthetic_case_ids
    if invalid_reusable_case_ids:
        raise BehaviouralValidationError(
            "Reusable planning caches must name synthetic cases only: "
            f"{sorted(invalid_reusable_case_ids)}"
        )
    reused_synthetic_cases = synthetic_cases[
        synthetic_cases["case_id"].isin(reusable_case_ids)
    ]
    existing_result_rows = _read_csv_rows(output / "case_results.csv") if resume else []
    resume_recomputed_case_ids = {
        str(row["case_id"])
        for row in existing_result_rows
        if row.get("phase") == "synthetic"
        and row.get("policy") == "price_insensitive"
        and row.get("case_status") == "pass"
        and not _finite_number(row.get("common_s10_expected_objective_eur"))
    }
    resume_recomputed_cases = synthetic_cases[
        synthetic_cases["case_id"].isin(resume_recomputed_case_ids)
    ]
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "synthetic_trajectories": int(len(synthetic_cases)),
        "synthetic_model_builds": int(
            2 * len(synthetic_cases) - len(reused_synthetic_cases)
        ),
        "synthetic_optimisation_solves": int(
            sum(
                _solve_tier_count(row.configuration, row.policy)
                for row in synthetic_cases.itertuples()
            )
            - sum(
                _planning_tier_count(row.configuration, row.policy)
                for row in reused_synthetic_cases.itertuples()
            )
        ),
        "reused_synthetic_planning_cache_count": int(len(reused_synthetic_cases)),
        "reused_synthetic_planning_cache_case_ids": sorted(reusable_case_ids),
        "resume_recomputed_synthetic_case_ids": sorted(resume_recomputed_case_ids),
        "resume_additional_model_builds": int(2 * len(resume_recomputed_cases)),
        "resume_additional_optimisation_solves": int(
            sum(
                _solve_tier_count(row.configuration, row.policy)
                for row in resume_recomputed_cases.itertuples()
            )
        ),
        "shadow_trajectories_only_after_synthetic_pass": int(len(shadow_cases)),
        "shadow_model_builds_only_after_synthetic_pass": int(2 * len(shadow_cases)),
        "shadow_optimisation_solves_only_after_synthetic_pass": int(
            sum(
                _solve_tier_count(row.configuration, row.policy)
                for row in shadow_cases.itertuples()
            )
        ),
        "expected_approximate_size_mb": int(
            config["outputs"]["expected_approximate_size_mb"]
        ),
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "git_eligible": False,
        "final_week_matrix_authorized_or_scheduled": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    _write_json(
        output / "input_manifest.json",
        {
            **_input_manifest(path, config, frames, evidence, shape_library),
            "shadow_overlay_manifests": overlay_manifests,
        },
    )
    _write_json(
        output / "code_version.json",
        {
            "git_head": _git_head(),
            "behavioural_module_sha256": _sha256(Path(__file__)),
            "phase6d_engine_sha256": _sha256(
                Path(__file__).with_name("s4_4c6_phase6d_eaf_heat_state_one_day.py")
            ),
            "config_sha256": _sha256(path),
        },
    )
    selection.to_csv(output / "shadow_day_selection.csv", index=False)
    manifest.to_csv(output / "case_manifest.csv", index=False)

    shadow_frames = replace(frames, qh_overlay=overlay)
    diagnostic_rows: list[dict[str, Any]] = []
    unique_scopes = manifest[manifest["phase"].eq("shadow")][
        ["day_id", "delivery_day", "profile_id", "arm"]
    ].drop_duplicates()
    for row in unique_scopes.to_dict(orient="records"):
        day = date.fromisoformat(str(row["delivery_day"]))
        bundle, actual = build_price_bundles(
            shadow_frames,
            week_id=str(row["day_id"]),
            delivery_day=day,
            arm=str(row["arm"]),
            scenario_count=10,
        )
        naive = _previous_week_naive_prices(
            frames,
            shape_library,
            delivery_day=day,
            granularity=bundle.granularity,
            random_seed=int(config["shape_overlay"]["random_seed"]),
        )
        diagnostic_rows.append(
            forecast_diagnostics(
                case_scope_id=f"{row['day_id']}__{row['arm']}",
                regime_role=str(row["profile_id"]),
                arm=str(row["arm"]),
                bundle=bundle,
                actual=actual,
                naive_prices=naive,
            )
        )
    _write_csv(output / "forecast_diagnostics.csv", diagnostic_rows)
    for name in (
        "behavioural_metrics.csv",
        "physical_validation_checks.csv",
        "economic_rationality_checks.csv",
        "case_results.csv",
    ):
        if not (output / name).exists():
            _write_csv(output / name, [])
    if not (output / "solver_diagnostics.json").exists():
        _write_json(output / "solver_diagnostics.json", [])
    if not (output / "gate_summary.json").exists():
        _write_json(
            output / "gate_summary.json",
            {
                "status": "prepared_no_solver_runs",
                "decision": None,
                "synthetic_gate_pass": False,
                "shadow_gate_started": False,
                "final_weeks_used_for_development": False,
            },
        )
    if not (output / "registry_entry.json").exists():
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": run_id,
                "run_class": config["run_class"],
                "lineage_role": config["lineage_role"],
                "status": "prepared",
                "git_eligible": False,
            },
        )
    if not (output / "warnings_and_limitations.md").exists():
        _write_warnings_and_limitations(output)
    return {
        "config": config,
        "representative": representative,
        "frames": frames,
        "shape_library": shape_library,
        "selection": selection,
        "shadow_frames": shadow_frames,
        "synthetic_bundles": synthetic_bundles,
        "manifest": manifest,
        "output": output,
        "declaration": declaration,
    }


def preflight(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
) -> dict[str, Any]:
    config = load_behavioural_config(config_path)
    representative = load_representative_config(config["representative_config"])
    frames = load_study_frames(representative)
    evidence = audit_phase0_evidence(config)
    return {
        "status": "pass" if all(row["reusable"] for row in evidence) else "block",
        "phase0_evidence": evidence,
        "planning_physical_tiebreak_mode": _representative_run_contract(
            representative
        )["planning_physical_tiebreak_mode"],
        "final_test_period_count": len(config["final_test_periods"]),
        "full_final_week_matrix_authorized": False,
        "strict_hourly_support_rows": int(len(frames.hourly_points)),
        "strict_s10_support_rows": int(len(frames.hourly_scenarios_10)),
    }


def _policy_name(case: Mapping[str, Any]) -> str:
    role = str(case["policy"])
    if role == "price_insensitive":
        return "price-insensitive"
    if role == "true_pf":
        return "true-PF"
    if role != "responsive":
        raise BehaviouralValidationError(f"Unknown behavioural policy: {role}")
    return "H-S10" if case["granularity"] == "hourly" else "QH-S10"


def _bundle_for_case(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
) -> tuple[SteelPriceInformationBundle, SteelActualPriceBundle]:
    if case["phase"] == "synthetic":
        return prepared["synthetic_bundles"][str(case["profile_id"])]
    return build_price_bundles(
        prepared["shadow_frames"],
        week_id=str(case["day_id"]),
        delivery_day=date.fromisoformat(str(case["delivery_day"])),
        arm=str(case["arm"]),
        scenario_count=10,
    )


def build_plant_eligibility_records(
    prepared: Mapping[str, Any],
    cases: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Freeze plant-level applicability before any economic solve is started.

    Eligibility is derived only from the frozen configuration, policy, market grid,
    and the ex-ante point-price support.  It never uses a solved dispatch or an
    actual/final-week price.  The records are therefore suitable as a fail-closed
    pre-solve contract, not as an ex-post explanation of unexpected behaviour.
    """

    if cases.empty:
        raise BehaviouralValidationError("Plant eligibility requires at least one case.")
    contract = prepared["config"]["plant_eligibility_contract"]
    records: list[dict[str, Any]] = []
    for case in cases.to_dict(orient="records"):
        if bool(case.get("final_test_case")):
            raise BehaviouralValidationError(
                "A final-week case cannot enter the plant eligibility gate."
            )
        bundle, _ = _bundle_for_case(prepared, case)
        point = np.asarray(bundle.point_prices, dtype=float)
        if len(point) == 0 or not np.isfinite(point).all():
            raise BehaviouralValidationError(
                f"Plant eligibility has invalid point-price support for {case['case_id']}."
            )
        is_c1 = str(case["configuration"]) == "C1"
        is_responsive = str(case["policy"]) == "responsive"
        nonflat = float(np.ptp(point)) > 1e-9
        crosses_break_even = bool(
            float(np.min(point)) < VN25_BREAK_EVEN_EUR_PER_MWH - 1e-9
            and float(np.max(point)) > VN25_BREAK_EVEN_EUR_PER_MWH + 1e-9
        )
        eaf_eligible = bool(is_c1 and is_responsive and nonflat)
        vn25_eligible = bool(eaf_eligible and crosses_break_even)
        common = {
            "case_id": str(case["case_id"]),
            "phase": str(case["phase"]),
            "profile_id": str(case["profile_id"]),
            "configuration": str(case["configuration"]),
            "policy": str(case["policy"]),
            "arm": str(case["arm"]),
            "market_grid": str(case["granularity"]),
            "determination_stage": "pre_solve",
            "uses_dispatch_or_actual_prices": False,
            "final_test_case": False,
            "point_price_support_sha256": _payload_sha256(
                {
                    "market_grid": bundle.granularity,
                    "timestamps_utc": [item.isoformat() for item in bundle.timestamps_utc],
                    "point_prices": list(bundle.point_prices),
                }
            ),
            "materiality_threshold_contract": contract["materiality_threshold"],
        }

        def add(
            mechanism: str,
            applicable: bool,
            reason: str,
            evidence: str,
            *,
            directional_gate: bool,
        ) -> None:
            records.append(
                {
                    **common,
                    "mechanism": mechanism,
                    "eligibility_status": (
                        "applicable" if applicable else "not_applicable"
                    ),
                    "hard_directional_gate": bool(applicable and directional_gate),
                    "binding_reason": reason,
                    "pre_solve_evidence": evidence,
                }
            )

        add(
            "eaf_heat_timing",
            eaf_eligible,
            (
                "c1_responsive_nonflat_profile_with_frozen_heat_timing_contract"
                if eaf_eligible
                else "requires_c1_responsive_nonflat_profile"
            ),
            (
                "C1 exposes endogenous three-QH heat starts on a maintenance-free day; "
                "the price profile is evaluated ex ante for non-flat support."
            ),
            directional_gate=True,
        )
        add(
            "drp_dri_buffer_support",
            eaf_eligible,
            (
                "inherits_eligible_c1_eaf_timing"
                if eaf_eligible
                else "requires_eligible_eaf_timing"
            ),
            "DRP and the DRI buffer share the frozen C1 material and terminal contract.",
            directional_gate=True,
        )
        add(
            "drp_eaf_vs_bf_bof_route_substitution",
            False,
            str(contract["route_substitution_not_applicable_reason"]),
            "The frozen one-day route quotas do not establish substitution headroom.",
            directional_gate=False,
        )
        add(
            "vn25_generation",
            vn25_eligible,
            (
                "c1_responsive_profile_crosses_frozen_vn25_break_even"
                if vn25_eligible
                else "requires_c1_responsive_profile_crossing_vn25_break_even"
            ),
            (
                f"Ex-ante point support crosses {VN25_BREAK_EVEN_EUR_PER_MWH:.12g} "
                "EUR/MWh and the frozen VN25 abstraction retains bounded headroom."
            ),
            directional_gate=True,
        )
        for mechanism in ("boiler_wag_allocation", "wag_flare"):
            add(
                mechanism,
                vn25_eligible,
                (
                    "inherits_eligible_vn25_wag_allocation"
                    if vn25_eligible
                    else "requires_eligible_vn25_wag_allocation"
                ),
                "Boiler and flare applicability is frozen from VN25 eligibility before solve.",
                directional_gate=True,
            )
        add(
            "ij01_no_direct_price_response",
            True,
            "frozen_non_price_responsive_asset_check",
            "IJ01 is monitored for zero named NG and no direct response claim.",
            directional_gate=False,
        )
        add(
            "hsm_dsp_output_preservation",
            True,
            "frozen_output_preservation_check",
            "HSM/DSP output and production requirements are common across price profiles.",
            directional_gate=False,
        )
    if any(
        row["eligibility_status"] == "not_applicable"
        and not str(row["binding_reason"]).strip()
        for row in records
    ):
        raise BehaviouralValidationError(
            "Every not-applicable plant mechanism needs a pre-solve binding reason."
        )
    return records


def _bundle_actual_hash(bundle: Any, actual: Any) -> str:
    return _payload_sha256(
        {
            "delivery_day": bundle.delivery_day.isoformat(),
            "timestamps": [item.isoformat() for item in bundle.timestamps_utc],
            "point_prices": list(bundle.point_prices),
            "scenario_prices": bundle.scenario_prices,
            "scenario_probabilities": bundle.scenario_probabilities,
            "actual_prices": list(actual.prices),
        }
    )


def _physical_initial_state_sha256(initial_state: SteelRollingState) -> str:
    payload = dict(initial_state.snapshot())
    payload.pop("episode_id", None)
    return _payload_sha256(payload)


def _comparison_expected_objective_eur(
    plan: SteelBidPlan,
    bundle: SteelPriceInformationBundle,
) -> float | None:
    if plan.policy in {"H-S10", "QH-S10"}:
        return float(plan.solver["expected_cost_reconstructed_eur"])
    if plan.policy != "price-insensitive":
        return None
    if len(bundle.scenario_prices) != 10:
        raise BehaviouralValidationError(
            "Price-insensitive common-support revaluation requires S10."
        )
    dispatch = pd.DataFrame(plan.scenario_dispatch)
    dispatch = dispatch[dispatch["economic_horizon_active"].astype(bool)].copy()
    if dispatch.empty or dispatch["scenario_id"].astype(str).nunique() != 1:
        raise BehaviouralValidationError(
            "Price-insensitive revaluation requires one frozen physical path."
        )
    grouped = (
        dispatch.groupby("market_interval_index", as_index=True)
        .agg(
            planned_import_mwh=("planned_net_grid_import_mwh", "sum"),
            planning_price_eur_per_mwh=("scenario_price_eur_per_mwh", "first"),
        )
        .sort_index()
    )
    expected_index = list(range(len(bundle.timestamps_utc)))
    if [int(item) for item in grouped.index] != expected_index:
        raise BehaviouralValidationError(
            "Price-insensitive dispatch does not cover the complete market grid."
        )
    imports = grouped["planned_import_mwh"].astype(float).to_numpy()
    planning_prices = grouped["planning_price_eur_per_mwh"].astype(float).to_numpy()
    expected_prices = np.zeros(len(expected_index), dtype=float)
    for scenario_id, probability in bundle.scenario_probabilities.items():
        expected_prices += float(probability) * np.asarray(
            bundle.scenario_prices[str(scenario_id)], dtype=float
        )
    reconstructed = float(plan.solver["expected_cost_reconstructed_eur"])
    non_price_cost = reconstructed - float(np.dot(imports, planning_prices))
    return non_price_cost + float(np.dot(imports, expected_prices))


def _load_reusable_planning_cache(
    path: str | Path,
    *,
    bundle: Any,
    actual: Any,
    configuration: str,
    policy: str,
) -> SteelBidPlan:
    cache = _resolve(path)
    with gzip.open(cache, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("input_sha256") != _bundle_actual_hash(bundle, actual):
        raise BehaviouralValidationError("Reusable plan input hash changed.")
    if (
        payload.get("configuration_id") != configuration
        or payload.get("policy") != policy
        or payload.get("delivery_day") != bundle.delivery_day.isoformat()
    ):
        raise BehaviouralValidationError("Reusable plan case contract changed.")
    solver = dict(payload["solver"])
    if (
        solver.get("expected_cost_optimality_proof")
        != "frozen_parent_optimum_plus_current_feasibility_proof"
        or solver.get("bid_curve_canonicalisation_performed") is not True
        or solver.get("bid_curve_canonical_tiebreak")
        != "minimum_total_volume_then_highest_willingness_price"
    ):
        raise BehaviouralValidationError("Reusable plan proof/canonical bid changed.")
    return SteelBidPlan(
        policy=str(payload["policy"]),
        configuration_id=str(payload["configuration_id"]),
        delivery_day=date.fromisoformat(str(payload["delivery_day"])),
        bids=[dict(row) for row in payload["bids"]],
        scenario_dispatch=[dict(row) for row in payload["scenario_dispatch"]],
        solver=solver,
        expected_cost_eur=float(payload["expected_cost_eur"]),
        input_scenario_ids=tuple(str(item) for item in payload["input_scenario_ids"]),
        input_probabilities={
            str(key): float(value)
            for key, value in payload["input_probabilities"].items()
        },
    )


def _check_row(
    case: Mapping[str, Any],
    check_id: str,
    passed: bool,
    observed: Any,
    expected: Any,
    *,
    hard_gate: bool = True,
    family: str = "technical",
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "phase": case["phase"],
        "configuration": case["configuration"],
        "policy": case["policy"],
        "arm": case["arm"],
        "check_family": family,
        "check_id": check_id,
        "hard_gate": hard_gate,
        "observed": observed,
        "expected": expected,
        "status": "pass" if passed else "fail",
    }


def _within_money_tolerance(error_eur: float, tolerance_eur: float) -> bool:
    """Match the Phase 6D reconstruction gate's floating-point slack."""
    return abs(float(error_eur)) <= float(tolerance_eur) + MONEY_NUMERICAL_SLACK_EUR


def _max_abs(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    return max((abs(float(row.get(field) or 0.0)) for row in rows), default=0.0)


def _physical_checks(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
    bundle: SteelPriceInformationBundle,
    actual: SteelActualPriceBundle,
    plan: Any,
    clearing: Any,
    redispatch: Any,
    initial_state: SteelRollingState,
) -> list[dict[str, Any]]:
    config = prepared["config"]
    gate = config["gate"]
    money = float(gate["money_tolerance_eur"])
    energy = float(gate["energy_tolerance_mwh"])
    material = float(gate["material_tolerance_t"])
    probability = float(gate["probability_tolerance"])
    progress_tolerance = float(gate["production_progress_tolerance_t"])
    rows = redispatch.physical_intervals
    checks: list[dict[str, Any]] = []

    def add(
        check_id: str,
        passed: bool,
        observed: Any,
        expected: Any,
        *,
        hard_gate: bool = True,
    ) -> None:
        checks.append(
            _check_row(
                case,
                check_id,
                passed,
                observed,
                expected,
                hard_gate=hard_gate,
            )
        )

    timestamps = pd.DatetimeIndex(bundle.timestamps_utc)
    local = timestamps.tz_convert(LOCAL_TZ)
    add(
        "d_minus_1_information_cutoff",
        bundle.forecast_origin_utc == expected_origin_utc(bundle.delivery_day),
        bundle.forecast_origin_utc.isoformat(),
        expected_origin_utc(bundle.delivery_day).isoformat(),
    )
    add(
        "actual_free_planning_bundle",
        not any("actual" in key.lower() for key in bundle.__dict__),
        sorted(bundle.__dict__),
        "no actual-labelled field",
    )
    expected_intervals = 24 if bundle.granularity == "hourly" else 96
    add(
        "complete_dst_aware_delivery_grid",
        len(timestamps) == expected_intervals
        and timestamps.nunique() == expected_intervals
        and set(local.date) == {bundle.delivery_day},
        len(timestamps),
        expected_intervals,
    )
    add(
        "exact_s10_input",
        len(bundle.scenario_prices) == 10,
        len(bundle.scenario_prices),
        10,
    )
    mass = float(sum(bundle.scenario_probabilities.values()))
    add("scenario_probability_mass", abs(mass - 1.0) <= probability, mass, 1.0)
    unique_paths = len({tuple(values) for values in bundle.scenario_prices.values()})
    add("unique_complete_scenario_paths", unique_paths == 10, unique_paths, 10)
    add(
        "scenario_support_complete",
        all(len(values) == expected_intervals for values in bundle.scenario_prices.values()),
        sorted({len(values) for values in bundle.scenario_prices.values()}),
        [expected_intervals],
    )
    add(
        "v1_expected_cost_incumbent_active",
        plan.solver["planning_physical_tiebreak_mode"] == EXPECTED_COST_INCUMBENT,
        plan.solver["planning_physical_tiebreak_mode"],
        EXPECTED_COST_INCUMBENT,
    )
    add(
        "planning_physical_tiebreak_skipped",
        plan.solver["physical_tiebreak_solve_performed"] is False,
        plan.solver["physical_tiebreak_solve_performed"],
        False,
    )
    add(
        "planning_production_optimum_registered",
        math.isfinite(float(plan.solver["production_progress_optimum_t"])),
        plan.solver["production_progress_optimum_t"],
        "finite",
    )
    add(
        "planning_expected_cost_optimum_registered",
        math.isfinite(float(plan.solver["expected_cost_optimum_eur"])),
        plan.solver["expected_cost_optimum_eur"],
        "finite",
    )
    selected_cost_gap = float(plan.solver["selected_incumbent_expected_cost_eur"]) - float(
        plan.solver["expected_cost_optimum_eur"]
    )
    add(
        "selected_incumbent_within_cost_tolerance",
        selected_cost_gap <= money + MONEY_NUMERICAL_SLACK_EUR,
        selected_cost_gap,
        f"<= {money}",
    )
    redispatch_tiers = {str(row["tier"]) for row in redispatch.solver["tier_solves"]}
    add(
        "redispatch_physical_tiebreak_executed",
        bool(redispatch.solver["physical_tiebreak_solve_performed"])
        and REDISPATCH_PHYSICAL_TIEBREAK_TIER in redispatch_tiers,
        sorted(redispatch_tiers),
        REDISPATCH_PHYSICAL_TIEBREAK_TIER,
    )
    all_solver_rows = [plan.solver, redispatch.solver]
    def tier_accepted(tier: Mapping[str, Any]) -> bool:
        return str(tier["termination_condition"]).lower() == "optimal" or bool(
            tier.get("epsilon_optimal_accepted", False)
        )

    all_optimal_or_epsilon = all(
        (
            str(record["termination_condition"]).lower() == "optimal"
            or bool(record.get("economic_epsilon_optimal_accepted", False))
        )
        and all(tier_accepted(tier) for tier in record["tier_solves"])
        for record in all_solver_rows
    )
    add(
        "all_solver_tiers_strict_or_epsilon_optimal",
        all_optimal_or_epsilon,
        all_optimal_or_epsilon,
        True,
    )
    settings_ok = all(
        int(record["solver_seed"]) == 0
        and float(record["solver_time_limit_seconds"]) == 900.0
        and float(record["solver_mip_gap_limit"]) == 0.001
        and float(record["solver_economic_mip_gap_limit"]) == 0.002
        and float(record["solver_integer_feasibility_tolerance"]) == 1e-9
        and bool(record.get("solver_version"))
        for record in all_solver_rows
    )
    add("frozen_solver_settings_and_version", settings_ok, settings_ok, True)
    progress_max = max(
        abs(float(plan.solver["production_progress_optimum_t"])),
        abs(float(redispatch.solver["production_progress_optimum_t"])),
    )
    add(
        "quota_and_production_progress",
        progress_max <= progress_tolerance,
        progress_max,
        f"<= {progress_tolerance}",
    )
    add(
        "physical_execution_interval_count",
        len(rows) == PHYSICAL_INTERVALS_PER_DAY,
        len(rows),
        PHYSICAL_INTERVALS_PER_DAY,
    )
    add(
        "carrier_specific_wag_balances",
        max(
            _max_abs(rows, "bfg_balance_residual_mwh"),
            _max_abs(rows, "cog_balance_residual_mwh"),
            _max_abs(rows, "bofg_balance_residual_mwh"),
        )
        <= energy,
        max(
            _max_abs(rows, "bfg_balance_residual_mwh"),
            _max_abs(rows, "cog_balance_residual_mwh"),
            _max_abs(rows, "bofg_balance_residual_mwh"),
        ),
        f"<= {energy}",
    )
    add(
        "named_ng_nonnegative",
        min(float(row["total_named_ng_procurement_mwh"]) for row in rows) >= -energy,
        min(float(row["total_named_ng_procurement_mwh"]) for row in rows),
        ">= 0",
    )
    steam_residual = max(
        abs(
            float(row["steam_15bar_supply_t"])
            + float(row["steam_15bar_unserved_t"])
            - float(row["steam_15bar_demand_t"])
            - float(row["steam_15bar_spill_t"])
        )
        for row in rows
    )
    add("steam_balance", steam_residual <= material, steam_residual, f"<= {material}")
    add(
        "no_unserved_steam",
        _max_abs(rows, "steam_15bar_unserved_t") <= material,
        _max_abs(rows, "steam_15bar_unserved_t"),
        0.0,
    )
    add(
        "electricity_identity",
        _max_abs(rows, "gross_site_electricity_identity_residual_mwh") <= energy,
        _max_abs(rows, "gross_site_electricity_identity_residual_mwh"),
        f"<= {energy}",
    )
    add(
        "no_export",
        _max_abs(rows, "gross_grid_export_mwh") <= energy,
        _max_abs(rows, "gross_grid_export_mwh"),
        0.0,
    )
    add(
        "c0_bof_material_balance",
        _max_abs(rows, "c0_bof_material_balance_residual_t") <= material,
        _max_abs(rows, "c0_bof_material_balance_residual_t"),
        f"<= {material}",
    )
    if case["configuration"] == "C1":
        origin_residual = max(
            max(
                abs(
                    float(row["bof_to_hsm_slab_t"])
                    + float(row["bof_to_dsp_liquid_steel_t"])
                    - float(row["bof_crude_steel_output_t"])
                ),
                abs(
                    float(row["eaf_to_hsm_slab_t"])
                    + float(row["eaf_to_dsp_liquid_steel_t"])
                    - float(row["eaf_liquid_steel_output_t"])
                ),
                abs(
                    float(row["cold_slab_draw_to_hsm_t"])
                    + float(row["eaf_to_hsm_slab_t"])
                    + float(row["imported_slab_to_hsm_t"])
                    - float(row["hot_strip_mill_t"])
                ),
            )
            for row in rows
        )
        add("c1_origin_balances", origin_residual <= material, origin_residual, f"<= {material}")
    inventory_min = min(
        float(row[field])
        for row in rows
        for field in (
            "coke_inventory_t",
            "sinter_inventory_t",
            "hot_iron_inventory_t",
            "cold_slab_inventory_t",
            "dri_inventory_t",
        )
    )
    add("executed_inventory_nonnegative", inventory_min >= -material, inventory_min, ">= 0")
    add(
        "all_horizon_inventory_bounds",
        float(redispatch.solver["inventory_bound_max_violation_t"]) <= material,
        redispatch.solver["inventory_bound_max_violation_t"],
        f"<= {material}",
    )
    add(
        "terminal_condition_activation_matches_frozen_nonterminal_policy",
        redispatch.solver["terminal_inventory_band_active"] is False
        and redispatch.solver["terminal_condition_policy"]
        == "non_terminal_rolling_day_no_terminal_band",
        {
            "active": redispatch.solver["terminal_inventory_band_active"],
            "policy": redispatch.solver["terminal_condition_policy"],
            "reference_band_distance_t_not_a_violation": redispatch.solver[
                "terminal_inventory_reference_max_distance_t"
            ],
        },
        "same frozen non-terminal rolling-day policy in every paired case",
    )
    state = redispatch.next_state
    handoff_ok = bool(
        state.executed_hours == initial_state.executed_hours + 24
        and state.executed_intervals == initial_state.executed_intervals + 96
        and state.last_executed_timestamp_utc == rows[-1]["target_timestamp_utc"]
    )
    add("daily_state_handoff", handoff_ok, state.snapshot(), "24h/96 interval advance")
    bid_frame = pd.DataFrame(plan.bids)
    bid_ok = True
    for _, group in bid_frame.groupby("market_interval_index"):
        ordered = group.sort_values("bid_price_eur_per_mwh")
        prices = tuple(ordered["bid_price_eur_per_mwh"].astype(float))
        if prices != STEEL_BID_GRID or (ordered["incremental_bid_volume_mwh"] < -energy).any():
            bid_ok = False
            break
        cumulative = [
            float(
                ordered.loc[
                    ordered["bid_price_eur_per_mwh"].ge(threshold),
                    "incremental_bid_volume_mwh",
                ].sum()
            )
            for threshold in STEEL_BID_GRID
        ]
        if any(cumulative[index] + energy < cumulative[index + 1] for index in range(len(cumulative) - 1)):
            bid_ok = False
            break
    add("bid_monotonicity_and_grid_contract", bid_ok, bid_ok, True)
    reconstructed_clearing = []
    for market_interval_index, row in enumerate(clearing.hourly):
        interval_bids = bid_frame[
            bid_frame["market_interval_index"].eq(market_interval_index)
        ]
        reconstructed_clearing.append(
            float(
                interval_bids.loc[
                    interval_bids["bid_price_eur_per_mwh"].ge(
                        float(row["realised_price_eur_per_mwh"])
                    ),
                    "incremental_bid_volume_mwh",
                ].sum()
            )
            - float(row["cleared_energy_mwh"])
        )
    clearing_error = max((abs(value) for value in reconstructed_clearing), default=0.0)
    add("clearing_reconstruction", clearing_error <= energy, clearing_error, f"<= {energy}")
    settlement_reconstructed = sum(
        float(row["allocated_pay_as_cleared_settlement_eur"])
        for row in rows
    )
    settlement_error = settlement_reconstructed - float(clearing.settlement_cost_eur)
    add(
        "settlement_reconstruction",
        _within_money_tolerance(settlement_error, money),
        settlement_error,
        0.0,
    )
    imbalance_volume = sum(
        float(row["allocated_absolute_imbalance_mwh"])
        for row in rows
    )
    imbalance_penalty = sum(
        float(row["allocated_imbalance_penalty_eur"])
        for row in rows
    )
    configured_penalty = float(
        prepared["config"]["frozen_contract"]["execution_recourse"][
            "penalty_eur_per_mwh"
        ]
    )
    add(
        "imbalance_penalty_reconstruction",
        _within_money_tolerance(
            imbalance_penalty - configured_penalty * imbalance_volume, money
        ),
        imbalance_penalty - configured_penalty * imbalance_volume,
        0.0,
    )
    objective_error = float(plan.solver["expected_cost_reconstruction_error_eur"])
    add(
        "expected_objective_reconstruction",
        _within_money_tolerance(objective_error, money),
        objective_error,
        0.0,
    )
    add(
        "maintenance_free_contract",
        not prepared["representative"]["experiment_contract"][
            "weekly_eaf_maintenance_active"
        ]
        and not prepared["representative"]["experiment_contract"][
            "annual_outage_active"
        ],
        "maintenance_free_normal_operation_day",
        True,
    )
    trajectory = {
        "market_granularity": bundle.granularity,
        "configuration_id": CONFIGURATION_IDS[str(case["configuration"])],
        "policy": _policy_name(case),
        "physical_dispatch": rows,
        "state": {"settlement_cost_eur": clearing.settlement_cost_eur},
        "solver": [plan.solver, redispatch.solver],
    }
    if case["configuration"] == "C1":
        trajectory["state"].update(
            {
                "eaf_unfinished_start_lag1": state.eaf_start_lag1,
                "eaf_unfinished_start_lag2": state.eaf_start_lag2,
            }
        )
    for existing in validate_phase6d_trajectory(trajectory):
        add(
            f"phase6d::{existing['check_id']}",
            existing["status"] == "pass",
            existing["observed"],
            existing["expected"],
        )
    return checks


def _safe_correlation(left: pd.Series, right: pd.Series, *, rank: bool) -> float | None:
    valid = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(valid) < 3 or valid["left"].nunique() < 2 or valid["right"].nunique() < 2:
        return None
    if rank:
        return float(valid["left"].rank().corr(valid["right"].rank()))
    return float(valid["left"].corr(valid["right"]))


def dri_change_correlations(
    hourly_prices: Sequence[float],
    hourly_inventory_levels: Sequence[float],
    *,
    initial_inventory: float,
) -> tuple[float | None, float | None]:
    """Correlate price with inventory changes, never absolute inventory levels."""

    price = pd.Series(hourly_prices, dtype=float)
    inventory = pd.Series(hourly_inventory_levels, dtype=float)
    previous = inventory.shift(1)
    if not inventory.empty:
        previous.iloc[0] = float(initial_inventory)
    delta = inventory - previous
    return (
        _safe_correlation(price, delta, rank=False),
        _safe_correlation(price, delta, rank=True),
    )


def bf_own_capacity_utilisation(
    throughput: Sequence[float], capacities: Sequence[float | None]
) -> float | None:
    """Return BF utilisation using the same BF object's represented capacity."""

    frame = pd.DataFrame({"throughput": throughput, "capacity": capacities})
    frame["capacity"] = pd.to_numeric(frame["capacity"], errors="coerce")
    valid = frame[frame["capacity"].gt(0.0)]
    return (
        float((valid["throughput"] / valid["capacity"]).mean())
        if not valid.empty
        else None
    )


def _case_metrics(
    case: Mapping[str, Any],
    bundle: SteelPriceInformationBundle,
    actual: SteelActualPriceBundle,
    plan: Any,
    clearing: Any,
    redispatch: Any,
    initial_state: SteelRollingState,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, float | None]]:
    dispatch = pd.DataFrame(redispatch.physical_intervals).sort_values(
        "physical_interval_index"
    )
    realised = dispatch["realised_price_eur_per_mwh"].astype(float).to_numpy()
    if bundle.granularity == "hourly":
        point_qh = np.repeat(np.asarray(bundle.point_prices, dtype=float), 4)
    else:
        point_qh = np.asarray(bundle.point_prices, dtype=float)
    arc = dispatch["eaf_arc_electricity_mwh"].astype(float).to_numpy()
    eaf_total = dispatch["eaf_total_electricity_mwh"].astype(float).to_numpy()
    starts = dispatch["eaf_heat_start"].astype(float).to_numpy()
    first = np.arange(len(dispatch)) < 48
    second = ~first
    cheap = point_qh < 160.0 - 1e-9
    expensive = point_qh > 160.0 + 1e-9
    negative = point_qh < 0.0
    above_vn25_break_even = point_qh > VN25_BREAK_EVEN_EUR_PER_MWH + 1e-9
    below_vn25_break_even = point_qh < VN25_BREAK_EVEN_EUR_PER_MWH - 1e-9
    eaf_sum = float(np.sum(eaf_total))
    capture = (
        float(np.sum(realised * eaf_total) / eaf_sum) if eaf_sum > 1e-12 else None
    )
    mean_price = float(np.mean(realised))
    local_hours = pd.to_datetime(
        dispatch["target_timestamp_utc"], utc=True
    ).dt.tz_convert(LOCAL_TZ).dt.floor("h")
    hourly = pd.DataFrame(
        {
            "hour": local_hours,
            "price": realised,
            "dri_inventory": dispatch["dri_inventory_t"].astype(float),
        }
    ).groupby("hour", as_index=False).agg(
        price=("price", "mean"), dri_inventory=("dri_inventory", "last")
    )
    initial_dri = float(initial_state.inventory_overrides.get("dri_buffer_initial_t", 0.0))
    hourly["dri_inventory_previous"] = hourly["dri_inventory"].shift(1)
    if not hourly.empty:
        hourly.loc[hourly.index[0], "dri_inventory_previous"] = initial_dri
    hourly["delta_dri_inventory_t"] = (
        hourly["dri_inventory"] - hourly["dri_inventory_previous"]
    )
    dri_pearson, dri_spearman = dri_change_correlations(
        hourly["price"],
        hourly["dri_inventory"],
        initial_inventory=initial_dri,
    )
    bf = dispatch["blast_furnace_6_t"].astype(float)
    capacity = pd.to_numeric(
        dispatch["blast_furnace_6_capacity_t"], errors="coerce"
    )
    relevant_flexible = eaf_sum if case["configuration"] == "C1" else float(
        dispatch["gross_electricity_mwh"].sum()
        - dispatch["site_background_electricity_mwh"].sum()
    )
    response_threshold = max(1.0, 0.001 * abs(relevant_flexible))
    planned_execution = pd.DataFrame(plan.scenario_dispatch)
    planned_execution = planned_execution[
        planned_execution["economic_horizon_active"].astype(bool)
    ]
    planned_import = float(
        (
            planned_execution["planned_net_grid_import_mwh"].astype(float)
            * planned_execution["scenario_probability"].astype(float)
        ).sum()
    )
    comparison_expected_objective = _comparison_expected_objective_eur(plan, bundle)
    result = {
        "case_id": case["case_id"],
        "phase": case["phase"],
        "profile_id": case["profile_id"],
        "delivery_day": case["delivery_day"],
        "configuration": case["configuration"],
        "policy": case["policy"],
        "arm": case["arm"],
        "granularity": case["granularity"],
        "forecast_scenario_input_sha256": _payload_sha256(
            {
                "point": bundle.point_prices,
                "scenarios": bundle.scenario_prices,
                "probabilities": bundle.scenario_probabilities,
            }
        ),
        "initial_state_sha256": _payload_sha256(initial_state.snapshot()),
        "physical_initial_state_sha256": _physical_initial_state_sha256(initial_state),
        "terminal_contract_sha256": _payload_sha256(
            redispatch.solver["terminal_inventory_observed_json"]
        ),
        "expected_objective_eur": float(plan.expected_cost_eur),
        "common_s10_expected_objective_eur": comparison_expected_objective,
        "common_expected_objective_basis": (
            "input_s10"
            if comparison_expected_objective is not None
            else "isolated_actual_oracle"
        ),
        "planned_expected_net_import_mwh": planned_import,
        "realised_settlement_eur": float(clearing.settlement_cost_eur),
        "realised_other_represented_cost_eur": float(
            redispatch.other_represented_cost_eur
        ),
        "imbalance_penalty_eur": float(redispatch.imbalance_penalty_eur),
        "absolute_imbalance_mwh": float(redispatch.absolute_imbalance_mwh),
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
        "e_program_compliant": (
            float(redispatch.absolute_imbalance_mwh) <= ENERGY_TOLERANCE_MWH
        ),
        "realised_total_represented_cost_eur": float(
            clearing.settlement_cost_eur
            + redispatch.other_represented_cost_eur
            + redispatch.imbalance_penalty_eur
        ),
        "produced_t": float(redispatch.produced_t),
        "net_grid_import_mwh": float(dispatch["redispatched_net_grid_import_mwh"].sum()),
        "net_grid_import_first_12h_mwh": float(
            dispatch.loc[first, "redispatched_net_grid_import_mwh"].sum()
        ),
        "net_grid_import_second_12h_mwh": float(
            dispatch.loc[second, "redispatched_net_grid_import_mwh"].sum()
        ),
        "gross_electricity_mwh": float(dispatch["gross_electricity_mwh"].sum()),
        "internal_generation_mwh": float(dispatch["total_internal_generation_mwh"].sum()),
        "named_ng_mwh": float(dispatch["total_named_ng_procurement_mwh"].sum()),
        "site_background_electricity_mwh": float(
            dispatch["site_background_electricity_mwh"].sum()
        ),
        "site_baseload_ng_mwh": float(dispatch["site_baseload_ng_mwh"].sum()),
        "residual_steam_t": float(dispatch["residual_steam_15bar_demand_t"].sum()),
        "eaf_heat_starts": float(np.sum(starts)),
        "eaf_heat_taps": float(dispatch["eaf_tap"].astype(float).sum()),
        "eaf_arc_mwh": float(np.sum(arc)),
        "eaf_total_electricity_mwh": eaf_sum,
        "eaf_liquid_steel_output_t": float(
            dispatch["eaf_liquid_steel_output_t"].sum()
        ),
        "eaf_dri_input_t": float(dispatch["eaf_dri_input_t"].sum()),
        "eaf_scrap_input_t": float(dispatch["eaf_scrap_input_t"].sum()),
        "eaf_named_ng_mwh": float(dispatch["eaf_named_ng_mwh"].sum()),
        "eaf_arc_first_12h_mwh": float(np.sum(arc[first])),
        "eaf_arc_second_12h_mwh": float(np.sum(arc[second])),
        "eaf_arc_cheap_mwh": float(np.sum(arc[cheap])),
        "eaf_arc_expensive_mwh": float(np.sum(arc[expensive])),
        "eaf_heat_starts_cheap": float(np.sum(starts[cheap])),
        "eaf_heat_starts_expensive": float(np.sum(starts[expensive])),
        "eaf_heat_starts_negative": float(np.sum(starts[negative])),
        "eaf_capture_price_eur_per_mwh": capture,
        "mean_market_price_eur_per_mwh": mean_price,
        "capture_price_discount_eur_per_mwh": (
            mean_price - capture if capture is not None else None
        ),
        "eaf_cheap_share": (
            float(np.sum(eaf_total[cheap]) / eaf_sum) if eaf_sum > 1e-12 else None
        ),
        "eaf_expensive_share": (
            float(np.sum(eaf_total[expensive]) / eaf_sum)
            if eaf_sum > 1e-12
            else None
        ),
        "dri_inventory_end_t": float(hourly["dri_inventory"].iloc[-1]),
        "dri_inventory_change_t": float(hourly["delta_dri_inventory_t"].sum()),
        "drp_pellet_input_t": float(dispatch["drp_pellet_input_t"].sum()),
        "drp_electricity_mwh": float(dispatch["drp_electricity_mwh"].sum()),
        "drp_named_ng_mwh": float(dispatch["drp_named_ng_mwh"].sum()),
        "price_delta_dri_pearson": dri_pearson,
        "price_delta_dri_spearman": dri_spearman,
        "bf6_throughput_t": float(bf.sum()),
        "bf6_own_capacity_t": float(capacity.sum(skipna=True)),
        "bf6_mean_own_capacity_utilisation": bf_own_capacity_utilisation(
            bf, capacity
        ),
        "bf6_throughput_std_t_per_qh": float(bf.std(ddof=0)),
        "bf6_max_abs_ramp_t_per_qh": float(bf.diff().abs().max() or 0.0),
        "bf6_off_intervals": int((bf <= 1e-9).sum()),
        "coke_inventory_end_t": float(dispatch["coke_inventory_t"].iloc[-1]),
        "sinter_inventory_end_t": float(dispatch["sinter_inventory_t"].iloc[-1]),
        "hot_iron_inventory_end_t": float(dispatch["hot_iron_inventory_t"].iloc[-1]),
        "bof_throughput_t": float(dispatch["basic_oxygen_furnace_t"].sum()),
        "hsm_throughput_t": float(dispatch["hot_strip_mill_t"].sum()),
        "dsp_output_t": float(dispatch["dsp_final_product_output_t"].sum()),
        "vn25_wag_mwh": float(dispatch["vn25_wag_fuel_mwh"].sum()),
        "vn25_named_ng_mwh": float(dispatch["vn25_named_ng_mwh"].sum()),
        "vn25_electricity_mwh": float(dispatch["vn25_electricity_mwh"].sum()),
        "vn25_total_fuel_mwh": float(dispatch["vn25_total_fuel_mwh"].sum()),
        "vn25_break_even_eur_per_mwh": VN25_BREAK_EVEN_EUR_PER_MWH,
        "vn25_above_break_even_interval_count": int(above_vn25_break_even.sum()),
        "vn25_below_break_even_interval_count": int(below_vn25_break_even.sum()),
        "vn25_electricity_above_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[above_vn25_break_even, "vn25_electricity_mwh"].mean())
            if above_vn25_break_even.any()
            else None
        ),
        "vn25_electricity_below_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[below_vn25_break_even, "vn25_electricity_mwh"].mean())
            if below_vn25_break_even.any()
            else None
        ),
        "net_import_above_break_even_mean_mwh_per_qh": (
            float(
                dispatch.loc[
                    above_vn25_break_even, "redispatched_net_grid_import_mwh"
                ].mean()
            )
            if above_vn25_break_even.any()
            else None
        ),
        "net_import_below_break_even_mean_mwh_per_qh": (
            float(
                dispatch.loc[
                    below_vn25_break_even, "redispatched_net_grid_import_mwh"
                ].mean()
            )
            if below_vn25_break_even.any()
            else None
        ),
        "vn25_wag_above_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[above_vn25_break_even, "vn25_wag_fuel_mwh"].mean())
            if above_vn25_break_even.any()
            else None
        ),
        "vn25_wag_below_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[below_vn25_break_even, "vn25_wag_fuel_mwh"].mean())
            if below_vn25_break_even.any()
            else None
        ),
        "boiler_named_ng_above_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[above_vn25_break_even, "boiler_named_ng_mwh"].mean())
            if above_vn25_break_even.any()
            else None
        ),
        "boiler_named_ng_below_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[below_vn25_break_even, "boiler_named_ng_mwh"].mean())
            if below_vn25_break_even.any()
            else None
        ),
        "flare_above_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[above_vn25_break_even, "wag_flared_mwh"].mean())
            if above_vn25_break_even.any()
            else None
        ),
        "flare_below_break_even_mean_mwh_per_qh": (
            float(dispatch.loc[below_vn25_break_even, "wag_flared_mwh"].mean())
            if below_vn25_break_even.any()
            else None
        ),
        "vn25_capacity_utilisation": (
            float(
                dispatch["vn25_electricity_mwh"].sum()
                / (dispatch["vn25_electric_capacity_mw"].iloc[0] * 24.0)
            )
            if float(dispatch["vn25_electric_capacity_mw"].iloc[0]) > 0.0
            else None
        ),
        "ij01_active_intervals": int((dispatch["ij01_total_fuel_mwh"] > 1e-9).sum()),
        "ij01_wag_mwh": float(dispatch["ij01_wag_fuel_mwh"].sum()),
        "ij01_named_ng_mwh": float(dispatch["ij01_named_ng_mwh"].sum()),
        "boiler_bfg_mwh": float(dispatch["boiler_bfg_mwh"].sum()),
        "boiler_cog_mwh": float(dispatch["boiler_cog_mwh"].sum()),
        "boiler_named_ng_mwh": float(dispatch["boiler_named_ng_mwh"].sum()),
        "steam_demand_t": float(dispatch["steam_15bar_demand_t"].sum()),
        "steam_supply_t": float(dispatch["steam_15bar_supply_t"].sum()),
        "steam_spill_t": float(dispatch["steam_15bar_spill_t"].sum()),
        "steam_unserved_t": float(dispatch["steam_15bar_unserved_t"].sum()),
        "flare_mwh": float(dispatch["wag_flared_mwh"].sum()),
        "response_materiality_threshold_mwh": response_threshold,
        "net_import_mwh_per_t": float(
            dispatch["redispatched_net_grid_import_mwh"].sum()
            / redispatch.produced_t
        )
        if redispatch.produced_t > 1e-12
        else None,
        "eaf_arc_mwh_per_t": float(np.sum(arc) / redispatch.produced_t)
        if redispatch.produced_t > 1e-12
        else None,
        "planning_solver_seconds": float(plan.solver["total_solver_seconds"]),
        "redispatch_solver_seconds": float(redispatch.solver["total_solver_seconds"]),
        "planning_variable_count": int(plan.solver["variable_count"]),
        "planning_binary_count": int(plan.solver["binary_count"]),
        "planning_constraint_count": int(plan.solver["constraint_count"]),
        "case_status": "pass",
    }
    metric_units = {
        "expected_objective_eur": "EUR",
        "realised_total_represented_cost_eur": "EUR",
        "imbalance_penalty_eur": "EUR",
        "absolute_imbalance_mwh": "MWh",
        "upward_consumption_imbalance_mwh": "MWh",
        "downward_consumption_imbalance_mwh": "MWh",
        "imbalance_affected_market_interval_count": "count",
        "maximum_market_interval_imbalance_mwh": "MWh",
        "produced_t": "t",
        "net_grid_import_mwh": "MWh",
        "gross_electricity_mwh": "MWh",
        "internal_generation_mwh": "MWh",
        "eaf_arc_mwh": "MWh",
        "eaf_heat_starts": "count",
        "eaf_heat_taps": "count",
        "eaf_liquid_steel_output_t": "t",
        "eaf_dri_input_t": "t",
        "eaf_scrap_input_t": "t",
        "eaf_named_ng_mwh": "MWh_LHV",
        "eaf_arc_first_12h_mwh": "MWh",
        "eaf_arc_second_12h_mwh": "MWh",
        "eaf_capture_price_eur_per_mwh": "EUR/MWh",
        "capture_price_discount_eur_per_mwh": "EUR/MWh",
        "dri_inventory_change_t": "t",
        "drp_pellet_input_t": "t",
        "drp_electricity_mwh": "MWh",
        "drp_named_ng_mwh": "MWh_LHV",
        "price_delta_dri_pearson": "correlation",
        "price_delta_dri_spearman": "correlation",
        "bf6_throughput_t": "t",
        "bf6_mean_own_capacity_utilisation": "fraction",
        "vn25_wag_mwh": "MWh_LHV",
        "vn25_named_ng_mwh": "MWh_LHV",
        "vn25_electricity_mwh": "MWh_e",
        "vn25_total_fuel_mwh": "MWh_LHV",
        "vn25_electricity_above_break_even_mean_mwh_per_qh": "MWh_e/qh",
        "vn25_electricity_below_break_even_mean_mwh_per_qh": "MWh_e/qh",
        "net_import_above_break_even_mean_mwh_per_qh": "MWh_e/qh",
        "net_import_below_break_even_mean_mwh_per_qh": "MWh_e/qh",
        "vn25_wag_above_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "vn25_wag_below_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "boiler_named_ng_above_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "boiler_named_ng_below_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "flare_above_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "flare_below_break_even_mean_mwh_per_qh": "MWh_LHV/qh",
        "boiler_bfg_mwh": "MWh_LHV",
        "boiler_cog_mwh": "MWh_LHV",
        "boiler_named_ng_mwh": "MWh_LHV",
        "steam_demand_t": "t",
        "steam_supply_t": "t",
        "steam_spill_t": "t",
        "steam_unserved_t": "t",
        "flare_mwh": "MWh_LHV",
        "site_background_electricity_mwh": "MWh_e",
        "site_baseload_ng_mwh": "MWh_LHV",
        "residual_steam_t": "t",
    }
    metrics = [
        {
            "case_id": case["case_id"],
            "phase": case["phase"],
            "configuration": case["configuration"],
            "policy": case["policy"],
            "arm": case["arm"],
            "metric_id": metric_id,
            "value": result.get(metric_id),
            "unit": unit,
            "source_interpretation": (
                "directional_not_calibration_target"
                if metric_id
                in {
                    "price_delta_dri_pearson",
                    "price_delta_dri_spearman",
                    "bf6_mean_own_capacity_utilisation",
                }
                else "model_diagnostic"
            ),
        }
        for metric_id, unit in metric_units.items()
    ]
    errors = point_qh - realised

    def conditional_mae(mask: np.ndarray) -> float | None:
        expanded = mask.copy()
        indices = np.flatnonzero(mask)
        for index in indices:
            expanded[max(index - 4, 0) : min(index + 5, len(expanded))] = True
        return float(np.mean(np.abs(errors[expanded]))) if expanded.any() else None

    generator = dispatch["vn25_electricity_mwh"].astype(float).to_numpy()
    activation = (generator > 1e-6) & np.r_[True, generator[:-1] <= 1e-6]
    large_import = dispatch["redispatched_net_grid_import_mwh"].astype(float).to_numpy()
    large_import = large_import >= float(np.quantile(large_import, 0.90))
    conditional = {
        "forecast_errors_around_eaf_starts_eur_per_mwh": conditional_mae(starts > 0.5),
        "forecast_errors_around_generator_activation_eur_per_mwh": conditional_mae(activation),
        "forecast_errors_around_large_net_import_eur_per_mwh": conditional_mae(large_import),
    }
    return result, metrics, conditional


def _run_case(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    bundle, actual = _bundle_for_case(prepared, case)
    delivery_day = date.fromisoformat(str(case["delivery_day"]))
    granularity = str(case["granularity"])
    context = _base_context_config(
        prepared["representative"],
        market_granularity=granularity,
        horizon_hours=24,
    )
    configuration = CONFIGURATION_IDS[str(case["configuration"])]
    policy = _policy_name(case)
    initial_state = SteelRollingState(
        episode_id=str(case["case_id"]), configuration_id=configuration
    )
    oracle = actual if policy == "true-PF" else None
    reusable_cache = prepared["config"].get("reusable_planning_cache", {}).get(
        str(case["case_id"])
    )
    if reusable_cache:
        plan = _load_reusable_planning_cache(
            reusable_cache,
            bundle=bundle,
            actual=actual,
            configuration=configuration,
            policy=policy,
        )
        plan.solver["planning_cache_reused"] = True
        plan.solver["planning_cache_path"] = str(reusable_cache)
    else:
        plan = solve_grouped_da_bid_plan(
            context,
            configuration,
            bundle,
            initial_state,
            policy,
            actuals_oracle=oracle,
            audit_future_paths=True,
            progress_callback=_solver_progress_callback(
                prepared["output"],
                experiment_id=str(case["case_id"]),
                delivery_day=delivery_day,
                solve_stage="planning",
            ),
        )
        plan.solver["planning_cache_reused"] = False
    clearing = clear_hourly_da_bids(plan.bids, actual)
    try:
        redispatch = solve_grouped_actual_redispatch(
            context,
            configuration,
            clearing,
            initial_state,
            actual.prices if policy == "true-PF" else bundle.point_prices,
            oracle_execute_D_cost_only=policy == "true-PF",
            imbalance_penalty_eur_per_mwh=float(
                prepared["config"]["frozen_contract"]["execution_recourse"][
                    "penalty_eur_per_mwh"
                ]
            ),
            progress_callback=_solver_progress_callback(
                prepared["output"],
                experiment_id=str(case["case_id"]),
                delivery_day=delivery_day,
                solve_stage="redispatch",
            ),
        )
    except Phase6DError as exc:
        if "infeasible" not in str(exc).lower():
            raise
        planned = pd.DataFrame(plan.scenario_dispatch)
        planned = planned[planned["economic_horizon_active"].astype(bool)]
        grouped = (
            planned.groupby(["scenario_id", "market_interval_index"])[
                "planned_net_grid_import_mwh"
            ]
            .sum()
            .unstack("market_interval_index")
        )
        realised_import = np.asarray(
            [float(row["cleared_energy_mwh"]) for row in clearing.hourly]
        )
        planned_paths = grouped.to_numpy(dtype=float)
        nearest_rmse = float(
            np.min(np.sqrt(np.mean((planned_paths - realised_import) ** 2, axis=1)))
        )
        outside_interval_envelope = int(
            np.sum(
                (realised_import < np.min(planned_paths, axis=0) - 1e-6)
                | (realised_import > np.max(planned_paths, axis=0) + 1e-6)
            )
        )
        raise BehaviouralRedispatchInfeasible(
            str(exc),
            {
                "failure_stage": "actual_price_bid_clearing_to_physical_redispatch",
                "planning_solver": plan.solver,
                "cleared_import_sha256": _payload_sha256(realised_import.tolist()),
                "cleared_import_total_mwh": float(np.sum(realised_import)),
                "nearest_complete_planned_scenario_import_path_rmse_mwh": nearest_rmse,
                "cleared_intervals_outside_scenario_import_envelope": outside_interval_envelope,
                "interpretation": (
                    "out_of_sample_intervalwise_bid_acceptance_does_not_map_to_a_"
                    "feasible_complete_physical_recourse_path"
                ),
            },
        ) from exc
    checks = _physical_checks(
        prepared,
        case,
        bundle,
        actual,
        plan,
        clearing,
        redispatch,
        initial_state,
    )
    result, metrics, conditional = _case_metrics(
        case,
        bundle,
        actual,
        plan,
        clearing,
        redispatch,
        initial_state,
    )
    _apply_physical_comparison_contract(result, context, configuration)
    hard_failures = [
        row for row in checks if bool(row["hard_gate"]) and row["status"] == "fail"
    ]
    if hard_failures:
        result["case_status"] = "fail"
    solver = {
        "case_id": case["case_id"],
        "planning": plan.solver,
        "redispatch": redispatch.solver,
    }
    return {
        "result": result,
        "metrics": metrics,
        "checks": checks,
        "solver": solver,
        "conditional_forecast_errors": conditional,
    }


def _economic_check(
    check_id: str,
    passed: bool,
    observed: Any,
    expected: Any,
    *,
    hard_gate: bool,
    phase: str,
    feasible_sets_nested: bool | None = None,
    explanation: str = "",
) -> dict[str, Any]:
    return {
        "case_id": "PAIRED_OR_AGGREGATE",
        "phase": phase,
        "check_family": "economic_rationality",
        "check_id": check_id,
        "hard_gate": hard_gate,
        "feasible_sets_nested": feasible_sets_nested,
        "observed": observed,
        "expected": expected,
        "status": "pass" if passed else "fail",
        "explanation": explanation,
    }


def _result_by_id(results: pd.DataFrame, case_id: str) -> pd.Series:
    selected = results[results["case_id"].eq(case_id)]
    if len(selected) != 1:
        raise BehaviouralValidationError(f"Expected one completed result for {case_id}.")
    return selected.iloc[0]


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _apply_physical_comparison_contract(
    result: dict[str, Any],
    context: Any,
    configuration: str,
) -> None:
    """Record frozen feasible-set identity instead of an outcome-derived proxy."""

    result["terminal_contract_sha256"] = _payload_sha256(
        context.terminal_inventory_band[configuration]
    )
    result["physical_feasible_set_sha256"] = _payload_sha256(
        {
            "configuration": configuration,
            "time_grid": {
                "horizon_steps": context.time_grid.horizon_steps,
                "execution_steps": context.time_grid.execution_steps,
                "time_step_hours": context.time_grid.time_step_hours,
            },
            "terminal_band": context.terminal_inventory_band[configuration],
            "quota": context.plan.quota_per_execution_block_t,
            "maintenance_intervals": [],
            "maintenance_policy": "maintenance_free_normal_operation_day",
        }
    )


def _backfill_result_comparison_contracts(
    results: list[dict[str, Any]],
    solver_rows: Sequence[Mapping[str, Any]],
) -> None:
    solver_by_case = {
        str(row["case_id"]): row for row in solver_rows if "planning" in row
    }
    for row in results:
        if row.get("case_status") != "pass":
            continue
        if not isinstance(row.get("physical_initial_state_sha256"), str):
            configuration = CONFIGURATION_IDS[str(row["configuration"])]
            initial_state = SteelRollingState(
                episode_id="administrative_id_excluded", configuration_id=configuration
            )
            row["physical_initial_state_sha256"] = _physical_initial_state_sha256(
                initial_state
            )
        if (
            row.get("policy") == "responsive"
            and not _finite_number(row.get("common_s10_expected_objective_eur"))
        ):
            planning = solver_by_case[str(row["case_id"])]["planning"]
            row["common_s10_expected_objective_eur"] = float(
                planning["expected_cost_reconstructed_eur"]
            )
            row["common_expected_objective_basis"] = "input_s10"


def evaluate_economic_rationality(
    results: pd.DataFrame,
    *,
    phase: str,
    money_tolerance_eur: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if phase == "synthetic":
        for configuration in ("C0", "C1"):
            responsive = _result_by_id(results, f"S1_{configuration}_responsive")
            insensitive = _result_by_id(
                results, f"S1_{configuration}_price_insensitive"
            )
            input_identity = (
                responsive["forecast_scenario_input_sha256"]
                == insensitive["forecast_scenario_input_sha256"]
                and responsive["physical_initial_state_sha256"]
                == insensitive["physical_initial_state_sha256"]
                and responsive["terminal_contract_sha256"]
                == insensitive["terminal_contract_sha256"]
                and responsive["physical_feasible_set_sha256"]
                == insensitive["physical_feasible_set_sha256"]
            )
            checks.append(
                _economic_check(
                    f"{configuration.lower()}_responsive_pi_nested_feasible_set_proof",
                    bool(input_identity),
                    input_identity,
                    True,
                    hard_gate=True,
                    phase=phase,
                    feasible_sets_nested=bool(input_identity),
                    explanation=(
                        "Price-insensitive fixes all sub-3000 bid blocks to zero; "
                        "the responsive formulation leaves those same nonnegative blocks free."
                    ),
                )
            )
            common_basis = bool(
                responsive["common_expected_objective_basis"] == "input_s10"
                and insensitive["common_expected_objective_basis"] == "input_s10"
            )
            dominance = float(responsive["common_s10_expected_objective_eur"]) - float(
                insensitive["common_s10_expected_objective_eur"]
            )
            checks.append(
                _economic_check(
                    f"{configuration.lower()}_responsive_expected_objective_dominance",
                    bool(
                        input_identity
                        and common_basis
                        and dominance
                        <= money_tolerance_eur + MONEY_NUMERICAL_SLACK_EUR
                    ),
                    dominance,
                    f"<= {money_tolerance_eur} EUR",
                    hard_gate=True,
                    phase=phase,
                    feasible_sets_nested=bool(input_identity and common_basis),
                    explanation=(
                        "The frozen flat-80 price-insensitive dispatch is revalued on the "
                        "same S10 prices without replanning; positive observed value means "
                        "responsive is more expensive on that common basis."
                    ),
                )
            )
            production_delta = abs(
                float(responsive["produced_t"]) - float(insensitive["produced_t"])
            )
            checks.append(
                _economic_check(
                    f"{configuration.lower()}_paired_production_invariance",
                    production_delta <= 1e-5,
                    production_delta,
                    "<= 1e-5 t",
                    hard_gate=True,
                    phase=phase,
                    explanation="Price response may not be created by production deviation.",
                )
            )
        forecast = _result_by_id(results, "S1_C1_responsive")
        perfect = _result_by_id(results, "S4_C1_true_pf")
        pf_identity = bool(
            forecast["physical_initial_state_sha256"]
            == perfect["physical_initial_state_sha256"]
            and forecast["terminal_contract_sha256"]
            == perfect["terminal_contract_sha256"]
            and forecast["physical_feasible_set_sha256"]
            == perfect["physical_feasible_set_sha256"]
        )
        pf_delta = float(perfect["realised_total_represented_cost_eur"]) - float(
            forecast["realised_total_represented_cost_eur"]
        )
        checks.append(
            _economic_check(
                "c1_true_pf_realised_cost_bound",
                bool(pf_identity and pf_delta <= money_tolerance_eur),
                pf_delta,
                f"<= {money_tolerance_eur} EUR",
                hard_gate=True,
                phase=phase,
                feasible_sets_nested=pf_identity,
                explanation=(
                    "The isolated PF policy has the same physical boundary and observes only "
                    "the S1 realisation; it is an upper-bound benchmark, not a forecast policy."
                ),
            )
        )
        for configuration in ("C0", "C1"):
            selected = results[
                results["configuration"].eq(configuration)
                & results["phase"].eq("synthetic")
            ]
            for field in (
                "site_background_electricity_mwh",
                "site_baseload_ng_mwh",
                "residual_steam_t",
            ):
                spread = float(selected[field].max() - selected[field].min())
                checks.append(
                    _economic_check(
                        f"{configuration.lower()}_fixed_service_invariance::{field}",
                        spread <= 1e-8,
                        spread,
                        "<= 1e-8",
                        hard_gate=True,
                        phase=phase,
                        explanation="Fixed residual/site-service terms may not react to price.",
                    )
                )
        s1 = _result_by_id(results, "S1_C1_responsive")
        s2 = _result_by_id(results, "S2_C1_responsive")
        eaf_did = abs(
            (
                float(s1["eaf_arc_first_12h_mwh"])
                - float(s1["eaf_arc_second_12h_mwh"])
            )
            - (
                float(s2["eaf_arc_first_12h_mwh"])
                - float(s2["eaf_arc_second_12h_mwh"])
            )
        )
        import_did = abs(
            (
                float(s1["net_grid_import_first_12h_mwh"])
                - float(s1["net_grid_import_second_12h_mwh"])
            )
            - (
                float(s2["net_grid_import_first_12h_mwh"])
                - float(s2["net_grid_import_second_12h_mwh"])
            )
        )
        threshold = max(
            float(s1["response_materiality_threshold_mwh"]),
            float(s2["response_materiality_threshold_mwh"]),
        )
        response = max(eaf_did, import_did)
        checks.append(
            _economic_check(
                "c1_material_response_under_mirrored_large_spread",
                response >= threshold,
                {"eaf_difference_in_differences_mwh": eaf_did, "import_difference_in_differences_mwh": import_did},
                f">= {threshold} MWh",
                hard_gate=True,
                phase=phase,
                explanation="At least one EAF/import response must exceed the frozen noise filter.",
            )
        )
        dri_direction = any(
            value is not None and not pd.isna(value) and float(value) > 0.0
            for value in (
                s1["price_delta_dri_pearson"],
                s2["price_delta_dri_pearson"],
            )
        )
        checks.append(
            _economic_check(
                "directional_price_delta_dri_positive_in_at_least_one_step_case",
                dri_direction,
                {
                    "S1": s1["price_delta_dri_pearson"],
                    "S2": s2["price_delta_dri_pearson"],
                },
                "directionally positive in at least one case",
                hard_gate=False,
                phase=phase,
                explanation=(
                    "F19 is directional only; the metric uses hourly changes in DRI inventory, "
                    "never its absolute level."
                ),
            )
        )
        c0 = _result_by_id(results, "S1_C0_responsive")
        checks.append(
            _economic_check(
                "directional_c0_continuous_bf_stability",
                int(c0["bf6_off_intervals"]) == 0,
                int(c0["bf6_off_intervals"]),
                0,
                hard_gate=False,
                phase=phase,
                explanation="F18/F19 direction only; no numerical BF target is imposed.",
            )
        )
    else:
        high_vol = results[
            results["phase"].eq("shadow")
            & results["profile_id"].eq("high_volatility")
            & results["configuration"].eq("C1")
        ]
        responsive = high_vol[
            high_vol["arm"].eq("C_qh_shape")
            & high_vol["policy"].eq("responsive")
        ].iloc[0]
        perfect = high_vol[high_vol["policy"].eq("true_pf")].iloc[0]
        identity = bool(
            responsive["physical_initial_state_sha256"]
            == perfect["physical_initial_state_sha256"]
            and responsive["physical_feasible_set_sha256"]
            == perfect["physical_feasible_set_sha256"]
        )
        delta = float(perfect["realised_total_represented_cost_eur"]) - float(
            responsive["realised_total_represented_cost_eur"]
        )
        checks.append(
            _economic_check(
                "shadow_high_volatility_pf_bound",
                bool(identity and delta <= money_tolerance_eur),
                delta,
                f"<= {money_tolerance_eur} EUR",
                hard_gate=True,
                phase=phase,
                feasible_sets_nested=identity,
                explanation="PF remains an isolated upper bound on the same shadow-day physics.",
            )
        )
        insensitive = high_vol[high_vol["policy"].eq("price_insensitive")].iloc[0]
        realised_delta = float(responsive["realised_total_represented_cost_eur"]) - float(
            insensitive["realised_total_represented_cost_eur"]
        )
        checks.append(
            _economic_check(
                "shadow_forecast_responsive_realised_vs_price_insensitive",
                True,
                realised_delta,
                "reported, no sign requirement",
                hard_gate=False,
                phase=phase,
                explanation="Forecast error may reverse ex-post ordering; this is not a hard gate.",
            )
        )
        arms = {
            arm: high_vol[
                high_vol["arm"].eq(arm) & high_vol["policy"].eq("responsive")
            ].iloc[0]
            for arm in ("A_hourly", "B_qh_flat", "C_qh_shape")
        }
        costs = {
            arm: float(row["realised_total_represented_cost_eur"])
            for arm, row in arms.items()
        }
        checks.append(
            _economic_check(
                "shadow_high_volatility_abc_cost_decomposition",
                True,
                {
                    "delta_qh_market_A_minus_B_eur": costs["A_hourly"]
                    - costs["B_qh_flat"],
                    "delta_shape_B_minus_C_eur": costs["B_qh_flat"]
                    - costs["C_qh_shape"],
                    "delta_total_A_minus_C_eur": costs["A_hourly"]
                    - costs["C_qh_shape"],
                    "positive_means_saving": True,
                },
                "reported without positive-effect requirement",
                hard_gate=False,
                phase=phase,
                explanation="B versus C differs only through the mean-preserving QH shape.",
            )
        )
    return checks


def _plant_check(
    check_id: str,
    passed: bool,
    observed: Any,
    expected: Any,
    *,
    hard_gate: bool,
    phase: str,
    explanation: str,
) -> dict[str, Any]:
    row = _economic_check(
        check_id,
        passed,
        observed,
        expected,
        hard_gate=hard_gate,
        phase=phase,
        explanation=explanation,
    )
    row["check_family"] = "plant_behavioural"
    return row


def evaluate_plant_behaviour(
    results: pd.DataFrame,
    eligibility_records: Sequence[Mapping[str, Any]],
    *,
    phase: str,
) -> list[dict[str, Any]]:
    """Evaluate only plant expectations frozen as applicable before solving."""

    records = pd.DataFrame(eligibility_records)
    selected_records = records[records["phase"].eq(phase)]
    checks: list[dict[str, Any]] = []
    pre_solve_contract_ok = bool(
        not selected_records.empty
        and selected_records["determination_stage"].eq("pre_solve").all()
        and not selected_records["uses_dispatch_or_actual_prices"].astype(bool).any()
        and not selected_records["final_test_case"].astype(bool).any()
        and selected_records.loc[
            selected_records["eligibility_status"].eq("not_applicable"),
            "binding_reason",
        ]
        .astype(str)
        .str.strip()
        .ne("")
        .all()
    )
    checks.append(
        _plant_check(
            "plant_eligibility_frozen_before_solve",
            pre_solve_contract_ok,
            {
                "record_count": int(len(selected_records)),
                "dispatch_or_actual_used": bool(
                    selected_records.get(
                        "uses_dispatch_or_actual_prices", pd.Series(dtype=bool)
                    )
                    .astype(bool)
                    .any()
                ),
            },
            "all records pre-solve, non-final, and reasoned",
            hard_gate=True,
            phase=phase,
            explanation="Applicability cannot be assigned after observing a dispatch.",
        )
    )
    expected_route_reason = (
        "frozen_one_day_route_quota_contract_does_not_prove_substitution_headroom"
    )
    route = selected_records[
        selected_records["mechanism"].eq("drp_eaf_vs_bf_bof_route_substitution")
    ]
    route_contract_ok = bool(
        not route.empty
        and route["eligibility_status"].eq("not_applicable").all()
        and route["binding_reason"].eq(expected_route_reason).all()
    )
    checks.append(
        _plant_check(
            "route_substitution_not_applicable_pre_solve",
            route_contract_ok,
            route[["eligibility_status", "binding_reason"]].drop_duplicates().to_dict(
                orient="records"
            ),
            expected_route_reason,
            hard_gate=True,
            phase=phase,
            explanation="The frozen route quotas do not prove substitution headroom.",
        )
    )

    phase_results = results[results["phase"].eq(phase)]
    ij01_max = float(phase_results["ij01_named_ng_mwh"].abs().max())
    checks.append(
        _plant_check(
            "ij01_named_ng_remains_zero",
            ij01_max <= ENERGY_TOLERANCE_MWH,
            ij01_max,
            f"<= {ENERGY_TOLERANCE_MWH} MWh_LHV",
            hard_gate=True,
            phase=phase,
            explanation="IJ01 has no authorised named-NG or direct-price-response claim.",
        )
    )
    if phase != "synthetic":
        return checks

    s1 = _result_by_id(phase_results, "S1_C1_responsive")
    s2 = _result_by_id(phase_results, "S2_C1_responsive")
    eaf_records = selected_records[
        selected_records["case_id"].isin(
            ["S1_C1_responsive", "S2_C1_responsive"]
        )
        & selected_records["mechanism"].eq("eaf_heat_timing")
    ]
    eaf_applicable = bool(
        len(eaf_records) == 2
        and eaf_records["eligibility_status"].eq("applicable").all()
    )
    arc_shift = {
        "S1_cheap_minus_expensive_mwh": float(s1["eaf_arc_cheap_mwh"])
        - float(s1["eaf_arc_expensive_mwh"]),
        "S2_cheap_minus_expensive_mwh": float(s2["eaf_arc_cheap_mwh"])
        - float(s2["eaf_arc_expensive_mwh"]),
    }
    arc_threshold = max(
        1.0,
        0.001
        * min(
            float(s1["eaf_total_electricity_mwh"]),
            float(s2["eaf_total_electricity_mwh"]),
        ),
    )
    checks.append(
        _plant_check(
            "eligible_eaf_arc_energy_moves_to_cheap_intervals",
            bool(
                eaf_applicable
                and min(arc_shift.values()) >= arc_threshold - ENERGY_TOLERANCE_MWH
            ),
            arc_shift,
            f"both >= {arc_threshold} MWh",
            hard_gate=eaf_applicable,
            phase=phase,
            explanation="Mirrored prices must move eligible EAF arc energy with the cheap half.",
        )
    )
    heat_shift = {
        "S1_cheap_minus_expensive_starts": float(s1["eaf_heat_starts_cheap"])
        - float(s1["eaf_heat_starts_expensive"]),
        "S2_cheap_minus_expensive_starts": float(s2["eaf_heat_starts_cheap"])
        - float(s2["eaf_heat_starts_expensive"]),
    }
    checks.append(
        _plant_check(
            "eligible_eaf_moves_at_least_one_heat_to_cheap_intervals",
            bool(eaf_applicable and min(heat_shift.values()) >= 1.0 - 1e-6),
            heat_shift,
            "both >= 1 shifted heat",
            hard_gate=eaf_applicable,
            phase=phase,
            explanation="Discrete EAF timing uses one shifted heat as its minimum response.",
        )
    )
    invariant_fields = (
        "produced_t",
        "eaf_heat_starts",
        "eaf_heat_taps",
        "eaf_liquid_steel_output_t",
        "eaf_dri_input_t",
        "eaf_scrap_input_t",
        "bf6_throughput_t",
        "bof_throughput_t",
        "hsm_throughput_t",
        "dsp_output_t",
    )
    invariant_deltas = {
        field: abs(float(s1[field]) - float(s2[field])) for field in invariant_fields
    }
    checks.append(
        _plant_check(
            "mirrored_price_route_and_output_invariance",
            max(invariant_deltas.values(), default=0.0) <= 1e-5,
            invariant_deltas,
            "all <= 1e-5 in their reported units",
            hard_gate=True,
            phase=phase,
            explanation=(
                "Price response may change timing but not frozen route totals or output."
            ),
        )
    )

    material_mechanism_responses: dict[str, float] = {
        "eaf_arc_minimum_cheap_shift_mwh": min(arc_shift.values())
    }
    for case_id in ("S1_C1_responsive", "S2_C1_responsive", "S3_C1_responsive"):
        row = _result_by_id(phase_results, case_id)
        vn25_record = selected_records[
            selected_records["case_id"].eq(case_id)
            & selected_records["mechanism"].eq("vn25_generation")
        ]
        if vn25_record.empty or vn25_record.iloc[0]["eligibility_status"] != "applicable":
            continue
        high_count = int(row["vn25_above_break_even_interval_count"])
        low_count = int(row["vn25_below_break_even_interval_count"])
        contrasted_count = min(high_count, low_count)
        generation_shift = contrasted_count * (
            float(row["vn25_electricity_above_break_even_mean_mwh_per_qh"])
            - float(row["vn25_electricity_below_break_even_mean_mwh_per_qh"])
        )
        import_avoidance = contrasted_count * (
            float(row["net_import_below_break_even_mean_mwh_per_qh"])
            - float(row["net_import_above_break_even_mean_mwh_per_qh"])
        )
        threshold = max(1.0, 0.001 * abs(float(row["vn25_electricity_mwh"])))
        material_mechanism_responses[f"{case_id}__vn25_generation_shift_mwh"] = (
            generation_shift
        )
        checks.append(
            _plant_check(
                f"{case_id}__eligible_vn25_above_break_even_response",
                generation_shift >= threshold - ENERGY_TOLERANCE_MWH,
                {
                    "generation_shift_mwh": generation_shift,
                    "net_import_avoidance_mwh": import_avoidance,
                },
                f"generation shift >= {threshold} MWh",
                hard_gate=True,
                phase=phase,
                explanation="VN25 generation must rise materially above its NG break-even.",
            )
        )
        checks.append(
            _plant_check(
                f"{case_id}__eligible_vn25_grid_import_response",
                import_avoidance >= threshold - ENERGY_TOLERANCE_MWH,
                import_avoidance,
                f">= {threshold} MWh",
                hard_gate=True,
                phase=phase,
                explanation="Material VN25 response must reduce net import on matched support.",
            )
        )
        wag_before_ng = bool(
            float(row["vn25_named_ng_mwh"]) <= ENERGY_TOLERANCE_MWH
            or float(row["vn25_wag_mwh"]) > ENERGY_TOLERANCE_MWH
        )
        checks.append(
            _plant_check(
                f"{case_id}__vn25_wag_precedes_named_ng",
                wag_before_ng,
                {
                    "vn25_wag_mwh": float(row["vn25_wag_mwh"]),
                    "vn25_named_ng_mwh": float(row["vn25_named_ng_mwh"]),
                },
                "named NG is zero or usable WAG is positive",
                hard_gate=True,
                phase=phase,
                explanation="Named NG may not replace all available WAG in VN25.",
            )
        )
        flare_delta = float(row["flare_above_break_even_mean_mwh_per_qh"]) - float(
            row["flare_below_break_even_mean_mwh_per_qh"]
        )
        checks.append(
            _plant_check(
                f"{case_id}__flare_does_not_increase_above_break_even",
                flare_delta <= ENERGY_TOLERANCE_MWH,
                flare_delta,
                f"<= {ENERGY_TOLERANCE_MWH} MWh_LHV/qh",
                hard_gate=True,
                phase=phase,
                explanation="With VN25 headroom, high-price intervals may not increase WAG flare.",
            )
        )
    material_threshold = max(
        float(s1["response_materiality_threshold_mwh"]),
        float(s2["response_materiality_threshold_mwh"]),
    )
    material_max = max(material_mechanism_responses.values(), default=0.0)
    checks.append(
        _plant_check(
            "at_least_one_named_eligible_c1_mechanism_responds_materially",
            material_max >= material_threshold - ENERGY_TOLERANCE_MWH,
            material_mechanism_responses,
            f"at least one >= {material_threshold} MWh",
            hard_gate=True,
            phase=phase,
            explanation="Accepted flexibility must be attributable to a named physical asset.",
        )
    )
    return checks


def _persist_progress(
    output: Path,
    *,
    results: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    physical_checks: Sequence[Mapping[str, Any]],
    economic_checks: Sequence[Mapping[str, Any]],
    solver: Sequence[Mapping[str, Any]],
) -> None:
    _write_csv(output / "case_results.csv", results)
    _write_csv(output / "behavioural_metrics.csv", metrics)
    _write_csv(output / "physical_validation_checks.csv", physical_checks)
    _write_csv(output / "economic_rationality_checks.csv", economic_checks)
    _write_json(output / "solver_diagnostics.json", list(solver))


def _phase_decision(
    *,
    phase: str,
    expected_case_ids: set[str],
    results: Sequence[Mapping[str, Any]],
    physical_checks: Sequence[Mapping[str, Any]],
    economic_checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = {
        str(row["case_id"])
        for row in results
        if str(row.get("phase")) == phase and row.get("case_status") == "pass"
    }
    hard_physical_failures = [
        row
        for row in physical_checks
        if str(row.get("phase")) == phase
        and bool(row.get("hard_gate"))
        and row.get("status") == "fail"
    ]
    hard_economic_failures = [
        row
        for row in economic_checks
        if str(row.get("phase")) == phase
        and bool(row.get("hard_gate"))
        and row.get("status") == "fail"
    ]
    soft_failures = [
        row
        for row in economic_checks
        if str(row.get("phase")) == phase
        and not bool(row.get("hard_gate"))
        and row.get("status") == "fail"
    ]
    blocking_case_diagnostics: list[dict[str, Any]] = []
    for row in results:
        if str(row.get("phase")) != phase or row.get("case_status") == "pass":
            continue
        raw_diagnostic = row.get("failure_diagnostic")
        diagnostic: Mapping[str, Any] = {}
        if isinstance(raw_diagnostic, Mapping):
            diagnostic = raw_diagnostic
        elif isinstance(raw_diagnostic, str) and raw_diagnostic.strip():
            try:
                parsed = json.loads(raw_diagnostic)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, Mapping):
                diagnostic = parsed
        blocking_case_diagnostics.append(
            {
                "case_id": str(row.get("case_id")),
                "case_status": str(row.get("case_status")),
                "error_type": str(row.get("error_type")),
                **{
                    key: diagnostic[key]
                    for key in (
                        "failure_stage",
                        "interpretation",
                        "cleared_import_total_mwh",
                        "cleared_intervals_outside_scenario_import_envelope",
                        "nearest_complete_planned_scenario_import_path_rmse_mwh",
                    )
                    if key in diagnostic
                },
            }
        )
    missing = sorted(expected_case_ids - completed)
    blocked = bool(hard_physical_failures or hard_economic_failures or missing)
    return {
        "phase": phase,
        "status": "block" if blocked else "pass",
        "expected_case_count": len(expected_case_ids),
        "completed_case_count": len(completed & expected_case_ids),
        "missing_or_failed_case_ids": missing,
        "hard_physical_failure_count": len(hard_physical_failures),
        "hard_economic_failure_count": len(hard_economic_failures),
        "soft_directional_failure_count": len(soft_failures),
        "hard_physical_failures": hard_physical_failures,
        "hard_economic_failures": hard_economic_failures,
        "soft_directional_failures": soft_failures,
        "blocking_case_diagnostics": blocking_case_diagnostics,
    }


def _update_forecast_conditionals(
    output: Path,
    case: Mapping[str, Any],
    conditional: Mapping[str, Any],
) -> None:
    if case["phase"] != "shadow":
        return
    rows = _read_csv_rows(output / "forecast_diagnostics.csv")
    base_id = f"{case['day_id']}__{case['arm']}"
    selected = next(
        (
            row
            for row in rows
            if row.get("case_scope_id") == base_id
            and row.get("diagnostic_stage") == "predispatch"
        ),
        None,
    )
    if selected is None:
        raise BehaviouralValidationError("Pre-dispatch forecast diagnostic is missing.")
    rows.append(
        {
            **selected,
            "case_scope_id": case["case_id"],
            "diagnostic_stage": "postdispatch_decision_conditioned",
            **conditional,
        }
    )
    _write_csv(output / "forecast_diagnostics.csv", rows)


def _enrich_cost_comparisons(results: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(results)
    if frame.empty or "case_status" not in frame:
        return
    passed = frame[frame["case_status"].eq("pass")]
    if {
        "S1_C1_responsive",
        "S1_C1_price_insensitive",
        "S4_C1_true_pf",
    }.issubset(set(passed["case_id"])):
        responsive = passed[passed["case_id"].eq("S1_C1_responsive")].iloc[0]
        insensitive = passed[
            passed["case_id"].eq("S1_C1_price_insensitive")
        ].iloc[0]
        perfect = passed[passed["case_id"].eq("S4_C1_true_pf")].iloc[0]
        for row in results:
            if row["case_id"] == "S1_C1_responsive":
                row["saving_vs_price_insensitive_eur"] = float(
                    insensitive["realised_total_represented_cost_eur"]
                    - responsive["realised_total_represented_cost_eur"]
                )
                row["pf_regret_eur"] = float(
                    responsive["realised_total_represented_cost_eur"]
                    - perfect["realised_total_represented_cost_eur"]
                )
    shadow = passed[
        passed["phase"].eq("shadow")
        & passed["profile_id"].eq("high_volatility")
        & passed["configuration"].eq("C1")
    ]
    if not shadow.empty and {"responsive", "price_insensitive", "true_pf"}.issubset(
        set(shadow["policy"])
    ):
        responsive = shadow[
            shadow["policy"].eq("responsive")
            & shadow["arm"].eq("C_qh_shape")
        ].iloc[0]
        insensitive = shadow[shadow["policy"].eq("price_insensitive")].iloc[0]
        perfect = shadow[shadow["policy"].eq("true_pf")].iloc[0]
        for row in results:
            if row["case_id"] == responsive["case_id"]:
                row["saving_vs_price_insensitive_eur"] = float(
                    insensitive["realised_total_represented_cost_eur"]
                    - responsive["realised_total_represented_cost_eur"]
                )
                row["pf_regret_eur"] = float(
                    responsive["realised_total_represented_cost_eur"]
                    - perfect["realised_total_represented_cost_eur"]
                )


def run_behavioural_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    phase: str = "all",
    resume: bool = False,
) -> dict[str, Any]:
    if phase not in {"synthetic", "shadow", "all"}:
        raise BehaviouralValidationError("Phase must be synthetic, shadow or all.")
    prepared = prepare_behavioural_run(config_path, run_id=run_id, resume=resume)
    output: Path = prepared["output"]
    manifest: pd.DataFrame = prepared["manifest"]
    results = _read_csv_rows(output / "case_results.csv")
    metrics = _read_csv_rows(output / "behavioural_metrics.csv")
    physical_checks = _read_csv_rows(output / "physical_validation_checks.csv")
    economic_checks = _read_csv_rows(output / "economic_rationality_checks.csv")
    solver = json.loads((output / "solver_diagnostics.json").read_text(encoding="utf-8"))
    _backfill_result_comparison_contracts(results, solver)
    completed_ids = {
        str(row["case_id"])
        for row in results
        if row.get("case_status") == "pass"
        and (
            row.get("policy") != "price_insensitive"
            or _finite_number(row.get("common_s10_expected_objective_eur"))
        )
    }
    phases = ["synthetic", "shadow"] if phase == "all" else [phase]
    final_summary: dict[str, Any] = {}
    for active_phase in phases:
        if active_phase == "shadow":
            synthetic_ids = set(
                manifest.loc[manifest["phase"].eq("synthetic"), "case_id"].astype(str)
            )
            synthetic_economic = evaluate_economic_rationality(
                pd.DataFrame(results),
                phase="synthetic",
                money_tolerance_eur=float(prepared["config"]["gate"]["money_tolerance_eur"]),
            )
            economic_checks = [
                row for row in economic_checks if row.get("phase") != "synthetic"
            ] + synthetic_economic
            synthetic_decision = _phase_decision(
                phase="synthetic",
                expected_case_ids=synthetic_ids,
                results=results,
                physical_checks=physical_checks,
                economic_checks=economic_checks,
            )
            if synthetic_decision["status"] != "pass":
                final_summary = {
                    "status": "complete_blocked_after_synthetic",
                    "decision": "BLOCK",
                    "synthetic_gate_pass": False,
                    "shadow_gate_started": False,
                    "synthetic": synthetic_decision,
                    "final_weeks_used_for_development": False,
                }
                break
        selected = manifest[manifest["phase"].eq(active_phase)].sort_values(
            "solve_sequence"
        )
        for case in selected.to_dict(orient="records"):
            _assert_run_execution_authorized(output, resume=False)
            if str(case["case_id"]) in completed_ids:
                continue
            results = [
                row for row in results if str(row.get("case_id")) != str(case["case_id"])
            ]
            metrics = [
                row for row in metrics if str(row.get("case_id")) != str(case["case_id"])
            ]
            physical_checks = [
                row
                for row in physical_checks
                if str(row.get("case_id")) != str(case["case_id"])
            ]
            solver = [
                row for row in solver if str(row.get("case_id")) != str(case["case_id"])
            ]
            started = time.perf_counter()
            try:
                outcome = _run_case(prepared, case)
            except Exception as exc:  # fail-closed artifact instead of silent incumbent use
                performance = isinstance(exc, Phase6DPerformanceIncomplete)
                infeasible = isinstance(exc, BehaviouralRedispatchInfeasible)
                emergency = isinstance(exc, Phase6DEmergencyRecourse)
                failure_status = (
                    "emergency_recourse"
                    if emergency
                    else (
                        "performance_incomplete"
                        if performance
                        else "infeasible" if infeasible else "fail"
                    )
                )
                results.append(
                    {
                        "case_id": case["case_id"],
                        "phase": case["phase"],
                        "profile_id": case["profile_id"],
                        "delivery_day": case["delivery_day"],
                        "configuration": case["configuration"],
                        "policy": case["policy"],
                        "arm": case["arm"],
                        "granularity": case["granularity"],
                        "case_status": failure_status,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "wall_seconds_before_failure": time.perf_counter() - started,
                        "failure_diagnostic": json.dumps(
                            getattr(exc, "diagnostic", {}), sort_keys=True, default=str
                        ),
                    }
                )
                physical_checks.append(
                    _check_row(
                        case,
                        "all_solver_tiers_proven_optimal"
                        if performance
                        else (
                            "actual_clearing_redispatch_feasible"
                            if infeasible
                            else "trajectory_execution_completed"
                        ),
                        False,
                        type(exc).__name__,
                        "optimal completed trajectory",
                    )
                )
                solver.append(
                    {
                        "case_id": case["case_id"],
                        "status": failure_status,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "failure_diagnostic": getattr(exc, "diagnostic", {}),
                    }
                )
                _persist_progress(
                    output,
                    results=results,
                    metrics=metrics,
                    physical_checks=physical_checks,
                    economic_checks=economic_checks,
                    solver=solver,
                )
                _write_run_control(
                    output,
                    status=failure_status,
                    resume_authorized=False,
                    reason=(
                        "positive_minimum_imbalance"
                        if emergency
                        else "behavioural_gate_failed_closed"
                    ),
                    diagnostic=getattr(exc, "diagnostic", {}),
                )
                break
            results.append(outcome["result"])
            metrics.extend(outcome["metrics"])
            physical_checks.extend(outcome["checks"])
            solver.append(outcome["solver"])
            completed_ids.add(str(case["case_id"]))
            _update_forecast_conditionals(
                output, case, outcome["conditional_forecast_errors"]
            )
            _persist_progress(
                output,
                results=results,
                metrics=metrics,
                physical_checks=physical_checks,
                economic_checks=economic_checks,
                solver=solver,
            )
            case_failed = any(
                row["case_id"] == case["case_id"]
                and bool(row["hard_gate"])
                and row["status"] == "fail"
                for row in physical_checks
            )
            if case_failed:
                break
        expected = set(selected["case_id"].astype(str))
        if expected.issubset(completed_ids):
            evaluated = evaluate_economic_rationality(
                pd.DataFrame(results),
                phase=active_phase,
                money_tolerance_eur=float(prepared["config"]["gate"]["money_tolerance_eur"]),
            )
            economic_checks = [
                row for row in economic_checks if row.get("phase") != active_phase
            ] + evaluated
        decision = _phase_decision(
            phase=active_phase,
            expected_case_ids=expected,
            results=results,
            physical_checks=physical_checks,
            economic_checks=economic_checks,
        )
        if decision["status"] != "pass":
            final_summary = {
                "status": f"complete_blocked_after_{active_phase}",
                "decision": "BLOCK",
                "synthetic_gate_pass": active_phase != "synthetic",
                "shadow_gate_started": active_phase == "shadow",
                active_phase: decision,
                "final_weeks_used_for_development": False,
            }
            break
        if active_phase == "synthetic" and phase == "synthetic":
            final_summary = {
                "status": "synthetic_pass_shadow_not_started",
                "decision": None,
                "synthetic_gate_pass": True,
                "shadow_gate_started": False,
                "synthetic": decision,
                "final_weeks_used_for_development": False,
            }
        elif active_phase == "shadow":
            all_soft_failures = [
                row
                for row in economic_checks
                if not bool(row.get("hard_gate")) and row.get("status") == "fail"
            ]
            gate_decision = "PASS_WITH_LIMITATION" if all_soft_failures else "PASS"
            synthetic_ids = set(
                manifest.loc[manifest["phase"].eq("synthetic"), "case_id"].astype(str)
            )
            synthetic_decision = _phase_decision(
                phase="synthetic",
                expected_case_ids=synthetic_ids,
                results=results,
                physical_checks=physical_checks,
                economic_checks=economic_checks,
            )
            final_summary = {
                "status": "complete",
                "decision": gate_decision,
                "synthetic_gate_pass": True,
                "shadow_gate_started": True,
                "synthetic": synthetic_decision,
                "shadow": decision,
                "directional_limitations": all_soft_failures,
                "selected_shadow_days": prepared["selection"][
                    ["regime_role", "day"]
                ].to_dict(orient="records"),
                "final_weeks_used_for_development": False,
                "final_week_matrix_run": False,
                "annualisation_allowed": False,
                "positive_economic_effect_required": False,
            }
    _enrich_cost_comparisons(results)
    _persist_progress(
        output,
        results=results,
        metrics=metrics,
        physical_checks=physical_checks,
        economic_checks=economic_checks,
        solver=solver,
    )
    if not final_summary:
        raise BehaviouralValidationError("No behavioural phase decision was produced.")
    final_summary.update(
        {
            "run_id": run_id,
            "run_class": prepared["config"]["run_class"],
            "lineage_role": prepared["config"]["lineage_role"],
            "output_policy": prepared["config"]["output_policy"],
            "completed_trajectory_count": sum(
                row.get("case_status") == "pass" for row in results
            ),
            "performance_incomplete_count": sum(
                row.get("case_status") == "performance_incomplete" for row in results
            ),
            "infeasible_trajectory_count": sum(
                row.get("case_status") == "infeasible" for row in results
            ),
            "emergency_recourse_count": sum(
                row.get("case_status") == "emergency_recourse" for row in results
            ),
            "resume_authorized": False,
        }
    )
    _write_json(output / "gate_summary.json", final_summary)
    _write_warnings_and_limitations(output, final_summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": run_id,
            "run_class": prepared["config"]["run_class"],
            "lineage_role": prepared["config"]["lineage_role"],
            "status": final_summary["status"],
            "decision": final_summary["decision"],
            "git_eligible": False,
            "final_week_matrix_run": False,
        },
    )
    run_control = json.loads(
        (output / "run_control.json").read_text(encoding="utf-8")
    )
    if run_control.get("resume_authorized") is not False:
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="behavioural_gate_completed_and_requires_new_authorization",
        )
    return {"output": str(output), "summary": final_summary}


def run_targeted_conditional_imbalance_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    case_ids: Sequence[str] = (
        "S0_C1_responsive",
        "shadow__typical_calm__2025-03-02__C__C1__responsive",
    ),
) -> dict[str, Any]:
    """Run only the two pre-authorized zero/minimum-imbalance diagnostics."""

    allowed = (
        "S0_C1_responsive",
        "shadow__typical_calm__2025-03-02__C__C1__responsive",
    )
    requested = tuple(str(item) for item in case_ids)
    if not requested or requested != allowed[: len(requested)]:
        raise BehaviouralValidationError(
            "Targeted gate cases must follow the frozen synthetic-then-typical/calm order."
        )
    prepared = prepare_behavioural_run(config_path, run_id=run_id, resume=False)
    output: Path = prepared["output"]
    manifest: pd.DataFrame = prepared["manifest"]
    selected = manifest.set_index("case_id").loc[list(requested)].reset_index()
    _write_json(
        output / "output_declaration.json",
        {
            **prepared["declaration"],
            "output_root": str(output.relative_to(REPO_ROOT)),
            "targeted_case_ids": list(requested),
            "expected_case_count": len(requested),
            "estimated_solver_tier_solves_minimum": len(requested) * 5,
            "estimated_solver_tier_solves_maximum": len(requested) * 7,
            "estimated_size": "minimal governed diagnostics, normally below 20 MB",
            "output_policy": "minimal",
            "run_class": "diagnostic_validation",
            "lineage_role": (
                "conditional minimum-imbalance implementation gate, not economic evidence"
            ),
            "full_four_week_matrix_authorized_or_scheduled": False,
        },
    )
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    solver: list[dict[str, Any]] = []
    failure_status: str | None = None
    for case in selected.to_dict(orient="records"):
        _assert_run_execution_authorized(output, resume=False)
        try:
            outcome = _run_case(prepared, case)
        except Exception as exc:
            if isinstance(exc, Phase6DEmergencyRecourse):
                failure_status = "emergency_recourse"
                reason = "positive_minimum_imbalance"
            elif isinstance(exc, Phase6DPerformanceIncomplete):
                failure_status = "performance_incomplete"
                reason = "minimum_or_other_solver_tier_not_proven_optimal"
            else:
                failure_status = "execution_failure"
                reason = "physical_or_reconstruction_gate_failed"
            diagnostic = getattr(exc, "diagnostic", {})
            results.append(
                {
                    "case_id": case["case_id"],
                    "phase": case["phase"],
                    "delivery_day": case["delivery_day"],
                    "configuration": case["configuration"],
                    "arm": case["arm"],
                    "case_status": failure_status,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failure_diagnostic": json.dumps(
                        diagnostic, sort_keys=True, default=str
                    ),
                }
            )
            solver.append(
                {
                    "case_id": case["case_id"],
                    "status": failure_status,
                    "diagnostic": diagnostic,
                }
            )
            _write_run_control(
                output,
                status=failure_status,
                resume_authorized=False,
                reason=reason,
                diagnostic=diagnostic,
            )
            _persist_progress(
                output,
                results=results,
                metrics=metrics,
                physical_checks=checks,
                economic_checks=[],
                solver=solver,
            )
            break
        result = outcome["result"]
        if float(result["absolute_imbalance_mwh"]) > ENERGY_TOLERANCE_MWH:
            raise BehaviouralValidationError(
                "A targeted gate case returned positive accepted imbalance."
            )
        results.append(result)
        metrics.extend(outcome["metrics"])
        checks.extend(outcome["checks"])
        solver.append(outcome["solver"])
        _persist_progress(
            output,
            results=results,
            metrics=metrics,
            physical_checks=checks,
            economic_checks=[],
            solver=solver,
        )
    passed = failure_status is None and len(results) == len(requested)
    summary = {
        "run_id": run_id,
        "status": "pass" if passed else failure_status,
        "decision": "PASS" if passed else "BLOCK",
        "requested_case_ids": list(requested),
        "completed_zero_imbalance_case_ids": [
            str(row["case_id"])
            for row in results
            if row.get("case_status") == "pass"
            and float(row.get("absolute_imbalance_mwh", math.inf))
            <= ENERGY_TOLERANCE_MWH
        ],
        "case_results": [
            {
                "case_id": row["case_id"],
                "case_status": row["case_status"],
                "absolute_imbalance_mwh": row.get("absolute_imbalance_mwh"),
                "error_type": row.get("error_type"),
            }
            for row in results
        ],
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": (
            "conditional minimum-imbalance implementation gate, not economic evidence"
        ),
        "resume_authorized": False,
        "full_four_week_matrix_run": False,
        "abc_comparison_eligible": False,
    }
    _write_json(output / "targeted_gate_summary.json", summary)
    _write_json(output / "gate_summary.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": run_id,
            "status": summary["status"],
            "decision": summary["decision"],
            "run_class": "diagnostic_validation",
            "lineage_role": summary["lineage_role"],
            "resume_authorized": False,
            "full_four_week_matrix_run": False,
            "git_eligible": False,
        },
    )
    if passed:
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="targeted_gate_completed_and_requires_next_phase_authorization",
        )
    return {"output": str(output), "summary": summary}


def _shadow_feasibility_patterns(
    prepared: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Freeze one portable clearing mask per distinct non-final shadow market path."""

    manifest: pd.DataFrame = prepared["manifest"]
    scopes = (
        manifest[manifest["phase"].eq("shadow")][
            ["day_id", "delivery_day", "arm", "granularity"]
        ]
        .drop_duplicates()
        .sort_values(["delivery_day", "day_id", "arm"])
    )
    patterns: list[dict[str, Any]] = []
    for scope in scopes.to_dict(orient="records"):
        matching = manifest[
            manifest["day_id"].eq(scope["day_id"])
            & manifest["arm"].eq(scope["arm"])
        ].iloc[0]
        _, actual = _bundle_for_case(prepared, matching.to_dict())
        granularity = str(scope["granularity"])
        patterns.append(
            build_validation_feasibility_clearing_pattern(
                actual,
                source_shadow_id=str(scope["day_id"]),
                bid_grid_id=PHASE6D_GRID_IDS[granularity],
                forbidden_final_periods=_final_periods(prepared["config"]),
            )
        )
    unique: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        path_id = str(pattern["path_id"])
        existing = unique.get(path_id)
        if existing is not None and existing != pattern:
            raise BehaviouralValidationError(
                "A feasibility path id maps to conflicting pattern payloads."
            )
        unique[path_id] = pattern
    return [unique[path_id] for path_id in sorted(unique)]


def _controlled_synthetic_feasibility_patterns(
    prepared: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Freeze one probability-free mask per controlled non-final profile."""

    manifest: pd.DataFrame = prepared["manifest"]
    synthetic = prepared["config"]["synthetic"]
    profiles = (
        manifest[manifest["phase"].eq("synthetic")]["profile_id"]
        .drop_duplicates()
        .sort_values()
    )
    patterns: list[dict[str, Any]] = []
    for profile_id in profiles.astype(str):
        matching = manifest[
            manifest["phase"].eq("synthetic")
            & manifest["profile_id"].eq(profile_id)
        ].iloc[0]
        _, actual = _bundle_for_case(prepared, matching.to_dict())
        source_lineage_sha256 = _payload_sha256(
            {
                "source_class": "controlled_synthetic_validation",
                "profile_id": profile_id,
                "point_profile_eur_per_mwh": synthetic[
                    "point_profiles_eur_per_mwh"
                ][profile_id],
                "scenario_residual_source_date": synthetic[
                    "scenario_residual_source_date"
                ],
                "actual_residual_source_date": synthetic[
                    "actual_residual_source_date"
                ],
                "residuals_centered_within_day": synthetic[
                    "residuals_centered_within_day"
                ],
                "common_random_numbers": synthetic["common_random_numbers"],
                "shape_overlay": prepared["config"]["shape_overlay"],
            }
        )
        patterns.append(
            build_validation_feasibility_clearing_pattern(
                actual,
                source_validation_case_id=(
                    f"synthetic_validation__{profile_id}"
                ),
                source_profile_id=profile_id,
                source_lineage_sha256=source_lineage_sha256,
                bid_grid_id=PHASE6D_GRID_IDS[str(matching["granularity"])],
                forbidden_final_periods=_final_periods(prepared["config"]),
            )
        )
    return patterns


def _validation_feasibility_patterns(
    prepared: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Combine frozen shadow and controlled-synthetic validation masks."""

    patterns = [
        *_shadow_feasibility_patterns(prepared),
        *_controlled_synthetic_feasibility_patterns(prepared),
    ]
    unique: dict[str, dict[str, Any]] = {}
    for pattern in sorted(
        patterns,
        key=lambda item: (
            str(item.get("source_class", "development_shadow")),
            str(item.get("source_shadow_id", "")),
            str(item.get("source_validation_case_id", "")),
        ),
    ):
        acceptance_id = _payload_sha256(
            {
                "market_grid": pattern["market_grid"],
                "bid_grid_id": pattern["bid_grid_id"],
                "acceptance_mask_by_lead_position": pattern[
                    "acceptance_mask_by_lead_position"
                ],
            }
        )
        unique.setdefault(acceptance_id, pattern)
    return [unique[key] for key in sorted(unique)]


def _case_local_feasibility_patterns(
    prepared: Mapping[str, Any], case: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Apply synthetic masks only to their matching development profile."""

    patterns = list(_shadow_feasibility_patterns(prepared))
    if str(case["phase"]) == "synthetic":
        profile_id = str(case["profile_id"])
        matching = [
            pattern
            for pattern in _controlled_synthetic_feasibility_patterns(prepared)
            if str(pattern["source_profile_id"]) == profile_id
        ]
        if len(matching) != 1:
            raise BehaviouralValidationError(
                "A synthetic case does not map to one frozen validation pattern."
            )
        patterns.extend(matching)
    return sorted(patterns, key=lambda item: str(item["path_id"]))


def _assess_feasibility_paths_for_plan(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
    plan: SteelBidPlan,
    patterns: Sequence[Mapping[str, Any]],
    *,
    round_index: int,
    initial_state: SteelRollingState | None = None,
) -> list[dict[str, Any]]:
    """Prove each pattern's minimum imbalance without economic scenario weight."""

    bundle, _ = _bundle_for_case(prepared, case)
    delivery_day = date.fromisoformat(str(case["delivery_day"]))
    granularity = str(case["granularity"])
    context = _base_context_config(
        prepared["representative"],
        market_granularity=granularity,
        horizon_hours=24,
    )
    configuration = CONFIGURATION_IDS[str(case["configuration"])]
    diagnostics: list[dict[str, Any]] = []
    active_path_ids = set(
        json.loads(plan.solver.get("feasibility_path_ids_json", "[]"))
    )
    for pattern in sorted(patterns, key=lambda item: str(item["path_id"])):
        if str(pattern["path_id"]) in active_path_ids:
            diagnostics.append(
                {
                    "path_id": str(pattern["path_id"]),
                    "minimum_imbalance_mwh": 0.0,
                    "status": "pass_by_embedded_exact_physical_identity",
                    "diagnostic": {
                        "feasibility_only": True,
                        "shared_bid_variable_component": "bid_volume_mwh",
                        "zero_imbalance_identity_embedded": True,
                    },
                }
            )
            continue
        pattern_actual = actual_bundle_from_feasibility_pattern(
            pattern,
            delivery_day=delivery_day,
            timestamps_utc=bundle.timestamps_utc,
            market_granularity=granularity,
            market_time_step_hours=bundle.time_step_hours,
            bid_grid_id=context.grid_id,
        )
        clearing = clear_hourly_da_bids(plan.bids, pattern_actual)
        state = (
            deepcopy(initial_state)
            if initial_state is not None
            else SteelRollingState(
                episode_id=(
                    f"{case['case_id']}__path_assessment__{pattern['path_id']}"
                ),
                configuration_id=configuration,
            )
        )
        state.episode_id = (
            f"{case['case_id']}__path_assessment__{pattern['path_id']}"
        )
        minimum_diagnostic = diagnose_feasibility_path_minimum_imbalance(
            context,
            configuration,
            clearing,
            state,
            bundle.point_prices,
            required_production_progress_optimum_t=float(
                plan.solver["production_progress_optimum_t"]
            ),
            progress_callback=_solver_progress_callback(
                prepared["output"],
                experiment_id=str(case["case_id"]),
                delivery_day=delivery_day,
                solve_stage=(
                    f"path_assessment_round_{round_index}__"
                    f"{pattern['path_id']}"
                ),
            ),
        )
        minimum = float(minimum_diagnostic["minimum_imbalance_mwh"])
        diagnostics.append(
            {
                "path_id": str(pattern["path_id"]),
                "minimum_imbalance_mwh": minimum,
                "status": (
                    "pass"
                    if minimum <= IMBALANCE_ZERO_TOLERANCE_MWH
                    else "violating"
                ),
                "diagnostic": minimum_diagnostic,
            }
        )
    return diagnostics


def solve_constraint_generated_bid_plan(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
    candidate_patterns: Sequence[Mapping[str, Any]],
    initial_state: SteelRollingState,
) -> dict[str, Any]:
    """Plan one C1 S10 day against bounded probability-free clearing paths."""

    bundle, _ = _bundle_for_case(prepared, case)
    delivery_day = date.fromisoformat(str(case["delivery_day"]))
    context = _base_context_config(
        prepared["representative"],
        market_granularity=str(case["granularity"]),
        horizon_hours=24,
    )
    configuration = CONFIGURATION_IDS[str(case["configuration"])]
    policy = _policy_name(case)
    if configuration != C1_CONFIGURATION or policy not in {"H-S10", "QH-S10"}:
        raise BehaviouralValidationError(
            "Constraint-generated cases must use the frozen C1 S10 contract."
        )
    compatible_patterns = tuple(
        pattern
        for pattern in candidate_patterns
        if pattern["market_grid"] == str(case["granularity"])
        and not bool(pattern["final_test_case"])
    )
    if not compatible_patterns:
        raise BehaviouralValidationError(
            "No non-final validation feasibility paths match the case market grid."
        )
    baseline_progress_optimum: float | None = None
    previous_round_plan: SteelBidPlan | None = None

    def solve_plan(
        selected_paths: Sequence[Mapping[str, Any]], round_index: int
    ) -> SteelBidPlan:
        nonlocal baseline_progress_optimum, previous_round_plan
        plan = solve_grouped_da_bid_plan(
            context,
            configuration,
            bundle,
            initial_state,
            policy,
            audit_future_paths=True,
            feasibility_paths=selected_paths,
            feasibility_progress_optimum_t=(
                baseline_progress_optimum if selected_paths else None
            ),
            parent_round_warm_start_plan=(
                previous_round_plan if selected_paths else None
            ),
            progress_callback=_solver_progress_callback(
                prepared["output"],
                experiment_id=str(case["case_id"]),
                delivery_day=delivery_day,
                solve_stage=f"augmentation_round_{round_index}_planning",
            ),
        )
        if baseline_progress_optimum is None:
            baseline_progress_optimum = float(
                plan.solver["production_progress_optimum_t"]
            )
        elif (
            float(plan.solver["production_progress_optimum_t"])
            > baseline_progress_optimum + 1e-6
        ):
            raise BehaviouralValidationError(
                "Path augmentation changed the primary production-progress optimum."
            )
        previous_round_plan = plan
        return plan

    def assess_plan(
        plan: SteelBidPlan,
        patterns: Sequence[Mapping[str, Any]],
        round_index: int,
    ) -> Sequence[Mapping[str, Any]]:
        return _assess_feasibility_paths_for_plan(
            prepared,
            case,
            plan,
            patterns,
            round_index=round_index,
            initial_state=initial_state,
        )

    return run_limited_path_feasibility_constraint_generation(
        compatible_patterns,
        solve_plan=solve_plan,
        assess_plan=assess_plan,
        max_augmentation_rounds=int(
            prepared["config"]["frozen_contract"][
                "path_feasibility_augmentation"
            ]["maximum_augmentation_rounds"]
        ),
    )


def run_s0_c1_planning_performance_diagnostic(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    expected_cost_warmstart: bool = True,
    planning_solver_execution_mode: str = PLANNING_SOLVER_SEQUENTIAL,
    gurobi_performance_options: Mapping[str, int | float] | None = None,
) -> dict[str, Any]:
    """Profile the frozen S0 C1 plan without redispatch or final-period data."""

    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    rows = prepared["manifest"].loc[
        prepared["manifest"]["case_id"].eq("S0_C1_responsive")
    ]
    if len(rows) != 1:
        raise BehaviouralValidationError("Frozen S0 C1 case is unavailable.")
    case = rows.iloc[0].to_dict()
    bundle, _ = _bundle_for_case(prepared, case)
    context = _base_context_config(
        prepared["representative"],
        market_granularity=str(case["granularity"]),
        horizon_hours=24,
    )
    context.config["expected_cost_warmstart"] = bool(expected_cost_warmstart)
    context.config["planning_solver_execution_mode"] = str(
        planning_solver_execution_mode
    )
    context.config["gurobi_performance_options"] = dict(
        gurobi_performance_options or {}
    )
    context.config["solver_log_directory"] = str(output / "solver_logs")
    context.config["solver_log_prefix"] = (
        "S0_C1_responsive__warm" if expected_cost_warmstart else "S0_C1_responsive__cold"
    )
    initial_state = SteelRollingState(
        episode_id=f"{run_id}__S0_C1_responsive",
        configuration_id=C1_CONFIGURATION,
    )
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": "non-final S0 C1 planning performance diagnosis",
        "performance_mode": str(planning_solver_execution_mode),
        "expected_cost_warmstart": bool(expected_cost_warmstart),
        "gurobi_performance_options": dict(gurobi_performance_options or {}),
        "estimated_model_count": 1,
        "estimated_solver_tier_solves": 2,
        "estimated_size": "below 20 MB including two directed solver logs",
        "final_test_periods_read_or_solved": False,
        "resume_authorized": False,
    }
    _write_json(output / "performance_diagnostic_declaration.json", declaration)
    try:
        plan = solve_grouped_da_bid_plan(
            context,
            C1_CONFIGURATION,
            bundle,
            initial_state,
            "QH-S10",
            audit_future_paths=True,
            progress_callback=_solver_progress_callback(
                output,
                experiment_id="S0_C1_responsive",
                delivery_day=bundle.delivery_day,
                solve_stage=(
                    "planning_performance_warmstart"
                    if expected_cost_warmstart
                    else "planning_performance_coldstart"
                ),
            ),
        )
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "solver": plan.solver,
            "economic_s10_contract_sha256": plan.solver[
                "economic_s10_contract_sha256"
            ],
            "scenario_probability_sum": plan.solver["scenario_probability_sum"],
        }
        _write_json(output / "planning_performance_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="planning_performance_diagnostic_completed",
        )
        return {"output": str(output), "summary": summary}
    except Phase6DPerformanceIncomplete as exc:
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "performance_incomplete",
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": exc.diagnostic,
        }
        _write_json(output / "planning_performance_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="performance_incomplete",
            resume_authorized=False,
            reason="S0_C1_planning_not_proven_optimal",
            diagnostic=exc.diagnostic,
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        _write_run_control(
            output,
            status="blocked",
            resume_authorized=False,
            reason="planning_performance_diagnostic_failed_closed",
            diagnostic=getattr(exc, "diagnostic", {}),
        )
        raise


def run_s0_c1_augmented_planning_performance_diagnostic(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    source_shadow_ids: Sequence[str],
    baseline_progress_optimum_t: float,
    gurobi_performance_options: Mapping[str, int | float] | None = None,
    final_path_gurobi_performance_options: Mapping[str, int | float] | None = None,
) -> dict[str, Any]:
    """Profile one frozen S0-C1 plan with an explicit non-final path set."""

    requested_sources = tuple(str(item) for item in source_shadow_ids)
    if not 1 <= len(requested_sources) <= MAX_PATH_FEASIBILITY_AUGMENTATION_ROUNDS:
        raise BehaviouralValidationError(
            "The augmented performance diagnostic requires one to three paths."
        )
    if len(set(requested_sources)) != len(requested_sources):
        raise BehaviouralValidationError("Augmented diagnostic sources must be unique.")
    if float(baseline_progress_optimum_t) < -1e-9:
        raise BehaviouralValidationError("Production progress optimum cannot be negative.")
    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    case_rows = prepared["manifest"].loc[
        prepared["manifest"]["case_id"].eq("S0_C1_responsive")
    ]
    if len(case_rows) != 1:
        raise BehaviouralValidationError("Frozen S0 C1 case is unavailable.")
    case = case_rows.iloc[0].to_dict()
    bundle, _ = _bundle_for_case(prepared, case)
    patterns = _validation_feasibility_patterns(prepared)
    by_source = {
        str(
            row.get("source_shadow_id")
            or row.get("source_validation_case_id")
        ): row
        for row in patterns
    }
    missing = sorted(set(requested_sources) - set(by_source))
    if missing:
        raise BehaviouralValidationError(
            f"Unknown non-final feasibility path sources: {missing}."
        )
    selected_paths = tuple(by_source[source] for source in requested_sources)
    if any(
        row["market_grid"] != "quarterhour" or bool(row["final_test_case"])
        for row in selected_paths
    ):
        raise BehaviouralValidationError(
            "The S0 C1 diagnostic accepts only non-final QH feasibility paths."
        )
    context = _base_context_config(
        prepared["representative"], market_granularity="quarterhour", horizon_hours=24
    )
    performance_options = dict(
        config["frozen_contract"]["gurobi_performance_options"]
    )
    performance_options.update(dict(gurobi_performance_options or {}))
    final_performance_options = {
        **performance_options,
        **dict(final_path_gurobi_performance_options or {}),
    }
    context.config["gurobi_performance_options"] = performance_options
    context.config["solver_log_directory"] = str(output / "solver_logs")
    context.config["solver_log_prefix"] = "s0c1"
    initial_state = SteelRollingState(
        episode_id=f"{run_id}__S0_C1_augmented_path_profile",
        configuration_id=C1_CONFIGURATION,
    )
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": "non-final two-path S0 C1 planning performance diagnosis",
        "case_id": "S0_C1_responsive",
        "source_shadow_ids": list(requested_sources),
        "path_ids": [str(row["path_id"]) for row in selected_paths],
        "baseline_progress_optimum_t": float(baseline_progress_optimum_t),
        "gurobi_performance_options": dict(
            context.config["gurobi_performance_options"]
        ),
        "final_path_gurobi_performance_options": final_performance_options,
        "estimated_model_count": len(selected_paths),
        "estimated_solver_tier_solves": 2 + 3 * (len(selected_paths) - 1),
        "estimated_size": "below 20 MB including directed solver logs",
        "final_test_periods_read_or_solved": False,
        "resume_authorized": False,
    }
    _write_json(output / "performance_diagnostic_declaration.json", declaration)
    try:
        parent_plan: SteelBidPlan | None = None
        plan: SteelBidPlan | None = None
        for path_count in range(1, len(selected_paths) + 1):
            context.config["gurobi_performance_options"] = dict(
                final_performance_options
                if path_count == len(selected_paths)
                else performance_options
            )
            context.config["solver_log_prefix"] = f"p{path_count}"
            plan = solve_grouped_da_bid_plan(
                context,
                C1_CONFIGURATION,
                bundle,
                initial_state,
                "QH-S10",
                audit_future_paths=True,
                feasibility_paths=selected_paths[:path_count],
                feasibility_progress_optimum_t=float(
                    baseline_progress_optimum_t
                ),
                parent_round_warm_start_plan=parent_plan,
                progress_callback=_solver_progress_callback(
                    output,
                    experiment_id="S0_C1_responsive",
                    delivery_day=bundle.delivery_day,
                    solve_stage=(
                        f"path_count_{path_count}_augmented_planning_performance"
                    ),
                ),
            )
            parent_plan = plan
        if plan is None:
            raise BehaviouralValidationError("No augmented profile plan was solved.")
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "solver": plan.solver,
            "economic_s10_contract_sha256": plan.solver[
                "economic_s10_contract_sha256"
            ],
            "scenario_probability_sum": plan.solver["scenario_probability_sum"],
        }
        _write_json(output / "augmented_planning_performance_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="augmented_planning_performance_diagnostic_completed",
        )
        return {"output": str(output), "summary": summary}
    except Phase6DPerformanceIncomplete as exc:
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "performance_incomplete",
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": exc.diagnostic,
        }
        _write_json(output / "augmented_planning_performance_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="performance_incomplete",
            resume_authorized=False,
            reason="S0_C1_augmented_planning_not_proven_optimal",
            diagnostic=exc.diagnostic,
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        _write_run_control(
            output,
            status="blocked",
            resume_authorized=False,
            reason="augmented_planning_performance_diagnostic_failed_closed",
            diagnostic=getattr(exc, "diagnostic", {}),
        )
        raise


def run_path_feasibility_blocker_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Reproduce and repair only the frozen 2-March C1 shadow blocker."""

    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    blocker_id = "shadow__typical_calm__2025-03-02__C__C1__responsive"
    manifest: pd.DataFrame = prepared["manifest"]
    case_rows = manifest[manifest["case_id"].eq(blocker_id)]
    if len(case_rows) != 1:
        raise BehaviouralValidationError("Frozen path-feasibility blocker is unavailable.")
    case = case_rows.iloc[0].to_dict()
    bundle, actual = _bundle_for_case(prepared, case)
    delivery_day = date.fromisoformat(str(case["delivery_day"]))
    context = _base_context_config(
        prepared["representative"],
        market_granularity=str(case["granularity"]),
        horizon_hours=24,
    )
    legacy_reproduction_context = _base_context_config(
        prepared["representative"],
        market_granularity=str(case["granularity"]),
        horizon_hours=24,
    )
    legacy_reproduction_context.config["bid_signature_symmetry_breaking"] = False
    legacy_reproduction_context.config["gurobi_performance_options"] = {}
    configuration = CONFIGURATION_IDS[str(case["configuration"])]
    policy = _policy_name(case)
    if policy != "QH-S10" or configuration != C1_CONFIGURATION:
        raise BehaviouralValidationError("Frozen blocker no longer maps to C1 QH-S10.")
    initial_state = SteelRollingState(
        episode_id=f"{blocker_id}__path_feasibility_gate",
        configuration_id=configuration,
    )
    _write_json(
        output / "output_declaration.json",
        {
            "output_root": output.relative_to(REPO_ROOT).as_posix(),
            "output_policy": "minimal",
            "run_class": "diagnostic_validation",
            "lineage_role": (
                "validation-derived feasibility-only blocker repair, not final evidence"
            ),
            "expected_model_count": 4,
            "expected_solver_tier_solves_minimum": 8,
            "expected_solver_tier_solves_maximum": 12,
            "estimated_size": "minimal governed diagnostics, normally below 20 MB",
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_authorized_or_scheduled": False,
        },
    )
    try:
        baseline_plan = solve_grouped_da_bid_plan(
            legacy_reproduction_context,
            configuration,
            bundle,
            initial_state,
            policy,
            audit_future_paths=True,
            progress_callback=_solver_progress_callback(
                output,
                experiment_id=blocker_id,
                delivery_day=delivery_day,
                solve_stage="baseline_planning",
            ),
        )
        baseline_clearing = clear_hourly_da_bids(baseline_plan.bids, actual)
        try:
            solve_grouped_actual_redispatch(
                legacy_reproduction_context,
                configuration,
                baseline_clearing,
                initial_state,
                bundle.point_prices,
                oracle_execute_D_cost_only=False,
                imbalance_penalty_eur_per_mwh=5000.0,
                progress_callback=_solver_progress_callback(
                    output,
                    experiment_id=blocker_id,
                    delivery_day=delivery_day,
                    solve_stage="baseline_redispatch",
                ),
            )
        except Phase6DEmergencyRecourse as exc:
            baseline_diagnostic = dict(exc.diagnostic)
        else:
            raise BehaviouralValidationError(
                "The known 2-March minimum-imbalance blocker was not reproduced."
            )
        expected_minimum = float(
            config["gate"]["known_blocker_minimum_imbalance_mwh"]
        )
        reproduction_tolerance = float(
            config["gate"]["known_blocker_reproduction_tolerance_mwh"]
        )
        reproduced_minimum = float(baseline_diagnostic["absolute_imbalance_mwh"])
        if abs(reproduced_minimum - expected_minimum) > reproduction_tolerance:
            raise BehaviouralValidationError(
                "The known blocker minimum imbalance was not reproduced within tolerance."
            )
        pattern = build_validation_feasibility_clearing_pattern(
            actual,
            source_shadow_id=str(case["day_id"]),
            bid_grid_id=context.grid_id,
            forbidden_final_periods=_final_periods(config),
        )
        _write_json(output / "feasibility_pattern_manifest.json", pattern)
        repaired_plan = solve_grouped_da_bid_plan(
            context,
            configuration,
            bundle,
            initial_state,
            policy,
            audit_future_paths=True,
            feasibility_paths=(pattern,),
            feasibility_progress_optimum_t=float(
                baseline_plan.solver["production_progress_optimum_t"]
            ),
            progress_callback=_solver_progress_callback(
                output,
                experiment_id=blocker_id,
                delivery_day=delivery_day,
                solve_stage="augmentation_round_1_planning",
            ),
        )
        if baseline_plan.input_probabilities != repaired_plan.input_probabilities:
            raise BehaviouralValidationError("S10 probabilities changed during repair.")
        if baseline_plan.input_scenario_ids != repaired_plan.input_scenario_ids:
            raise BehaviouralValidationError("S10 scenario ids changed during repair.")
        if (
            baseline_plan.solver["economic_s10_contract_sha256"]
            != repaired_plan.solver["economic_s10_contract_sha256"]
        ):
            raise BehaviouralValidationError("S10 prices or probabilities changed.")
        if float(
            repaired_plan.solver["feasibility_path_expected_cost_contribution_eur"]
        ) != 0.0:
            raise BehaviouralValidationError("A feasibility path entered expected cost.")
        repaired_clearing = clear_hourly_da_bids(repaired_plan.bids, actual)
        repaired_redispatch = solve_grouped_actual_redispatch(
            context,
            configuration,
            repaired_clearing,
            initial_state,
            bundle.point_prices,
            oracle_execute_D_cost_only=False,
            imbalance_penalty_eur_per_mwh=5000.0,
            progress_callback=_solver_progress_callback(
                output,
                experiment_id=blocker_id,
                delivery_day=delivery_day,
                solve_stage="repaired_redispatch",
            ),
        )
        if repaired_redispatch.absolute_imbalance_mwh > ENERGY_TOLERANCE_MWH:
            raise BehaviouralValidationError("Repaired blocker retains imbalance.")
        if repaired_redispatch.solver.get(
            "conditional_minimum_imbalance_solve_performed"
        ):
            raise BehaviouralValidationError(
                "Repaired blocker still needed the minimum-imbalance solve."
            )
        checks = _physical_checks(
            prepared,
            case,
            bundle,
            actual,
            repaired_plan,
            repaired_clearing,
            repaired_redispatch,
            initial_state,
        )
        failed_checks = [row for row in checks if row["status"] != "pass"]
        if failed_checks:
            raise BehaviouralValidationError(
                f"Repaired blocker failed physical/reconstruction checks: {failed_checks}"
            )
        summary = {
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "case_id": blocker_id,
            "before_economic_imbalance_mwh": float(
                baseline_diagnostic["economic_imbalance_before_gate"][
                    "absolute_imbalance_mwh"
                ]
            ),
            "before_minimum_imbalance_mwh": reproduced_minimum,
            "after_absolute_imbalance_mwh": float(
                repaired_redispatch.absolute_imbalance_mwh
            ),
            "after_minimum_solve_performed": False,
            "added_pattern_count": 1,
            "added_path_ids": [str(pattern["path_id"])],
            "economic_s10_contract_sha256": repaired_plan.solver[
                "economic_s10_contract_sha256"
            ],
            "repaired_bid_curve_sha256": _payload_sha256(repaired_plan.bids),
            "repaired_scenario_dispatch_sha256": _payload_sha256(
                repaired_plan.scenario_dispatch
            ),
            "repaired_clearing_sha256": _payload_sha256(repaired_clearing.hourly),
            "repaired_physical_dispatch_sha256": _payload_sha256(
                repaired_redispatch.physical_intervals
            ),
            "repaired_next_state_sha256": _payload_sha256(
                repaired_redispatch.next_state.snapshot()
            ),
            "repaired_expected_cost_eur": float(repaired_plan.expected_cost_eur),
            "repaired_cleared_settlement_eur": float(
                repaired_clearing.settlement_cost_eur
            ),
            "repaired_realised_represented_cost_eur": float(
                repaired_redispatch.other_represented_cost_eur
            ),
            "scenario_probability_sum": sum(
                float(item) for item in repaired_plan.input_probabilities.values()
            ),
            "feasibility_path_expected_cost_contribution_eur": 0.0,
            "model_growth": {
                "variables": int(repaired_plan.solver["variable_count"])
                - int(baseline_plan.solver["variable_count"]),
                "binaries": int(repaired_plan.solver["binary_count"])
                - int(baseline_plan.solver["binary_count"]),
                "constraints": int(repaired_plan.solver["constraint_count"])
                - int(baseline_plan.solver["constraint_count"]),
            },
            "baseline_planning_solver": baseline_plan.solver,
            "baseline_method_role": "frozen_legacy_blocker_reproduction",
            "repaired_method_role": (
                "bid_signature_symmetry_breaking_mipfocus1_"
                "feasibility_aware_expected_cost_incumbent"
            ),
            "repaired_planning_solver": repaired_plan.solver,
            "repaired_redispatch_solver": repaired_redispatch.solver,
            "physical_check_count": len(checks),
            "output_policy": "minimal",
            "run_class": "diagnostic_validation",
            "lineage_role": (
                "validation-derived feasibility-only blocker repair, not final evidence"
            ),
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
        }
        _write_csv(output / "physical_validation_checks.csv", checks)
        _write_json(output / "path_feasibility_blocker_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="phase_b_pass_requires_phase_c_gate",
        )
        return {"output": str(output), "summary": summary, "prepared": prepared}
    except Exception as exc:
        diagnostic = getattr(exc, "diagnostic", {})
        summary = {
            "run_id": run_id,
            "status": "blocked",
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": diagnostic,
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
        }
        _write_json(output / "path_feasibility_blocker_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status=(
                "path_feasibility_augmentation_incomplete"
                if isinstance(exc, Phase6DPathFeasibilityIncomplete)
                else "blocked"
            ),
            resume_authorized=False,
            reason="path_feasibility_blocker_gate_failed_closed",
            diagnostic=diagnostic,
        )
        raise


def _run_constraint_generated_case(
    prepared: Mapping[str, Any],
    case: Mapping[str, Any],
    candidate_patterns: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Run one C1 responsive case with bounded feasibility constraint generation."""

    bundle, actual = _bundle_for_case(prepared, case)
    delivery_day = date.fromisoformat(str(case["delivery_day"]))
    context = _base_context_config(
        prepared["representative"],
        market_granularity=str(case["granularity"]),
        horizon_hours=24,
    )
    configuration = CONFIGURATION_IDS[str(case["configuration"])]
    initial_state = SteelRollingState(
        episode_id=f"{case['case_id']}__path_feasibility_gate",
        configuration_id=configuration,
    )
    generated = solve_constraint_generated_bid_plan(
        prepared,
        case,
        candidate_patterns,
        initial_state,
    )
    plan: SteelBidPlan = generated["plan"]
    clearing = clear_hourly_da_bids(plan.bids, actual)
    redispatch = solve_grouped_actual_redispatch(
        context,
        configuration,
        clearing,
        initial_state,
        bundle.point_prices,
        oracle_execute_D_cost_only=False,
        imbalance_penalty_eur_per_mwh=5000.0,
        progress_callback=_solver_progress_callback(
            prepared["output"],
            experiment_id=str(case["case_id"]),
            delivery_day=delivery_day,
            solve_stage="final_augmented_redispatch",
        ),
    )
    if redispatch.absolute_imbalance_mwh > ENERGY_TOLERANCE_MWH:
        raise BehaviouralValidationError("An augmented C1 case retained imbalance.")
    conditional_recovery_used = bool(
        redispatch.solver.get("conditional_minimum_imbalance_solve_performed")
    )
    if conditional_recovery_used:
        conditional_gate = redispatch.solver["conditional_imbalance_gate"]
        if (
            float(conditional_gate["minimum_imbalance_mwh"])
            > ENERGY_TOLERANCE_MWH
            or not bool(
                redispatch.solver.get("hard_zero_economic_resolve_performed")
            )
            or not bool(conditional_gate.get("economic_result_accepted", False))
            or not bool(conditional_gate.get("abc_comparison_eligible", False))
        ):
            raise BehaviouralValidationError(
                "Conditional imbalance recovery did not prove an accepted "
                "hard-zero economic result."
            )
    checks = _physical_checks(
        prepared,
        case,
        bundle,
        actual,
        plan,
        clearing,
        redispatch,
        initial_state,
    )
    failed_checks = [row for row in checks if row["status"] != "pass"]
    if failed_checks:
        raise BehaviouralValidationError(
            f"Augmented case failed physical/reconstruction checks: {failed_checks}"
        )
    result, metrics, conditional = _case_metrics(
        case,
        bundle,
        actual,
        plan,
        clearing,
        redispatch,
        initial_state,
    )
    _apply_physical_comparison_contract(result, context, configuration)
    result.update(
        {
            "path_feasibility_augmentation_status": generated["status"],
            "path_feasibility_added_pattern_count": len(
                generated["selected_paths"]
            ),
            "path_feasibility_added_path_ids": json.dumps(
                [str(item["path_id"]) for item in generated["selected_paths"]]
            ),
            "path_feasibility_round_count": len(generated["rounds"]) - 1,
            "path_feasibility_rounds": json.dumps(
                generated["rounds"], sort_keys=True, default=str
            ),
            "conditional_zero_imbalance_recovery_used": conditional_recovery_used,
        }
    )
    return {
        "result": result,
        "metrics": metrics,
        "conditional": conditional,
        "checks": checks,
        "solver": {
            "case_id": case["case_id"],
            "planning": plan.solver,
            "redispatch": redispatch.solver,
            "path_feasibility_constraint_generation": generated["rounds"],
        },
    }


def run_s0_c1_constraint_generation_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    pattern_scope: str = "governed_validation",
) -> dict[str, Any]:
    """Run only the non-final S0-C1 end-to-end augmentation blocker gate."""

    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    case_rows = prepared["manifest"].loc[
        prepared["manifest"]["case_id"].eq("S0_C1_responsive")
    ]
    if len(case_rows) != 1:
        raise BehaviouralValidationError("Frozen S0 C1 case is unavailable.")
    case = case_rows.iloc[0].to_dict()
    if bool(case["final_test_case"]):
        raise BehaviouralValidationError("A final-test case entered the S0-C1 gate.")
    if pattern_scope == "governed_validation":
        patterns = _validation_feasibility_patterns(prepared)
    elif pattern_scope == "shadow_only_runtime_diagnostic":
        patterns = _shadow_feasibility_patterns(prepared)
    elif pattern_scope == "shadow_plus_case_validation":
        patterns = _case_local_feasibility_patterns(prepared, case)
    else:
        raise BehaviouralValidationError("Unknown S0-C1 pattern scope.")
    compatible_patterns = [
        row for row in patterns if row["market_grid"] == str(case["granularity"])
    ]
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": (
            "non-final S0-C1 end-to-end path-feasibility blocker gate"
        ),
        "trajectory_count": 1,
        "case_id": "S0_C1_responsive",
        "pattern_scope": pattern_scope,
        "candidate_pattern_count": len(compatible_patterns),
        "maximum_augmentation_rounds": int(
            config["frozen_contract"]["path_feasibility_augmentation"][
                "maximum_augmentation_rounds"
            ]
        ),
        "maximum_patterns_added_per_round": 1,
        "estimated_model_count": (
            "one baseline plan plus at most three augmented plans and separation models"
        ),
        "estimated_solver_tier_solves": (
            "bounded by 16 planning tiers, 16 separation tiers, and 3 redispatch tiers"
        ),
        "estimated_size": "minimal governed diagnostics, normally below 25 MB",
        "final_test_periods_read_or_solved": False,
        "final_week_matrix_authorized_or_scheduled": False,
        "resume_authorized": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    _write_json(
        output / "feasibility_pattern_manifest.json",
        {
            "pattern_count": len(compatible_patterns),
            "patterns": compatible_patterns,
            "raw_validation_prices_persisted": False,
            "economic_scenario_probability_assigned": False,
            "final_test_period_source_count": 0,
        },
    )
    try:
        _assert_run_execution_authorized(output, resume=False)
        outcome = _run_constraint_generated_case(prepared, case, patterns)
        result = outcome["result"]
        _persist_progress(
            output,
            results=[result],
            metrics=outcome["metrics"],
            physical_checks=outcome["checks"],
            economic_checks=[],
            solver=[outcome["solver"]],
        )
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "absolute_imbalance_mwh": float(result["absolute_imbalance_mwh"]),
            "conditional_minimum_imbalance_solve_performed": bool(
                outcome["solver"]["redispatch"][
                    "conditional_minimum_imbalance_solve_performed"
                ]
            ),
            "added_pattern_count": int(
                result["path_feasibility_added_pattern_count"]
            ),
            "added_path_ids": json.loads(
                str(result["path_feasibility_added_path_ids"])
            ),
            "augmentation_round_count": int(
                result["path_feasibility_round_count"]
            ),
            "planning_economic_certificate": {
                key: outcome["solver"]["planning"][key]
                for key in (
                    "economic_optimality_class",
                    "economic_objective_lower_bound_eur",
                    "economic_objective_upper_bound_eur",
                    "economic_absolute_objective_band_eur",
                    "economic_certified_relative_gap",
                )
            },
            "redispatch_economic_certificate": {
                key: outcome["solver"]["redispatch"][key]
                for key in (
                    "economic_optimality_class",
                    "economic_objective_lower_bound_eur",
                    "economic_objective_upper_bound_eur",
                    "economic_absolute_objective_band_eur",
                    "economic_certified_relative_gap",
                )
            },
            "solver_diagnostics_artifact": "solver_diagnostics.json",
            "physical_check_failure_count": 0,
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
        }
        _write_json(output / "s0_c1_constraint_generation_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="s0_c1_gate_pass_requires_full_non_final_behavioural_gate",
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        diagnostic = getattr(exc, "diagnostic", {})
        summary = {
            **declaration,
            "run_id": run_id,
            "status": (
                "path_feasibility_augmentation_incomplete"
                if isinstance(exc, Phase6DPathFeasibilityIncomplete)
                else "blocked"
            ),
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": diagnostic,
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
        }
        _write_json(output / "s0_c1_constraint_generation_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status=str(summary["status"]),
            resume_authorized=False,
            reason="s0_c1_constraint_generation_gate_failed_closed",
            diagnostic=diagnostic,
        )
        raise


def run_single_path_feasibility_case_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    case_id: str,
) -> dict[str, Any]:
    """Continue the non-final plant gate with exactly one unfinished case."""

    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    manifest: pd.DataFrame = prepared["manifest"]
    selected = manifest.loc[manifest["case_id"].astype(str).eq(str(case_id))]
    if len(selected) != 1:
        raise BehaviouralValidationError(
            f"Single-case continuation requires one manifest case: {case_id!r}."
        )
    case = selected.iloc[0].to_dict()
    if bool(case["final_test_case"]):
        raise BehaviouralValidationError("A final-test case cannot enter continuation.")
    eligibility_records = build_plant_eligibility_records(prepared, selected)
    _write_csv(output / "plant_eligibility_records.csv", eligibility_records)
    _write_json(
        output / "plant_eligibility_manifest.json",
        {
            "determination_stage": "pre_solve",
            "record_count": len(eligibility_records),
            "case_count": 1,
            "uses_dispatch_or_actual_prices": False,
            "final_test_case_count": 0,
            "records_sha256": _payload_sha256(eligibility_records),
        },
    )
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": "single unfinished non-final plant-gate continuation case",
        "trajectory_count": 1,
        "case_id": str(case_id),
        "estimated_model_count": "two baseline models plus bounded separation models for C1 S10 only",
        "estimated_solver_tier_solves": "case-dependent; fail closed at 900 s per tier",
        "estimated_size": "minimal governed diagnostics, normally below 20 MB",
        "final_test_periods_read_or_solved": False,
        "final_week_matrix_authorized_or_scheduled": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    try:
        _assert_run_execution_authorized(output, resume=False)
        if (
            str(case["configuration"]) == "C1"
            and _policy_name(case) in {"H-S10", "QH-S10"}
        ):
            outcome = _run_constraint_generated_case(
                prepared,
                case,
                _case_local_feasibility_patterns(prepared, case),
            )
        else:
            outcome = _run_case(prepared, case)
        result = outcome["result"]
        if float(result["absolute_imbalance_mwh"]) > ENERGY_TOLERANCE_MWH:
            raise BehaviouralValidationError(
                "A continuation case returned positive accepted imbalance."
            )
        failed_checks = [
            row for row in outcome["checks"] if row["status"] != "pass"
        ]
        if failed_checks:
            raise BehaviouralValidationError(
                f"Continuation case failed hard checks: {failed_checks}"
            )
        _persist_progress(
            output,
            results=[result],
            metrics=outcome["metrics"],
            physical_checks=outcome["checks"],
            economic_checks=[],
            solver=[outcome["solver"]],
        )
        summary = {
            **declaration,
            "status": "pass_pending_cross_case_plant_aggregation",
            "decision": "PASS",
            "absolute_imbalance_mwh": float(result["absolute_imbalance_mwh"]),
            "physical_check_count": len(outcome["checks"]),
            "physical_check_failure_count": 0,
            "plant_eligibility_record_count": len(eligibility_records),
            "cross_case_plant_evaluation_pending": True,
            "solver_diagnostics_artifact": "solver_diagnostics.json",
            "resume_authorized": False,
        }
        _write_json(output / "single_case_continuation_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="single_case_pass_pending_cross_case_plant_aggregation",
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        diagnostic = getattr(exc, "diagnostic", {})
        summary = {
            **declaration,
            "status": "blocked",
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": diagnostic,
            "resume_authorized": False,
        }
        _write_json(output / "single_case_continuation_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="blocked",
            resume_authorized=False,
            reason="single_case_continuation_failed_closed",
            diagnostic=diagnostic,
        )
        raise


def _audit_aggregated_case_artifacts(
    prepared: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    checks: Sequence[Mapping[str, Any]],
    solver_rows: Sequence[Mapping[str, Any]],
    source_by_case: Mapping[str, Path],
) -> list[dict[str, Any]]:
    """Prove that persisted cases satisfy the current no-solve reuse contract."""

    manifest = prepared["manifest"].set_index("case_id", drop=False)
    checks_by_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in checks:
        checks_by_case.setdefault(str(row["case_id"]), []).append(row)
    solver_by_case = {str(row["case_id"]): row for row in solver_rows}
    audit: list[dict[str, Any]] = []

    def accepted_tier(tier: Mapping[str, Any]) -> bool:
        if str(tier.get("termination_condition", "")).lower() == "optimal":
            return True
        return bool(tier.get("epsilon_optimal_accepted", False)) and bool(
            _finite_number(tier.get("best_bound"))
            and _finite_number(tier.get("objective_value"))
            and _finite_number(tier.get("certified_relative_gap"))
            and float(tier["certified_relative_gap"]) <= ECONOMIC_MIP_GAP_LIMIT
        )

    def economic_certificate(record: Mapping[str, Any]) -> dict[str, float]:
        lower = float(record["economic_objective_lower_bound_eur"])
        upper = float(record["economic_objective_upper_bound_eur"])
        band = float(record["economic_absolute_objective_band_eur"])
        gap = float(record["economic_certified_relative_gap"])
        if (
            not all(math.isfinite(value) for value in (lower, upper, band, gap))
            or lower > upper + MONEY_NUMERICAL_SLACK_EUR
            or abs(band - (upper - lower)) > MONEY_NUMERICAL_SLACK_EUR
            or gap > ECONOMIC_MIP_GAP_LIMIT
        ):
            raise BehaviouralValidationError(
                "An aggregated economic solver certificate is invalid."
            )
        return {"lower_bound_eur": lower, "upper_bound_eur": upper, "band_eur": band, "relative_gap": gap}

    for raw_result in results:
        result = dict(raw_result)
        case_id = str(result["case_id"])
        if case_id not in manifest.index or case_id not in source_by_case:
            raise BehaviouralValidationError(
                f"Aggregated case provenance is missing for {case_id}."
            )
        case = manifest.loc[case_id].to_dict()
        bundle, _ = _bundle_for_case(prepared, case)
        expected_forecast_sha256 = _payload_sha256(
            {
                "point": bundle.point_prices,
                "scenarios": bundle.scenario_prices,
                "probabilities": bundle.scenario_probabilities,
            }
        )
        configuration = CONFIGURATION_IDS[str(result["configuration"])]
        expected_state_sha256 = _physical_initial_state_sha256(
            SteelRollingState(
                episode_id="administrative_id_excluded",
                configuration_id=configuration,
            )
        )
        comparison_context = _base_context_config(
            prepared["representative"],
            market_granularity=str(result["granularity"]),
            horizon_hours=24,
        )
        expected_contract: dict[str, Any] = {}
        _apply_physical_comparison_contract(
            expected_contract, comparison_context, configuration
        )
        identity_ok = bool(
            result.get("forecast_scenario_input_sha256")
            == expected_forecast_sha256
            and result.get("physical_initial_state_sha256")
            == expected_state_sha256
            and result.get("terminal_contract_sha256")
            == expected_contract["terminal_contract_sha256"]
            and result.get("physical_feasible_set_sha256")
            == expected_contract["physical_feasible_set_sha256"]
        )
        case_checks = checks_by_case.get(case_id, [])
        checks_ok = bool(
            case_checks and all(row.get("status") == "pass" for row in case_checks)
        )
        solver = solver_by_case.get(case_id)
        if solver is None:
            raise BehaviouralValidationError(
                f"Aggregated solver diagnostics are missing for {case_id}."
            )
        planning = solver["planning"]
        redispatch = solver["redispatch"]
        tiers_ok = all(
            accepted_tier(tier)
            for record in (planning, redispatch)
            for tier in record["tier_solves"]
        )
        planning_certificate = economic_certificate(planning)
        redispatch_certificate = economic_certificate(redispatch)
        source_manifest = json.loads(
            (source_by_case[case_id] / "input_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        expected_scenario_count = 10 if result.get("policy") == "responsive" else 1
        contract_ok = bool(
            identity_ok
            and checks_ok
            and tiers_ok
            and source_manifest.get("final_test_periods_read_or_solved") is False
            and int(planning["scenario_count"]) == expected_scenario_count
            and abs(float(planning["scenario_probability_sum"]) - 1.0) <= 1e-10
            and float(redispatch["imbalance_penalty_eur_per_mwh"]) == 5000.0
            and int(redispatch["imbalance_penalty_term_count"]) == 1
            and float(redispatch["absolute_imbalance_mwh"])
            <= ENERGY_TOLERANCE_MWH
            and result.get("case_status") == "pass"
        )
        if not contract_ok:
            raise BehaviouralValidationError(
                f"Aggregated case failed the current reuse contract: {case_id}."
            )
        audit.append(
            {
                "case_id": case_id,
                "source_root": source_by_case[case_id]
                .relative_to(REPO_ROOT)
                .as_posix(),
                "status": "pass",
                "forecast_state_terminal_and_feasible_set_identity": identity_ok,
                "physical_and_financial_check_count": len(case_checks),
                "planning_economic_certificate": planning_certificate,
                "redispatch_economic_certificate": redispatch_certificate,
                "absolute_imbalance_mwh": float(
                    redispatch["absolute_imbalance_mwh"]
                ),
                "solver_tiers_strict_or_epsilon_optimal": tiers_ok,
                "planning_scenario_count": int(planning["scenario_count"]),
                "final_test_periods_read_or_solved": False,
            }
        )
    return audit


def aggregate_path_feasibility_case_artifacts(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    phase: str,
    case_run_roots: Sequence[str | Path],
) -> dict[str, Any]:
    """Aggregate completed single-case artifacts without running a solver."""

    if phase not in {"synthetic", "shadow"}:
        raise BehaviouralValidationError("Artifact aggregation phase is invalid.")
    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    expected_ids = set(
        prepared["manifest"].loc[
            prepared["manifest"]["phase"].eq(phase), "case_id"
        ].astype(str)
    )
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    eligibility_records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    source_by_case: dict[str, Path] = {}
    for raw_spec in case_run_roots:
        raw_text = str(raw_spec)
        requested_case_id: str | None = None
        raw_root = raw_text
        if "=" in raw_text:
            requested_case_id, raw_root = raw_text.split("=", 1)
            if requested_case_id not in expected_ids or not raw_root:
                raise BehaviouralValidationError(
                    "Explicit aggregate sources must use EXPECTED_CASE_ID=RUN_ROOT."
                )
        source = _resolve(raw_root)
        source_results = _read_csv_rows(source / "case_results.csv")
        if requested_case_id is None:
            source_ids = {
                str(row["case_id"])
                for row in source_results
                if str(row.get("case_id")) in expected_ids
            }
        else:
            selected_rows = [
                row
                for row in source_results
                if str(row.get("case_id")) == requested_case_id
            ]
            if len(selected_rows) != 1:
                raise BehaviouralValidationError(
                    f"Explicit aggregate source does not contain exactly one "
                    f"{requested_case_id!r} result."
                )
            source_ids = {requested_case_id}
        eligibility_path = source / "plant_eligibility_records.csv"
        if eligibility_path.exists():
            eligibility_records.extend(
                row
                for row in _read_csv_rows(eligibility_path)
                if str(row["case_id"]) in expected_ids
            )
        if not source_ids:
            sources.append(
                {
                    "source_root": source.relative_to(REPO_ROOT).as_posix(),
                    "case_ids": [],
                    "eligibility_only": True,
                }
            )
            continue
        duplicate_ids = source_ids.intersection(source_by_case)
        if duplicate_ids:
            raise BehaviouralValidationError(
                f"Aggregate case sources are duplicated: {sorted(duplicate_ids)}."
            )
        source_by_case.update({case_id: source for case_id in source_ids})
        results.extend(
            row for row in source_results if str(row["case_id"]) in source_ids
        )
        metrics.extend(
            row
            for row in _read_csv_rows(source / "behavioural_metrics.csv")
            if str(row["case_id"]) in source_ids
        )
        checks.extend(
            row
            for row in _read_csv_rows(source / "physical_validation_checks.csv")
            if str(row["case_id"]) in source_ids
        )
        source_solver = json.loads(
            (source / "solver_diagnostics.json").read_text(encoding="utf-8")
        )
        solver_rows.extend(
            row for row in source_solver if str(row["case_id"]) in source_ids
        )
        sources.append(
            {
                "source_root": source.relative_to(REPO_ROOT).as_posix(),
                "case_ids": sorted(source_ids),
                "eligibility_only": False,
            }
        )
    result_ids = [str(row["case_id"]) for row in results]
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != expected_ids:
        raise BehaviouralValidationError(
            "Aggregated case artifacts must cover every phase case exactly once."
        )
    reuse_audit = _audit_aggregated_case_artifacts(
        prepared,
        results,
        checks,
        solver_rows,
        source_by_case,
    )
    _backfill_result_comparison_contracts(results, solver_rows)
    for row in results:
        comparison_context = _base_context_config(
            prepared["representative"],
            market_granularity=str(row["granularity"]),
            horizon_hours=24,
        )
        _apply_physical_comparison_contract(
            row,
            comparison_context,
            CONFIGURATION_IDS[str(row["configuration"])],
        )
    if any(
        row.get("case_status") != "pass"
        or float(row["absolute_imbalance_mwh"]) > ENERGY_TOLERANCE_MWH
        for row in results
    ):
        raise BehaviouralValidationError("An aggregated case is not a zero-imbalance PASS.")
    if any(row.get("status") != "pass" for row in checks):
        raise BehaviouralValidationError("An aggregated physical check failed.")
    eligibility_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in eligibility_records:
        eligibility_by_key[(str(row["case_id"]), str(row["mechanism"]))] = row
    eligibility_records = list(eligibility_by_key.values())
    if {str(row["case_id"]) for row in eligibility_records} != expected_ids:
        raise BehaviouralValidationError("Aggregated plant eligibility is incomplete.")
    passed = pd.DataFrame(results)
    economic_checks = evaluate_economic_rationality(
        passed,
        phase=phase,
        money_tolerance_eur=float(config["gate"]["money_tolerance_eur"]),
    )
    plant_checks = evaluate_plant_behaviour(
        passed,
        eligibility_records,
        phase=phase,
    )
    decision = _phase_decision(
        phase=phase,
        expected_case_ids=expected_ids,
        results=results,
        physical_checks=checks,
        economic_checks=[*economic_checks, *plant_checks],
    )
    _persist_progress(
        output,
        results=results,
        metrics=metrics,
        physical_checks=checks,
        economic_checks=[*economic_checks, *plant_checks],
        solver=solver_rows,
    )
    _write_csv(output / "plant_eligibility_records.csv", eligibility_records)
    _write_csv(output / "plant_behavioural_checks.csv", plant_checks)
    _write_json(output / "aggregation_sources.json", sources)
    _write_json(output / "case_artifact_reuse_audit.json", reuse_audit)
    summary = {
        "run_id": run_id,
        "status": "pass" if decision["status"] == "pass" else "blocked",
        "decision": "PASS" if decision["status"] == "pass" else "BLOCK",
        "phase": phase,
        "case_count": len(results),
        "case_artifact_reuse_audit_pass_count": len(reuse_audit),
        "absolute_imbalance_max_mwh": max(
            float(row["absolute_imbalance_mwh"]) for row in results
        ),
        "physical_check_failure_count": sum(
            row.get("status") != "pass" for row in checks
        ),
        "economic_or_plant_hard_failure_count": int(
            decision["hard_economic_failure_count"]
        ),
        "phase_decision": decision,
        "solver_runs_started": 0,
        "comparison_contracts_reconstructed_from_frozen_config": True,
        "final_test_periods_read_or_solved": False,
        "resume_authorized": False,
    }
    _write_json(output / "case_artifact_aggregation_summary.json", summary)
    _write_json(output / "gate_summary.json", summary)
    _write_run_control(
        output,
        status="completed" if summary["decision"] == "PASS" else "blocked",
        resume_authorized=False,
        reason="case_artifact_aggregation_complete",
    )
    return {"output": str(output), "summary": summary}


def _rolling_state_from_snapshot(snapshot: Mapping[str, Any]) -> SteelRollingState:
    return SteelRollingState(
        episode_id=str(snapshot["episode_id"]),
        configuration_id=str(snapshot["configuration_id"]),
        inventory_overrides={
            str(key): float(value)
            for key, value in dict(snapshot["inventory_overrides"]).items()
        },
        cumulative_production_t=float(snapshot["cumulative_production_t"]),
        executed_hours=int(snapshot["executed_hours"]),
        executed_intervals=int(snapshot["executed_intervals"]),
        last_executed_timestamp_utc=snapshot.get("last_executed_timestamp_utc"),
        cumulative_route_progress_t={
            str(key): float(value)
            for key, value in dict(snapshot["cumulative_route_progress_t"]).items()
        },
        eaf_start_lag1=int(snapshot["eaf_start_lag1"]),
        eaf_start_lag2=int(snapshot["eaf_start_lag2"]),
        drp_last_pellet_input_t=(
            None
            if snapshot.get("drp_last_pellet_input_t") is None
            else float(snapshot["drp_last_pellet_input_t"])
        ),
    )


def _non_final_rolling_week_inputs(
    prepared: Mapping[str, Any],
) -> dict[str, Any]:
    contract = prepared["config"]["non_final_rolling_week"]
    week_start = date.fromisoformat(str(contract["week_start"]))
    week_end = date.fromisoformat(str(contract["week_end"]))
    days = [week_start + timedelta(days=offset) for offset in range(7)]
    frames: StudyFrames = prepared["frames"]
    strict_points = frames.hourly_points[
        frames.hourly_points["model_id"].eq(STRICT_MODEL_ID)
    ]
    strict_scenarios = frames.hourly_scenarios_10[
        frames.hourly_scenarios_10["model_id"].eq(STRICT_MODEL_ID)
    ]
    shape_library = prepared["shape_library"]
    overlays: list[pd.DataFrame] = []
    overlay_manifests: list[dict[str, Any]] = []
    for delivery_day in days:
        points = _day_rows(strict_points, delivery_day).sort_values(
            "target_timestamp_utc"
        )
        scenarios = _day_rows(strict_scenarios, delivery_day).sort_values(
            ["scenario_id", "target_timestamp_utc"]
        )
        if len(points) != 24 or len(scenarios) != 240:
            raise BehaviouralValidationError(
                "The frozen non-final rolling week lacks complete Strict S10 support."
            )
        actuals = points[
            ["target_timestamp_utc", "delivery_date_local", "actual_price"]
        ].copy()
        overlay, manifest = apply_counterfactual_shape_overlay(
            week_id=str(contract["week_id"]),
            hourly_points=points,
            hourly_scenarios=scenarios,
            hourly_actuals=actuals,
            shape_library=dict(shape_library),
            random_seed=int(prepared["config"]["shape_overlay"]["random_seed"]),
            tolerance=float(
                prepared["config"]["shape_overlay"][
                    "mean_preservation_tolerance"
                ]
            ),
        )
        manifest.update(
            {
                "delivery_day": delivery_day.isoformat(),
                "non_final_rolling_validation": True,
                "final_test_case": False,
            }
        )
        overlays.append(overlay)
        overlay_manifests.append(manifest)
    combined_overlay = pd.concat(overlays, ignore_index=True)
    if not bool(combined_overlay["counterfactual"].all()):
        raise BehaviouralValidationError(
            "The rolling validation overlay lost its counterfactual flag."
        )
    rolling_frames = replace(frames, qh_overlay=combined_overlay)
    case_rows: list[dict[str, Any]] = []
    experiment_rows: list[dict[str, Any]] = []
    for configuration in contract["configurations"]:
        for arm in contract["arms"]:
            granularity = "hourly" if arm == "A_hourly" else "quarterhour"
            experiment_id = (
                f"rolling_validation__{contract['week_id']}__{configuration}__{arm}"
            )
            experiment_rows.append(
                {
                    "experiment_id": experiment_id,
                    "week_id": contract["week_id"],
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "configuration": configuration,
                    "arm": arm,
                    "granularity": granularity,
                    "policy": "responsive",
                    "scenario_count": 10,
                    "horizon_hours": 24,
                    "day_count": 7,
                    "final_test_case": False,
                }
            )
            for delivery_day in days:
                case_rows.append(
                    {
                        "case_id": f"{experiment_id}__{delivery_day.isoformat()}",
                        "phase": "rolling_validation",
                        "profile_id": "non_final_complete_week",
                        "day_id": contract["week_id"],
                        "delivery_day": delivery_day.isoformat(),
                        "configuration": configuration,
                        "policy": "responsive",
                        "arm": arm,
                        "granularity": granularity,
                        "final_test_case": False,
                        "experiment_id": experiment_id,
                    }
                )
    all_patterns = _shadow_feasibility_patterns(prepared)
    eligible_patterns = [
        pattern
        for pattern in all_patterns
        if date.fromisoformat(str(pattern["source_delivery_day"])) < week_start
        and not bool(pattern["final_test_case"])
    ]
    prior_source_days = {
        str(pattern["source_delivery_day"]) for pattern in eligible_patterns
    }
    if len(prior_source_days) < int(contract["minimum_prior_shadow_source_count"]):
        raise BehaviouralValidationError(
            "Too few chronologically prior shadow sources cover the rolling gate."
        )
    if any(
        date.fromisoformat(str(pattern["source_delivery_day"])) >= week_start
        for pattern in eligible_patterns
    ):
        raise BehaviouralValidationError(
            "A contemporaneous or future pattern entered the rolling gate."
        )
    prepared_rolling = {
        **prepared,
        "shadow_frames": rolling_frames,
    }
    cases = pd.DataFrame(case_rows)
    eligibility = build_plant_eligibility_records(prepared_rolling, cases)
    return {
        "contract": contract,
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "frames": rolling_frames,
        "prepared": prepared_rolling,
        "cases": cases,
        "experiments": pd.DataFrame(experiment_rows),
        "patterns": eligible_patterns,
        "eligibility": eligibility,
        "overlay": combined_overlay,
        "overlay_manifests": overlay_manifests,
        "prior_source_days": sorted(prior_source_days),
    }


def _rolling_week_plant_checks(
    results: pd.DataFrame,
    eligibility_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Close the frozen plant gate across the non-final rolling week."""

    phase = "rolling_validation"
    checks = evaluate_plant_behaviour(
        results,
        eligibility_records,
        phase=phase,
    )
    c1 = results[
        results["phase"].eq(phase) & results["configuration"].eq("C1")
    ]
    named_response_fields = (
        "eaf_arc_mwh",
        "drp_electricity_mwh",
        "vn25_electricity_mwh",
        "boiler_named_ng_mwh",
        "flare_mwh",
    )
    daily_spreads: dict[str, float] = {field: 0.0 for field in named_response_fields}
    for _, daily in c1.groupby("delivery_day"):
        if set(daily["arm"].astype(str)) != {
            "A_hourly",
            "B_qh_flat",
            "C_qh_shape",
        }:
            continue
        for field in named_response_fields:
            daily_spreads[field] = max(
                daily_spreads[field],
                float(daily[field].max() - daily[field].min()),
            )
    materiality = max(
        1.0,
        float(c1["response_materiality_threshold_mwh"].max()),
    )
    eligible = pd.DataFrame(eligibility_records)
    eligible_c1 = eligible[
        eligible["phase"].eq(phase)
        & eligible["configuration"].eq("C1")
        & eligible["eligibility_status"].eq("applicable")
    ]
    maximum_eaf_cheap_expensive_shift = float(
        (
            c1["eaf_arc_cheap_mwh"].astype(float)
            - c1["eaf_arc_expensive_mwh"].astype(float)
        )
        .abs()
        .max()
    )
    material_response = max(
        max(daily_spreads.values()),
        maximum_eaf_cheap_expensive_shift,
    )
    checks.append(
        _plant_check(
            "rolling_c1_named_physical_response",
            bool(not eligible_c1.empty and material_response >= materiality),
            {
                "maximum_daily_arm_spread_by_field": daily_spreads,
                "maximum_eaf_cheap_expensive_shift_mwh": (
                    maximum_eaf_cheap_expensive_shift
                ),
                "applicable_record_count": int(len(eligible_c1)),
            },
            f">= {materiality} MWh in at least one named field/day",
            hard_gate=True,
            phase=phase,
            explanation=(
                "At least one pre-solve-eligible C1 mechanism must produce a "
                "material response in a named physical asset across A/B/C."
            ),
        )
    )
    weekly_by_arm = (
        results[results["phase"].eq(phase)]
        .groupby(["configuration", "arm"], as_index=False)[
            ["produced_t", "hsm_throughput_t", "dsp_output_t"]
        ]
        .sum()
    )
    for configuration in ("C0", "C1"):
        selected = weekly_by_arm[weekly_by_arm["configuration"].eq(configuration)]
        for field in ("produced_t", "hsm_throughput_t", "dsp_output_t"):
            spread = float(selected[field].max() - selected[field].min())
            checks.append(
                _plant_check(
                    f"rolling_{configuration.lower()}_{field}_arm_invariance",
                    spread <= 1e-5,
                    spread,
                    "<= 1e-5",
                    hard_gate=True,
                    phase=phase,
                    explanation=(
                        "Market-arm differences may not be created by changing "
                        "the frozen weekly production/output requirement."
                    ),
                )
            )
    steam_unserved = float(results["steam_unserved_t"].abs().max())
    checks.append(
        _plant_check(
            "rolling_steam_unserved_remains_zero",
            steam_unserved <= ENERGY_TOLERANCE_MWH,
            steam_unserved,
            f"<= {ENERGY_TOLERANCE_MWH}",
            hard_gate=True,
            phase=phase,
            explanation="Every rolling day must close steam supply without a plug.",
        )
    )
    return checks


def run_non_final_rolling_week_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    """Run exactly one frozen non-final C0/C1 A/B/C rolling validation week."""

    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=resume,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    rolling = _non_final_rolling_week_inputs(prepared)
    experiments: pd.DataFrame = rolling["experiments"]
    cases: pd.DataFrame = rolling["cases"]
    if len(experiments) != 6 or len(cases) != 42:
        raise BehaviouralValidationError(
            "The non-final rolling gate must contain 6 experiments and 42 days."
        )
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": (
            "non-final maintenance-free rolling C0/C1 A/B/C path-feasibility gate"
        ),
        "week_id": rolling["contract"]["week_id"],
        "week_start": rolling["week_start"].isoformat(),
        "week_end": rolling["week_end"].isoformat(),
        "experiment_count": 6,
        "rolling_day_count": 42,
        "estimated_model_count": (
            "84 base daily plan/redispatch models plus bounded C1 separation and "
            "augmentation models; approximately 180-220 model instances at the "
            "current shadow-pattern incidence"
        ),
        "estimated_solver_tier_solves": (
            "approximately 390 from the current hourly/QH shadow incidence; "
            "minimum 210, case-dependent, with at most three one-pattern "
            "augmentation rounds and 900 s per tier"
        ),
        "expected_file_count": "approximately 20 compact run-level artifacts",
        "estimated_size": "minimal governed checkpoints and diagnostics, below 100 MB",
        "retention_status": "ignored_local_governed_diagnostic",
        "git_eligible": False,
        "final_test_periods_read_or_solved": False,
        "final_week_matrix_authorized_or_scheduled": False,
        "maintenance_policy": "maintenance_free_normal_operation_week",
    }
    _write_json(output / "output_declaration.json", declaration)
    _write_csv(
        output / "rolling_validation_experiment_manifest.csv",
        experiments.to_dict(orient="records"),
    )
    _write_csv(
        output / "rolling_validation_case_manifest.csv",
        cases.to_dict(orient="records"),
    )
    _write_csv(
        output / "plant_eligibility_records.csv", rolling["eligibility"]
    )
    _write_json(
        output / "rolling_validation_pattern_manifest.json",
        {
            "pattern_count": len(rolling["patterns"]),
            "prior_source_days": rolling["prior_source_days"],
            "patterns": rolling["patterns"],
            "probability_assigned": False,
            "expected_cost_weight_assigned": False,
            "final_test_source_count": 0,
        },
    )
    rolling["overlay"].to_parquet(
        output / "rolling_validation_counterfactual_overlay.parquet", index=False
    )
    _write_json(
        output / "rolling_validation_overlay_manifest.json",
        rolling["overlay_manifests"],
    )
    fingerprint = _payload_sha256(
        {
            "contract": rolling["contract"],
            "experiments": experiments.to_dict(orient="records"),
            "pattern_ids": sorted(
                str(pattern["path_id"]) for pattern in rolling["patterns"]
            ),
            "overlay_manifests": rolling["overlay_manifests"],
        }
    )
    checkpoint_path = output / "rolling_week_checkpoint.json"
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    states = {
        str(row["experiment_id"]): SteelRollingState(
            episode_id=str(row["experiment_id"]),
            configuration_id=CONFIGURATION_IDS[str(row["configuration"])],
        )
        for row in experiments.to_dict(orient="records")
    }
    completed_case_ids: list[str] = []
    if resume:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("input_fingerprint") != fingerprint:
            raise BehaviouralValidationError(
                "Rolling-week checkpoint differs from frozen inputs."
            )
        results = list(checkpoint["results"])
        metrics = list(checkpoint["metrics"])
        checks = list(checkpoint["checks"])
        solver_rows = list(checkpoint["solver_rows"])
        completed_case_ids = [str(item) for item in checkpoint["completed_case_ids"]]
        states = {
            str(key): _rolling_state_from_snapshot(value)
            for key, value in checkpoint["states"].items()
        }
    elif checkpoint_path.exists():
        raise BehaviouralValidationError(
            "Rolling-week checkpoint exists; use resume or a new run id."
        )

    try:
        for case in cases.to_dict(orient="records"):
            case_id = str(case["case_id"])
            if case_id in completed_case_ids:
                continue
            _assert_run_execution_authorized(output, resume=False)
            experiment_id = str(case["experiment_id"])
            state = states[experiment_id]
            before = state.snapshot()
            bundle, actual = _bundle_for_case(rolling["prepared"], case)
            context = _base_context_config(
                prepared["representative"],
                market_granularity=str(case["granularity"]),
                horizon_hours=24,
            )
            configuration = CONFIGURATION_IDS[str(case["configuration"])]
            if configuration == C1_CONFIGURATION:
                generated = solve_constraint_generated_bid_plan(
                    rolling["prepared"],
                    case,
                    rolling["patterns"],
                    state,
                )
                plan: SteelBidPlan = generated["plan"]
            else:
                generated = {
                    "status": "not_applicable_c0",
                    "selected_paths": [],
                    "rounds": [],
                }
                plan = solve_grouped_da_bid_plan(
                    context,
                    configuration,
                    bundle,
                    state,
                    _policy_name(case),
                    audit_future_paths=True,
                    progress_callback=_solver_progress_callback(
                        output,
                        experiment_id=experiment_id,
                        delivery_day=date.fromisoformat(str(case["delivery_day"])),
                        solve_stage="planning",
                    ),
                )
            clearing = clear_hourly_da_bids(plan.bids, actual)
            redispatch = solve_grouped_actual_redispatch(
                context,
                configuration,
                clearing,
                state,
                bundle.point_prices,
                oracle_execute_D_cost_only=False,
                imbalance_penalty_eur_per_mwh=5000.0,
                progress_callback=_solver_progress_callback(
                    output,
                    experiment_id=experiment_id,
                    delivery_day=date.fromisoformat(str(case["delivery_day"])),
                    solve_stage="redispatch",
                ),
            )
            if redispatch.absolute_imbalance_mwh > ENERGY_TOLERANCE_MWH:
                raise BehaviouralValidationError(
                    "A rolling validation day retained accepted imbalance."
                )
            day_checks = _physical_checks(
                rolling["prepared"],
                case,
                bundle,
                actual,
                plan,
                clearing,
                redispatch,
                state,
            )
            if any(row["status"] != "pass" for row in day_checks):
                raise BehaviouralValidationError(
                    "A rolling validation day failed a physical or financial check."
                )
            result, day_metrics, _ = _case_metrics(
                case,
                bundle,
                actual,
                plan,
                clearing,
                redispatch,
                state,
            )
            _apply_physical_comparison_contract(
                result, context, configuration
            )
            result.update(
                {
                    "experiment_id": experiment_id,
                    "path_feasibility_augmentation_status": generated["status"],
                    "path_feasibility_added_pattern_count": len(
                        generated["selected_paths"]
                    ),
                    "path_feasibility_added_path_ids": json.dumps(
                        [
                            str(pattern["path_id"])
                            for pattern in generated["selected_paths"]
                        ]
                    ),
                    "planning_expected_lower_bound_eur": plan.solver[
                        "economic_objective_lower_bound_eur"
                    ],
                    "planning_expected_upper_bound_eur": plan.solver[
                        "economic_objective_upper_bound_eur"
                    ],
                    "planning_expected_relative_gap": plan.solver[
                        "economic_certified_relative_gap"
                    ],
                }
            )
            results.append(result)
            metrics.extend(day_metrics)
            checks.extend(day_checks)
            solver_rows.append(
                {
                    "case_id": case_id,
                    "experiment_id": experiment_id,
                    "planning": plan.solver,
                    "redispatch": redispatch.solver,
                    "path_feasibility_constraint_generation": generated["rounds"],
                }
            )
            state = redispatch.next_state
            if state.executed_hours != int(before["executed_hours"]) + 24:
                raise BehaviouralValidationError(
                    "A rolling state handoff did not advance exactly 24 hours."
                )
            states[experiment_id] = state
            completed_case_ids.append(case_id)
            _persist_progress(
                output,
                results=results,
                metrics=metrics,
                physical_checks=checks,
                economic_checks=[],
                solver=solver_rows,
            )
            _write_json(
                checkpoint_path,
                {
                    "input_fingerprint": fingerprint,
                    "completed_case_ids": completed_case_ids,
                    "results": results,
                    "metrics": metrics,
                    "checks": checks,
                    "solver_rows": solver_rows,
                    "states": {
                        key: value.snapshot() for key, value in states.items()
                    },
                    "complete": False,
                    "resume_authorized": True,
                },
            )
        if len(results) != 42 or len(completed_case_ids) != 42:
            raise BehaviouralValidationError(
                "The rolling validation week did not complete 42 daily trajectories."
            )
        result_frame = pd.DataFrame(results)
        plant_checks = _rolling_week_plant_checks(
            result_frame,
            rolling["eligibility"],
        )
        _write_csv(output / "plant_behavioural_checks.csv", plant_checks)
        _persist_progress(
            output,
            results=results,
            metrics=metrics,
            physical_checks=checks,
            economic_checks=plant_checks,
            solver=solver_rows,
        )
        weekly_rows: list[dict[str, Any]] = []
        weekly_sum_fields = (
            "net_grid_import_mwh",
            "gross_electricity_mwh",
            "internal_generation_mwh",
            "named_ng_mwh",
            "eaf_heat_starts",
            "eaf_heat_taps",
            "eaf_arc_mwh",
            "eaf_total_electricity_mwh",
            "eaf_liquid_steel_output_t",
            "eaf_dri_input_t",
            "eaf_scrap_input_t",
            "eaf_named_ng_mwh",
            "drp_pellet_input_t",
            "drp_electricity_mwh",
            "drp_named_ng_mwh",
            "bf6_throughput_t",
            "bof_throughput_t",
            "hsm_throughput_t",
            "dsp_output_t",
            "vn25_wag_mwh",
            "vn25_named_ng_mwh",
            "vn25_electricity_mwh",
            "boiler_bfg_mwh",
            "boiler_cog_mwh",
            "boiler_named_ng_mwh",
            "steam_demand_t",
            "steam_supply_t",
            "steam_spill_t",
            "steam_unserved_t",
            "flare_mwh",
        )
        for experiment in experiments.to_dict(orient="records"):
            selected = result_frame[
                result_frame["experiment_id"].eq(experiment["experiment_id"])
            ]
            state = states[str(experiment["experiment_id"])]
            weekly_rows.append(
                {
                    **experiment,
                    "completed_day_count": len(selected),
                    "expected_objective_eur": float(
                        selected["expected_objective_eur"].sum()
                    ),
                    "expected_objective_lower_bound_eur": float(
                        selected["planning_expected_lower_bound_eur"].sum()
                    ),
                    "expected_objective_upper_bound_eur": float(
                        selected["planning_expected_upper_bound_eur"].sum()
                    ),
                    "realised_total_represented_cost_eur": float(
                        selected["realised_total_represented_cost_eur"].sum()
                    ),
                    "absolute_imbalance_mwh": float(
                        selected["absolute_imbalance_mwh"].sum()
                    ),
                    "produced_t": float(selected["produced_t"].sum()),
                    "planning_solver_seconds": float(
                        selected["planning_solver_seconds"].sum()
                    ),
                    "redispatch_solver_seconds": float(
                        selected["redispatch_solver_seconds"].sum()
                    ),
                    "final_executed_hours": state.executed_hours,
                    "state_handoff_pass": state.executed_hours == 168,
                    **{
                        field: float(selected[field].sum())
                        for field in weekly_sum_fields
                    },
                }
            )
        weekly = pd.DataFrame(weekly_rows)
        comparison_rows: list[dict[str, Any]] = []
        for configuration in ("C0", "C1"):
            by_arm = {
                str(row["arm"]): row
                for row in weekly[weekly["configuration"].eq(configuration)].to_dict(
                    orient="records"
                )
            }
            for label, arm_a, arm_b in (
                ("qh_market", "A_hourly", "B_qh_flat"),
                ("shape", "B_qh_flat", "C_qh_shape"),
                ("total", "A_hourly", "C_qh_shape"),
            ):
                a = by_arm[arm_a]
                b = by_arm[arm_b]
                comparison_rows.append(
                    {
                        "configuration": configuration,
                        "comparison": label,
                        "arm_a": arm_a,
                        "arm_b": arm_b,
                        "realised_saving_a_minus_b_eur": float(
                            a["realised_total_represented_cost_eur"]
                            - b["realised_total_represented_cost_eur"]
                        ),
                        "expected_difference_lower_bound_eur": float(
                            a["expected_objective_lower_bound_eur"]
                            - b["expected_objective_upper_bound_eur"]
                        ),
                        "expected_difference_upper_bound_eur": float(
                            a["expected_objective_upper_bound_eur"]
                            - b["expected_objective_lower_bound_eur"]
                        ),
                    }
                )
        production_spread = max(
            float(group["produced_t"].max() - group["produced_t"].min())
            for _, group in weekly.groupby("configuration")
        )
        passed = bool(
            checks
            and all(row["status"] == "pass" for row in checks)
            and all(
                row["status"] == "pass"
                for row in plant_checks
                if bool(row["hard_gate"])
            )
        ) and bool(
            weekly["completed_day_count"].eq(7).all()
            and weekly["state_handoff_pass"].all()
            and result_frame["absolute_imbalance_mwh"]
            .le(ENERGY_TOLERANCE_MWH)
            .all()
            and production_spread <= 1e-5
        )
        if not passed:
            raise BehaviouralValidationError(
                "The completed rolling week failed an aggregate gate."
            )
        _write_csv(output / "rolling_week_results.csv", weekly_rows)
        _write_csv(output / "rolling_week_comparisons.csv", comparison_rows)
        _write_json(
            checkpoint_path,
            {
                "input_fingerprint": fingerprint,
                "completed_case_ids": completed_case_ids,
                "states": {key: value.snapshot() for key, value in states.items()},
                "complete": True,
                "resume_authorized": False,
            },
        )
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "completed_experiment_count": 6,
            "completed_rolling_day_count": 42,
            "maximum_daily_imbalance_mwh": max(
                float(row["absolute_imbalance_mwh"]) for row in results
            ),
            "physical_and_financial_check_count": len(checks),
            "physical_and_financial_failure_count": 0,
            "plant_behavioural_check_count": len(plant_checks),
            "plant_behavioural_hard_failure_count": 0,
            "production_spread_across_arms_t": production_spread,
            "final_test_periods_read_or_solved": False,
            "resume_authorized": False,
        }
        _write_json(output / "rolling_week_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_json(output / "run_summary.json", summary)
        _write_warnings_and_limitations(output, summary)
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": run_id,
                "run_class": declaration["run_class"],
                "lineage_role": declaration["lineage_role"],
                "status": summary["status"],
                "decision": summary["decision"],
                "resume_authorized": False,
                "final_week_matrix_run": False,
                "git_eligible": False,
            },
        )
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="non_final_rolling_week_gate_passed",
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        diagnostic = {
            "error_type": type(exc).__name__,
            "error": str(exc),
            **dict(getattr(exc, "diagnostic", {})),
        }
        summary = {
            **declaration,
            "run_id": run_id,
            "status": (
                "emergency_recourse"
                if isinstance(exc, Phase6DEmergencyRecourse)
                else "blocked"
            ),
            "decision": "BLOCK",
            "completed_rolling_day_count": len(results),
            "diagnostic": diagnostic,
            "resume_authorized": False,
        }
        _write_json(output / "rolling_week_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_json(output / "run_summary.json", summary)
        _write_warnings_and_limitations(output, summary)
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": run_id,
                "run_class": declaration["run_class"],
                "lineage_role": declaration["lineage_role"],
                "status": summary["status"],
                "decision": summary["decision"],
                "resume_authorized": False,
                "final_week_matrix_run": False,
                "git_eligible": False,
            },
        )
        _write_run_control(
            output,
            status=str(summary["status"]),
            resume_authorized=False,
            reason="non_final_rolling_week_gate_failed_closed",
            diagnostic=diagnostic,
        )
        return {"output": str(output), "summary": summary}


def run_full_path_feasibility_behavioural_gate(
    config_path: str | Path = BEHAVIOURAL_CONFIG,
    *,
    run_id: str,
    phase_b_summary_path: str | Path,
) -> dict[str, Any]:
    """Run 9 synthetic and 13 shadow cases, never any final-week case."""

    phase_b_path = _resolve(phase_b_summary_path)
    phase_b = json.loads(phase_b_path.read_text(encoding="utf-8"))
    if (
        phase_b.get("status") != "pass"
        or float(phase_b.get("after_absolute_imbalance_mwh", math.inf))
        > ENERGY_TOLERANCE_MWH
        or phase_b.get("after_minimum_solve_performed") is not False
    ):
        raise BehaviouralValidationError("Phase C requires a proven Phase-B PASS.")
    config = load_behavioural_config(config_path)
    prepared = prepare_behavioural_run(
        config_path,
        run_id=run_id,
        resume=False,
        output_root=config["path_feasibility_output_root"],
    )
    output: Path = prepared["output"]
    patterns = _validation_feasibility_patterns(prepared)
    _write_json(
        output / "feasibility_pattern_manifest.json",
        {
            "pattern_count": len(patterns),
            "patterns": patterns,
            "raw_validation_prices_persisted": False,
            "economic_scenario_probability_assigned": False,
            "final_test_period_source_count": 0,
        },
    )
    manifest: pd.DataFrame = prepared["manifest"]
    selected = pd.concat(
        [
            manifest[manifest["phase"].eq("synthetic")],
            manifest[manifest["phase"].eq("shadow")],
        ],
        ignore_index=True,
    )
    if len(selected) != 22:
        raise BehaviouralValidationError("The full behavioural gate is not 9+13 cases.")
    if selected["final_test_case"].astype(bool).any():
        raise BehaviouralValidationError("A final-test case entered Phase C.")
    eligibility_records = build_plant_eligibility_records(prepared, selected)
    _write_csv(output / "plant_eligibility_records.csv", eligibility_records)
    _write_json(
        output / "plant_eligibility_manifest.json",
        {
            "determination_stage": "pre_solve",
            "record_count": len(eligibility_records),
            "case_count": int(selected["case_id"].nunique()),
            "uses_dispatch_or_actual_prices": False,
            "final_test_case_count": 0,
            "records_sha256": _payload_sha256(eligibility_records),
        },
    )
    _write_json(
        output / "output_declaration.json",
        {
            "output_root": output.relative_to(REPO_ROOT).as_posix(),
            "output_policy": "minimal",
            "run_class": "diagnostic_validation",
            "lineage_role": (
                "validation-derived path-feasibility behavioural gate, not final evidence"
            ),
            "trajectory_count": 22,
            "synthetic_trajectory_count": 9,
            "shadow_trajectory_count": 13,
            "candidate_pattern_count": len(patterns),
            "maximum_augmentation_rounds_per_c1_s10_plan": 3,
            "maximum_patterns_added_per_round": 1,
            "estimated_model_count": "44 baseline plus bounded C1 separation models",
            "estimated_solver_tier_solves": "case-dependent; fail closed at 900 s per tier",
            "estimated_size": "minimal governed diagnostics, normally below 50 MB",
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_authorized_or_scheduled": False,
        },
    )
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    economic_checks: list[dict[str, Any]] = []
    plant_checks: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    try:
        for case in selected.to_dict(orient="records"):
            _assert_run_execution_authorized(output, resume=False)
            if (
                str(case["configuration"]) == "C1"
                and _policy_name(case) in {"H-S10", "QH-S10"}
            ):
                outcome = _run_constraint_generated_case(
                    prepared,
                    case,
                    _case_local_feasibility_patterns(prepared, case),
                )
            else:
                outcome = _run_case(prepared, case)
            result = outcome["result"]
            if float(result["absolute_imbalance_mwh"]) > ENERGY_TOLERANCE_MWH:
                raise BehaviouralValidationError(
                    "A Phase-C case returned positive accepted imbalance."
                )
            results.append(result)
            metrics.extend(outcome["metrics"])
            checks.extend(outcome["checks"])
            solver_rows.append(outcome["solver"])
            _persist_progress(
                output,
                results=results,
                metrics=metrics,
                physical_checks=checks,
                economic_checks=[*economic_checks, *plant_checks],
                solver=solver_rows,
            )
        passed = pd.DataFrame(results)
        synthetic_pass = int(passed["phase"].eq("synthetic").sum())
        shadow_pass = int(passed["phase"].eq("shadow").sum())
        if synthetic_pass != 9 or shadow_pass != 13:
            raise BehaviouralValidationError("Phase C did not complete 9+13 PASS cases.")
        money_tolerance = float(config["gate"]["money_tolerance_eur"])
        economic_checks = evaluate_economic_rationality(
            passed, phase="synthetic", money_tolerance_eur=money_tolerance
        ) + evaluate_economic_rationality(
            passed, phase="shadow", money_tolerance_eur=money_tolerance
        )
        plant_checks = evaluate_plant_behaviour(
            passed, eligibility_records, phase="synthetic"
        ) + evaluate_plant_behaviour(
            passed, eligibility_records, phase="shadow"
        )
        _persist_progress(
            output,
            results=results,
            metrics=metrics,
            physical_checks=checks,
            economic_checks=[*economic_checks, *plant_checks],
            solver=solver_rows,
        )
        _write_csv(output / "plant_behavioural_checks.csv", plant_checks)
        phase_decisions = {
            active_phase: _phase_decision(
                phase=active_phase,
                expected_case_ids=set(
                    selected.loc[
                        selected["phase"].eq(active_phase), "case_id"
                    ].astype(str)
                ),
                results=results,
                physical_checks=checks,
                economic_checks=[*economic_checks, *plant_checks],
            )
            for active_phase in ("synthetic", "shadow")
        }
        if any(row["status"] != "pass" for row in phase_decisions.values()):
            raise BehaviouralValidationError(
                "The full path-feasibility behavioural/plant gate failed closed."
            )
        added_counts = [
            int(row.get("path_feasibility_added_pattern_count", 0))
            for row in results
        ]
        summary = {
            "run_id": run_id,
            "status": "pass",
            "decision": "PASS",
            "synthetic_pass_count": synthetic_pass,
            "shadow_pass_count": shadow_pass,
            "absolute_imbalance_max_mwh": max(
                float(row["absolute_imbalance_mwh"]) for row in results
            ),
            "emergency_recourse_count": 0,
            "candidate_pattern_count": len(patterns),
            "maximum_added_pattern_count_per_case": max(added_counts, default=0),
            "total_case_pattern_augmentations": sum(added_counts),
            "synthetic_gate": phase_decisions["synthetic"],
            "shadow_gate": phase_decisions["shadow"],
            "plant_eligibility_record_count": len(eligibility_records),
            "plant_hard_failure_count": 0,
            "economic_hard_failure_count": 0,
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
            "output_policy": "minimal",
            "run_class": "diagnostic_validation",
            "lineage_role": (
                "validation-derived path-feasibility behavioural gate, not final evidence"
            ),
        }
        _write_json(output / "path_feasibility_behavioural_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="path_feasibility_behavioural_pass_requires_final_week_authorization",
        )
        return {"output": str(output), "summary": summary}
    except Exception as exc:
        diagnostic = getattr(exc, "diagnostic", {})
        summary = {
            "run_id": run_id,
            "status": (
                "path_feasibility_augmentation_incomplete"
                if isinstance(exc, Phase6DPathFeasibilityIncomplete)
                else "blocked"
            ),
            "decision": "BLOCK",
            "completed_case_count": len(results),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "diagnostic": diagnostic,
            "final_test_periods_read_or_solved": False,
            "final_week_matrix_run": False,
            "resume_authorized": False,
        }
        _write_json(output / "path_feasibility_behavioural_summary.json", summary)
        _write_json(output / "gate_summary.json", summary)
        _write_run_control(
            output,
            status=str(summary["status"]),
            resume_authorized=False,
            reason="path_feasibility_behavioural_gate_failed_closed",
            diagnostic=diagnostic,
        )
        raise
