from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import C0, C1  # noqa: E402
from steel.s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR  # noqa: E402
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR  # noqa: E402
from steel.s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff import C5O_B_DIR  # noqa: E402
from steel.s4_4c5o_c_dsp_downstream_physical_layer import (  # noqa: E402
    C5O_C_DIR,
    STAGE,
    run_s4_4c5o_c_dsp_downstream_physical_layer,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/DSP_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5o_c_outputs() -> Path:
    run_s4_4c5o_c_dsp_downstream_physical_layer()
    return C5O_C_DIR


def test_c5o_c_required_outputs_and_stage_status(c5o_c_outputs: Path):
    required = [
        "s4_4c5o_c_stage_gate.json",
        "s4_4c5o_c_run_registry.csv",
        "s4_4c5o_c_dsp_development_input_rows.csv",
        "s4_4c5o_c_dsp_validation_anchors.csv",
        "s4_4c5o_c_dsp_activity_report.csv",
        "s4_4c5o_c_dsp_material_energy_ledger.csv",
        "s4_4c5o_c_downstream_integration_dashboard.csv",
        "s4_4c5o_c_modelled_totals_delta.csv",
        "s4_4c5o_c_plant_kpi_table.csv",
        "s4_4c5o_c_compact_healthcheck.csv",
        "s4_4c5o_c_red_flags.csv",
        "s4_4c5o_c_compact_table_for_chat.csv",
        "s4_4c5o_c_dsp_downstream_physical_layer_report.json",
        "s4_4c5o_c_summary.json",
    ]
    for name in required:
        path = c5o_c_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5o_c_outputs / "s4_4c5o_c_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_dsp_downstream_physical_layer"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["DSP_WAG_consumption_active"] is False
    assert gate["DSP_NG_consumption_active"] is False
    assert gate["DSP_mFRR_provider_base"] is False
    assert gate["hidden_liquid_steel_source_active"] is False


def test_dsp_source_card_and_development_input_rows_are_governed(c5o_c_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "DSP_OUTPUT_BASIS" in text
    assert "DSP_FUEL_GAS_BASE_ACTIVE" in text
    assert "DSP_MFRR_PROVIDER_BASE" in text

    rows = _read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "DSP_OUTPUT_BASIS",
        "DSP_RECONCILIATION_MODE",
        "DSP_C0_OUTPUT_ANNUAL_MT_Y",
        "DSP_C1_OUTPUT_ANNUAL_MT_Y",
        "DSP_C0_SHARE_OF_OSF_TO_DSP",
        "DSP_C1_EAF_ROUTE_SHARE_OF_DSP",
        "DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_BASE",
        "DSP_INTERNAL_SCRAP_LOSS_T_PER_T_COIL_DERIVED",
        "DSP_ELECTRICITY_MWH_PER_T_COIL_BASE",
        "DSP_TUNNEL_FURNACE_HEAT_GJ_PER_T",
        "DSP_FUEL_GAS_BASE_ACTIVE",
        "DSP_DIRECT_CO2_MODE_BASE",
        "DSP_DIRECT_CO2_T_PER_T_COIL_BASE",
        "DSP_MFRR_PROVIDER_BASE",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("DSP_Parameters.md")
        assert row["input_status"].startswith("development")
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]

    assert by_id["DSP_FUEL_GAS_BASE_ACTIVE"]["base_value"] == "false"
    assert by_id["DSP_TUNNEL_FURNACE_HEAT_GJ_PER_T"]["base_value"] == "deferred"
    assert by_id["DSP_MFRR_PROVIDER_BASE"]["base_value"] == "false"
    anchors = _read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_validation_anchors.csv")
    assert {row["anchor_status"] for row in anchors} >= {
        "raw_validation_anchor_not_hourly_constraint",
        "route_share_validation_anchor_not_constraint",
    }


def test_dsp_activity_preserves_existing_placeholder_and_reports_anchors(c5o_c_outputs: Path):
    activity = _keyed(_read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_activity_report.csv"))
    c5l_d = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for config in (C0, C1):
        row = activity[(config, 24)]
        inherited = c5l_d[(config, 24)]
        assert row["DSP_ACTIVE"] == "true"
        assert _num(row["DSP_active_output_site_t_y"]) == pytest.approx(_num(inherited["dsp_output_site_t_y"]), abs=1e-6)
        assert _num(row["DSP_active_output_site_t_y"]) == pytest.approx(1_350_000.0, abs=1e-6)
        assert _num(row["DSP_raw_anchor_site_t_y"]) == pytest.approx(1_500_000.0, abs=1e-6)
        assert _num(row["DSP_raw_anchor_gap_site_t_y"]) == pytest.approx(-150_000.0, abs=1e-6)
        assert row["raw_anchor_used_as_hourly_constraint"] == "false"
        assert row["DSP_placeholder_replaced_by_actual_output"] == "true"
        assert row["DSP_output_double_counts_placeholder"] == "false"

    assert _num(activity[(C0, 24)]["C0_OSF_to_DSP_route_share_observed"]) == pytest.approx(0.20, abs=1e-12)
    assert activity[(C0, 24)]["C0_OSF_to_DSP_route_share_status"] == "pass"
    assert activity[(C1, 24)]["C1_EAF_route_share_status"] == "route_origin_not_fully_tracked"
    assert activity[(C1, 24)]["DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT"] == "true"


def test_dsp_material_formula_closure_and_no_hidden_slack(c5o_c_outputs: Path):
    rows = _keyed(_read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_material_energy_ledger.csv"))
    for config in (C0, C1):
        row = rows[(config, 24)]
        output = _num(row["DSP_output_site_t_y"])
        assert _num(row["DSP_liquid_steel_input_site_t_y"]) == pytest.approx(output * 1.05, abs=1e-6)
        assert _num(row["DSP_internal_scrap_loss_site_t_y"]) == pytest.approx(output * 0.05, abs=1e-6)
        assert _num(row["DSP_hidden_liquid_steel_source_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["DSP_liquid_steel_exceeds_available_routed_steel"] == "false"
        assert row["DSP_liquid_steel_exceeds_total_liquid_steel_pool"] == "false"
        assert row["DSP_internal_scrap_handling_status"] == "reporting_only_not_connected_to_EAF_scrap_loop"
        assert row["DSP_internal_scrap_used_as_free_EAF_input"] == "false"


def test_dsp_electricity_formula_and_total_scope_expansion(c5o_c_outputs: Path):
    material = _keyed(_read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_material_energy_ledger.csv"))
    totals = _keyed(_read_csv(c5o_c_outputs / "s4_4c5o_c_modelled_totals_delta.csv"))
    c5o_b_totals = _keyed(_read_csv(C5O_B_DIR / "s4_4c5o_b_modelled_totals_delta.csv"))
    for config in (C0, C1):
        row = material[(config, 24)]
        total = totals[(config, 24)]
        before = c5o_b_totals[(config, 24)]
        output = _num(row["DSP_output_site_t_y"])
        electricity = output * 0.056
        assert _num(row["DSP_electricity_MWh_e_y"]) == pytest.approx(electricity, abs=1e-6)
        assert _num(row["DSP_electricity_TWh_e_y"]) == pytest.approx(electricity / 1_000_000.0, abs=1e-12)
        assert row["DSP_electricity_price_responsive"] == "false"
        assert _num(total["DSP_electricity_delta_MWh_e_y"]) == pytest.approx(electricity, abs=1e-6)
        assert _num(total["process_electricity_after_DSP_MWh_e_y"]) == pytest.approx(
            _num(before["process_electricity_after_EAF_MWh_e_y"]) + electricity,
            abs=1e-6,
        )


def test_dsp_no_wag_no_fuel_no_direct_co2(c5o_c_outputs: Path):
    material = _read_csv(c5o_c_outputs / "s4_4c5o_c_dsp_material_energy_ledger.csv")
    totals = _read_csv(c5o_c_outputs / "s4_4c5o_c_modelled_totals_delta.csv")
    for row in material:
        assert row["DSP_FUEL_GAS_BASE_ACTIVE"] == "false"
        assert row["DSP_tunnel_furnace_heat_status"] == "deferred_no_active_heat_coefficient"
        assert _num(row["DSP_WAG_consumption_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DSP_NG_consumption_GJ_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["DSP_WAG_consumption_active_without_heat_coefficient"] == "false"
        assert row["DSP_NG_consumption_active_without_heat_coefficient"] == "false"
        assert row["DSP_direct_CO2_mode"] == "fuel-derived only"
        assert _num(row["DSP_direct_CO2_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["DSP_direct_CO2_zero_accounting_caveat"] == "true"
        assert row["DSP_mFRR_provider_base"] == "false"
    for row in totals:
        assert _num(row["DSP_NG_delta_PJ_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DSP_WAG_consumption_delta_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["WAG_invariant_status_after_DSP"] == "pass"
        assert row["LHV_consistency_status_after_DSP"] == "pass"
        assert row["CO2_guard_status_after_DSP"] == "pass"
        assert row["HSM_heat_case"] == "base_0_50"


def test_dsp_downstream_integration_preserves_c5_targets_and_hsm_case(c5o_c_outputs: Path):
    downstream = _keyed(_read_csv(c5o_c_outputs / "s4_4c5o_c_downstream_integration_dashboard.csv"))
    c5k = _keyed(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    c5l_d = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for config in (C0, C1):
        row = downstream[(config, 24)]
        k = c5k[(config, 24)]
        inherited = c5l_d[(config, 24)]
        assert row["DSP_output_in_final_product_ledger"] == "true"
        assert row["DSP_output_not_added_on_top_of_placeholder"] == "true"
        assert row["HSM_WBW_C5l_d_base_0_50_preserved"] == "true"
        assert row["HSM_heat_case"] == "base_0_50"
        assert row["BOF_plus_EAF_total_matches_C5k_target"] == "true"
        assert _num(row["BOF_plus_EAF_total_site_t_y"]) == pytest.approx(
            _num(k["active_total_liquid_steel_target_site_t_y"]),
            abs=1e-6,
        )
        assert _num(row["DSP_plus_HSM_final_product_proxy_site_t_y"]) == pytest.approx(
            _num(inherited["active_final_product_proxy_site_t_y"]),
            abs=1e-6,
        )
        assert row["EAF_output_remains_connected_downstream"] == "true"
        assert row["upstream_downstream_mismatch_after_DSP"] == "false"


def test_dsp_route_origin_caveat_and_healthcheck_redflags(c5o_c_outputs: Path):
    redflags = _read_csv(c5o_c_outputs / "s4_4c5o_c_red_flags.csv")
    failure_columns = [
        "DSP_ACTIVE_WITHOUT_LIQUID_STEEL_INPUT",
        "DSP_HIDDEN_LIQUID_STEEL_SOURCE",
        "DSP_OUTPUT_DOUBLE_COUNTS_PLACEHOLDER",
        "DSP_OUTPUT_NOT_IN_FINAL_PRODUCT_LEDGER",
        "DSP_LIQUID_STEEL_EXCEEDS_AVAILABLE_ROUTED_STEEL",
        "DSP_BREAKS_C1_TOTAL_PRODUCTION",
        "DSP_BREAKS_HSM_WBW_C5L_D_BASE",
        "DSP_WAG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT",
        "DSP_NG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT",
        "DSP_MFRR_ENABLED_IN_BASE",
        "DSP_DIRECT_CO2_DOUBLE_COUNT",
        "DSP_ELECTRICITY_PRICE_RESPONSIVE_IN_BASE",
        "DSP_INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT",
        "UPSTREAM_DOWNSTREAM_MISMATCH_AFTER_DSP",
    ]
    for row in redflags:
        assert row["failure_count"] == "0"
        assert row["status"] == "pass_with_caveats"
        for column in failure_columns:
            assert row[column] == "false", (row["configuration"], row["horizon_hours"], column)
        assert row["DSP_TUNNEL_FURNACE_HEAT_DEFERRED_CAVEAT"] == "true"
        assert row["DSP_FUEL_GAS_NOT_MODELLED_CAVEAT"] == "true"
        assert row["DSP_DIRECT_CO2_ZERO_ONLY_BECAUSE_FUEL_INACTIVE"] == "true"
        assert row["DSP_INTERNAL_SCRAP_REPORTING_ONLY"] == "true"
        assert row["DSP_NOT_THESIS_APPROVED"] == "true"

    c0 = next(row for row in redflags if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in redflags if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    assert c0["DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT"] == "false"
    assert c1["DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT"] == "true"
