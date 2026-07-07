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
from steel.s4_4c5j_bof_osf_minimal_parameterisation import (  # noqa: E402
    BOF_CO2_MODE,
    C5H_DIR,
    C5J_DIR,
    SOURCE_CARD,
    run_s4_4c5j_bof_osf_minimal_parameterisation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5j_outputs() -> Path:
    run_s4_4c5j_bof_osf_minimal_parameterisation()
    return C5J_DIR


def test_c5j_required_outputs_exist_parse_and_stage_gate(c5j_outputs: Path):
    required = [
        "s4_4c5j_stage_gate.json",
        "s4_4c5j_run_registry.csv",
        "s4_4c5j_24h_summary.csv",
        "s4_4c5j_168h_summary.csv",
        "s4_4c5j_bof_osf_development_input_rows.csv",
        "s4_4c5j_bof_osf_parameter_register.csv",
        "s4_4c5j_bof_osf_report.csv",
        "s4_4c5j_bof_osf_anchor_gap_dashboard.csv",
        "s4_4c5j_wag_generation_consumption_by_plant.csv",
        "s4_4c5j_wag_aggregate_invariant.csv",
        "s4_4c5j_bof_co2_accounting_dashboard.csv",
        "s4_4c5j_lhv_consistency_checks.csv",
        "s4_4c5j_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5j_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5j_outputs / "s4_4c5j_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_bof_osf_minimal_parameterisation_with_validation_gaps"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["source_card_present"] is True
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["lhv_consistency_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["anchor_constraints_used_count"] == 0
    assert gate["direct_WAG_market_valuation_added"] is False
    assert gate["BOFG_export_revenue_added"] is False
    assert gate["forbidden_economic_features_added"] is False


def test_c5j_source_card_is_candidate_only():
    text = SOURCE_CARD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "candidate source-card" in lowered
    assert "thesis usability: false" in lowered
    assert "not exact tata truth" in lowered
    assert "BOF_HOT_METAL_INPUT_T_PER_T_LS_C0" in text
    assert "BOFG_LHV_MJ_PER_NM3" in text
    assert "8.6" in text
    assert "validation/reporting targets only" in lowered


def test_c5j_bof_parameters_are_governed_development_inputs(c5j_outputs: Path):
    rows = _read_csv(c5j_outputs / "s4_4c5j_bof_osf_development_input_rows.csv")
    required = {
        "BOF_HOT_METAL_INPUT_T_PER_T_LS_C0",
        "BOF_SCRAP_INPUT_T_PER_T_LS_C0",
        "BOF_HOT_METAL_INPUT_T_PER_T_LS_C1",
        "BOF_SCRAP_INPUT_T_PER_T_LS_C1",
        "BOF_OXYGEN_INPUT_NM3_PER_T_LS",
        "BOF_OXYGEN_INPUT_KG_PER_T_LS",
        "BOF_ELECTRICITY_MWH_PER_T_LS",
        "BOF_BOFG_OUTPUT_NM3_PER_T_LS",
        "BOF_DIRECT_CO2_T_PER_T_LS",
        "BOFG_LHV_MJ_PER_NM3",
    }
    assert required == {row["parameter_id"] for row in rows}
    for row in rows:
        assert row["input_status"] == "development_candidate"
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["development_executable"] == "true"
        assert row["applies_to_solver"] == "false"
        assert "not thesis-approved" in row["caveat"]


def test_c5j_coefficients_are_configuration_specific_and_not_modelbuilder_literals(c5j_outputs: Path):
    rows = {row["parameter_id"]: row for row in _read_csv(c5j_outputs / "s4_4c5j_bof_osf_development_input_rows.csv")}
    assert _num(rows["BOF_HOT_METAL_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.875)
    assert _num(rows["BOF_SCRAP_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.208)
    assert _num(rows["BOF_HOT_METAL_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.824)
    assert _num(rows["BOF_SCRAP_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.294)

    modelbuilder = Path("scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py").read_text(encoding="utf-8")
    for forbidden_literal in ("0.875", "0.208", "0.824", "0.294", "0.0268", "0.0825"):
        assert forbidden_literal not in modelbuilder


def test_c5j_bof_report_uses_governed_input_math(c5j_outputs: Path):
    report = _read_csv(c5j_outputs / "s4_4c5j_bof_osf_report.csv")
    assert len(report) == 4
    for row in report:
        ls_site = _num(row["bof_liquid_steel_site_t_y"])
        hm = _num(row["bof_hot_metal_input_t_per_t_LS"])
        scrap = _num(row["bof_scrap_input_t_per_t_LS"])
        metallic = hm + scrap
        assert _num(row["bof_hot_metal_input_site_t_y"]) == pytest.approx(ls_site * hm)
        assert _num(row["bof_scrap_input_site_t_y"]) == pytest.approx(ls_site * scrap)
        assert _num(row["bof_oxygen_input_site_Nm3_y"]) == pytest.approx(ls_site * 55.0)
        assert _num(row["bof_electricity_site_MWh_y"]) == pytest.approx(ls_site * 0.0268)
        assert _num(row["bof_direct_co2_site_t_y"]) == pytest.approx(ls_site * 0.0825)
        assert _num(row["bof_metallic_input_t_per_t_LS"]) == pytest.approx(metallic)
        assert _num(row["bof_liquid_steel_yield_per_t_metallic_input"]) == pytest.approx(1.0 / metallic)
        assert row["validation_anchors_used_as_constraints"] == "false"
        assert row["bof_driver_basis"] == "existing_liquid_steel_route_throughput"


def test_c5j_bofg_lhv_and_separate_wag_carrier(c5j_outputs: Path):
    report = _read_csv(c5j_outputs / "s4_4c5j_bof_osf_report.csv")
    for row in report:
        assert _num(row["bofg_lhv_MJ_per_Nm3"]) == pytest.approx(8.6)
        expected_mwh = _num(row["bof_bofg_output_site_Nm3_y"]) * 8.6 / 3600.0
        assert _num(row["bof_bofg_output_site_MWh_LHV_y"]) == pytest.approx(expected_mwh)
        assert _num(row["bof_bofg_output_site_PJ_LHV_y"]) == pytest.approx(expected_mwh * 3.6e-6)

    wag = _read_csv(c5j_outputs / "s4_4c5j_wag_generation_consumption_by_plant.csv")
    bofg_rows = [row for row in wag if row["carrier"] == "BOFG"]
    assert bofg_rows
    assert all(row["carrier"] != "WAG" for row in wag)
    assert any(row["plant_id"] == "BOF" and row["carrier"] == "BOFG" for row in wag)
    assert all(row["LHV_MJ_per_Nm3_used"] in {"8.6", "8.600000"} for row in bofg_rows)

    aggregate = _read_csv(c5j_outputs / "s4_4c5j_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(_num(row["BOFG_generated_MWh_y"]) > 0.0 for row in aggregate)


def test_c5j_direct_co2_reported_without_objective_double_count(c5j_outputs: Path):
    co2 = _read_csv(c5j_outputs / "s4_4c5j_bof_co2_accounting_dashboard.csv")
    direct = [row for row in co2 if row["emission_bucket"] == "BOF_direct_CO2_diagnostic"]
    combustion = [row for row in co2 if row["emission_bucket"] == "BOFG_combustion_CO2_potential"]
    assert direct and combustion
    assert all(row["CO2_mode"] == BOF_CO2_MODE for row in direct)
    assert all(_num(row["CO2_site_t_y"]) > 0.0 for row in direct)
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)
    assert all(row["included_in_total_direct_CO2"] == "false" for row in combustion)
    assert all(row["status"] == "pass" for row in co2)


def test_c5j_validation_anchors_are_gap_rows_not_constraints(c5j_outputs: Path):
    anchors = _read_csv(c5j_outputs / "s4_4c5j_bof_osf_anchor_gap_dashboard.csv")
    assert len(anchors) == 14
    assert all(row["constraint_used"] == "false" for row in anchors)
    assert all(row["anchor_status"] == "validation_reporting_only" for row in anchors)
    assert any(row["metric"] == "BOF_liquid_steel_output_t_y" and row["configuration"] == C0 for row in anchors)
    assert any(row["metric"] == "BF_BOF_route_liquid_steel_including_alloys_t_y" and row["configuration"] == C1 for row in anchors)


def test_c5j_preserves_c5h_bf_and_downstream_invariants(c5j_outputs: Path):
    c5h_gate = json.loads((C5H_DIR / "s4_4c5h_stage_gate.json").read_text(encoding="utf-8"))
    assert c5h_gate["decision"] == "pass_development_bf_controller_parameterisation_with_open_coke_and_co2_gaps"
    assert c5h_gate["wag_aggregate_invariant_fail_count"] == 0
    assert c5h_gate["lhv_consistency_fail_count"] == 0

    summary = _read_csv(C5H_DIR / "s4_4c5h_24h_summary.csv")
    c1 = next(row for row in summary if row["configuration_id"] == C1)
    final_product_site = _num(c1["final_product_proxy_t"]) * 365.0
    retained_site = final_product_site * _num(c1["retained_route_share"])
    eaf_site = final_product_site * _num(c1["drp_eaf_route_share"])
    assert retained_site > 0.0
    assert eaf_site > 0.0
    assert final_product_site == pytest.approx(retained_site + eaf_site)
