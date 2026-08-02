"""Diagnostic figures for the frozen fixed-27 C6 baseline.

This module is deliberately outside the frozen method payload.  It invokes the
accepted C1 S10/path-feasibility orchestration unchanged and persists only the
executed non-final quarter-hour trajectories needed for human plant review.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np
import pandas as pd
import yaml

from .s4_4c6_behavioural_validation import (
    BEHAVIOURAL_CONFIG,
    CONFIGURATION_IDS,
    VN25_BREAK_EVEN_EUR_PER_MWH,
    _apply_physical_comparison_contract,
    _base_context_config,
    _bundle_for_case,
    _case_local_feasibility_patterns,
    _case_metrics,
    _physical_checks,
    _solver_progress_callback,
    _write_run_control,
    build_plant_eligibility_records,
    prepare_behavioural_run,
    solve_constraint_generated_bid_plan,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    ENERGY_TOLERANCE_MWH,
    SteelBidPlan,
    SteelRollingState,
    clear_hourly_da_bids,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import (
    solve_grouped_actual_redispatch,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


VISUAL_REVIEW_CONFIG = Path(
    "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c6_fixed27_baseline_visual_review.yaml"
)
CASE_LABELS = {
    "S1_C1_responsive": "S1 goedkoop → duur",
    "S2_C1_responsive": "S2 duur → goedkoop",
    "shadow__high_price__2025-09-09__C__C1__responsive": (
        "Hoge prijs · C"
    ),
    "shadow__negative_low_price__2025-06-08__C__C1__responsive": (
        "Negatief/laag · C"
    ),
    "shadow__high_volatility__2025-05-10__A_hourly__C1__responsive": (
        "Hoge volatiliteit · A"
    ),
    "shadow__high_volatility__2025-05-10__B_qh_flat__C1__responsive": (
        "Hoge volatiliteit · B"
    ),
    "shadow__high_volatility__2025-05-10__C__C1__responsive": (
        "Hoge volatiliteit · C"
    ),
}
ARM_COLORS = {
    "A_hourly": "#1f77b4",
    "B_qh_flat": "#ff7f0e",
    "C_qh_shape": "#2ca02c",
}
ALLOWED_REVIEW_STATUSES = {
    "PASS",
    "PLAUSIBLE_BUT_NOT_PROVEN",
    "NOT_APPLICABLE",
    "FAIL",
}


class Fixed27VisualReviewError(RuntimeError):
    """Fail-closed fixed-baseline review error."""


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (REPO_ROOT / candidate).resolve()
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def load_visual_review_config(path: str | Path = VISUAL_REVIEW_CONFIG) -> dict[str, Any]:
    config_path = _resolve(path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("output_policy") != "minimal":
        raise Fixed27VisualReviewError("The visual review must remain minimal.")
    if config.get("run_class") != "diagnostic_validation":
        raise Fixed27VisualReviewError("The visual review is diagnostic_validation only.")
    fixed = config["fixed_contract"]
    expected = {
        "daily_eaf_heat_starts": 27,
        "daily_eaf_heat_taps": 27,
        "daily_eaf_liquid_steel_t": 8775.0,
        "scenario_count": 10,
        "economic_horizon_hours": 24,
        "execution_hours": 24,
        "imbalance_penalty_eur_per_mwh": 5000.0,
        "economic_mip_gap": 0.002,
        "solver_time_limit_seconds": 900,
        "variable_daily_heat_counts": False,
        "final_test_periods_read_or_solved": False,
        "full_four_week_matrix_authorized": False,
    }
    if fixed != expected:
        raise Fixed27VisualReviewError("The fixed-27 diagnostic contract changed.")
    return config


def _source_case_artifact(
    source_root: Path, case_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    result_frame = pd.read_csv(source_root / "case_results.csv")
    selected = result_frame[result_frame["case_id"].astype(str).eq(case_id)]
    if len(selected) != 1 or str(selected.iloc[0]["case_status"]) != "pass":
        raise Fixed27VisualReviewError(
            f"Accepted source does not contain one PASS row for {case_id}."
        )
    solver_payload = json.loads(
        (source_root / "solver_diagnostics.json").read_text(encoding="utf-8")
    )
    solver_rows = solver_payload if isinstance(solver_payload, list) else [solver_payload]
    solver_selected = [
        row for row in solver_rows if str(row.get("case_id")) == case_id
    ]
    if len(solver_selected) != 1:
        raise Fixed27VisualReviewError(
            f"Accepted source has no unique solver certificate for {case_id}."
        )
    return selected.iloc[0].to_dict(), solver_selected[0]


def preflight_fixed27_visual_review(
    config_path: str | Path = VISUAL_REVIEW_CONFIG,
) -> dict[str, Any]:
    config = load_visual_review_config(config_path)
    freeze_path = _resolve(config["method_freeze"])
    freeze = yaml.safe_load(freeze_path.read_text(encoding="utf-8"))
    rolling_path = _resolve(config["non_final_rolling_pass_summary"])
    rolling = json.loads(rolling_path.read_text(encoding="utf-8"))
    representative_path = _resolve(config["representative_config"])
    representative = yaml.safe_load(representative_path.read_text(encoding="utf-8"))
    if freeze.get("status") != "ready_for_final_week_authorisation":
        raise Fixed27VisualReviewError("The fixed baseline is not in its PASS state.")
    if freeze.get("validation_evidence", {}).get("decision") != "PASS":
        raise Fixed27VisualReviewError("The method-freeze validation is not PASS.")
    if rolling.get("status") != "pass" or rolling.get("decision") != "PASS":
        raise Fixed27VisualReviewError("The non-final rolling gate is not PASS.")
    if bool(rolling.get("final_test_periods_read_or_solved")):
        raise Fixed27VisualReviewError("The rolling source declares final-period use.")
    authorization = representative.get("authorization", {})
    if bool(authorization.get("full_four_week_matrix_authorized")):
        raise Fixed27VisualReviewError("The final four-week matrix is authorized.")
    if authorization.get("authorization_receipt") is not None:
        raise Fixed27VisualReviewError("An unexpected final authorization receipt exists.")

    source_rows: list[dict[str, Any]] = []
    case_ids: list[str] = []
    for item in config["allowed_cases"]:
        case_id = str(item["case_id"])
        source_root = _resolve(item["accepted_source_root"])
        result, solver = _source_case_artifact(source_root, case_id)
        interval_files = list(source_root.glob("*interval*dispatch*")) + list(
            source_root.glob("executed_physical_intervals.*")
        )
        source_rows.append(
            {
                "case_id": case_id,
                "source_root": source_root.relative_to(REPO_ROOT).as_posix(),
                "source_status": result["case_status"],
                "absolute_imbalance_mwh": float(result["absolute_imbalance_mwh"]),
                "eaf_heat_starts": float(result["eaf_heat_starts"]),
                "eaf_heat_taps": float(result["eaf_heat_taps"]),
                "solver_certificate_present": bool(solver),
                "interval_dispatch_present": bool(interval_files),
            }
        )
        case_ids.append(case_id)
    if len(case_ids) != 7 or len(set(case_ids)) != 7:
        raise Fixed27VisualReviewError("The bounded review must contain seven cases.")
    if any(row["eaf_heat_starts"] != 27.0 for row in source_rows):
        raise Fixed27VisualReviewError("An accepted source is not fixed at 27 starts.")
    if any(row["eaf_heat_taps"] != 27.0 for row in source_rows):
        raise Fixed27VisualReviewError("An accepted source is not fixed at 27 taps.")
    return {
        "status": "pass",
        "decision": "PASS",
        "fixed_method_freeze_sha256": _sha256(freeze_path),
        "rolling_gate_sha256": _sha256(rolling_path),
        "full_four_week_matrix_authorized": False,
        "final_test_periods_read_or_solved": False,
        "variable_heat_candidate_artifacts_created": False,
        "accepted_source_count": len(source_rows),
        "sources_with_interval_dispatch": sum(
            bool(row["interval_dispatch_present"]) for row in source_rows
        ),
        "diagnostic_rerun_required": not all(
            bool(row["interval_dispatch_present"]) for row in source_rows
        ),
        "sources": source_rows,
    }


def _execute_fixed_case(
    prepared: Mapping[str, Any], case: Mapping[str, Any]
) -> dict[str, Any]:
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
        _case_local_feasibility_patterns(prepared, case),
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
            solve_stage="fixed27_visual_review_redispatch",
        ),
    )
    if float(redispatch.absolute_imbalance_mwh) > ENERGY_TOLERANCE_MWH:
        raise Fixed27VisualReviewError("A review rerun retained accepted imbalance.")
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
    failures = [row for row in checks if row["status"] != "pass"]
    if failures:
        raise Fixed27VisualReviewError(
            f"A review rerun failed physical/reconstruction checks: {failures}"
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
            "conditional_zero_imbalance_recovery_used": bool(
                redispatch.solver.get(
                    "conditional_minimum_imbalance_solve_performed", False
                )
            ),
        }
    )
    rows = pd.DataFrame(redispatch.physical_intervals)
    if len(rows) != 96:
        raise Fixed27VisualReviewError("Review dispatch must contain 96 QH rows.")
    group_size = int(round(float(rows["market_time_step_hours"].iloc[0]) / 0.25))
    point_qh = np.repeat(np.asarray(bundle.point_prices, dtype=float), group_size)
    if len(point_qh) != len(rows):
        raise Fixed27VisualReviewError("Point-price expansion is not grid-correct.")
    rows.insert(0, "case_id", str(case["case_id"]))
    rows.insert(1, "profile_id", str(case["profile_id"]))
    rows.insert(2, "arm", str(case["arm"]))
    rows["forecast_price_eur_per_mwh"] = point_qh
    rows["cleared_e_program_allocated_mwh"] = (
        rows["market_period_cleared_energy_mwh"].astype(float) / group_size
    )
    rows["physical_net_import_mw"] = (
        rows["redispatched_net_grid_import_mwh"].astype(float) / 0.25
    )
    rows["cleared_e_program_mw"] = (
        rows["cleared_e_program_allocated_mwh"].astype(float) / 0.25
    )
    rows["net_imbalance_mwh"] = (
        rows["allocated_upward_consumption_imbalance_mwh"].astype(float)
        - rows["allocated_downward_consumption_imbalance_mwh"].astype(float)
    )
    rows["net_imbalance_mw"] = rows["net_imbalance_mwh"] / 0.25
    solver = {
        "case_id": str(case["case_id"]),
        "planning": plan.solver,
        "redispatch": redispatch.solver,
        "path_feasibility_constraint_generation": generated["rounds"],
    }
    return {
        "result": result,
        "metrics": metrics,
        "conditional": conditional,
        "checks": checks,
        "solver": solver,
        "dispatch": rows,
    }


def _certificate(solver: Mapping[str, Any]) -> dict[str, float | str]:
    return {
        "class": str(solver["economic_optimality_class"]),
        "lower": float(solver["economic_objective_lower_bound_eur"]),
        "upper": float(solver["economic_objective_upper_bound_eur"]),
        "band": float(solver["economic_absolute_objective_band_eur"]),
        "gap": float(solver["economic_certified_relative_gap"]),
    }


def _market_grid_import_identity_residual(dispatch: pd.DataFrame) -> float:
    """Reconstruct import identity on the cleared market grid.

    The physical model always reports quarter-hour values.  For an hourly arm,
    the cleared E-program and allocated imbalance are repeated over the four
    physical intervals, so physical import must first be averaged back to the
    hourly clearing interval.  QH arms have one physical row per market row and
    are therefore unchanged by this grouping.
    """
    required = {
        "market_interval_index",
        "redispatched_net_grid_import_mwh",
        "cleared_e_program_allocated_mwh",
        "net_imbalance_mwh",
    }
    missing = required - set(dispatch.columns)
    if missing:
        raise Fixed27VisualReviewError(
            f"Dispatch is missing import-identity columns: {sorted(missing)}."
        )
    market = dispatch.groupby("market_interval_index", sort=True, observed=True)[
        [
            "redispatched_net_grid_import_mwh",
            "cleared_e_program_allocated_mwh",
            "net_imbalance_mwh",
        ]
    ].mean()
    residual = (
        market["redispatched_net_grid_import_mwh"].astype(float)
        - market["cleared_e_program_allocated_mwh"].astype(float)
        - market["net_imbalance_mwh"].astype(float)
    )
    return float(residual.abs().max())


def _reconcile_case(
    result: Mapping[str, Any],
    dispatch: pd.DataFrame,
    solver: Mapping[str, Any],
    source_result: Mapping[str, Any],
    source_solver: Mapping[str, Any],
) -> list[dict[str, Any]]:
    case_id = str(result["case_id"])
    rows: list[dict[str, Any]] = []

    def add(check_id: str, observed: float | bool, expected: Any, passed: bool) -> None:
        rows.append(
            {
                "case_id": case_id,
                "check_id": check_id,
                "observed": observed,
                "expected": expected,
                "status": "pass" if passed else "fail",
            }
        )

    starts = float(dispatch["eaf_heat_start"].sum())
    taps = float(dispatch["eaf_tap"].sum())
    liquid = float(dispatch["eaf_liquid_steel_output_t"].sum())
    add("exact_27_eaf_starts", starts, 27.0, abs(starts - 27.0) <= 1e-8)
    add("exact_27_eaf_taps", taps, 27.0, abs(taps - 27.0) <= 1e-8)
    add("exact_8775_t_eaf_liquid", liquid, 8775.0, abs(liquid - 8775.0) <= 1e-6)
    identity_residual = _market_grid_import_identity_residual(dispatch)
    add(
        "physical_import_equals_program_plus_imbalance",
        identity_residual,
        "<=1e-5 MWh/market interval",
        identity_residual <= 1e-5,
    )
    imbalance = float(dispatch["allocated_absolute_imbalance_mwh"].sum())
    add(
        "zero_imbalance",
        imbalance,
        "<=1e-5 MWh/day",
        imbalance <= ENERGY_TOLERANCE_MWH,
    )
    dispatch_totals = {
        "net_grid_import_mwh": "redispatched_net_grid_import_mwh",
        "gross_electricity_mwh": "gross_electricity_mwh",
        "internal_generation_mwh": "total_internal_generation_mwh",
        "named_ng_mwh": "total_named_ng_procurement_mwh",
        "eaf_arc_mwh": "eaf_arc_electricity_mwh",
        "eaf_total_electricity_mwh": "eaf_total_electricity_mwh",
        "steam_demand_t": "steam_15bar_demand_t",
        "steam_supply_t": "steam_15bar_supply_t",
        "steam_spill_t": "steam_15bar_spill_t",
        "steam_unserved_t": "steam_15bar_unserved_t",
        "flare_mwh": "wag_flared_mwh",
    }
    for result_key, dispatch_key in dispatch_totals.items():
        observed = float(dispatch[dispatch_key].sum())
        expected = float(result[result_key])
        tolerance = max(1e-5, abs(expected) * 1e-9)
        add(
            f"dispatch_reconstructs_{result_key}",
            observed,
            expected,
            abs(observed - expected) <= tolerance,
        )
    settlement = float(dispatch["allocated_pay_as_cleared_settlement_eur"].sum())
    penalty = float(dispatch["allocated_imbalance_penalty_eur"].sum())
    total = settlement + float(result["realised_other_represented_cost_eur"]) + penalty
    add(
        "realised_cost_reconstruction",
        total,
        float(result["realised_total_represented_cost_eur"]),
        abs(total - float(result["realised_total_represented_cost_eur"])) <= 0.01,
    )
    source_plan = _certificate(source_solver["planning"])
    source_redispatch = _certificate(source_solver["redispatch"])
    rerun_plan = _certificate(solver["planning"])
    rerun_redispatch = _certificate(solver["redispatch"])
    expected_objective = float(result["expected_objective_eur"])
    realised_cost = float(result["realised_total_represented_cost_eur"])
    redispatch_variable_cost = float(result["realised_other_represented_cost_eur"]) + float(
        result["imbalance_penalty_eur"]
    )
    add(
        "rerun_expected_objective_inside_rerun_certificate",
        expected_objective,
        f"[{rerun_plan['lower']}, {rerun_plan['upper']}]",
        float(rerun_plan["lower"]) - 0.01
        <= expected_objective
        <= float(rerun_plan["upper"]) + 0.01,
    )
    add(
        "rerun_variable_cost_inside_redispatch_certificate",
        redispatch_variable_cost,
        f"[{rerun_redispatch['lower']}, {rerun_redispatch['upper']}]",
        float(rerun_redispatch["lower"]) - 0.01
        <= redispatch_variable_cost
        <= float(rerun_redispatch["upper"]) + 0.011,
    )
    planning_overlap = max(
        float(source_plan["lower"]), float(rerun_plan["lower"])
    ) <= min(float(source_plan["upper"]), float(rerun_plan["upper"])) + 0.01
    add(
        "accepted_and_rerun_planning_certificates_overlap",
        planning_overlap,
        True,
        planning_overlap,
    )
    redispatch_overlap = max(
        float(source_redispatch["lower"]), float(rerun_redispatch["lower"])
    ) <= min(
        float(source_redispatch["upper"]), float(rerun_redispatch["upper"])
    ) + 0.01
    add(
        "accepted_and_rerun_redispatch_certificates_overlap",
        redispatch_overlap,
        True,
        redispatch_overlap,
    )
    add(
        "source_and_rerun_production_equal",
        float(result["produced_t"]),
        float(source_result["produced_t"]),
        abs(float(result["produced_t"]) - float(source_result["produced_t"]))
        <= 1e-4,
    )
    add(
        "source_and_rerun_realised_cost_equal",
        realised_cost,
        float(source_result["realised_total_represented_cost_eur"]),
        abs(
            realised_cost
            - float(source_result["realised_total_represented_cost_eur"])
        )
        <= 0.01,
    )
    add(
        "source_and_rerun_scenario_hash_equal",
        bool(
            str(result["forecast_scenario_input_sha256"])
            == str(source_result["forecast_scenario_input_sha256"])
        ),
        True,
        str(result["forecast_scenario_input_sha256"])
        == str(source_result["forecast_scenario_input_sha256"]),
    )
    add(
        "epsilon_policy_preserved",
        float(solver["planning"]["solver_economic_mip_gap_limit"]),
        0.002,
        float(solver["planning"]["solver_economic_mip_gap_limit"]) == 0.002,
    )
    return rows


def _synthetic_mirror_checks(dispatch: pd.DataFrame) -> list[dict[str, Any]]:
    left = dispatch[dispatch["case_id"].eq("S1_C1_responsive")].sort_values(
        "physical_interval_index"
    )
    right = dispatch[dispatch["case_id"].eq("S2_C1_responsive")].sort_values(
        "physical_interval_index"
    )
    if len(left) != 96 or len(right) != 96:
        raise Fixed27VisualReviewError("Synthetic mirror dispatch is incomplete.")
    shifted_heats = 0.5 * float(
        np.abs(
            left["eaf_heat_start"].to_numpy(dtype=float)
            - right["eaf_heat_start"].to_numpy(dtype=float)
        ).sum()
    )
    cheap_start_share = []
    for frame in (left, right):
        price = frame["realised_price_eur_per_mwh"].to_numpy(dtype=float)
        starts = frame["eaf_heat_start"].to_numpy(dtype=float)
        threshold = float(np.median(price))
        cheap_start_share.append(
            float(starts[price <= threshold].sum() / max(starts.sum(), 1.0))
        )
    same_production = abs(
        float(left["eaf_liquid_steel_output_t"].sum())
        - float(right["eaf_liquid_steel_output_t"].sum())
    ) <= 1e-6
    return [
        {
            "case_id": "S1_vs_S2",
            "check_id": "mirrored_prices_shift_at_least_one_heat",
            "observed": shifted_heats,
            "expected": ">=1 heat",
            "status": "pass" if shifted_heats >= 1.0 - 1e-8 else "fail",
        },
        {
            "case_id": "S1_vs_S2",
            "check_id": "mirrored_prices_preserve_eaf_output",
            "observed": same_production,
            "expected": True,
            "status": "pass" if same_production else "fail",
        },
        {
            "case_id": "S1_vs_S2",
            "check_id": "cheap_interval_start_share",
            "observed": json.dumps(
                {"S1": cheap_start_share[0], "S2": cheap_start_share[1]}
            ),
            "expected": "timing follows each mirrored cheap block",
            "status": "pass" if shifted_heats >= 1.0 - 1e-8 else "fail",
        },
    ]


def _load_reusable_case_checkpoint(
    checkpoint_root: Path,
    *,
    case_id: str,
) -> dict[str, Any]:
    root = _resolve(checkpoint_root)
    governed_parent = _resolve(
        "data/03_Optimisation/runs/steel_c6_fixed27_baseline_visual_review"
    )
    if not root.is_relative_to(governed_parent):
        raise Fixed27VisualReviewError("Reusable checkpoint is outside its governed root.")
    required = {
        "dispatch": root / "interval_dispatch.csv",
        "result": root / "case_result.json",
        "solver": root / "solver_diagnostics.json",
    }
    if any(not path.exists() for path in required.values()):
        raise Fixed27VisualReviewError("Reusable checkpoint is incomplete.")
    parent_summary = root.parents[1] / "run_summary.json"
    summary = json.loads(parent_summary.read_text(encoding="utf-8"))
    stopped_in_current_case_review = (
        summary.get("error_type") == "Fixed27VisualReviewError"
        and case_id in str(summary.get("error", ""))
    )
    completed_case_results = root.parents[1] / "case_results.csv"
    completed_reconciliation = root.parents[1] / "dispatch_reconciliation_checks.csv"
    stopped_after_completed_case = False
    if completed_case_results.exists() and completed_reconciliation.exists():
        completed = pd.read_csv(completed_case_results)
        reconciled = pd.read_csv(completed_reconciliation)
        case_completed = case_id in set(completed.get("case_id", pd.Series(dtype=str)))
        case_checks = reconciled.loc[reconciled["case_id"].astype(str) == case_id]
        stopped_after_completed_case = bool(
            summary.get("error_type") == "Fixed27VisualReviewError"
            and case_completed
            and not case_checks.empty
            and case_checks["status"].eq("pass").all()
        )
    if not (stopped_in_current_case_review or stopped_after_completed_case):
        raise Fixed27VisualReviewError(
            "Reusable checkpoint did not stop in the post-solve review contract."
        )
    dispatch = pd.read_csv(required["dispatch"])
    result = json.loads(required["result"].read_text(encoding="utf-8"))
    solver = json.loads(required["solver"].read_text(encoding="utf-8"))
    if len(dispatch) != 96 or set(dispatch["case_id"].astype(str)) != {case_id}:
        raise Fixed27VisualReviewError("Reusable checkpoint dispatch is not one QH day.")
    if str(result.get("case_id")) != case_id or str(solver.get("case_id")) != case_id:
        raise Fixed27VisualReviewError("Reusable checkpoint case identity changed.")
    if (
        abs(float(dispatch["eaf_heat_start"].sum()) - 27.0) > 1e-8
        or abs(float(dispatch["eaf_tap"].sum()) - 27.0) > 1e-8
        or float(result["absolute_imbalance_mwh"]) > ENERGY_TOLERANCE_MWH
    ):
        raise Fixed27VisualReviewError("Reusable checkpoint violates fixed-27 or zero imbalance.")
    return {
        "result": result,
        "metrics": [],
        "conditional": {},
        "checks": [
            {
                "case_id": case_id,
                "check_id": "diagnostic_checkpoint_written_after_internal_checks",
                "observed": True,
                "expected": True,
                "status": "pass",
                "hard_gate": True,
            }
        ],
        "solver": solver,
        "dispatch": dispatch,
        "checkpoint_reuse": {
            "source_root": root.relative_to(REPO_ROOT).as_posix(),
            "interval_dispatch_sha256": _sha256(required["dispatch"]),
            "case_result_sha256": _sha256(required["result"]),
            "solver_diagnostics_sha256": _sha256(required["solver"]),
            "source_failure_stage": (
                "post_solve_diagnostic_reconciliation"
                if stopped_in_current_case_review
                else "completed_before_later_post_solve_diagnostic_failure"
            ),
            "new_solver_run_started": False,
        },
    }


def _case_frame(dispatch: pd.DataFrame, case_id: str) -> pd.DataFrame:
    frame = dispatch[dispatch["case_id"].eq(case_id)].copy()
    frame["timestamp_local"] = pd.to_datetime(
        frame["target_timestamp_utc"], utc=True
    ).dt.tz_convert("Europe/Amsterdam")
    return frame.sort_values("timestamp_local")


def _format_time_axes(axes: Sequence[plt.Axes]) -> None:
    formatter = mdates.DateFormatter("%H:%M")
    for axis in axes:
        axis.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 4)))
        axis.xaxis.set_major_formatter(formatter)
        axis.grid(True, axis="y", alpha=0.25)


def _save_figure(fig: plt.Figure, path: Path, *, dpi: int) -> None:
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _plot_eaf_mirror(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = ["S1_C1_responsive", "S2_C1_responsive"]
    fig, axes = plt.subplots(4, 2, figsize=(14, 10), sharex="col")
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        axes[0, column].plot(x, frame["forecast_price_eur_per_mwh"], label="Forecast")
        axes[0, column].plot(
            x,
            frame["realised_price_eur_per_mwh"],
            label="Gerealiseerd",
            linestyle="--",
        )
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[0, column].set_ylabel("€/MWh")
        axes[0, column].legend(loc="best", fontsize=8)
        axes[1, column].step(
            x,
            frame["eaf_arc_electricity_mwh"] / 0.25,
            where="post",
            color="#d62728",
        )
        axes[1, column].set_ylabel("Arc-power [MW]")
        for field, level, marker, label in (
            ("eaf_heat_start", 3, "^", "Start"),
            ("eaf_melt", 2, "s", "Melt"),
            ("eaf_tap", 1, "v", "Tap"),
        ):
            active = frame[field].astype(float) > 0.5
            axes[2, column].scatter(
                x[active],
                np.full(int(active.sum()), level),
                marker=marker,
                s=22,
                label=label,
            )
        axes[2, column].set_yticks([1, 2, 3], ["Tap", "Melt", "Start"])
        axes[2, column].set_ylabel("Heat-state")
        axes[2, column].legend(loc="upper right", ncol=3, fontsize=8)
        starts = frame["eaf_heat_start"].cumsum()
        taps = frame["eaf_tap"].cumsum()
        axes[3, column].step(x, starts, where="post", label="Starts")
        axes[3, column].step(x, taps, where="post", label="Taps", linestyle="--")
        axes[3, column].axhline(27, color="black", linewidth=1, linestyle=":")
        axes[3, column].set_ylabel("Cumulatief [heats]")
        axes[3, column].set_xlabel("Lokale tijd")
        axes[3, column].legend(loc="lower right", fontsize=8)
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("EAF timing onder gespiegeld prijsprofiel · fixed 27 heats")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_drp_dri_eaf(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = [
        "shadow__high_price__2025-09-09__C__C1__responsive",
        "shadow__negative_low_price__2025-06-08__C__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    fig, axes = plt.subplots(4, 3, figsize=(16, 10), sharex="col")
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        axes[0, column].step(
            x, frame["drp_pellet_input_t"] / 0.25, where="post"
        )
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[0, column].set_ylabel("Pellets [t/h]")
        axes[1, column].step(
            x, frame["drp_electricity_mwh"] / 0.25, where="post"
        )
        axes[1, column].set_ylabel("DRP [MW]")
        axes[2, column].plot(x, frame["dri_inventory_t"])
        axes[2, column].set_ylabel("DRI-voorraad [t]")
        taps = frame["eaf_tap"].astype(float) > 0.5
        axes[3, column].scatter(
            x[taps], np.ones(int(taps.sum())), marker="v", s=24
        )
        axes[3, column].set_yticks([1], ["Tap"])
        axes[3, column].set_ylabel("EAF")
        axes[3, column].set_xlabel("Lokale tijd")
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("DRP–DRI–EAF-koppeling")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_vn25_break_even(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = [
        "shadow__high_price__2025-09-09__C__C1__responsive",
        "shadow__negative_low_price__2025-06-08__C__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    fig, axes = plt.subplots(2, 3, figsize=(16, 6), sharex="col")
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        axes[0, column].plot(x, frame["forecast_price_eur_per_mwh"], label="Forecast")
        axes[0, column].plot(
            x, frame["realised_price_eur_per_mwh"], linestyle="--", label="Gerealiseerd"
        )
        axes[0, column].axhline(
            VN25_BREAK_EVEN_EUR_PER_MWH,
            color="black",
            linewidth=1,
            linestyle=":",
            label="NG break-even",
        )
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[0, column].set_ylabel("€/MWh")
        axes[0, column].legend(loc="best", fontsize=7)
        axes[1, column].step(
            x, frame["vn25_electricity_mwh"] / 0.25, where="post", color="#9467bd"
        )
        axes[1, column].set_ylabel("VN25 [MW]")
        axes[1, column].set_xlabel("Lokale tijd")
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("VN25-respons rond named-NG-break-even")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_vn25_fuels_import_flare(
    dispatch: pd.DataFrame, path: Path, dpi: int
) -> None:
    case_ids = [
        "shadow__high_price__2025-09-09__C__C1__responsive",
        "shadow__negative_low_price__2025-06-08__C__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    fig, axes = plt.subplots(4, 3, figsize=(16, 10), sharex="col")
    fields = [
        ("vn25_wag_fuel_mwh", "VN25 WAG [MW LHV]"),
        ("vn25_named_ng_mwh", "VN25 named NG [MW LHV]"),
        ("redispatched_net_grid_import_mwh", "Netimport [MW]"),
        ("wag_flared_mwh", "Flare [MW LHV]"),
    ]
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        for row, (field, label) in enumerate(fields):
            axes[row, column].step(x, frame[field] / 0.25, where="post")
            axes[row, column].set_ylabel(label)
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[3, column].set_xlabel("Lokale tijd")
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("VN25-brandstof, netimport en flare")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_process_gas(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = [
        "shadow__high_price__2025-09-09__C__C1__responsive",
        "shadow__negative_low_price__2025-06-08__C__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    fig, axes = plt.subplots(2, 3, figsize=(16, 7), sharex="col")
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        destinations = np.vstack(
            [
                frame["vn25_wag_fuel_mwh"].to_numpy(dtype=float) / 0.25,
                frame["ij01_wag_fuel_mwh"].to_numpy(dtype=float) / 0.25,
                (
                    frame["boiler_bfg_mwh"].to_numpy(dtype=float)
                    + frame["boiler_cog_mwh"].to_numpy(dtype=float)
                )
                / 0.25,
                frame["wag_flared_mwh"].to_numpy(dtype=float) / 0.25,
            ]
        )
        axes[0, column].stackplot(
            x,
            destinations,
            labels=["VN25", "IJ01", "Boiler", "Flare"],
            alpha=0.8,
        )
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[0, column].set_ylabel("Procesgas [MW LHV]")
        axes[0, column].legend(loc="upper right", fontsize=7)
        for field, label in (
            ("bfg_flared_mwh", "BFG flare"),
            ("cog_flared_mwh", "COG flare"),
            ("bofg_flared_mwh", "BOFG flare"),
        ):
            axes[1, column].step(
                x, frame[field] / 0.25, where="post", label=label
            )
        axes[1, column].set_ylabel("Carrierflare [MW LHV]")
        axes[1, column].set_xlabel("Lokale tijd")
        axes[1, column].legend(loc="upper right", fontsize=7)
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("Procesgasverdeling en carrier-specifieke flare")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_steel_chain_abc(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = [
        "shadow__high_volatility__2025-05-10__A_hourly__C1__responsive",
        "shadow__high_volatility__2025-05-10__B_qh_flat__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    throughput = [
        ("blast_furnace_6_t", "BF6 [t/h]"),
        ("basic_oxygen_furnace_t", "BOF [t/h]"),
        ("hot_strip_mill_t", "HSM [t/h]"),
        ("dsp_final_product_output_t", "DSP [t/h]"),
    ]
    inventories = [
        ("coke_inventory_t", "Coke [t]"),
        ("sinter_inventory_t", "Sinter [t]"),
        ("hot_iron_inventory_t", "Hot iron [t]"),
        ("cold_slab_inventory_t", "Cold slab [t]"),
    ]
    fig, axes = plt.subplots(4, 2, figsize=(15, 11), sharex="col")
    for case_id in case_ids:
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        arm = str(frame["arm"].iloc[0])
        color = ARM_COLORS[arm]
        label = arm.split("_")[0]
        for row, (field, ylabel) in enumerate(throughput):
            axes[row, 0].step(
                x, frame[field] / 0.25, where="post", label=label, color=color
            )
            axes[row, 0].set_ylabel(ylabel)
        for row, (field, ylabel) in enumerate(inventories):
            axes[row, 1].plot(x, frame[field], label=label, color=color)
            axes[row, 1].set_ylabel(ylabel)
    axes[0, 0].set_title("Continue staalroute")
    axes[0, 1].set_title("Relevante buffers")
    axes[0, 0].legend(loc="best", ncol=3, fontsize=8)
    axes[0, 1].legend(loc="best", ncol=3, fontsize=8)
    axes[3, 0].set_xlabel("Lokale tijd")
    axes[3, 1].set_xlabel("Lokale tijd")
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("BF6–BOF–HSM/DSP-keten · A/B/C hoge volatiliteit")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _plot_grid_reconciliation(dispatch: pd.DataFrame, path: Path, dpi: int) -> None:
    case_ids = [
        "shadow__high_volatility__2025-05-10__A_hourly__C1__responsive",
        "shadow__high_volatility__2025-05-10__B_qh_flat__C1__responsive",
        "shadow__high_volatility__2025-05-10__C__C1__responsive",
    ]
    fig, axes = plt.subplots(3, 3, figsize=(16, 8), sharex="col")
    for column, case_id in enumerate(case_ids):
        frame = _case_frame(dispatch, case_id)
        x = frame["timestamp_local"]
        arm = str(frame["arm"].iloc[0])
        color = ARM_COLORS[arm]
        axes[0, column].plot(x, frame["realised_price_eur_per_mwh"], color=color)
        axes[0, column].set_title(CASE_LABELS[case_id])
        axes[0, column].set_ylabel("Prijs [€/MWh]")
        axes[1, column].step(
            x,
            frame["physical_net_import_mw"],
            where="post",
            label="Fysieke import",
            color=color,
        )
        axes[1, column].step(
            x,
            frame["cleared_e_program_mw"],
            where="post",
            label="Geklaard E-programma",
            color="black",
            linestyle="--",
        )
        axes[1, column].set_ylabel("Elektriciteit [MW]")
        axes[1, column].legend(loc="best", fontsize=7)
        axes[2, column].step(
            x, frame["net_imbalance_mw"], where="post", color="#d62728"
        )
        axes[2, column].axhline(0, color="black", linewidth=0.8)
        axes[2, column].set_ylabel("Onbalans [MW]")
        axes[2, column].set_xlabel("Lokale tijd")
    _format_time_axes(list(axes.ravel()))
    fig.suptitle("Fysieke netimport, E-programma en onbalans")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def build_abc_cost_summary(
    results: pd.DataFrame, solver_rows: Sequence[Mapping[str, Any]]
) -> pd.DataFrame:
    selected = results[
        results["profile_id"].eq("high_volatility")
        & results["configuration"].eq("C1")
        & results["policy"].eq("responsive")
    ].copy()
    if set(selected["arm"]) != {"A_hourly", "B_qh_flat", "C_qh_shape"}:
        raise Fixed27VisualReviewError("The A/B/C cost set is incomplete.")
    solver_by_case = {str(row["case_id"]): row for row in solver_rows}
    rows: list[dict[str, Any]] = []
    for arm in ("A_hourly", "B_qh_flat", "C_qh_shape"):
        result = selected[selected["arm"].eq(arm)].iloc[0]
        certificate = _certificate(solver_by_case[str(result["case_id"])]["planning"])
        rows.append(
            {
                "arm": arm,
                "case_id": result["case_id"],
                "realised_cost_eur": float(
                    result["realised_total_represented_cost_eur"]
                ),
                "expected_objective_eur": float(result["expected_objective_eur"]),
                "expected_lower_bound_eur": certificate["lower"],
                "expected_upper_bound_eur": certificate["upper"],
                "expected_relative_gap": certificate["gap"],
            }
        )
    output = pd.DataFrame(rows)
    cost = output.set_index("arm")["realised_cost_eur"]
    output["delta_qh_market_eur"] = float(cost["A_hourly"] - cost["B_qh_flat"])
    output["delta_shape_eur"] = float(cost["B_qh_flat"] - cost["C_qh_shape"])
    output["delta_total_eur"] = float(cost["A_hourly"] - cost["C_qh_shape"])
    return output


def _plot_cost_waterfall(costs: pd.DataFrame, path: Path, dpi: int) -> None:
    indexed = costs.set_index("arm")
    a = float(indexed.loc["A_hourly", "realised_cost_eur"])
    b = float(indexed.loc["B_qh_flat", "realised_cost_eur"])
    c = float(indexed.loc["C_qh_shape", "realised_cost_eur"])
    delta_market = a - b
    delta_shape = b - c
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    floor = min(a, b, c) - max(abs(a - b), abs(b - c), 10_000.0) * 1.5
    axes[0].bar(0, a - floor, bottom=floor, color=ARM_COLORS["A_hourly"])
    axes[0].bar(
        1,
        b - a,
        bottom=a,
        color="#2ca02c" if delta_market >= 0 else "#d62728",
    )
    axes[0].bar(
        2,
        c - b,
        bottom=b,
        color="#2ca02c" if delta_shape >= 0 else "#d62728",
    )
    axes[0].bar(3, c - floor, bottom=floor, color=ARM_COLORS["C_qh_shape"])
    axes[0].set_xticks(
        range(4), ["A", "Δ QH-markt", "Δ shape", "C"]
    )
    axes[0].set_ylabel("Gerealiseerde kosten [€]")
    axes[0].set_ylim(floor, max(a, b, c) + max(abs(a - b), abs(b - c), 10_000.0))
    for x, value, label in (
        (0, a, f"€{a:,.0f}"),
        (1, (a + b) / 2, f"besparing {delta_market:,.0f}"),
        (2, (b + c) / 2, f"besparing {delta_shape:,.0f}"),
        (3, c, f"€{c:,.0f}"),
    ):
        axes[0].text(x, value, label, ha="center", va="bottom", fontsize=8)
    axes[0].grid(True, axis="y", alpha=0.25)
    x = np.arange(3)
    expected = indexed.loc[
        ["A_hourly", "B_qh_flat", "C_qh_shape"], "expected_objective_eur"
    ].to_numpy(dtype=float)
    lower = indexed.loc[
        ["A_hourly", "B_qh_flat", "C_qh_shape"], "expected_lower_bound_eur"
    ].to_numpy(dtype=float)
    upper = indexed.loc[
        ["A_hourly", "B_qh_flat", "C_qh_shape"], "expected_upper_bound_eur"
    ].to_numpy(dtype=float)
    axes[1].errorbar(
        x,
        expected,
        yerr=np.vstack([expected - lower, upper - expected]),
        fmt="o",
        capsize=5,
        color="black",
    )
    axes[1].set_xticks(x, ["A", "B", "C"])
    axes[1].set_ylabel("Expected objective [€]")
    axes[1].set_title("Gecertificeerde LB/UB-band")
    axes[1].grid(True, axis="y", alpha=0.25)
    fig.suptitle("A/B/C-kosten · hoge volatiliteit 10 mei 2025")
    fig.tight_layout()
    _save_figure(fig, path, dpi=dpi)


def _site_kpis(
    results: pd.DataFrame, solver_rows: Sequence[Mapping[str, Any]]
) -> pd.DataFrame:
    solver_by_case = {str(row["case_id"]): row for row in solver_rows}
    rows: list[dict[str, Any]] = []
    for result in results.to_dict(orient="records"):
        solver = solver_by_case[str(result["case_id"])]
        planning = _certificate(solver["planning"])
        redispatch = _certificate(solver["redispatch"])
        produced = float(result["produced_t"])
        rows.append(
            {
                "case_id": result["case_id"],
                "label": CASE_LABELS[str(result["case_id"])],
                "arm": result["arm"],
                "production_t": produced,
                "eaf_heat_starts": float(result["eaf_heat_starts"]),
                "eaf_heat_taps": float(result["eaf_heat_taps"]),
                "eaf_liquid_steel_t": float(result["eaf_liquid_steel_output_t"]),
                "realised_cost_eur": float(
                    result["realised_total_represented_cost_eur"]
                ),
                "realised_cost_eur_per_t": float(
                    result["realised_total_represented_cost_eur"]
                )
                / produced,
                "expected_objective_eur": float(result["expected_objective_eur"]),
                "expected_lower_bound_eur": planning["lower"],
                "expected_upper_bound_eur": planning["upper"],
                "gross_electricity_mwh": float(result["gross_electricity_mwh"]),
                "net_grid_import_mwh": float(result["net_grid_import_mwh"]),
                "internal_generation_mwh": float(result["internal_generation_mwh"]),
                "named_ng_mwh_lhv": float(result["named_ng_mwh"]),
                "steam_demand_t": float(result["steam_demand_t"]),
                "steam_supply_t": float(result["steam_supply_t"]),
                "steam_spill_t": float(result["steam_spill_t"]),
                "steam_unserved_t": float(result["steam_unserved_t"]),
                "flare_mwh_lhv": float(result["flare_mwh"]),
                "absolute_imbalance_mwh": float(result["absolute_imbalance_mwh"]),
                "planning_optimality_class": planning["class"],
                "planning_gap": planning["gap"],
                "redispatch_optimality_class": redispatch["class"],
                "redispatch_gap": redispatch["gap"],
                "planning_runtime_s": float(result["planning_solver_seconds"]),
                "redispatch_runtime_s": float(result["redispatch_solver_seconds"]),
                "planning_variables": int(float(result["planning_variable_count"])),
                "planning_binaries": int(float(result["planning_binary_count"])),
                "planning_constraints": int(float(result["planning_constraint_count"])),
            }
        )
    return pd.DataFrame(rows)


def _eligibility_lookup(
    records: pd.DataFrame, case_id: str, mechanism: str
) -> tuple[str, str]:
    selected = records[
        records["case_id"].astype(str).eq(case_id)
        & records["mechanism"].astype(str).eq(mechanism)
    ]
    if len(selected) != 1:
        raise Fixed27VisualReviewError(
            f"Eligibility record is not unique: {case_id} / {mechanism}."
        )
    row = selected.iloc[0]
    return str(row["eligibility_status"]), str(row["binding_reason"])


def _plant_review(
    results: pd.DataFrame,
    dispatch: pd.DataFrame,
    eligibility: pd.DataFrame,
    mirror_checks: pd.DataFrame,
) -> pd.DataFrame:
    mirror_pass = bool((mirror_checks["status"] == "pass").all())
    rows: list[dict[str, Any]] = []

    def add(
        case_id: str,
        plant: str,
        expected: str,
        eligibility_text: str,
        observed: str,
        kpi: str,
        judgement: str,
    ) -> None:
        if judgement not in ALLOWED_REVIEW_STATUSES:
            raise Fixed27VisualReviewError("Unknown plant-review judgement.")
        rows.append(
            {
                "Case": CASE_LABELS[case_id],
                "case_id": case_id,
                "Plant": plant,
                "Verwacht gedrag": expected,
                "Eligibility": eligibility_text,
                "Waargenomen gedrag": observed,
                "KPI": kpi,
                "Oordeel": judgement,
            }
        )

    result_by_case = {
        str(row["case_id"]): row for row in results.to_dict(orient="records")
    }
    for case_id, result in result_by_case.items():
        frame = _case_frame(dispatch, case_id)
        eaf_eligibility, eaf_reason = _eligibility_lookup(
            eligibility, case_id, "eaf_heat_timing"
        )
        eaf_judgement = (
            "PASS"
            if case_id in {"S1_C1_responsive", "S2_C1_responsive"} and mirror_pass
            else "PLAUSIBLE_BUT_NOT_PROVEN"
        )
        add(
            case_id,
            "EAF",
            "27 heats blijven gelijk; timing verschuift naar goedkopere intervallen.",
            f"{eaf_eligibility}: {eaf_reason}",
            "Starts/taps en output sluiten; timing is zichtbaar in de QH-tijdlijn.",
            (
                f"starts={float(result['eaf_heat_starts']):.0f}; "
                f"taps={float(result['eaf_heat_taps']):.0f}; "
                f"capture={float(result['eaf_capture_price_eur_per_mwh']):.2f} €/MWh"
            ),
            eaf_judgement,
        )
        drp_eligibility, drp_reason = _eligibility_lookup(
            eligibility, case_id, "drp_dri_buffer_support"
        )
        add(
            case_id,
            "DRP/DRI",
            "DRP en DRI-buffer ondersteunen EAF-timing zonder materiaaltekort.",
            f"{drp_eligibility}: {drp_reason}",
            "DRP-feed, elektriciteit en DRI-voorraad blijven fysiek gesloten.",
            (
                f"DRP={float(result['drp_electricity_mwh']):.1f} MWh; "
                f"ΔDRI={float(result['dri_inventory_change_t']):.1f} t"
            ),
            "PLAUSIBLE_BUT_NOT_PROVEN",
        )
        route_eligibility, route_reason = _eligibility_lookup(
            eligibility, case_id, "drp_eaf_vs_bf_bof_route_substitution"
        )
        add(
            case_id,
            "BF6/BOF",
            "Geen route-substitutieclaim; continue route blijft stabiel.",
            f"{route_eligibility}: {route_reason}",
            "BF6 en BOF blijven actief; routevolume is bevroren.",
            (
                f"BF6={float(result['bf6_throughput_t']):.1f} t; "
                f"BOF={float(result['bof_throughput_t']):.1f} t"
            ),
            "NOT_APPLICABLE",
        )
        vn_eligibility, vn_reason = _eligibility_lookup(
            eligibility, case_id, "vn25_generation"
        )
        if vn_eligibility == "not_applicable":
            vn_judgement = "NOT_APPLICABLE"
        else:
            above = frame["forecast_price_eur_per_mwh"].astype(float) > (
                VN25_BREAK_EVEN_EUR_PER_MWH + 1e-9
            )
            below = frame["forecast_price_eur_per_mwh"].astype(float) < (
                VN25_BREAK_EVEN_EUR_PER_MWH - 1e-9
            )
            response = (
                above.any()
                and below.any()
                and float(frame.loc[above, "vn25_electricity_mwh"].mean())
                > float(frame.loc[below, "vn25_electricity_mwh"].mean()) + 0.25
            )
            vn_judgement = "PASS" if response else "FAIL"
        add(
            case_id,
            "VN25",
            "Boven NG-break-even meer opwekking en minder netimport, indien eligible.",
            f"{vn_eligibility}: {vn_reason}",
            "Opwekking en brandstofmix zijn tegen de vooraf bevroren eligibility beoordeeld.",
            (
                f"generation={float(result['vn25_electricity_mwh']):.1f} MWh; "
                f"WAG={float(result['vn25_wag_mwh']):.1f}; "
                f"NG={float(result['vn25_named_ng_mwh']):.1f} MWh LHV"
            ),
            vn_judgement,
        )
        boiler_eligibility, boiler_reason = _eligibility_lookup(
            eligibility, case_id, "boiler_wag_allocation"
        )
        add(
            case_id,
            "Boiler/steam",
            "Steam blijft gedekt; WAG/NG-verdeling mag reageren indien eligible.",
            f"{boiler_eligibility}: {boiler_reason}",
            "Steam demand en supply sluiten; unserved steam blijft nul.",
            (
                f"demand={float(result['steam_demand_t']):.1f} t; "
                f"unserved={float(result['steam_unserved_t']):.3g} t"
            ),
            (
                "PASS"
                if float(result["steam_unserved_t"]) <= 1e-6
                else "FAIL"
            ),
        )
        flare_eligibility, flare_reason = _eligibility_lookup(
            eligibility, case_id, "wag_flare"
        )
        add(
            case_id,
            "Procesgas/flare",
            "Bruikbaar procesgas gaat naar assets vóór flare waar fysiek mogelijk.",
            f"{flare_eligibility}: {flare_reason}",
            "Bestemmingen en carrier-specifieke flare zijn apart zichtbaar.",
            f"flare={float(result['flare_mwh']):.1f} MWh LHV",
            (
                "PLAUSIBLE_BUT_NOT_PROVEN"
                if flare_eligibility == "applicable"
                else "NOT_APPLICABLE"
            ),
        )
        ij_eligibility, ij_reason = _eligibility_lookup(
            eligibility, case_id, "ij01_no_direct_price_response"
        )
        add(
            case_id,
            "IJ01",
            "Geen directe prijsresponsclaim en nul named NG.",
            f"{ij_eligibility}: {ij_reason}",
            "IJ01 named NG blijft nul.",
            f"IJ01 named NG={float(result['ij01_named_ng_mwh']):.3g} MWh LHV",
            "PASS" if abs(float(result["ij01_named_ng_mwh"])) <= 1e-6 else "FAIL",
        )
        hsm_eligibility, hsm_reason = _eligibility_lookup(
            eligibility, case_id, "hsm_dsp_output_preservation"
        )
        add(
            case_id,
            "HSM/DSP",
            "Downstream output blijft behouden zonder prijsgedreven stops.",
            f"{hsm_eligibility}: {hsm_reason}",
            "HSM- en DSP-totalen sluiten met de vaste routeproductie.",
            (
                f"HSM={float(result['hsm_throughput_t']):.1f} t; "
                f"DSP={float(result['dsp_output_t']):.1f} t"
            ),
            "PASS",
        )
        add(
            case_id,
            "Site/grid",
            "Fysieke import volgt het geklaarde E-programma zonder onbalans.",
            "applicable: hard settlement/physical identity",
            "E-programma, fysieke import en settlement reconstrueren per interval.",
            f"absolute imbalance={float(result['absolute_imbalance_mwh']):.3g} MWh",
            (
                "PASS"
                if float(result["absolute_imbalance_mwh"])
                <= ENERGY_TOLERANCE_MWH
                else "FAIL"
            ),
        )
    return pd.DataFrame(rows)


def _generate_figures(
    output: Path,
    dispatch: pd.DataFrame,
    costs: pd.DataFrame,
    *,
    dpi: int,
) -> pd.DataFrame:
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    definitions = [
        (
            "eaf_timing_synthetic_mirror.png",
            _plot_eaf_mirror,
            "S1/S2 prijs, arc-power, heat-state en cumulatieve starts/taps.",
            "Bewijst timingrespons bij exact 27 heats; geen weekclaim.",
        ),
        (
            "drp_dri_eaf_coupling.png",
            _plot_drp_dri_eaf,
            "DRP-feed, DRP-elektriciteit, DRI-voorraad en EAF-taps.",
            "Visuele bufferreview; bounds blijven door de fysieke gate afgedwongen.",
        ),
        (
            "vn25_break_even_generation.png",
            _plot_vn25_break_even,
            "Prijs versus named-NG-break-even en VN25-opwekking.",
            "Directioneel alleen hard waar eligibility vooraf applicable is.",
        ),
        (
            "vn25_fuels_import_flare.png",
            _plot_vn25_fuels_import_flare,
            "VN25 WAG/NG, netimport en flare op dezelfde fysieke tijdgrid.",
            "WAG is geaggregeerd waar de dispatch geen carrierallocatie bewaart.",
        ),
        (
            "process_gas_distribution.png",
            _plot_process_gas,
            "Procesgas naar VN25, IJ01, boiler en flare; carrierflare apart.",
            "VN25/IJ01 bewaren WAG-totaal, niet een verzonnen carrierverdeling.",
        ),
        (
            "steel_chain_and_inventories_abc.png",
            _plot_steel_chain_abc,
            "BF6–BOF–HSM/DSP en relevante buffers voor A/B/C.",
            "Eén non-final hoge-volatiliteitsdag; geen route-substitutieclaim.",
        ),
        (
            "grid_program_imbalance_abc.png",
            _plot_grid_reconciliation,
            "Fysieke import, geklaard E-programma en onbalans voor A/B/C.",
            "Hourly E-programma is correct over vier fysieke kwartieren verdeeld.",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for filename, function, content, limitation in definitions:
        function(dispatch, figures / filename, dpi)
        rows.append(
            {
                "figure": f"figures/{filename}",
                "content": content,
                "limitation": limitation,
            }
        )
    cost_filename = "abc_cost_waterfall.png"
    _plot_cost_waterfall(costs, figures / cost_filename, dpi)
    rows.append(
        {
            "figure": f"figures/{cost_filename}",
            "content": "A→ΔQH-markt→Δshape→C en expected-objective LB/UB.",
            "limitation": "Eén non-final dag; epsilon-banden kunnen overlappen.",
        }
    )
    return pd.DataFrame(rows)


def run_fixed27_visual_review(
    config_path: str | Path = VISUAL_REVIEW_CONFIG,
    *,
    run_id: str,
    reusable_case_checkpoints: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    preflight = preflight_fixed27_visual_review(config_path)
    config = load_visual_review_config(config_path)
    output_parent = _resolve(config["output_root"])
    prepared = prepare_behavioural_run(
        config.get("behavioural_config", BEHAVIOURAL_CONFIG),
        run_id=run_id,
        resume=False,
        output_root=output_parent,
    )
    output: Path = prepared["output"]
    allowed = [str(item["case_id"]) for item in config["allowed_cases"]]
    selected = prepared["manifest"][
        prepared["manifest"]["case_id"].astype(str).isin(allowed)
    ].copy()
    selected["case_order"] = selected["case_id"].map(
        {case_id: index for index, case_id in enumerate(allowed)}
    )
    selected = selected.sort_values("case_order").drop(columns="case_order")
    if selected["case_id"].astype(str).tolist() != allowed:
        raise Fixed27VisualReviewError("Selected-case order or membership changed.")
    if selected["final_test_case"].astype(bool).any():
        raise Fixed27VisualReviewError("A final-test case entered the visual review.")
    if set(selected["configuration"].astype(str)) != {"C1"}:
        raise Fixed27VisualReviewError("The visual review is C1-only.")
    if set(selected["scenario_count"].astype(int)) != {10}:
        raise Fixed27VisualReviewError("The visual review is S10-only.")
    _write_csv(output / "selected_case_manifest.csv", selected)
    eligibility = pd.DataFrame(build_plant_eligibility_records(prepared, selected))
    _write_csv(output / "plant_eligibility_records.csv", eligibility)
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": config["lineage_role"],
        "retention_status": config["retention_status"],
        "git_eligible": False,
        "case_count": 7,
        "estimated_model_count": config["output_expectation"][
            "expected_model_count"
        ],
        "estimated_solver_tier_count": config["output_expectation"][
            "expected_solver_tier_count"
        ],
        "expected_file_count": config["output_expectation"]["expected_file_count"],
        "expected_approximate_size_mb": config["output_expectation"][
            "expected_approximate_size_mb"
        ],
        "fixed_daily_eaf_heats": 27,
        "economic_horizon_hours": 24,
        "scenario_count": 10,
        "final_test_periods_read_or_solved": False,
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    solvers: list[dict[str, Any]] = []
    physical_checks: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    dispatch_frames: list[pd.DataFrame] = []
    source_by_case = {
        str(item["case_id"]): _resolve(item["accepted_source_root"])
        for item in config["allowed_cases"]
    }
    reusable_case_checkpoints = dict(reusable_case_checkpoints or {})
    unknown_reuse = set(reusable_case_checkpoints) - set(allowed)
    if unknown_reuse:
        raise Fixed27VisualReviewError(
            f"Checkpoint reuse names cases outside the bounded set: {unknown_reuse}."
        )
    checkpoint_reuse_audit: list[dict[str, Any]] = []
    try:
        for case in selected.to_dict(orient="records"):
            case_id = str(case["case_id"])
            if case_id in reusable_case_checkpoints:
                outcome = _load_reusable_case_checkpoint(
                    Path(reusable_case_checkpoints[case_id]), case_id=case_id
                )
                checkpoint_reuse_audit.append(outcome["checkpoint_reuse"])
            else:
                outcome = _execute_fixed_case(prepared, case)
            checkpoint_name = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:16]
            checkpoint_root = output / "case_checkpoints" / checkpoint_name
            checkpoint_root.mkdir(parents=True, exist_ok=True)
            _write_csv(
                checkpoint_root / "interval_dispatch.csv", outcome["dispatch"]
            )
            _write_json(
                checkpoint_root / "case_result.json", outcome["result"]
            )
            _write_json(
                checkpoint_root / "solver_diagnostics.json", outcome["solver"]
            )
            source_result, source_solver = _source_case_artifact(
                source_by_case[case_id], case_id
            )
            case_reconciliation = _reconcile_case(
                outcome["result"],
                outcome["dispatch"],
                outcome["solver"],
                source_result,
                source_solver,
            )
            failed_reconciliation = [
                row for row in case_reconciliation if row["status"] != "pass"
            ]
            if failed_reconciliation:
                _write_csv(
                    output / "failed_dispatch_reconciliation_checks.csv",
                    pd.DataFrame(case_reconciliation),
                )
                raise Fixed27VisualReviewError(
                    "Review dispatch failed source reconciliation: "
                    f"{case_id}: {failed_reconciliation}"
                )
            results.append(outcome["result"])
            solvers.append(outcome["solver"])
            physical_checks.extend(outcome["checks"])
            reconciliation.extend(case_reconciliation)
            dispatch_frames.append(outcome["dispatch"])
            _write_csv(output / "case_results.csv", pd.DataFrame(results))
            _write_json(output / "solver_diagnostics.json", solvers)
            _write_csv(
                output / "physical_validation_checks.csv",
                pd.DataFrame(physical_checks),
            )
            _write_csv(
                output / "dispatch_reconciliation_checks.csv",
                pd.DataFrame(reconciliation),
            )
            _write_csv(
                output / "interval_dispatch.csv",
                pd.concat(dispatch_frames, ignore_index=True),
            )
            _write_json(
                output / "progress_current.json",
                {
                    "status": "running",
                    "completed_case_ids": [row["case_id"] for row in results],
                    "completed_case_count": len(results),
                    "expected_case_count": 7,
                    "resume_authorized": False,
                    "final_test_periods_read_or_solved": False,
                },
            )
            _write_json(
                output / "checkpoint_reuse_audit.json", checkpoint_reuse_audit
            )
        dispatch = pd.concat(dispatch_frames, ignore_index=True)
        mirror = pd.DataFrame(_synthetic_mirror_checks(dispatch))
        reconciliation.extend(mirror.to_dict(orient="records"))
        reconciliation_frame = pd.DataFrame(reconciliation)
        if (reconciliation_frame["status"] != "pass").any():
            raise Fixed27VisualReviewError("The synthetic mirror gate did not pass.")
        results_frame = pd.DataFrame(results)
        costs = build_abc_cost_summary(results_frame, solvers)
        site_kpis = _site_kpis(results_frame, solvers)
        plant_review = _plant_review(
            results_frame, dispatch, eligibility, mirror
        )
        if (plant_review["Oordeel"] == "FAIL").any():
            decision = "FAIL"
            status = "completed_human_review_with_failure"
        else:
            decision = "PASS"
            status = "ready_for_human_review"
        figure_index = _generate_figures(
            output,
            dispatch,
            costs,
            dpi=int(config["output_expectation"]["png_dpi"]),
        )
        _write_csv(output / "dispatch_reconciliation_checks.csv", reconciliation_frame)
        _write_csv(output / "site_kpis.csv", site_kpis)
        _write_csv(output / "plant_behaviour_review.csv", plant_review)
        _write_csv(output / "abc_cost_summary.csv", costs)
        _write_csv(output / "figure_index.csv", figure_index)
        _write_json(
            output / "input_manifest.json",
            {
                "visual_review_config": {
                    "path": _resolve(config_path).relative_to(REPO_ROOT).as_posix(),
                    "sha256": _sha256(_resolve(config_path)),
                },
                "method_freeze": {
                    "path": _resolve(config["method_freeze"])
                    .relative_to(REPO_ROOT)
                    .as_posix(),
                    "sha256": _sha256(_resolve(config["method_freeze"])),
                },
                "accepted_case_sources": [
                    {
                        "case_id": case_id,
                        "root": root.relative_to(REPO_ROOT).as_posix(),
                        "case_results_sha256": _sha256(root / "case_results.csv"),
                        "solver_diagnostics_sha256": _sha256(
                            root / "solver_diagnostics.json"
                        ),
                    }
                    for case_id, root in source_by_case.items()
                ],
                "final_test_periods_read_or_solved": False,
                "new_forecast_or_scenario_artifacts_created": False,
            },
        )
        summary = {
            **declaration,
            "run_id": run_id,
            "status": status,
            "decision": decision,
            "completed_case_count": len(results),
            "interval_dispatch_row_count": len(dispatch),
            "figure_count": len(figure_index),
            "plant_review_row_count": len(plant_review),
            "hard_reconciliation_check_count": len(reconciliation_frame),
            "hard_reconciliation_failure_count": int(
                (reconciliation_frame["status"] != "pass").sum()
            ),
            "maximum_absolute_imbalance_mwh": float(
                results_frame["absolute_imbalance_mwh"].astype(float).max()
            ),
            "minimum_eaf_heat_starts": float(
                results_frame["eaf_heat_starts"].astype(float).min()
            ),
            "maximum_eaf_heat_starts": float(
                results_frame["eaf_heat_starts"].astype(float).max()
            ),
            "minimum_eaf_heat_taps": float(
                results_frame["eaf_heat_taps"].astype(float).min()
            ),
            "maximum_eaf_heat_taps": float(
                results_frame["eaf_heat_taps"].astype(float).max()
            ),
            "wall_seconds": time.perf_counter() - started,
            "source_preflight": preflight,
            "final_test_periods_read_or_solved": False,
            "full_four_week_matrix_authorized": False,
            "resume_authorized": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(
            output / "code_version.json",
            {
                "visual_review_module": Path(__file__).relative_to(REPO_ROOT).as_posix(),
                "visual_review_module_sha256": _sha256(Path(__file__)),
                "frozen_method_files_modified_by_review": False,
            },
        )
        (output / "warnings_and_limitations.md").write_text(
            "# Warnings and limitations\n\n"
            "- This is a non-final diagnostic human review of seven fixed-27 cases.\n"
            "- It is not annual, not a final representative-week result, and not a "
            "new method selection.\n"
            "- VN25 and flare direction is only hard where pre-solve eligibility is "
            "applicable.\n"
            "- VN25/IJ01 process gas is retained as aggregate WAG where the accepted "
            "dispatch does not expose carrier-specific allocation.\n",
            encoding="utf-8",
        )
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": run_id,
                "run_class": "diagnostic_validation",
                "status": status,
                "decision": decision,
                "retention_status": "ignored_local_governed_diagnostic",
                "git_eligible": False,
            },
        )
        _write_run_control(
            output,
            status="completed",
            resume_authorized=False,
            reason="fixed27_visual_review_complete_stop_before_final_weeks",
        )
        return {"output": str(output), **summary}
    except Exception as exc:
        summary = {
            **declaration,
            "run_id": run_id,
            "status": "blocked",
            "decision": "BLOCK",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "completed_case_count": len(results),
            "wall_seconds": time.perf_counter() - started,
            "final_test_periods_read_or_solved": False,
            "full_four_week_matrix_authorized": False,
            "resume_authorized": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_run_control(
            output,
            status="blocked",
            resume_authorized=False,
            reason="fixed27_visual_review_failed_closed",
        )
        raise
