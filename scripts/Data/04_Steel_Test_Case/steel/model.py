from __future__ import annotations

from dataclasses import dataclass

from pyomo.environ import (
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    SolverFactory,
    Var,
    maximize,
    minimize,
)

from .config import SteelToyConfig


@dataclass(frozen=True)
class ModelStats:
    variables: int
    binaries: int
    constraints: int


def build_model(
    config: SteelToyConfig,
    *,
    objective_mode: str = "cost_min",
    ignore_source_limits: bool = False,
    include_production_target: bool = True,
):
    model = __import__("pyomo.environ", fromlist=["ConcreteModel"]).ConcreteModel()
    model.TIME = Set(initialize=config.time_indices, ordered=True)
    model.CARRIERS = Set(initialize=config.carriers)
    model.PROCESSES = Set(initialize=list(config.processes))
    model.SOURCES = Set(initialize=list(config.sources))
    model.SINKS = Set(initialize=list(config.sinks))
    model.STORES = Set(initialize=list(config.stores))

    model.process_throughput = Var(model.PROCESSES, model.TIME, domain=NonNegativeReals)
    model.source_supply = Var(model.SOURCES, model.TIME, domain=NonNegativeReals)
    model.sink_flow = Var(model.SINKS, model.TIME, domain=NonNegativeReals)
    model.store_charge = Var(model.STORES, model.TIME, domain=NonNegativeReals)
    model.store_discharge = Var(model.STORES, model.TIME, domain=NonNegativeReals)
    model.inventory = Var(model.STORES, model.TIME, domain=NonNegativeReals)

    time_points = config.time_indices
    first_time = time_points[0]
    last_time = time_points[-1]
    previous_time = {time_points[idx]: time_points[idx - 1] for idx in range(1, len(time_points))}

    def process_capacity_min_rule(m, process_name, time_index):
        return m.process_throughput[process_name, time_index] >= config.processes[process_name].capacity_min_tph

    def process_capacity_max_rule(m, process_name, time_index):
        return m.process_throughput[process_name, time_index] <= config.processes[process_name].capacity_max_tph

    model.process_capacity_min = Constraint(model.PROCESSES, model.TIME, rule=process_capacity_min_rule)
    model.process_capacity_max = Constraint(model.PROCESSES, model.TIME, rule=process_capacity_max_rule)

    if not ignore_source_limits:
        def source_capacity_rule(m, source_name, time_index):
            return m.source_supply[source_name, time_index] <= config.sources[source_name].max_supply_tph

        model.source_capacity = Constraint(model.SOURCES, model.TIME, rule=source_capacity_rule)

    def store_charge_capacity_rule(m, store_name, time_index):
        return m.store_charge[store_name, time_index] <= config.stores[store_name].charge_max_tph

    def store_discharge_capacity_rule(m, store_name, time_index):
        return m.store_discharge[store_name, time_index] <= config.stores[store_name].discharge_max_tph

    def store_capacity_rule(m, store_name, time_index):
        return m.inventory[store_name, time_index] <= config.stores[store_name].capacity_tonnes

    model.store_charge_capacity = Constraint(model.STORES, model.TIME, rule=store_charge_capacity_rule)
    model.store_discharge_capacity = Constraint(model.STORES, model.TIME, rule=store_discharge_capacity_rule)
    model.store_capacity = Constraint(model.STORES, model.TIME, rule=store_capacity_rule)

    def inventory_balance_rule(m, store_name, time_index):
        initial = config.stores[store_name].initial_inventory_tonnes
        previous_inventory = initial if time_index == first_time else m.inventory[store_name, previous_time[time_index]]
        return (
            m.inventory[store_name, time_index]
            == previous_inventory + m.store_charge[store_name, time_index] - m.store_discharge[store_name, time_index]
        )

    model.store_inventory_balance = Constraint(model.STORES, model.TIME, rule=inventory_balance_rule)

    def terminal_min_rule(m, store_name):
        return m.inventory[store_name, last_time] >= config.stores[store_name].terminal_min_tonnes

    def terminal_max_rule(m, store_name):
        return m.inventory[store_name, last_time] <= config.stores[store_name].terminal_max_tonnes

    model.store_terminal_min = Constraint(model.STORES, rule=terminal_min_rule)
    model.store_terminal_max = Constraint(model.STORES, rule=terminal_max_rule)

    def carrier_balance_rule(m, carrier_name, time_index):
        process_net = sum(
            config.processes[process_name].conversion.get(carrier_name, 0.0) * m.process_throughput[process_name, time_index]
            for process_name in m.PROCESSES
        )
        source_net = sum(
            m.source_supply[source_name, time_index]
            for source_name in m.SOURCES
            if config.sources[source_name].carrier == carrier_name
        )
        sink_net = sum(
            m.sink_flow[sink_name, time_index]
            for sink_name in m.SINKS
            if config.sinks[sink_name].carrier == carrier_name
        )
        discharge_net = sum(
            m.store_discharge[store_name, time_index]
            for store_name in m.STORES
            if config.stores[store_name].carrier == carrier_name
        )
        charge_net = sum(
            m.store_charge[store_name, time_index]
            for store_name in m.STORES
            if config.stores[store_name].carrier == carrier_name
        )
        return process_net + source_net + discharge_net - charge_net - sink_net == 0.0

    model.carrier_balance = Constraint(model.CARRIERS, model.TIME, rule=carrier_balance_rule)

    if include_production_target:
        def production_target_rule(m):
            delivered = sum(m.sink_flow[config.production_target.sink, time_index] for time_index in m.TIME)
            return delivered >= config.production_target.total_tonnes

        model.production_target = Constraint(rule=production_target_rule)

    def cost_objective_rule(m):
        process_cost = sum(
            config.processes[process_name].operating_cost_per_tonne * m.process_throughput[process_name, time_index]
            for process_name in m.PROCESSES
            for time_index in m.TIME
        )
        source_cost = sum(
            config.sources[source_name].unit_cost_per_tonne * m.source_supply[source_name, time_index]
            for source_name in m.SOURCES
            for time_index in m.TIME
        )
        store_cost = sum(
            config.stores[store_name].throughput_cost_per_tonne
            * (m.store_charge[store_name, time_index] + m.store_discharge[store_name, time_index])
            for store_name in m.STORES
            for time_index in m.TIME
        )
        return process_cost + source_cost + store_cost

    if objective_mode == "cost_min":
        model.total_cost = Objective(rule=cost_objective_rule, sense=minimize)
    elif objective_mode == "max_production":
        def max_production_rule(m):
            return sum(m.sink_flow[config.production_target.sink, time_index] for time_index in m.TIME)

        model.max_production = Objective(rule=max_production_rule, sense=maximize)
    else:
        raise ValueError(f"Unsupported objective_mode={objective_mode}")
    return model


def choose_solver(config: SteelToyConfig):
    for solver_name in config.solver.preferred_solvers:
        solver = SolverFactory(solver_name)
        if solver is not None and solver.available(exception_flag=False):
            return solver_name, solver
    raise RuntimeError(
        "No configured LP solver is available. Tried: "
        + ", ".join(config.solver.preferred_solvers)
    )


def collect_model_stats(model) -> ModelStats:
    variables = list(model.component_data_objects(Var, active=True, descend_into=True))
    constraints = list(model.component_data_objects(Constraint, active=True, descend_into=True))
    binary_count = sum(1 for variable in variables if variable.is_binary())
    return ModelStats(
        variables=len(variables),
        binaries=binary_count,
        constraints=len(constraints),
    )
