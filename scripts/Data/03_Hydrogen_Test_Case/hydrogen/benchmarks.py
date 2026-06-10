from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from .optimisation_model import (
    DispatchSolveResult,
    ModelStats,
    SolverResult,
    _apply_gurobi_license_env,
    _ensure_solver_package,
    _pulp_model_stats,
    _pyomo_model_stats,
    _resolve_pulp_solver,
    _resolve_pyomo_solver,
    pulp,
    pyo,
    solve_deterministic_dispatch,
    solve_stochastic_dispatch,
)
from .plant_parameters import HydrogenConfig
from .production_target import (
    build_rolling_production_target_plan,
    is_rolling_deadline_mode,
    should_apply_terminal_inventory_value,
)


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    dispatch: pd.DataFrame
    scenario_costs: pd.DataFrame
    solver_status: str
    solver_runtime_seconds: float
    solver_name: str
    solver_package: str
    objective_value: float | None
    optimisation_cvar: float | None
    model_stats: ModelStats | None
    market_model_type: str
    warnings: tuple[str, ...]


def _extract_actual_series(day_frame: pd.DataFrame) -> tuple[pd.DatetimeIndex, pd.Series]:
    actual = (
        day_frame[["delivery_start_utc", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
    )
    return pd.DatetimeIndex(pd.to_datetime(actual["delivery_start_utc"], utc=True)), actual["actual_price_eur_per_mwh"].astype(float).reset_index(drop=True)


def _extract_point_forecast_series(day_frame: pd.DataFrame) -> tuple[pd.DatetimeIndex, pd.Series]:
    forecast = (
        day_frame[["delivery_start_utc", "point_forecast_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
    )
    return pd.DatetimeIndex(pd.to_datetime(forecast["delivery_start_utc"], utc=True)), forecast["point_forecast_eur_per_mwh"].astype(float).reset_index(drop=True)


def _price_insensitive_heuristic(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    target_hydrogen_min_kg: float | None = None,
) -> pd.DataFrame:
    if is_rolling_deadline_mode(config.production_targets):
        raise ValueError(
            "price_insensitive_heuristic does not support production_targets.mode=rolling_deadline_envelope. "
            "Use the optimisation-based benchmark path instead."
        )
    timestamps, _ = _extract_actual_series(day_frame)
    horizon = len(timestamps)
    delta_t = config.delta_t_hours
    target_kg = float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg)
    h2_rate = target_kg / horizon
    p_el_target = h2_rate / (config.hydrogen_system.h2_efficiency_kg_per_mwh * delta_t)
    p_el_target = float(np.clip(p_el_target, config.hydrogen_system.electrolyser_min_mw, config.hydrogen_system.electrolyser_nominal_mw))
    p_comp_target = float(min(config.hydrogen_system.compressor_max_mw, config.hydrogen_system.compressor_specific_mwh_per_kg * h2_rate / delta_t))
    h_comp_target = p_comp_target * delta_t / config.hydrogen_system.compressor_specific_mwh_per_kg
    h_prod_target = config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el_target * delta_t

    rows: list[dict[str, Any]] = []
    buf = float(inventory_start_kg)
    for index, timestamp in enumerate(timestamps):
        if index == 0:
            p_el = p_el_target
        else:
            prev = rows[-1]["P_el_mw"]
            ramp = config.hydrogen_system.electrolyser_ramp_mw_per_h
            p_el = float(np.clip(p_el_target, prev - ramp, prev + ramp))
        h_prod = config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el * delta_t
        max_sellable = max(buf + h_prod - reserve_kg, 0.0)
        h_comp = float(min(h_comp_target, max_sellable))
        p_comp = h_comp * config.hydrogen_system.compressor_specific_mwh_per_kg / delta_t
        buf = buf + h_prod - h_comp
        rows.append(
            {
                "delivery_start_utc": timestamp,
                "P_el_mw": p_el,
                "u_el": 1.0 if p_el >= config.hydrogen_system.electrolyser_min_mw else 0.0,
                "H_prod_kg": h_prod,
                "P_comp_mw": p_comp,
                "H_comp_kg": h_comp,
                "H_buf_kg": buf,
            }
        )
    dispatch = pd.DataFrame(rows)
    dispatch["shortfall_kg"] = max(target_kg - dispatch["H_comp_kg"].sum(), 0.0)
    return dispatch


def _solve_price_insensitive_optimised_plan(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    production_target_mode: str,
    target_hydrogen_min_kg: float | None,
    target_hydrogen_max_kg: float | None,
    solver_log_path: str | None,
) -> tuple[pd.DataFrame, SolverResult, ModelStats]:
    if is_rolling_deadline_mode(config.production_targets):
        raise ValueError(
            "price_insensitive optimisation benchmark does not yet support rolling_deadline_envelope economics. "
            "Rolling mode no longer values all H_comp as unlimited sellable output."
        )
    timestamps, _ = _extract_actual_series(day_frame)
    delta_t = float(config.delta_t_hours)
    horizon = list(range(len(timestamps)))
    if not horizon:
        raise ValueError("Price-insensitive optimisation received an empty day frame.")

    _ensure_solver_package(config.solver)
    _apply_gurobi_license_env(config.solver)
    preference = str(config.solver.package_preference).strip().lower()

    target_hydrogen_min_kg_value = float(
        config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg
    )
    target_hydrogen_max_kg_value = (
        None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    )
    rolling_target_plan = (
        build_rolling_production_target_plan(
            timestamps_utc=timestamps,
            hydrogen=config.hydrogen_system,
            production_targets=config.production_targets,
            delta_t_hours=delta_t,
        )
        if is_rolling_deadline_mode(config.production_targets)
        else None
    )

    def _build_pyomo_model():
        m = pyo.ConcreteModel(name="hydrogen_price_insensitive_plan")
        m.T = pyo.RangeSet(0, len(timestamps) - 1)
        m.P_el = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.u_el = pyo.Var(m.T, domain=pyo.Binary)
        m.H_prod = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.P_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.H_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.H_buf = pyo.Var(m.T, domain=pyo.NonNegativeReals)
        m.shortfall = pyo.Var(domain=pyo.NonNegativeReals)
        m.constraints = pyo.ConstraintList()
        for t in horizon:
            m.constraints.add(m.P_el[t] >= config.hydrogen_system.electrolyser_min_mw * m.u_el[t])
            m.constraints.add(m.P_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * m.u_el[t])
            m.constraints.add(m.H_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * m.P_el[t] * delta_t)
            m.constraints.add(m.P_comp[t] <= config.hydrogen_system.compressor_max_mw)
            m.constraints.add(
                m.P_comp[t] * delta_t
                == config.hydrogen_system.compressor_specific_mwh_per_kg * m.H_comp[t]
            )
            if t == 0:
                m.constraints.add(m.H_buf[t] == inventory_start_kg + m.H_prod[t] - m.H_comp[t])
            else:
                m.constraints.add(m.H_buf[t] == m.H_buf[t - 1] + m.H_prod[t] - m.H_comp[t])
                m.constraints.add(m.P_el[t] - m.P_el[t - 1] <= config.hydrogen_system.electrolyser_ramp_mw_per_h)
                m.constraints.add(m.P_el[t - 1] - m.P_el[t] <= config.hydrogen_system.electrolyser_ramp_mw_per_h)
            m.constraints.add(m.H_buf[t] >= reserve_kg)
            m.constraints.add(m.H_buf[t] <= config.hydrogen_system.storage_capacity_kg)
        if rolling_target_plan is not None:
            m.constraints.add(m.shortfall == 0.0)
            for bound in rolling_target_plan.rolling_constraints:
                m.constraints.add(
                    float(rolling_target_plan.initial_inventory_kg)
                    + sum(m.H_comp[t] for t in range(bound.cutoff_time_index + 1))
                    >= float(bound.cumulative_required_kg)
                )
            for guard in rolling_target_plan.terminal_guards:
                if guard.active:
                    m.constraints.add(sum(m.H_comp[t] for t in horizon) >= float(guard.minimum_h_comp_required_by_horizon_end_kg))
            if rolling_target_plan.max_inventory_kg is not None:
                for t in horizon:
                    m.constraints.add(
                        float(rolling_target_plan.initial_inventory_kg)
                        + sum(m.H_comp[k] for k in range(t + 1))
                        - float(rolling_target_plan.cumulative_required_due_by_time_index_kg[t])
                        <= float(rolling_target_plan.max_inventory_kg)
                    )
        elif str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
            m.constraints.add(sum(m.H_comp[t] for t in horizon) >= target_hydrogen_min_kg_value)
            if target_hydrogen_max_kg_value is not None:
                m.constraints.add(sum(m.H_comp[t] for t in horizon) <= target_hydrogen_max_kg_value)
            m.constraints.add(m.shortfall == 0.0)
        else:
            m.constraints.add(sum(m.H_comp[t] for t in horizon) + m.shortfall >= target_hydrogen_min_kg_value)
        return m

    def _build_dispatch_from_pyomo(model):
        dispatch = pd.DataFrame(
            {
                "delivery_start_utc": list(timestamps),
                "P_el_mw": [float(pyo.value(model.P_el[t]) or 0.0) for t in horizon],
                "u_el": [float(pyo.value(model.u_el[t]) or 0.0) for t in horizon],
                "H_prod_kg": [float(pyo.value(model.H_prod[t]) or 0.0) for t in horizon],
                "P_comp_mw": [float(pyo.value(model.P_comp[t]) or 0.0) for t in horizon],
                "H_comp_kg": [float(pyo.value(model.H_comp[t]) or 0.0) for t in horizon],
                "H_buf_kg": [float(pyo.value(model.H_buf[t]) or 0.0) for t in horizon],
            }
        )
        dispatch["shortfall_kg"] = float(pyo.value(model.shortfall) or 0.0)
        return dispatch

    def _solve_pyomo():
        if pyo is None:
            raise RuntimeError("Pyomo backend requested but Pyomo is not installed.")
        model = _build_pyomo_model()
        solver, solver_name = _resolve_pyomo_solver(config.solver, solver_log_path)
        model.objective = pyo.Objective(expr=model.shortfall, sense=pyo.minimize)
        solver.solve(model, tee=False)
        best_shortfall = float(pyo.value(model.shortfall) or 0.0)
        model.del_component(model.objective)
        model.shortfall_fix = pyo.Constraint(expr=model.shortfall <= best_shortfall + 1e-6)
        model.objective = pyo.Objective(expr=sum(model.H_comp[t] for t in horizon), sense=pyo.maximize)
        started = __import__("time").perf_counter()
        try:
            if solver_log_path is not None:
                results = solver.solve(model, tee=False, logfile=solver_log_path)
            else:
                results = solver.solve(model, tee=False)
        except TypeError:
            results = solver.solve(model, tee=False)
        runtime = __import__("time").perf_counter() - started
        solver_status = getattr(getattr(results, "solver", None), "status", None)
        termination = getattr(getattr(results, "solver", None), "termination_condition", None)
        termination_text = str(termination).strip().lower() if termination is not None else ""
        status_text = "Optimal" if termination_text == "optimal" else f"{solver_status}:{termination}"
        return (
            _build_dispatch_from_pyomo(model),
            SolverResult(
                status=status_text,
                objective_value=float(pyo.value(model.objective)) if pyo.value(model.objective) is not None else None,
                runtime_seconds=float(runtime),
                mip_gap=float(config.solver.mip_gap),
                solver_package="pyomo",
                solver_name=str(solver_name),
            ),
            _pyomo_model_stats(model, scenario_count=1, horizon_steps=len(horizon), delta_t_hours=delta_t),
        )

    def _solve_pulp():
        if pulp is None:
            raise RuntimeError("PuLP backend requested but PuLP is not installed.")
        model = pulp.LpProblem("hydrogen_price_insensitive_plan", pulp.LpMinimize)
        p_el = {t: pulp.LpVariable(f"P_el_{t}", lowBound=0.0) for t in horizon}
        u_el = {t: pulp.LpVariable(f"u_el_{t}", lowBound=0, upBound=1, cat=pulp.LpBinary) for t in horizon}
        h_prod = {t: pulp.LpVariable(f"H_prod_{t}", lowBound=0.0) for t in horizon}
        p_comp = {t: pulp.LpVariable(f"P_comp_{t}", lowBound=0.0) for t in horizon}
        h_comp = {t: pulp.LpVariable(f"H_comp_{t}", lowBound=0.0) for t in horizon}
        h_buf = {t: pulp.LpVariable(f"H_buf_{t}", lowBound=0.0) for t in horizon}
        shortfall = pulp.LpVariable("shortfall", lowBound=0.0)
        for t in horizon:
            model += p_el[t] >= config.hydrogen_system.electrolyser_min_mw * u_el[t], f"el_min_power_{t}"
            model += p_el[t] <= config.hydrogen_system.electrolyser_nominal_mw * u_el[t], f"el_max_power_{t}"
            model += h_prod[t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el[t] * delta_t, f"h_prod_balance_{t}"
            model += p_comp[t] <= config.hydrogen_system.compressor_max_mw, f"comp_max_power_{t}"
            model += p_comp[t] * delta_t == config.hydrogen_system.compressor_specific_mwh_per_kg * h_comp[t], f"comp_specific_energy_{t}"
            if t == 0:
                model += h_buf[t] == inventory_start_kg + h_prod[t] - h_comp[t], f"buffer_state_{t}"
            else:
                model += h_buf[t] == h_buf[t - 1] + h_prod[t] - h_comp[t], f"buffer_state_{t}"
                model += p_el[t] - p_el[t - 1] <= config.hydrogen_system.electrolyser_ramp_mw_per_h, f"ramp_up_{t}"
                model += p_el[t - 1] - p_el[t] <= config.hydrogen_system.electrolyser_ramp_mw_per_h, f"ramp_down_{t}"
            model += h_buf[t] >= reserve_kg, f"reserve_min_{t}"
            model += h_buf[t] <= config.hydrogen_system.storage_capacity_kg, f"buffer_max_{t}"
        if rolling_target_plan is not None:
            model += shortfall == 0.0, "rolling_target_shortfall_zero"
            for idx, bound in enumerate(rolling_target_plan.rolling_constraints):
                model += (
                    float(rolling_target_plan.initial_inventory_kg)
                    + pulp.lpSum(h_comp[t] for t in range(bound.cutoff_time_index + 1))
                    >= float(bound.cumulative_required_kg)
                ), f"rolling_due_lb_{idx}"
            for idx, guard in enumerate(rolling_target_plan.terminal_guards):
                if guard.active:
                    model += pulp.lpSum(h_comp[t] for t in horizon) >= float(guard.minimum_h_comp_required_by_horizon_end_kg), f"rolling_terminal_guard_{idx}"
            if rolling_target_plan.max_inventory_kg is not None:
                for t in horizon:
                    model += (
                        float(rolling_target_plan.initial_inventory_kg)
                        + pulp.lpSum(h_comp[k] for k in range(t + 1))
                        - float(rolling_target_plan.cumulative_required_due_by_time_index_kg[t])
                        <= float(rolling_target_plan.max_inventory_kg)
                    ), f"rolling_inventory_cap_{t}"
        elif str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
            model += pulp.lpSum(h_comp[t] for t in horizon) >= target_hydrogen_min_kg_value, "delivery_target_lb"
            if target_hydrogen_max_kg_value is not None:
                model += pulp.lpSum(h_comp[t] for t in horizon) <= target_hydrogen_max_kg_value, "delivery_target_ub"
            model += shortfall == 0.0, "hard_target_shortfall_zero"
        else:
            model += pulp.lpSum(h_comp[t] for t in horizon) + shortfall >= target_hydrogen_min_kg_value, "delivery_target_lb"
        model += shortfall
        solver_backend, solver_name = _resolve_pulp_solver(config.solver, log_path=solver_log_path)
        model.solve(solver_backend)
        best_shortfall = float(shortfall.value() or 0.0)
        model.constraints["shortfall_fix"] = shortfall <= best_shortfall + 1e-6
        model.sense = pulp.LpMaximize
        model.setObjective(pulp.lpSum(h_comp[t] for t in horizon))
        started = __import__("time").perf_counter()
        model.solve(solver_backend)
        runtime = __import__("time").perf_counter() - started
        dispatch = pd.DataFrame(
            {
                "delivery_start_utc": list(timestamps),
                "P_el_mw": [float(p_el[t].value() or 0.0) for t in horizon],
                "u_el": [float(u_el[t].value() or 0.0) for t in horizon],
                "H_prod_kg": [float(h_prod[t].value() or 0.0) for t in horizon],
                "P_comp_mw": [float(p_comp[t].value() or 0.0) for t in horizon],
                "H_comp_kg": [float(h_comp[t].value() or 0.0) for t in horizon],
                "H_buf_kg": [float(h_buf[t].value() or 0.0) for t in horizon],
            }
        )
        dispatch["shortfall_kg"] = float(shortfall.value() or 0.0)
        return (
            dispatch,
            SolverResult(
                status=str(pulp.LpStatus.get(model.status, str(model.status))),
                objective_value=float(model.objective.value()) if model.objective.value() is not None else None,
                runtime_seconds=float(runtime),
                mip_gap=float(config.solver.mip_gap),
                solver_package="pulp",
                solver_name=str(solver_name),
            ),
            _pulp_model_stats(model, scenario_count=1, horizon_steps=len(horizon), delta_t_hours=delta_t),
        )

    if preference in {"pyomo", "auto"} and pyo is not None:
        try:
            return _solve_pyomo()
        except RuntimeError:
            if preference == "pyomo":
                raise
    return _solve_pulp()


def _scenario_cost_table_for_fixed_dispatch(
    *,
    day_frame: pd.DataFrame,
    dispatch: pd.DataFrame,
    config: HydrogenConfig,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    shortfall_penalty_eur_per_kg: float | None = None,
) -> pd.DataFrame:
    price_panel = day_frame[["scenario_id", "scenario_probability", "delivery_start_utc", "scenario_price_eur_per_mwh"]].copy()
    price_panel["delivery_start_utc"] = pd.to_datetime(price_panel["delivery_start_utc"], utc=True)
    probabilities = (
        price_panel[["scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["scenario_id"])
        .set_index("scenario_id")["scenario_probability"]
        .astype(float)
        .to_dict()
    )

    merged = price_panel.merge(dispatch[["delivery_start_utc", "P_el_mw", "P_comp_mw"]], on="delivery_start_utc", how="left")
    merged["energy_cost_eur"] = merged["scenario_price_eur_per_mwh"].astype(float) * (
        merged["P_el_mw"].astype(float) + merged["P_comp_mw"].astype(float)
    ) * config.delta_t_hours
    electricity = merged.groupby("scenario_id", as_index=False)["energy_cost_eur"].sum()
    effective_shortfall_penalty = float(
        config.economics.shortfall_penalty_eur_per_kg
        if shortfall_penalty_eur_per_kg is None
        else shortfall_penalty_eur_per_kg
    )
    effective_hydrogen_revenue_per_kg = (
        float(config.economics.h2_sale_price_eur_per_kg)
        if not is_rolling_deadline_mode(config.production_targets)
        else 0.0
    )
    shortfall_penalty = float(effective_shortfall_penalty * dispatch["shortfall_kg"].iloc[0])
    revenue = float(effective_hydrogen_revenue_per_kg * dispatch["H_comp_kg"].sum())
    terminal_value = (
        float(config.terminal_inventory_value_per_kg * (dispatch["H_buf_kg"].iloc[-1] - terminal_reference_start_kg))
        if apply_terminal_value
        else 0.0
    )

    electricity["scenario_probability"] = electricity["scenario_id"].map(probabilities).astype(float)
    electricity["hydrogen_revenue_eur"] = revenue
    electricity["shortfall_penalty_eur"] = shortfall_penalty
    electricity["terminal_inventory_value_eur"] = terminal_value
    electricity["net_cost_eur"] = (
        electricity["energy_cost_eur"] + shortfall_penalty - revenue - terminal_value
    )
    electricity = electricity.rename(columns={"energy_cost_eur": "electricity_cost_eur"})
    return electricity


def _heuristic_model_stats(day_frame: pd.DataFrame, config: HydrogenConfig) -> ModelStats:
    timestamps, _ = _extract_actual_series(day_frame)
    return ModelStats(
        variable_count=0,
        binary_variable_count=0,
        constraint_count=0,
        scenario_count=int(day_frame["scenario_id"].astype(str).nunique()),
        horizon_steps=len(timestamps),
        timestep_hours=float(config.delta_t_hours),
    )


def run_price_insensitive(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None = None,
) -> StrategyResult:
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=config.production_targets,
    )
    dispatch, solver_result, model_stats = _solve_price_insensitive_optimised_plan(
        day_frame=day_frame,
        config=config,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        production_target_mode=production_target_mode,
        target_hydrogen_min_kg=target_hydrogen_min_kg,
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        solver_log_path=solver_log_path,
    )
    scenario_costs = _scenario_cost_table_for_fixed_dispatch(
        day_frame=day_frame,
        dispatch=dispatch,
        config=config,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
    )
    return StrategyResult(
        strategy="price_insensitive",
        dispatch=dispatch,
        scenario_costs=scenario_costs,
        solver_status=solver_result.status,
        solver_runtime_seconds=solver_result.runtime_seconds,
        solver_name=solver_result.solver_name,
        solver_package=solver_result.solver_package,
        objective_value=solver_result.objective_value,
        optimisation_cvar=None,
        model_stats=model_stats,
        market_model_type="deterministic_physical_optimisation_ignore_da_prices",
        warnings=(
            "planning_objective=minimise_shortfall_then_maximise_hydrogen_output",
            "ignores_da_prices_in_planning",
        ),
    )


def run_price_insensitive_heuristic(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None = None,
) -> StrategyResult:
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=config.production_targets,
    )
    dispatch = _price_insensitive_heuristic(
        day_frame=day_frame,
        config=config,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        target_hydrogen_min_kg=target_hydrogen_min_kg,
    )
    scenario_costs = _scenario_cost_table_for_fixed_dispatch(
        day_frame=day_frame,
        dispatch=dispatch,
        config=config,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
    )
    return StrategyResult(
        strategy="price_insensitive_heuristic",
        dispatch=dispatch,
        scenario_costs=scenario_costs,
        solver_status="heuristic",
        solver_runtime_seconds=0.0,
        solver_name="heuristic",
        solver_package="native",
        objective_value=float(np.sum(scenario_costs["scenario_probability"] * scenario_costs["net_cost_eur"])),
        optimisation_cvar=None,
        model_stats=_heuristic_model_stats(day_frame, config),
        market_model_type="heuristic_physical_plan_ignore_da_prices",
        warnings=("legacy_price_insensitive_heuristic",),
    )


def _run_stochastic_with_gamma(
    *,
    strategy: str,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    gamma: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str,
    target_hydrogen_min_kg: float | None,
    target_hydrogen_max_kg: float | None,
    shortfall_penalty_eur_per_kg: float | None,
    solver_log_path: str | None,
) -> StrategyResult:
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=config.production_targets,
    )
    solve = solve_stochastic_dispatch(
        day_scenarios=day_frame,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        daily_target_kg=float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg),
        gamma=float(gamma),
        alpha=float(config.risk.alpha),
        production_target_mode=production_target_mode,
        production_targets=config.production_targets,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=float(config.terminal_inventory_value_per_kg),
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        solver_log_path=solver_log_path,
    )
    return StrategyResult(
        strategy=strategy,
        dispatch=solve.dispatch,
        scenario_costs=solve.scenario_costs,
        solver_status=solve.solver.status,
        solver_runtime_seconds=solve.solver.runtime_seconds,
        solver_name=solve.solver.solver_name,
        solver_package=solve.solver.solver_package,
        objective_value=solve.solver.objective_value,
        optimisation_cvar=solve.optimisation_cvar,
        model_stats=solve.model_stats,
        market_model_type="schedule_and_settle_dispatch",
        warnings=(),
    )


def run_stochastic_risk_neutral(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None,
) -> StrategyResult:
    return _run_stochastic_with_gamma(
        strategy="stochastic_risk_neutral",
        day_frame=day_frame,
        config=config,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        gamma=0.0,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        production_target_mode=production_target_mode,
        target_hydrogen_min_kg=target_hydrogen_min_kg,
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=solver_log_path,
    )


def run_stochastic_cvar(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    gamma: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None,
) -> StrategyResult:
    return _run_stochastic_with_gamma(
        strategy="stochastic_cvar",
        day_frame=day_frame,
        config=config,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        gamma=gamma,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        production_target_mode=production_target_mode,
        target_hydrogen_min_kg=target_hydrogen_min_kg,
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=solver_log_path,
    )


def run_perfect_foresight(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None,
) -> StrategyResult:
    timestamps, actual_prices = _extract_actual_series(day_frame)
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=config.production_targets,
    )
    solve = solve_deterministic_dispatch(
        prices_eur_per_mwh=actual_prices,
        timestamps_utc=timestamps,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        daily_target_kg=float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg),
        production_target_mode=production_target_mode,
        production_targets=config.production_targets,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=float(config.terminal_inventory_value_per_kg),
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        solver_log_path=solver_log_path,
    )
    return StrategyResult(
        strategy="perfect_foresight",
        dispatch=solve.dispatch,
        scenario_costs=solve.scenario_costs,
        solver_status=solve.solver.status,
        solver_runtime_seconds=solve.solver.runtime_seconds,
        solver_name=solve.solver.solver_name,
        solver_package=solve.solver.solver_package,
        objective_value=solve.solver.objective_value,
        optimisation_cvar=None,
        model_stats=solve.model_stats,
        market_model_type="schedule_and_settle_dispatch",
        warnings=("oracle_upper_bound",),
    )


def run_deterministic_point_forecast(
    *,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    production_target_mode: str = "current_soft_target",
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    solver_log_path: str | None,
) -> StrategyResult:
    timestamps, point = _extract_point_forecast_series(day_frame)
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=config.production_targets,
    )
    solve = solve_deterministic_dispatch(
        prices_eur_per_mwh=point,
        timestamps_utc=timestamps,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        daily_target_kg=float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg),
        production_target_mode=production_target_mode,
        production_targets=config.production_targets,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=float(config.terminal_inventory_value_per_kg),
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        solver_log_path=solver_log_path,
    )
    return StrategyResult(
        strategy="deterministic_point_forecast",
        dispatch=solve.dispatch,
        scenario_costs=solve.scenario_costs,
        solver_status=solve.solver.status,
        solver_runtime_seconds=solve.solver.runtime_seconds,
        solver_name=solve.solver.solver_name,
        solver_package=solve.solver.solver_package,
        objective_value=solve.solver.objective_value,
        optimisation_cvar=None,
        model_stats=solve.model_stats,
        market_model_type="schedule_and_settle_dispatch",
        warnings=(),
    )


STRATEGY_REGISTRY: dict[str, Callable[..., StrategyResult]] = {
    "price_insensitive": run_price_insensitive,
    "price_insensitive_heuristic": run_price_insensitive_heuristic,
    "stochastic_risk_neutral": run_stochastic_risk_neutral,
    "stochastic_cvar": run_stochastic_cvar,
    "perfect_foresight": run_perfect_foresight,
    "deterministic_point_forecast": run_deterministic_point_forecast,
}
