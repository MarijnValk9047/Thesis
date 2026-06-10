from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .optimisation.input_resolver import ResolvedMFRRCapacityPilotInput
from .plant_parameters import (
    EconomicSettings,
    HydrogenSystemSettings,
    ProductionTargetsSettings,
    ReserveFeasibilityProxySettings,
    SolverSettings,
)
from .production_target import (
    build_rolling_production_target_plan,
    build_rolling_up_recovery_proxy_bounds,
    deliverable_output_kg_per_site_load_mwh,
    is_rolling_deadline_mode,
    RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY,
    RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM,
    should_apply_terminal_inventory_value,
)

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
    objective_components: pd.DataFrame | None = None
    mfrr_capacity_summary: pd.DataFrame | None = None
    debug_info: dict[str, Any] | None = None


MFRR_MARKET_TZ = ZoneInfo("Europe/Amsterdam")


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
    hydrogen_revenue_per_kg: float,
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
        hydrogen_revenue = float(hydrogen_revenue_per_kg * dispatch["H_comp_kg"].sum())
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


def _resolve_mfrr_capacity_horizon_metadata(
    timestamps: pd.DatetimeIndex,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput,
) -> tuple[list[str], list[str], dict[int, str], dict[str, list[int]]]:
    delivery_days = sorted(mfrr_capacity_pilot.candidate_summary["delivery_date_local"].astype(str).unique().tolist())
    directions = sorted(mfrr_capacity_pilot.candidate_summary["direction"].astype(str).unique().tolist())
    time_to_day = {
        idx: pd.Timestamp(timestamp).tz_convert(MFRR_MARKET_TZ).date().isoformat()
        for idx, timestamp in enumerate(timestamps)
    }
    if set(delivery_days) != set(time_to_day.values()):
        raise ValueError(
            "mFRR capacity pilot days must match the stochastic dispatch horizon days exactly."
        )
    day_to_time = {day: [idx for idx, local_day in time_to_day.items() if local_day == day] for day in delivery_days}
    for day, indices in day_to_time.items():
        if not indices:
            raise ValueError(f"No dispatch periods were found for mFRR capacity pilot day {day}.")
    return delivery_days, directions, time_to_day, day_to_time


def _build_mfrr_capacity_summary_from_solution(
    *,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput,
    dispatch: pd.DataFrame,
    hydrogen: HydrogenSystemSettings,
    offered_lookup: dict[tuple[str, str, str], float],
    selected_lookup: dict[tuple[str, str, str], float],
) -> pd.DataFrame:
    if dispatch.empty:
        return pd.DataFrame()
    work = dispatch.copy()
    work["delivery_date_local"] = (
        pd.to_datetime(work["delivery_start_utc"], utc=True, errors="raise")
        .dt.tz_convert(MFRR_MARKET_TZ)
        .dt.date.astype(str)
    )
    work["site_load_mw"] = work["P_el_mw"].astype(float) + work["P_comp_mw"].astype(float)
    max_site_load = float(hydrogen.electrolyser_nominal_mw + hydrogen.compressor_max_mw)
    diagnostics = (
        work.groupby("delivery_date_local", as_index=False)
        .agg(
            min_up_headroom_mw=("site_load_mw", "min"),
            max_site_load_mw=("site_load_mw", "max"),
        )
        .copy()
    )
    diagnostics["min_down_headroom_mw"] = max_site_load - diagnostics["max_site_load_mw"].astype(float)

    summary = mfrr_capacity_pilot.candidate_summary.copy()
    summary["selected_bid_candidate"] = summary.apply(
        lambda row: float(
            selected_lookup.get((str(row["delivery_date_local"]), str(row["direction"]), str(row["candidate_id"])), 0.0)
        ),
        axis=1,
    )
    summary["offered_capacity_mw"] = summary.apply(
        lambda row: float(
            offered_lookup.get((str(row["delivery_date_local"]), str(row["direction"]), str(row["candidate_id"])), 0.0)
        ),
        axis=1,
    )
    summary["expected_capacity_revenue_eur"] = (
        summary["expected_revenue_coefficient_eur_per_mw"].astype(float) * summary["offered_capacity_mw"].astype(float)
    )
    totals = (
        summary.groupby(["delivery_date_local", "direction"], as_index=False)["offered_capacity_mw"]
        .sum()
        .rename(columns={"offered_capacity_mw": "offered_capacity_total_mw"})
    )
    summary = summary.merge(totals, on=["delivery_date_local", "direction"], how="left")
    summary = summary.merge(diagnostics, on="delivery_date_local", how="left")
    summary["min_deliverability_margin_mw"] = np.where(
        summary["direction"].astype(str).eq("Up"),
        summary["min_up_headroom_mw"].astype(float) - summary["offered_capacity_total_mw"].astype(float),
        summary["min_down_headroom_mw"].astype(float) - summary["offered_capacity_total_mw"].astype(float),
    )
    return summary.sort_values(["delivery_date_local", "direction", "candidate_rank"]).reset_index(drop=True)


def _add_mfrr_capacity_pilot_pyomo_components(
    *,
    model: Any,
    timestamps: pd.DatetimeIndex,
    horizon: list[int],
    delta_t_hours: float,
    hydrogen: HydrogenSystemSettings,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput,
    rolling_target_plan: Any = None,
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings | None = None,
) -> dict[str, Any]:
    delivery_days, directions, time_to_day, _ = _resolve_mfrr_capacity_horizon_metadata(
        timestamps,
        mfrr_capacity_pilot,
    )
    candidate_summary = mfrr_capacity_pilot.candidate_summary.copy()
    candidate_summary["delivery_date_local"] = candidate_summary["delivery_date_local"].astype(str)
    candidate_summary["direction"] = candidate_summary["direction"].astype(str)
    candidate_summary["candidate_id"] = candidate_summary["candidate_id"].astype(str)
    candidate_summary["candidate_price_eur_per_mw_isp"] = pd.to_numeric(
        candidate_summary["candidate_price_eur_per_mw_isp"], errors="raise"
    )
    candidate_summary["expected_revenue_coefficient_eur_per_mw"] = pd.to_numeric(
        candidate_summary["expected_revenue_coefficient_eur_per_mw"], errors="raise"
    )
    candidate_keys = [
        (str(row["delivery_date_local"]), str(row["direction"]), str(row["candidate_id"]))
        for row in candidate_summary.to_dict(orient="records")
    ]
    day_direction_pairs = sorted({(day, direction) for day in delivery_days for direction in directions})
    candidate_ids_by_pair = {
        (day, direction): [
            str(row["candidate_id"])
            for row in candidate_summary[
                (candidate_summary["delivery_date_local"].astype(str) == day)
                & (candidate_summary["direction"].astype(str) == direction)
            ].sort_values("candidate_rank")
            .to_dict(orient="records")
        ]
        for day, direction in day_direction_pairs
    }
    expected_revenue_lookup = {
        (str(row["delivery_date_local"]), str(row["direction"]), str(row["candidate_id"])): float(
            row["expected_revenue_coefficient_eur_per_mw"]
        )
        for row in candidate_summary.to_dict(orient="records")
    }
    max_site_load = float(hydrogen.electrolyser_nominal_mw + hydrogen.compressor_max_mw)
    offer_big_m = min(float(mfrr_capacity_pilot.capacity_offer_big_m_mw), max_site_load)
    proxy_mode = str(reserve_feasibility_proxy.mode).strip() if reserve_feasibility_proxy is not None else "none"
    down_absorption_proxy_active = bool(
        reserve_feasibility_proxy is not None
        and bool(reserve_feasibility_proxy.enabled)
        and proxy_mode in {
            RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION,
            RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY,
        }
        and rolling_target_plan is not None
    )
    up_recovery_proxy_active = bool(
        reserve_feasibility_proxy is not None
        and bool(reserve_feasibility_proxy.enabled)
        and proxy_mode == RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY
        and rolling_target_plan is not None
    )
    if down_absorption_proxy_active:
        if rolling_target_plan.max_inventory_kg is None:
            raise ValueError(
                "reserve_feasibility_proxy conservative_output_absorption requires "
                "a finite production_targets.max_inventory_kg in rolling_deadline_envelope mode."
            )
        if (
            str(reserve_feasibility_proxy.down_output_absorption_source).strip()
            != RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM
        ):
            raise ValueError(
                "Unsupported reserve_feasibility_proxy.down_output_absorption_source: "
                f"{reserve_feasibility_proxy.down_output_absorption_source!r}"
            )
        down_activation_duration_hours = float(reserve_feasibility_proxy.down_activation_duration_hours)
        down_output_kg_per_mwh = float(deliverable_output_kg_per_site_load_mwh(hydrogen=hydrogen))
    else:
        down_activation_duration_hours = 0.0
        down_output_kg_per_mwh = 0.0
    if up_recovery_proxy_active:
        if (
            str(reserve_feasibility_proxy.up_recovery_source).strip()
            != RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM
        ):
            raise ValueError(
                "Unsupported reserve_feasibility_proxy.up_recovery_source: "
                f"{reserve_feasibility_proxy.up_recovery_source!r}"
            )
        up_activation_duration_hours = float(reserve_feasibility_proxy.up_activation_duration_hours)
        up_output_kg_per_mwh = float(deliverable_output_kg_per_site_load_mwh(hydrogen=hydrogen))
        up_recovery_bounds = build_rolling_up_recovery_proxy_bounds(
            timestamps_utc=timestamps,
            hydrogen=hydrogen,
            rolling_target_plan=rolling_target_plan,
            delta_t_hours=delta_t_hours,
        )
        max_cumulative_required_kg = max(
            [float(required) for _, required in rolling_target_plan.cumulative_requirements_by_due_date] or [0.0]
        )
        up_recovery_relaxation_kg = max(0.0, max_cumulative_required_kg - float(rolling_target_plan.initial_inventory_kg))
    else:
        up_activation_duration_hours = 0.0
        up_output_kg_per_mwh = 0.0
        up_recovery_bounds = tuple()
        up_recovery_relaxation_kg = 0.0
    if bool(mfrr_capacity_pilot.offer_continuous_mw):
        raise ValueError(
            "Continuous mFRR capacity offers are no longer supported in this pilot. "
            "Dutch incident reserve capacity bids must respect the 1 MW minimum and 1 MW step size."
        )
    offer_domain = pyo.NonNegativeIntegers

    model.MFRR_DAY_DIRECTION = pyo.Set(dimen=2, initialize=day_direction_pairs, ordered=True)
    model.MFRR_DAY_DIRECTION_CANDIDATE = pyo.Set(dimen=3, initialize=candidate_keys, ordered=True)
    model.mfrr_bid_select = pyo.Var(model.MFRR_DAY_DIRECTION_CANDIDATE, domain=pyo.Binary)
    model.mfrr_offered_capacity_mw = pyo.Var(model.MFRR_DAY_DIRECTION_CANDIDATE, domain=offer_domain)
    model.mfrr_offered_capacity_total_mw = pyo.Expression(
        model.MFRR_DAY_DIRECTION,
        rule=lambda m, day, direction: sum(
            m.mfrr_offered_capacity_mw[day, direction, candidate_id]
            for candidate_id in candidate_ids_by_pair[(day, direction)]
        ),
    )
    model.mfrr_expected_capacity_revenue_eur = pyo.Expression(
        expr=sum(
            expected_revenue_lookup[(day, direction, candidate_id)] * model.mfrr_offered_capacity_mw[day, direction, candidate_id]
            for day, direction, candidate_id in candidate_keys
        )
    )
    for day, direction in day_direction_pairs:
        model.constraints.add(
            sum(
                model.mfrr_bid_select[day, direction, candidate_id]
                for candidate_id in candidate_ids_by_pair[(day, direction)]
            )
            <= 1
        )
    for day, direction, candidate_id in candidate_keys:
        model.constraints.add(
            model.mfrr_offered_capacity_mw[day, direction, candidate_id]
            <= offer_big_m * model.mfrr_bid_select[day, direction, candidate_id]
        )
        model.constraints.add(
            model.mfrr_offered_capacity_mw[day, direction, candidate_id]
            >= 1.0 * model.mfrr_bid_select[day, direction, candidate_id]
        )
    for t in horizon:
        day = time_to_day[t]
        if (day, "Up") in day_direction_pairs:
            model.constraints.add(model.mfrr_offered_capacity_total_mw[day, "Up"] <= model.P_el[t] + model.P_comp[t])
            if up_recovery_proxy_active:
                selected_up_expr = sum(
                    model.mfrr_bid_select[day, "Up", candidate_id]
                    for candidate_id in candidate_ids_by_pair[(day, "Up")]
                )
                for bound in up_recovery_bounds:
                    if int(bound.time_index) != int(t):
                        continue
                    model.constraints.add(
                        model.mfrr_offered_capacity_total_mw[day, "Up"] * up_activation_duration_hours * up_output_kg_per_mwh
                        <= float(rolling_target_plan.initial_inventory_kg)
                        + sum(model.H_comp[k] for k in range(t + 1))
                        + float(bound.future_max_recoverable_output_kg)
                        - float(bound.cumulative_required_kg)
                        + float(up_recovery_relaxation_kg) * (1.0 - selected_up_expr)
                    )
        if (day, "Down") in day_direction_pairs:
            model.constraints.add(
                model.mfrr_offered_capacity_total_mw[day, "Down"] <= max_site_load - (model.P_el[t] + model.P_comp[t])
            )
            if down_absorption_proxy_active:
                model.constraints.add(
                    model.mfrr_offered_capacity_total_mw[day, "Down"] * down_activation_duration_hours * down_output_kg_per_mwh
                    + float(rolling_target_plan.initial_inventory_kg)
                    + sum(model.H_comp[k] for k in range(t + 1))
                    - float(rolling_target_plan.cumulative_required_due_by_time_index_kg[t])
                    <= float(rolling_target_plan.max_inventory_kg)
                )
    return {
        "expected_capacity_revenue_expr": model.mfrr_expected_capacity_revenue_eur,
        "candidate_keys": candidate_keys,
        "day_direction_pairs": day_direction_pairs,
        "down_absorption_proxy_active": down_absorption_proxy_active,
        "down_activation_duration_hours": float(down_activation_duration_hours),
        "down_output_kg_per_mwh": float(down_output_kg_per_mwh),
        "up_recovery_proxy_active": up_recovery_proxy_active,
        "up_activation_duration_hours": float(up_activation_duration_hours),
        "up_output_kg_per_mwh": float(up_output_kg_per_mwh),
        "up_recovery_bounds": up_recovery_bounds,
    }


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
    production_targets: ProductionTargetsSettings | None,
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings | None,
    shortfall_penalty_eur_per_kg: float | None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput | None = None,
    solver_log_path: str | None = None,
    debug_options: dict[str, Any] | None = None,
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
    rolling_target_plan = (
        build_rolling_production_target_plan(
            timestamps_utc=timestamps,
            hydrogen=hydrogen,
            production_targets=production_targets,
            delta_t_hours=delta_t_hours,
        )
        if is_rolling_deadline_mode(production_targets)
        else None
    )
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=production_targets,
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
                m.constraints.add(sum_h_comp >= float(guard.minimum_h_comp_required_by_horizon_end_kg))
        if rolling_target_plan.max_inventory_kg is not None:
            for t in horizon:
                m.constraints.add(
                    float(rolling_target_plan.initial_inventory_kg)
                    + sum(m.H_comp[k] for k in range(t + 1))
                    - float(rolling_target_plan.cumulative_required_due_by_time_index_kg[t])
                    <= float(rolling_target_plan.max_inventory_kg)
                )
    elif _is_hard_target_mode(production_target_mode):
        m.constraints.add(sum_h_comp >= target_hydrogen_min_kg)
        if target_hydrogen_max_kg_value is not None:
            m.constraints.add(sum_h_comp <= target_hydrogen_max_kg_value)
        m.constraints.add(m.shortfall == 0.0)
    else:
        m.constraints.add(sum_h_comp + m.shortfall >= target_hydrogen_min_kg)

    mfrr_expected_capacity_revenue_expr: float | Any = 0.0
    mfrr_day_direction_pairs: list[tuple[str, str]] = []
    mfrr_candidate_keys: list[tuple[str, str, str]] = []
    mfrr_offer_lookup: dict[tuple[str, str, str], float] = {}
    mfrr_select_lookup: dict[tuple[str, str, str], float] = {}
    if mfrr_capacity_pilot is not None:
        mfrr_components = _add_mfrr_capacity_pilot_pyomo_components(
            model=m,
            timestamps=timestamps,
            horizon=horizon,
            delta_t_hours=delta_t_hours,
            hydrogen=hydrogen,
            mfrr_capacity_pilot=mfrr_capacity_pilot,
            rolling_target_plan=rolling_target_plan,
            reserve_feasibility_proxy=reserve_feasibility_proxy,
        )
        mfrr_expected_capacity_revenue_expr = mfrr_components["expected_capacity_revenue_expr"]
        mfrr_candidate_keys = list(mfrr_components["candidate_keys"])
        mfrr_day_direction_pairs = list(mfrr_components["day_direction_pairs"])
        mfrr_down_absorption_proxy_active = bool(mfrr_components["down_absorption_proxy_active"])
        mfrr_down_output_kg_per_mwh = float(mfrr_components["down_output_kg_per_mwh"])
        mfrr_up_recovery_proxy_active = bool(mfrr_components["up_recovery_proxy_active"])
        mfrr_up_output_kg_per_mwh = float(mfrr_components["up_output_kg_per_mwh"])
        mfrr_up_recovery_bounds = tuple(mfrr_components["up_recovery_bounds"])
        if bool((debug_options or {}).get("force_mfrr_offer_zero", False)):
            for key in mfrr_candidate_keys:
                m.constraints.add(m.mfrr_offered_capacity_mw[key] == 0.0)
    else:
        mfrr_down_absorption_proxy_active = False
        mfrr_down_output_kg_per_mwh = 0.0
        mfrr_up_recovery_proxy_active = False
        mfrr_up_output_kg_per_mwh = 0.0
        mfrr_up_recovery_bounds = tuple()
    terminal_value_expr = (
        terminal_value_per_kg * (m.H_buf[t_max] - terminal_reference_start_kg)
        if effective_apply_terminal_value
        else 0.0
    )
    shortfall_penalty_expr = effective_shortfall_penalty * m.shortfall
    effective_hydrogen_revenue_per_kg = (
        float(economics.h2_sale_price_eur_per_kg)
        if rolling_target_plan is None
        else 0.0
    )
    revenue_expr = effective_hydrogen_revenue_per_kg * sum_h_comp

    for s in scenario_ids:
        electricity_cost_expr = sum(price_lookup[(s, t)] * (m.P_el[t] + m.P_comp[t]) * delta_t_hours for t in horizon)
        m.constraints.add(m.net_cost[s] == electricity_cost_expr + shortfall_penalty_expr - revenue_expr - terminal_value_expr)
        m.constraints.add(m.xi[s] >= m.net_cost[s] - m.zeta)

    expected_net_cost = sum(probabilities[s] * m.net_cost[s] for s in scenario_ids)
    cvar_term = m.zeta + (1.0 / (1.0 - alpha)) * sum(probabilities[s] * m.xi[s] for s in scenario_ids)
    m.objective = pyo.Objective(
        expr=expected_net_cost - mfrr_expected_capacity_revenue_expr + gamma * cvar_term,
        sense=pyo.minimize,
    )

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
        hydrogen_revenue_per_kg=effective_hydrogen_revenue_per_kg,
        shortfall_kg=shortfall_value,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        apply_terminal_value=effective_apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=terminal_value_per_kg,
        net_cost_lookup=net_cost_lookup,
        xi_lookup=xi_lookup,
    )
    zeta_value = float(_safe_pyomo_value(m.zeta) or 0.0)
    cvar_value = float(zeta_value + (1.0 / (1.0 - alpha)) * np.sum(scenario_costs["scenario_probability"] * scenario_costs["xi_value"]))
    objective_value = _safe_pyomo_value(m.objective)
    expected_operational_net_cost = float(np.sum(scenario_costs["scenario_probability"] * scenario_costs["net_cost_eur"]))
    expected_mfrr_capacity_revenue = float(_safe_pyomo_value(mfrr_expected_capacity_revenue_expr) or 0.0)
    objective_components = pd.DataFrame(
        [
            {
                "expected_operational_net_cost_eur": expected_operational_net_cost,
                "expected_mfrr_capacity_revenue_eur": expected_mfrr_capacity_revenue,
                "cvar_term_eur": cvar_value,
                "cvar_weight_gamma": float(gamma),
                "objective_value_eur": float(objective_value) if objective_value is not None else np.nan,
            }
        ]
    )
    if mfrr_capacity_pilot is not None:
        mfrr_offer_lookup = {
            key: float(_safe_pyomo_value(m.mfrr_offered_capacity_mw[key]) or 0.0) for key in mfrr_candidate_keys
        }
        mfrr_select_lookup = {
            key: float(_safe_pyomo_value(m.mfrr_bid_select[key]) or 0.0) for key in mfrr_candidate_keys
        }
        mfrr_capacity_summary = _build_mfrr_capacity_summary_from_solution(
            mfrr_capacity_pilot=mfrr_capacity_pilot,
            dispatch=dispatch,
            hydrogen=hydrogen,
            offered_lookup=mfrr_offer_lookup,
            selected_lookup=mfrr_select_lookup,
        )
    else:
        mfrr_capacity_summary = None
    model_stats = _pyomo_model_stats(
        m,
        scenario_count=len(scenario_ids),
        horizon_steps=len(horizon),
        delta_t_hours=delta_t_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    diagnostics = _pyomo_solver_diagnostics(results)
    up_recovery_headroom_by_time_index_kg: list[float] = []
    if rolling_target_plan is not None and mfrr_up_recovery_bounds:
        cumulative_h_comp = dispatch["H_comp_kg"].astype(float).cumsum().tolist()
        grouped_bounds: dict[int, list[Any]] = {}
        for bound in mfrr_up_recovery_bounds:
            grouped_bounds.setdefault(int(bound.time_index), []).append(bound)
        for t in horizon:
            if int(t) not in grouped_bounds:
                up_recovery_headroom_by_time_index_kg.append(0.0)
                continue
            candidate_headrooms = [
                float(rolling_target_plan.initial_inventory_kg)
                + float(cumulative_h_comp[t])
                + float(bound.future_max_recoverable_output_kg)
                - float(bound.cumulative_required_kg)
                for bound in grouped_bounds[int(t)]
            ]
            up_recovery_headroom_by_time_index_kg.append(float(min(candidate_headrooms)))
    debug_info: dict[str, Any] | None = None
    if bool((debug_options or {}).get("collect_objective_audit", False)):
        active_objectives = list(m.component_data_objects(pyo.Objective, active=True, descend_into=True))
        debug_info = {
            "active_objective_count": int(len(active_objectives)),
            "active_objectives": [
                {
                    "name": str(obj.name),
                    "sense": "minimize" if obj.sense == pyo.minimize else "maximize",
                    "value": _safe_pyomo_value(obj),
                }
                for obj in active_objectives
            ],
            "reported_objective_value_eur": float(objective_value) if objective_value is not None else None,
            "expected_operational_net_cost_eur": float(expected_operational_net_cost),
            "expected_mfrr_capacity_revenue_eur": float(expected_mfrr_capacity_revenue),
            "cvar_term_eur": float(cvar_value),
            "effective_hydrogen_revenue_per_kg": float(effective_hydrogen_revenue_per_kg),
            "force_mfrr_offer_zero": bool((debug_options or {}).get("force_mfrr_offer_zero", False)),
            "solver_diagnostics": diagnostics,
            "production_targets_mode": str(production_targets.mode) if production_targets is not None else "legacy_daily_minimum",
            "rolling_target_plan": None
            if rolling_target_plan is None
            else {
                "due_date_interpretation": rolling_target_plan.due_date_interpretation,
                "horizon_start_local_date": rolling_target_plan.horizon_start_local_date,
                "horizon_end_local_date": rolling_target_plan.horizon_end_local_date,
                "rolling_constraints": [
                    {
                        "due_date": bound.due_date,
                        "cutoff_time_index": int(bound.cutoff_time_index),
                        "cumulative_required_kg": float(bound.cumulative_required_kg),
                    }
                    for bound in rolling_target_plan.rolling_constraints
                ],
                "terminal_guards": [
                    {
                        "due_date": guard.due_date,
                        "cumulative_required_kg": float(guard.cumulative_required_kg),
                        "future_max_production_kg": float(guard.future_max_production_kg),
                        "minimum_h_comp_required_by_horizon_end_kg": float(guard.minimum_h_comp_required_by_horizon_end_kg),
                        "active": bool(guard.active),
                    }
                    for guard in rolling_target_plan.terminal_guards
                ],
                "inventory_cap_active": rolling_target_plan.max_inventory_kg is not None,
                "max_inventory_kg": rolling_target_plan.max_inventory_kg,
                "cumulative_required_due_by_time_index_kg": [
                    float(value) for value in rolling_target_plan.cumulative_required_due_by_time_index_kg
                ],
                "terminal_inventory_value_mode": rolling_target_plan.terminal_inventory_value_mode,
                "effective_apply_terminal_value": bool(effective_apply_terminal_value),
                "effective_hydrogen_revenue_per_kg": float(effective_hydrogen_revenue_per_kg),
                "reserve_feasibility_proxy": {
                    "enabled": bool(reserve_feasibility_proxy.enabled) if reserve_feasibility_proxy is not None else False,
                    "mode": str(reserve_feasibility_proxy.mode) if reserve_feasibility_proxy is not None else "none",
                    "down_activation_duration_hours": (
                        float(reserve_feasibility_proxy.down_activation_duration_hours)
                        if reserve_feasibility_proxy is not None
                        else 0.0
                    ),
                    "down_output_absorption_source": (
                        str(reserve_feasibility_proxy.down_output_absorption_source)
                        if reserve_feasibility_proxy is not None
                        else "none"
                    ),
                    "up_activation_duration_hours": (
                        float(reserve_feasibility_proxy.up_activation_duration_hours)
                        if reserve_feasibility_proxy is not None
                        else 0.0
                    ),
                    "up_recovery_source": (
                        str(reserve_feasibility_proxy.up_recovery_source)
                        if reserve_feasibility_proxy is not None
                        else "none"
                    ),
                    "active_for_down_rolling_cap": bool(mfrr_down_absorption_proxy_active),
                    "down_output_kg_per_mwh": float(mfrr_down_output_kg_per_mwh),
                    "active_for_up_rolling_recovery": bool(mfrr_up_recovery_proxy_active),
                    "up_output_kg_per_mwh": float(mfrr_up_output_kg_per_mwh),
                    "up_recovery_headroom_by_time_index_kg": [
                        float(value) for value in up_recovery_headroom_by_time_index_kg
                    ],
                },
            },
        }
    elif rolling_target_plan is not None:
        debug_info = {
            "production_targets_mode": str(production_targets.mode),
            "rolling_target_plan": {
                "due_date_interpretation": rolling_target_plan.due_date_interpretation,
                "horizon_start_local_date": rolling_target_plan.horizon_start_local_date,
                "horizon_end_local_date": rolling_target_plan.horizon_end_local_date,
                "rolling_constraints": [
                    {
                        "due_date": bound.due_date,
                        "cutoff_time_index": int(bound.cutoff_time_index),
                        "cumulative_required_kg": float(bound.cumulative_required_kg),
                    }
                    for bound in rolling_target_plan.rolling_constraints
                ],
                "terminal_guards": [
                    {
                        "due_date": guard.due_date,
                        "cumulative_required_kg": float(guard.cumulative_required_kg),
                        "future_max_production_kg": float(guard.future_max_production_kg),
                        "minimum_h_comp_required_by_horizon_end_kg": float(guard.minimum_h_comp_required_by_horizon_end_kg),
                        "active": bool(guard.active),
                    }
                    for guard in rolling_target_plan.terminal_guards
                ],
                "inventory_cap_active": rolling_target_plan.max_inventory_kg is not None,
                "max_inventory_kg": rolling_target_plan.max_inventory_kg,
                "cumulative_required_due_by_time_index_kg": [
                    float(value) for value in rolling_target_plan.cumulative_required_due_by_time_index_kg
                ],
                "terminal_inventory_value_mode": rolling_target_plan.terminal_inventory_value_mode,
                "effective_apply_terminal_value": bool(effective_apply_terminal_value),
                "effective_hydrogen_revenue_per_kg": float(effective_hydrogen_revenue_per_kg),
                "reserve_feasibility_proxy": {
                    "enabled": bool(reserve_feasibility_proxy.enabled) if reserve_feasibility_proxy is not None else False,
                    "mode": str(reserve_feasibility_proxy.mode) if reserve_feasibility_proxy is not None else "none",
                    "down_activation_duration_hours": (
                        float(reserve_feasibility_proxy.down_activation_duration_hours)
                        if reserve_feasibility_proxy is not None
                        else 0.0
                    ),
                    "down_output_absorption_source": (
                        str(reserve_feasibility_proxy.down_output_absorption_source)
                        if reserve_feasibility_proxy is not None
                        else "none"
                    ),
                    "up_activation_duration_hours": (
                        float(reserve_feasibility_proxy.up_activation_duration_hours)
                        if reserve_feasibility_proxy is not None
                        else 0.0
                    ),
                    "up_recovery_source": (
                        str(reserve_feasibility_proxy.up_recovery_source)
                        if reserve_feasibility_proxy is not None
                        else "none"
                    ),
                    "active_for_down_rolling_cap": bool(mfrr_down_absorption_proxy_active),
                    "down_output_kg_per_mwh": float(mfrr_down_output_kg_per_mwh),
                    "active_for_up_rolling_recovery": bool(mfrr_up_recovery_proxy_active),
                    "up_output_kg_per_mwh": float(mfrr_up_output_kg_per_mwh),
                    "up_recovery_headroom_by_time_index_kg": [
                        float(value) for value in up_recovery_headroom_by_time_index_kg
                    ],
                },
            },
        }
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
        objective_components=objective_components,
        mfrr_capacity_summary=mfrr_capacity_summary,
        debug_info=debug_info,
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
    production_targets: ProductionTargetsSettings | None,
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings | None,
    shortfall_penalty_eur_per_kg: float | None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput | None = None,
    solver_log_path: str | None = None,
    debug_options: dict[str, Any] | None = None,
) -> DispatchSolveResult:
    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")
    if mfrr_capacity_pilot is not None:
        raise RuntimeError("The v1 mFRR capacity pilot is implemented only for the Pyomo backend.")
    build_started = perf_counter()
    effective_shortfall_penalty = _effective_shortfall_penalty(
        economics,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
    )
    rolling_target_plan = (
        build_rolling_production_target_plan(
            timestamps_utc=timestamps,
            hydrogen=hydrogen,
            production_targets=production_targets,
            delta_t_hours=delta_t_hours,
        )
        if is_rolling_deadline_mode(production_targets)
        else None
    )
    effective_apply_terminal_value = should_apply_terminal_inventory_value(
        apply_terminal_value=apply_terminal_value,
        production_targets=production_targets,
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
                model += sum_h_comp >= float(guard.minimum_h_comp_required_by_horizon_end_kg), f"rolling_terminal_guard_{idx}"
        if rolling_target_plan.max_inventory_kg is not None:
            for t in horizon:
                model += (
                    float(rolling_target_plan.initial_inventory_kg)
                    + pulp.lpSum(h_comp[k] for k in range(t + 1))
                    - float(rolling_target_plan.cumulative_required_due_by_time_index_kg[t])
                    <= float(rolling_target_plan.max_inventory_kg)
                ), f"rolling_inventory_cap_{t}"
    elif _is_hard_target_mode(production_target_mode):
        model += sum_h_comp >= target_hydrogen_min_kg, "daily_target_lb"
        if target_hydrogen_max_kg_value is not None:
            model += sum_h_comp <= target_hydrogen_max_kg_value, "daily_target_ub"
        model += shortfall == 0.0, "hard_target_shortfall_zero"
    else:
        model += sum_h_comp + shortfall >= target_hydrogen_min_kg, "daily_target_lb"

    terminal_value_expr = (
        terminal_value_per_kg * (h_buf[len(timestamps) - 1] - terminal_reference_start_kg)
        if effective_apply_terminal_value
        else 0.0
    )
    shortfall_penalty_expr = effective_shortfall_penalty * shortfall
    effective_hydrogen_revenue_per_kg = (
        float(economics.h2_sale_price_eur_per_kg)
        if rolling_target_plan is None
        else 0.0
    )
    revenue_expr = effective_hydrogen_revenue_per_kg * sum_h_comp

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
        hydrogen_revenue_per_kg=effective_hydrogen_revenue_per_kg,
        shortfall_kg=shortfall_value,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        apply_terminal_value=effective_apply_terminal_value,
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
        debug_info={
            "production_targets_mode": str(production_targets.mode) if production_targets is not None else "legacy_daily_minimum",
            "rolling_target_plan": None
            if rolling_target_plan is None
            else {
                "due_date_interpretation": rolling_target_plan.due_date_interpretation,
                "horizon_start_local_date": rolling_target_plan.horizon_start_local_date,
                "horizon_end_local_date": rolling_target_plan.horizon_end_local_date,
                "rolling_constraints": [
                    {
                        "due_date": bound.due_date,
                        "cutoff_time_index": int(bound.cutoff_time_index),
                        "cumulative_required_kg": float(bound.cumulative_required_kg),
                    }
                    for bound in rolling_target_plan.rolling_constraints
                ],
                "terminal_guards": [
                    {
                        "due_date": guard.due_date,
                        "cumulative_required_kg": float(guard.cumulative_required_kg),
                        "future_max_production_kg": float(guard.future_max_production_kg),
                        "minimum_h_comp_required_by_horizon_end_kg": float(guard.minimum_h_comp_required_by_horizon_end_kg),
                        "active": bool(guard.active),
                    }
                    for guard in rolling_target_plan.terminal_guards
                ],
                "inventory_cap_active": rolling_target_plan.max_inventory_kg is not None,
                "max_inventory_kg": rolling_target_plan.max_inventory_kg,
                "terminal_inventory_value_mode": rolling_target_plan.terminal_inventory_value_mode,
                "effective_apply_terminal_value": bool(effective_apply_terminal_value),
                "effective_hydrogen_revenue_per_kg": float(effective_hydrogen_revenue_per_kg),
            },
        },
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
    production_targets: ProductionTargetsSettings | None = None,
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings | None = None,
    shortfall_penalty_eur_per_kg: float | None = None,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    terminal_value_per_kg: float,
    target_hydrogen_max_kg: float | None = None,
    mfrr_capacity_pilot: ResolvedMFRRCapacityPilotInput | None = None,
    solver_log_path: str | None = None,
    debug_options: dict[str, Any] | None = None,
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
                production_targets=production_targets,
                reserve_feasibility_proxy=reserve_feasibility_proxy,
                shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
                apply_terminal_value=apply_terminal_value,
                terminal_reference_start_kg=terminal_reference_start_kg,
                terminal_value_per_kg=terminal_value_per_kg,
                mfrr_capacity_pilot=mfrr_capacity_pilot,
                solver_log_path=solver_log_path,
                debug_options=debug_options,
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
            production_targets=production_targets,
            reserve_feasibility_proxy=reserve_feasibility_proxy,
            shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
            apply_terminal_value=apply_terminal_value,
            terminal_reference_start_kg=terminal_reference_start_kg,
            terminal_value_per_kg=terminal_value_per_kg,
            mfrr_capacity_pilot=mfrr_capacity_pilot,
            solver_log_path=solver_log_path,
            debug_options=debug_options,
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
    production_targets: ProductionTargetsSettings | None = None,
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings | None = None,
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
        production_targets=production_targets,
        reserve_feasibility_proxy=reserve_feasibility_proxy,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        apply_terminal_value=apply_terminal_value,
        terminal_reference_start_kg=terminal_reference_start_kg,
        terminal_value_per_kg=terminal_value_per_kg,
        solver_log_path=solver_log_path,
    )
