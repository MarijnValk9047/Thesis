from __future__ import annotations

from dataclasses import replace

import pytest

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from steel.s4_4c6_deterministic_c0_temporal_validation import (
    initial_c0_state,
    load_c0_validation_config,
)
from steel.s4_4c6_deterministic_hourly_temporal_validation import (
    C0_ANNUAL_QH_CONTRACT_VERSION,
    C1_ANNUAL_QH_CONTRACT_VERSION,
    _annual_initial_inventory_targets,
    _build_model,
    _qh_context,
)
from steel.s4_4c6_deterministic_hourly_full_year import (
    _annual_physical_horizon_hours,
)
from steel.s4_4c6_deterministic_temporal_repair import (
    _annual_heat_schedule,
    cumulative_eaf_target_taps,
    initial_temporal_state,
    load_temporal_repair_config,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


def _configs():
    c0 = load_c0_validation_config()
    return c0, load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])


@pytest.mark.parametrize(
    ("execution_hours", "horizon_hours", "execution_steps", "horizon_steps"),
    ((23, 71, 92, 284), (24, 72, 96, 288), (25, 73, 100, 292)),
)
def test_qh_annual_context_keeps_v60_execution_plus_48h_tail(
    execution_hours: int,
    horizon_hours: int,
    execution_steps: int,
    horizon_steps: int,
) -> None:
    _, c1 = _configs()
    context = _qh_context(
        c1,
        C0_ANNUAL_QH_CONTRACT_VERSION,
        execution_hours=execution_hours,
        physical_horizon_hours=horizon_hours,
    )
    assert context.time_grid.execution_hours == execution_hours
    assert context.time_grid.execution_steps == execution_steps
    assert context.time_grid.horizon_steps == horizon_steps
    assert context.time_grid.horizon_hours - context.time_grid.execution_hours == 48
    assert context.time_grid.hours_to_steps(48) == 192
    assert _annual_physical_horizon_hours(
        configuration=C1_CONFIGURATION,
        execution_hours=execution_hours,
        remaining_calendar_hours=8760,
        final_day=False,
    ) == horizon_hours


def test_qh_annual_heat_schedule_preserves_v60_dynamic_quota_policy() -> None:
    _, c1 = _configs()
    days = [
        {
            "day_length_hours": hours,
            "execution_steps": hours * 4,
        }
        for hours in ([24] * 26 + [25] + [24] * 153 + [23] + [24] * 184)
    ]
    policy = c1["deterministic_temporal_repair"]["causal_flat_year"]
    schedule = _annual_heat_schedule(
        days,
        annual_target_taps=cumulative_eaf_target_taps(8760),
        daily_tolerance=int(policy["heat_target_daily_tolerance"]),
        quota_period_days=7,
        quota_neutral_upper_cap=int(
            policy["routine_quota_normal_day_upper_taps"]
        ),
    )
    assert len(schedule) == 365
    assert sum(row["target"] for row in schedule) == 9945
    assert schedule[0]["quota_period_target"] == 191
    assert (schedule[0]["lower"], schedule[0]["upper"]) == (23, 29)
    assert min(row["lower"] for row in schedule) == 22
    assert max(row["upper"] for row in schedule) == 29


def test_qh_annual_c0_builder_uses_native_execution_steps() -> None:
    c0, c1 = _configs()
    context = _qh_context(
        c1,
        C0_ANNUAL_QH_CONTRACT_VERSION,
        execution_hours=24,
        physical_horizon_hours=72,
    )
    state = replace(
        initial_c0_state(c0, episode_id="qh_annual_grid_c0"),
        temporal_contract_version=C0_ANNUAL_QH_CONTRACT_VERSION,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 96,
        configuration=C0_CONFIGURATION,
        annual_readiness=True,
        annual_initial_inventory_targets_t=_annual_initial_inventory_targets(
            c0, c1, configuration=C0_CONFIGURATION
        ),
    )
    assert len(model.TIME) == 288
    assert model.annual_execution_hours == 24
    assert model.annual_execution_steps == 96


def test_qh_annual_c1_future_calendar_links_in_qh_steps() -> None:
    c0, c1 = _configs()
    context = _qh_context(
        c1,
        C1_ANNUAL_QH_CONTRACT_VERSION,
        execution_hours=24,
        physical_horizon_hours=72,
    )
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_QH_CONTRACT_VERSION,
        eaf_quota_period_id="annual_quota_001",
        eaf_quota_target_taps=32,
        eaf_quota_completed_taps=0,
    )
    future_calendar = [
        {
            "calendar_day_index": 2,
            "day_length_hours": 24,
            "lower": 0,
            "upper": 32,
            "quota_period_index": 1,
            "quota_period_target": 32,
            "quota_period_boundary": True,
        }
    ]
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 96,
        configuration=C1_CONFIGURATION,
        lower_taps=0,
        upper_taps=32,
        annual_readiness=True,
        annual_initial_inventory_targets_t=_annual_initial_inventory_targets(
            c0, c1, configuration=C1_CONFIGURATION
        ),
        annual_future_heat_calendar=future_calendar,
        annual_current_quota_period_index=1,
        year_terminal_remaining_taps=32,
        year_terminal_recovery_index=287,
    )
    assert model.c1_annual_future_heat_calendar_complete is True
    assert model.c1_annual_future_heat_calendar_physical_row_end_hours == (192,)
    assert hasattr(model, "eaf_heat_start")
    assert not hasattr(model, "eaf_heat_start_subslot")
    assert model.dri_thermal_accounting_interval == "hourly_v60_on_native_qh_grid"
    assert len(model.drp_hdri_allocation_balance) == 72
    assert len(model.eaf_dri_thermal_input_balance) == 72
    assert len(model.eaf_cdri_share_limit) == 72
    assert model.year_end_eaf_idle_index_policy == "native_qh_eaf_start_intervals"
    assert model.hourly_year_end_coefficient_closure_tolerance_t == pytest.approx(1e-6)
    idle_expression = str(model.hourly_year_end_eaf_idle.expr)
    assert "eaf_heat_start[286]" in idle_expression
    assert "eaf_heat_start[287]" in idle_expression


def test_qh_visible_year_endpoint_validates_terminal_on_qh_steps() -> None:
    c0, c1 = _configs()
    context = _qh_context(
        c1,
        C0_ANNUAL_QH_CONTRACT_VERSION,
        execution_hours=24,
        physical_horizon_hours=72,
    )
    state = replace(
        initial_c0_state(c0, episode_id="qh_visible_year_endpoint"),
        temporal_contract_version=C0_ANNUAL_QH_CONTRACT_VERSION,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 96,
        configuration=C0_CONFIGURATION,
        annual_readiness=True,
        year_terminal_recovery_index=1_343,
        annual_initial_inventory_targets_t=_annual_initial_inventory_targets(
            c0, c1, configuration=C0_CONFIGURATION
        ),
        physical_horizon_hours=336,
        commitment_day_lengths_hours=(24,) * 14,
    )
    assert len(model.TIME) == 1_344
    assert model.hourly_annual_inventory_terminal_index == 1_343
