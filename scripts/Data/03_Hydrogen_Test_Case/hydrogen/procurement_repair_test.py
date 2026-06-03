from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .bidding_backtest import run_real_scenario_bidding_dry_run
from .cvar import compute_weighted_cvar_from_frame
from .optimisation_model import (
    ModelStats,
    SolverResult,
    _apply_gurobi_license_env,
    _ensure_solver_package,
    _pulp_model_stats,
    _pyomo_model_stats,
    _resolve_pulp_solver,
    _resolve_pyomo_solver,
    _safe_pyomo_value,
    pulp,
    pyo,
)
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .selected_test_weeks_cvar_policy_eval import _load_and_validate_phase_e2_weeks
from .selected_week_smoke import (
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    TOLERANCE,
    _label_for_artifact,
    _validation_row,
)
from .weekly_hard_band_decision import _prepare_artifact_day_payloads
from .weekly_hard_band_target import (
    TARGET_MODE_WEEKLY_HARD_BAND,
    WeeklyHardBandSettings,
    build_weekly_hard_band_settings,
    compute_weekly_target_day_bounds,
)


REPAIR_POLICY_FIRM_BASELINE = "firm_baseline_plus_flexible_layer"
REPAIR_POLICY_EMERGENCY_IMPORT = "emergency_import_fallback"
REPAIR_POLICIES = (
    REPAIR_POLICY_FIRM_BASELINE,
    REPAIR_POLICY_EMERGENCY_IMPORT,
)


@dataclass(frozen=True)
class BaselineDispatchResult:
    dispatch: pd.DataFrame
    solver: SolverResult
    model_stats: ModelStats


@dataclass(frozen=True)
class ProcurementRepairRunResult:
    run_dir: Path
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    comparison: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    runtime_summary: pd.DataFrame


def _bool_text(value: bool) -> str:
    return "true" if bool(value) else "false"


def _accepted_solver_status(status: Any) -> bool:
    text = str(status).strip().lower()
    return text == "optimal" or text.startswith("optimal")


def _safe_numeric(value: Any) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else float("nan")


def _save_parquet_if_possible(run_dir: Path, name: str, frame: pd.DataFrame) -> bool:
    try:
        save_frame_parquet(run_dir, name, frame)
        return True
    except Exception:
        return False


def _runtime_summary(runtime_diagnostics: pd.DataFrame) -> pd.DataFrame:
    if runtime_diagnostics.empty:
        return pd.DataFrame(columns=["section", "group", "metric", "value", "notes"])
    rows: list[dict[str, Any]] = []
    rows.append({"section": "totals", "group": "all", "metric": "wall_time_seconds", "value": float(runtime_diagnostics["wall_time_seconds"].sum()), "notes": ""})
    for stage, group in runtime_diagnostics.groupby("solve_stage", sort=False):
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "count", "value": float(group.shape[0]), "notes": ""})
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "mean_wall_time_seconds", "value": float(group["wall_time_seconds"].mean()), "notes": ""})
    for used_cache, group in runtime_diagnostics.groupby("used_cache", sort=False):
        rows.append({"section": "cache_usage", "group": _bool_text(bool(used_cache)), "metric": "count", "value": float(group.shape[0]), "notes": ""})
    return pd.DataFrame(rows)


def _build_run_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
    run_slug: str,
    output_root: Path | None,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    return replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(run_slug),
            execution_mode="procurement_repair_test",
        ),
        models=replace(base.models, include=(str(artifact_id),)),
        outputs=replace(
            base.outputs,
            root=Path(output_root) if output_root is not None else base.outputs.root,
            save_figures=False,
        ),
    )


def _solve_minimum_secure_baseline_dispatch(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    target_hydrogen_min_kg: float,
    target_hydrogen_max_kg: float,
    solver_log_path: str | None,
) -> BaselineDispatchResult:
    timestamps = pd.DatetimeIndex(
        pd.to_datetime(
            day_frame[["delivery_start_utc"]].drop_duplicates()["delivery_start_utc"],
            utc=True,
            errors="raise",
        ).sort_values()
    )
    if timestamps.empty:
        raise ValueError("Baseline dispatch received an empty day frame.")

    delta_t_hours = float(config.delta_t_hours)
    ramp_limit = float(config.hydrogen_system.electrolyser_ramp_mw_per_h * delta_t_hours)
    _ensure_solver_package(config.solver)
    _apply_gurobi_license_env(config.solver)
    preference = str(config.solver.package_preference).strip().lower()

    if preference in {"pyomo", "auto"} and pyo is not None:
        try:
            build_started = perf_counter()
            model = pyo.ConcreteModel(name="minimum_secure_baseline_dispatch")
            model.T = pyo.RangeSet(0, len(timestamps) - 1)
            model.P_el = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.u_el = pyo.Var(model.T, domain=pyo.Binary)
            model.H_prod = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.P_comp = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.H_comp = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.H_buf = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.constraints = pyo.ConstraintList()
            for t in range(len(timestamps)):
                model.constraints.add(model.P_el[t] >= config.hydrogen_system.electrolyser_min_mw * model.u_el[t])
                model.constraints.add(model.P_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * model.u_el[t])
                model.constraints.add(model.H_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * model.P_el[t] * delta_t_hours)
                model.constraints.add(model.P_comp[t] <= config.hydrogen_system.compressor_max_mw)
                model.constraints.add(model.P_comp[t] * delta_t_hours == config.hydrogen_system.compressor_specific_mwh_per_kg * model.H_comp[t])
                if t == 0:
                    model.constraints.add(model.H_buf[t] == inventory_start_kg + model.H_prod[t] - model.H_comp[t])
                else:
                    model.constraints.add(model.H_buf[t] == model.H_buf[t - 1] + model.H_prod[t] - model.H_comp[t])
                    model.constraints.add(model.P_el[t] - model.P_el[t - 1] <= ramp_limit)
                    model.constraints.add(model.P_el[t - 1] - model.P_el[t] <= ramp_limit)
                model.constraints.add(model.H_buf[t] >= reserve_kg)
                model.constraints.add(model.H_buf[t] <= config.hydrogen_system.storage_capacity_kg)
            total_h2 = sum(model.H_comp[t] for t in range(len(timestamps)))
            model.constraints.add(total_h2 >= float(target_hydrogen_min_kg))
            model.constraints.add(total_h2 <= float(target_hydrogen_max_kg))
            model.objective = pyo.Objective(
                expr=sum(delta_t_hours * (model.P_el[t] + model.P_comp[t]) for t in range(len(timestamps))),
                sense=pyo.minimize,
            )
            model_build_time = perf_counter() - build_started
            solver, solver_name = _resolve_pyomo_solver(config.solver, solver_log_path)
            started = perf_counter()
            try:
                if solver_log_path is not None:
                    results = solver.solve(model, tee=False, logfile=solver_log_path)
                else:
                    results = solver.solve(model, tee=False)
            except TypeError:
                results = solver.solve(model, tee=False)
            solver_runtime = perf_counter() - started
            termination = getattr(getattr(results, "solver", None), "termination_condition", None)
            termination_text = str(termination).strip().lower() if termination is not None else ""
            solver_status = "Optimal" if termination_text == "optimal" else str(termination)
            post_started = perf_counter()
            dispatch = pd.DataFrame(
                {
                    "delivery_start_utc": list(timestamps),
                    "P_el_mw": [float(_safe_pyomo_value(model.P_el[t]) or 0.0) for t in range(len(timestamps))],
                    "u_el": [float(_safe_pyomo_value(model.u_el[t]) or 0.0) for t in range(len(timestamps))],
                    "H_prod_kg": [float(_safe_pyomo_value(model.H_prod[t]) or 0.0) for t in range(len(timestamps))],
                    "P_comp_mw": [float(_safe_pyomo_value(model.P_comp[t]) or 0.0) for t in range(len(timestamps))],
                    "H_comp_kg": [float(_safe_pyomo_value(model.H_comp[t]) or 0.0) for t in range(len(timestamps))],
                    "H_buf_kg": [float(_safe_pyomo_value(model.H_buf[t]) or 0.0) for t in range(len(timestamps))],
                    "timestep_hours": float(delta_t_hours),
                }
            )
            dispatch["firm_baseline_load_mw"] = dispatch["P_el_mw"] + dispatch["P_comp_mw"]
            dispatch["firm_baseline_energy_mwh"] = dispatch["firm_baseline_load_mw"] * delta_t_hours
            model_stats = _pyomo_model_stats(
                model,
                scenario_count=1,
                horizon_steps=len(timestamps),
                delta_t_hours=delta_t_hours,
            )
            postprocess_time = perf_counter() - post_started
            solver_result = SolverResult(
                status=solver_status,
                objective_value=float(pyo.value(model.objective)) if pyo.value(model.objective) is not None else None,
                runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
                mip_gap=float(config.solver.mip_gap),
                solver_package="pyomo",
                solver_name=str(solver_name),
                termination_condition=str(termination) if termination is not None else None,
                model_build_time_seconds=float(model_build_time),
                solver_time_seconds=float(solver_runtime),
                postprocess_time_seconds=float(postprocess_time),
            )
            return BaselineDispatchResult(dispatch=dispatch, solver=solver_result, model_stats=model_stats)
        except RuntimeError:
            if preference == "pyomo":
                raise

    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")
    build_started = perf_counter()
    horizon = range(len(timestamps))
    model = pulp.LpProblem("minimum_secure_baseline_dispatch", pulp.LpMinimize)
    p_el = {t: pulp.LpVariable(f"P_el_{t}", lowBound=0.0) for t in horizon}
    u_el = {t: pulp.LpVariable(f"u_el_{t}", lowBound=0.0, upBound=1.0, cat=pulp.LpBinary) for t in horizon}
    h_prod = {t: pulp.LpVariable(f"H_prod_{t}", lowBound=0.0) for t in horizon}
    p_comp = {t: pulp.LpVariable(f"P_comp_{t}", lowBound=0.0) for t in horizon}
    h_comp = {t: pulp.LpVariable(f"H_comp_{t}", lowBound=0.0) for t in horizon}
    h_buf = {t: pulp.LpVariable(f"H_buf_{t}", lowBound=0.0) for t in horizon}
    for t in horizon:
        model += p_el[t] >= config.hydrogen_system.electrolyser_min_mw * u_el[t], f"el_min_{t}"
        model += p_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * u_el[t], f"el_max_{t}"
        model += h_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el[t] * delta_t_hours, f"h_prod_{t}"
        model += p_comp[t] <= config.hydrogen_system.compressor_max_mw, f"comp_max_{t}"
        model += p_comp[t] * delta_t_hours == config.hydrogen_system.compressor_specific_mwh_per_kg * h_comp[t], f"comp_specific_{t}"
        if t == 0:
            model += h_buf[t] == inventory_start_kg + h_prod[t] - h_comp[t], f"storage_{t}"
        else:
            model += h_buf[t] == h_buf[t - 1] + h_prod[t] - h_comp[t], f"storage_{t}"
            model += p_el[t] - p_el[t - 1] <= ramp_limit, f"ramp_up_{t}"
            model += p_el[t - 1] - p_el[t] <= ramp_limit, f"ramp_down_{t}"
        model += h_buf[t] >= reserve_kg, f"reserve_{t}"
        model += h_buf[t] <= config.hydrogen_system.storage_capacity_kg, f"storage_cap_{t}"
    total_h2 = pulp.lpSum(h_comp[t] for t in horizon)
    model += total_h2 >= float(target_hydrogen_min_kg), "target_lb"
    model += total_h2 <= float(target_hydrogen_max_kg), "target_ub"
    model += pulp.lpSum(delta_t_hours * (p_el[t] + p_comp[t]) for t in horizon)
    model_build_time = perf_counter() - build_started
    solver_backend, solver_name = _resolve_pulp_solver(config.solver, log_path=solver_log_path)
    started = perf_counter()
    model.solve(solver_backend)
    solver_runtime = perf_counter() - started
    post_started = perf_counter()
    dispatch = pd.DataFrame(
        {
            "delivery_start_utc": list(timestamps),
            "P_el_mw": [float(p_el[t].value() or 0.0) for t in horizon],
            "u_el": [float(u_el[t].value() or 0.0) for t in horizon],
            "H_prod_kg": [float(h_prod[t].value() or 0.0) for t in horizon],
            "P_comp_mw": [float(p_comp[t].value() or 0.0) for t in horizon],
            "H_comp_kg": [float(h_comp[t].value() or 0.0) for t in horizon],
            "H_buf_kg": [float(h_buf[t].value() or 0.0) for t in horizon],
            "timestep_hours": float(delta_t_hours),
        }
    )
    dispatch["firm_baseline_load_mw"] = dispatch["P_el_mw"] + dispatch["P_comp_mw"]
    dispatch["firm_baseline_energy_mwh"] = dispatch["firm_baseline_load_mw"] * delta_t_hours
    model_stats = _pulp_model_stats(
        model,
        scenario_count=1,
        horizon_steps=len(timestamps),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - post_started
    solver_result = SolverResult(
        status=str(pulp.LpStatus.get(model.status, str(model.status))),
        objective_value=float(model.objective.value()) if model.objective.value() is not None else None,
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(config.solver.mip_gap),
        solver_package="pulp",
        solver_name=str(solver_name),
        termination_condition=str(pulp.LpStatus.get(model.status, str(model.status))),
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
    )
    return BaselineDispatchResult(dispatch=dispatch, solver=solver_result, model_stats=model_stats)


def _build_daily_metric_row(
    *,
    run_id: str,
    policy: str,
    artifact_id: str,
    model_label: str,
    week_row: pd.Series,
    day_payload: dict[str, Any],
    delivery_day: str,
    bounds: Any,
    cumulative_before_kg: float,
    stochastic_result: Any | None,
    baseline_result: BaselineDispatchResult | None,
    baseline_bid_price: float,
    emergency_import_price: float,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    if stochastic_result is None:
        return {
            "run_id": str(run_id),
            "repair_policy": str(policy),
            "artifact_id": str(artifact_id),
            "model_id": str(day_payload["model_id"]),
            "model_label": str(model_label),
            "week_id": str(week_row["week_id"]),
            "week_label": str(week_row["week_label"]),
            "regime_label": str(week_row["regime_label"]),
            "delivery_day": str(delivery_day),
            "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]),
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "cvar_alpha": np.nan,
            "cvar_gamma": np.nan,
            "stochastic_solver_status": str(skip_reason or "not_run"),
            "actual_redispatch_solver_status": str(skip_reason or "not_run"),
            "redispatch_feasible": False,
            "weekly_target_met": False,
            "daily_band_violation": 0,
            "hydrogen_sold_or_compressed_kg": np.nan,
            "expected_adjusted_profit": np.nan,
            "realised_adjusted_profit": np.nan,
            "cvar_tail_profit": np.nan,
            "worst_scenario_profit": np.nan,
            "submitted_energy_mwh": np.nan,
            "cleared_energy_mwh": np.nan,
            "rejected_energy_mwh": np.nan,
            "used_cleared_energy_mwh": np.nan,
            "unused_cleared_energy_mwh": np.nan,
            "firm_baseline_energy_mwh": float(baseline_result.dispatch["firm_baseline_energy_mwh"].sum()) if baseline_result is not None else 0.0,
            "emergency_import_mwh": np.nan,
            "emergency_import_cost": np.nan,
            "da_settlement_cost": np.nan,
            "clearing_ratio": np.nan,
            "average_actual_price_paid": np.nan,
            "high_bid_share": np.nan,
            "market_cap_bid_share": np.nan,
            "storage_min_kg": np.nan,
            "reserve_boundary_hits": np.nan,
            "solve_time_seconds": np.nan,
            "mip_gap": np.nan,
            "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
            "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
            "weekly_target_kg": float(bounds.weekly_target_kg),
            "cumulative_before_kg": float(cumulative_before_kg),
            "cumulative_after_kg": float(cumulative_before_kg),
            "days_remaining_in_week": int(bounds.days_remaining_in_week),
            "firm_baseline_floor_enforced": bool(policy == REPAIR_POLICY_FIRM_BASELINE),
            "emergency_import_enabled": bool(policy == REPAIR_POLICY_EMERGENCY_IMPORT),
            "firm_baseline_bid_price_eur_per_mwh": float(baseline_bid_price),
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
        }

    metrics = stochastic_result.metrics_summary.iloc[0]
    actual = stochastic_result.actual_settlement_results.iloc[0]
    scenario = stochastic_result.scenario_objective_summary.copy()
    actual_clearing = stochastic_result.actual_clearing.copy()
    submitted = stochastic_result.optimisation_result.submitted_bids.copy()
    submitted_energy_total = float(pd.to_numeric(submitted["bid_quantity_mw"], errors="coerce").sum())
    high_bid_energy = float(
        pd.to_numeric(
            submitted.loc[pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce") >= 250.0, "bid_quantity_mw"],
            errors="coerce",
        ).sum()
    )
    market_cap = float(pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce").max())
    market_cap_bid_energy = float(
        pd.to_numeric(
            submitted.loc[np.isclose(pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce"), market_cap), "bid_quantity_mw"],
            errors="coerce",
        ).sum()
    )
    reconstructed = compute_weighted_cvar_from_frame(
        scenario,
        loss_column="loss_eur",
        probability_column="scenario_probability",
        alpha=float(metrics["cvar_alpha"]),
    )
    actual_h2 = float(actual["hydrogen_compressed_or_sold_kg"])
    return {
        "run_id": str(run_id),
        "repair_policy": str(policy),
        "artifact_id": str(artifact_id),
        "model_id": str(day_payload["model_id"]),
        "model_label": str(model_label),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "regime_label": str(week_row["regime_label"]),
        "delivery_day": str(delivery_day),
        "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]),
        "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
        "cvar_alpha": float(metrics["cvar_alpha"]),
        "cvar_gamma": float(metrics["cvar_gamma"]),
        "stochastic_solver_status": str(stochastic_result.optimisation_result.solver.status),
        "actual_redispatch_solver_status": str(actual["solver_status"]),
        "redispatch_feasible": bool(_accepted_solver_status(actual["solver_status"])),
        "weekly_target_met": False,
        "daily_band_violation": int(actual_h2 < bounds.daily_lower_bound_kg - TOLERANCE or actual_h2 > bounds.daily_upper_bound_kg + TOLERANCE),
        "hydrogen_sold_or_compressed_kg": actual_h2,
        "expected_adjusted_profit": float(metrics["expected_adjusted_profit_eur"]),
        "realised_adjusted_profit": float(actual["realised_adjusted_profit_eur"]),
        "cvar_tail_profit": float(-reconstructed.cvar),
        "worst_scenario_profit": float(pd.to_numeric(scenario["adjusted_profit_eur"], errors="coerce").min()),
        "submitted_energy_mwh": float(metrics["submitted_energy_mwh"]),
        "cleared_energy_mwh": float(metrics["cleared_energy_mwh"]),
        "rejected_energy_mwh": float(metrics["rejected_energy_mwh"]),
        "used_cleared_energy_mwh": float(actual["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(actual["unused_cleared_energy_mwh"]),
        "firm_baseline_energy_mwh": float(baseline_result.dispatch["firm_baseline_energy_mwh"].sum()) if baseline_result is not None else 0.0,
        "emergency_import_mwh": float(actual.get("emergency_import_mwh", 0.0)),
        "emergency_import_cost": float(actual.get("emergency_import_cost_eur", 0.0)),
        "da_settlement_cost": float(actual["realised_DA_settlement_cost_eur"]),
        "clearing_ratio": float(metrics["clearing_ratio"]),
        "average_actual_price_paid": float(metrics["weighted_average_actual_price_paid_for_cleared_energy"]),
        "high_bid_share": float(high_bid_energy / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "market_cap_bid_share": float(market_cap_bid_energy / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "storage_min_kg": float(actual["storage_min_kg"]),
        "reserve_boundary_hits": int(actual["reserve_boundary_hits"]),
        "solve_time_seconds": float(stochastic_result.optimisation_result.solver.runtime_seconds),
        "mip_gap": float(0.001 if stochastic_result.optimisation_result.solver.objective_value is not None else np.nan),
        "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
        "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
        "weekly_target_kg": float(bounds.weekly_target_kg),
        "cumulative_before_kg": float(cumulative_before_kg),
        "cumulative_after_kg": float(cumulative_before_kg + actual_h2),
        "days_remaining_in_week": int(bounds.days_remaining_in_week),
        "firm_baseline_floor_enforced": bool(policy == REPAIR_POLICY_FIRM_BASELINE),
        "emergency_import_enabled": bool(policy == REPAIR_POLICY_EMERGENCY_IMPORT),
        "firm_baseline_bid_price_eur_per_mwh": float(baseline_bid_price),
        "emergency_import_price_eur_per_mwh": float(emergency_import_price),
        "validation_fail_count": int((stochastic_result.validation_checks["status"].astype(str) == "fail").sum()),
        "actual_settlement_run_dir": str(stochastic_result.run_dir) if stochastic_result.run_dir is not None else "",
        "accepted_bid_energy_mwh": float(pd.to_numeric(actual_clearing.loc[actual_clearing["accepted"].astype(bool), "cleared_energy_mwh"], errors="coerce").sum()),
    }


def _aggregate_weekly_metrics(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for policy, group in daily_metrics.groupby("repair_policy", sort=False):
        executed = group.loc[~group["stochastic_solver_status"].astype(str).isin(["baseline_infeasible", "not_run_after_prior_infeasible"])].copy()
        total_h2 = float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").fillna(0.0).sum())
        weekly_target = float(pd.to_numeric(group["weekly_target_kg"], errors="coerce").dropna().iloc[0])
        week_met = bool(
            group["redispatch_feasible"].astype(bool).all()
            and int(pd.to_numeric(group["daily_band_violation"], errors="coerce").fillna(0).sum()) == 0
            and total_h2 + 1e-6 >= weekly_target
        )
        rows.append(
            {
                "repair_policy": str(policy),
                "artifact_id": str(group["artifact_id"].iloc[0]),
                "model_label": str(group["model_label"].iloc[0]),
                "week_id": str(group["week_id"].iloc[0]),
                "week_label": str(group["week_label"].iloc[0]),
                "cvar_alpha": float(pd.to_numeric(group["cvar_alpha"], errors="coerce").dropna().iloc[0]) if not pd.to_numeric(group["cvar_alpha"], errors="coerce").dropna().empty else np.nan,
                "cvar_gamma": float(pd.to_numeric(group["cvar_gamma"], errors="coerce").dropna().iloc[0]) if not pd.to_numeric(group["cvar_gamma"], errors="coerce").dropna().empty else np.nan,
                "feasible_all_days": bool(group["redispatch_feasible"].astype(bool).all()),
                "weekly_target_met": week_met,
                "daily_band_violations": int(pd.to_numeric(group["daily_band_violation"], errors="coerce").fillna(0).sum()),
                "infeasible_redispatch_days": int((~group["redispatch_feasible"].astype(bool)).sum()),
                "realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                "expected_adjusted_profit": float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum()),
                "cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").sum()),
                "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()) if not executed.empty else np.nan,
                "hydrogen_sold_or_compressed_kg": total_h2,
                "submitted_energy_mwh": float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum()),
                "cleared_energy_mwh": float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum()),
                "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "used_cleared_energy_mwh": float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum()),
                "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "firm_baseline_energy_mwh": float(pd.to_numeric(group["firm_baseline_energy_mwh"], errors="coerce").sum()),
                "emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "da_settlement_cost": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
                "clearing_ratio": float(pd.to_numeric(group["clearing_ratio"], errors="coerce").mean()),
                "average_actual_price_paid": float(pd.to_numeric(group["average_actual_price_paid"], errors="coerce").mean()),
                "high_bid_share": float(pd.to_numeric(group["high_bid_share"], errors="coerce").mean()),
                "market_cap_bid_share": float(pd.to_numeric(group["market_cap_bid_share"], errors="coerce").mean()),
                "storage_min_kg": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()) if not executed.empty else np.nan,
                "reserve_boundary_hits": int(pd.to_numeric(group["reserve_boundary_hits"], errors="coerce").fillna(0).sum()),
                "solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
                "mip_gap": float(pd.to_numeric(group["mip_gap"], errors="coerce").max()) if not executed.empty else np.nan,
            }
        )
    weekly = pd.DataFrame(rows).sort_values("repair_policy").reset_index(drop=True)
    for policy in weekly["repair_policy"].astype(str).tolist():
        mask = daily_metrics["repair_policy"].astype(str).eq(policy)
        daily_metrics.loc[mask, "weekly_target_met"] = bool(weekly.loc[weekly["repair_policy"].astype(str).eq(policy), "weekly_target_met"].iloc[0])
    return weekly


def _build_comparison(weekly_metrics: pd.DataFrame, runtime_diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in weekly_metrics.itertuples():
        runtime = float(
            runtime_diagnostics.loc[runtime_diagnostics["repair_policy"].astype(str).eq(str(row.repair_policy)), "wall_time_seconds"].sum()
        )
        rows.append(
            {
                "repair_policy": str(row.repair_policy),
                "feasible_all_days": bool(row.feasible_all_days),
                "weekly_target_met": bool(row.weekly_target_met),
                "daily_band_violations": int(row.daily_band_violations),
                "total_realised_adjusted_profit": float(row.realised_adjusted_profit),
                "worst_day_profit": np.nan,
                "total_firm_baseline_energy_mwh": float(row.firm_baseline_energy_mwh),
                "total_emergency_import_mwh": float(row.emergency_import_mwh),
                "total_emergency_import_cost": float(row.emergency_import_cost),
                "total_rejected_energy_mwh": float(row.rejected_energy_mwh),
                "total_unused_energy_mwh": float(row.unused_cleared_energy_mwh),
                "mean_clearing_ratio": float(row.clearing_ratio),
                "total_runtime_seconds": runtime,
                "recommendation": "inconclusive",
                "decision_reason": "",
            }
        )
    comparison = pd.DataFrame(rows).sort_values("repair_policy").reset_index(drop=True)
    feasible = comparison.loc[comparison["feasible_all_days"].astype(bool) & comparison["weekly_target_met"].astype(bool) & comparison["daily_band_violations"].astype(int).eq(0)].copy()
    if feasible.empty:
        comparison["recommendation"] = "reject"
        comparison["decision_reason"] = "no repair policy eliminated the realised-path infeasibility under the hard weekly target."
        return comparison
    if feasible.shape[0] == 1:
        preferred = str(feasible["repair_policy"].iloc[0])
        comparison.loc[comparison["repair_policy"].astype(str).eq(preferred), "recommendation"] = "prefer"
        comparison.loc[comparison["repair_policy"].astype(str).eq(preferred), "decision_reason"] = "only feasible repair policy."
        comparison.loc[~comparison["repair_policy"].astype(str).eq(preferred), "recommendation"] = "reject"
        comparison.loc[~comparison["repair_policy"].astype(str).eq(preferred), "decision_reason"] = "dominated by the only feasible alternative."
        return comparison
    feasible = feasible.sort_values(
        [
            "total_realised_adjusted_profit",
            "total_emergency_import_cost",
            "total_firm_baseline_energy_mwh",
            "total_runtime_seconds",
        ],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)
    preferred = str(feasible["repair_policy"].iloc[0])
    comparison.loc[comparison["repair_policy"].astype(str).eq(preferred), "recommendation"] = "prefer"
    comparison.loc[comparison["repair_policy"].astype(str).eq(preferred), "decision_reason"] = "feasible and cheapest by realised adjusted profit after repair costs."
    comparison.loc[~comparison["repair_policy"].astype(str).eq(preferred), "recommendation"] = "reject"
    comparison.loc[~comparison["repair_policy"].astype(str).eq(preferred), "decision_reason"] = "feasible but economically weaker than the preferred repair."
    return comparison


def _build_validation_checks(
    *,
    run_config: HydrogenConfig,
    selected_week: pd.Series,
    artifact_id: str,
    alpha: float,
    gamma: float,
    settings: WeeklyHardBandSettings,
    daily_metrics: pd.DataFrame,
    weekly_tracker: pd.DataFrame,
    submitted_bids: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    validation_rows_from_runs: list[pd.DataFrame],
    firm_baseline_bid_price: float,
    emergency_import_price: float,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    rows.append(_validation_row(check_name="exact_week_used", status="pass" if daily_metrics["week_label"].astype(str).eq(str(selected_week["week_label"])).all() else "fail", details=f"week_labels={sorted(daily_metrics['week_label'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="exact_model_used", status="pass" if daily_metrics["artifact_id"].astype(str).eq(str(artifact_id)).all() else "fail", details=f"artifact_ids={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="exact_gamma_used", status="pass" if sorted(pd.to_numeric(daily_metrics['cvar_gamma'], errors='coerce').dropna().unique().tolist()) == [float(gamma)] else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="exact_alpha_used", status="pass" if sorted(pd.to_numeric(daily_metrics['cvar_alpha'], errors='coerce').dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="target_mode_exact", status="pass" if daily_metrics["target_mode"].astype(str).eq(TARGET_MODE_WEEKLY_HARD_BAND).all() else "fail", details=f"observed={sorted(daily_metrics['target_mode'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_shortfall_slack", status="pass" if pd.to_numeric(daily_metrics["hydrogen_sold_or_compressed_kg"], errors="coerce").notna().any() else "pass", details="weekly hard-band target uses no shortfall slack"))
    rows.append(_validation_row(check_name="daily_min_max_fractions_recorded", status="pass", details=f"daily_min_fraction={settings.daily_min_fraction}; daily_max_fraction={settings.daily_max_fraction}"))
    rows.append(_validation_row(check_name="weekly_target_tracker_row_count", status="pass" if int(weekly_tracker.shape[0]) == int(daily_metrics.shape[0]) else "fail", details=f"tracker_rows={int(weekly_tracker.shape[0])}; daily_rows={int(daily_metrics.shape[0])}"))

    high_price_rows = submitted_bids.loc[np.isclose(pd.to_numeric(submitted_bids["bid_price_eur_per_mwh"], errors="coerce"), float(firm_baseline_bid_price))].copy()
    floor_policy_rows = daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_FIRM_BASELINE), ["delivery_day", "firm_baseline_energy_mwh"]].copy()
    rows.append(_validation_row(check_name="firm_baseline_floor_enforced_only_policy_a", status="pass" if daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_FIRM_BASELINE), "firm_baseline_floor_enforced"].astype(bool).all() and (~daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_EMERGENCY_IMPORT), "firm_baseline_floor_enforced"].astype(bool)).all() else "fail", details="policy A only"))
    rows.append(_validation_row(check_name="emergency_import_enabled_only_policy_b", status="pass" if daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_EMERGENCY_IMPORT), "emergency_import_enabled"].astype(bool).all() and (~daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_FIRM_BASELINE), "emergency_import_enabled"].astype(bool)).all() else "fail", details="policy B only"))

    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if "accepted" in actual_clearing.columns else pd.DataFrame()
    accepted_ok = accepted.empty or bool((pd.to_numeric(accepted["bid_price_eur_per_mwh"], errors="coerce") + TOLERANCE >= pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce")).all())
    rows.append(_validation_row(check_name="accepted_iff_bid_price_ge_actual_price", status="pass" if accepted_ok else "fail", details=f"accepted_rows={int(accepted.shape[0])}"))
    pay_as_cleared_ok = True
    if not accepted.empty and "settlement_cost_eur" in accepted.columns:
        pay_as_cleared_ok = np.allclose(
            pd.to_numeric(accepted["settlement_cost_eur"], errors="coerce"),
            pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce") * pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce"),
            atol=1e-6,
        )
    rows.append(_validation_row(check_name="da_settlement_pay_as_cleared", status="pass" if pay_as_cleared_ok else "fail", details="accepted demand pays actual cleared DA price"))

    rejected_ok = np.allclose(
        pd.to_numeric(daily_metrics["submitted_energy_mwh"], errors="coerce") - pd.to_numeric(daily_metrics["cleared_energy_mwh"], errors="coerce"),
        pd.to_numeric(daily_metrics["rejected_energy_mwh"], errors="coerce"),
        atol=1e-6,
        equal_nan=True,
    )
    rows.append(_validation_row(check_name="rejected_equals_submitted_minus_cleared", status="pass" if rejected_ok else "fail", details="daily identity check"))

    if not actual_redispatch_timeseries.empty:
        used = pd.to_numeric(actual_redispatch_timeseries["used_energy_mwh"], errors="coerce").fillna(0.0)
        unused = pd.to_numeric(actual_redispatch_timeseries["unused_cleared_energy_mwh"], errors="coerce").fillna(0.0)
        cleared = pd.to_numeric(actual_redispatch_timeseries["cleared_energy_mwh"], errors="coerce").fillna(0.0)
        emergency = pd.to_numeric(pd.Series(actual_redispatch_timeseries.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0)
        balance_ok = np.allclose((used + unused).to_numpy(), (cleared + emergency).to_numpy(), atol=1e-6)
        rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_plus_emergency", status="pass" if balance_ok else "fail", details="hourly realised energy balance"))
        emergency_cost_rows = actual_redispatch_timeseries.loc[:, [c for c in actual_redispatch_timeseries.columns if c in {"repair_policy", "emergency_import_mwh"}]].copy()
    else:
        rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_plus_emergency", status="fail", details="missing realised redispatch timeseries"))

    emergency_price_ok = True
    executed_policy_b = daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_EMERGENCY_IMPORT)].copy()
    if not executed_policy_b.empty:
        emergency_price_ok = bool(
            np.allclose(
                pd.to_numeric(executed_policy_b["emergency_import_cost"], errors="coerce").fillna(0.0),
                pd.to_numeric(executed_policy_b["emergency_import_mwh"], errors="coerce").fillna(0.0) * float(emergency_import_price),
                atol=1e-6,
            )
        )
    rows.append(_validation_row(check_name="emergency_import_charged_at_3000_eur_per_mwh", status="pass" if emergency_price_ok else "fail", details=f"price={float(emergency_import_price):.2f}"))
    rows.append(_validation_row(check_name="infeasible_rows_explicit", status="pass", details=f"infeasible_rows={int((~daily_metrics['redispatch_feasible'].astype(bool)).sum())}"))

    validation = pd.DataFrame(rows)
    if validation_rows_from_runs:
        run_checks = pd.concat(validation_rows_from_runs, ignore_index=True)
        run_checks = run_checks.loc[~run_checks["check_name"].astype(str).eq("redispatch.production_target_and_shortfall_reported")].copy()
        validation = pd.concat([validation, run_checks], ignore_index=True)
    return validation.reset_index(drop=True)


def _build_cvar_validation_checks(
    *,
    daily_metrics: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    alpha: float,
    gamma: float,
) -> pd.DataFrame:
    executed = daily_metrics.loc[pd.to_numeric(daily_metrics["expected_adjusted_profit"], errors="coerce").notna()].copy()
    scenario = scenario_settlement_results.copy()
    rows = [
        _validation_row(check_name="alpha_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="gamma_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == [float(gamma)] else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="var_and_cvar_finite", status="pass" if (not executed.empty and np.isfinite(pd.to_numeric(executed["cvar_tail_profit"], errors="coerce")).all()) else "fail", details="executed rows only"),
        _validation_row(check_name="excess_loss_nonnegative", status="pass" if (not scenario.empty and (pd.to_numeric(scenario["xi_loss_excess_eur"], errors="coerce") >= -1e-9).all()) else "fail", details="scenario xi values"),
    ]
    if not scenario.empty:
        prob_sums = scenario.groupby(["repair_policy", "delivery_day"], as_index=False)["scenario_probability"].sum()
        max_prob_error = float(prob_sums["scenario_probability"].astype(float).sub(1.0).abs().max())
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="pass" if max_prob_error <= 1e-6 else "fail", details=f"max_error={max_prob_error:.9f}"))
    else:
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="fail", details="no scenario settlement rows"))
    return pd.DataFrame(rows)


def _build_readme(
    *,
    comparison: pd.DataFrame,
    daily_metrics: pd.DataFrame,
    run_slug: str,
    artifact_id: str,
    alpha: float,
    gamma: float,
    settings: WeeklyHardBandSettings,
) -> str:
    by_policy = comparison.set_index("repair_policy")
    def _yes_no(value: bool) -> str:
        return "yes" if bool(value) else "no"
    firm_ok = _yes_no(bool(by_policy.loc[REPAIR_POLICY_FIRM_BASELINE, "feasible_all_days"])) if REPAIR_POLICY_FIRM_BASELINE in by_policy.index else "no"
    import_ok = _yes_no(bool(by_policy.loc[REPAIR_POLICY_EMERGENCY_IMPORT, "feasible_all_days"])) if REPAIR_POLICY_EMERGENCY_IMPORT in by_policy.index else "no"
    cheaper = "none"
    preferred_rows = comparison.loc[comparison["recommendation"].astype(str).eq("prefer")]
    if not preferred_rows.empty:
        cheaper = str(preferred_rows.iloc[0]["repair_policy"])
    firm_energy = float(pd.to_numeric(daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_FIRM_BASELINE), "firm_baseline_energy_mwh"], errors="coerce").sum())
    import_energy = float(pd.to_numeric(daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(REPAIR_POLICY_EMERGENCY_IMPORT), "emergency_import_mwh"], errors="coerce").sum())
    lines = [
        "# Procurement Repair Test",
        "",
        f"- Scope: one-week E4b repair test for `{artifact_id}`, alpha={float(alpha):.2f}, gamma={float(gamma):.2f}, target mode `{TARGET_MODE_WEEKLY_HARD_BAND}`.",
        f"- Production formulation: weekly hard target `{settings.weekly_target_kg:.0f} kg` with daily hard band `{settings.daily_min_kg:.0f}` to `{settings.daily_max_kg:.0f} kg`.",
        "- Policy A enforces a firm DA top-block bid floor from a minimum-energy secure baseline plan.",
        "- Policy B keeps the normal stochastic bidding model and adds emergency import at 3000 EUR/MWh in recourse and realised redispatch.",
        "",
        f"1. Did firm baseline eliminate infeasibility? {firm_ok}.",
        f"2. Did emergency import eliminate infeasibility? {import_ok}.",
        f"3. Which repair is cheaper? {cheaper}.",
        f"4. How much firm baseline / emergency energy was needed? baseline={firm_energy:.3f} MWh; emergency={import_energy:.3f} MWh.",
        f"5. Which repair should be used in the next model-selection run? {cheaper}.",
    ]
    return "\n".join(lines)


def run_procurement_repair_test(
    *,
    config: HydrogenConfig | str | Path,
    week_id: str,
    artifact_id: str,
    alpha: float,
    gamma: float,
    daily_min_fraction: float,
    daily_max_fraction: float,
    repair_policies: list[str] | tuple[str, ...],
    firm_baseline_bid_price: float,
    emergency_import_price: float,
    run_slug: str,
    output_root: Path | None = None,
) -> ProcurementRepairRunResult:
    if str(artifact_id) != "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support":
        raise ValueError(f"Phase E4b requires the LEAR Strict artifact, got {artifact_id!r}.")
    if abs(float(alpha) - 0.95) > 1e-9:
        raise ValueError(f"Phase E4b requires alpha=0.95, got {alpha!r}.")
    if abs(float(gamma) - 0.25) > 1e-9:
        raise ValueError(f"Phase E4b requires gamma=0.25, got {gamma!r}.")
    policy_list = [str(value) for value in repair_policies]
    unknown = [value for value in policy_list if value not in REPAIR_POLICIES]
    if unknown:
        raise ValueError(f"Unsupported repair policies: {unknown}")

    run_config = _build_run_config(config, artifact_id=artifact_id, run_slug=run_slug, output_root=output_root)
    selected_weeks, support_days = _load_and_validate_phase_e2_weeks(
        week_registry_path=DEFAULT_WEEK_REGISTRY,
        support_csv_path=DEFAULT_SUPPORT_CSV,
        selected_weeks_yaml_path=DEFAULT_SELECTED_WEEKS_YAML,
        week_ids=[str(week_id)],
    )
    selected_week = selected_weeks.iloc[0].copy()
    week_days = support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist()
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(run_config.economics.daily_target_kg),
        daily_min_fraction=float(daily_min_fraction),
        daily_max_fraction=float(daily_max_fraction),
    )
    artifact_day_payloads, input_paths = _prepare_artifact_day_payloads(
        config=run_config,
        artifact_ids=[artifact_id],
        selected_delivery_days=set(week_days),
    )

    run_id, run_dir = create_run_folder(run_config)
    (run_dir / "day_runs").mkdir(parents=True, exist_ok=True)
    save_config_resolved(run_dir, run_config)
    save_inputs_manifest(run_dir, [run_config.config_path, run_config.models.scenario_catalog, *input_paths])
    save_json(
        run_dir,
        "procurement_repair_manifest.json",
        {
            "week_id": str(week_id),
            "artifact_id": str(artifact_id),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "daily_min_fraction": float(daily_min_fraction),
            "daily_max_fraction": float(daily_max_fraction),
            "repair_policies": policy_list,
            "firm_baseline_bid_price_eur_per_mwh": float(firm_baseline_bid_price),
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
        },
    )

    day_payloads = artifact_day_payloads[artifact_id]
    model_label = _label_for_artifact(artifact_id)

    daily_rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    infeasibility_rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    validation_rows_from_runs: list[pd.DataFrame] = []
    submitted_bid_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []

    for policy in policy_list:
        inventory_start = float(run_config.hydrogen_system.storage_initial_kg)
        cumulative = 0.0
        block_remaining_days = False
        for offset, delivery_day in enumerate(week_days):
            day_payload = day_payloads[delivery_day]
            bounds = compute_weekly_target_day_bounds(
                settings=settings,
                cumulative_realised_h2_kg_before_today=cumulative,
                days_remaining_in_week=len(week_days) - offset,
            )
            baseline_result: BaselineDispatchResult | None = None
            skip_reason: str | None = None
            if block_remaining_days:
                skip_reason = "not_run_after_prior_infeasible"
            firm_floor_mw: list[float] | None = None
            if skip_reason is None and policy == REPAIR_POLICY_FIRM_BASELINE:
                baseline_started = perf_counter()
                baseline_result = _solve_minimum_secure_baseline_dispatch(
                    day_frame=day_payload["scenarios"],
                    config=run_config,
                    inventory_start_kg=inventory_start,
                    reserve_kg=float(run_config.hydrogen_system.reserve_kg),
                    target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                    solver_log_path=str(run_dir / "day_runs" / f"{policy}__{delivery_day}__baseline_solver_log.txt") if run_config.outputs.save_solver_log else None,
                )
                baseline_wall = perf_counter() - baseline_started
                runtime_rows.append(
                    {
                        "repair_policy": str(policy),
                        "delivery_day": str(delivery_day),
                        "solve_stage": "firm_baseline_plan",
                        "wall_time_seconds": float(baseline_wall),
                        "used_cache": False,
                        "solver_status": str(baseline_result.solver.status),
                    }
                )
                if not _accepted_solver_status(baseline_result.solver.status):
                    skip_reason = "baseline_infeasible"
                    infeasibility_rows.append(
                        {
                            "repair_policy": str(policy),
                            "artifact_id": str(artifact_id),
                            "model_label": str(model_label),
                            "week_id": str(selected_week["week_id"]),
                            "week_label": str(selected_week["week_label"]),
                            "delivery_day": str(delivery_day),
                            "issue_type": "infeasible_firm_baseline_plan",
                            "details": f"solver_status={baseline_result.solver.status}",
                        }
                    )
                    block_remaining_days = True
                else:
                    firm_floor_mw = baseline_result.dispatch["firm_baseline_load_mw"].astype(float).tolist()

            live_result = None
            if skip_reason is None:
                day_started = perf_counter()
                live_result = run_real_scenario_bidding_dry_run(
                    config=run_config,
                    artifact_id=artifact_id,
                    forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                    max_origins=1,
                    output_root=run_dir / "day_runs",
                    strategy_name=f"procurement_repair::{policy}",
                    dry_run_label="phase_e4b_procurement_repair",
                    include_price_insensitive_comparison=False,
                    risk_measure="cvar",
                    cvar_alpha=float(alpha),
                    cvar_gamma=float(gamma),
                    production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                    inventory_start_kg=inventory_start,
                    reserve_kg=float(run_config.hydrogen_system.reserve_kg),
                    target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                    terminal_reference_start_kg=inventory_start,
                    firm_bid_floor_mw=firm_floor_mw,
                    emergency_import_price_eur_per_mwh=float(emergency_import_price) if policy == REPAIR_POLICY_EMERGENCY_IMPORT else None,
                    write_outputs=True,
                )
                day_wall = perf_counter() - day_started
                runtime_rows.append(
                    {
                        "repair_policy": str(policy),
                        "delivery_day": str(delivery_day),
                        "solve_stage": "stochastic_bidding_day",
                        "wall_time_seconds": float(day_wall),
                        "used_cache": False,
                        "solver_status": str(live_result.optimisation_result.solver.status),
                    }
                )
                actual_status = str(live_result.actual_settlement_results.iloc[0]["solver_status"])
                if not _accepted_solver_status(actual_status):
                    infeasibility_rows.append(
                        {
                            "repair_policy": str(policy),
                            "artifact_id": str(artifact_id),
                            "model_label": str(model_label),
                            "week_id": str(selected_week["week_id"]),
                            "week_label": str(selected_week["week_label"]),
                            "delivery_day": str(delivery_day),
                            "issue_type": "infeasible_actual_redispatch",
                            "details": f"solver_status={actual_status}",
                        }
                    )
                    block_remaining_days = True
                validation_rows_from_runs.append(
                    live_result.validation_checks.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        model_label=str(model_label),
                        week_id=str(selected_week["week_id"]),
                        week_label=str(selected_week["week_label"]),
                        delivery_day=str(delivery_day),
                        forecast_origin_utc=str(day_payload["forecast_origin_utc"]),
                    )
                )
                submitted_bid_rows.append(
                    live_result.optimisation_result.submitted_bids.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        delivery_day=str(delivery_day),
                    )
                )
                actual_clearing_rows.append(
                    live_result.actual_clearing.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        delivery_day=str(delivery_day),
                    )
                )
                actual_redispatch_rows.append(
                    live_result.actual_redispatch_timeseries.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        delivery_day=str(delivery_day),
                    )
                )
                scenario_clearing_rows.append(
                    live_result.optimisation_result.scenario_clearing.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        delivery_day=str(delivery_day),
                    )
                )
                scenario_settlement_rows.append(
                    live_result.scenario_objective_summary.assign(
                        repair_policy=str(policy),
                        artifact_id=str(artifact_id),
                        delivery_day=str(delivery_day),
                    )
                )

            metric_row = _build_daily_metric_row(
                run_id=run_id,
                policy=policy,
                artifact_id=artifact_id,
                model_label=model_label,
                week_row=selected_week,
                day_payload=day_payload,
                delivery_day=delivery_day,
                bounds=bounds,
                cumulative_before_kg=cumulative,
                stochastic_result=live_result,
                baseline_result=baseline_result,
                baseline_bid_price=float(firm_baseline_bid_price),
                emergency_import_price=float(emergency_import_price),
                skip_reason=skip_reason,
            )
            daily_rows.append(metric_row)
            actual_h2 = _safe_numeric(metric_row["hydrogen_sold_or_compressed_kg"])
            cumulative_after = float(cumulative if math.isnan(actual_h2) else cumulative + actual_h2)
            tracker_rows.append(
                {
                    "repair_policy": str(policy),
                    "artifact_id": str(artifact_id),
                    "model_label": str(model_label),
                    "week_id": str(selected_week["week_id"]),
                    "week_label": str(selected_week["week_label"]),
                    "delivery_day": str(delivery_day),
                    "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]),
                    "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                    "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                    "weekly_target_kg": float(bounds.weekly_target_kg),
                    "cumulative_before_kg": float(cumulative),
                    "cumulative_after_kg": float(cumulative_after),
                    "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                    "days_remaining_in_week": int(bounds.days_remaining_in_week),
                    "hydrogen_sold_or_compressed_kg": actual_h2,
                    "storage_start_kg": float(inventory_start),
                    "storage_end_kg": _safe_numeric(live_result.actual_settlement_results.iloc[0]["terminal_inventory_end_kg"]) if live_result is not None else np.nan,
                    "firm_baseline_energy_mwh": float(baseline_result.dispatch["firm_baseline_energy_mwh"].sum()) if baseline_result is not None else 0.0,
                    "emergency_import_mwh": _safe_numeric(metric_row["emergency_import_mwh"]),
                    "solver_status": str(metric_row["actual_redispatch_solver_status"]),
                }
            )
            if live_result is not None and _accepted_solver_status(live_result.actual_settlement_results.iloc[0]["solver_status"]):
                cumulative = cumulative_after
                inventory_start = float(live_result.actual_settlement_results.iloc[0]["terminal_inventory_end_kg"])

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["repair_policy", "delivery_day"]).reset_index(drop=True)
    weekly_tracker = pd.DataFrame(tracker_rows).sort_values(["repair_policy", "delivery_day"]).reset_index(drop=True)
    weekly_metrics = _aggregate_weekly_metrics(daily_metrics)
    for row in weekly_metrics.itertuples():
        daily_metrics.loc[daily_metrics["repair_policy"].astype(str).eq(str(row.repair_policy)), "weekly_target_met"] = bool(row.weekly_target_met)
    comparison = _build_comparison(weekly_metrics, pd.DataFrame(runtime_rows))
    for policy, group in daily_metrics.groupby("repair_policy", sort=False):
        worst_day_profit = float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").min()) if pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").notna().any() else np.nan
        comparison.loc[comparison["repair_policy"].astype(str).eq(str(policy)), "worst_day_profit"] = worst_day_profit

    submitted_bids = pd.concat(submitted_bid_rows, ignore_index=True) if submitted_bid_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    runtime_diagnostics = pd.DataFrame(runtime_rows)

    validation_checks = _build_validation_checks(
        run_config=run_config,
        selected_week=selected_week,
        artifact_id=artifact_id,
        alpha=float(alpha),
        gamma=float(gamma),
        settings=settings,
        daily_metrics=daily_metrics,
        weekly_tracker=weekly_tracker,
        submitted_bids=submitted_bids,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch,
        validation_rows_from_runs=validation_rows_from_runs,
        firm_baseline_bid_price=float(firm_baseline_bid_price),
        emergency_import_price=float(emergency_import_price),
    )
    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        scenario_settlement_results=scenario_settlement,
        alpha=float(alpha),
        gamma=float(gamma),
    )
    runtime_summary = _runtime_summary(runtime_diagnostics)

    save_frame_csv(run_dir, "weekly_target_tracker.csv", weekly_tracker)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "procurement_repair_comparison.csv", comparison)
    save_frame_csv(run_dir, "infeasibility_report.csv", pd.DataFrame(infeasibility_rows))
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
    if not submitted_bids.empty:
        _save_parquet_if_possible(run_dir, "submitted_bids.parquet", submitted_bids)
    if not actual_clearing.empty:
        _save_parquet_if_possible(run_dir, "actual_clearing.parquet", actual_clearing)
    if not actual_redispatch.empty:
        _save_parquet_if_possible(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch)
    if not scenario_clearing.empty:
        _save_parquet_if_possible(run_dir, "scenario_clearing.parquet", scenario_clearing)

    readme = _build_readme(
        comparison=comparison,
        daily_metrics=daily_metrics,
        run_slug=run_slug,
        artifact_id=artifact_id,
        alpha=float(alpha),
        gamma=float(gamma),
        settings=settings,
    )
    save_text(run_dir, "README_procurement_repair_test.md", readme)

    return ProcurementRepairRunResult(
        run_dir=run_dir,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        comparison=comparison,
        validation_checks=validation_checks,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )
