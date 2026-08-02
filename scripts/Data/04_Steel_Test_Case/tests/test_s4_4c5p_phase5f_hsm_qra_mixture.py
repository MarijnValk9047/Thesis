from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pyomo.environ import value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _c0_real_anchor_energy_recovery_interfaces,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    S44B_INPUT_DIR,
    S44CModelBuilderError,
    _build_c0_inputs,
    _build_c0_model,
    _load_tables,
)


GENERATOR_CONFIG = {
    "enabled": True,
    "electricity_efficiency": 0.345,
    "total_fuel_volume_cap_nm3_h": 900_000.0,
    "natural_gas_lhv_mj_per_nm3": 35.8,
    "electrical_capacity_mw": 770.0,
    "export_allowed": False,
}
BRIDGE_CONFIG = {
    "enabled": True,
    "inferred_low_case_full_site_ng_floor_pj_y": 8.005,
    "already_represented_fixed_ng_pj_y": 0.0,
    "already_represented_fixed_ng_component_id": "none_identified",
    "already_represented_fixed_ng_derivation": "explicit_zero_no_overlap_identified",
    "flexible_other_site_heat_service_envelope_pj_y": 3.07,
    "normal_case_flexible_ng_validation_reference_pj_y": 1.65,
}


def _policy(ng_volume_fraction: float, cog_volume_fraction: float, *, displace: bool):
    return {
        "basis": "qra_volumetric_design_flow_sensitivity",
        "ng_volume_fraction": ng_volume_fraction,
        "cog_volume_fraction": cog_volume_fraction,
        "ng_lhv_mj_per_nm3": 37.5,
        "cog_lhv_mj_per_nm3": 18.5,
        "block_hours": 24,
        "energy_share_tolerance_fraction": 0.0,
        "displace_from_c0_fixed_ng_bridge": displace,
    }


def _c0_model(policy, *, horizon_hours: int = 24):
    generator, bridge = _c0_real_anchor_energy_recovery_interfaces(
        {
            "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
            "c0_full_site_energy_bridge": BRIDGE_CONFIG,
        }
    )
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=horizon_hours,
        target_multiplier=1.0,
    )
    return _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        aggregate_generator_technical_interface=generator,
        full_site_energy_bridge=bridge,
        hsm_source_mix_policy=policy,
    )


def test_reference_qra_volume_mix_is_converted_once_to_lhv_energy_share() -> None:
    model = _c0_model(_policy(0.45, 0.55, displace=True))
    expected = 0.45 * 37.5 / (0.45 * 37.5 + 0.55 * 18.5)

    assert model.hsm_eligible_carriers == ("COG", "NG")
    assert model.hsm_source_mix_block_hours == 24
    assert model.hsm_ng_energy_share_target == pytest.approx(expected)
    assert model.hsm_ng_energy_share_target != pytest.approx(expected * (37.5 / 18.5))
    assert model.bfg_to_hsm[0].fixed and value(model.bfg_to_hsm[0]) == pytest.approx(0.0)
    assert model.bofg_to_hsm[0].fixed and value(model.bofg_to_hsm[0]) == pytest.approx(0.0)


def test_reference_qra_mix_is_the_default_active_hsm_controller_policy() -> None:
    model = _c0_model(None)
    expected = 0.45 * 37.5 / (0.45 * 37.5 + 0.55 * 18.5)

    assert model.hsm_source_mix_policy_active is True
    assert model.hsm_eligible_carriers == ("COG", "NG")
    assert value(model.hsm_ng_energy_share_target) == pytest.approx(expected)
    assert model.hsm_source_mix_basis == (
        "qra_reference_volumetric_design_flow_45_ng_55_cog"
    )


def test_explicit_empty_policy_retains_labelled_historical_allocation() -> None:
    model = _c0_model({})

    assert model.hsm_source_mix_policy_active is False
    assert model.hsm_eligible_carriers == ("BFG", "COG", "BOFG", "NG")


def test_heracless_qra_volume_mix_converts_to_89_percent_ng_energy() -> None:
    model = _c0_model(_policy(0.80, 0.20, displace=False))
    assert model.hsm_ng_energy_share_target == pytest.approx(
        0.80 * 37.5 / (0.80 * 37.5 + 0.20 * 18.5)
    )


def test_incomplete_forecast_tail_is_not_constrained_as_an_hourly_mix() -> None:
    model = _c0_model(_policy(0.45, 0.55, displace=True), horizon_hours=25)
    assert len(model.hsm_source_mix_constraints) == 2


def test_reference_mix_is_24h_not_hourly_and_reclassifies_fixed_ng_without_addition() -> None:
    model = _c0_model(_policy(0.45, 0.55, displace=True))
    share = model.hsm_ng_energy_share_target
    for t in model.TIME:
        model.hot_strip_mill[t].set_value(10.0)
        heat = value(model.hsm_reheat_demand_mwh[t])
        # Deliberately vary the hourly split while preserving the 24-hour mix.
        hourly_share = share - 0.10 if int(t) < 12 else share + 0.10
        model.ng_to_hsm_mwh[t].set_value(hourly_share * heat)
        model.cog_to_hsm[t].set_value((1.0 - hourly_share) * heat)

    total_heat = sum(value(model.hsm_reheat_demand_mwh[t]) for t in model.TIME)
    total_ng = sum(value(model.ng_to_hsm_mwh[t]) for t in model.TIME)
    gross_fixed = sum(
        value(model.full_site_fixed_ng_component_gross_mwh[t]) for t in model.TIME
    )
    residual_fixed = sum(
        value(model.full_site_fixed_ng_component_mwh[t]) for t in model.TIME
    )

    assert len(model.hsm_source_mix_constraints) == 2
    assert total_ng / total_heat == pytest.approx(share)
    assert residual_fixed + total_ng == pytest.approx(gross_fixed)
    assert all(
        value(model.full_site_fixed_ng_component_mwh[t]) >= 0.0 for t in model.TIME
    )
    assert all(
        value(model.full_site_fixed_ng_component_mwh[t])
        + value(model.ng_to_hsm_mwh[t])
        == pytest.approx(value(model.full_site_fixed_ng_component_gross_mwh[t]))
        for t in model.TIME
    )


def test_source_mix_rejects_bfg_bofg_eligibility_and_missing_bridge_displacement() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=24, target_multiplier=1.0
    )
    with pytest.raises(S44CModelBuilderError, match="enabled C0 fixed-NG bridge"):
        _build_c0_model(
            inputs,
            enable_minimal_wag_layer=True,
            development_controller_activation="full",
            hsm_source_mix_policy=_policy(0.45, 0.55, displace=True),
        )
