from __future__ import annotations

from dataclasses import replace

import pytest
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import value

from steel.s4_4c6_deterministic_c0_temporal_validation import (
    C0_TEMPORAL_CONTRACT_VERSION,
    C0TemporalValidationError,
    build_c0_temporal_model,
    initial_c0_state,
    load_c0_validation_config,
    prepare_c0_context,
    validate_c0_state,
)
from steel.s4_4c6_deterministic_temporal_repair import load_temporal_repair_config
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


@pytest.fixture(scope="module")
def c0_contract():
    config = load_c0_validation_config()
    temporal = load_temporal_repair_config(REPO_ROOT / config["base_temporal_config"])
    context = prepare_c0_context(config, temporal)
    state = initial_c0_state(config, episode_id="pytest_c0_temporal")
    model, procurement, band = build_c0_temporal_model(
        context, state, config, (80.0,) * 96
    )
    return config, context, state, model, procurement, band


def test_c0_state_contract_rejects_c1_or_old_states(c0_contract):
    config, _, state, *_ = c0_contract
    assert state.temporal_contract_version == C0_TEMPORAL_CONTRACT_VERSION
    with pytest.raises(C0TemporalValidationError):
        validate_c0_state(replace(state, configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF"), config)
    with pytest.raises(C0TemporalValidationError):
        validate_c0_state(replace(state, temporal_contract_version="c1_deterministic_scalar_temporal_v6"), config)


def test_c0_material_interface_separates_activity_sinter_and_pellets(c0_contract):
    config, context, _, model, *_ = c0_contract
    assert model.c0_bf_material_interface_status == (
        "annual_mer_reconciliation_separate_from_bf_activity_proxy"
    )
    material = config["c0_material_contract"]
    assert material["sinter_t_per_t_hot_metal"] == pytest.approx(3_468_750 / 5_906_250)
    assert material["pellets_t_per_t_hot_metal"] == pytest.approx(5_718_750 / 5_906_250)
    assert model.bf_activity_proxy is not model.bf_sinter_input
    assert hasattr(model, "bf_pellet_input_t")
    assert hasattr(model, "pellet_balance")
    assert model.pellet_origin_ledger_status.startswith(
        "physical_origin_conservation"
    )
    assert value(model.external_bf_pellets_to_bf_t[0]) == pytest.approx(
        1_406_250.0 / 8_760.0 * 0.25
    )
    assert value(model.external_dr_pellets_to_drp_t[0]) == pytest.approx(0.0)
    pellet_cost_flows = {
        flow["flow_id"]: flow["model_component_attribute"]
        for flow in context.cost_flows
        if "PELLET" in str(flow["flow_id"])
    }
    assert pellet_cost_flows["C0_MAT_IMPORTED_BF_PELLETS"] == (
        "external_bf_pellets_to_bf_t"
    )
    assert model.c0_bf_coke_t_per_t_hot_metal == pytest.approx(1.6875 / 5.90625)
    assert model.c0_bf_coke_t_per_t_hot_metal != pytest.approx(0.359)
    assert material["final_product_t_y"] == pytest.approx(6_750_000.0)
    assert material["raw_mer_liquid_steel_t_y"] == pytest.approx(7_200_000.0)
    assert material["physical_minima_scaling_policy"] == (
        "do_not_scale_technical_minima_proportionally_to_annual_output"
    )
    assert material["annual_internal_scrap_cap_t_y"] == pytest.approx(562_500.0)
    assert material["annual_external_scrap_cap_t_y"] == pytest.approx(847_500.0)
    assert material["annual_site_scrap_cap_t_y"] == pytest.approx(1_410_000.0)
    assert material["annual_bof_scrap_cap_t_y"] == pytest.approx(1_410_000.0)
    assert (
        material["annual_external_scrap_cap_t_y"]
        + material["annual_internal_scrap_cap_t_y"]
    ) == pytest.approx(material["annual_site_scrap_cap_t_y"])
    presentation = config["presentation_contract"]
    assert presentation["canonical_final_product_t_y"] == pytest.approx(6_750_000.0)
    assert presentation["figure_formats"] == ["png"]
    for normalized in presentation["downstream_normalization"].values():
        assert normalized["hsm_final_output_t_y"] + normalized[
            "dsp_final_output_t_y"
        ] == pytest.approx(6_750_000.0)


def test_c0_tail_is_recoverable_but_capacities_remain_hard(c0_contract):
    _, _, _, model, *_ = c0_contract
    assert model.c0_inventory_terminal_policy.startswith("executed_state_with_bounded")
    assert set(model.temporal_tail_cyclic_closures_replaced) == {
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
        "pellet_terminal",
    }
    for name in ("coke_capacity", "sinter_capacity", "hot_iron_capacity", "cold_slab_capacity", "pellet_capacity"):
        assert getattr(model, name).active


def test_c0_dynamics_and_configuration_assets_are_explicit(c0_contract):
    config, _, _, model, *_ = c0_contract
    assert model.c0_temporal_plant_dynamics_status == (
        "user_authorized_development_policy_not_site_truth"
    )
    assert model.kgf1_setpoint_block_steps == 16
    assert model.kgf2_setpoint_block_steps == 16
    assert model.bf6_setpoint_block_steps == 4
    assert model.bf7_setpoint_block_steps == 4
    assert model.pefa_setpoint_block_steps == 16
    assert model.c0_temporal_operating_ranges_t_h["coking_plant_1"] == pytest.approx(
        (135.0, 180.0)
    )
    assert config["plant_dynamics"]["operating_envelope_status"] == (
        "user_authorized_shared_C0_C1_development_bands_near_source_anchors_not_technical_capacity"
    )
    assert not hasattr(model, "drp_pellet_input")
    assert not hasattr(model, "eaf_heat_start")
    assert not hasattr(model, "vn25_electricity_mwh")


def test_c0_normalized_capacity_contract_is_flat_calibrated_and_has_no_fixed_bf_floor(
    c0_contract,
):
    config, _, _, model, *_ = c0_contract
    normalized = config["plant_dynamics"]["normalized_capacity_contract"]
    assert normalized["price_response_not_used_for_calibration"] is True
    assert model.normalized_capacity_price_response_used_for_calibration is False
    assert len(model.normalized_capacity_envelope_constraints) == 2 * 6 * 192
    for component_name, row in normalized["assets"].items():
        reference = float(row["reference_rate_t_h"])
        assert model.normalized_capacity_contract[component_name][
            "reference_rate_t_h"
        ] == pytest.approx(reference)
        if not str(row.get("lower_policy", "")).startswith("user_authorized_"):
            assert float(row["resolved_minimum_t_h"]) >= (
                reference * (1.0 - float(row["relative_half_width"])) - 1e-5
            )
        if not str(row.get("upper_policy", "")).startswith("user_authorized_"):
            assert float(row["resolved_maximum_t_h"]) <= (
                reference * (1.0 + float(row["relative_half_width"])) + 1e-5
            )
    assert model.normalized_capacity_aggregate_recoverability_floors == {}
    assert len(model.normalized_capacity_aggregate_recoverability) == 0
    assert config["plant_dynamics"]["active_operating_ranges_t_h"][
        "sintering_plant"
    ] == pytest.approx((200.0, 340.0))
    assert config["plant_dynamics"]["sifa"]["ramp_t_h_per_hour"] == pytest.approx(
        7.676265
    )
    assert config["plant_dynamics"]["active_operating_ranges_t_h"][
        "coking_plant_1"
    ] == pytest.approx((135.0, 180.0))
    assert normalized["assets"]["pefa_pellet_output_t"][
        "resolved_minimum_t_h"
    ] == pytest.approx(450.0)
    assert normalized["assets"]["pefa_pellet_output_t"][
        "resolved_maximum_t_h"
    ] == pytest.approx(600.0)
    assert config["plant_dynamics"]["pefa"]["maximum_step_t_h"] == pytest.approx(
        6.533244
    )
    assert config["plant_dynamics"]["active_operating_ranges_t_h"][
        "coking_plant_2"
    ] == pytest.approx((105.0, 150.0))
    superseded = normalized["superseded_aggregate_floor"]
    assert superseded["components"] == ["blast_furnace_6", "blast_furnace_7"]
    assert superseded["minimum_combined_rate_t_h"] == pytest.approx(304.61538462)


def test_c0_downstream_uses_shared_hourly_holds_and_dsp_envelope(c0_contract):
    config, _, _, model, *_ = c0_contract
    downstream = config["plant_dynamics"]["downstream_temporal_contract"]
    assert model.hsm_temporal_block_steps == 4
    assert model.dsp_temporal_block_steps == 4
    assert len(model.hsm_temporal_block_holds) == 144
    assert len(model.hsm_temporal_step_constraints) == 96
    assert len(model.dsp_temporal_block_holds) == 144
    assert len(model.dsp_temporal_output_cap) == 192
    assert downstream["dsp_final_product_max_t_h"] == pytest.approx(
        1_500_000.0 / 8_760.0
    )


def test_c0_scrap_origin_is_conserved_and_only_external_is_costed(c0_contract):
    _, _, _, model, procurement, _ = c0_contract
    assert hasattr(model, "c0_bof_scrap_origin_balance")
    assert hasattr(model, "c0_external_scrap_deadline_caps")
    assert hasattr(model, "c0_internal_scrap_deadline_caps")
    objective_names = {variable.parent_component().name for variable in identify_variables(procurement)}
    assert "external_scrap_to_bof_t" in objective_names
    assert "internal_scrap_to_bof_t" not in objective_names


def test_c0_generator_contract_is_aggregate_and_unchanged(c0_contract):
    _, context, _, model, *_ = c0_contract
    contract = context.c0_aggregate_generator
    assert contract["electricity_efficiency"] == pytest.approx(0.345)
    assert contract["electrical_capacity_mw"] == pytest.approx(770.0)
    assert contract["total_fuel_volume_cap_nm3_h"] == pytest.approx(900_000.0)
    assert model.aggregate_generator_technical_interface_active is True
    assert not hasattr(model, "vn25_minimum_output")


def test_c0_objective_contains_execution_variables_only(c0_contract):
    _, _, _, model, procurement, band = c0_contract
    assert model.c0_objective_mode == "scalar_procurement_only"
    assert band[0] <= band[1]
    variable_indices = {
        int(variable.index())
        for variable in identify_variables(procurement)
        if isinstance(variable.index(), int)
    }
    assert variable_indices
    assert max(variable_indices) < 96
