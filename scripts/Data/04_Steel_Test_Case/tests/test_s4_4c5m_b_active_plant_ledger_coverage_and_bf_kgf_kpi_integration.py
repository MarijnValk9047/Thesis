from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import (  # noqa: E402
    C0,
    C1,
    COG_GROSS_MWH_PER_T_COKE,
    WAG_TOL_MWH,
)
from steel.s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import (  # noqa: E402
    C5M_B_DIR,
    CURRENT_C5_ELECTRICITY_SCOPE,
    EXPECTED_COMPONENTS,
    STAGE,
    run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _extract(label: str, text: str) -> float:
    match = re.search(rf"{re.escape(label)}=([-0-9.]+)", text)
    assert match, text
    return float(match.group(1))


@pytest.fixture(scope="module")
def c5m_b_outputs() -> Path:
    run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration()
    return C5M_B_DIR


def test_c5m_b_required_outputs_and_stage_status(c5m_b_outputs: Path):
    required = [
        "s4_4c5m_b_stage_gate.json",
        "s4_4c5m_b_run_registry.csv",
        "s4_4c5m_b_plant_coverage_matrix.csv",
        "s4_4c5m_b_plant_kpi_table.csv",
        "s4_4c5m_b_modelled_totals.csv",
        "s4_4c5m_b_wag_carrier_ledger.csv",
        "s4_4c5m_b_electricity_ledger.csv",
        "s4_4c5m_b_steam_utility_ledger.csv",
        "s4_4c5m_b_co2_diagnostic_ledger.csv",
        "s4_4c5m_b_coke_balance_diagnostic.csv",
        "s4_4c5m_b_anchor_context_gaps.csv",
        "s4_4c5m_b_red_flags.csv",
        "s4_4c5m_b_change_detection.csv",
        "s4_4c5m_b_compact_table_for_chat.csv",
        "s4_4c5m_b_plant_ledger_coverage_report.json",
        "s4_4c5m_b_summary.json",
    ]
    for filename in required:
        path = c5m_b_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_b_outputs / "s4_4c5m_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_plant_ledger_coverage_with_open_coke_balance_gap"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["hard_redflag_count"] == 0
    assert gate["open_coke_gap_redflag_count"] > 0
    assert "BF_and_KGF_are_implemented_in_underlying_C5_ledgers" in gate["bf_kgf_implementation_status"]


def test_c5m_b_plant_coverage_matrix_includes_bf_kgf_and_expected_components(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_plant_coverage_matrix.csv")
    components = {row["plant_or_controller"] for row in rows}
    assert set(EXPECTED_COMPONENTS).issubset(components)

    by_key = {
        (row["configuration"], int(row["horizon_hours"]), row["plant_or_controller"]): row
        for row in rows
    }
    for horizon in {int(row["horizon_hours"]) for row in rows}:
        assert by_key[(C0, horizon, "KGF1")]["active_status"] == "active"
        assert by_key[(C0, horizon, "KGF2")]["active_status"] == "active"
        assert by_key[(C0, horizon, "BF6")]["active_status"] == "active"
        assert by_key[(C0, horizon, "BF7")]["active_status"] == "active"
        assert by_key[(C1, horizon, "KGF1")]["active_status"] == "active"
        assert by_key[(C1, horizon, "KGF2")]["active_status"] == "inactive_or_not_applicable"
        assert by_key[(C1, horizon, "BF6")]["active_status"] == "active"
        assert by_key[(C1, horizon, "BF7")]["active_status"] == "inactive_or_not_applicable"

    for row in rows:
        if row["plant_or_controller"] in {"BF6", "BF7"} and row["active_status"] == "active":
            assert row["WAG_generation"] == "included"
            assert row["included_in_WAG_generation_total"] == "included"
            assert row["CO2_diagnostic"] == "included"
        if row["plant_or_controller"] in {"KGF1", "KGF2"} and row["active_status"] == "active":
            assert row["WAG_generation"] == "included"
            assert row["WAG_consumption"] == "included"
            assert row["included_in_WAG_consumption_total"] == "included"


def test_c5m_b_bf_and_kgf_kpi_rows_show_self_use_deductions(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_plant_kpi_table.csv")
    for row in rows:
        if row["active_status"] != "active":
            continue
        if row["plant_or_controller"] in {"BF6", "BF7"}:
            gross = _extract("gross_BFG", row["caveat/status"])
            hot_stove = _extract("hot_stove_deduction", row["caveat/status"])
            surplus = _extract("BFG_surplus", row["material_outputs_summary"])
            assert surplus == pytest.approx(gross - hot_stove, abs=WAG_TOL_MWH)
            assert "process_electricity" in row["included_in_totals_flags"]
        if row["plant_or_controller"] in {"KGF1", "KGF2"}:
            coke = _num(row["activity_driver_value"])
            self_use = _extract("COG_self_use", row["WAG_consumed_by_carrier"])
            surplus = _extract("COG", row["WAG_generated_by_carrier"])
            assert surplus == pytest.approx(coke * COG_GROSS_MWH_PER_T_COKE - self_use, abs=WAG_TOL_MWH)
            assert "KGF underfiring deducted before COG surplus" in row["caveat/status"]


def test_c5m_b_ledgers_include_bf_kgf_scope_expansion_without_full_site_label(c5m_b_outputs: Path):
    totals = _read_csv(c5m_b_outputs / "s4_4c5m_b_modelled_totals.csv")
    electricity = _read_csv(c5m_b_outputs / "s4_4c5m_b_electricity_ledger.csv")
    steam = _read_csv(c5m_b_outputs / "s4_4c5m_b_steam_utility_ledger.csv")
    co2 = _read_csv(c5m_b_outputs / "s4_4c5m_b_co2_diagnostic_ledger.csv")

    for row in totals:
        assert row["process_electricity_scope_label"] == CURRENT_C5_ELECTRICITY_SCOPE
        assert row["process_electricity_scope_label"] != "full_site_electricity"
        assert "not_full_site_electricity" in row["process_electricity_scope_label"]
        assert row["expected_total_scope_expansion_due_to_BF_KGF_ledger_inclusion"] == "true"
        assert _num(row["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) > _num(row["old_C5m_a_process_electricity_site_MWh_e_y"])
        assert _num(row["BF_electricity_site_MWh_e_y"]) > 0.0
        assert _num(row["KGF_electricity_site_MWh_e_y"]) > 0.0
        assert _num(row["new_diagnostic_CO2_including_KGF_site_t_y"]) > _num(row["old_C5m_a_diagnostic_CO2_site_t_y"])
        assert row["WAG_invariant_status"] == "pass"
        assert row["LHV_consistency_status"] == "pass"
        assert row["CO2_double_counting_guard_status"] == "pass"

    for row in electricity:
        if row["plant_group"] in {"BF", "KGF"}:
            assert row["included_in_modelled_process_electricity_total"] == "true"
            assert row["status"] == "included_governed_development_coefficients"
    for row in steam:
        if row["plant_group"] in {"BF", "KGF", "Sinter_Plant"}:
            assert row["included_in_modelled_steam_total"] == "true"
    for row in co2:
        assert row["included_in_ETS_objective"] == "false"
        assert row["double_count_guard_status"] == "pass"


def test_c5m_b_wag_generation_totals_and_controller_guards_pass(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_wag_carrier_ledger.csv")
    by_case = {}
    for row in rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        by_case.setdefault(key, {})[row["carrier"]] = row
        assert row["status"] == "pass"
        assert abs(_num(row["balance_error_site_MWh_LHV_y"])) <= WAG_TOL_MWH

    for carriers in by_case.values():
        assert {"BFG", "COG", "BOFG"}.issubset(carriers)
        assert _num(carriers["BFG"]["generated_site_MWh_LHV_y"]) > 0.0
        assert _num(carriers["COG"]["generated_site_MWh_LHV_y"]) > 0.0
        assert _num(carriers["BOFG"]["generated_site_MWh_LHV_y"]) > 0.0


def test_c5m_b_change_detection_preserves_upstream_outputs(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_change_detection.csv")
    for row in rows:
        if row["expected_total_scope_expansion_due_to_BF_KGF_ledger_inclusion"] == "true":
            assert row["status"] == "expected_scope_expansion"
            assert abs(_num(row["delta_value"])) > 0.0
        else:
            assert row["status"] == "pass"
            assert abs(_num(row["delta_value"])) <= 1.0

    totals = _read_csv(c5m_b_outputs / "s4_4c5m_b_modelled_totals.csv")
    assert all(row["HSM_heat_case"] == "base_0_50" for row in totals)


def test_c5m_b_red_flags_are_hard_false_with_open_coke_gap_visible(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_red_flags.csv")
    expected_flags = {
        "redflag_active_plant_missing_kpi_coverage",
        "redflag_bf_missing_from_electricity_total_when_coefficient_governed",
        "redflag_kgf_missing_from_electricity_total_when_coefficient_governed",
        "redflag_bf_missing_from_WAG_generation_total",
        "redflag_kgf_missing_from_WAG_generation_total",
        "redflag_bf_hot_stove_not_deducted_before_BFG_surplus",
        "redflag_kgf_underfiring_not_deducted_before_COG_surplus",
        "redflag_coke_balance_gap_unexplained",
        "redflag_process_electricity_labelled_full_site",
        "redflag_steam_demand_missing_for_active_governed_plant",
        "redflag_co2_diagnostic_missing_for_active_governed_plant",
        "redflag_WAG_invariant_failed",
        "redflag_LHV_failed",
        "redflag_CO2_double_counting_failed",
        "redflag_C5k_targets_changed",
        "redflag_C5j_BOF_coefficients_changed",
        "redflag_C5l_d_HSM_heat_case_changed",
        "redflag_C5m_Sinter_outputs_changed",
    }
    for row in rows:
        assert expected_flags.issubset(row.keys())
        assert int(row["hard_redflag_count"]) == 0
        assert row["redflag_coke_balance_gap_unexplained"] == "true"
        assert int(row["open_coke_gap_redflag_count"]) == 1
        assert row["status"] == "pass_with_open_coke_gap"


def test_c5m_b_coke_balance_diagnostic_does_not_hide_gaps(c5m_b_outputs: Path):
    rows = _read_csv(c5m_b_outputs / "s4_4c5m_b_coke_balance_diagnostic.csv")
    assert rows
    for row in rows:
        assert row["external_coke_import_or_shortfall_supported"] == "false"
        assert row["redflag_coke_balance_gap_unexplained"] == "true"
        assert row["status"] == "open_gap_reported_not_forced"
        assert abs(_num(row["coke_balance_gap_site_t_y"])) > 1.0


def test_c5m_b_sinter_and_hsm_reporting_guards_remain_active(c5m_b_outputs: Path):
    coverage = _read_csv(c5m_b_outputs / "s4_4c5m_b_plant_coverage_matrix.csv")
    for row in coverage:
        if row["plant_or_controller"] == "Sinter_Plant":
            assert row["WAG_generation"] == "intentionally_not_applicable"
            assert row["WAG_consumption"] == "included"
            assert row["steam_demand"] == "included"
        if row["plant_or_controller"] == "HSM_WBW":
            assert row["CO2_diagnostic"] == "blocked_missing_governed_parameter"

    kpis = _read_csv(c5m_b_outputs / "s4_4c5m_b_plant_kpi_table.csv")
    for row in kpis:
        if row["plant_or_controller"] == "Sinter_Plant":
            assert "COG=" in row["WAG_consumed_by_carrier"]
            assert row["WAG_generated_by_carrier"] == ""
