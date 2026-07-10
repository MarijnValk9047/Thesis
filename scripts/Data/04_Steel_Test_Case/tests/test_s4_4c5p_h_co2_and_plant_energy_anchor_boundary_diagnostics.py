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
from steel.s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics import (  # noqa: E402
    C5P_A_DIR,
    C5P_B_DIR,
    C5P_C_DIR,
    C5P_D_DIR,
    C5P_E_DIR,
    C5P_F_DIR,
    C5P_G_DIR,
    C5P_H_DIR,
    CO2_BOUNDARY_COLUMNS,
    CO2_COMPONENT_COLUMNS,
    DECISION_COLUMNS,
    DOUBLE_COUNT_COLUMNS,
    ELECTRICITY_SUMMARY_COLUMNS,
    FACTOR_COLUMNS,
    NG_SUMMARY_COLUMNS,
    PLANT_ANCHOR_COLUMNS,
    READINESS_COLUMNS,
    REDFLAG_COLUMNS,
    REPORT_PATH,
    SOURCE_GAP_COLUMNS,
    run_s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics,
)


REQUIRED_FILES = {
    "c5_plant_energy_anchor_coverage_matrix.csv": PLANT_ANCHOR_COLUMNS,
    "c5_plant_electricity_anchor_summary.csv": ELECTRICITY_SUMMARY_COLUMNS,
    "c5_plant_ng_anchor_summary.csv": NG_SUMMARY_COLUMNS,
    "c5_residual_policy_readiness_from_plant_anchors.csv": READINESS_COLUMNS,
    "c5_co2_component_inventory.csv": CO2_COMPONENT_COLUMNS,
    "c5_co2_boundary_matrix.csv": CO2_BOUNDARY_COLUMNS,
    "c5_co2_double_counting_risk_matrix.csv": DOUBLE_COUNT_COLUMNS,
    "c5_co2_factor_gap_and_source_review.csv": FACTOR_COLUMNS,
    "c5_energy_anchor_source_gap_register.csv": SOURCE_GAP_COLUMNS,
    "c5_co2_energy_boundary_decision_register.csv": DECISION_COLUMNS,
    "c5_co2_energy_boundary_red_flags.csv": REDFLAG_COLUMNS,
}

REQUIRED_PLANTS = {
    "KGF/coking",
    "BF/hot stove",
    "BOF/OSF",
    "Sinter",
    "PEFA/pelletizing",
    "DRP",
    "EAF",
    "DSP",
    "HSM/WBW",
    "Linde/ASU",
    "Boilers K15/K16",
    "Boilers K23/K24",
    "Boiler K41",
    "STEG11",
    "TG2",
    "IJ01/VN25 generator interface",
    "residual/background electricity",
    "residual/background NG",
    "WAG flaring/spill",
    "buffers/stores",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5p_h_outputs() -> Path:
    run_s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics()
    return C5P_H_DIR


def test_c5p_h_outputs_parse_and_have_required_columns(c5p_h_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_h_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    for name in ["s4_4c5p_h_stage_gate.json", "s4_4c5p_h_summary.json"]:
        json.loads((c5p_h_outputs / name).read_text(encoding="utf-8"))
    assert _read_csv(c5p_h_outputs / "s4_4c5p_h_run_registry.csv")
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_h_outputs / "s4_4c5p_h_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_co2_and_plant_energy_anchor_boundary_diagnostics"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["residual_electricity_policy_ready"] is False
    assert gate["residual_ng_policy_ready"] is False
    assert gate["ETS_readiness"] == "NO_GO"
    assert gate["economics_readiness"] == "NO_GO"


def test_c5p_h_preserves_current_c5_stage_metrics(c5p_h_outputs: Path):
    gate = json.loads((c5p_h_outputs / "s4_4c5p_h_stage_gate.json").read_text(encoding="utf-8"))
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
    assert p_g_gate["C0_modelled_exposure_pre_floor_TWh_y"] == pytest.approx(-0.324941, abs=1e-6)
    assert p_e_gate["C1_generator_fuel_gap_PJ_y"] == pytest.approx(4.763389, abs=1e-6)
    assert p_d_gate["C1_24h_DRI_buffer_capacity_t"] == pytest.approx(15229.652603, abs=1e-6)
    assert p_c_gate["C0_24h_generator_electricity_actual_TWh_e_y"] == pytest.approx(2.067665, abs=1e-6)
    assert p_b_gate["C0_24h_total_steam_demand_t_y"] == pytest.approx(356130.613099, abs=1e-6)
    assert p_a_gate["C1_24h_total_oxygen_t_y"] == pytest.approx(982143.7312, abs=1e-6)


def test_plant_electricity_and_ng_anchor_coverage(c5p_h_outputs: Path):
    coverage = _read_csv(c5p_h_outputs / "c5_plant_energy_anchor_coverage_matrix.csv")
    plants = {row["plant_or_asset"] for row in coverage}
    assert REQUIRED_PLANTS <= plants
    assert {row["configuration"] for row in coverage} == {C0, C1}
    assert {row["energy_carrier"] for row in coverage} == {"electricity", "natural_gas"}
    assert all(row["coverage_status"] for row in coverage)
    assert all(row["can_support_residual_policy"] in {"true", "false"} for row in coverage)

    keyed = {(row["configuration"], row["plant_or_asset"], row["energy_carrier"]): row for row in coverage}
    assert keyed[(C1, "DRP", "electricity")]["coverage_status"] == "modelled_and_source_anchored"
    assert keyed[(C1, "DRP", "natural_gas")]["coverage_status"] == "modelled_and_source_anchored"
    assert keyed[(C1, "EAF", "electricity")]["coverage_status"] == "modelled_and_source_anchored"
    assert keyed[(C0, "residual/background electricity", "electricity")]["coverage_status"] == "missing_source_card"
    assert keyed[(C1, "residual/background NG", "natural_gas")]["coverage_status"] == "missing_source_card"
    assert keyed[(C1, "HSM/WBW", "natural_gas")]["coverage_status"] == "missing_source_card"

    electricity = _read_csv(c5p_h_outputs / "c5_plant_electricity_anchor_summary.csv")
    e_keyed = {(row["configuration"], row["plant_or_asset"]): row for row in electricity}
    assert _num(e_keyed[(C1, "EAF")]["current_model_electricity_twh_y"]) == pytest.approx(1.4137, abs=1e-6)
    assert _num(e_keyed[(C1, "Linde/ASU")]["current_model_electricity_twh_y"]) == pytest.approx(0.392857, abs=1e-6)
    assert e_keyed[(C0, "residual/background electricity")]["coverage_status"] == "missing_source_card"

    ng = _read_csv(c5p_h_outputs / "c5_plant_ng_anchor_summary.csv")
    ng_keyed = {(row["configuration"], row["plant_or_asset"]): row for row in ng}
    assert _num(ng_keyed[(C1, "DRP")]["current_model_ng_pj_y"]) == pytest.approx(27.516175, abs=1e-6)
    assert _num(ng_keyed[(C1, "IJ01/VN25 generator interface")]["current_model_ng_pj_y"]) == pytest.approx(4.1, abs=1e-6)
    assert ng_keyed[(C1, "residual/background NG")]["coverage_status"] == "missing_source_card"


def test_residual_readiness_source_repairs_are_explicit(c5p_h_outputs: Path):
    readiness = _read_csv(c5p_h_outputs / "c5_residual_policy_readiness_from_plant_anchors.csv")
    assert len(readiness) == 4
    assert all(row["residual_can_be_modelled"] == "false" for row in readiness)
    assert any(row["boundary"] == "electricity" and row["recommended_status"] == "not_ready_for_hard_residual_load" for row in readiness)
    assert any(row["boundary"] == "natural_gas" and row["recommended_status"] == "not_ready_for_hard_residual_load" for row in readiness)

    gaps = _read_csv(c5p_h_outputs / "c5_energy_anchor_source_gap_register.csv")
    gap_ids = {row["gap_id"] for row in gaps}
    assert {"GAP_ELEC_SITE", "GAP_NG_SITE", "GAP_CO2_WAG", "GAP_CO2_SCOPE2"} <= gap_ids
    assert all(row["recommended_action"] for row in gaps)


def test_co2_boundary_component_only_and_double_counting_visible(c5p_h_outputs: Path):
    inventory = _read_csv(c5p_h_outputs / "c5_co2_component_inventory.csv")
    components = {row["component"] for row in inventory}
    assert {
        "PEFA_diagnostic_CO2",
        "DRP_capture_stream",
        "EAF_midpoint_CO2",
        "DSP_direct_CO2",
        "boiler_generator_fuel_explicit_CO2",
        "NG_combustion_CO2_deferred",
        "WAG_combustion_or_flare_CO2_deferred",
        "electricity_scope2_CO2_deferred",
    } <= components
    drp = next(row for row in inventory if row["configuration"] == C1 and row["component"] == "DRP_capture_stream")
    assert _num(drp["co2_model_output_mt_y"]) == pytest.approx(0.794912, abs=1e-6)
    assert drp["emission_source_type"] == "capture_stream"
    assert drp["ets_ready"] == "false"

    boundary = {row["configuration"]: row for row in _read_csv(c5p_h_outputs / "c5_co2_boundary_matrix.csv")}
    assert _num(boundary[C0]["direct_process_co2_mt"]) == pytest.approx(0.452813, abs=1e-6)
    assert _num(boundary[C1]["direct_process_co2_mt"]) == pytest.approx(0.94324, abs=1e-6)
    assert _num(boundary[C1]["captured_co2_stream_mt"]) == pytest.approx(0.794912, abs=1e-6)
    assert boundary[C1]["wag_combustion_co2_mt"] == ""
    assert boundary[C1]["ng_combustion_co2_mt"] == ""
    assert boundary[C1]["electricity_scope2_co2_mt"] == ""
    assert boundary[C1]["ets_ready"] == "false"

    double_count = _read_csv(c5p_h_outputs / "c5_co2_double_counting_risk_matrix.csv")
    carriers = {row["carbon_carrier_or_source"] for row in double_count}
    assert {"BFG", "COG", "BOFG", "natural_gas", "DRP_capture_stream", "EAF_aggregate_CO2", "PEFA_aggregate_CO2", "electricity_scope2"} <= carriers
    assert all(row["recommended_policy"] for row in double_count)


def test_co2_factor_review_and_decisions_block_ets_economics(c5p_h_outputs: Path):
    factors = _read_csv(c5p_h_outputs / "c5_co2_factor_gap_and_source_review.csv")
    factor_ids = {row["factor_id"] for row in factors}
    assert {"FAC_BFG_COMBUSTION", "FAC_COG_CARBON", "FAC_BOFG_COMBUSTION", "FAC_NG_COMBUSTION", "FAC_SCOPE2_GRID"} <= factor_ids
    assert all(row["current_use_status"] != "active_ETS_factor" for row in factors)

    decisions = {row["decision_id"]: row for row in _read_csv(c5p_h_outputs / "c5_co2_energy_boundary_decision_register.csv")}
    assert decisions["DEC_CO2_BOUNDARY_OPTION"]["recommended_option"].startswith("A_component_diagnostic_only")
    assert decisions["DEC_WAG_CARBON_POLICY"]["must_fix_before_co2_objective"] == "true"
    assert decisions["DEC_ETS_ECONOMICS_READINESS"]["current_status"] == "NO_GO"


def test_red_flags_absent_and_caveats_present(c5p_h_outputs: Path):
    rows = _read_csv(c5p_h_outputs / "c5_co2_energy_boundary_red_flags.csv")
    failures = [row for row in rows if row["severity"] == "failure"]
    caveats = [row for row in rows if row["severity"] == "caveat"]
    assert failures
    assert all(row["active"] == "false" for row in failures)
    active_caveats = {row["red_flag"] for row in caveats if row["active"] == "true"}
    assert {
        "CO2_PLANT_ANCHOR_DIAGNOSTIC_ONLY",
        "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE",
        "PLANT_NG_ANCHORS_INCOMPLETE",
        "RESIDUAL_ELECTRICITY_POLICY_NOT_READY",
        "RESIDUAL_NG_POLICY_NOT_READY",
        "CO2_BOUNDARY_COMPONENT_ONLY",
        "ETS_NOT_READY",
        "ECONOMICS_NO_GO",
        "NOT_THESIS_APPROVED",
    } <= active_caveats
