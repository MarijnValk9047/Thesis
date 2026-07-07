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
from steel.s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import C5O_A_DIR  # noqa: E402
from steel.s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff import (  # noqa: E402
    C5O_B_DIR,
    STAGE,
    run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5o_b_outputs() -> Path:
    run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff()
    return C5O_B_DIR


def test_c5o_b_required_outputs_and_stage_status(c5o_b_outputs: Path):
    required = [
        "s4_4c5o_b_stage_gate.json",
        "s4_4c5o_b_run_registry.csv",
        "s4_4c5o_b_eaf_development_input_rows.csv",
        "s4_4c5o_b_eaf_validation_anchors.csv",
        "s4_4c5o_b_eaf_activity_report.csv",
        "s4_4c5o_b_eaf_material_energy_ledger.csv",
        "s4_4c5o_b_eaf_heat_state_ledger.csv",
        "s4_4c5o_b_dri_buffer_handoff_dashboard.csv",
        "s4_4c5o_b_downstream_integration_dashboard.csv",
        "s4_4c5o_b_modelled_totals_delta.csv",
        "s4_4c5o_b_plant_kpi_table.csv",
        "s4_4c5o_b_compact_healthcheck.csv",
        "s4_4c5o_b_red_flags.csv",
        "s4_4c5o_b_compact_table_for_chat.csv",
        "s4_4c5o_b_eaf_minimal_physical_layer_report.json",
        "s4_4c5o_b_summary.json",
    ]
    for name in required:
        path = c5o_b_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5o_b_outputs / "s4_4c5o_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_eaf_minimal_physical_layer_with_dri_buffer_handoff"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["temporary_DRI_interface_replaced"] is True
    assert gate["EAF_offgas_as_WAG"] is False
    assert gate["mFRR_variables_active"] is False
    assert gate["hidden_DRI_or_HBI_source_active"] is False


def test_eaf_source_card_and_development_input_rows_are_governed(c5o_b_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "EAF_HEAT_SIZE_T_LS" in text
    assert "EAF_HDRI_INPUT_T_PER_T_LS" in text
    assert "EAF_OFFGAS_AS_WAG" in text

    rows = _read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "EAF_HEAT_STATE_MODEL_ACTIVE",
        "EAF_OUTPUT_BASIS",
        "EAF_HEAT_SIZE_T_LS",
        "EAF_POWER_RATE_MAX_REL",
        "EAF_MFRR_UP_ALLOWED_BASE",
        "EAF_OFFGAS_AS_WAG",
        "EAF_RECONCILIATION_MODE",
        "EAF_C1_LS_ANNUAL_OUTPUT_MT",
        "EAF_HDRI_INPUT_T_PER_T_LS_SOURCE",
        "EAF_DRI_INPUT_T_PER_T_LS_ACTIVE_POLICY",
        "EAF_SCRAP_INPUT_T_PER_T_LS",
        "EAF_ELECTRICITY_MWH_PER_T_LS_TATA",
        "EAF_NG_GJ_PER_T_LS",
        "EAF_OXYGEN_INPUT_NM3_PER_T_LS_BREF",
        "O2_T_PER_NM3",
        "EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("EAF_Parameters.md")
        assert row["input_status"].startswith("development")
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]

    assert _num(by_id["EAF_POWER_RATE_MAX_REL"]["base_value"]) == pytest.approx(1.0)
    assert by_id["EAF_OFFGAS_AS_WAG"]["base_value"] == "false"
    assert by_id["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE_POLICY"]["base_value"].startswith("derived_by_C5o_b")
    anchors = _read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_validation_anchors.csv")
    assert {row["anchor_status"] for row in anchors} >= {
        "raw_validation_anchor_not_hourly_constraint",
        "raw_validation_anchor_not_hidden_HBI_supply",
    }


def test_c0_eaf_is_inactive_zero(c5o_b_outputs: Path):
    material = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_material_energy_ledger.csv"))
    handoff = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_dri_buffer_handoff_dashboard.csv"))
    heat = [
        row
        for row in _read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_heat_state_ledger.csv")
        if row["configuration"] == C0 and int(row["horizon_hours"]) == 24
    ]
    for horizon in (24, 168):
        row = material[(C0, horizon)]
        assert row["EAF_ACTIVE"] == "false"
        assert _num(row["EAF_LS_output_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_DRI_input_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_scrap_input_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_arc_electricity_MWh_e_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_NG_GJ_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_oxygen_diagnostic_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_CO2_diagnostic_midpoint_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert handoff[(C0, horizon)]["temporary_DRI_to_future_EAF_interface_active_after_C5o_b"] == "false"
    assert all(row["arc_power_on"] == "false" for row in heat)


def test_c1_production_and_anchor_comparison(c5o_b_outputs: Path):
    activity = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_activity_report.csv"))
    c5k = _keyed(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    row = activity[(C1, 24)]
    k = c5k[(C1, 24)]

    eaf_target = _num(k["active_eaf_liquid_steel_target_site_t_y"])
    bof_target = _num(k["active_bof_liquid_steel_target_site_t_y"])
    total_target = _num(k["active_total_liquid_steel_target_site_t_y"])
    assert row["EAF_ACTIVE"] == "true"
    assert _num(row["EAF_active_LS_target_site_t_y"]) == pytest.approx(eaf_target, abs=1e-6)
    assert _num(row["EAF_raw_anchor_LS_site_t_y"]) == pytest.approx(3.3e6, abs=1e-6)
    assert _num(row["EAF_raw_anchor_gap_site_t_y"]) == pytest.approx(eaf_target - 3.3e6, abs=1e-6)
    assert _num(row["BOF_plus_EAF_total_site_t_y"]) == pytest.approx(total_target, abs=1e-6)
    assert _num(row["BOF_plus_EAF_total_site_t_y"]) == pytest.approx(bof_target + eaf_target, abs=1e-6)
    assert row["BOF_plus_EAF_total_matches_C5k_target"] == "true"
    assert row["C5k_route_split_preserved"] == "true"


def test_drp_eaf_dri_handoff_replaces_temporary_interface(c5o_b_outputs: Path):
    activity = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_activity_report.csv"))
    material = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_material_energy_ledger.csv"))
    handoff = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_dri_buffer_handoff_dashboard.csv"))
    c5o_a_buffer = _keyed(_read_csv(C5O_A_DIR / "s4_4c5o_a_dri_buffer_interface_dashboard.csv"))
    row = activity[(C1, 24)]
    mat = material[(C1, 24)]
    hand = handoff[(C1, 24)]
    old = c5o_a_buffer[(C1, 24)]
    eaf_ls = _num(row["EAF_active_LS_target_site_t_y"])
    available = _num(row["available_DRP_DRI_for_EAF_site_t_y"])

    assert _num(row["EAF_DRI_requirement_under_source_coeff_site_t_y"]) == pytest.approx(eaf_ls * 0.848, abs=1e-6)
    assert _num(row["EAF_DRI_gap_under_source_coeff_site_t_y"]) == pytest.approx(available - eaf_ls * 0.848, abs=1e-6)
    assert _num(row["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE"]) == pytest.approx(available / eaf_ls, rel=1e-12)
    assert row["EAF_DRI_coeff_reconciled_to_active_C5"] == "true"
    assert _num(mat["EAF_DRI_input_site_t_y"]) == pytest.approx(available, abs=1e-6)
    assert _num(hand["C5o_a_temporary_DRI_to_future_EAF_interface_site_t_y"]) == pytest.approx(_num(old["DRI_to_future_EAF_placeholder_site_t_y"]), abs=1e-6)
    assert _num(hand["C5o_b_EAF_DRI_input_site_t_y"]) == pytest.approx(_num(old["DRI_to_future_EAF_placeholder_site_t_y"]), abs=1e-6)
    assert hand["temporary_DRI_interface_replaced_by_EAF_input"] == "true"
    assert hand["temporary_DRI_to_future_EAF_interface_active_after_C5o_b"] == "false"
    assert hand["DRI_buffer_terminal_status"] == "pass"
    assert _num(hand["DRI_inventory_drift_t"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(hand["hidden_DRI_source_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(hand["HBI_import_site_t_y"]) == pytest.approx(0.0, abs=1e-9)


def test_eaf_formula_closure(c5o_b_outputs: Path):
    row = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_material_energy_ledger.csv"))[(C1, 24)]
    ls = _num(row["EAF_LS_output_site_t_y"])

    assert _num(row["EAF_scrap_input_site_t_y"]) == pytest.approx(ls * 0.303, abs=1e-6)
    assert _num(row["EAF_arc_electricity_MWh_e_y"]) == pytest.approx(ls * 0.422, abs=1e-6)
    assert _num(row["EAF_average_annual_arc_load_MW"]) == pytest.approx(ls * 0.422 / 8760.0, abs=1e-6)
    assert _num(row["EAF_NG_GJ_y"]) == pytest.approx(ls * 0.05, abs=1e-6)
    assert _num(row["EAF_carbon_coke_breeze_anthracite_GJ_y"]) == pytest.approx(ls * 0.27, abs=1e-6)
    assert _num(row["EAF_electrodes_GJ_y"]) == pytest.approx(ls * 0.03, abs=1e-6)
    assert _num(row["EAF_oxygen_input_t_per_t_LS"]) == pytest.approx(35.0 * 0.001429, abs=1e-12)
    assert _num(row["EAF_oxygen_diagnostic_t_y"]) == pytest.approx(ls * 35.0 * 0.001429, abs=1e-6)
    assert row["EAF_CO2_mode"] == "aggregate_BREF_midpoint_diagnostic"
    assert _num(row["EAF_CO2_diagnostic_midpoint_t_y"]) == pytest.approx(ls * 0.126, abs=1e-6)
    assert _num(row["EAF_CO2_diagnostic_range_low_t_y"]) == pytest.approx(ls * 0.072, abs=1e-6)
    assert _num(row["EAF_CO2_diagnostic_range_high_t_y"]) == pytest.approx(ls * 0.180, abs=1e-6)
    assert row["EAF_fuel_explicit_CO2_active"] == "false"
    assert row["EAF_CO2_double_count_risk"] == "false"


def test_heat_state_accounting(c5o_b_outputs: Path):
    rows = [
        row
        for row in _read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_heat_state_ledger.csv")
        if row["configuration"] == C1 and int(row["horizon_hours"]) == 24
    ]
    assert {row["heat_state"] for row in rows} == {
        "MELTING_POWER_ON_1",
        "MELTING_POWER_ON_2",
        "TAPPING_TURNAROUND_POWER_OFF",
    }
    melting = [row for row in rows if row["arc_power_on"] == "true"]
    tapping = next(row for row in rows if row["heat_state"] == "TAPPING_TURNAROUND_POWER_OFF")
    heat_count = 3_350_000.0 / 325.0

    assert len(melting) == 2
    assert _num(rows[0]["EAF_heat_count_equivalent_y"]) == pytest.approx(heat_count, abs=1e-9)
    assert _num(rows[0]["EAF_arc_energy_per_heat_MWh"]) == pytest.approx(325.0 * 0.422, abs=1e-12)
    assert _num(rows[0]["EAF_active_heat_arc_power_MW"]) == pytest.approx((325.0 * 0.422) / 0.5, abs=1e-12)
    assert all(_num(row["EAF_arc_electricity_MWh_e_y"]) > 0 for row in melting)
    assert _num(tapping["EAF_arc_electricity_MWh_e_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(tapping["liquid_steel_release_after_tapping_t_y"]) == pytest.approx(3_350_000.0, abs=1e-6)
    assert all(row["electricity_outside_power_on_state"] == "false" for row in rows)
    assert all(row["mFRR_variable_or_revenue_active"] == "false" for row in rows)
    assert all(_num(row["mFRR_readiness_diagnostic_MW"]) > 0 for row in melting)
    assert _num(tapping["mFRR_readiness_diagnostic_MW"]) == pytest.approx(0.0, abs=1e-9)


def test_offgas_steam_wag_and_totals_guards(c5o_b_outputs: Path):
    material = _read_csv(c5o_b_outputs / "s4_4c5o_b_eaf_material_energy_ledger.csv")
    totals = _read_csv(c5o_b_outputs / "s4_4c5o_b_modelled_totals_delta.csv")
    for row in material:
        assert row["EAF_offgas_as_WAG"] == "false"
        assert _num(row["EAF_offgas_to_BFG_COG_BOFG_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["EAF_useful_WAG_generation_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["EAF_secondary_met_electricity_included_in_arc_total"] == "false"
        assert row["EAF_mFRR_variables_active"] == "false"
        assert row["EAF_overpower_gt_1_enabled"] == "false"
    for row in totals:
        assert row["EAF_offgas_entered_WAG"] == "false"
        assert row["EAF_CO2_guard_status_after_EAF"] == "pass"
        assert row["WAG_invariant_status_after_EAF"] == "pass"
        assert row["LHV_consistency_status_after_EAF"] == "pass"
        assert row["HSM_heat_case"] == "base_0_50"


def test_downstream_interface_and_hsm_baseline_preserved(c5o_b_outputs: Path):
    downstream = _keyed(_read_csv(c5o_b_outputs / "s4_4c5o_b_downstream_integration_dashboard.csv"))
    c5l_d = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    row = downstream[(C1, 24)]

    assert row["EAF_placeholder_replaced_by_actual_output"] == "true"
    assert row["EAF_double_counts_existing_route_placeholder"] == "false"
    assert row["EAF_output_connected_to_downstream"] == "true"
    assert row["C1_total_production_matches_target"] == "true"
    assert _num(row["C1_total_production_mismatch_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert row["HSM_heat_case"] == "base_0_50"
    assert row["HSM_base_0_50_default_preserved"] == "true"
    assert c5l_d[(C1, 24)]["active_cap_case"] == "base_0_50"
    assert row["DSP_NOT_IMPLEMENTED_CAVEAT"] == "true"


def test_healthcheck_redflags_are_false_and_caveats_are_reported(c5o_b_outputs: Path):
    redflags = _read_csv(c5o_b_outputs / "s4_4c5o_b_red_flags.csv")
    failure_columns = [
        "EAF_ACTIVE_IN_C0",
        "EAF_DRI_HIDDEN_SOURCE",
        "EAF_HBI_IMPORT_USED_IN_BASE",
        "EAF_DRI_BUFFER_TERMINAL_VIOLATION",
        "EAF_DRI_BUFFER_CAPACITY_BINDING_UNEXPECTED",
        "EAF_TEMP_DRI_INTERFACE_NOT_REPLACED",
        "EAF_DOUBLE_COUNTS_EXISTING_ROUTE_PLACEHOLDER",
        "EAF_OUTPUT_NOT_CONNECTED_TO_DOWNSTREAM",
        "EAF_OFFGAS_ENTERED_WAG",
        "EAF_MFRR_VARIABLES_ACTIVE_IN_BASE",
        "EAF_OVERPOWER_GT_1_ENABLED",
        "EAF_ELECTRICITY_OUTSIDE_POWER_ON_STATE",
        "EAF_CO2_DOUBLE_COUNT_RISK",
        "C1_TOTAL_PRODUCTION_MISMATCH_AFTER_EAF",
        "HSM_BASE_0_50_REVERTED",
        "DRP_PELLET_BALANCE_BROKEN_BY_EAF",
    ]
    for row in redflags:
        assert row["failure_count"] == "0"
        assert row["status"] == "pass_with_caveats"
        for column in failure_columns:
            assert row[column] == "false", (row["configuration"], row["horizon_hours"], column)

    c1 = next(row for row in redflags if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    assert c1["EAF_DRI_COEFF_RECONCILED_TO_ACTIVE_C5"] == "true"
    assert c1["EAF_HEAT_INTEGERITY_RELAXED_FOR_DEVELOPMENT"] == "true"
    assert c1["OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT"] == "true"
    assert c1["STEAM_RECOVERY_REPORTING_ONLY"] == "true"
    assert c1["EAF_NOT_THESIS_APPROVED"] == "true"
