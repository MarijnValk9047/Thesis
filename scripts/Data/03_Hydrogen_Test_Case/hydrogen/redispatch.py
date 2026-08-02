from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from scripts.optimisation_performance import (
    StructuralSignature,
    StructuralTemplateCache,
    dst_shape_for_steps,
    stable_hash,
    validate_performance_mode,
)

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
from .plant_parameters import HydrogenConfig
from .production_target import WeeklyQuotaDeadlinePlan
from .validation_checks import validate_dispatch_physical, validate_redispatch_solution


@dataclass(frozen=True)
class RedispatchSolveResult:
    timeseries: pd.DataFrame
    summary: pd.DataFrame
    validation_checks: pd.DataFrame
    solver: SolverResult
    model_stats: ModelStats
    performance: dict[str, Any] | None = None


_REDISPATCH_TEMPLATE_CACHE = StructuralTemplateCache()


def validate_cleared_profile_schema(cleared_profile: pd.DataFrame) -> pd.DataFrame:
    required = {
        "delivery_start_utc",
        "cleared_energy_mwh",
        "actual_price_eur_per_mwh",
        "timestep_hours",
    }
    missing = required.difference(cleared_profile.columns)
    if missing:
        raise ValueError(f"Cleared profile is missing required columns: {sorted(missing)}")

    frame = cleared_profile.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["cleared_energy_mwh"] = pd.to_numeric(frame["cleared_energy_mwh"], errors="raise")
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["actual_price_eur_per_mwh"], errors="raise")
    frame["timestep_hours"] = pd.to_numeric(frame["timestep_hours"], errors="raise")
    if frame["delivery_start_utc"].duplicated().any():
        raise ValueError("Cleared profile contains duplicate delivery_start_utc rows.")
    if (frame["cleared_energy_mwh"] < -1e-9).any():
        raise ValueError("Cleared profile contains negative cleared_energy_mwh values.")
    if (frame["timestep_hours"] <= 0.0).any():
        raise ValueError("Cleared profile contains nonpositive timestep_hours values.")
    if frame["timestep_hours"].nunique() != 1:
        raise ValueError("Cleared profile must use a constant timestep_hours value within one solve.")
    return frame.sort_values("delivery_start_utc").reset_index(drop=True)


def _metadata_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in (
            "run_id",
            "strategy",
            "source_strategy",
            "bridge_strategy",
            "actual_path_id",
            "forecast_model",
            "scenario_model",
            "granularity",
            "horizon",
            "forecast_origin_utc",
            "redispatch_case",
        )
        if column in frame.columns
    ]


def _diagnose_unused_energy_reason(timeseries: pd.DataFrame, config: HydrogenConfig, tolerance: float = 1e-6) -> str:
    if timeseries.empty or "unused_cleared_energy_mwh" not in timeseries.columns:
        return "not_applicable"
    unused_mask = timeseries["unused_cleared_energy_mwh"].astype(float) > tolerance
    if not bool(unused_mask.any()):
        return "none"

    reasons: list[str] = []
    subset = timeseries.loc[unused_mask].copy()
    max_component_use_mwh = subset["used_energy_mwh"].astype(float) >= (
        subset["timestep_hours"].astype(float)
        * (config.hydrogen_system.electrolyser_nominal_mw + config.hydrogen_system.compressor_max_mw)
        - tolerance
    )
    if bool(max_component_use_mwh.any()):
        reasons.append("electrolyser_and_compressor_power_limits")
    elif bool((subset["P_el_mw"].astype(float) >= config.hydrogen_system.electrolyser_nominal_mw - tolerance).any()):
        reasons.append("electrolyser_power_limit")
    elif bool((subset["P_comp_mw"].astype(float) >= config.hydrogen_system.compressor_max_mw - tolerance).any()):
        reasons.append("compressor_power_limit")

    if bool((subset["H_buf_kg"].astype(float) >= config.hydrogen_system.storage_capacity_kg - tolerance).any()):
        reasons.append("storage_capacity_limit")

    if bool((subset["u_el"].astype(float) <= tolerance).all() and (subset["cleared_energy_mwh"].astype(float) > tolerance).all()):
        reasons.append("minimum_load_and_ramp_constraints")

    if not reasons:
        reasons.append("physical_constraints_binding_not_uniquely_diagnosed")
    return ";".join(dict.fromkeys(reasons))


def _build_summary(
    *,
    timeseries: pd.DataFrame,
    config: HydrogenConfig,
    solver: SolverResult,
    model_stats: ModelStats,
    metadata: dict[str, Any],
    inventory_start_kg: float,
    reserve_kg: float,
    target_hydrogen_kg: float,
    terminal_reference_start_kg: float,
    shortfall_penalty_eur_per_kg: float,
    emergency_import_price_eur_per_mwh: float | None,
) -> pd.DataFrame:
    tolerance = 1e-6
    used_energy_mwh = float(timeseries["used_energy_mwh"].sum())
    cleared_energy_mwh = float(timeseries["cleared_energy_mwh"].sum())
    unused_energy_mwh = float(timeseries["unused_cleared_energy_mwh"].sum())
    emergency_import_mwh = float(pd.to_numeric(pd.Series(timeseries.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0).sum())
    hydrogen_produced_kg = float(timeseries["H_prod_kg"].sum())
    hydrogen_compressed_kg = float(timeseries["H_comp_kg"].sum())
    hydrogen_above_target_kg = float(max(hydrogen_compressed_kg - target_hydrogen_kg, 0.0))
    shortfall_kg = float(timeseries["shortfall_kg"].iloc[0]) if not timeseries.empty else float("nan")
    storage_min_kg = float(timeseries["H_buf_kg"].min()) if not timeseries.empty else float("nan")
    storage_max_kg = float(timeseries["H_buf_kg"].max()) if not timeseries.empty else float("nan")
    terminal_inventory_change_kg = float(timeseries["H_buf_kg"].iloc[-1] - terminal_reference_start_kg) if not timeseries.empty else float("nan")
    terminal_inventory_correction_eur = float(config.terminal_inventory_value_per_kg * terminal_inventory_change_kg)
    realised_settlement_cost = float((timeseries["actual_price_eur_per_mwh"] * timeseries["cleared_energy_mwh"]).sum())
    hydrogen_revenue = float(config.economics.h2_sale_price_eur_per_kg * hydrogen_compressed_kg)
    unused_energy_penalty = float(config.economics.unused_energy_penalty_eur_per_mwh * unused_energy_mwh)
    emergency_import_cost = float(emergency_import_mwh * float(emergency_import_price_eur_per_mwh)) if emergency_import_price_eur_per_mwh is not None else 0.0
    shortfall_penalty = float(shortfall_penalty_eur_per_kg * shortfall_kg)
    redispatch_objective_excluding_settlement = float(
        hydrogen_revenue
        - unused_energy_penalty
        - emergency_import_cost
        - shortfall_penalty
        + terminal_inventory_correction_eur
    )
    realised_adjusted_profit = float(
        hydrogen_revenue
        - realised_settlement_cost
        - unused_energy_penalty
        - emergency_import_cost
        - shortfall_penalty
        + terminal_inventory_correction_eur
    )
    reserve_boundary_hits = int(np.sum(np.isclose(timeseries["H_buf_kg"].to_numpy(), reserve_kg, atol=1e-3)))
    ramp_limit = config.hydrogen_system.electrolyser_ramp_mw_per_h * model_stats.timestep_hours
    ramps = timeseries["P_el_mw"].astype(float).diff().abs().dropna()
    ramp_boundary_hits = int(np.sum(np.isclose(ramps.to_numpy(), ramp_limit, atol=1e-3))) if not ramps.empty else 0

    row = {
        **metadata,
        "cleared_energy_mwh": cleared_energy_mwh,
        "used_energy_mwh": used_energy_mwh,
        "unused_cleared_energy_mwh": unused_energy_mwh,
        "unused_energy_share": float(unused_energy_mwh / cleared_energy_mwh) if cleared_energy_mwh > tolerance else 0.0,
        "unused_energy_penalty_eur_per_mwh": float(config.economics.unused_energy_penalty_eur_per_mwh),
        "shortfall_penalty_eur_per_kg": float(shortfall_penalty_eur_per_kg),
        "realised_DA_settlement_cost_eur": realised_settlement_cost,
        "hydrogen_revenue_eur": hydrogen_revenue,
        "unused_energy_penalty_eur": unused_energy_penalty,
        "emergency_import_mwh": emergency_import_mwh,
        "emergency_import_cost_eur": emergency_import_cost,
        "unused_energy_physical_reason": _diagnose_unused_energy_reason(timeseries, config),
        "shortfall_penalty_eur": shortfall_penalty,
        "hydrogen_produced_kg": hydrogen_produced_kg,
        "hydrogen_compressed_or_sold_kg": hydrogen_compressed_kg,
        "hydrogen_above_target_kg": hydrogen_above_target_kg,
        "target_hydrogen_kg": float(target_hydrogen_kg),
        "shortfall_kg": shortfall_kg,
        "target_fulfilment_ratio": float(min(hydrogen_compressed_kg, target_hydrogen_kg) / target_hydrogen_kg) if target_hydrogen_kg > tolerance else np.nan,
        "target_fulfilment_ratio_capped_for_reliability": float(min(hydrogen_compressed_kg, target_hydrogen_kg) / target_hydrogen_kg) if target_hydrogen_kg > tolerance else np.nan,
        "production_to_target_ratio_uncapped": float(hydrogen_compressed_kg / target_hydrogen_kg) if target_hydrogen_kg > tolerance else np.nan,
        "terminal_inventory_start_kg": float(terminal_reference_start_kg),
        "terminal_inventory_end_kg": float(timeseries["H_buf_kg"].iloc[-1]) if not timeseries.empty else float("nan"),
        "terminal_inventory_change_kg": terminal_inventory_change_kg,
        "terminal_inventory_correction_eur": terminal_inventory_correction_eur,
        "revenue_from_total_hydrogen_eur": hydrogen_revenue,
        "revenue_associated_with_above_target_hydrogen_eur": float(hydrogen_above_target_kg * config.economics.h2_sale_price_eur_per_kg),
        "redispatch_objective_excluding_settlement_eur": redispatch_objective_excluding_settlement,
        "realised_adjusted_profit_eur": realised_adjusted_profit,
        "storage_initial_kg": float(inventory_start_kg),
        "storage_min_kg": storage_min_kg,
        "storage_max_kg": storage_max_kg,
        "reserve_boundary_hits": reserve_boundary_hits,
        "ramp_boundary_hits": ramp_boundary_hits,
        "solver_status": solver.status,
        "objective_value": solver.objective_value,
        "solve_time_seconds": solver.runtime_seconds,
        "variable_count": model_stats.variable_count,
        "binary_variable_count": model_stats.binary_variable_count,
        "constraint_count": model_stats.constraint_count,
        "timestep_hours": model_stats.timestep_hours,
    }
    return pd.DataFrame([row])


def _solve_with_pyomo(
    *,
    profile: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    target_hydrogen_kg: float,
    target_hydrogen_max_kg: float | None,
    terminal_reference_start_kg: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float,
    solver_log_path: str | None,
    emergency_import_price_eur_per_mwh: float | None,
    previous_electrolyser_power_mw: float | None,
    weekly_quota_plan: WeeklyQuotaDeadlinePlan | None,
) -> tuple[pd.DataFrame, SolverResult, ModelStats]:
    if pyo is None:
        raise RuntimeError("Pyomo backend requested but Pyomo is not installed.")

    delta_t_hours = float(profile["timestep_hours"].iloc[0])
    timestamps = pd.DatetimeIndex(profile["delivery_start_utc"])
    cleared_lookup = dict(enumerate(profile["cleared_energy_mwh"].astype(float).tolist()))
    price_lookup = dict(enumerate(profile["actual_price_eur_per_mwh"].astype(float).tolist()))
    t_max = len(timestamps) - 1
    horizon = list(range(len(timestamps)))
    ramp_limit = config.hydrogen_system.electrolyser_ramp_mw_per_h * delta_t_hours

    build_started = perf_counter()
    m = pyo.ConcreteModel(name="hydrogen_actual_redispatch")
    m.T = pyo.RangeSet(0, t_max)
    m.P_el = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.u_el = pyo.Var(m.T, domain=pyo.Binary)
    m.H_prod = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.P_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.H_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.H_buf = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.unused = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    emergency_import_enabled = emergency_import_price_eur_per_mwh is not None and float(emergency_import_price_eur_per_mwh) > 0.0
    if emergency_import_enabled:
        m.emergency_import = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.shortfall = pyo.Var(domain=pyo.NonNegativeReals)

    m.constraints = pyo.ConstraintList()
    for t in horizon:
        m.constraints.add(m.P_el[t] >= config.hydrogen_system.electrolyser_min_mw * m.u_el[t])
        m.constraints.add(m.P_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * m.u_el[t])
        m.constraints.add(m.H_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * m.P_el[t] * delta_t_hours)
        m.constraints.add(m.P_comp[t] <= config.hydrogen_system.compressor_max_mw)
        m.constraints.add(
            m.P_comp[t] * delta_t_hours
            == config.hydrogen_system.compressor_specific_mwh_per_kg * m.H_comp[t]
        )
        if emergency_import_enabled:
            m.constraints.add(
                delta_t_hours * (m.P_el[t] + m.P_comp[t]) + m.unused[t]
                == cleared_lookup[t] + m.emergency_import[t]
            )
        else:
            m.constraints.add(
                delta_t_hours * (m.P_el[t] + m.P_comp[t]) + m.unused[t] == cleared_lookup[t]
            )
        if t == 0:
            m.constraints.add(m.H_buf[t] == inventory_start_kg + m.H_prod[t] - m.H_comp[t])
            if previous_electrolyser_power_mw is not None:
                previous_power = float(previous_electrolyser_power_mw)
                m.constraints.add(m.P_el[t] - previous_power <= ramp_limit)
                m.constraints.add(previous_power - m.P_el[t] <= ramp_limit)
        else:
            m.constraints.add(m.H_buf[t] == m.H_buf[t - 1] + m.H_prod[t] - m.H_comp[t])
            m.constraints.add(m.P_el[t] - m.P_el[t - 1] <= ramp_limit)
            m.constraints.add(m.P_el[t - 1] - m.P_el[t] <= ramp_limit)
        m.constraints.add(m.H_buf[t] >= reserve_kg)
        m.constraints.add(m.H_buf[t] <= config.hydrogen_system.storage_capacity_kg)

    if weekly_quota_plan is not None:
        for quota_constraint in weekly_quota_plan.constraints:
            m.constraints.add(
                sum(m.H_comp[t] for t in quota_constraint.horizon_time_indices)
                >= float(quota_constraint.minimum_horizon_compression_kg)
            )

    target_hydrogen_max_kg_value = (
        None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    )
    sum_h_comp = sum(m.H_comp[t] for t in horizon)
    total_unused = sum(m.unused[t] for t in horizon)
    if str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
        m.constraints.add(sum_h_comp >= target_hydrogen_kg)
        if target_hydrogen_max_kg_value is not None:
            m.constraints.add(sum_h_comp <= target_hydrogen_max_kg_value)
        m.constraints.add(m.shortfall == 0.0)
    else:
        m.constraints.add(sum_h_comp + m.shortfall >= target_hydrogen_kg)

    hydrogen_revenue = config.economics.h2_sale_price_eur_per_kg * sum_h_comp
    unused_penalty = config.economics.unused_energy_penalty_eur_per_mwh * total_unused
    emergency_import_cost = (
        float(emergency_import_price_eur_per_mwh) * sum(m.emergency_import[t] for t in horizon)
        if emergency_import_enabled
        else 0.0
    )
    shortfall_penalty = shortfall_penalty_eur_per_kg * m.shortfall
    terminal_value = config.terminal_inventory_value_per_kg * (m.H_buf[t_max] - terminal_reference_start_kg)
    m.objective = pyo.Objective(
        expr=hydrogen_revenue - unused_penalty - emergency_import_cost - shortfall_penalty + terminal_value,
        sense=pyo.maximize,
    )

    model_build_time = perf_counter() - build_started
    solver, solver_name = _resolve_pyomo_solver(config.solver, solver_log_path)
    started = perf_counter()
    try:
        if solver_log_path is not None:
            results = solver.solve(m, tee=False, logfile=solver_log_path)
        else:
            results = solver.solve(m, tee=False)
    except TypeError:
        results = solver.solve(m, tee=False)
    solver_runtime = perf_counter() - started

    solver_status = getattr(getattr(results, "solver", None), "status", None)
    termination = getattr(getattr(results, "solver", None), "termination_condition", None)
    termination_text = str(termination).strip().lower() if termination is not None else ""
    status_text = "Optimal" if termination_text == "optimal" else f"{solver_status}:{termination}"

    postprocess_started = perf_counter()
    dispatch = pd.DataFrame(
        {
            "delivery_start_utc": list(timestamps),
            "P_el_mw": [float(_safe_pyomo_value(m.P_el[t]) or 0.0) for t in horizon],
            "u_el": [float(_safe_pyomo_value(m.u_el[t]) or 0.0) for t in horizon],
            "H_prod_kg": [float(_safe_pyomo_value(m.H_prod[t]) or 0.0) for t in horizon],
            "P_comp_mw": [float(_safe_pyomo_value(m.P_comp[t]) or 0.0) for t in horizon],
            "H_comp_kg": [float(_safe_pyomo_value(m.H_comp[t]) or 0.0) for t in horizon],
            "H_buf_kg": [float(_safe_pyomo_value(m.H_buf[t]) or 0.0) for t in horizon],
            "unused_cleared_energy_mwh": [float(_safe_pyomo_value(m.unused[t]) or 0.0) for t in horizon],
            "emergency_import_mwh": [float(_safe_pyomo_value(m.emergency_import[t]) or 0.0) for t in horizon] if emergency_import_enabled else [0.0 for _ in horizon],
            "shortfall_kg": float(_safe_pyomo_value(m.shortfall) or 0.0),
            "cleared_energy_mwh": [float(cleared_lookup[t]) for t in horizon],
            "actual_price_eur_per_mwh": [float(price_lookup[t]) for t in horizon],
            "timestep_hours": float(delta_t_hours),
        }
    )
    dispatch["used_energy_mwh"] = delta_t_hours * (dispatch["P_el_mw"] + dispatch["P_comp_mw"])
    dispatch["settlement_cost_eur"] = dispatch["actual_price_eur_per_mwh"] * dispatch["cleared_energy_mwh"]
    dispatch["unused_energy_penalty_eur"] = dispatch["unused_cleared_energy_mwh"] * config.economics.unused_energy_penalty_eur_per_mwh
    dispatch["hydrogen_revenue_eur"] = dispatch["H_comp_kg"] * config.economics.h2_sale_price_eur_per_kg
    dispatch["terminal_inventory_value_eur_contrib"] = 0.0
    dispatch.loc[dispatch.index[-1], "terminal_inventory_value_eur_contrib"] = (
        config.terminal_inventory_value_per_kg * (dispatch["H_buf_kg"].iloc[-1] - terminal_reference_start_kg)
    )

    model_stats = _pyomo_model_stats(
        m,
        scenario_count=1,
        horizon_steps=len(horizon),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    solver_result = SolverResult(
        status=status_text,
        objective_value=_safe_pyomo_value(m.objective),
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(config.solver.mip_gap),
        solver_package="pyomo",
        solver_name=str(solver_name),
        termination_condition=str(termination) if termination is not None else None,
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
    )
    return dispatch, solver_result, model_stats


def _solve_with_pulp(
    *,
    profile: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    target_hydrogen_kg: float,
    target_hydrogen_max_kg: float | None,
    terminal_reference_start_kg: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float,
    solver_log_path: str | None,
    emergency_import_price_eur_per_mwh: float | None,
    previous_electrolyser_power_mw: float | None,
    weekly_quota_plan: WeeklyQuotaDeadlinePlan | None,
) -> tuple[pd.DataFrame, SolverResult, ModelStats]:
    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")

    build_started = perf_counter()
    delta_t_hours = float(profile["timestep_hours"].iloc[0])
    timestamps = pd.DatetimeIndex(profile["delivery_start_utc"])
    cleared_lookup = dict(enumerate(profile["cleared_energy_mwh"].astype(float).tolist()))
    price_lookup = dict(enumerate(profile["actual_price_eur_per_mwh"].astype(float).tolist()))
    horizon = range(len(timestamps))
    ramp_limit = config.hydrogen_system.electrolyser_ramp_mw_per_h * delta_t_hours

    model = pulp.LpProblem("hydrogen_actual_redispatch", pulp.LpMaximize)
    p_el = {t: pulp.LpVariable(f"P_el_{t}", lowBound=0.0) for t in horizon}
    u_el = {t: pulp.LpVariable(f"u_el_{t}", lowBound=0, upBound=1, cat=pulp.LpBinary) for t in horizon}
    h_prod = {t: pulp.LpVariable(f"H_prod_{t}", lowBound=0.0) for t in horizon}
    p_comp = {t: pulp.LpVariable(f"P_comp_{t}", lowBound=0.0) for t in horizon}
    h_comp = {t: pulp.LpVariable(f"H_comp_{t}", lowBound=0.0) for t in horizon}
    h_buf = {t: pulp.LpVariable(f"H_buf_{t}", lowBound=0.0) for t in horizon}
    unused = {t: pulp.LpVariable(f"unused_{t}", lowBound=0.0) for t in horizon}
    emergency_import_enabled = emergency_import_price_eur_per_mwh is not None and float(emergency_import_price_eur_per_mwh) > 0.0
    emergency_import = {t: pulp.LpVariable(f"emergency_import_{t}", lowBound=0.0) for t in horizon} if emergency_import_enabled else None
    shortfall = pulp.LpVariable("shortfall", lowBound=0.0)

    for t in horizon:
        model += p_el[t] >= config.hydrogen_system.electrolyser_min_mw * u_el[t], f"el_min_power_{t}"
        model += p_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * u_el[t], f"el_max_power_{t}"
        model += h_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el[t] * delta_t_hours, f"h_prod_balance_{t}"
        model += p_comp[t] <= config.hydrogen_system.compressor_max_mw, f"comp_max_power_{t}"
        model += p_comp[t] * delta_t_hours == config.hydrogen_system.compressor_specific_mwh_per_kg * h_comp[t], f"comp_specific_energy_{t}"
        if emergency_import_enabled:
            model += delta_t_hours * (p_el[t] + p_comp[t]) + unused[t] == cleared_lookup[t] + emergency_import[t], f"cleared_energy_balance_{t}"
        else:
            model += delta_t_hours * (p_el[t] + p_comp[t]) + unused[t] == cleared_lookup[t], f"cleared_energy_balance_{t}"
        if t == 0:
            model += h_buf[t] == inventory_start_kg + h_prod[t] - h_comp[t], f"buffer_state_{t}"
            if previous_electrolyser_power_mw is not None:
                previous_power = float(previous_electrolyser_power_mw)
                model += p_el[t] - previous_power <= ramp_limit, f"boundary_ramp_up_{t}"
                model += previous_power - p_el[t] <= ramp_limit, f"boundary_ramp_down_{t}"
        else:
            model += h_buf[t] == h_buf[t - 1] + h_prod[t] - h_comp[t], f"buffer_state_{t}"
            model += p_el[t] - p_el[t - 1] <= ramp_limit, f"ramp_up_{t}"
            model += p_el[t - 1] - p_el[t] <= ramp_limit, f"ramp_down_{t}"
        model += h_buf[t] >= reserve_kg, f"reserve_min_{t}"
        model += h_buf[t] <= config.hydrogen_system.storage_capacity_kg, f"buffer_max_{t}"

    if weekly_quota_plan is not None:
        for quota_index, quota_constraint in enumerate(weekly_quota_plan.constraints):
            model += (
                pulp.lpSum(h_comp[t] for t in quota_constraint.horizon_time_indices)
                >= float(quota_constraint.minimum_horizon_compression_kg)
            ), f"weekly_quota_{quota_index}"

    target_hydrogen_max_kg_value = (
        None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    )
    sum_h_comp = pulp.lpSum(h_comp[t] for t in horizon)
    total_unused = pulp.lpSum(unused[t] for t in horizon)
    if str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
        model += sum_h_comp >= target_hydrogen_kg, "delivery_target_lb"
        if target_hydrogen_max_kg_value is not None:
            model += sum_h_comp <= target_hydrogen_max_kg_value, "delivery_target_ub"
        model += shortfall == 0.0, "hard_target_shortfall_zero"
    else:
        model += sum_h_comp + shortfall >= target_hydrogen_kg, "delivery_target_lb"
    objective = (
        config.economics.h2_sale_price_eur_per_kg * sum_h_comp
        - config.economics.unused_energy_penalty_eur_per_mwh * total_unused
        - (
            float(emergency_import_price_eur_per_mwh) * pulp.lpSum(emergency_import[t] for t in horizon)
            if emergency_import_enabled
            else 0.0
        )
        - shortfall_penalty_eur_per_kg * shortfall
        + config.terminal_inventory_value_per_kg * (h_buf[len(timestamps) - 1] - terminal_reference_start_kg)
    )
    model += objective

    model_build_time = perf_counter() - build_started
    solver_backend, solver_name = _resolve_pulp_solver(config.solver, log_path=solver_log_path)
    started = perf_counter()
    model.solve(solver_backend)
    solver_runtime = perf_counter() - started

    postprocess_started = perf_counter()
    dispatch = pd.DataFrame(
        {
            "delivery_start_utc": list(timestamps),
            "P_el_mw": [float(p_el[t].value() or 0.0) for t in horizon],
            "u_el": [float(u_el[t].value() or 0.0) for t in horizon],
            "H_prod_kg": [float(h_prod[t].value() or 0.0) for t in horizon],
            "P_comp_mw": [float(p_comp[t].value() or 0.0) for t in horizon],
            "H_comp_kg": [float(h_comp[t].value() or 0.0) for t in horizon],
            "H_buf_kg": [float(h_buf[t].value() or 0.0) for t in horizon],
            "unused_cleared_energy_mwh": [float(unused[t].value() or 0.0) for t in horizon],
            "emergency_import_mwh": [float(emergency_import[t].value() or 0.0) for t in horizon] if emergency_import_enabled else [0.0 for _ in horizon],
            "shortfall_kg": float(shortfall.value() or 0.0),
            "cleared_energy_mwh": [float(cleared_lookup[t]) for t in horizon],
            "actual_price_eur_per_mwh": [float(price_lookup[t]) for t in horizon],
            "timestep_hours": float(delta_t_hours),
        }
    )
    dispatch["used_energy_mwh"] = delta_t_hours * (dispatch["P_el_mw"] + dispatch["P_comp_mw"])
    dispatch["settlement_cost_eur"] = dispatch["actual_price_eur_per_mwh"] * dispatch["cleared_energy_mwh"]
    dispatch["unused_energy_penalty_eur"] = dispatch["unused_cleared_energy_mwh"] * config.economics.unused_energy_penalty_eur_per_mwh
    dispatch["hydrogen_revenue_eur"] = dispatch["H_comp_kg"] * config.economics.h2_sale_price_eur_per_kg
    dispatch["terminal_inventory_value_eur_contrib"] = 0.0
    dispatch.loc[dispatch.index[-1], "terminal_inventory_value_eur_contrib"] = (
        config.terminal_inventory_value_per_kg * (dispatch["H_buf_kg"].iloc[-1] - terminal_reference_start_kg)
    )

    model_stats = _pulp_model_stats(
        model,
        scenario_count=1,
        horizon_steps=len(timestamps),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
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
    return dispatch, solver_result, model_stats


def solve_actual_redispatch_from_cleared_energy(
    cleared_profile: pd.DataFrame,
    *,
    config: HydrogenConfig,
    inventory_start_kg: float | None = None,
    reserve_kg: float | None = None,
    target_hydrogen_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    terminal_reference_start_kg: float | None = None,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | Path | None = None,
    emergency_import_price_eur_per_mwh: float | None = None,
    previous_electrolyser_power_mw: float | None = None,
    weekly_quota_plan: WeeklyQuotaDeadlinePlan | None = None,
    performance_mode: str = "optimized_equivalent",
) -> RedispatchSolveResult:
    profile = validate_cleared_profile_schema(cleared_profile)
    performance_mode_value = validate_performance_mode(performance_mode)
    granularity = (
        str(profile["granularity"].dropna().iloc[0])
        if "granularity" in profile.columns and not profile["granularity"].dropna().empty
        else ("quarter_hour" if abs(float(profile["timestep_hours"].iloc[0]) - 0.25) <= 1e-12 else "hourly")
    )
    signature = StructuralSignature(
        model_type="hydrogen_actual_redispatch",
        granularity=granularity,
        timestep_count=len(profile),
        scenario_count=1,
        bid_grid=(),
        dst_shape=dst_shape_for_steps(granularity, len(profile), 1),
        physical_config_hash=stable_hash({"hydrogen_system": asdict(config.hydrogen_system)}),
        quota_structure=(
            "none"
            if weekly_quota_plan is None
            else stable_hash([list(item.horizon_time_indices) for item in weekly_quota_plan.constraints])
        ),
    )
    if performance_mode_value == "optimized_equivalent":
        cache_status, _ = _REDISPATCH_TEMPLATE_CACHE.register(
            signature, {"timestep_count": len(profile), "scenario_count": 1}
        )
    else:
        cache_status = "disabled_legacy_rebuild"
    inventory_start = float(config.hydrogen_system.storage_initial_kg if inventory_start_kg is None else inventory_start_kg)
    reserve_floor = float(config.hydrogen_system.reserve_kg if reserve_kg is None else reserve_kg)
    target_kg = float(config.economics.daily_target_kg if target_hydrogen_kg is None else target_hydrogen_kg)
    terminal_reference = float(inventory_start if terminal_reference_start_kg is None else terminal_reference_start_kg)
    effective_shortfall_penalty = float(
        config.economics.shortfall_penalty_eur_per_kg
        if shortfall_penalty_eur_per_kg is None
        else shortfall_penalty_eur_per_kg
    )

    _ensure_solver_package(config.solver)
    _apply_gurobi_license_env(config.solver)
    preference = str(config.solver.package_preference).strip().lower()
    log_path = str(solver_log_path) if solver_log_path is not None else None

    if preference in {"pyomo", "auto"} and pyo is not None:
        try:
            dispatch, solver, model_stats = _solve_with_pyomo(
                profile=profile,
                config=config,
                inventory_start_kg=inventory_start,
                reserve_kg=reserve_floor,
                target_hydrogen_kg=target_kg,
                target_hydrogen_max_kg=target_hydrogen_max_kg,
                terminal_reference_start_kg=terminal_reference,
                production_target_mode=production_target_mode,
                shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
                solver_log_path=log_path,
                emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
                previous_electrolyser_power_mw=previous_electrolyser_power_mw,
                weekly_quota_plan=weekly_quota_plan,
            )
        except RuntimeError:
            if preference == "pyomo":
                raise
            dispatch, solver, model_stats = _solve_with_pulp(
                profile=profile,
                config=config,
                inventory_start_kg=inventory_start,
                reserve_kg=reserve_floor,
                target_hydrogen_kg=target_kg,
                target_hydrogen_max_kg=target_hydrogen_max_kg,
                terminal_reference_start_kg=terminal_reference,
                production_target_mode=production_target_mode,
                shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
                solver_log_path=log_path,
                emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
                previous_electrolyser_power_mw=previous_electrolyser_power_mw,
                weekly_quota_plan=weekly_quota_plan,
            )
    else:
        dispatch, solver, model_stats = _solve_with_pulp(
            profile=profile,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=reserve_floor,
            target_hydrogen_kg=target_kg,
            target_hydrogen_max_kg=target_hydrogen_max_kg,
            terminal_reference_start_kg=terminal_reference,
            production_target_mode=production_target_mode,
            shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
            solver_log_path=log_path,
            emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
            previous_electrolyser_power_mw=previous_electrolyser_power_mw,
            weekly_quota_plan=weekly_quota_plan,
        )

    metadata = {}
    for column in _metadata_columns(profile):
        value = profile[column].dropna().iloc[0] if not profile[column].dropna().empty else np.nan
        metadata[column] = value

    dispatch = dispatch.copy()
    for column, value in metadata.items():
        dispatch[column] = value
    summary = _build_summary(
        timeseries=dispatch,
        config=config,
        solver=solver,
        model_stats=model_stats,
        metadata=metadata,
        inventory_start_kg=inventory_start,
        reserve_kg=reserve_floor,
        target_hydrogen_kg=target_kg,
        terminal_reference_start_kg=terminal_reference,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
    )
    validation_rows = validate_redispatch_solution(
        dispatch,
        summary_row=summary.iloc[0],
        config=config,
        reserve_kg=reserve_floor,
        inventory_start_kg=inventory_start,
    )
    validation_checks = pd.DataFrame(validation_rows)
    return RedispatchSolveResult(
        timeseries=dispatch.reset_index(drop=True),
        summary=summary.reset_index(drop=True),
        validation_checks=validation_checks.reset_index(drop=True),
        solver=solver,
        model_stats=model_stats,
        performance={
            "schema_version": "optimisation_performance_v1",
            "performance_mode": performance_mode_value,
            "structural_signature": signature.digest,
            "model_reuse_status": (
                "disabled_legacy_rebuild" if cache_status == "disabled_legacy_rebuild"
                else "static_structure_cache_hit_pyomo_rebuilt" if cache_status == "hit"
                else "static_structure_registered_pyomo_rebuilt"
            ),
            "cache_status": cache_status,
            "warm_start_status": "not_applicable_continuous_redispatch",
            "warm_start_values_applied": 0,
            "pyomo_model_rebuilt": True,
        },
    )
