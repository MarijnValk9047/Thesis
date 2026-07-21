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
from steel.s4_4c5p_i_source_card_candidate_overlay_reconciliation import (  # noqa: E402
    ACTIVITY_COLUMNS,
    C5P_A_DIR,
    C5P_B_DIR,
    C5P_C_DIR,
    C5P_D_DIR,
    C5P_E_DIR,
    C5P_F_DIR,
    C5P_G_DIR,
    C5P_H_DIR,
    C5P_I_DIR,
    CO2_COLUMNS,
    ELECTRICITY_COLUMNS,
    ELECTRICITY_GAP_COLUMNS,
    MIGRATION_COLUMNS,
    NG_FUEL_COLUMNS,
    NG_GAP_COLUMNS,
    REDFLAG_COLUMNS,
    REPORT_PATH,
    run_s4_4c5p_i_source_card_candidate_overlay_reconciliation,
)


REQUIRED_FILES = {
    "c5_candidate_overlay_activity_basis.csv": ACTIVITY_COLUMNS,
    "c5_candidate_overlay_electricity_by_plant.csv": ELECTRICITY_COLUMNS,
    "c5_candidate_overlay_ng_fuel_by_plant.csv": NG_FUEL_COLUMNS,
    "c5_candidate_overlay_electricity_anchor_gap.csv": ELECTRICITY_GAP_COLUMNS,
    "c5_candidate_overlay_ng_anchor_gap.csv": NG_GAP_COLUMNS,
    "c5_candidate_overlay_co2_mode_comparison.csv": CO2_COLUMNS,
    "c5_candidate_overlay_migration_recommendations.csv": MIGRATION_COLUMNS,
    "c5_candidate_overlay_red_flags.csv": REDFLAG_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5p_i_outputs() -> Path:
    run_s4_4c5p_i_source_card_candidate_overlay_reconciliation()
    return C5P_I_DIR


def test_c5p_i_outputs_parse_and_have_required_columns(c5p_i_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_i_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    for name in ["s4_4c5p_i_stage_gate.json", "s4_4c5p_i_summary.json"]:
        json.loads((c5p_i_outputs / name).read_text(encoding="utf-8"))
    assert _read_csv(c5p_i_outputs / "s4_4c5p_i_run_registry.csv")
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_i_outputs / "s4_4c5p_i_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_source_card_candidate_overlay_reconciliation"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["candidate_values_migrated_to_executable_inputs"] is False
    assert gate["economics_readiness"] == "NO_GO"
    assert gate["DA_readiness"] == "NO_GO"


def test_c5p_i_preserves_current_c5_stage_metrics(c5p_i_outputs: Path):
    gate = json.loads((c5p_i_outputs / "s4_4c5p_i_stage_gate.json").read_text(encoding="utf-8"))
    p_h_gate = json.loads((C5P_H_DIR / "s4_4c5p_h_stage_gate.json").read_text(encoding="utf-8"))
    p_g_gate = json.loads((C5P_G_DIR / "s4_4c5p_g_stage_gate.json").read_text(encoding="utf-8"))
    p_f_gate = json.loads((C5P_F_DIR / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8"))
    p_e_gate = json.loads((C5P_E_DIR / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8"))
    p_d_gate = json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8"))
    p_c_gate = json.loads((C5P_C_DIR / "s4_4c5p_c_stage_gate.json").read_text(encoding="utf-8"))
    p_b_gate = json.loads((C5P_B_DIR / "s4_4c5p_b_stage_gate.json").read_text(encoding="utf-8"))
    p_a_gate = json.loads((C5P_A_DIR / "s4_4c5p_a_stage_gate.json").read_text(encoding="utf-8"))

    assert gate["denominator_status"] == p_f_gate["denominator_status"]
    assert gate["electricity_boundary_status"] == p_g_gate["electricity_boundary_status"]
    assert gate["ng_boundary_status"] == p_g_gate["ng_boundary_status"]
    assert gate["co2_boundary_status"] == p_h_gate["co2_boundary_status"]
    assert p_e_gate["C1_generator_fuel_gap_PJ_y"] == pytest.approx(4.763389, abs=1e-6)
    assert p_d_gate["C1_24h_DRI_buffer_capacity_t"] == pytest.approx(15229.652603, abs=1e-6)
    assert p_c_gate["C0_24h_generator_electricity_validation_anchor_TWh_e_y"] == pytest.approx(2.0, abs=1e-9)
    assert p_b_gate["C1_24h_total_steam_demand_t_y"] == pytest.approx(165461.611488, abs=1e-6)
    assert p_a_gate["C0_24h_ASU_electricity_MWh_y"] == pytest.approx(357375.0375, abs=1e-6)


def test_overlay_scenarios_are_diagnostic_only_and_separate(c5p_i_outputs: Path):
    electricity_gap = _read_csv(c5p_i_outputs / "c5_candidate_overlay_electricity_anchor_gap.csv")
    scenarios = {row["scenario"] for row in electricity_gap}
    assert {
        "scenario0_current_C5_baseline",
        "scenario1_conservative_candidate_overlay",
        "scenario2_expanded_generic_overlay",
    } <= scenarios
    c0_current = next(row for row in electricity_gap if row["configuration"] == C0 and row["scenario"] == "scenario0_current_C5_baseline")
    c0_expanded = next(row for row in electricity_gap if row["configuration"] == C0 and row["scenario"] == "scenario2_expanded_generic_overlay")
    c1_current = next(row for row in electricity_gap if row["configuration"] == C1 and row["scenario"] == "scenario0_current_C5_baseline")
    c1_expanded = next(row for row in electricity_gap if row["configuration"] == C1 and row["scenario"] == "scenario2_expanded_generic_overlay")
    assert _num(c0_current["candidate_overlay_gross_demand_twh"]) == pytest.approx(1.742724, abs=1e-6)
    assert _num(c0_current["pre_floor_exposure_twh"]) == pytest.approx(-0.324941, abs=1e-6)
    assert _num(c0_expanded["candidate_overlay_gross_demand_twh"]) > _num(c0_current["candidate_overlay_gross_demand_twh"])
    assert _num(c0_expanded["pre_floor_exposure_twh"]) > 0.0
    assert _num(c1_expanded["candidate_overlay_gross_demand_twh"]) > _num(c1_current["candidate_overlay_gross_demand_twh"])
    assert all("validation/context" in row["caveat"] or row["grid_import_anchor_twh"] == "" for row in electricity_gap)

    ng_gap = _read_csv(c5p_i_outputs / "c5_candidate_overlay_ng_anchor_gap.csv")
    assert {row["scenario"] for row in ng_gap} == {
        "scenario0_current_C5_baseline",
        "scenario1_conservative_candidate_overlay",
        "scenario2_expanded_generic_fuel_overlay_if_HSM_reheat_all_NG_equivalent",
    }
    assert all(row["full_site_ng_anchor_pj"] == "" for row in ng_gap)


def test_electricity_and_ng_fuel_overlay_by_plant(c5p_i_outputs: Path):
    electricity = _read_csv(c5p_i_outputs / "c5_candidate_overlay_electricity_by_plant.csv")
    e_ids = {row["candidate_parameter_id"] for row in electricity}
    assert {
        "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID",
        "DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_SENS_HIGH",
        "BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA",
        "KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE",
    } <= e_ids
    c1_hsm = next(
        row
        for row in electricity
        if row["configuration"] == C1 and row["candidate_parameter_id"] == "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID"
    )
    assert _num(c1_hsm["overlay_electricity_twh_y"]) == pytest.approx(0.566856, abs=1e-6)
    assert _num(c1_hsm["delta_vs_current_twh_y"]) > 0

    fuel = _read_csv(c5p_i_outputs / "c5_candidate_overlay_ng_fuel_by_plant.csv")
    fuel_ids = {row["candidate_parameter_id"] for row in fuel}
    assert {
        "HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID",
        "KGF_COG_FOR_HEATING_GJ_PER_T_COKE",
        "BOF_NG_M3_PER_T_LS_BIEDA",
        "BOILER_EFFICIENCY_BASE",
    } <= fuel_ids
    bof_ng = next(row for row in fuel if row["configuration"] == C1 and row["candidate_parameter_id"] == "BOF_NG_M3_PER_T_LS_BIEDA")
    assert bof_ng["overlay_fuel_pj_y"] == ""
    assert "not converted" in bof_ng["caveat"].lower()


def test_co2_modes_do_not_double_count_and_ets_is_false(c5p_i_outputs: Path):
    rows = _read_csv(c5p_i_outputs / "c5_candidate_overlay_co2_mode_comparison.csv")
    modes = {row["co2_mode"] for row in rows}
    assert {
        "scenario0_current_component_diagnostic",
        "scenario3_aggregate_process_counter_mode",
        "scenario4_WAG_fuel_explicit_mode_deferred",
    } <= modes
    assert all(row["ets_ready"] == "false" for row in rows)
    c1_aggregate = next(row for row in rows if row["configuration"] == C1 and row["co2_mode"] == "scenario3_aggregate_process_counter_mode")
    assert _num(c1_aggregate["diagnostic_total_mt"]) == pytest.approx(1.679861, abs=1e-6)
    assert c1_aggregate["fuel_explicit_co2_mt"] == ""
    assert "excluding_WAG" in c1_aggregate["double_counting_risk"]
    fuel_mode = next(row for row in rows if row["configuration"] == C0 and row["co2_mode"] == "scenario4_WAG_fuel_explicit_mode_deferred")
    assert fuel_mode["diagnostic_total_mt"] == ""
    assert "official factors" in fuel_mode["interpretation"]


def test_migration_recommendations_and_red_flags(c5p_i_outputs: Path):
    recommendations = _read_csv(c5p_i_outputs / "c5_candidate_overlay_migration_recommendations.csv")
    rec_by_id = {row["candidate_parameter_id"]: row for row in recommendations}
    assert rec_by_id["HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID"]["migration_recommendation"] == "source_review_required_before_migration"
    assert rec_by_id["HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID"]["migration_recommendation"] == "use_as_sensitivity_only"
    assert rec_by_id["WAG_OFFICIAL_CO2_FACTOR_SOURCE_REPAIR"]["migration_recommendation"] == "deferred"
    assert all(row["local_locator_verified"] in {"true", "false"} for row in recommendations)
    assert all(row["migration_recommendation"] != "migrate_candidate_to_dev_input_later" for row in recommendations)

    flags = _read_csv(c5p_i_outputs / "c5_candidate_overlay_red_flags.csv")
    failure_flags = [row for row in flags if row["severity"] == "failure"]
    assert failure_flags
    assert all(row["active"] == "false" for row in failure_flags)
    caveats = {row["red_flag"] for row in flags if row["severity"] == "caveat" and row["active"] == "true"}
    assert {
        "CANDIDATE_OVERLAY_DIAGNOSTIC_ONLY",
        "SOURCE_CARD_VALUES_NOT_EXECUTABLE",
        "RESIDUAL_ELECTRICITY_REMAINS_DIAGNOSTIC",
        "CO2_BOUNDARY_NOT_ETS_READY",
        "DENOMINATOR_UNRESOLVED",
        "NOT_THESIS_APPROVED",
    } <= caveats
