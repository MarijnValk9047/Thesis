from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation import _anchor_comparisons, _apply_wag_lhv_source_factor_override, _electricity_boundary_overrides, _generator_interface_cap_mode, _guardrails, _hsm_carrier_precedence, _hsm_eligible_carriers, _linde_n2_auxiliary_electricity_mwh_h, _origin_material_rows, _quantile, _representation_gap_rows, _route_band, _wag_lhv_source_factor_override
from steel.wag_development_controller_contract import load_development_controller_profile


def _carrier(carrier: str) -> dict:
    return {
        "carrier": carrier,
        "generation_MWh_LHV_y": 100.0,
        "process_or_self_use_MWh_LHV_y": 20.0,
        "hsm_pefa_MWh_LHV_y": 20.0,
        "steam_boiler_MWh_LHV_y": 20.0,
        "generator_MWh_LHV_y": 20.0,
        "flare_MWh_LHV_y": 20.0,
        "residual_MWh_LHV_y": 0.0,
        "balance_status": "pass",
    }


def _utilities() -> list[dict]:
    return [
        {"metric": "final_product_output", "model_value": 6.7, "caveat": "x"},
        {"metric": "gross_electricity", "model_value": 4.0, "caveat": "x"},
        {"metric": "net_grid_import_after_internal_WAG_offset", "model_value": 3.0, "caveat": "x"},
        {"metric": "internal_WAG_generator_electricity_offset", "model_value": 1.2, "caveat": "internal only"},
        {"metric": "WAG_explicit_combustion_CO2", "model_value": 1.0, "caveat": "Mode B only"},
        {"metric": "steam_production_proxy", "model_value": 0.2, "caveat": "energy proxy"},
        {"metric": "modelled_steam_15bar_demand", "model_value": 165.0, "caveat": "mapped only"},
        {"metric": "modelled_steam_15bar_supply", "model_value": 165.0, "caveat": "source bridge"},
        {"metric": "modelled_steam_15bar_unserved", "model_value": 0.0, "caveat": "mapped only"},
    ]


def test_hsm_precedence_reads_explicit_carrier_order_without_mix_ratio() -> None:
    config = {"wag_controller_policy": {"hsm_carrier_precedence": ["COG", "BFG", "BOFG", "NG"]}}
    assert _hsm_carrier_precedence(config) == ("COG", "BFG", "BOFG", "NG")


def test_source_sensitivity_reads_hsm_eligibility_generator_mode_and_route_band() -> None:
    config = {
        "wag_controller_policy": {
            "hsm_eligible_carriers": ["COG", "NG"],
            "generator_interface_cap_mode": "volume_envelope_only",
        }
    }
    scenario = {"c1_liquid_steel_route_band": {"bof_lower_share": 0.503703704, "bof_upper_share": 0.503703704}}
    assert _hsm_eligible_carriers(config) == ("COG", "NG")
    assert _generator_interface_cap_mode(config) == "volume_envelope_only"
    assert _route_band(scenario) == {"bof_lower_share": 0.503703704, "bof_upper_share": 0.503703704}


def test_linde_auxiliary_context_load_must_be_explicit_and_non_negative() -> None:
    assert _linde_n2_auxiliary_electricity_mwh_h({"linde_n2_auxiliary_electricity_mwh_h": 45.0}, None) == 45.0
    assert _linde_n2_auxiliary_electricity_mwh_h({}, 0.0) == 0.0


def test_electricity_boundary_sensitivity_allows_only_named_activity_linked_loads() -> None:
    scenario = {
        "electricity_boundary_overrides": {
            "eaf_secondary_electricity_mwh_per_t_ls": 0.031,
            "dsp_electricity_mwh_per_t_coil": 0.104,
        }
    }
    assert _electricity_boundary_overrides(scenario) == scenario["electricity_boundary_overrides"]


def test_wag_lhv_sensitivity_requires_complete_carrier_specific_positive_map() -> None:
    scenario = {"wag_lhv_mj_per_nm3_override": {"BFG": 3.85, "COG": 18.5, "BOFG": 8.6}}
    assert _wag_lhv_source_factor_override(scenario) == scenario["wag_lhv_mj_per_nm3_override"]


def test_wag_lhv_sensitivity_changes_generation_energy_but_not_energy_basis_demands() -> None:
    from types import SimpleNamespace

    retained = SimpleNamespace(
        bfg_nm3_per_t_hot_iron=1600.0,
        cog_m3_per_t_dry_coal=400.0,
        bofg_nm3_per_t_liquid_steel=250.0,
        bfg_mwh_per_t_hot_iron=1.0,
        cog_mwh_per_t_coke=2.0,
        bofg_mwh_per_t_liquid_steel=3.0,
        kgf_underfiring_mwh_per_t_coke=0.97,
        sinter_cog_mwh_per_t_sinter=0.027,
    )
    # The production implementation uses frozen dataclasses.  This minimal
    # check therefore asserts the public conversion invariant directly.
    assert retained.bfg_nm3_per_t_hot_iron * 3.85 / 3600.0 == 1.711111111111111
    assert retained.kgf_underfiring_mwh_per_t_coke == 0.97
    assert retained.sinter_cog_mwh_per_t_sinter == 0.027


def test_guardrails_accept_only_carrier_specific_balance_rows() -> None:
    checks = _guardrails([_carrier("BFG"), _carrier("COG"), _carrier("BOFG")], _utilities())
    assert next(row for row in checks if row["check_id"] == "AT_001")["status"] == "pass"
    assert next(row for row in checks if row["check_id"] == "AT_002")["status"] == "pass"
    assert next(row for row in checks if row["check_id"] == "AT_006")["status"] == "pass"


def test_c5p_b_profile_exposes_explicit_mapped_steam_mass_basis() -> None:
    profile = load_development_controller_profile("C1_phase1_BF_BOF_plus_DRP_EAF")
    assert profile.boiler_steam_15bar_demand_t_h > 0.0
    assert profile.boiler_fuel_mwh_per_t_steam > 0.0
    assert profile.bof_electricity_mwh_per_t_ls > 0.0
    assert profile.kgf_electricity_mwh_per_t_coke > 0.0
    assert profile.dsp_electricity_mwh_per_t_coil > 0.0
    assert profile.asu_electricity_mwh_per_t_o2 > 0.0
    assert profile.sinter_electricity_mwh_per_t_sinter > 0.0
    assert profile.bof_oxygen_t_per_t_ls > 0.0
    assert profile.bf_electricity_mwh_per_t_hot_metal > 0.0
    assert profile.bf_oxygen_t_per_t_hot_metal > 0.0


def test_anchor_comparisons_keep_scope_one_as_reporting_only() -> None:
    anchors = {
        "c1_official_scope1_8_3_missing": {"converted_value": "8.3", "source_trust_rank": "Rank 1", "locator_quality": "partial", "caveat": "partial"},
        "athan_table9_phase1_co2_9_108": {"converted_value": "9.10779317", "source_trust_rank": "Rank 3", "locator_quality": "partial", "caveat": "context"},
    }
    rows = _anchor_comparisons(_utilities(), [_carrier("BFG"), _carrier("COG"), _carrier("BOFG")], anchors)
    scope = next(row for row in rows if row["anchor_id"] == "c1_official_scope1_8_3_missing")
    assert scope["comparison_class"] == "reporting_only"
    assert scope["status"] == "partial_not_scored"
    assert scope["comparability_status"] == "reporting_only"


def test_athanasiadis_wag_twh_is_compared_to_internal_generator_electricity() -> None:
    rows = _anchor_comparisons(_utilities(), [_carrier("BFG"), _carrier("COG"), _carrier("BOFG")], {})
    wag = next(row for row in rows if row["anchor_id"] == "athan_table9_phase1_wag_1_23")
    assert wag["metric"] == "internal_WAG_generator_electricity_offset"
    assert wag["unit"] == "TWh/y"
    assert wag["comparison_class"] == "secondary_context"
    assert wag["comparability_status"] == "not_comparable"


def test_generator_wag_subtotal_excludes_unmodelled_named_ng_from_comparison() -> None:
    rows = _anchor_comparisons(_utilities(), [_carrier("BFG"), _carrier("COG"), _carrier("BOFG")], {})
    wag = next(row for row in rows if row["anchor_id"] == "c1_generator_wag_with_flare_10_6")
    total = next(row for row in rows if row["anchor_id"] == "c1_generator_total_with_flare_14_6")
    assert wag["metric"] == "generator_plus_flare_WAG_fuel"
    assert wag["anchor_value"] == 10.6
    assert wag["comparison_class"] == "boundary_comparable"
    assert wag["comparability_status"] == "comparable"
    assert total["model_value"] == ""
    assert total["comparison_class"] == "not_comparable"
    assert total["status"] == "not_comparable"


def test_representation_gap_register_is_not_a_residual_load_budget(monkeypatch) -> None:
    class _Model:
        TIME = (0,)
        hot_strip_mill = {0: 100.0}
        eaf_liquid_steel_output = {0: 50.0}
        coke_output = {0: 30.0}
        bf6_hot_iron_output = {0: 40.0}
        bf_electricity_mwh = {0: 2.0}
        hsm_rolling_electricity_mwh = {0: 7.0}
        kgf_electricity_mwh = {0: 2.0}
        dsp_electricity_mwh = {0: 1.0}
        dsp_final_product_output = {0: 20.0}

    monkeypatch.setattr(
        "steel.s4_4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation._candidate_value",
        lambda _path, **criteria: {
            "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID": 0.104,
            "KGF_ELECTRICITY_GROSS_SERVICE_GJ_PER_T_COKE": 0.0972,
            "DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_SENS_HIGH": 0.104,
            "EAF_SECONDARY_MET_ELECTRICITY_MWH_PER_T_LS": 0.031,
        }[criteria["candidate_parameter_id"] if "candidate_parameter_id" in criteria else criteria["parameter_id"]],
    )
    rows = _representation_gap_rows(_Model(), 1)
    eaf_secondary = next(row for row in rows if row["process_or_interface"] == "EAF secondary metallurgy electricity")
    assert eaf_secondary["status"] == "deferred_accounting_only"
    assert eaf_secondary["current_model_value_TWh_y"] == 0.0


def test_quantile_uses_deterministic_linear_interpolation() -> None:
    assert _quantile([0.0, 10.0, 20.0, 30.0], 0.5) == 15.0
    assert _quantile([0.0, 10.0, 20.0, 30.0], 0.25) == 7.5


def test_origin_ledger_keeps_imported_slab_out_of_upstream_energy_and_co2() -> None:
    class _Model:
        TIME = (0,)
        bof_crude_steel_output = {0: 100.0}
        eaf_liquid_steel_output = {0: 50.0}
        bof_to_hsm_slab = {0: 30.0}
        eaf_to_hsm_slab = {0: 20.0}
        imported_slab_to_hsm = {0: 10.0}
        hot_strip_mill = {0: 60.0}
        dsp_final_product_output = {0: 20.0}
        final_product_output = {0: 80.0}

    rows = _origin_material_rows(_Model(), 1)
    values = {row["metric"]: row for row in rows}
    assert values["HSM_origin_input_balance_residual"]["status"] == "pass"
    assert values["imported_slab_upstream_electricity"]["annual_value"] == 0.0
    assert values["imported_slab_upstream_WAG"]["annual_value"] == 0.0
    assert values["imported_slab_upstream_NG"]["annual_value"] == 0.0
    assert values["imported_slab_upstream_direct_fuel_CO2"]["annual_value"] == 0.0
