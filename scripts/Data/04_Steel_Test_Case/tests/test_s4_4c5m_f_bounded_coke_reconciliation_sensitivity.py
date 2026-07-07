from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5h_blast_furnace_controller_parameterisation import BF_COKE_RATE_T_PER_T_HM  # noqa: E402
from steel.s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit import BF_COKE_RATE_LOW  # noqa: E402
from steel.s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report import C5M_E_DIR  # noqa: E402
from steel.s4_4c5m_f_bounded_coke_reconciliation_sensitivity import (  # noqa: E402
    C5M_F_DIR,
    STAGE,
    run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _keyed_case(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["case_id"]): row for row in rows}


@pytest.fixture(scope="module")
def c5m_f_outputs() -> Path:
    run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity()
    return C5M_F_DIR


def test_c5m_f_required_outputs_and_stage_status(c5m_f_outputs: Path):
    required = [
        "s4_4c5m_f_stage_gate.json",
        "s4_4c5m_f_run_registry.csv",
        "s4_4c5m_f_scenario_definitions.csv",
        "s4_4c5m_f_coke_balance_by_scenario.csv",
        "s4_4c5m_f_bf_coke_rate_range_checks.csv",
        "s4_4c5m_f_kgf_anchor_checks.csv",
        "s4_4c5m_f_kgf_kpi_propagation.csv",
        "s4_4c5m_f_bf_coke_rate_impact.csv",
        "s4_4c5m_f_wag_propagation.csv",
        "s4_4c5m_f_co2_propagation.csv",
        "s4_4c5m_f_option_comparison.csv",
        "s4_4c5m_f_recommendation.csv",
        "s4_4c5m_f_red_flags.csv",
        "s4_4c5m_f_compact_table_for_chat.csv",
        "s4_4c5m_f_bounded_coke_reconciliation_report.json",
        "s4_4c5m_f_summary.json",
    ]
    for filename in required:
        path = c5m_f_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_f_outputs / "s4_4c5m_f_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_bounded_coke_reconciliation_sensitivity"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["baseline_unchanged_confirmation"] is True
    assert gate["external_coke_implemented"] is False
    assert gate["case_1_closure_count"] == 4
    assert gate["failure_count"] == 0


def test_c5m_f_case_0_matches_repaired_c5m_e_baseline(c5m_f_outputs: Path):
    c5m_e = _keyed(_read_csv(C5M_E_DIR / "s4_4c5m_e_repaired_coke_balance.csv"))
    coke = _keyed_case(_read_csv(c5m_f_outputs / "s4_4c5m_f_coke_balance_by_scenario.csv"))
    for key, e_row in c5m_e.items():
        row = coke[(*key, "case_0_repaired_current_baseline")]
        assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(BF_COKE_RATE_T_PER_T_HM, abs=1e-12)
        assert _num(row["KGF_output_site_t_y"]) == pytest.approx(_num(e_row["KGF_coke_output_site_t_y"]), abs=1e-6)
        assert _num(row["BF_coke_demand_site_t_y"]) == pytest.approx(_num(e_row["BF_coke_demand_site_t_y"]), abs=1e-6)
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(_num(e_row["coke_balance_gap_site_t_y"]), abs=1e-6)
        assert row["gap_closed"] == "false"
        assert row["baseline_changed"] == "false"


def test_c5m_f_scenario_definition_governance_fields(c5m_f_outputs: Path):
    rows = _read_csv(c5m_f_outputs / "s4_4c5m_f_scenario_definitions.csv")
    expected_cases = {
        "case_0_repaired_current_baseline",
        "case_1_active_scaled_KGF_anchor_exact_BF_rate",
        "case_2_active_scaled_KGF_anchor_low_BF_rate",
        "case_3_raw_public_KGF_anchor_exact_BF_rate",
    }
    grouped: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        grouped.setdefault((row["configuration"], int(row["horizon_hours"])), set()).add(row["case_id"])
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["input_status"] in {"repaired_baseline_reference", "reconciliation_sensitivity"}
        if row["case_id"] != "case_0_repaired_current_baseline":
            assert "not" in row["caveat"] or "sensitivity" in row["caveat"]
    for seen in grouped.values():
        assert seen == expected_cases


def test_c5m_f_case_1_uses_active_scaled_anchor_exact_rates_and_closes(c5m_f_outputs: Path):
    anchors = _keyed(_read_csv(C5M_E_DIR / "s4_4c5m_e_kgf_anchor_context.csv"))
    coke = _keyed_case(_read_csv(c5m_f_outputs / "s4_4c5m_f_coke_balance_by_scenario.csv"))
    for key, anchor in anchors.items():
        row = coke[(*key, "case_1_active_scaled_KGF_anchor_exact_BF_rate")]
        assert _num(row["KGF_output_site_t_y"]) == pytest.approx(_num(anchor["active_scaled_public_KGF_anchor_site_t_y"]), abs=1e-6)
        assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(
            _num(row["KGF_output_site_t_y"]) / _num(row["BF_HM_driver_site_t_y"]),
            abs=1e-9,
        )
        assert row["gap_closed"] == "true"
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(0.0, abs=1.0)
        assert row["BF_coke_rate_within_source_range"] == "true"
        assert row["source_support_classification"] == "evidence_bounded_reconciliation_sensitivity"
        if row["configuration"].startswith("C0"):
            assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(0.285714286, abs=1e-9)
            assert row["C0_required_rate_near_low_bound"] == "true"
        if row["configuration"].startswith("C1"):
            assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(0.354314341, abs=1e-9)
            assert row["C0_required_rate_near_low_bound"] == "false"


def test_c5m_f_case_2_low_rate_reports_surplus(c5m_f_outputs: Path):
    coke = _read_csv(c5m_f_outputs / "s4_4c5m_f_coke_balance_by_scenario.csv")
    rows = [row for row in coke if row["case_id"] == "case_2_active_scaled_KGF_anchor_low_BF_rate"]
    assert len(rows) == 4
    for row in rows:
        assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(BF_COKE_RATE_LOW, abs=1e-12)
        assert row["gap_closed"] == "true"
        assert _num(row["coke_surplus_site_t_y"]) > 0.0
        assert row["source_support_classification"] == "low_coke_rate_optimistic_sensitivity"
        assert row["recommended_role"] == "sensitivity"


def test_c5m_f_case_3_uses_raw_public_kgf_anchor(c5m_f_outputs: Path):
    anchors = _keyed(_read_csv(C5M_E_DIR / "s4_4c5m_e_kgf_anchor_context.csv"))
    coke = _keyed_case(_read_csv(c5m_f_outputs / "s4_4c5m_f_coke_balance_by_scenario.csv"))
    for key, anchor in anchors.items():
        row = coke[(*key, "case_3_raw_public_KGF_anchor_exact_BF_rate")]
        assert _num(row["KGF_output_site_t_y"]) == pytest.approx(_num(anchor["raw_public_KGF_anchor_site_t_y"]), abs=1e-6)
        assert row["KGF_output_relation_to_public_anchor"] == "equals_raw_public_KGF_anchor"
        assert row["gap_closed"] == "true"
        assert row["BF_coke_rate_within_source_range"] == "true"
        assert row["source_support_classification"] == "raw_anchor_sensitivity_not_active_model_baseline"


def test_c5m_f_kgf_kpi_propagation_for_changed_output(c5m_f_outputs: Path):
    rows = _read_csv(c5m_f_outputs / "s4_4c5m_f_kgf_kpi_propagation.csv")
    assert rows
    for row in rows:
        if row["case_id"] == "case_0_repaired_current_baseline":
            assert _num(row["delta_KGF_coke_output_t_y"]) == pytest.approx(0.0, abs=1e-9)
            assert row["KGF_output_changed"] == "false"
        else:
            assert _num(row["delta_KGF_coke_output_t_y"]) > 0.0
            assert _num(row["delta_dry_coal_input_t_y"]) > 0.0
            assert _num(row["delta_KGF_electricity_MWh_y"]) > 0.0
            assert _num(row["delta_KGF_steam_proxy_MWh_y"]) > 0.0
            assert _num(row["delta_COG_generation_MWh_LHV_y"]) > 0.0
            assert _num(row["delta_KGF_underfiring_MWh_LHV_y"]) > 0.0
            assert _num(row["delta_net_COG_surplus_MWh_LHV_y"]) > 0.0
            assert _num(row["delta_KGF_CO2_t_y"]) > 0.0
            assert row["KGF_output_changed"] == "true"
        assert row["KPI_deltas_reported"] == "true"
        assert row["baseline_changed"] == "false"


def test_c5m_f_wag_and_co2_propagation_exist_and_pass(c5m_f_outputs: Path):
    wag = _read_csv(c5m_f_outputs / "s4_4c5m_f_wag_propagation.csv")
    co2 = _read_csv(c5m_f_outputs / "s4_4c5m_f_co2_propagation.csv")
    assert len(wag) == 16
    assert len(co2) == 16
    for row in wag:
        assert _num(row["gross_BFG_generated_MWh_LHV_y"]) > 0.0
        assert _num(row["net_BFG_after_BF_hot_stove_MWh_LHV_y"]) > 0.0
        assert _num(row["net_COG_after_KGF_underfiring_MWh_LHV_y"]) > 0.0
        assert _num(row["BOFG_available_MWh_LHV_y"]) > 0.0
        assert row["COG_HSM_Sinter_demands_still_served"] == "true"
        assert row["HSM_unserved_reheat_MWh_y"] == "0.0"
        assert row["Sinter_unserved_gas_MWh_y"] == "0.0"
        assert row["WAG_invariant_status"] == "pass"
        assert row["WAG_market_valuation_added"] == "false"
        assert row["WAG_export_revenue_added"] == "false"
    for row in co2:
        assert row["BF_CO2_changed_by_BF_coke_rate_sensitivity"] == "false"
        assert row["BOF_CO2_changed"] == "false"
        assert row["Sinter_CO2_changed"] == "false"
        assert row["HSM_CO2_status"] == "blocked_missing_governed_combustion_emission_factors"
        assert row["fuel_combustion_CO2_activated"] == "false"
        assert row["CO2_double_counting_guard_status"] == "pass"


def test_c5m_f_bf_coke_rate_impact_caveats(c5m_f_outputs: Path):
    rows = _read_csv(c5m_f_outputs / "s4_4c5m_f_bf_coke_rate_impact.csv")
    assert rows
    for row in rows:
        if row["case_id"] == "case_0_repaired_current_baseline":
            assert row["BF_coke_rate_changed_vs_baseline"] == "false"
            assert _num(row["delta_BF_coke_demand_t_y"]) == pytest.approx(0.0, abs=1e-6)
        else:
            assert row["BF_coke_rate_changed_vs_baseline"] == "true"
            assert _num(row["delta_BF_coke_demand_t_y"]) < 0.0
        assert row["BF_aggregate_CO2_unchanged_if_hot_metal_unchanged"] == "true"
        assert row["BFG_generation_unchanged_if_tied_to_hot_metal_not_coke_rate"] == "true"
        assert row["coke_carbon_explicit_BF_CO2_mode"] == "inactive_deferred"


def test_c5m_f_recommendation_and_red_flags(c5m_f_outputs: Path):
    recommendations = _read_csv(c5m_f_outputs / "s4_4c5m_f_recommendation.csv")
    for row in recommendations:
        assert row["case_1_closes_gap"] == "true"
        assert row["case_1_rate_within_range"] == "true"
        assert row["external_unmodelled_coke_recommended_now"] == "false"
        assert row["preferred_case_for_future_baseline_consideration"] == "case_1_active_scaled_KGF_anchor_exact_BF_rate"
        assert row["baseline_changed"] == "false"

    redflags = _read_csv(c5m_f_outputs / "s4_4c5m_f_red_flags.csv")
    expected = {
        "redflag_baseline_changed",
        "redflag_case_1_gap_not_closed",
        "redflag_case_1_required_rate_outside_range",
        "redflag_case_1_missing_KGF_KPI_deltas",
        "redflag_C0_required_rate_near_low_bound",
        "redflag_KGF_anchor_scenario_changes_WAG_without_reporting",
        "redflag_CO2_guard_failed",
        "redflag_WAG_invariant_failed",
        "redflag_external_coke_implemented",
        "redflag_C5k_targets_changed",
        "redflag_C5j_BOF_coefficients_changed",
        "redflag_C5l_d_HSM_heat_case_changed",
        "redflag_C5m_Sinter_outputs_changed",
    }
    for row in redflags:
        assert expected.issubset(row.keys())
        assert row["redflag_baseline_changed"] == "false"
        assert row["redflag_case_1_gap_not_closed"] == "false"
        assert row["redflag_case_1_required_rate_outside_range"] == "false"
        assert row["redflag_case_1_missing_KGF_KPI_deltas"] == "false"
        assert row["redflag_KGF_anchor_scenario_changes_WAG_without_reporting"] == "false"
        assert row["redflag_CO2_guard_failed"] == "false"
        assert row["redflag_WAG_invariant_failed"] == "false"
        assert row["redflag_external_coke_implemented"] == "false"
        assert row["redflag_C5k_targets_changed"] == "false"
        assert row["redflag_C5j_BOF_coefficients_changed"] == "false"
        assert row["redflag_C5l_d_HSM_heat_case_changed"] == "false"
        assert row["redflag_C5m_Sinter_outputs_changed"] == "false"
        assert int(row["hard_redflag_count"]) == 0
        if row["configuration"].startswith("C0"):
            assert row["redflag_C0_required_rate_near_low_bound"] == "true"
            assert int(row["caveat_redflag_count"]) == 1
        else:
            assert row["redflag_C0_required_rate_near_low_bound"] == "false"
            assert int(row["caveat_redflag_count"]) == 0
