from __future__ import annotations

from dataclasses import replace

import pytest
from pyomo.environ import value

from steel.s4_4c6_deterministic_behaviour_anchor_validation import (
    _activate_c1_calibration_bundle,
    load_validation_config,
)
from steel.s4_4c6_deterministic_c0_temporal_validation import (
    initial_c0_state,
    load_c0_validation_config,
)
from steel.s4_4c6_deterministic_hourly_temporal_validation import (
    ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T,
    ANNUAL_RECOVERABILITY_HANDOFF_RESERVE_T_PER_FUTURE_REPLAN,
    C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    C0_HOURLY_CONTRACT_VERSION,
    C1_ANNUAL_HOURLY_CONTRACT_VERSION,
    C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T,
    C1_HOURLY_CONTRACT_VERSION,
    C1_KGF_ANNUAL_RECONCILIATION_TOLERANCE_T,
    C1_KGF1_DRY_COAL_PROGRESS_KEY,
    STATE_FEASIBILITY_TOLERANCE,
    _annual_exact_terminal_recoverable_bounds,
    _annual_banded_terminal_recoverable_bounds,
    _annual_recoverable_progress_bounds,
    _annual_initial_inventory_targets,
    _build_model,
    _c1_annual_progress_corridor_bounds,
    _c0_contract,
    _execution_product_band,
    _hourly_context,
    _requires_infeasibility_confirmation,
    _synthetic_late_year_state,
    build_hourly_annual_calendar,
    c0_annual_operational_reconciliation,
    load_hourly_annual_prices,
    HourlyTemporalValidationError,
)
from steel.s4_4c6_deterministic_temporal_repair import (
    DEFAULT_RATE_RANGES_T_H,
    initial_temporal_state,
    load_temporal_repair_config,
)
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    _temporal_origin_scrap_ledger,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


def test_state_generating_solver_tolerance_is_strict():
    assert STATE_FEASIBILITY_TOLERANCE == 1e-8
    assert ANNUAL_RECOVERABILITY_HANDOFF_RESERVE_T_PER_FUTURE_REPLAN == 0.0


def test_first_infeasible_status_requires_dual_reduction_confirmation():
    assert _requires_infeasibility_confirmation(
        "infeasible",
        attempt_index=1,
        attempt_count=2,
        confirmation_already_active=False,
    )
    assert not _requires_infeasibility_confirmation(
        "infeasible",
        attempt_index=2,
        attempt_count=2,
        confirmation_already_active=True,
    )


def test_c1_year_endpoint_lower_absorbs_only_microton_roundoff():
    lower, upper = _c1_annual_progress_corridor_bounds(
        annual_target_t=6_750_000.0,
        completed_t=6_627_358.813646918,
        endpoint_hours=8_760,
    )
    nominal_lower = 6_750_000.0 - 4_000.0 - 6_627_358.813646918
    assert lower == pytest.approx(
        nominal_lower - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
    )
    assert C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T == 4_000.0
    assert upper == pytest.approx(6_754_000.0 - 6_627_358.813646918)


def test_kgf_annual_reconciliation_band_is_one_ton_and_stateful():
    lower, upper = _annual_banded_terminal_recoverable_bounds(
        annual_target_t=1_242_500.0,
        tolerance_t=C1_KGF_ANNUAL_RECONCILIATION_TOLERANCE_T,
        completed_t=1_200_000.0,
        endpoint_hours=8_760,
        mandatory_future_rate_t_h=100.0,
        future_reachable_rate_t_h=200.0,
    )
    assert C1_KGF_ANNUAL_RECONCILIATION_TOLERANCE_T == 1.0
    assert lower == pytest.approx(42_499.0)
    assert upper == pytest.approx(42_501.0)


@pytest.fixture(scope="module")
def hourly_c1():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    behaviour = load_validation_config(REPO_ROOT / c0["behaviour_validation_config"])
    _activate_c1_calibration_bundle(c1, behaviour)
    context = _hourly_context(c1, C1_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="hourly_test_week",
        eaf_quota_target_taps=191,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=191,
    )
    return context, state, model


@pytest.fixture(scope="module")
def hourly_c0():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C0_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_c0_state(c0, episode_id="hourly_c0_test"),
        temporal_contract_version=C0_HOURLY_CONTRACT_VERSION,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C0_CONFIGURATION,
        day_index=1,
        c0_inventory_values_eur_per_t={"coke_inventory_t": 1.0},
    )
    return context, state, model


def test_hourly_model_has_hourly_global_grid_and_internal_eaf_subslots(hourly_c1):
    context, _, model = hourly_c1
    assert context.time_grid.time_step_hours == 1.0
    assert len(model.TIME) == 72
    assert len(model.EAF_SUBTIME) == 288
    assert model.eaf_internal_batch_subslots_per_hour == 4
    assert model.eaf_batch_time_contract == (
        "hourly_grid_with_internal_15_minute_eaf_subslots"
    )
    assert model.sifa_maximum_rate_step_t_h == pytest.approx(6.265638)
    assert model.sifa_minimum_direction_hours == 2.0


def test_c0_c1_common_asset_families_use_same_relative_capacity_method():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    c0_assets = c0["plant_dynamics"]["normalized_capacity_contract"]["assets"]
    c1_assets = c1["deterministic_temporal_repair"]["plant_dynamics"][
        "normalized_capacity_contract"
    ]["assets"]
    for family in ("coking_plant", "sintering_plant", "blast_furnace", "pelletizing_plant"):
        c0_rows = [row for row in c0_assets.values() if row["family"] == family]
        c1_rows = [row for row in c1_assets.values() if row["family"] == family]
        assert c0_rows and c1_rows
        assert {float(row["relative_half_width"]) for row in c0_rows} == {
            float(row["relative_half_width"]) for row in c1_rows
        }
        assert {
            float(row["ramp_fraction_of_reference_per_setpoint"])
            for row in c0_rows
        } == {
            float(row["ramp_fraction_of_reference_per_setpoint"])
            for row in c1_rows
        }
    shared_components = {
        "coking_plant_1": (135.0, 180.0),
        "sintering_plant": (200.0, 340.0),
        "blast_furnace_6": (120.0, 170.0),
        "pefa_pellet_output_t": (450.0, 600.0),
    }
    for component, expected in shared_components.items():
        assert (
            float(c0_assets[component]["resolved_minimum_t_h"]),
            float(c0_assets[component]["resolved_maximum_t_h"]),
        ) == pytest.approx(expected)
        assert (
            float(c1_assets[component]["resolved_minimum_t_h"]),
            float(c1_assets[component]["resolved_maximum_t_h"]),
        ) == pytest.approx(expected)


def test_hourly_eaf_can_represent_more_than_24_heats_per_day(hourly_c1):
    _, _, model = hourly_c1
    assert model.eaf_daily_heat_upper.upper() == 28
    assert len(model.eaf_heat_start_subslot) == 288


def test_hourly_eaf_arc_profile_is_two_power_blocks_then_zero_tap(hourly_c1):
    _, _, model = hourly_c1
    original_values = {
        int(subslot): model.eaf_heat_start_subslot[subslot].value
        for subslot in model.EAF_SUBTIME
    }
    for subslot in model.EAF_SUBTIME:
        model.eaf_heat_start_subslot[subslot].value = 0.0
    model.eaf_heat_start_subslot[0].value = 1.0
    assert value(model.eaf_melt_subslot[0]) == pytest.approx(1.0)
    assert value(model.eaf_melt_subslot[1]) == pytest.approx(1.0)
    assert value(model.eaf_tap_subslot[2]) == pytest.approx(1.0)
    assert value(model.eaf_arc_power_mw_subslot[0]) == pytest.approx(274.44444443)
    assert value(model.eaf_arc_power_mw_subslot[1]) == pytest.approx(274.44444443)
    assert value(model.eaf_arc_power_mw_subslot[2]) == pytest.approx(0.0)
    assert 0.25 * sum(
        value(model.eaf_arc_power_mw_subslot[q]) for q in range(3)
    ) == pytest.approx(model.eaf_arc_energy_mwh_per_heat)
    for subslot, original in original_values.items():
        model.eaf_heat_start_subslot[subslot].value = original


@pytest.mark.parametrize("fixture_name", ["hourly_c0", "hourly_c1"])
def test_hsm_uses_four_hour_blocks_and_bounded_boundary_steps(
    request, fixture_name
):
    _, state, model = request.getfixturevalue(fixture_name)
    assert state.hsm_last_input_t_h is not None
    assert model.hsm_temporal_block_steps == 1
    assert model.hsm_temporal_campaign_minimum_hours == 1.0
    assert model.hsm_temporal_maximum_step_t_h == 200.0
    assert len(model.hsm_temporal_block_holds) == 0
    assert len(model.hsm_temporal_step_constraints) == 144
    assert model.hsm_temporal_campaign_status == (
        "user_authorized_blocked_hourly_development_policy_not_site_truth"
    )


def test_hourly_objective_contains_only_hourly_execution_and_continuation(hourly_c1):
    _, _, model = hourly_c1
    assert model.hourly_objective_mode == (
        "scalar_procurement_plus_linear_heat_continuation"
    )
    assert len(model.TIME) == 72
    assert model.hourly_physical_feasibility_lookahead_hours == 48
    assert model.hourly_physical_tail_price_information_active is False
    assert model.hourly_physical_tail_cost_active is False
    objective = str(model.hourly_scalar_objective.expr)
    assert "drp_pellet_input[23]" in objective
    assert "drp_pellet_input[24]" not in objective
    assert "eaf_heat_start_subslot[95]" in objective
    assert "eaf_heat_start_subslot[96]" not in objective
    assert value(model.hourly_continuation_value, exception=False) is None


def test_hourly_state_contract_is_not_qh_compatible(hourly_c1):
    _, state, _ = hourly_c1
    assert state.temporal_contract_version == C1_HOURLY_CONTRACT_VERSION
    assert state.drp_last_pellet_input_t == 350.0


def test_hourly_c1_separates_direct_hdri_and_stored_cdri(hourly_c1):
    _, _, model = hourly_c1
    assert model.c1_dri_thermal_state_mode == "hdri_direct_plus_cdri_buffer"
    assert model.c1_hdri_temperature_c == 600.0
    assert model.c1_cdri_temperature_c == 50.0
    assert model.c1_cdri_max_share == 0.30
    assert model.c1_dri_buffer_thermal_or_silo_claim == (
        "cold_dri_inventory_only_no_separate_silo_or_cooling_dynamics"
    )
    for component in (
        "hdri_direct_to_eaf_t",
        "hdri_to_cdri_storage_t",
        "cdri_from_storage_to_eaf_t",
        "drp_hdri_allocation_balance",
        "eaf_dri_thermal_input_balance",
        "eaf_cdri_share_limit",
        "cdri_withdrawal_from_prior_inventory",
        "eaf_cold_dri_reheat_electricity_mwh",
    ):
        assert hasattr(model, component)


def test_hourly_c1_cdri_share_and_electricity_premium_are_hard_model_terms(hourly_c1):
    _, _, model = hourly_c1
    share_expression = str(model.eaf_cdri_share_limit[0].expr)
    electricity_expression = str(model.electricity_mwh[0].expr)
    assert "cdri_from_storage_to_eaf_t[0]" in share_expression
    assert "0.3" in share_expression
    assert "cdri_from_storage_to_eaf_t[0]" in electricity_expression


def test_c0_fixed_bf_floor_is_replaced_by_stateful_week_recoverability(hourly_c0):
    _, _, model = hourly_c0
    assert not model.normalized_capacity_aggregate_recoverability.active
    assert model.c0_fixed_bf_aggregate_floor_active is False
    assert len(model.c0_week_route_recoverability) == 6
    assert set(model.c0_week_route_audit) == {
        "C0_BOF_crude_steel_output_t",
        "C0_HSM_final_product_t",
        "C0_DSP_final_product_t",
    }
    assert model.c0_week_route_audit["C0_DSP_final_product_t"][
        "maximum_future_day_t"
    ] == pytest.approx(24.0 * 1_500_000.0 / 8_760.0)
    bof_scrap_cap_t_h = float(
        value(model.c0_bof_hourly_scrap_cap[model.TIME.first()].upper)
    )
    assert model.c0_week_route_audit["C0_BOF_crude_steel_output_t"][
        "maximum_future_day_t"
    ] == pytest.approx(bof_scrap_cap_t_h / 0.208 * 24.0)
    assert model.c0_week_terminal_inventory_bands_t["cold_slab_inventory_t"] == {
        "capacity_t": 25_000.0,
        "target_t": 12_500.0,
        "lower_t": 0.0,
        "upper_t": 25_000.0,
    }
    assert model.c0_week_terminal_inventory_basis == (
        "governed_fixed_initial_terminal_quantity_with_one_percent_band"
    )


def test_c0_objective_values_executed_inventory_without_tail_state(hourly_c0):
    _, _, model = hourly_c0
    assert model.hourly_objective_mode == (
        "scalar_procurement_plus_calibrated_inventory_continuation"
    )
    assert set(model.c0_inventory_shortfall_t) == {
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    }
    assert "coke_inventory[23]" in str(
        model.c0_inventory_continuation_constraints[1].expr
    )
    assert "coke_inventory[47]" not in str(model.hourly_scalar_objective.expr)


def test_c0_reporting_denominator_is_separate_from_physical_route_output():
    c0 = load_c0_validation_config()
    material = c0["c0_material_contract"]
    assert material["reporting_final_product_t_y"] == pytest.approx(6_750_000.0)
    assert material["physical_bof_liquid_steel_t_y"] == pytest.approx(6_750_000.0)
    assert material["physical_final_product_t_y"] == pytest.approx(6_468_750.0)
    assert material["reporting_normalization_factor"] == pytest.approx(
        6_750_000.0 / 6_468_750.0
    )


def test_c0_week_route_band_is_the_user_authorized_one_percent():
    c0 = load_c0_validation_config()
    rolling = c0["c0_hourly_rolling_contract"]
    assert rolling["route_band_fraction"] == pytest.approx(0.01)
    assert rolling["route_band_basis"] == (
        "user_authorized_one_percent_tolerance_for_rounded_MER_route_anchors"
    )


def test_c0_aggregate_final_product_uses_the_same_route_band(hourly_c0):
    context, state, _ = hourly_c0
    c0 = load_c0_validation_config()
    lower, upper = _execution_product_band(
        context,
        state,
        configuration=C0_CONFIGURATION,
        c0_config=c0,
    )
    central = c0["c0_material_contract"]["physical_final_product_t_y"] * 24 / 8760
    assert lower == 0.0
    assert upper > central


def test_c1_execution_band_leaves_daily_lower_to_stateful_witness_until_terminal():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
    )
    lower, upper = _execution_product_band(
        context,
        state,
        configuration=C1_CONFIGURATION,
        c0_config=c0,
        c1_config=c1,
    )
    assert lower == 0.0
    assert upper == pytest.approx(6_754_000.0)
    final_state = replace(
        state,
        executed_hours=8_736,
        executed_intervals=8_736,
        cumulative_production_t=6_730_000.0,
    )
    assert _execution_product_band(
        context,
        final_state,
        configuration=C1_CONFIGURATION,
        c0_config=c0,
        c1_config=c1,
    ) == pytest.approx((15_999.9999, 24_000.0))


def test_c0_day_six_uses_physical_tail_to_prove_week_closure():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C0_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_c0_state(c0, episode_id="hourly_c0_day_six_test"),
        temporal_contract_version=C0_HOURLY_CONTRACT_VERSION,
        executed_hours=120,
        executed_intervals=120,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C0_CONFIGURATION,
        day_index=6,
    )
    assert len(model.c0_physical_tail_week_closure) == 6
    assert "coke_inventory[47]" in str(
        model.c0_inventory_continuation_constraints[2].expr
    )


def test_c0_day_five_uses_exact_72h_week_closure_not_abstract_future_proxy():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C0_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_c0_state(c0, episode_id="hourly_c0_day_five_test"),
        temporal_contract_version=C0_HOURLY_CONTRACT_VERSION,
        executed_hours=96,
        executed_intervals=96,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C0_CONFIGURATION,
        day_index=5,
    )
    assert len(model.TIME) == 72
    assert len(model.c0_physical_tail_week_closure) == 6
    assert not hasattr(model, "c0_future_hot_metal_recoverable_t")


def test_hourly_annual_cold_start_inventory_contract_is_configuration_complete():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    c0_targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C0_CONFIGURATION
    )
    c1_targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C1_CONFIGURATION
    )
    assert c0_targets == {
        "coke_inventory": 360.0,
        "sinter_inventory": 320.0,
        "hot_iron_inventory": 250.0,
        "cold_slab_inventory": 12_500.0,
        "pellet_inventory": 25_000.0,
    }
    assert c1_targets == {
        "dri_inventory": 0.0,
        "coke_inventory": 180.0,
        "sinter_inventory": 320.0,
        "hot_iron_inventory": 250.0,
        "cold_slab_inventory": 12_500.0,
        "eaf_slab_inventory": 0.0,
        "pellet_inventory": 50_000.0,
    }


def test_c1_annual_kgf_anchor_is_validation_only_and_coke_balance_drives_output():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_kgf_recoverability",
        eaf_quota_target_taps=191,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C1_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=191,
        annual_readiness=True,
        annual_initial_inventory_targets_t=targets,
    )
    assert not hasattr(model, "kgf1_execution_route_anchor")
    assert not hasattr(model, "kgf1_annual_execution_recoverability")
    assert not hasattr(model, "kgf1_annual_physical_tail_recoverability")
    assert model.kgf1_anchor_constraints_active is False
    assert model.kgf1_anchor_role == (
        "validation_only_mer_annual_reference_physical_coke_balance_drives_output"
    )
    assert hasattr(model, "c1_annual_joint_residual_product_certificate")
    assert float(model.dsp_final_product_horizon_cap.upper()) == pytest.approx(
        1_500_000.0
    )
    assert float(model.imported_slab_horizon_cap.upper()) == pytest.approx(
        600_000.0
    )
    assert len(model.c1_annual_residual_capacity_limits) == 21
    assert model.c1_annual_joint_residual_policy == (
        "shared_calendar_integer_heat_and_shiftable_daily_route_continuation_v13"
    )
    assert model.c1_annual_joint_residual_target_taps == 9_945
    assert model.c1_annual_joint_residual_product_lower_t == 6_746_000.0
    assert model.c1_annual_recoverability_numerical_tolerance_t == 1e-4
    assert len(model.c1_future_continuous_reachability) > 0
    assert hasattr(model, "c1_future_hsm_input_t")
    assert model.c1_annual_joint_residual_certified_horizon_hours == 24
    assert model.c1_annual_joint_residual_physical_horizon_hours == 72
    assert model.c1_annual_joint_residual_future_hours == 8_736
    assert model.c1_annual_joint_residual_downstream_future_hours == 8_736
    assert model.c1_annual_joint_residual_downstream_boundary_reserve_hours == 0
    assert model.c1_annual_import_recoverability_hours == 8_736
    assert model.c1_annual_tail_import_recoverability_hours == 8_712
    assert model.c1_annual_minimum_imported_slab_t > 0.0
    assert hasattr(model, "c1_annual_executed_import_deadline")
    assert hasattr(model, "c1_annual_physical_tail_import_viability")
    assert model.c1_annual_import_deadline_policy == (
        "source_to_equation_minimum_import_with_executed_and_physical_tail_viability"
    )
    assert hasattr(model, "c1_annual_physical_tail_recursive_product_certificate")
    assert len(model.c1_annual_physical_tail_residual_limits) >= 20
    assert model.c1_annual_recursive_tail_future_hours == 8_712
    assert model.c1_annual_recursive_handoff_horizon_hours == 48
    assert model.c1_annual_recursive_tail_policy == (
        "first_price_blind_tail_day_ends_inside_annual_recoverable_set"
    )
    assert len(model.hourly_physical_tail_product_handoff) == 1
    assert model.hourly_physical_tail_handoff_policy == (
        "c0_route_recoverability_or_c1_shared_calendar_continuation"
    )
    assert model.c1_physical_horizon_progress_audit["physical_horizon_hours"] == 72
    assert model.kgf1_annual_recoverability_audit["completed_before_t"] == 0.0
    assert model.kgf1_annual_recoverability_audit["constraint_active"] is False
    assert model.kgf1_annual_recoverability_audit["annual_reference_t"] == pytest.approx(
        c1["deterministic_temporal_repair"]["kgf1_route_scale_reconciliation"]
        ["annual_dry_coal_target_t_y"]
    )
    assert C1_KGF1_DRY_COAL_PROGRESS_KEY not in state.cumulative_route_progress_t


def test_c1_annual_future_heat_calendar_is_integer_price_blind_and_tail_linked():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_calendar_continuation",
        eaf_quota_target_taps=191,
        eaf_quota_completed_taps=0,
    )
    future_rows = [
        {
            "calendar_day_index": day,
            "day_length_hours": 24,
            "lower": 20,
            "upper": 32,
            "quota_period_index": 0,
            "quota_period_target": 191,
            "quota_period_boundary": int(day == 7),
        }
        for day in range(2, 8)
    ]
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=191,
        annual_readiness=True,
        annual_initial_inventory_targets_t=_annual_initial_inventory_targets(
            c0, c1, configuration=C1_CONFIGURATION
        ),
        annual_future_heat_calendar=future_rows,
    )
    assert model.c1_annual_future_heat_calendar_complete is True
    assert model.c1_annual_future_heat_calendar_policy == (
        "price_blind_calendar_day_integer_taps_with_quota_equalities_and_physical_tail_link"
    )
    assert len(model.c1_future_eaf_taps_by_calendar_day) == 6
    expressions = " ".join(
        str(model.c1_annual_future_heat_calendar_constraints[index].expr)
        for index in model.c1_annual_future_heat_calendar_constraints
    )
    assert len(model.c1_annual_future_heat_calendar_constraints) >= 16
    assert "c1_future_eaf_taps_by_calendar_day[0]" in expressions
    assert model.c1_annual_future_heat_calendar_physical_row_end_hours[:2] == (
        48,
        72,
    )
    assert "price" not in expressions.lower()
    assert model.c1_annual_future_daily_route_policy == (
        "price_blind_shiftable_daily_origin_downstream_inventory_witness_v1"
    )
    assert len(model.c1_future_slab_inventory_by_calendar_day_t) == 6
    daily_expressions = " ".join(
        str(model.c1_annual_future_daily_route_constraints[index].expr)
        for index in model.c1_annual_future_daily_route_constraints
    )
    assert "c1_future_slab_inventory_by_calendar_day_t[0]" in daily_expressions
    assert "cold_slab_inventory[23]" in daily_expressions
    assert "price" not in daily_expressions.lower()


def test_c1_physical_tail_carries_calendar_heat_bounds_and_quota_boundary():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_tail_quota_test",
        eaf_quota_target_taps=77,
        eaf_quota_completed_taps=0,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C1_CONFIGURATION
    )
    tail_days = [
        {
            "calendar_day_index": 2,
            "start_hour": 24,
            "end_hour": 48,
            "lower_taps": 23,
            "upper_taps": 29,
            "quota_period_index": 5,
            "closes_current_quota": False,
            "remaining_quota_taps": 77,
        },
        {
            "calendar_day_index": 3,
            "start_hour": 48,
            "end_hour": 72,
            "lower_taps": 23,
            "upper_taps": 29,
            "quota_period_index": 5,
            "closes_current_quota": True,
            "remaining_quota_taps": 77,
        },
    ]
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=23,
        upper_taps=29,
        remaining_taps=77,
        annual_readiness=True,
        annual_initial_inventory_targets_t=targets,
        physical_tail_heat_days=tail_days,
    )
    assert len(model.eaf_physical_tail_calendar_constraints) == 6
    assert model.eaf_physical_tail_calendar_audit == tail_days
    quota_expression = str(model.eaf_physical_tail_calendar_constraints[5].expr)
    assert "eaf_heat_start_subslot[285]" in quota_expression
    assert "eaf_heat_start_subslot[286]" not in quota_expression
    assert "77" in quota_expression


def test_c1_recoverable_tail_does_not_force_cyclic_material_inventory_closure():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="recoverable_inventory_tail_test",
        eaf_quota_target_taps=191,
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=191,
        annual_readiness=True,
        annual_initial_inventory_targets_t=_annual_initial_inventory_targets(
            c0, c1, configuration=C1_CONFIGURATION
        ),
    )
    for name in (
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
        "dri_terminal_equality",
        "eaf_slab_terminal",
    ):
        assert not getattr(model, name).active, name
    if hasattr(model, "pellet_terminal"):
        assert not model.pellet_terminal.active
    assert model.c1_inventory_terminal_policy == (
        "executed_state_with_bounded_physical_continuation_no_cyclic_tail_closure"
    )


def test_c0_hourly_annual_prefix_has_no_week_terminal_and_values_executed_state():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C0_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_c0_state(c0, episode_id="c0_annual_prefix"),
        temporal_contract_version=C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C0_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C0_CONFIGURATION,
        annual_readiness=True,
        annual_initial_inventory_targets_t=targets,
        c0_inventory_values_eur_per_t={"coke_inventory_t": 1.0},
    )
    assert model.hourly_objective_mode == (
        "scalar_procurement_plus_calibrated_inventory_continuation"
    )
    assert len(model.c0_annual_route_progress) == 6
    assert len(model.c0_physical_tail_route_handoff) == 6
    assert len(model.hourly_physical_tail_product_handoff) == 2
    assert not hasattr(model, "rolling_terminal_inventory_band")
    assert model.hourly_physical_tail_inventory_policy == (
        "balance_capacity_and_executed_state_only_until_true_year_terminal"
    )
    assert not hasattr(model, "c0_week_route_recoverability")
    continuation_constraints = " ".join(
        str(model.c0_inventory_continuation_constraints[index].expr)
        for index in model.c0_inventory_continuation_constraints
    )
    assert "coke_inventory[23]" in continuation_constraints
    assert "coke_inventory[47]" not in continuation_constraints
    assert model.hourly_annual_inventory_terminal_active is False


def test_c0_day_26_route_lower_is_recoverable_not_an_exact_daily_quota():
    lower, upper = _annual_recoverable_progress_bounds(
        annual_target_t=6_750_000.0,
        band_fraction=0.01,
        completed_t=457_705.47945,
        endpoint_hours=624,
    )
    assert lower == 0.0
    assert upper > 18_337.54


def test_annual_recoverability_converges_to_the_terminal_band():
    lower, upper = _annual_recoverable_progress_bounds(
        annual_target_t=6_750_000.0,
        band_fraction=0.01,
        completed_t=6_650_000.0,
        endpoint_hours=8760,
    )
    assert lower == pytest.approx(32_500.0)
    assert upper == pytest.approx(167_500.0)


def test_c0_exact_terminal_recoverability_allows_timing_but_closes_year():
    early_lower, early_upper = _annual_exact_terminal_recoverable_bounds(
        annual_target_t=6_750_000.0,
        completed_t=0.0,
        endpoint_hours=24,
    )
    assert early_lower == 0.0
    assert early_upper == pytest.approx(6_750_000.0)
    final_lower, final_upper = _annual_exact_terminal_recoverable_bounds(
        annual_target_t=6_750_000.0,
        completed_t=6_730_000.0,
        endpoint_hours=8760,
    )
    assert final_lower == pytest.approx(20_000.0)
    assert final_upper == pytest.approx(20_000.0)


def test_c0_annual_joint_material_reconciliation_has_positive_headroom():
    certificate = c0_annual_operational_reconciliation(
        load_c0_validation_config()
    )
    assert certificate["passed"] is True
    assert certificate["cyclic_inventory_net_supply_t"] == 0.0
    rows = {row["flow_id"]: row for row in certificate["rows"]}
    assert set(rows) == {
        "coke_t",
        "sinter_t",
        "pellets_t",
        "bof_scrap_t",
        "hot_metal_t",
    }
    assert rows["coke_t"]["headroom_t"] > 0.0
    assert rows["pellets_t"]["headroom_t"] > 0.0
    assert rows["bof_scrap_t"]["annual_demand_t"] == pytest.approx(1_404_000.0)
    assert rows["bof_scrap_t"]["annual_reachable_supply_t"] == pytest.approx(
        1_410_000.0
    )
    assert rows["bof_scrap_t"]["headroom_t"] == pytest.approx(6_000.0)


def test_c0_annual_model_embeds_one_joint_net_terminal_material_certificate():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C0_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_c0_state(c0, episode_id="joint_residual_contract"),
        temporal_contract_version=C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C0_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C0_CONFIGURATION,
        annual_readiness=True,
        annual_initial_inventory_targets_t=targets,
    )
    assert model.c0_annual_coupled_residual_policy == (
        "joint_net_of_terminal_inventory_material_certificate_v1"
    )
    assert len(model.c0_annual_coupled_residual_limits) == 4
    assert hasattr(model, "c0_annual_coupled_residual_scrap")


def test_hourly_annual_terminal_uses_executed_endpoint_only_on_true_year_end():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_terminal_test",
        eaf_quota_target_taps=191,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C1_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=191,
        annual_readiness=True,
        final_year_day=True,
        annual_initial_inventory_targets_t=targets,
    )
    expressions = " ".join(
        str(model.hourly_annual_inventory_terminal[index].expr)
        for index in model.hourly_annual_inventory_terminal
    )
    assert model.hourly_annual_inventory_terminal_active is True
    assert model.hourly_annual_inventory_terminal_band_fraction == pytest.approx(
        0.10
    )
    assert model.hourly_annual_inventory_terminal_band_fraction_by_component[
        "pellet_inventory"
    ] == pytest.approx(0.10)
    assert model.hourly_annual_inventory_terminal_bands_t["coke_inventory"] == {
        "target_t": 180.0,
        "capacity_t": 360.0,
        "lower_t": 144.0,
        "upper_t": 216.0,
        "band_fraction": 0.10,
        "band_scale_basis": "modelled_inventory_capacity",
    }
    assert model.hourly_annual_inventory_terminal_bands_t["pellet_inventory"] == {
        "target_t": 50_000.0,
        "capacity_t": 50_000.0,
        "lower_t": 45_000.0,
        "upper_t": 50_000.0,
        "band_fraction": 0.10,
        "band_scale_basis": "terminal_target_no_finite_modelled_capacity",
    }
    assert "dri_inventory[23]" in expressions
    assert "pellet_inventory[23]" in expressions
    assert "inventory[47]" not in expressions


def test_hourly_annual_calendar_is_exact_and_retains_dst_day_lengths():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    calendar = build_hourly_annual_calendar(c1)
    assert len(calendar) == 8760
    assert calendar["timestamp_utc"].is_unique
    counts = (
        calendar.groupby("calendar_day_index")["local_day_length_hours"]
        .first()
        .value_counts()
        .to_dict()
    )
    assert counts == {24: 363, 23: 1, 25: 1}
    assert not calendar["maintenance_active"].any()


def test_annual_price_interface_is_exact_and_fail_closed():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    calendar = build_hourly_annual_calendar(c1)
    flat = load_hourly_annual_prices(calendar, strategy="price_insensitive")
    assert len(flat) == 8760
    assert set(flat["price_eur_per_mwh"]) == {80.0}

    partial_qh_source = REPO_ROOT / (
        "data/02_Forecasting/01_DA_prices/scenario_evaluation/"
        "20260729_strict_inputs/qh_prices_2026.csv"
    )
    with pytest.raises(HourlyTemporalValidationError):
        load_hourly_annual_prices(
            calendar,
            strategy="perfect_foresight_oracle",
            source_path=partial_qh_source,
            source_is_realised_oracle=True,
        )


@pytest.mark.parametrize("day_length", [23, 25])
def test_hourly_builder_accepts_dst_execution_days(day_length):
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(
        c1, C0_ANNUAL_HOURLY_CONTRACT_VERSION, execution_hours=day_length
    )
    state = replace(
        initial_c0_state(c0, episode_id=f"dst_{day_length}"),
        temporal_contract_version=C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C0_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * day_length,
        configuration=C0_CONFIGURATION,
        annual_readiness=True,
        annual_initial_inventory_targets_t=targets,
    )
    assert model.hourly_execution_hours == day_length
    assert len(model.TIME) == 72


def test_penultimate_day_proves_year_inventory_terminal_in_physical_tail():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    context = _hourly_context(c1, C1_ANNUAL_HOURLY_CONTRACT_VERSION)
    state = replace(
        initial_temporal_state(c1),
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_terminal_recovery_test",
        eaf_quota_target_taps=54,
    )
    targets = _annual_initial_inventory_targets(
        c0, c1, configuration=C1_CONFIGURATION
    )
    model, _, _ = _build_model(
        context,
        state,
        c0,
        c1,
        (80.0,) * 24,
        configuration=C1_CONFIGURATION,
        lower_taps=26,
        upper_taps=28,
        remaining_taps=54,
        year_terminal_remaining_taps=386,
        annual_readiness=True,
        year_terminal_recovery_index=47,
        annual_initial_inventory_targets_t=targets,
    )
    expressions = " ".join(
        str(model.hourly_annual_inventory_terminal[index].expr)
        for index in model.hourly_annual_inventory_terminal
    )
    assert model.hourly_annual_inventory_terminal_active is False
    assert model.hourly_annual_inventory_recovery_active is True
    assert model.hourly_year_end_eaf_tap_recovery.lower == 386
    assert model.hourly_year_end_eaf_tap_recovery.upper == 386
    assert hasattr(model, "c1_annual_joint_residual_product_certificate")
    assert model.c1_annual_joint_residual_product_certificate.active is False
    assert model.c1_annual_residual_capacity_limits.active is False
    assert model.c1_future_continuous_reachability.active is False
    assert model.c1_annual_executed_import_deadline.active is False
    assert model.c1_annual_physical_tail_import_viability.active is False
    assert model.c1_annual_physical_tail_residual_limits.active is False
    assert (
        model.c1_annual_physical_tail_recursive_product_certificate.active is False
    )
    assert model.c1_annual_visible_endpoint_certificate_policy == (
        "exact_physical_endpoint_replaces_all_abstract_future_residuals"
    )
    assert model.hourly_annual_inventory_terminal_index == 47
    assert model.hourly_year_end_future_replan_handoffs == 1
    assert model.hourly_year_end_numerical_handoff_reserve_t == pytest.approx(0.0)
    assert "dri_inventory[47]" in expressions
    assert "pellet_inventory[47]" in expressions


def test_final_day_physical_tail_splits_scrap_cap_at_annual_reset():
    c0 = load_c0_validation_config()
    c1 = load_temporal_repair_config(REPO_ROOT / c0["base_temporal_config"])
    state = replace(
        _synthetic_late_year_state(c0, c1, configuration=C0_CONFIGURATION),
        executed_hours=8736,
        executed_intervals=8736,
    )
    contract = _c0_contract(
        c0,
        (0.0, 1.0e9),
        contract_version=C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    )
    ledger = _temporal_origin_scrap_ledger(
        contract,
        state,
        planning_horizon_hours=48,
        deadline_hours=(24,),
    )
    assert ledger["annual_quota_reset_crossed_in_physical_tail"] is True
    assert (
        ledger["site_total_scrap_supply_deadline_caps_t"][24]
        < ledger["site_total_scrap_supply_cap_t"]
    )
