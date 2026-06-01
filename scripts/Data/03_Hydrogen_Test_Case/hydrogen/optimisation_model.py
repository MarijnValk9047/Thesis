from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .plant_parameters import EconomicSettings, HydrogenSystemSettings, SolverSettings

try:
    import pyomo.environ as pyo
except ImportError:  # pragma: no cover - dependency availability is environment-specific.
    pyo = None

try:
    import pulp
except ImportError:  # pragma: no cover - dependency availability is environment-specific.
    pulp = None


@dataclass(frozen=True)
class SolverResult:
    status: str
    objective_value: float | None
    runtime_seconds: float
    mip_gap: float | None
    solver_package: str
    solver_name: str
    termination_condition: str | None = None
    model_build_time_seconds: float | None = None
    solver_time_seconds: float | None = None
    postprocess_time_seconds: float | None = None
    gurobi_node_count: float | None = None
    gurobi_iteration_count: float | None = None
    gurobi_best_bound: float | None = None
    gurobi_incumbent: float | None = None


@dataclass(frozen=True)
class ModelStats:
    variable_count: int
    binary_variable_count: int
    constraint_count: int
    scenario_count: int
    horizon_steps: int
    timestep_hours: float


@dataclass(frozen=True)
class DispatchSolveResult:
    dispatch: pd.DataFrame
    scenario_costs: pd.DataFrame
    solver: SolverResult
    optimisation_cvar: float | None
    zeta: float | None
    model_stats: ModelStats


def _ensure_solver_package(settings: SolverSettings) -> None:
    preference = str(settings.package_preference).strip().lower()
    if preference == "pyomo":
        if pyo is None:
            raise RuntimeError("Pyomo is not installed in the active environment. Install with: pip install pyomo")
        return
    if preference == "pulp":
        if pulp is None:
            raise RuntimeError("PuLP is not installed in the active environment. Install with: pip install pulp")
        return
    if pyo is None and pulp is None:
        raise RuntimeError(
            "No MILP package is available. Install at least one of: "
            "'pyomo' (preferred) or 'pulp' in the active environment."
        )


def _resolve_pulp_solver(settings: SolverSettings, log_path: str | None = None):
    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")
    solver_name = settings.solver_name.strip().lower()
    if solver_name in {"auto", "cbc", "pulp_cbc", "coin"}:
        kwargs: dict[str, Any] = {
            "msg": True,
            "timeLimit": int(settings.time_limit_seconds),
            "gapRel": float(settings.mip_gap),
        }
        if log_path:
            kwargs["logPath"] = log_path
        return pulp.PULP_CBC_CMD(**kwargs), "cbc"
    if solver_name == "glpk":
        return pulp.GLPK_CMD(msg=True), "glpk"
    raise ValueError(f"Unsupported solver_name: {settings.solver_name}")


def _prepare_price_panel(day_scenarios: pd.DataFrame) -> tuple[pd.DatetimeIndex, list[str], dict[tuple[str, int], float], dict[str, float]]:
    ordered_time = (
        pd.to_datetime(day_scenarios["delivery_start_utc"], utc=True)
        .drop_duplicates()
        .sort_values()
        .to_list()
    )
    timestamps = pd.DatetimeIndex(ordered_time)
    scenario_meta = (
        day_scenarios[["scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["scenario_id"])
        .sort_values("scenario_id")
        .reset_index(drop=True)
    )
    scenario_ids = scenario_meta["scenario_id"].astype(str).tolist()
    probabilities = {row["scenario_id"]: float(row["scenario_probability"]) for row in scenario_meta.to_dict(orient="records")}

    time_to_idx = {timestamp: idx for idx, timestamp in enumerate(timestamps)}
    price_lookup: dict[tuple[str, int], float] = {}
    for row in day_scenarios.to_dict(orient="records"):
        s = str(row["scenario_id"])
        t = time_to_idx[pd.Timestamp(row["delivery_start_utc"])]
        price_lookup[(s, t)] = float(row["scenario_price_eur_per_mwh"])
    return timestamps, scenario_ids, price_lookup, probabilities


def _pyomo_candidate_solver_names(settings: SolverSettings) -> list[str]:
    requested = str(settings.solver_name).strip().lower()
    if requested and requested != "auto":
        aliases = {
            "pyomo_highs": "highs",
            "pyomo_cbc": "cbc",
            "pyomo_glpk": "glpk",
            "pyomo_gurobi": "gurobi",
            "gurobi_direct": "gurobi_direct",
        }
        return [aliases.get(requested, requested)]
    return ["gurobi", "gurobi_direct", "appsi_highs", "highs", "cbc", "glpk"]


def _configure_pyomo_solver(solver: Any, solver_name: str, settings: SolverSettings, log_path: str | None) -> None:
    if solver_name == "appsi_highs" and hasattr(solver, "config"):
        try:
            solver.config.time_limit = float(settings.time_limit_seconds)
        except Exception:
            pass
        try:
            solver.config.mip_gap = float(settings.mip_gap)
        except Exception:
            pass
        if log_path:
            try:
                solver.config.logfile = str(log_path)
            except Exception:
                pass
        return

    try:
        options = solver.options
    except Exception:
        options = None
    if options is not None:
        if solver_name in {"gurobi", "gurobi_direct"}:
            options["TimeLimit"] = float(settings.time_limit_seconds)
            options["MIPGap"] = float(settings.mip_gap)
        if solver_name in {"highs"}:
            options["time_limit"] = float(settings.time_limit_seconds)
            options["mip_rel_gap"] = float(settings.mip_gap)
        elif solver_name in {"cbc"}:
            options["seconds"] = float(settings.time_limit_seconds)
            options["ratio"] = float(settings.mip_gap)
        elif solver_name in {"glpk"}:
            options["tmlim"] = int(settings.time_limit_seconds)
            options["mipgap"] = float(settings.mip_gap)


def _resolve_pyomo_solver(settings: SolverSettings, log_path: str | None = None):
    if pyo is None:
        raise RuntimeError("Pyomo backend requested but Pyomo is not installed.")
    attempts: list[str] = []
    for solver_name in _pyomo_candidate_solver_names(settings):
        try:
            solver = pyo.SolverFactory(solver_name)
            available = bool(solver is not None and solver.available(False))
        except Exception as exc:
            attempts.append(f"{solver_name}=error({type(exc).__name__})")
            continue
        if not available:
            attempts.append(f"{solver_name}=unavailable")
            continue
        _configure_pyomo_solver(solver, solver_name, settings, log_path)
        return solver, solver_name
    raise RuntimeError(
        "Pyomo is installed but no usable solver backend was found. "
        f"Tried: {', '.join(attempts)}. "
        "Install one backend, for example: highspy (for appsi_highs), or a system solver like CBC/GLPK/HiGHS."
    )


def _apply_gurobi_license_env(settings: SolverSettings) -> None:
    if settings.grb_license_file is None:
        return
    license_path = settings.grb_license_file
    if not license_path.exists():
        raise FileNotFoundError(f"Gurobi license file was configured but not found: {license_path}")
    selected_path = license_path
    try:
        license_text = license_path.read_text(encoding="utf-8", errors="ignore")
        is_wls_license = "WLSACCESSID=" in license_text and "LICENSEID=" in license_text
    except OSError:
        is_wls_license = False
    if is_wls_license:
        try:
            import gurobipy

            pip_license_path = Path(gurobipy.__file__).with_name("gurobi.lic")
            if pip_license_path.exists():
                selected_path = pip_license_path
        except Exception:
            selected_path = license_path
    os.environ["GRB_LICENSE_FILE"] = str(selected_path)


def _extract_solution_rows(
    *,
    day_scenarios: pd.DataFrame,
    timestamps: pd.DatetimeIndex,
    scenario_ids: list[str],
    probabilities: dict[str, float],
    dispatch: pd.DataFrame,
    delta_t_hours: float,
    economics: EconomicSettings,
    shortfall_kg: float,
    shortfall_penalty_eur_per_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    net_cost_lookup: dict[str, float | None],
    xi_lookup: dict[str, float | None],
) -> pd.DataFrame:
    scenario_cost_rows: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        power_total = dispatch["P_el_mw"] + dispatch["P_comp_mw"]
        scenario_prices = (
            day_scenarios[day_scenarios["scenario_id"].astype(str) == scenario_id]
            .sort_values("delivery_start_utc")["scenario_price_eur_per_mwh"]
            .astype(float)
            .to_numpy()
        )
        electricity_cost = float(np.sum(scenario_prices * power_total.to_numpy() * delta_t_hours))
        hydrogen_revenue = float(economics.h2_sale_price_eur_per_kg * dispatch["H_comp_kg"].sum())
        shortfall_penalty = float(shortfall_penalty_eur_per_kg * shortfall_kg)
        terminal_value = (
            float(terminal_value_per_kg * (dispatch["H_buf_kg"].iloc[-1] - terminal_reference_start_kg))
            if apply_terminal_value
            else 0.0
        )
        total_net_cost = electricity_cost + shortfall_penalty - hydrogen_revenue - terminal_value
        net_cost_value = net_cost_lookup.get(scenario_id)
        xi_value = xi_lookup.get(scenario_id)
        scenario_cost_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_probability": probabilities[scenario_id],
                "electricity_cost_eur": electricity_cost,
                "hydrogen_revenue_eur": hydrogen_revenue,
                "shortfall_penalty_eur": shortfall_penalty,
                "terminal_inventory_value_eur": terminal_value,
                "net_cost_eur": float(net_cost_value) if net_cost_value is not None else total_net_cost,
                "net_cost_recomputed_eur": total_net_cost,
                "xi_value": float(xi_value) if xi_value is not None else 0.0,
            }
        )
    return pd.DataFrame(scenario_cost_rows)


def _safe_pyomo_value(component: Any) -> float | None:
    direct_value = getattr(component, "value", None)
    if direct_value is not None:
        try:
            return float(direct_value)
        except Exception:
            pass
    try:
        value = pyo.value(component, exception=False)
    except Exception:
        return None
    if value is None:
        return None
    return float(value)


def _effective_shortfall_penalty(
    economics: EconomicSettings,
    *,
    shortfall_penalty_eur_per_kg: float | None,
) -> float:
    return float(
        economics.shortfall_penalty_eur_per_kg
        if shortfall_penalty_eur_per_kg is None
        else shortfall_penalty_eur_per_kg
    )


def _is_hard_target_mode(production_target_mode: str) -> bool:
    return str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}


def _pyomo_solver_diagnostics(results: Any) -> dict[str, float | None]:
    def _to_float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    solver_block = getattr(results, "solver", None)
    node_count = None
    iteration_count = None
    best_bound = None
    incumbent = None
    try:
        statistics = getattr(solver_block, "statistics", None)
        if statistics is not None:
            bnb = getattr(statistics, "branch_and_bound", None)
            if bnb is not None:
                node_count = getattr(bnb, "number_of_created_subproblems", None)
                best_bound = getattr(bnb, "lower_bound", None)
                incumbent = getattr(bnb, "upper_bound", None)
    except Exception:
        pass
    try:
        iteration_count = getattr(solver_block, "iterations", None)
    except Exception:
        iteration_count = None
    return {
        "gurobi_node_count": _to_float_or_none(node_count),
        "gurobi_iteration_count": _to_float_or_none(iteration_count),
        "gurobi_best_bound": _to_float_or_none(best_bound),
        "gurobi_incumbent": _to_float_or_none(incumbent),
    }


def _pyomo_model_stats(model: Any, *, scenario_count: int, horizon_steps: int, delta_t_hours: float) -> ModelStats:
    variables = list(model.component_data_objects(pyo.Var, active=True, descend_into=True))
    constraints = list(model.component_data_objects(pyo.Constraint, active=True, descend_into=True))
    binary_count = sum(1 for variable in variables if variable.is_binary())
    return ModelStats(
        variable_count=len(variables),
        binary_variable_count=binary_count,
        constraint_count=len(constraints),
        scenario_count=int(scenario_count),
        horizon_steps=int(horizon_steps),
        timestep_hours=float(delta_t_hours),
    )


def _pulp_model_stats(model: Any, *, scenario_count: int, horizon_steps: int, delta_t_hours: float) -> ModelStats:
    variables = list(model.variables())
    binary_count = 0
    for variable in variables:
        try:
            is_binary = bool(variable.isBinary())
        except Exception:
            category = str(getattr(variable, "cat", "")).lower()
            is_binary = category == "binary"
        binary_count += int(is_binary)
    return ModelStats(
        variable_count=len(variables),
        binary_variable_count=binary_count,
        constraint_count=len(model.constraints),
        scenario_count=int(scenario_count),
        horizon_steps=int(horizon_steps),
        timestep_hours=float(delta_t_hours),
    )


def _solve_with_pyomo(
    *,
    day_scenarios: pd.DataFrame,
    hydrogen: HydrogenSystemSettings,
    economics: EconomicSettings,
    solver_settings: SolverSettings,
    delta_t_hours: float,
    inventory_start_kg: float,
    reserve_kg: float,
    daily_target_kg: float,
    target_hydrogen_max_kg: float | None,
    gamma: float,
    alpha: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float | None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    solver_log_path: str | None = None,
) -> DispatchSolveResult:
    if pyo is None:
        raise RuntimeError("Pyomo backend requested but Pyomo is not installed.")

    timestamps, scenario_ids, price_lookup, probabilities = _prepare_price_panel(day_scenarios)
    if not scenario_ids:
        raise ValueError("No scenarios are available for stochastic optimisation.")
    t_max = len(timestamps) - 1
    horizon = list(range(len(timestamps)))

    build_started = perf_counter()
    effective_shortfall_penalty = _effective_shortfall_penalty(
        economics,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
    )
    m = pyo.ConcreteModel(name="hydrogen_stochastic_dispatch")
    m.T = pyo.RangeSet(0, t_max)
    m.S = pyo.Set(initialize=scenario_ids, ordered=True)

    m.P_el = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.u_el = pyo.Var(m.T, domain=pyo.Binary)
    m.H_prod = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.P_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.H_comp = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.H_buf = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.shortfall = pyo.Var(domain=pyo.NonNegativeReals)

    m.net_cost = pyo.Var(m.S)
    m.zeta = pyo.Var()
    m.xi = pyo.Var(m.S, domain=pyo.NonNegativeReals)

    m.constraints = pyo.ConstraintList()
    for t in horizon:
        m.constraints.add(m.P_el[t] >= hydrogen.electrolyser_min_mw * m.u_el[t])
        m.constraints.add(m.P_el[t] <= hydrogen.electrolyser_nominal_mw * m.u_el[t])
        m.constraints.add(m.H_prod[t] == hydrogen.h2_efficiency_kg_per_mwh * m.P_el[t] * delta_t_hours)
        m.constraints.add(m.P_comp[t] <= hydrogen.compressor_max_mw)
        m.constraints.add(m.P_comp[t] * delta_t_hours == hydrogen.compressor_specific_mwh_per_kg * m.H_comp[t])
        if t == 0:
            m.constraints.add(m.H_buf[t] == inventory_start_kg + m.H_prod[t] - m.H_comp[t])
        else:
            m.constraints.add(m.H_buf[t] == m.H_buf[t - 1] + m.H_prod[t] - m.H_comp[t])
            m.constraints.add(m.P_el[t] - m.P_el[t - 1] <= hydrogen.electrolyser_ramp_mw_per_h)
            m.constraints.add(m.P_el[t - 1] - m.P_el[t] <= hydrogen.electrolyser_ramp_mw_per_h)
        m.constraints.add(m.H_buf[t] >= reserve_kg)
        m.constraints.add(m.H_buf[t] <= hydrogen.storage_capacity_kg)

    target_hydrogen_min_kg = float(daily_target_kg)
    target_hydrogen_max_kg_value = (
        None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    )
    sum_h_comp = sum(m.H_comp[t] for t in horizon)
    if _is_hard_target_mode(production_target_mode):
        m.constraints.add(sum_h_comp >= target_hydrogen_min_kg)
        if target_hydrogen_max_kg_value is not None:
            m.constraints.add(sum_h_comp <= target_hydrogen_max_kg_value)
        m.constraints.add(m.shortfall == 0.0)
    else:
        m.constraints.add(sum_h_comp + m.shortfall >= target_hydrogen_min_kg)

    terminal_value_expr = terminal_value_per_kg * (m.H_buf[t_max] - terminal_reference_start_kg) if apply_terminal_value else 0.0
    shortfall_penalty_expr = effective_shortfall_penalty * m.shortfall
    revenue_expr = economics.h2_sale_price_eur_per_kg * sum_h_comp

    for s in scenario_ids:
        electricity_cost_expr = sum(price_lookup[(s, t)] * (m.P_el[t] + m.P_comp[t]) * delta_t_hours for t in horizon)
        m.constraints.add(m.net_cost[s] == electricity_cost_expr + shortfall_penalty_expr - revenue_expr - terminal_value_expr)
        m.constraints.add(m.xi[s] >= m.net_cost[s] - m.zeta)

    expected_net_cost = sum(probabilities[s] * m.net_cost[s] for s in scenario_ids)
    cvar_term = m.zeta + (1.0 / (1.0 - alpha)) * sum(probabilities[s] * m.xi[s] for s in scenario_ids)
    m.objective = pyo.Objective(expr=expected_net_cost + gamma * cvar_term, sense=pyo.minimize)

    model_build_time = perf_counter() - build_started
    solver, solver_name = _resolve_pyomo_solver(solver_settings, solver_log_path)
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
        }
    )
    shortfall_value = float(_safe_pyomo_value(m.shortfall) or 0.0)
    dispatch["shortfall_kg"] = shortfall_value

    net_cost_lookup = {s: _safe_pyomo_value(m.net_cost[s]) for s in scenario_ids}
    xi_lookup = {s: _safe_pyomo_value(m.xi[s]) for s in scenario_ids}
    scenario_costs = _extract_solution_rows(
        day_scenarios=day_scenarios,
        timestamps=timestamps,
        scenario_ids=scenario_ids,
        probabilities=probabilities,
        dispatch=dispatch,
        delta_t_hours=delta_t_hours,
        economics=economics,
        shortfall_kg=shortfall_value,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=terminal_value_per_kg,
        net_cost_lookup=net_cost_lookup,
        xi_lookup=xi_lookup,
    )
    zeta_value = float(_safe_pyomo_value(m.zeta) or 0.0)
    cvar_value = float(zeta_value + (1.0 / (1.0 - alpha)) * np.sum(scenario_costs["scenario_probability"] * scenario_costs["xi_value"]))
    objective_value = _safe_pyomo_value(m.objective)
    model_stats = _pyomo_model_stats(
        m,
        scenario_count=len(scenario_ids),
        horizon_steps=len(horizon),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    diagnostics = _pyomo_solver_diagnostics(results)
    solver_result = SolverResult(
        status=status_text,
        objective_value=objective_value,
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(solver_settings.mip_gap),
        solver_package="pyomo",
        solver_name=str(solver_name),
        termination_condition=str(termination) if termination is not None else None,
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
        gurobi_node_count=diagnostics["gurobi_node_count"],
        gurobi_iteration_count=diagnostics["gurobi_iteration_count"],
        gurobi_best_bound=diagnostics["gurobi_best_bound"],
        gurobi_incumbent=diagnostics["gurobi_incumbent"],
    )
    return DispatchSolveResult(
        dispatch=dispatch,
        scenario_costs=scenario_costs,
        solver=solver_result,
        optimisation_cvar=cvar_value,
        zeta=zeta_value,
        model_stats=model_stats,
    )


def _solve_with_pulp(
    *,
    day_scenarios: pd.DataFrame,
    hydrogen: HydrogenSystemSettings,
    economics: EconomicSettings,
    solver_settings: SolverSettings,
    delta_t_hours: float,
    inventory_start_kg: float,
    reserve_kg: float,
    daily_target_kg: float,
    target_hydrogen_max_kg: float | None,
    gamma: float,
    alpha: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float | None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    solver_log_path: str | None = None,
) -> DispatchSolveResult:
    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")
    build_started = perf_counter()
    effective_shortfall_penalty = _effective_shortfall_penalty(
        economics,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
    )
    timestamps, scenario_ids, price_lookup, probabilities = _prepare_price_panel(day_scenarios)
    if not scenario_ids:
        raise ValueError("No scenarios are available for stochastic optimisation.")

    horizon = range(len(timestamps))
    model = pulp.LpProblem("hydrogen_stochastic_dispatch", pulp.LpMinimize)

    p_el = {t: pulp.LpVariable(f"P_el_{t}", lowBound=0.0) for t in horizon}
    u_el = {t: pulp.LpVariable(f"u_el_{t}", lowBound=0, upBound=1, cat=pulp.LpBinary) for t in horizon}
    h_prod = {t: pulp.LpVariable(f"H_prod_{t}", lowBound=0.0) for t in horizon}
    p_comp = {t: pulp.LpVariable(f"P_comp_{t}", lowBound=0.0) for t in horizon}
    h_comp = {t: pulp.LpVariable(f"H_comp_{t}", lowBound=0.0) for t in horizon}
    h_buf = {t: pulp.LpVariable(f"H_buf_{t}", lowBound=0.0) for t in horizon}
    shortfall = pulp.LpVariable("shortfall", lowBound=0.0)

    net_cost = {s: pulp.LpVariable(f"net_cost__{s}") for s in scenario_ids}
    zeta = pulp.LpVariable("zeta")
    xi = {s: pulp.LpVariable(f"xi__{s}", lowBound=0.0) for s in scenario_ids}

    for t in horizon:
        model += p_el[t] >= hydrogen.electrolyser_min_mw * u_el[t], f"el_min_power_{t}"
        model += p_el[t] <= hydrogen.electrolyser_nominal_mw * u_el[t], f"el_max_power_{t}"
        model += h_prod[t] == hydrogen.h2_efficiency_kg_per_mwh * p_el[t] * delta_t_hours, f"h2_prod_balance_{t}"
        model += p_comp[t] <= hydrogen.compressor_max_mw, f"comp_max_power_{t}"
        model += p_comp[t] * delta_t_hours == hydrogen.compressor_specific_mwh_per_kg * h_comp[t], f"comp_specific_energy_{t}"
        if t == 0:
            model += h_buf[t] == inventory_start_kg + h_prod[t] - h_comp[t], f"buffer_state_{t}"
        else:
            model += h_buf[t] == h_buf[t - 1] + h_prod[t] - h_comp[t], f"buffer_state_{t}"
            model += p_el[t] - p_el[t - 1] <= hydrogen.electrolyser_ramp_mw_per_h, f"ramp_up_{t}"
            model += p_el[t - 1] - p_el[t] <= hydrogen.electrolyser_ramp_mw_per_h, f"ramp_down_{t}"
        model += h_buf[t] >= reserve_kg, f"reserve_min_{t}"
        model += h_buf[t] <= hydrogen.storage_capacity_kg, f"buffer_max_{t}"

    target_hydrogen_min_kg = float(daily_target_kg)
    target_hydrogen_max_kg_value = (
        None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    )
    sum_h_comp = pulp.lpSum(h_comp[t] for t in horizon)
    if _is_hard_target_mode(production_target_mode):
        model += sum_h_comp >= target_hydrogen_min_kg, "daily_target_lb"
        if target_hydrogen_max_kg_value is not None:
            model += sum_h_comp <= target_hydrogen_max_kg_value, "daily_target_ub"
        model += shortfall == 0.0, "hard_target_shortfall_zero"
    else:
        model += sum_h_comp + shortfall >= target_hydrogen_min_kg, "daily_target_lb"

    terminal_value_expr = terminal_value_per_kg * (h_buf[len(timestamps) - 1] - terminal_reference_start_kg) if apply_terminal_value else 0.0
    shortfall_penalty_expr = effective_shortfall_penalty * shortfall
    revenue_expr = economics.h2_sale_price_eur_per_kg * sum_h_comp

    for scenario_id in scenario_ids:
        electricity_cost_expr = pulp.lpSum(
            price_lookup[(scenario_id, t)] * (p_el[t] + p_comp[t]) * delta_t_hours for t in horizon
        )
        model += (
            net_cost[scenario_id]
            == electricity_cost_expr + shortfall_penalty_expr - revenue_expr - terminal_value_expr
        ), f"net_cost_balance__{scenario_id}"
        model += xi[scenario_id] >= net_cost[scenario_id] - zeta, f"cvar_slack_lb__{scenario_id}"

    expected_net_cost = pulp.lpSum(probabilities[s] * net_cost[s] for s in scenario_ids)
    cvar_term = zeta + (1.0 / (1.0 - alpha)) * pulp.lpSum(probabilities[s] * xi[s] for s in scenario_ids)
    model += expected_net_cost + gamma * cvar_term

    model_build_time = perf_counter() - build_started
    solver_backend, solver_name = _resolve_pulp_solver(solver_settings, log_path=solver_log_path)
    started = perf_counter()
    model.solve(solver_backend)
    solver_runtime = perf_counter() - started

    status = pulp.LpStatus.get(model.status, str(model.status))
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
        }
    )
    shortfall_value = float(shortfall.value() or 0.0)
    dispatch["shortfall_kg"] = shortfall_value

    net_cost_lookup = {s: float(net_cost[s].value()) if net_cost[s].value() is not None else None for s in scenario_ids}
    xi_lookup = {s: float(xi[s].value()) if xi[s].value() is not None else None for s in scenario_ids}
    scenario_costs = _extract_solution_rows(
        day_scenarios=day_scenarios,
        timestamps=timestamps,
        scenario_ids=scenario_ids,
        probabilities=probabilities,
        dispatch=dispatch,
        delta_t_hours=delta_t_hours,
        economics=economics,
        shortfall_kg=shortfall_value,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=terminal_value_per_kg,
        net_cost_lookup=net_cost_lookup,
        xi_lookup=xi_lookup,
    )

    cvar_value = float((zeta.value() or 0.0) + (1.0 / (1.0 - alpha)) * np.sum(scenario_costs["scenario_probability"] * scenario_costs["xi_value"]))
    model_stats = _pulp_model_stats(
        model,
        scenario_count=len(scenario_ids),
        horizon_steps=len(timestamps),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    solver_result = SolverResult(
        status=str(status),
        objective_value=float(model.objective.value()) if model.objective.value() is not None else None,
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(solver_settings.mip_gap),
        solver_package="pulp",
        solver_name=solver_name,
        termination_condition=str(status),
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
    )
    return DispatchSolveResult(
        dispatch=dispatch,
        scenario_costs=scenario_costs,
        solver=solver_result,
        optimisation_cvar=cvar_value,
        zeta=float(zeta.value() or 0.0),
        model_stats=model_stats,
    )


def solve_stochastic_dispatch(
    *,
    day_scenarios: pd.DataFrame,
    hydrogen: HydrogenSystemSettings,
    economics: EconomicSettings,
    solver_settings: SolverSettings,
    delta_t_hours: float,
    inventory_start_kg: float,
    reserve_kg: float,
    daily_target_kg: float,
    gamma: float,
    alpha: float,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    target_hydrogen_max_kg: float | None = None,
    solver_log_path: str | None = None,
) -> DispatchSolveResult:
    _ensure_solver_package(solver_settings)
    _apply_gurobi_license_env(solver_settings)
    preference = str(solver_settings.package_preference).strip().lower()
    last_error: Exception | None = None
    if preference in {"pyomo", "auto"} and pyo is not None:
        try:
            return _solve_with_pyomo(
                day_scenarios=day_scenarios,
                hydrogen=hydrogen,
                economics=economics,
                solver_settings=solver_settings,
                delta_t_hours=delta_t_hours,
                inventory_start_kg=inventory_start_kg,
                reserve_kg=reserve_kg,
                daily_target_kg=daily_target_kg,
                target_hydrogen_max_kg=target_hydrogen_max_kg,
                gamma=gamma,
                alpha=alpha,
                production_target_mode=production_target_mode,
                shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
                apply_terminal_value=apply_terminal_value,
                terminal_reference_start_kg=terminal_reference_start_kg,
                terminal_value_per_kg=terminal_value_per_kg,
                solver_log_path=solver_log_path,
            )
        except RuntimeError as exc:
            last_error = exc
            if preference == "pyomo":
                raise
    if preference in {"pulp", "auto"} and pulp is not None:
        return _solve_with_pulp(
            day_scenarios=day_scenarios,
            hydrogen=hydrogen,
            economics=economics,
            solver_settings=solver_settings,
            delta_t_hours=delta_t_hours,
            inventory_start_kg=inventory_start_kg,
            reserve_kg=reserve_kg,
            daily_target_kg=daily_target_kg,
            target_hydrogen_max_kg=target_hydrogen_max_kg,
            gamma=gamma,
            alpha=alpha,
            production_target_mode=production_target_mode,
            shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
            apply_terminal_value=apply_terminal_value,
            terminal_reference_start_kg=terminal_reference_start_kg,
            terminal_value_per_kg=terminal_value_per_kg,
            solver_log_path=solver_log_path,
        )
    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error
    raise RuntimeError(
        "No configured solver backend could be started. "
        f"package_preference={solver_settings.package_preference}, solver_name={solver_settings.solver_name}."
    )


def solve_deterministic_dispatch(
    *,
    prices_eur_per_mwh: pd.Series,
    timestamps_utc: pd.DatetimeIndex,
    hydrogen: HydrogenSystemSettings,
    economics: EconomicSettings,
    solver_settings: SolverSettings,
    delta_t_hours: float,
    inventory_start_kg: float,
    reserve_kg: float,
    daily_target_kg: float,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    target_hydrogen_max_kg: float | None = None,
    solver_log_path: str | None = None,
) -> DispatchSolveResult:
    frame = pd.DataFrame(
        {
            "scenario_id": "deterministic",
            "scenario_probability": 1.0,
            "scenario_price_eur_per_mwh": pd.Series(prices_eur_per_mwh).astype(float).to_numpy(),
            "delivery_start_utc": list(timestamps_utc),
        }
    )
    return solve_stochastic_dispatch(
        day_scenarios=frame,
        hydrogen=hydrogen,
        economics=economics,
        solver_settings=solver_settings,
        delta_t_hours=delta_t_hours,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        daily_target_kg=daily_target_kg,
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        gamma=0.0,
        alpha=0.95,
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=terminal_value_per_kg,
        solver_log_path=solver_log_path,
    )
