from __future__ import annotations

import copy
import csv
import json
import math
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import Binary, ConcreteModel, Objective, RangeSet, Var, value
from pyomo.repn import generate_standard_repn


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (  # noqa: E402
    C1_CONFIGURATION,
)
from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (  # noqa: E402
    Phase6BError,
    SteelRollingState,
    _represented_cost_expression,
)
from steel.s4_4c6_deterministic_temporal_repair import (  # noqa: E402
    ANNUAL_EAF_ROUTE_T,
    CALENDAR_CONTRACT_VERSION,
    CONTINUOUS_ASSETS,
    HeatCountCertificationCase,
    OBJECTIVE_MODE,
    ScalarObjectiveComponents,
    ScalarSolveResult,
    TEMPORAL_CONTRACT_VERSION,
    TemporalPhysicalInfeasibility,
    TemporalRepairError,
    _calendar_day_context,
    _calendar_year_inventory_terminal_targets,
    _annual_calendar_contract,
    _annual_heat_schedule,
    _annual_progress_corridor_execution_bounds,
    _annual_recoverable_execution_bounds,
    _eaf_maintenance_intervals_for_horizon,
    _executed_operational_signature,
    _fix_executed_solution_prefix,
    _last_accepted_annual_values,
    _phase5e_static_anchor_gate,
    _state_numeric_drift,
    add_execution_boundary_carry_witness,
    add_annual_upper_recoverability,
    add_week_heat_contract,
    administrative_carbon_balance_rows,
    annual_anchor_delta_rows,
    annual_operational_anchor_rows,
    build_scalar_objective_components,
    build_temporal_model,
    canonicalize_state_rate,
    cumulative_eaf_target_taps,
    dynamic_daily_heat_bounds,
    initial_temporal_state,
    heat_count_case_metadata,
    heat_count_expansion_order,
    load_temporal_repair_config,
    must_run_bof_conflict_diagnostic,
    objective_variable_names,
    physical_day_heat_cap,
    prepare_temporal_context,
    quota_period_target_taps,
    reachable_eaf_carry_in_states,
    recursive_coke_hot_iron_conflict_diagnostic,
    solve_scalar_operational_model,
    validate_temporal_state,
)
import steel.s4_4c6_deterministic_temporal_repair as temporal_module  # noqa: E402


@pytest.fixture(scope="module")
def temporal_fixture():
    config = load_temporal_repair_config()
    context = prepare_temporal_context(config)
    state = initial_temporal_state(config)
    model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=20,
        upper_taps=32,
    )
    return config, context, state, model


def test_d5_bounded_oracle_and_scaled_state_tolerances_are_explicit():
    config = load_temporal_repair_config()
    repair = config["deterministic_temporal_repair"]
    assert repair["d5_strict_time_limit_seconds"] == 120
    assert repair["d5_strict_relative_gap"] == pytest.approx(0.001)
    assert repair["d5_strict_absolute_gap_eur"] == pytest.approx(1.0)
    assert repair["d5_rate_tolerance_t_h"] == pytest.approx(0.1)
    assert repair["d5_inventory_tolerance_t"] == pytest.approx(0.1)


def test_c1_downstream_uses_shared_hourly_holds_and_dsp_envelope(
    temporal_fixture,
):
    config, _, _, model = temporal_fixture
    downstream = config["deterministic_temporal_repair"]["plant_dynamics"][
        "downstream_temporal_contract"
    ]
    assert model.hsm_temporal_block_steps == 4
    assert model.dsp_temporal_block_steps == 4
    assert len(model.hsm_temporal_block_holds) == 144
    assert len(model.hsm_temporal_step_constraints) == 96
    assert len(model.dsp_temporal_block_holds) == 144
    assert len(model.dsp_temporal_output_cap) == 192
    assert hasattr(model, "eaf_slab_inventory")
    assert hasattr(model, "eaf_slab_balance")
    assert hasattr(model, "shared_cold_slab_capacity")
    assert not model.cold_slab_terminal.active
    assert not model.eaf_slab_terminal.active
    assert downstream["dsp_final_product_max_t_h"] == pytest.approx(
        1_500_000.0 / 8_760.0
    )


def test_state_rate_roundoff_is_snapped_without_widening_bounds():
    assert canonicalize_state_rate(349.999995, 350.0, 550.0) == 350.0
    assert canonicalize_state_rate(550.000005, 350.0, 550.0) == 550.0
    assert canonicalize_state_rate(349.999, 350.0, 550.0) == pytest.approx(349.999)


def test_d5_operational_signature_ignores_heat_timing_but_preserves_counts():
    def build(starts: list[int]) -> ConcreteModel:
        model = ConcreteModel()
        model.time_step_hours = 0.25
        model.T = RangeSet(0, 7)
        model.eaf_heat_start = Var(model.T, domain=Binary)
        model.eaf_heat_tap = Var(model.T, domain=Binary)
        for interval, start in enumerate(starts):
            model.eaf_heat_start[interval].set_value(start)
            model.eaf_heat_tap[interval].set_value(
                starts[interval - 2] if interval >= 2 else 0
            )
        return model

    early = build([1, 0, 0, 1, 0, 0, 0, 0])
    late = build([0, 1, 0, 0, 1, 0, 0, 0])
    assert _executed_operational_signature(
        early, 8
    ) == _executed_operational_signature(late, 8)


def test_d5_state_drift_uses_physical_scale_not_solver_epsilon():
    config = load_temporal_repair_config()
    reference = initial_temporal_state(config)
    within = replace(
        reference,
        pefa_last_output_t_h=float(reference.pefa_last_output_t_h) + 0.05,
        pellet_inventory_t=float(reference.pellet_inventory_t) + 0.05,
    )
    outside = replace(
        reference,
        pefa_last_output_t_h=float(reference.pefa_last_output_t_h) + 0.11,
    )
    assert _state_numeric_drift(reference, within, config) == {}
    assert "pefa_last_output_t_h" in _state_numeric_drift(
        reference, outside, config
    )


def test_cumulative_eaf_rounding_and_week_targets_are_exact():
    assert math.isclose(ANNUAL_EAF_ROUTE_T, 3_232_012.260)
    assert cumulative_eaf_target_taps(0) == 0
    assert quota_period_target_taps(0) == 191
    assert {quota_period_target_taps(index) for index in range(8)} == {190, 191}


def test_annual_calendar_is_dst_exact_and_fully_maintenance_excluded():
    config = load_temporal_repair_config()
    assert config["deterministic_temporal_repair"]["causal_flat_year"][
        "solver_feasibility_tolerance"
    ] == pytest.approx(1e-9)
    calendar, major_dates = _annual_calendar_contract(config)
    assert len(calendar) == 365
    assert sum(day["day_length_hours"] for day in calendar) == 8760
    assert {day["day_length_hours"] for day in calendar} == {23, 24, 25}
    assert not major_dates
    assert all(not day["eaf_major_outage"] for day in calendar)
    assert all(not day["eaf_weekly_outage"] for day in calendar)
    assert all(day["eaf_unavailable_steps"] == 0 for day in calendar)
    assert all(
        day["eaf_available_steps"] == day["execution_steps"] for day in calendar
    )
    target = cumulative_eaf_target_taps(8760)
    schedule = _annual_heat_schedule(
        calendar,
        annual_target_taps=target,
        daily_tolerance=4,
        quota_period_days=7,
        quota_neutral_upper_cap=29,
    )
    assert sum(item["target"] for item in schedule) == target
    assert all(item["target"] <= item["physical_cap"] for item in schedule)
    normal = schedule[0]
    assert normal["lower"] == normal["target"] - 4
    assert normal["upper"] <= 29
    assert normal["upper"] - normal["lower"] > 2


def test_all_annual_execution_days_and_physical_tails_have_zero_maintenance():
    config = load_temporal_repair_config()
    calendar, major_dates = _annual_calendar_contract(config)
    assert all(
        _eaf_maintenance_intervals_for_horizon(
            start_utc=day["start_utc"],
            horizon_steps=192,
            major_dates=major_dates,
            timezone_name="Europe/Amsterdam",
        )
        == ()
        for day in calendar
    )


def test_maintenance_excluded_heat_schedule_uses_calendar_duration_only():
    config = load_temporal_repair_config()
    calendar, major_dates = _annual_calendar_contract(config)
    assert not major_dates
    assert sum(day["day_length_hours"] for day in calendar) == 8760
    assert not any(day["eaf_major_outage"] for day in calendar)
    assert not any(day["eaf_weekly_outage"] for day in calendar)
    target = cumulative_eaf_target_taps(8760)
    schedule = _annual_heat_schedule(
        calendar,
        annual_target_taps=target,
        daily_tolerance=1,
        quota_period_days=7,
        quota_neutral_upper_cap=int(
            config["deterministic_temporal_repair"]["causal_flat_year"][
                "routine_quota_normal_day_upper_taps"
            ]
        ),
    )
    assert sum(item["target"] for item in schedule) == target
    assert sum(item["quota_period_boundary"] for item in schedule) == 53
    assert schedule[-1]["quota_period_boundary"] == 1
    assert schedule[-1]["quota_period_target"] == 28
    full_period_targets = {
        item["quota_period_target"]
        for item in schedule[:-1]
        if item["quota_period_boundary"]
    }
    assert full_period_targets.issubset({189, 190, 191, 192})
    assert all(item["upper"] - item["lower"] <= 8 for item in schedule)
    assert all(item["lower"] <= item["upper"] for item in schedule)
    assert all(item["upper"] <= 29 for item in schedule)
    for period_index in range(53):
        period = [
            item
            for item in schedule
            if item["quota_period_index"] == period_index
        ]
        assert period[-1]["quota_period_cumulative_target"] == period[-1][
            "quota_period_target"
        ]


def test_annual_route_policy_replaces_daily_reference_with_executed_recoverability(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    bounds = {
        "bof_liquid_steel": (8_000.0, 10_000.0),
        "hsm_final_output": (12_000.0, 17_000.0),
        "dsp_final_output": (3_000.0, 5_000.0),
        "imported_slab": (1_000.0, 2_000.0),
    }
    model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=29,
        final_product_execution_bounds_t=(15_000.0, 22_000.0),
        route_reference_policy="annual_recoverable_calendar",
        executed_route_bounds_t=bounds,
    )
    assert model.annual_route_reference_status == (
        "same_annual_route_volumes_calendar_recoverable"
    )
    assert len(model.annual_executed_route_bounds) == 2 * len(bounds)
    assert not hasattr(model, "c1_reference_bof_liquid_steel_lower")
    assert not model.dri_terminal_equality.active
    assert model.temporal_dri_tail_state_policy == (
        "capacity_bounded_rolling_state_no_artificial_tail_cycle"
    )
    assert temporal_fixture[3].dri_terminal_equality.active


def test_inventory_closure_is_only_applied_at_true_calendar_year_boundary():
    targets = {"dri_inventory": 0.0, "coke_inventory": 180.0}
    assert (
        _calendar_year_inventory_terminal_targets(
            targets, final_day=True, full_year=False
        )
        is None
    )
    assert (
        _calendar_year_inventory_terminal_targets(
            targets, final_day=False, full_year=True
        )
        is None
    )
    assert _calendar_year_inventory_terminal_targets(
        targets, final_day=True, full_year=True
    ) == targets


def test_annual_recoverability_does_not_impose_a_daily_central_route_target():
    assert _annual_recoverable_execution_bounds(
        terminal_lower_t=1_000.0,
        terminal_upper_t=1_100.0,
        completed_t=200.0,
        future_physical_max_t=900.0,
    ) == (0.0, 900.0)
    assert _annual_recoverable_execution_bounds(
        terminal_lower_t=1_000.0,
        terminal_upper_t=1_100.0,
        completed_t=200.0,
        future_physical_max_t=700.0,
    ) == (100.0, 900.0)
    # The day-358 diagnostic needs at least 4,109.589 t DSP output. Terminal
    # recoverability leaves the real annual route headroom available instead
    # of imposing the former artificial 4,059.101-t daily schedule cap.
    assert _annual_recoverable_execution_bounds(
        terminal_lower_t=1_439_196.429,
        terminal_upper_t=1_453_660.714,
        completed_t=1_418_741.184837338,
        future_physical_max_t=28_767.12328767123,
    ) == pytest.approx((0.0, 34_919.52916266187))


def test_annual_progress_corridor_allows_one_physical_tail_of_timing_flexibility():
    assert _annual_progress_corridor_execution_bounds(
        planned_cumulative_t=500.0,
        physical_tail_corridor_t=100.0,
        terminal_lower_t=1_000.0,
        terminal_upper_t=1_100.0,
        completed_t=450.0,
        future_physical_max_t=900.0,
    ) == (0.0, 150.0)
    # The helper defaults to a complete physical tail.  The annual runner may
    # use a shorter executed-state lead, but its scheduling guard must then
    # remain above the output required by hard plant and product constraints.
    assert _annual_progress_corridor_execution_bounds(
        planned_cumulative_t=1_418_691.6969510573,
        physical_tail_corridor_t=8_219.17808219178,
        terminal_lower_t=1_439_196.429,
        terminal_upper_t=1_453_660.714,
        completed_t=1_418_741.184837338,
        future_physical_max_t=28_767.12328767123,
    )[1] > 4_109.589041095771
    assert _annual_progress_corridor_execution_bounds(
        planned_cumulative_t=500.0,
        physical_tail_corridor_t=100.0,
        executed_lead_corridor_t=50.0,
        terminal_lower_t=1_000.0,
        terminal_upper_t=1_100.0,
        completed_t=450.0,
        future_physical_max_t=900.0,
    ) == (0.0, 100.0)


def test_annual_day_359_upper_reserves_mandatory_future_minimum():
    lower, upper = _annual_recoverable_execution_bounds(
        terminal_lower_t=1_439_196.429,
        terminal_upper_t=1_453_660.714,
        completed_t=1_426_909.8751548252,
        future_physical_max_t=24_657.53424657534,
        mandatory_future_minimum_t=24_657.53424657534,
    )
    assert lower == 0.0
    assert upper == pytest.approx(2_093.304598599417)


def test_annual_upper_recoverability_covers_every_product_and_route_metric(
    temporal_fixture,
):
    _, context, _, model = temporal_fixture
    metrics = {
        "final_product",
        "bof_liquid_steel",
        "hsm_final_output",
        "dsp_final_output",
        "imported_slab",
    }
    add_annual_upper_recoverability(
        model,
        execution_steps=context.time_grid.execution_steps,
        hsm_final_t_per_t_slab=float(
            context.c1_reference_routing["hsm_final_t_per_t_slab"]
        ),
        terminal_bounds_t={metric: (1_000.0, 2_000.0) for metric in metrics},
        completed_t={metric: 100.0 for metric in metrics},
        future_physical_max_t={metric: 10_000.0 for metric in metrics},
    )
    assert set(model.ANNUAL_UPPER_RECOVERABILITY_METRICS) == metrics
    assert len(model.annual_upper_recoverability) == 5
    assert len(model.annual_own_lower_future_minimum) == 5
    assert model.annual_upper_recoverability_formula == (
        "upper_today=annual_upper-cumulative_completed-mandatory_future_minimum"
    )


def test_annual_hard_inventory_terminal_uses_existing_dri_carry_semantics(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=28,
        week_boundary=True,
        route_reference_policy="annual_recoverable_calendar",
        final_product_execution_bounds_t=(18_000.0, 19_000.0),
        execution_inventory_terminal_targets_t={
            "dri_inventory": 0.0,
            "coke_inventory": 180.0,
        },
    )
    assert model.annual_execution_dri_terminal_index == 94
    assert model.annual_execution_inventory_terminal_status == (
        "hard_calendar_year_closure_with_last_quarter_dri_carry"
    )


def test_day_caps_follow_occupancy_and_carry_in():
    assert physical_day_heat_cap(96) == 32
    assert physical_day_heat_cap(96, initial_start_lag1=1) == 32
    assert physical_day_heat_cap(96, initial_start_lag2=1) == 32
    assert physical_day_heat_cap(92) == 30
    assert physical_day_heat_cap(100) == 33
    assert physical_day_heat_cap(100, initial_start_lag2=1) == 34


def test_fixed_count_diagnostic_order_has_nonblocking_core_prefix():
    assert heat_count_expansion_order() == (
        27,
        26,
        28,
        25,
        29,
        24,
        30,
        23,
        31,
        22,
        32,
        21,
        20,
    )
    assert heat_count_expansion_order()[:3] == (27, 26, 28)
    assert 30 not in heat_count_expansion_order()[:3]


def test_feasibility_timeout_without_incumbent_is_unknown_and_has_no_iis(
    monkeypatch,
):
    class TimeoutSolver:
        def solve(self, model, **kwargs):
            del model, kwargs
            return SimpleNamespace(
                solver=SimpleNamespace(
                    status="ok",
                    termination_condition="maxTimeLimit",
                ),
                problem=[],
                solution=[],
            )

    monkeypatch.setattr(
        temporal_module,
        "_solver",
        lambda *args, **kwargs: TimeoutSolver(),
    )
    model = ConcreteModel()
    model.executed_eaf_taps = Var(initialize=0.0)
    model.rolling_production_progress_deviation_t = Var(initialize=0.0)
    record = temporal_module._solve_zero_objective_feasibility(
        model,
        load_temporal_repair_config(),
        run_case="timeout_without_incumbent",
        time_limit_seconds=60.0,
    )
    assert not record["feasible_incumbent"]
    assert record["feasibility_status"] == "unknown"
    assert record["iis_status"] == "not_applicable"
    assert record["time_limit_seconds"] == pytest.approx(60.0)


def test_adjacent_count_warm_start_copies_like_named_variable_values():
    source = ConcreteModel()
    source.x = Var((0, 1), initialize={0: 2.0, 1: 3.0})
    target = ConcreteModel()
    target.x = Var((0, 1), initialize=0.0)
    copied = temporal_module._copy_adjacent_warm_start(source, target)
    assert copied == 2
    assert value(target.x[0]) == pytest.approx(2.0)
    assert value(target.x[1]) == pytest.approx(3.0)


def test_fixed_count_certificate_identity_is_stateful_and_records_resources(
    temporal_fixture,
):
    config, _, state, model = temporal_fixture
    cases = (
        HeatCountCertificationCase(
            "normal_zero_carry_27",
            27,
            state,
            24,
            remaining_quota_taps=191,
        ),
        HeatCountCertificationCase(
            "normal_lag1_27",
            27,
            replace(state, eaf_start_lag1=1),
            24,
            remaining_quota_taps=164,
        ),
        HeatCountCertificationCase(
            "short_day_zero_carry_27",
            27,
            state,
            23,
            remaining_quota_taps=191,
            physical_horizon_hours=72,
        ),
    )
    metadata = [heat_count_case_metadata(case, config) for case in cases]
    identities = {
        (
            row["fixed_count"],
            row["state_sha256"],
            row["calendar_day_length_hours"],
            row["carry_in_lag1"],
            row["carry_in_lag2"],
            row["remaining_week_taps"],
            row["physical_tail_hours"],
        )
        for row in metadata
    }
    assert len(identities) == len(cases)
    assert all(row["remaining_site_scrap_cap_t"] > 0.0 for row in metadata)
    assert model.temporal_beginning_inventories_t
    assert set(model.temporal_beginning_inventories_t) == {
        "coke_store_initial_t",
        "sinter_store_initial_t",
        "hot_iron_store_initial_t",
        "cold_slab_store_initial_t",
        "dri_buffer_initial_t",
    }


def test_reachable_carry_states_and_dst_contexts_are_explicit(temporal_fixture):
    config, context, state, _ = temporal_fixture
    carry_states = reachable_eaf_carry_in_states(state)
    assert {
        (item.eaf_start_lag1, item.eaf_start_lag2) for item in carry_states
    } == {(0, 0), (1, 0), (0, 1)}
    witness_model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=28,
    )
    add_execution_boundary_carry_witness(
        witness_model,
        execution_steps=96,
        lag1=1,
        lag2=0,
    )
    assert value(witness_model.temporal_carry_witness_lag1.lower) == 1.0
    assert value(witness_model.temporal_carry_witness_lag2.lower) == 0.0
    assert tuple(
        variable.name
        for variable in identify_variables(
            witness_model.temporal_carry_witness_lag1.body
        )
    ) == ("eaf_heat_start[95]",)
    assert tuple(
        variable.name
        for variable in identify_variables(
            witness_model.temporal_carry_witness_lag2.body
        )
    ) == ("eaf_heat_start[94]",)
    for hours, steps, cap in ((23, 92, 30), (25, 100, 33)):
        day_context = _calendar_day_context(
            context,
            calendar_day_length_hours=hours,
            physical_horizon_hours=48,
        )
        assert day_context.time_grid.execution_steps == steps
        assert day_context.time_grid.horizon_steps == 192
        model = build_temporal_model(
            day_context,
            state,
            config,
            lower_taps=20,
            upper_taps=cap,
        )
        assert model.eaf_daily_upper_taps == cap
        assert len(model.TIME) == 192


def test_longer_tail_extension_fixes_only_the_executed_solution_prefix():
    source = ConcreteModel()
    source.time_step_hours = 0.25
    source.x = Var(range(4))
    source.asset_day_on = Var(range(2))
    target = ConcreteModel()
    target.time_step_hours = 0.25
    target.x = Var(range(6))
    target.asset_day_on = Var(range(3))
    for index, expected in enumerate((1.0, 2.0, 3.0, 4.0)):
        source.x[index].set_value(expected)
    source.asset_day_on[0].set_value(1.0)
    source.asset_day_on[1].set_value(0.0)
    fixed = _fix_executed_solution_prefix(source, target, execution_steps=2)
    assert fixed == 3
    assert target.x[0].fixed and value(target.x[0]) == pytest.approx(1.0)
    assert target.x[1].fixed and value(target.x[1]) == pytest.approx(2.0)
    assert not target.x[2].fixed
    assert not target.x[3].fixed
    assert target.asset_day_on[0].fixed
    assert not target.asset_day_on[1].fixed


def test_dynamic_heat_bounds_make_last_day_exact():
    assert dynamic_daily_heat_bounds(
        remaining_taps=28,
        today_lower=20,
        today_upper=32,
        future_lower_bounds=(),
        future_upper_bounds=(),
    ) == (28, 28)
    assert dynamic_daily_heat_bounds(
        remaining_taps=191,
        today_lower=20,
        today_upper=32,
        future_lower_bounds=(20,) * 6,
        future_upper_bounds=(32,) * 6,
    ) == (20, 32)


def test_v6_rejects_old_checkpoint_snapshot():
    old = SteelRollingState("old", C1_CONFIGURATION).snapshot()
    with pytest.raises(Phase6BError, match="temporal contract mismatch"):
        SteelRollingState.from_snapshot(
            old,
            required_temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        )


def test_v6_rejects_old_maintenance_calendar_and_roundtrips_current_contract():
    state = SteelRollingState(
        "direction_roundtrip",
        C1_CONFIGURATION,
        temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version="old_weekly_maintenance_calendar",
        sifa_trend_direction="up",
        sifa_trend_cooldown_intervals=5,
    )
    with pytest.raises(Phase6BError, match="calendar contract mismatch"):
        SteelRollingState.from_snapshot(
            state.snapshot(),
            required_temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
            required_calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        )
    state.calendar_contract_version = CALENDAR_CONTRACT_VERSION
    restored = SteelRollingState.from_snapshot(
        state.snapshot(),
        required_temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        required_calendar_contract_version=CALENDAR_CONTRACT_VERSION,
    )
    assert restored.sifa_trend_direction == "up"
    assert restored.sifa_trend_cooldown_intervals == 5


def test_upstream_development_dynamics_and_pellet_bus_are_central_and_unit_correct(
    temporal_fixture,
):
    config, context, state, model = temporal_fixture
    dynamics = config["deterministic_temporal_repair"]["plant_dynamics"]
    assert model.c1_temporal_plant_dynamics_status == (
        "user_authorized_development_policy_not_site_truth"
    )
    assert model.sifa_ramp_t_h_per_qh == pytest.approx(6.265638)
    assert model.sifa_minimum_direction_intervals == 8
    assert model.bf6_setpoint_block_steps == 4
    assert model.bf6_maximum_step_t_h == pytest.approx(2.94819)
    assert model.kgf1_setpoint_block_steps == 16
    assert model.kgf1_maximum_step_t_h == pytest.approx(2.873348)
    assert model.drp_temporal_setpoint_block_steps == 4
    assert model.drp_temporal_maximum_step_t_h == pytest.approx(12.5)
    assert model.pefa_setpoint_block_steps == 16
    assert model.pefa_maximum_step_t_h == pytest.approx(7.574881)
    assert model.pefa_price_response_policy == (
        "bounded_endogenous_response_via_closed_fired_pellet_bus"
    )
    assert model.kgf1_anchor_role == (
        "validation_only_mer_annual_reference_physical_coke_balance_drives_output"
    )
    assert model.kgf1_anchor_constraints_active is False
    assert not hasattr(model, "kgf1_execution_route_anchor")
    assert len(model.pellet_balance) == 192
    assert len(model.bf6_setpoint_holds) == 144
    assert len(model.kgf1_setpoint_holds) == 180
    assert len(model.drp_temporal_setpoint_holds) == 144
    assert len(model.pefa_setpoint_holds) == 180
    assert not hasattr(model, "downstream_block_sensitivity_constraints")
    assert state.pefa_last_output_t_h == pytest.approx(541.0629)
    assert state.pellet_inventory_t == pytest.approx(50_000.0)

    normalized = dynamics["normalized_capacity_contract"]
    assert normalized["price_response_not_used_for_calibration"] is True
    assert model.normalized_capacity_price_response_used_for_calibration is False
    assert len(model.normalized_capacity_envelope_constraints) == 2 * 4 * 192

    assert model.pellet_origin_ledger_status.startswith(
        "physical_origin_conservation"
    )
    assert value(model.external_bf_pellets_to_bf_t[0]) == pytest.approx(0.0)
    assert value(model.external_dr_pellets_to_drp_t[0]) == pytest.approx(
        200_000.0 / 8_760.0 * 0.25
    )
    assert {
        flow["flow_id"]: flow["model_component_attribute"]
        for flow in context.cost_flows
        if "PELLET" in str(flow["flow_id"])
    }["C1_MAT_DRP_PELLETS"] == "external_dr_pellets_to_drp_t"

    pellet_repn = generate_standard_repn(model.pellet_balance[0].body)
    pellet_coefficients = {
        variable.name: coefficient
        for variable, coefficient in zip(
            pellet_repn.linear_vars, pellet_repn.linear_coefs
        )
    }
    assert pellet_coefficients["pefa_pellet_output_t[0]"] == pytest.approx(-1.0)
    assert pellet_coefficients[
        "internal_pefa_pellets_to_bf_t[0]"
    ] == pytest.approx(1.0)
    assert pellet_coefficients[
        "internal_pefa_pellets_to_drp_t[0]"
    ] == pytest.approx(1.0)
    drp_origin_repn = generate_standard_repn(
        model.pellet_drp_origin_balance[0].body
    )
    drp_origin_coefficients = {
        variable.name: coefficient
        for variable, coefficient in zip(
            drp_origin_repn.linear_vars, drp_origin_repn.linear_coefs
        )
    }
    assert drp_origin_coefficients["drp_pellet_input[0]"] == pytest.approx(1.0)
    assert drp_origin_coefficients[
        "internal_pefa_pellets_to_drp_t[0]"
    ] == pytest.approx(-1.0)
    assert not model.pellet_terminal.active

    pefa_electricity_repn = generate_standard_repn(
        model.pefa_electricity_mwh[0].expr
    )
    assert pefa_electricity_repn.linear_coefs == pytest.approx((0.0213,))

    model.sintering_plant[0].set_value(
        state.last_continuous_rate_t_h["sintering_plant"]
        * context.time_grid.time_step_hours
    )
    model.sifa_rate_increase_t[0].set_value(0.0)
    model.sifa_rate_decrease_t[0].set_value(0.0)
    model.sifa_up_direction[0].set_value(0.0)
    model.sifa_down_direction[0].set_value(0.0)
    assert value(model.sifa_rate_change_identity[0].body) == pytest.approx(0.0)
    assert dynamics["sifa"]["ramp_fraction_of_reference_per_qh"] == pytest.approx(
        0.025
    )


def test_carried_sifa_direction_forbids_early_reversal(temporal_fixture):
    config, context, state, _ = temporal_fixture
    carried = replace(
        state,
        sifa_trend_direction="up",
        sifa_trend_cooldown_intervals=3,
    )
    model = build_temporal_model(
        context,
        carried,
        config,
        lower_taps=26,
        upper_taps=28,
    )
    assert all(model.sifa_down_direction[q].fixed for q in range(3))
    assert all(value(model.sifa_down_direction[q]) == 0.0 for q in range(3))
    assert not model.sifa_down_direction[3].fixed


def test_downstream_blocks_remain_explicit_offline_sensitivity(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    sensitivity = copy.deepcopy(config)
    sensitivity["deterministic_temporal_repair"]["plant_dynamics"][
        "downstream_block_sensitivity"
    ]["active"] = True
    model = build_temporal_model(
        context,
        state,
        sensitivity,
        lower_taps=26,
        upper_taps=28,
    )
    assert model.downstream_block_sensitivity_status == (
        "offline_development_sensitivity_not_site_truth"
    )
    # Two components, 2-hour blocks: 7 hold equalities per 8-QH block.
    assert len(model.downstream_block_sensitivity_constraints) == 336


def test_vn25_executed_state_accepts_solver_tolerance_at_development_bounds():
    config = load_temporal_repair_config()
    context = prepare_temporal_context(config)
    state = initial_temporal_state(config)
    lower_tolerance_state = replace(state, last_vn25_output_mw=175.0 - 5e-7)
    validate_temporal_state(lower_tolerance_state, config)
    model = build_temporal_model(
        context,
        lower_tolerance_state,
        config,
        lower_taps=26,
        upper_taps=28,
    )
    assert model.vn25_initial_ramp_up.active
    assert model.vn25_initial_ramp_down.active
    validate_temporal_state(
        replace(state, last_vn25_output_mw=350.0 + 5e-7),
        config,
    )
    with pytest.raises(TemporalRepairError, match="valid VN25 output"):
        validate_temporal_state(
            replace(state, last_vn25_output_mw=175.0 - 2e-6),
            config,
        )


def test_c1_must_run_is_direct_and_kgf1_band_surrounds_route_anchor(
    temporal_fixture,
):
    config, context, _, model = temporal_fixture
    assert context.c1_continuous_activities == CONTINUOUS_ASSETS
    expected = config["deterministic_temporal_repair"]["continuous_must_run_assets"]
    for asset in CONTINUOUS_ASSETS:
        on_name = "drp_on" if asset == "drp_pellet_input" else f"{asset}_on"
        assert all(getattr(model, on_name)[q].fixed for q in model.TIME)
        assert all(value(getattr(model, on_name)[q]) == pytest.approx(1.0) for q in model.TIME)
        assert float(expected[asset]["minimum_rate_t_h"]) > 0.0
        assert float(expected[asset]["maximum_rate_t_h"]) > float(
            expected[asset]["minimum_rate_t_h"]
        )
    reconciliation = model.c1_kgf1_route_scale_reconciliation
    assert reconciliation["raw_kgf1_coke_anchor_t_y"] == pytest.approx(1_000_000.0)
    assert reconciliation["raw_bof_liquid_steel_anchor_t_y"] == pytest.approx(
        3_400_000.0
    )
    assert reconciliation["fixed_reference_bof_central_t_y"] == pytest.approx(
        3_329_952.026,
        abs=1.0,
    )
    assert reconciliation["route_scale"] == pytest.approx(
        3_329_952.026 / 3_400_000.0,
        abs=1e-9,
    )
    assert reconciliation["dry_coal_floor_t_h"] == pytest.approx(
        143.66735001233883,
        abs=1e-9,
    )
    assert expected["coking_plant_1"]["minimum_rate_t_h"] < reconciliation[
        "dry_coal_floor_t_h"
    ] < expected["coking_plant_1"]["maximum_rate_t_h"]
    assert reconciliation["technical_minimum_claim"] == "false"
    kgf1_min = model.retained_process_min["coking_plant_1", 0]
    kgf1_repn = generate_standard_repn(kgf1_min.body)
    coefficients = {
        variable.name: coefficient
        for variable, coefficient in zip(
            kgf1_repn.linear_vars,
            kgf1_repn.linear_coefs,
            strict=True,
        )
    }
    assert value(kgf1_min.upper) == pytest.approx(0.0)
    assert kgf1_repn.constant == pytest.approx(
        expected["coking_plant_1"]["minimum_rate_t_h"] * 0.25
    )
    assert coefficients["coking_plant_1[0]"] == pytest.approx(-1.0)


def test_generator_qh_units_ramp_boundary_and_ij01_off(temporal_fixture):
    _, _, _, model = temporal_fixture
    assert model.generator_operating_mode == "normal_operation_vn25_available"
    assert model.vn25_electric_capacity_mw == pytest.approx(350.0)
    assert model.vn25_electric_capacity_interval_mwh == pytest.approx(87.5)
    assert model.vn25_min_electric_output_mw == pytest.approx(175.0)
    assert model.vn25_min_electric_output_interval_mwh == pytest.approx(43.75)
    assert model.vn25_ramp_interval_power_delta_mw == pytest.approx(52.5)
    assert model.vn25_ramp_interval_energy_delta_mwh == pytest.approx(13.125)
    assert hasattr(model, "vn25_initial_ramp_up")
    assert hasattr(model, "vn25_initial_ramp_down")
    assert value(model.vn25_gas_volume_cap[0].upper) == pytest.approx(150_000.0)
    for carrier in ("bfg", "cog", "bofg"):
        assert all(getattr(model, f"{carrier}_to_ij01")[q].fixed for q in model.TIME)
    assert all(model.ng_to_ij01_mwh[q].fixed for q in model.TIME)


def test_eaf_occupancy_and_daily_contract_replace_route_band(temporal_fixture):
    _, context, _, model = temporal_fixture
    assert len(model.TIME) == 192
    assert context.time_grid.execution_steps == 96
    assert model.eaf_daily_lower_taps == 20
    assert model.eaf_daily_upper_taps == 32
    assert not any(
        "c1_reference_eaf_liquid_steel" in name
        for name in model.component_map()
    )
    assert model.eaf_daily_route_band_replaced_by_heat_recoverability is True


def test_old_static_tiebreak_has_no_forbidden_c1_variables(temporal_fixture):
    _, _, _, model = temporal_fixture
    assert objective_variable_names(model.static_price_naive_objective.expr) == set()


def test_recoverable_tail_separates_bf_activity_and_removes_false_route_conflict(
    temporal_fixture,
):
    _, context, _, model = temporal_fixture
    assert not model.sinter_terminal.active
    assert not model.hot_iron_terminal.active
    assert not model.coke_terminal.active
    assert not model.cold_slab_terminal.active
    assert model.sinter_capacity.active
    assert model.hot_iron_capacity.active
    assert model.temporal_tail_cyclic_closures_replaced == (
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
        "eaf_slab_terminal",
        "pellet_terminal",
    )
    assert model.temporal_executed_handoff_index == (
        context.time_grid.execution_steps - 1
    )
    assert model.temporal_physical_tail_steps == (
        context.time_grid.horizon_steps - context.time_grid.execution_steps
    )
    diagnostic = must_run_bof_conflict_diagnostic(model)
    assert diagnostic["conversion_direction_audit"]["status"] == (
        "activity_and_physical_material_buses_separated"
    )
    assert diagnostic["sinter_output_t_per_t_ore"] == pytest.approx(1.23)
    assert diagnostic[
        "hot_iron_output_t_per_t_represented_bf_activity"
    ] == pytest.approx(
        2.1041666667
    )
    assert diagnostic["sinter_input_t_per_t_hot_metal"] == pytest.approx(1.0)
    assert diagnostic["bof_liquid_output_t_per_t_hot_iron_input"] == pytest.approx(
        1.0 / 0.824
    )
    assert diagnostic["forced_minimum_bof_liquid_steel_t"] == pytest.approx(
        14_405.339806058253
    )
    assert diagnostic["existing_bof_route_upper_t"] == pytest.approx(
        18_337.54403287671
    )
    assert diagnostic["minimum_excess_over_upper_t"] < 0.0
    assert diagnostic["forced_minimum_bof_liquid_steel_t"] != pytest.approx(
        23_001.779935644274
    )
    assert diagnostic["bound_changes_applied"] is False


def test_executed_coke_hot_iron_state_is_recursively_recoverable(
    temporal_fixture,
):
    config, context, state, model = temporal_fixture
    assert model.temporal_recursive_recovery_horizon_hours == 48
    assert model.temporal_recursive_recovery_horizon_steps == 192
    assert model.temporal_recursive_recovery_handoff_index == 95
    assert model.temporal_recursive_recovery_status == (
        "necessary_coke_hot_iron_bof_viability_cut"
    )
    route_cut = model.temporal_coke_hot_iron_route_recursive_recoverability
    assert route_cut.active
    repn = generate_standard_repn(route_cut.body)
    coefficients = {
        variable.name: coefficient
        for variable, coefficient in zip(repn.linear_vars, repn.linear_coefs)
    }
    bof_yield = 1.0 / 0.824
    coke_per_hot_metal = float(
        context.source_coke_chain["bf_coke_t_per_t_hot_metal"]
    )
    assert coefficients["hot_iron_inventory[95]"] == pytest.approx(bof_yield)
    assert coefficients["coke_inventory[95]"] == pytest.approx(
        bof_yield / coke_per_hot_metal
    )
    maximum_coke_at_failed_day1_hot_iron = (
        float(value(route_cut.upper))
        - float(repn.constant)
        - coefficients["hot_iron_inventory[95]"] * 72.49223918780427
    ) / coefficients["coke_inventory[95]"]
    assert maximum_coke_at_failed_day1_hot_iron == pytest.approx(
        895.2126553407998
    )
    assert maximum_coke_at_failed_day1_hot_iron > 360.0

    model_72h = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=28,
        planning_horizon_hours=72,
    )
    assert model_72h.temporal_recursive_recovery_horizon_steps == 192
    assert model_72h.temporal_recursive_recovery_handoff_index == 95
    assert model_72h.temporal_fixed_recovery_checkpoint_hours == 48
    assert model_72h.temporal_fixed_recovery_checkpoint_steps == 192
    assert model_72h.temporal_extended_tail_policy == (
        "preserve_48h_recovery_checkpoint_then_extend_feasibility"
    )
    assert tuple(
        variable.name
        for variable in identify_variables(
            model_72h.temporal_fixed_recovery_dri_terminal.body
        )
    ) == ("dri_inventory[190]",)
    assert tuple(
        variable.name
        for variable in identify_variables(
            model_72h.temporal_fixed_recovery_cold_slab_terminal.body
        )
    ) == ("cold_slab_inventory[191]",)
    assert model_72h.eaf_heat_start[190].fixed
    assert model_72h.eaf_heat_start[191].fixed
    assert value(model_72h.eaf_heat_start[190]) == 0.0
    assert value(model_72h.eaf_heat_start[191]) == 0.0
    assert tuple(model_72h.scrap_supply_deadlines) == (192,)
    assert value(model_72h.site_scrap_supply_deadline_cap[192].upper) == (
        pytest.approx(1_900_000.0 * 48.0 / 8760.0)
    )
    assert value(model_72h.external_scrap_supply_deadline_cap[192].upper) == (
        pytest.approx(1_300_000.0 * 48.0 / 8760.0)
    )
    assert value(model_72h.internal_scrap_supply_deadline_cap[192].upper) == (
        pytest.approx(600_000.0 * 48.0 / 8760.0)
    )

    hard_terminal = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=28,
        planning_horizon_hours=168,
        hard_inventory_terminal=True,
    )
    assert not hasattr(
        hard_terminal,
        "temporal_coke_hot_iron_route_recursive_recoverability",
    )
    assert not hasattr(hard_terminal, "site_scrap_supply_deadline_cap")


def test_route_scaled_kgf1_floor_removes_day2_and_week_conflict(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    day2_state = replace(
        state,
        inventory_overrides={
            **state.inventory_overrides,
            "coke_store_initial_t": 360.0,
            "hot_iron_store_initial_t": 2.5796244081611803,
            "sinter_store_initial_t": 0.0,
        },
    )
    day2_model = build_temporal_model(
        context,
        day2_state,
        config,
        lower_taps=26,
        upper_taps=28,
    )
    build_scalar_objective_components(
        context,
        day2_model,
        electricity_prices=[75.0] * context.time_grid.execution_steps,
        remaining_taps=163,
        continuation_eur_per_heat=0.0,
    )
    conflict = recursive_coke_hot_iron_conflict_diagnostic(day2_model)
    assert conflict["conflict_id"] == (
        "c1_kgf1_coke_hot_iron_bof_recursive_week_conflict"
    )
    assert conflict["recursive_handoff_excess_t_liquid_steel"] < 0.0
    assert conflict["hard_168h_terminal_minimum_excess_t_liquid_steel"] < 0.0
    assert conflict["physical_bounds_or_yields_changed"] is False


def test_c1_sinter_bf_bof_chain_has_separate_units_and_annual_anchors(
    temporal_fixture,
):
    config, _, _, model = temporal_fixture
    interface = config["deterministic_temporal_repair"][
        "c1_bf_material_interface"
    ]
    assert model.c1_bf_activity_quantity_role == (
        "governed_represented_bf_activity_proxy"
    )
    assert model.c1_bf_activity_rate_unit == "t_represented_bf_activity/h"
    assert model.c1_annual_sinter_anchor_t_y == pytest.approx(2_800_000.0)
    assert model.c1_annual_hot_metal_anchor_t_y == pytest.approx(2_800_000.0)
    assert model.c1_sinter_t_per_t_hot_metal == pytest.approx(1.0)
    assert interface["sensitivity_sinter_t_per_t_hot_metal"] == pytest.approx(
        1.088
    )
    hot_metal = generate_standard_repn(model.bf6_hot_iron_output[0].expr)
    physical_sinter = generate_standard_repn(model.bf_sinter_input[0].expr)
    hot_metal_coeff = next(
        coefficient
        for variable, coefficient in zip(
            hot_metal.linear_vars, hot_metal.linear_coefs
        )
        if variable is model.blast_furnace_6[0]
    )
    sinter_coeff = next(
        coefficient
        for variable, coefficient in zip(
            physical_sinter.linear_vars, physical_sinter.linear_coefs
        )
        if variable is model.blast_furnace_6[0]
    )
    assert hot_metal_coeff == pytest.approx(2.1041666667)
    assert sinter_coeff / hot_metal_coeff == pytest.approx(1.0)
    average_bf_activity = 2_800_000.0 / 8760.0 / hot_metal_coeff
    average_sifa_feed = 2_800_000.0 / 8760.0 / 1.23
    assert 120.0 <= average_bf_activity <= 170.0
    assert 160.0 <= average_sifa_feed <= 320.0


def test_route_contract_separates_bf_activity_from_physical_sinter():
    path = (
        STEEL_ROOT.parents[2]
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/"
        "c5_route_boundary_contract.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = {
            row["route_id"]: row
            for row in csv.DictReader(handle)
            if row["configuration"] == "C1"
        }
    assert float(rows["C1_BF_ACTIVITY"]["conversion_factor"]) == pytest.approx(
        2.1041666667
    )
    assert rows["C1_BF_ACTIVITY"]["input_carrier_material"] == (
        "represented_bf_activity"
    )
    assert float(rows["C1_BF"]["conversion_factor"]) == pytest.approx(1.0)
    assert rows["C1_BF"]["input_carrier_material"] == "sinter"


def test_scrap_origin_ledger_conserves_routes_and_central_caps(temporal_fixture):
    _, _, _, model = temporal_fixture
    for route in ("bof", "eaf"):
        assert hasattr(model, f"external_scrap_to_{route}_t")
        assert hasattr(model, f"internal_scrap_to_{route}_t")
        assert hasattr(model, f"{route}_scrap_origin_balance")
    assert value(model.site_scrap_supply_cap.upper) == pytest.approx(
        1_900_000.0 * 48.0 / 8760.0
    )
    assert value(model.bof_scrap_supply_cap.upper) == pytest.approx(
        1_000_000.0 * 48.0 / 8760.0
    )
    assert value(model.eaf_scrap_supply_cap.upper) == pytest.approx(
        900_000.0 * 48.0 / 8760.0
    )
    assert value(model.external_scrap_supply_cap.upper) == pytest.approx(
        1_300_000.0 * 48.0 / 8760.0
    )
    assert value(model.internal_scrap_supply_cap.upper) == pytest.approx(
        600_000.0 * 48.0 / 8760.0
    )
    assert model.c1_scrap_origin_policy == (
        "external_purchase_plus_bounded_internal_reuse_rolling_horizon_quota"
    )


def test_scrap_budget_carries_across_rolling_days_without_reuse(temporal_fixture):
    config, context, state, _ = temporal_fixture
    carried = replace(
        state,
        executed_hours=24,
        executed_intervals=96,
        cumulative_external_scrap_to_bof_t=2_000.0,
        cumulative_external_scrap_to_eaf_t=1_500.0,
        cumulative_internal_scrap_to_bof_t=700.0,
        cumulative_internal_scrap_to_eaf_t=900.0,
    )
    model = build_temporal_model(
        context,
        carried,
        config,
        lower_taps=20,
        upper_taps=32,
    )
    assert value(model.external_scrap_supply_cap.upper) == pytest.approx(
        1_300_000.0 * 72.0 / 8760.0 - 3_500.0
    )
    assert value(model.internal_scrap_supply_cap.upper) == pytest.approx(
        600_000.0 * 72.0 / 8760.0 - 1_600.0
    )
    assert value(model.site_scrap_supply_cap.upper) == pytest.approx(
        1_900_000.0 * 72.0 / 8760.0 - 5_100.0
    )
    assert not hasattr(model, "site_scrap_supply_deadline_cap")


def test_only_external_scrap_is_in_represented_procurement_cost(temporal_fixture):
    _, context, _, model = temporal_fixture
    expression = _represented_cost_expression(
        context,
        model,
        C1_CONFIGURATION,
        (75.0,) * len(model.TIME),
        objective_hours=tuple(range(context.time_grid.execution_steps)),
    )
    names = {
        variable.parent_component().name
        for variable in identify_variables(expression, include_fixed=False)
    }
    assert "external_scrap_to_bof_t" in names
    assert "external_scrap_to_eaf_t" in names
    assert "internal_scrap_to_bof_t" not in names
    assert "internal_scrap_to_eaf_t" not in names
    assert "bof_scrap_supply_t" not in names


def test_base_hbi_is_zero_and_dri_buffer_is_explicitly_cold_without_silo_claim(
    temporal_fixture,
):
    _, _, _, model = temporal_fixture
    assert all(value(model.imported_hbi_to_eaf_t[q]) == 0.0 for q in model.TIME)
    assert model.c1_metallics_sensitivity_mode == "base"
    assert model.c1_dri_buffer_representation == (
        "cold_dri_timing_buffer_with_direct_hdri_feed"
    )
    assert model.c1_dri_buffer_active_capacity_t == pytest.approx(17_760.0)
    assert model.c1_dri_buffer_source_candidate_t == pytest.approx(15_350.0)
    assert model.c1_dri_buffer_thermal_or_silo_claim == (
        "cold_dri_inventory_only_no_separate_silo_or_cooling_dynamics"
    )
    assert model.c1_dri_thermal_state_mode == "hdri_direct_plus_cdri_buffer"
    assert model.c1_hdri_temperature_c == pytest.approx(600.0)
    assert model.c1_cdri_temperature_c == pytest.approx(50.0)
    assert model.c1_cdri_max_share == pytest.approx(0.30)


def test_hbi_and_high_scrap_are_separate_predetermined_offline_sensitivities(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    hbi_config = copy.deepcopy(config)
    hbi = hbi_config["deterministic_temporal_repair"][
        "c1_metallics_sensitivity"
    ]
    hbi["mode"] = "hbi"
    hbi["hbi_annual_cap_t_y"] = 1_100_000.0
    hbi_model = build_temporal_model(
        context,
        state,
        hbi_config,
        lower_taps=20,
        upper_taps=32,
    )
    assert hbi_model.c1_metallics_sensitivity_mode == "hbi"
    assert value(hbi_model.imported_hbi_horizon_cap.upper) == pytest.approx(
        1_100_000.0 * 48.0 / 8760.0
    )
    assert hasattr(hbi_model, "eaf_dri_equivalent_balance")

    high_config = copy.deepcopy(config)
    high = high_config["deterministic_temporal_repair"][
        "c1_metallics_sensitivity"
    ]
    high.update(
        {
            "mode": "high_scrap",
            "hbi_annual_cap_t_y": 0.0,
            "eaf_hdri_t_per_t_liquid_steel": 1.9 / 3.3,
            "eaf_scrap_t_per_t_liquid_steel": 1.8 / 3.3,
        }
    )
    high_scrap = high_config["deterministic_temporal_repair"][
        "scrap_origin_contract"
    ]
    high_scrap.update(
        {
            "annual_eaf_scrap_cap_t_y": 1_800_000.0,
            "annual_external_scrap_cap_t_y": 2_200_000.0,
            "annual_site_scrap_cap_t_y": 2_800_000.0,
        }
    )
    high_model = build_temporal_model(
        context,
        state,
        high_config,
        lower_taps=20,
        upper_taps=32,
    )
    assert high_model.c1_metallics_sensitivity_mode == "high_scrap"
    assert all(
        value(high_model.imported_hbi_to_eaf_t[q]) == 0.0
        for q in high_model.TIME
    )
    scrap_repn = generate_standard_repn(high_model.eaf_scrap_supply_t[0].expr)
    dri_repn = generate_standard_repn(high_model.eaf_dri_equivalent_input[0].expr)
    assert scrap_repn.linear_coefs[0] == pytest.approx((1.8 / 3.3) * 162.5)
    assert dri_repn.linear_coefs[0] == pytest.approx((1.9 / 3.3) * 162.5)

    stacked = copy.deepcopy(hbi_config)
    stacked_metallics = stacked["deterministic_temporal_repair"][
        "c1_metallics_sensitivity"
    ]
    stacked_metallics["eaf_hdri_t_per_t_liquid_steel"] = 1.9 / 3.3
    stacked_metallics["eaf_scrap_t_per_t_liquid_steel"] = 1.8 / 3.3
    with pytest.raises(Phase6BError, match="predetermined MER endpoint recipe"):
        build_temporal_model(
            context,
            state,
            stacked,
            lower_taps=20,
            upper_taps=32,
        )


def test_explicit_week_terminal_keeps_inventory_and_heat_closure_hard(
    temporal_fixture,
):
    config, context, state, _ = temporal_fixture
    model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=20,
        upper_taps=32,
        planning_horizon_hours=168,
        hard_inventory_terminal=True,
    )
    add_week_heat_contract(model, target_taps=quota_period_target_taps(0))
    assert model.c1_inventory_terminal_policy == "hard_cyclic_or_campaign_terminal"
    assert model.sinter_terminal.active
    assert model.hot_iron_terminal.active
    assert model.coke_terminal.active
    assert model.cold_slab_terminal.active
    assert model.temporal_tail_cyclic_closures_replaced == ()
    assert model.eaf_week_target.active
    assert model.eaf_week_terminal_idle.active


def test_d_objective_has_no_tail_variables_or_market_constructs(temporal_fixture):
    _, context, _, model = temporal_fixture
    expression = _represented_cost_expression(
        context,
        model,
        C1_CONFIGURATION,
        (75.0,) * 192,
        objective_hours=tuple(range(96)),
    )
    variables = list(identify_variables(expression, include_fixed=False))
    assert variables
    assert all(
        not variable.is_indexed() and int(variable.index()) < 96
        for variable in variables
    )
    forbidden_names = {"scenario", "probability", "bid", "clearing", "settlement"}
    assert not any(
        token in variable.name.lower()
        for token in forbidden_names
        for variable in variables
    )


def test_scalar_objective_is_single_linear_D_cost_plus_continuation(temporal_fixture):
    config, context, state, _ = temporal_fixture
    model = build_temporal_model(
        context,
        state,
        config,
        lower_taps=26,
        upper_taps=28,
    )
    components = build_scalar_objective_components(
        context,
        model,
        electricity_prices=(75.0,) * 96,
        remaining_taps=191,
        continuation_eur_per_heat=123.0,
    )
    active = list(model.component_data_objects(Objective, active=True))
    assert [item.name for item in active] == ["temporal_scalar_objective"]
    assert model.temporal_objective_mode == OBJECTIVE_MODE
    assert model.temporal_physical_zero_preservation.active
    assert not hasattr(model, "temporal_tv_abs")
    assert not hasattr(model, "temporal_heat_deviation")
    repn = generate_standard_repn(components.total_eur)
    assert repn.nonlinear_expr is None
    variables = list(identify_variables(components.procurement_eur, include_fixed=False))
    assert variables
    assert all(int(variable.index()[-1] if isinstance(variable.index(), tuple) else variable.index()) < 96 for variable in variables)
    continuation_names = {
        variable.name
        for variable in identify_variables(components.continuation_eur, include_fixed=False)
    }
    assert continuation_names
    assert all(
        "eaf_tap" in name or "eaf_heat_start" in name
        for name in continuation_names
    )


def test_process_electricity_overlay_does_not_dispatch_mer_boundary_residual():
    config = load_temporal_repair_config()
    config["deterministic_temporal_repair"][
        "experimental_process_electricity_overlay"
    ] = {
        "classification": (
            "experimental_proportional_process_electricity_not_source_proven"
        ),
        "mwh_per_t_activity": 0.04664,
    }
    context = prepare_temporal_context(config)
    model = build_temporal_model(
        context,
        initial_temporal_state(config),
        config,
        lower_taps=26,
        upper_taps=28,
    )

    assert model.experimental_process_electricity_boundary_policy == (
        "operating_process_total_active_broad_site_difference_reporting_only"
    )
    for t in model.TIME:
        assert value(model.site_background_electricity_mwh[t]) == pytest.approx(0.0)
        identity = generate_standard_repn(
            model.gross_total_electricity_mwh[t]
            - model.represented_gross_electricity_before_background_mwh[t]
        )
        assert identity.nonlinear_expr is None
        assert not identity.linear_vars
        assert identity.constant == pytest.approx(0.0)


def test_ng_service_overlay_replaces_legacy_baseload_without_double_counting():
    config = load_temporal_repair_config()
    config["deterministic_temporal_repair"][
        "experimental_ng_service_calibration"
    ] = {
        "classification": "user_authorized_c1_origin_explicit_ng_service_calibration",
        "ironmaking_target_pj_y": 2.0,
        "ironmaking_basis_t_y": 2_800_000.0,
        "downstream_target_pj_y": 13.1,
        "downstream_basis_t_y": 6_750_000.0,
    }
    context = prepare_temporal_context(config)
    model = build_temporal_model(
        context,
        initial_temporal_state(config),
        config,
        lower_taps=26,
        upper_taps=28,
    )

    assert model.experimental_ng_service_targets == pytest.approx(
        {
            "ironmaking_target_pj_y": 2.0,
            "ironmaking_basis_t_y": 2_800_000.0,
            "downstream_target_pj_y": 13.1,
            "downstream_basis_t_y": 6_750_000.0,
        }
    )
    assert model.c1_downstream_ng_service_covers_explicit_flows.active
    for t in model.TIME:
        expected = (
            model.generator_named_ng_mwh[t]
            + model.full_site_energy_bridge_named_ng_mwh[t]
            + model.c1_existing_ironmaking_ng_service_mwh[t]
            + model.c1_existing_downstream_ng_service_mwh[t]
            + model.drp_named_ng_mwh[t]
            + model.eaf_named_ng_mwh[t]
        )
        identity = generate_standard_repn(
            model.total_named_ng_procurement_mwh[t] - expected
        )
        assert identity.nonlinear_expr is None
        assert not identity.linear_vars
        assert identity.constant == pytest.approx(0.0)


def test_coal_wag_overlay_scales_procurement_and_carbon_residual_is_reporting_only():
    config = load_temporal_repair_config()
    calibration = {
        "classification": "user_authorized_c1_coal_completion_carrier_wag_calibration",
        "coal_procurement_multiplier": 1.28495216932074,
        "bfg_mwh_per_t_hot_metal": 1.46825396825397,
        "cog_mwh_per_t_kgf_activity": 1.78780575437936,
        "bofg_mwh_per_t_bof_steel": 0.179738562091503,
        "cog_self_use_scale": 0.942949340241867,
        "coal_anchor_t_y": 2_200_000.0,
        "coal_anchor_pj_y": 58.0,
    }
    config["deterministic_temporal_repair"][
        "experimental_coal_wag_calibration"
    ] = calibration
    context = prepare_temporal_context(config)
    model = build_temporal_model(
        context,
        initial_temporal_state(config),
        config,
        lower_taps=26,
        upper_taps=28,
    )

    assert model.experimental_coal_wag_parameters == calibration
    for t in model.TIME:
        coal_identity = generate_standard_repn(
            model.c1_total_coal_input_t[t]
            - calibration["coal_procurement_multiplier"]
            * (model.coking_plant_1[t] + model.bf_pci_input_t[t])
        )
        assert coal_identity.nonlinear_expr is None
        assert not coal_identity.linear_vars
        assert coal_identity.constant == pytest.approx(0.0)

    carbon = administrative_carbon_balance_rows(
        [
            {"metric_id": "bfg_fuel_explicit_co2", "model_annual_equivalent": 3.0},
            {"metric_id": "cog_fuel_explicit_co2", "model_annual_equivalent": 0.4},
            {"metric_id": "bofg_fuel_explicit_co2", "model_annual_equivalent": 0.5},
            {"metric_id": "fuel_explicit_co2_total", "model_annual_equivalent": 6.5},
        ]
    )
    assert all(row["physical_balance_closed"] is False for row in carbon)
    assert all(row["residual_enters_model"] is False for row in carbon)
    assert {row["source_class"] for row in carbon} == {
        "coal_and_other_carbon",
        "natural_gas",
        "fluxes",
        "full_site_scope1",
    }


def _scalar_result(*, status: str, incumbent: bool, attempt: str) -> ScalarSolveResult:
    return ScalarSolveResult(
        run_case="unit_scalar",
        attempt=attempt,
        status=status,
        solver_status="ok",
        termination_condition="maxTimeLimit",
        feasible_incumbent=incumbent,
        incumbent_objective_eur=1.0 if incumbent else None,
        procurement_eur=1.0 if incumbent else None,
        continuation_eur=0.0 if incumbent else None,
        best_bound_eur=0.9 if incumbent else None,
        absolute_gap_eur=0.1 if incumbent else None,
        relative_gap=0.1 if incumbent else None,
        runtime_seconds=6.0,
        time_limit_seconds=6.0,
        mip_gap_target=0.002,
        fallback_used=attempt == "fallback_60s",
        solver_log_path="unit.log",
        variable_count=1,
        binary_count=1,
        constraint_count=1,
    )


def test_scalar_solver_falls_back_only_after_no_incumbent(monkeypatch):
    config = load_temporal_repair_config()
    calls: list[tuple[str, bool]] = []
    outcomes = iter(
        (
            _scalar_result(
                status="unknown_under_time_limit",
                incumbent=False,
                attempt="primary_6s",
            ),
            _scalar_result(
                status="feasible_fallback",
                incumbent=True,
                attempt="fallback_60s",
            ),
        )
    )

    def fake_attempt(*args, **kwargs):
        calls.append((kwargs["attempt"], kwargs.get("dual_reductions", True)))
        return next(outcomes)

    monkeypatch.setattr(temporal_module, "_solve_scalar_attempt", fake_attempt)
    components = ScalarObjectiveComponents(0.0, 0.0, 0.0, 191, 0.0)
    accepted, attempts = solve_scalar_operational_model(
        object(),
        components,
        config,
        run_case="unit_scalar",
        solver_log_root=Path("tmp/unit_scalar_logs"),
    )
    assert calls == [("primary_6s", True), ("fallback_60s", False)]
    assert len(attempts) == 2
    assert accepted.status == "feasible_fallback"


def test_scalar_solver_does_not_fallback_with_primary_incumbent(monkeypatch):
    config = load_temporal_repair_config()
    calls: list[str] = []

    def fake_attempt(*args, **kwargs):
        calls.append(kwargs["attempt"])
        return _scalar_result(
            status="feasible_time_limited",
            incumbent=True,
            attempt="primary_6s",
        )

    monkeypatch.setattr(temporal_module, "_solve_scalar_attempt", fake_attempt)
    accepted, attempts = solve_scalar_operational_model(
        object(),
        ScalarObjectiveComponents(0.0, 0.0, 0.0, 191, 0.0),
        config,
        run_case="unit_scalar",
        solver_log_root=Path("tmp/unit_scalar_logs"),
    )
    assert calls == ["primary_6s"]
    assert len(attempts) == 1
    assert accepted.status == "feasible_time_limited"


def test_scalar_solver_uses_physical_label_only_for_proven_infeasible(
    monkeypatch,
):
    config = load_temporal_repair_config()

    def fake_attempt(*args, **kwargs):
        return _scalar_result(
            status="proven_infeasible",
            incumbent=False,
            attempt="primary_6s",
        )

    monkeypatch.setattr(temporal_module, "_solve_scalar_attempt", fake_attempt)
    with pytest.raises(TemporalPhysicalInfeasibility):
        solve_scalar_operational_model(
            object(),
            ScalarObjectiveComponents(0.0, 0.0, 0.0, 191, 0.0),
            config,
            run_case="unit_scalar",
            solver_log_root=Path("tmp/unit_scalar_logs"),
        )


def test_annual_anchor_regression_reuses_phase5e_and_keeps_partial_gaps_reporting_only():
    static_gate = _phase5e_static_anchor_gate()
    assert static_gate["annual_anchor_comparison_pass"]
    assert static_gate["carrier_coverage_pass"]
    assert static_gate["generator_source_identity_pass"]
    assert not static_gate["annual_anchors_enter_constraints"]
    assert not static_gate["annual_anchors_enter_objectives"]

    rows, gate = annual_operational_anchor_rows(
        {},
        evaluation_id="unit_d1_provisional",
        executed_hours=24,
        period_classification="provisional_annualised_diagnostic",
        calendar_coverage="one_flat_reference_day_not_representative_year",
    )
    by_id = {row["metric_id"]: row for row in rows}
    required = {
        "bfg_production",
        "cog_production",
        "bofg_production",
        "represented_named_ng_total",
        "process_electricity_boundary",
        "broad_site_electricity_boundary",
        "generator_fuel_total",
        "generator_output",
        "fuel_explicit_co2_total",
        "drp_captured_co2",
        "site_final_product",
        "eaf_liquid_steel",
        "site_scrap",
        "hbi_import",
        "drp_pellet_input",
        "imported_slab",
    }
    assert required <= set(by_id)
    assert by_id["represented_named_ng_total"]["comparability"] == (
        "partially_comparable"
    )
    assert "residual" in by_id["represented_named_ng_total"]["caveat"].lower()
    assert gate["identity_gate_pass"]
    assert gate["partial_boundaries_do_not_fail_on_full_site_gap"]
    assert not gate["annual_anchors_enter_constraints"]
    assert not gate["annual_anchors_enter_objectives"]

    deltas = annual_anchor_delta_rows(
        rows,
        baseline_id="accepted_test",
        baseline_values={"generator_output": 1.0},
    )
    delta_by_id = {row["metric_id"]: row for row in deltas}
    assert delta_by_id["generator_output"]["comparison_status"] == "compared"
    assert delta_by_id["bfg_production"]["comparison_status"] == (
        "not_available_no_comparable_baseline"
    )
    assert json.loads(json.dumps(gate))["identity_gate_pass"] is True


def test_annual_anchor_energy_conversion_reports_pj_not_tj():
    rows, _ = annual_operational_anchor_rows(
        {
            "bfg_generated": 1_000.0,
            "total_named_ng_procurement_mwh": 2_000.0,
        },
        evaluation_id="unit_energy_conversion",
        executed_hours=8760,
        period_classification="unit",
        calendar_coverage="full_denominator",
    )
    by_id = {row["metric_id"]: row for row in rows}
    assert by_id["bfg_production"]["model_annual_equivalent"] == pytest.approx(
        0.0036
    )
    assert by_id["represented_named_ng_total"][
        "model_annual_equivalent"
    ] == pytest.approx(0.0072)


def test_last_accepted_phase5e_energy_baseline_is_converted_to_pj_per_year():
    values = _last_accepted_annual_values()
    rows = [
        row
        for row in csv.DictReader(
            (
                temporal_module.LAST_ACCEPTED_ANNUAL_BASELINE_ROOT
                / "dynamic_period_metrics.csv"
            ).open(encoding="utf-8", newline="")
        )
        if row["configuration_id"] == C1_CONFIGURATION
    ]
    expected_grid = sum(
        float(row["gross_grid_import_mwh"])
        * 8760.0
        / int(row["executed_hours"])
        * temporal_module.MWH_TO_PJ
        for row in rows
    ) / len(rows)
    expected_generator = sum(
        float(row["generator_electricity_mwh"])
        * 8760.0
        / int(row["executed_hours"])
        * temporal_module.MWH_TO_PJ
        for row in rows
    ) / len(rows)
    assert values["gross_grid_import"] == pytest.approx(expected_grid)
    assert values["generator_output"] == pytest.approx(expected_generator)
    assert values["gross_grid_import"] < 20.0
    assert values["generator_output"] < 10.0


def test_temporal_config_contains_no_enabled_future_scope():
    config = load_temporal_repair_config()
    assert config["temporal_contract_version"] == TEMPORAL_CONTRACT_VERSION
    assert all(config["forbidden_scope"].values())
    assert Path(config["output_root"]).parts[-1].startswith(
        "steel_c6_deterministic_scalar_temporal_repair"
    )
    assert config["objective_mode"] == OBJECTIVE_MODE
    assert config["lineage_role"] == (
        "diagnostic_superseding_lexicographic_temporal_evidence"
    )
    repair = config["deterministic_temporal_repair"]
    assert repair["operational_time_limit_seconds"] == 6
    assert repair["operational_fallback_time_limit_seconds"] == 60
    assert repair["runtime_mip_gap"] == 0.002
    assert repair["planned_full_run"]["solve_attempt_count_upper_bound"] == 120
    assert repair["feasibility_initial_time_limit_seconds"] == 60
    assert repair["feasibility_extended_time_limit_seconds"] >= 60
