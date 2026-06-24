from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
)

from .downstream_scheduling_inputs import DownstreamAssumptions, load_downstream_assumptions
from .model import collect_model_stats


class DownstreamSchedulingBuildError(ValueError):
    """Raised when the governed S2.13 downstream model cannot be built safely."""


@dataclass(frozen=True)
class DownstreamCaseOptions:
    smoke_case_id: str = "c0_base_downstream"
    hsm_unavailable_hours: tuple[int, ...] = ()
    hsm_capacity_multiplier: float = 1.0
    reheater_enabled: bool = True
    require_cold_slab_creation: bool = False
    route_share_mode: str = "fixed"
    bf_bof_share_lower: float | None = None
    bf_bof_share_upper: float | None = None


def _time_set(horizon_hours: int) -> list[int]:
    if horizon_hours <= 0:
        raise DownstreamSchedulingBuildError("horizon_hours must be positive.")
    return list(range(horizon_hours))


def _safe_active_input_periods(horizon_hours: int, *, secondary_delay: int, casting_delay: int) -> set[int]:
    last_input = horizon_hours - 1 - secondary_delay - casting_delay
    return {t for t in range(horizon_hours) if t <= last_input}


def _safe_caster_periods(horizon_hours: int, *, casting_delay: int) -> set[int]:
    return {t for t in range(horizon_hours) if casting_delay <= t <= horizon_hours - 1 - casting_delay}


def _availability_from_unavailable(time_points: Iterable[int], unavailable_hours: Iterable[int]) -> dict[int, int]:
    blocked = {int(t) for t in unavailable_hours}
    return {int(t): 0 if int(t) in blocked else 1 for t in time_points}


def build_downstream_scheduling_model(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    assumptions: DownstreamAssumptions | None = None,
    case_options: DownstreamCaseOptions | None = None,
):
    assumptions = assumptions or load_downstream_assumptions(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
    )
    if assumptions.configuration_id != configuration_id:
        raise DownstreamSchedulingBuildError("Assumption configuration does not match requested configuration.")
    case_options = case_options or DownstreamCaseOptions()
    if assumptions.hot_slab_window_steps < 1:
        raise DownstreamSchedulingBuildError("hot_slab_window_steps must be at least one.")

    time_points = _time_set(horizon_hours)
    last_time = time_points[-1]
    previous = {time_points[idx]: time_points[idx - 1] for idx in range(1, len(time_points))}
    active_secondary = _safe_active_input_periods(
        horizon_hours,
        secondary_delay=assumptions.secondary_delay_steps,
        casting_delay=assumptions.casting_delay_steps,
    )
    active_caster = _safe_caster_periods(horizon_hours, casting_delay=assumptions.casting_delay_steps)
    active_reheater_input = {
        t for t in time_points if t + assumptions.reheating_delay_steps <= last_time
    }
    hsm_availability = _availability_from_unavailable(time_points, case_options.hsm_unavailable_hours)
    reheater_availability = {t: 1 if case_options.reheater_enabled else 0 for t in time_points}

    model = ConcreteModel(name=f"s2_13_downstream_{configuration_id}_{case_options.smoke_case_id}_{horizon_hours}h")
    model.TIME = Set(initialize=time_points, ordered=True)
    model.HOT_AGES = Set(initialize=list(range(assumptions.hot_slab_window_steps)), ordered=True)

    model.bof_liquid_steel_output = Var(model.TIME, domain=NonNegativeReals)
    model.eaf_liquid_steel_output = Var(model.TIME, domain=NonNegativeReals)
    model.secondary_metallurgy_input = Var(model.TIME, domain=NonNegativeReals)
    model.secondary_metallurgy_output = Var(model.TIME, domain=NonNegativeReals)
    model.caster_input = Var(model.TIME, domain=NonNegativeReals)
    model.cast_slab_output = Var(model.TIME, domain=NonNegativeReals)
    model.hot_to_dsp_by_age = Var(model.HOT_AGES, model.TIME, domain=NonNegativeReals)
    model.hot_to_hsm_by_age = Var(model.HOT_AGES, model.TIME, domain=NonNegativeReals)
    model.dsp_hot_slab_input = Var(model.TIME, domain=NonNegativeReals)
    model.dsp_product_output = Var(model.TIME, domain=NonNegativeReals)
    model.hsm_hot_slab_input = Var(model.TIME, domain=NonNegativeReals)
    model.hot_slab_inventory = Var(model.HOT_AGES, model.TIME, domain=NonNegativeReals)
    model.hot_slab_to_cold = Var(model.TIME, domain=NonNegativeReals)
    model.cold_slab_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.reheat_cold_slab_input = Var(model.TIME, domain=NonNegativeReals)
    model.reheated_slab_output = Var(model.TIME, domain=NonNegativeReals)
    model.reheated_slab_queue = Var(model.TIME, domain=NonNegativeReals)
    model.hsm_reheated_slab_input = Var(model.TIME, domain=NonNegativeReals)
    model.hsm_total_slab_input = Var(model.TIME, domain=NonNegativeReals)
    model.hsm_product_output = Var(model.TIME, domain=NonNegativeReals)
    model.final_product_output = Var(model.TIME, domain=NonNegativeReals)
    model.final_product_overproduction = Var(domain=NonNegativeReals)

    model.dsp_on = Var(model.TIME, domain=Binary)
    model.dsp_startup = Var(model.TIME, domain=Binary)
    model.dsp_shutdown = Var(model.TIME, domain=Binary)
    model.reheater_on = Var(model.TIME, domain=Binary)
    model.reheater_startup = Var(model.TIME, domain=Binary)
    model.reheater_shutdown = Var(model.TIME, domain=Binary)
    model.hsm_on = Var(model.TIME, domain=Binary)
    model.hsm_startup = Var(model.TIME, domain=Binary)
    model.hsm_shutdown = Var(model.TIME, domain=Binary)

    model.dsp_throughput_variation = Var(model.TIME, domain=NonNegativeReals)
    model.reheater_throughput_variation = Var(model.TIME, domain=NonNegativeReals)
    model.hsm_throughput_variation = Var(model.TIME, domain=NonNegativeReals)

    def _liquid_to_secondary_rule(m, t):
        return m.secondary_metallurgy_input[t] == m.bof_liquid_steel_output[t] + m.eaf_liquid_steel_output[t]

    model.liquid_steel_to_secondary_metallurgy = Constraint(model.TIME, rule=_liquid_to_secondary_rule)

    model.route_total_liquid_steel_source = Expression(
        expr=sum(model.secondary_metallurgy_input[t] for t in model.TIME)
    )
    model.bof_route_total = Expression(expr=sum(model.bof_liquid_steel_output[t] for t in model.TIME))
    model.eaf_route_total = Expression(expr=sum(model.eaf_liquid_steel_output[t] for t in model.TIME))
    if case_options.route_share_mode == "fixed":
        model.route_bf_bof_share_preservation = Constraint(
            expr=model.bof_route_total == assumptions.bf_bof_share * model.route_total_liquid_steel_source
        )
        model.route_drp_eaf_share_preservation = Constraint(
            expr=model.eaf_route_total == assumptions.drp_eaf_share * model.route_total_liquid_steel_source
        )
    elif case_options.route_share_mode == "endogenous_bounded":
        if case_options.bf_bof_share_lower is None or case_options.bf_bof_share_upper is None:
            raise DownstreamSchedulingBuildError("Endogenous route mode requires BF-BOF lower and upper bounds.")
        if not (0.0 <= case_options.bf_bof_share_lower <= case_options.bf_bof_share_upper <= 1.0):
            raise DownstreamSchedulingBuildError("Endogenous BF-BOF route-share bounds must lie in [0, 1].")
        model.route_bf_bof_share_lower_bound = Constraint(
            expr=model.bof_route_total
            >= case_options.bf_bof_share_lower * model.route_total_liquid_steel_source
        )
        model.route_bf_bof_share_upper_bound = Constraint(
            expr=model.bof_route_total
            <= case_options.bf_bof_share_upper * model.route_total_liquid_steel_source
        )
    else:
        raise DownstreamSchedulingBuildError(f"Unsupported route_share_mode={case_options.route_share_mode!r}.")

    def _secondary_delay_rule(m, t):
        source_t = t - assumptions.secondary_delay_steps
        if source_t < 0:
            return m.secondary_metallurgy_output[t] == 0.0
        return m.secondary_metallurgy_output[t] == assumptions.secondary_yield * m.secondary_metallurgy_input[source_t]

    model.secondary_metallurgy_delay = Constraint(model.TIME, rule=_secondary_delay_rule)

    def _secondary_max_rule(m, t):
        return m.secondary_metallurgy_input[t] <= assumptions.secondary.max_tph * (1 if t in active_secondary else 0)

    def _secondary_min_rule(m, t):
        return m.secondary_metallurgy_input[t] >= assumptions.secondary.min_tph * (1 if t in active_secondary else 0)

    model.secondary_metallurgy_max_throughput = Constraint(model.TIME, rule=_secondary_max_rule)
    model.secondary_metallurgy_min_throughput = Constraint(model.TIME, rule=_secondary_min_rule)

    def _secondary_ramp_up_rule(m, t):
        if t == 0 or t not in active_secondary or previous[t] not in active_secondary:
            return Constraint.Skip
        return m.secondary_metallurgy_input[t] - m.secondary_metallurgy_input[previous[t]] <= assumptions.secondary.ramp_tph

    def _secondary_ramp_down_rule(m, t):
        if t == 0 or t not in active_secondary or previous[t] not in active_secondary:
            return Constraint.Skip
        return m.secondary_metallurgy_input[previous[t]] - m.secondary_metallurgy_input[t] <= assumptions.secondary.ramp_tph

    model.secondary_metallurgy_ramp_up = Constraint(model.TIME, rule=_secondary_ramp_up_rule)
    model.secondary_metallurgy_ramp_down = Constraint(model.TIME, rule=_secondary_ramp_down_rule)

    model.caster_input_link = Constraint(model.TIME, rule=lambda m, t: m.caster_input[t] == m.secondary_metallurgy_output[t])

    def _caster_delay_rule(m, t):
        source_t = t - assumptions.casting_delay_steps
        if source_t < 0:
            return m.cast_slab_output[t] == 0.0
        return m.cast_slab_output[t] == assumptions.casting_yield * m.caster_input[source_t]

    model.casting_delay = Constraint(model.TIME, rule=_caster_delay_rule)

    def _caster_max_rule(m, t):
        return m.caster_input[t] <= assumptions.caster.max_tph * (1 if t in active_caster else 0)

    def _caster_min_rule(m, t):
        return m.caster_input[t] >= assumptions.caster.min_tph * (1 if t in active_caster else 0)

    model.caster_max_throughput = Constraint(model.TIME, rule=_caster_max_rule)
    model.caster_min_throughput = Constraint(model.TIME, rule=_caster_min_rule)

    def _caster_ramp_up_rule(m, t):
        if t == 0 or t not in active_caster or previous[t] not in active_caster:
            return Constraint.Skip
        return m.caster_input[t] - m.caster_input[previous[t]] <= assumptions.caster.ramp_tph

    def _caster_ramp_down_rule(m, t):
        if t == 0 or t not in active_caster or previous[t] not in active_caster:
            return Constraint.Skip
        return m.caster_input[previous[t]] - m.caster_input[t] <= assumptions.caster.ramp_tph

    model.caster_ramp_up = Constraint(model.TIME, rule=_caster_ramp_up_rule)
    model.caster_ramp_down = Constraint(model.TIME, rule=_caster_ramp_down_rule)

    def _hot_available(m, age, t):
        if age == 0:
            return m.cast_slab_output[t]
        if t == 0:
            return assumptions.initial_hot_slab_inventory_t
        return m.hot_slab_inventory[age - 1, previous[t]]

    def _hot_consumption_bound_rule(m, age, t):
        return m.hot_to_dsp_by_age[age, t] + m.hot_to_hsm_by_age[age, t] <= _hot_available(m, age, t)

    model.hot_slab_age_consumption_bound = Constraint(model.HOT_AGES, model.TIME, rule=_hot_consumption_bound_rule)

    def _hot_inventory_rule(m, age, t):
        available = _hot_available(m, age, t)
        used = m.hot_to_dsp_by_age[age, t] + m.hot_to_hsm_by_age[age, t]
        if age == assumptions.hot_slab_window_steps - 1:
            return m.hot_slab_inventory[age, t] == 0.0
        return m.hot_slab_inventory[age, t] == available - used

    model.hot_slab_age_inventory_balance = Constraint(model.HOT_AGES, model.TIME, rule=_hot_inventory_rule)
    model.hot_slab_age_terminal_inventory = Constraint(
        model.HOT_AGES,
        rule=lambda m, age: m.hot_slab_inventory[age, last_time] == assumptions.initial_hot_slab_inventory_t,
    )

    def _hot_to_cold_rule(m, t):
        age = assumptions.hot_slab_window_steps - 1
        available = _hot_available(m, age, t)
        used = m.hot_to_dsp_by_age[age, t] + m.hot_to_hsm_by_age[age, t]
        return m.hot_slab_to_cold[t] == available - used

    model.hot_slab_expiry_to_cold_yard = Constraint(model.TIME, rule=_hot_to_cold_rule)
    model.dsp_hot_input_by_age_link = Constraint(
        model.TIME,
        rule=lambda m, t: m.dsp_hot_slab_input[t] == sum(m.hot_to_dsp_by_age[age, t] for age in m.HOT_AGES),
    )
    model.hsm_hot_input_by_age_link = Constraint(
        model.TIME,
        rule=lambda m, t: m.hsm_hot_slab_input[t] == sum(m.hot_to_hsm_by_age[age, t] for age in m.HOT_AGES),
    )

    def _inventory_balance_rule(m, t):
        prior = assumptions.initial_cold_slab_inventory_t if t == 0 else m.cold_slab_inventory[previous[t]]
        return m.cold_slab_inventory[t] == prior + m.hot_slab_to_cold[t] - m.reheat_cold_slab_input[t]

    model.cold_slab_inventory_balance = Constraint(model.TIME, rule=_inventory_balance_rule)
    model.cold_slab_capacity = Constraint(
        model.TIME,
        rule=lambda m, t: m.cold_slab_inventory[t] <= assumptions.slab_yard_capacity_t,
    )
    model.cold_slab_terminal_inventory = Constraint(
        expr=model.cold_slab_inventory[last_time]
        == assumptions.initial_cold_slab_inventory_t * assumptions.terminal_cold_inventory_ratio
    )

    def _reheated_delay_rule(m, t):
        source_t = t - assumptions.reheating_delay_steps
        if source_t < 0:
            return m.reheated_slab_output[t] == 0.0
        return m.reheated_slab_output[t] == assumptions.reheating_yield * m.reheat_cold_slab_input[source_t]

    model.reheating_delay = Constraint(model.TIME, rule=_reheated_delay_rule)

    def _reheated_queue_rule(m, t):
        prior = assumptions.initial_reheated_queue_t if t == 0 else m.reheated_slab_queue[previous[t]]
        return m.reheated_slab_queue[t] == prior + m.reheated_slab_output[t] - m.hsm_reheated_slab_input[t]

    model.reheated_slab_queue_balance = Constraint(model.TIME, rule=_reheated_queue_rule)
    model.reheated_slab_queue_terminal = Constraint(
        expr=model.reheated_slab_queue[last_time] == assumptions.terminal_reheated_queue_t
    )

    model.hsm_total_slab_input_link = Constraint(
        model.TIME,
        rule=lambda m, t: m.hsm_total_slab_input[t] == m.hsm_hot_slab_input[t] + m.hsm_reheated_slab_input[t],
    )
    model.dsp_output_yield = Constraint(
        model.TIME,
        rule=lambda m, t: m.dsp_product_output[t] == assumptions.dsp_yield * m.dsp_hot_slab_input[t],
    )
    model.hsm_output_yield = Constraint(
        model.TIME,
        rule=lambda m, t: m.hsm_product_output[t] == assumptions.hsm_yield * m.hsm_total_slab_input[t],
    )
    model.final_product_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.final_product_output[t] == m.dsp_product_output[t] + m.hsm_product_output[t],
    )

    def _operating_relation(m, on_var, startup_var, shutdown_var, t):
        previous_on = 0 if t == 0 else on_var[previous[t]]
        return on_var[t] - previous_on == startup_var[t] - shutdown_var[t]

    model.dsp_startup_shutdown_relation = Constraint(
        model.TIME,
        rule=lambda m, t: _operating_relation(m, m.dsp_on, m.dsp_startup, m.dsp_shutdown, t),
    )
    model.reheater_startup_shutdown_relation = Constraint(
        model.TIME,
        rule=lambda m, t: _operating_relation(m, m.reheater_on, m.reheater_startup, m.reheater_shutdown, t),
    )
    model.hsm_startup_shutdown_relation = Constraint(
        model.TIME,
        rule=lambda m, t: _operating_relation(m, m.hsm_on, m.hsm_startup, m.hsm_shutdown, t),
    )

    def _min_up_rule(on_var, startup_var, min_up_steps: int, t):
        if min_up_steps <= 1:
            return Constraint.Skip
        window = [k for k in time_points if t <= k <= min(last_time, t + min_up_steps - 1)]
        return sum(on_var[k] for k in window) >= min_up_steps * startup_var[t] - max(0, t + min_up_steps - 1 - last_time)

    def _min_down_rule(on_var, shutdown_var, min_down_steps: int, t):
        if min_down_steps <= 1:
            return Constraint.Skip
        window = [k for k in time_points if t <= k <= min(last_time, t + min_down_steps - 1)]
        return sum(1 - on_var[k] for k in window) >= min_down_steps * shutdown_var[t] - max(0, t + min_down_steps - 1 - last_time)

    model.dsp_min_up = Constraint(
        model.TIME,
        rule=lambda m, t: _min_up_rule(m.dsp_on, m.dsp_startup, assumptions.dsp.min_up_steps, t),
    )
    model.dsp_min_down = Constraint(
        model.TIME,
        rule=lambda m, t: _min_down_rule(m.dsp_on, m.dsp_shutdown, assumptions.dsp.min_down_steps, t),
    )
    model.reheater_min_up = Constraint(
        model.TIME,
        rule=lambda m, t: _min_up_rule(m.reheater_on, m.reheater_startup, assumptions.reheater.min_up_steps, t),
    )
    model.reheater_min_down = Constraint(
        model.TIME,
        rule=lambda m, t: _min_down_rule(m.reheater_on, m.reheater_shutdown, assumptions.reheater.min_down_steps, t),
    )
    model.hsm_min_up = Constraint(
        model.TIME,
        rule=lambda m, t: _min_up_rule(m.hsm_on, m.hsm_startup, assumptions.hsm.min_up_steps, t),
    )
    model.hsm_min_down = Constraint(
        model.TIME,
        rule=lambda m, t: _min_down_rule(m.hsm_on, m.hsm_shutdown, assumptions.hsm.min_down_steps, t),
    )

    model.dsp_capacity_max = Constraint(
        model.TIME,
        rule=lambda m, t: m.dsp_hot_slab_input[t] <= assumptions.dsp.max_tph * m.dsp_on[t],
    )
    model.dsp_capacity_min_when_on = Constraint(
        model.TIME,
        rule=lambda m, t: m.dsp_hot_slab_input[t] >= assumptions.dsp.min_tph * m.dsp_on[t],
    )
    model.reheater_availability = Constraint(model.TIME, rule=lambda m, t: m.reheater_on[t] <= reheater_availability[t])
    model.reheater_capacity_max = Constraint(
        model.TIME,
        rule=lambda m, t: m.reheat_cold_slab_input[t] <= assumptions.reheater.max_tph * m.reheater_on[t],
    )
    model.reheater_input_completes_within_horizon = Constraint(
        model.TIME,
        rule=lambda m, t: m.reheat_cold_slab_input[t]
        <= assumptions.reheater.max_tph * (1 if t in active_reheater_input else 0),
    )
    model.reheater_capacity_min_when_on = Constraint(
        model.TIME,
        rule=lambda m, t: m.reheat_cold_slab_input[t] >= assumptions.reheater.min_tph * m.reheater_on[t],
    )
    model.hsm_availability = Constraint(model.TIME, rule=lambda m, t: m.hsm_on[t] <= hsm_availability[t])
    model.hsm_capacity_max = Constraint(
        model.TIME,
        rule=lambda m, t: m.hsm_total_slab_input[t]
        <= assumptions.hsm.max_tph * case_options.hsm_capacity_multiplier * hsm_availability[t] * m.hsm_on[t],
    )
    model.hsm_capacity_min_when_on = Constraint(
        model.TIME,
        rule=lambda m, t: m.hsm_total_slab_input[t] >= assumptions.hsm.min_tph * hsm_availability[t] * m.hsm_on[t],
    )

    def _ramp_up_rule(x, startup, envelope, t):
        previous_value = 0.0 if t == 0 else x[previous[t]]
        return x[t] - previous_value <= envelope.ramp_tph + envelope.max_tph * startup[t]

    def _ramp_down_rule(x, shutdown, envelope, t):
        previous_value = 0.0 if t == 0 else x[previous[t]]
        return previous_value - x[t] <= envelope.ramp_tph + envelope.max_tph * shutdown[t]

    model.dsp_ramp_up = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_up_rule(m.dsp_hot_slab_input, m.dsp_startup, assumptions.dsp, t),
    )
    model.dsp_ramp_down = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_down_rule(m.dsp_hot_slab_input, m.dsp_shutdown, assumptions.dsp, t),
    )
    model.reheater_ramp_up = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_up_rule(m.reheat_cold_slab_input, m.reheater_startup, assumptions.reheater, t),
    )
    model.reheater_ramp_down = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_down_rule(m.reheat_cold_slab_input, m.reheater_shutdown, assumptions.reheater, t),
    )
    model.hsm_ramp_up = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_up_rule(m.hsm_total_slab_input, m.hsm_startup, assumptions.hsm, t),
    )
    model.hsm_ramp_down = Constraint(
        model.TIME,
        rule=lambda m, t: _ramp_down_rule(m.hsm_total_slab_input, m.hsm_shutdown, assumptions.hsm, t),
    )

    def _variation_rule(x, variation, t):
        previous_value = 0.0 if t == 0 else x[previous[t]]
        return (
            variation[t] >= x[t] - previous_value,
            variation[t] >= previous_value - x[t],
        )

    model.dsp_variation_up = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.dsp_hot_slab_input, m.dsp_throughput_variation, t)[0],
    )
    model.dsp_variation_down = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.dsp_hot_slab_input, m.dsp_throughput_variation, t)[1],
    )
    model.reheater_variation_up = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.reheat_cold_slab_input, m.reheater_throughput_variation, t)[0],
    )
    model.reheater_variation_down = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.reheat_cold_slab_input, m.reheater_throughput_variation, t)[1],
    )
    model.hsm_variation_up = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.hsm_total_slab_input, m.hsm_throughput_variation, t)[0],
    )
    model.hsm_variation_down = Constraint(
        model.TIME,
        rule=lambda m, t: _variation_rule(m.hsm_total_slab_input, m.hsm_throughput_variation, t)[1],
    )

    model.horizon_final_product_output = Expression(expr=sum(model.final_product_output[t] for t in model.TIME))
    model.horizon_liquid_steel_input = Expression(expr=sum(model.secondary_metallurgy_input[t] for t in model.TIME))
    model.horizon_dsp_output = Expression(expr=sum(model.dsp_product_output[t] for t in model.TIME))
    model.horizon_hsm_output = Expression(expr=sum(model.hsm_product_output[t] for t in model.TIME))
    model.horizon_hot_charge_tonnage = Expression(
        expr=sum(model.dsp_hot_slab_input[t] + model.hsm_hot_slab_input[t] for t in model.TIME)
    )
    model.horizon_reheated_tonnage = Expression(expr=sum(model.hsm_reheated_slab_input[t] for t in model.TIME))
    model.horizon_hot_slab_to_cold = Expression(expr=sum(model.hot_slab_to_cold[t] for t in model.TIME))
    model.horizon_startup_count = Expression(
        expr=sum(
            model.dsp_startup[t] + model.reheater_startup[t] + model.hsm_startup[t]
            for t in model.TIME
        )
    )

    model.final_product_target = Constraint(expr=model.horizon_final_product_output >= assumptions.final_product_target_t)
    model.final_product_overproduction_accounting = Constraint(
        expr=model.final_product_overproduction
        == model.horizon_final_product_output - assumptions.final_product_target_t
    )
    model.dsp_horizon_share_target = Constraint(
        expr=model.horizon_dsp_output == assumptions.dsp_share * assumptions.final_product_target_t
    )
    model.hsm_horizon_share_floor = Constraint(
        expr=model.horizon_hsm_output >= (1.0 - assumptions.dsp_share) * assumptions.final_product_target_t
    )

    if case_options.require_cold_slab_creation:
        model.required_cold_slab_creation = Constraint(
            expr=model.horizon_hot_slab_to_cold >= assumptions.q_avg_hsm_tph
        )

    model.continuous_casting_electricity_driver = Expression(expr=sum(model.caster_input[t] for t in model.TIME))
    model.dsp_electricity_driver = Expression(expr=sum(model.dsp_hot_slab_input[t] for t in model.TIME))
    model.slab_handling_electricity_driver = Expression(expr=sum(model.hot_slab_to_cold[t] for t in model.TIME))
    model.reheating_fuel_heat_driver = Expression(expr=sum(model.reheat_cold_slab_input[t] for t in model.TIME))
    model.hsm_electricity_driver = Expression(expr=sum(model.hsm_total_slab_input[t] for t in model.TIME))
    model.hot_charge_tonnage_driver = Expression(expr=model.horizon_hot_charge_tonnage)
    model.cold_charge_reheated_tonnage_driver = Expression(expr=model.horizon_reheated_tonnage)
    model.final_hot_rolled_product_output_driver = Expression(expr=model.horizon_final_product_output)
    model.wag_compatible_reheating_fuel_demand_hook = Expression(expr=sum(model.reheat_cold_slab_input[t] for t in model.TIME))

    model.primary_objective = Objective(expr=model.final_product_overproduction, sense=minimize)
    model.secondary_objective = Objective(
        expr=(
            assumptions.secondary_weight_cold_slab_creation * model.horizon_hot_slab_to_cold
            + assumptions.secondary_weight_reheated_tonnage * model.horizon_reheated_tonnage
            + assumptions.secondary_weight_startup * model.horizon_startup_count
            + assumptions.secondary_weight_throughput_variation
            * sum(
                model.dsp_throughput_variation[t]
                + model.reheater_throughput_variation[t]
                + model.hsm_throughput_variation[t]
                for t in model.TIME
            )
        ),
        sense=minimize,
    )
    model.secondary_objective.deactivate()

    model.s2_13_assumptions = assumptions
    model.s2_13_case_options = case_options
    model.s2_13_metadata = {
        "scope": "S2.13 downstream scheduling extension",
        "configuration_id": configuration_id,
        "horizon_hours": horizon_hours,
        "assumption_set_id": assumptions.assumption_set_id,
        "smoke_case_id": case_options.smoke_case_id,
        "final_product_target_t": assumptions.final_product_target_t,
        "bf_bof_share": assumptions.bf_bof_share,
        "drp_eaf_share": assumptions.drp_eaf_share,
        "dsp_share": assumptions.dsp_share,
        "shortfall_slack_active": False,
        "market_logic_active": False,
        "thesis_usability": False,
        "source_boundary": "re_frozen_S2_wrapper_not_generated_run_folder",
    }
    model.s2_13_model_stats = collect_model_stats(model)
    return model
