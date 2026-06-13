from __future__ import annotations

from typing import Any

from pyomo.environ import SolverStatus, TerminationCondition, value
from pyomo.contrib.solver.common.util import NoFeasibleSolutionError

from .config import SteelToyConfig
from .model import build_model


def _terminal_rule_precheck(config: SteelToyConfig) -> dict[str, Any] | None:
    horizon = len(config.time_indices)
    for store_name, store in config.stores.items():
        if store.terminal_min_tonnes > store.capacity_tonnes or store.terminal_max_tonnes > store.capacity_tonnes:
            return {
                "infeasibility_class": "terminal_inventory_violation",
                "reason": f"{store_name} terminal bound exceeds store capacity.",
            }
        if store.terminal_min_tonnes > store.terminal_max_tonnes:
            return {
                "infeasibility_class": "terminal_inventory_violation",
                "reason": f"{store_name} terminal minimum exceeds terminal maximum.",
            }
        max_reachable = store.initial_inventory_tonnes + store.charge_max_tph * horizon
        min_reachable = max(0.0, store.initial_inventory_tonnes - store.discharge_max_tph * horizon)
        if store.terminal_min_tonnes > max_reachable or store.terminal_max_tonnes < min_reachable:
            return {
                "infeasibility_class": "terminal_inventory_violation",
                "reason": f"{store_name} terminal inventory is unreachable within configured charge/discharge limits.",
            }
    return None


def _solve_max_production(config: SteelToyConfig, solver, *, ignore_source_limits: bool) -> tuple[float | None, str, str]:
    model = build_model(
        config,
        objective_mode="max_production",
        ignore_source_limits=ignore_source_limits,
        include_production_target=False,
    )
    try:
        result = solver.solve(model, tee=False)
    except NoFeasibleSolutionError:
        result = solver.solve(model, tee=False, load_solutions=False)
    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    success = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )
    if not success:
        return None, solver_status, termination_condition
    produced = sum(value(model.sink_flow[config.production_target.sink, time_index]) for time_index in config.time_indices)
    return float(produced), solver_status, termination_condition


def classify_infeasibility(config: SteelToyConfig, solver) -> dict[str, Any]:
    precheck = _terminal_rule_precheck(config)
    if precheck is not None:
        precheck["target_tonnes"] = float(config.production_target.total_tonnes)
        precheck["max_production_with_source_limits_tonnes"] = None
        precheck["max_production_relaxed_source_limits_tonnes"] = None
        return precheck

    actual_max, actual_status, actual_term = _solve_max_production(config, solver, ignore_source_limits=False)
    relaxed_max, relaxed_status, relaxed_term = _solve_max_production(config, solver, ignore_source_limits=True)
    target = float(config.production_target.total_tonnes)
    inferred = "unknown_infeasibility"
    reason = "Infeasibility could not be classified with the current S2 heuristic."

    if actual_max is not None and actual_max + 1e-6 < target:
        if relaxed_max is not None and relaxed_max + 1e-6 >= target:
            inferred = "feed_shortage"
            reason = "Relaxing source supply limits makes the production target reachable."
        else:
            inferred = "capacity_bottleneck"
            reason = "Even after relaxing source supply limits, route/process capacity is insufficient for the target."

    return {
        "infeasibility_class": inferred,
        "reason": reason,
        "target_tonnes": target,
        "max_production_with_source_limits_tonnes": actual_max,
        "max_production_with_source_limits_solver_status": actual_status,
        "max_production_with_source_limits_termination": actual_term,
        "max_production_relaxed_source_limits_tonnes": relaxed_max,
        "max_production_relaxed_source_limits_solver_status": relaxed_status,
        "max_production_relaxed_source_limits_termination": relaxed_term,
    }
