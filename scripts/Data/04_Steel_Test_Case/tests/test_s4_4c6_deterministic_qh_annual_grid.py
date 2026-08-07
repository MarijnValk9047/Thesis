from __future__ import annotations

from dataclasses import replace

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
from steel.s4_4c6_deterministic_temporal_repair import (
    initial_temporal_state,
    load_temporal_repair_config,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


def _configs():
    c0 = load_c0_validation_config()
    return c0, load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])


def test_qh_annual_context_keeps_hours_and_model_steps_distinct() -> None:
    _, c1 = _configs()
    context = _qh_context(
        c1,
        C0_ANNUAL_QH_CONTRACT_VERSION,
        execution_hours=24,
        physical_horizon_hours=72,
    )
    assert context.time_grid.execution_hours == 24
    assert context.time_grid.execution_steps == 96
    assert context.time_grid.horizon_steps == 288
    assert context.time_grid.hours_to_steps(48) == 192


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
            "quota_period_boundary": False,
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
    )
    assert model.c1_annual_future_heat_calendar_complete is True
    assert model.c1_annual_future_heat_calendar_physical_row_end_hours == (192,)
