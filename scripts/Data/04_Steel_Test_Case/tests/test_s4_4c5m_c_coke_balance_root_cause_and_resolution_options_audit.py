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
from steel.s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR  # noqa: E402
from steel.s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit import (  # noqa: E402
    BF_COKE_RATE_LOW,
    C5M_C_DIR,
    STAGE,
    run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5m_c_outputs() -> Path:
    run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit()
    return C5M_C_DIR


def test_c5m_c_required_outputs_and_stage_status(c5m_c_outputs: Path):
    required = [
        "s4_4c5m_c_stage_gate.json",
        "s4_4c5m_c_run_registry.csv",
        "s4_4c5m_c_current_coke_balance_root_cause.csv",
        "s4_4c5m_c_source_range_summary.csv",
        "s4_4c5m_c_option_A_kgf_scaling_impacts.csv",
        "s4_4c5m_c_option_B_bf_coke_rate_sensitivity.csv",
        "s4_4c5m_c_option_C_external_coke_supply.csv",
        "s4_4c5m_c_option_D_kgf_efficiency_intensity_what_if.csv",
        "s4_4c5m_c_option_comparison.csv",
        "s4_4c5m_c_red_flags.csv",
        "s4_4c5m_c_compact_table_for_chat.csv",
        "s4_4c5m_c_coke_balance_audit_report.json",
        "s4_4c5m_c_summary.json",
    ]
    for filename in required:
        path = c5m_c_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_c_outputs / "s4_4c5m_c_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_coke_balance_audit_no_baseline_change"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["no_baseline_change_confirmation"] is True
    assert gate["failure_count"] == 0
    assert gate["baseline_hard_redflag_count"] == 0
    assert "Option_C_explicit_external_or_unmodelled_coke_supply" in gate["recommended_next_implementation_path"]


def test_c5m_c_current_coke_gap_matches_c5m_b(c5m_c_outputs: Path):
    current = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    c5m_b = _keyed(_read_csv(C5M_B_DIR / "s4_4c5m_b_coke_balance_diagnostic.csv"))
    assert current
    for key, row in current.items():
        source = c5m_b[key]
        assert _num(row["BF_coke_demand_site_t_y"]) == pytest.approx(_num(source["BF_coke_demand_site_t_y"]), abs=1e-6)
        assert _num(row["total_KGF_coke_output_site_t_y"]) == pytest.approx(_num(source["KGF_coke_production_site_t_y"]), abs=1e-6)
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(_num(source["coke_balance_gap_site_t_y"]), abs=1e-6)
        assert row["caused_by_KGF_output_too_low_relative_to_BF_demand"] == "true"
        assert row["caused_by_missing_external_coke_import_policy"] == "true"
        assert row["reporting_only_issue"] == "false"


def test_c5m_c_option_a_kgf_scaling_closes_gap_and_reports_all_kpi_deltas(c5m_c_outputs: Path):
    rows = _read_csv(c5m_c_outputs / "s4_4c5m_c_option_A_kgf_scaling_impacts.csv")
    required_delta_fields = [
        "additional_dry_coal_input_t_y",
        "additional_KGF_electricity_MWh_y",
        "additional_KGF_steam_proxy_MWh_y",
        "additional_KGF_steam_mass_t_y",
        "additional_raw_clean_COG_generation_MWh_LHV_y",
        "additional_KGF_underfiring_MWh_LHV_y",
        "additional_net_COG_surplus_MWh_LHV_y",
        "additional_KGF_CO2_t_y",
    ]
    for row in rows:
        assert _num(row["coke_gap_after_option_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["scaling_factor"]) > 1.0
        assert row["required_output_exceeds_source_anchor"] == "true"
        assert row["baseline_changed"] == "false"
        for field in required_delta_fields:
            assert _num(row[field]) > 0.0
        assert "residual_or_interface" in row["WAG_invariant_feasibility_status"]


def test_c5m_c_option_b_required_bf_coke_rate_and_range_status(c5m_c_outputs: Path):
    current = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    option_b = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_option_B_bf_coke_rate_sensitivity.csv"))
    for key, row in option_b.items():
        source = current[key]
        expected = _num(source["total_KGF_coke_output_site_t_y"]) / _num(source["BF_hot_metal_output_site_t_y"])
        assert _num(row["required_BF_coke_rate_t_per_t_HM"]) == pytest.approx(expected, abs=1e-6)
        assert _num(row["active_BF_coke_rate_t_per_t_HM"]) == pytest.approx(BF_COKE_RATE_T_PER_T_HM, abs=1e-12)
        assert _num(row["required_BF_coke_rate_t_per_t_HM"]) < BF_COKE_RATE_LOW
        assert row["required_rate_range_status"] == "below_candidate_range"
        assert row["COG_generation_changed"] == "false"
        assert row["WAG_totals_changed_under_current_model"] == "false"
        assert row["recommendation_role"] == "unsupported_without_new_evidence"


def test_c5m_c_option_c_external_supply_closes_gap_without_onsite_kpi_changes(c5m_c_outputs: Path):
    current = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    option_c = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_option_C_external_coke_supply.csv"))
    for key, row in option_c.items():
        source = current[key]
        expected_external = max(_num(source["BF_coke_demand_site_t_y"]) - _num(source["total_KGF_coke_output_site_t_y"]), 0.0)
        assert _num(row["external_coke_supply_to_BF_t_y"]) == pytest.approx(expected_external, abs=1e-6)
        assert _num(row["coke_balance_residual_after_external_supply_t_y"]) == pytest.approx(0.0, abs=1e-12)
        assert row["process_electricity_changed"] == "false"
        assert row["onsite_COG_generation_changed"] == "false"
        assert row["onsite_KGF_CO2_changed"] == "false"
        assert "not_public_Tata_truth" in row["interpretation"]


def test_c5m_c_option_d_required_intensity_changes_and_range_comparison(c5m_c_outputs: Path):
    current = _keyed(_read_csv(c5m_c_outputs / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    rows = _read_csv(c5m_c_outputs / "s4_4c5m_c_option_D_kgf_efficiency_intensity_what_if.csv")
    assert rows
    by_case = {}
    for row in rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        by_case.setdefault(key, {})[row["metric"]] = row
        scale = _num(row["scaling_factor_to_close_gap"])
        assert scale == pytest.approx(
            _num(current[key]["BF_coke_demand_site_t_y"]) / _num(current[key]["total_KGF_coke_output_site_t_y"]),
            abs=1e-6,
        )
        assert _num(row["required_value"]) == pytest.approx(_num(row["active_value"]) / scale, abs=1e-4)
        assert row["baseline_changed"] == "false"

    for metrics in by_case.values():
        assert metrics["coal_input_t_per_t_coke"]["candidate_range_status"] == "below_candidate_range"
        assert metrics["COG_yield_Nm3_per_t_coke"]["candidate_range_status"] == "below_candidate_range"
        assert metrics["underfiring_GJ_per_t_coke"]["candidate_range_status"] == "below_candidate_range"
        assert metrics["steam_GJ_per_t_coke"]["candidate_range_status"] == "within_candidate_range"
        assert metrics["direct_CO2_t_per_t_coke"]["candidate_range_status"] == "below_candidate_range"


def test_c5m_c_option_comparison_and_recommendation(c5m_c_outputs: Path):
    rows = {row["option_id"]: row for row in _read_csv(c5m_c_outputs / "s4_4c5m_c_option_comparison.csv")}
    assert set(rows) == {
        "Current_C5m_b_baseline",
        "A_scale_KGF_output_to_BF_coke_demand",
        "B_reduce_BF_coke_rate_to_existing_KGF_output",
        "C_explicit_external_or_unmodelled_coke_supply",
        "D_KGF_efficiency_improvement_more_coke_same_KPIs",
    }
    assert rows["A_scale_KGF_output_to_BF_coke_demand"]["changes_COG_generation"] == "true"
    assert rows["A_scale_KGF_output_to_BF_coke_demand"]["violates_or_overshoots_KGF_anchors"] == "true"
    assert rows["B_reduce_BF_coke_rate_to_existing_KGF_output"]["source_support_level"] == "unsupported_if_required_rate_below_low_range"
    assert rows["C_explicit_external_or_unmodelled_coke_supply"]["recommended_role"] == "lowest_governance_risk_next_development_patch_as_explicit_closure_policy"
    assert rows["D_KGF_efficiency_improvement_more_coke_same_KPIs"]["source_support_level"] == "unsupported_for_base"


def test_c5m_c_red_flags_are_baseline_false_with_option_caveats(c5m_c_outputs: Path):
    rows = _read_csv(c5m_c_outputs / "s4_4c5m_c_red_flags.csv")
    expected_flags = {
        "redflag_baseline_changed",
        "redflag_bf_coke_rate_changed",
        "redflag_kgf_coke_output_changed",
        "redflag_c5k_targets_changed",
        "redflag_c5m_b_kpis_changed",
        "redflag_option_A_exceeds_KGF_anchor",
        "redflag_option_B_required_coke_rate_below_supported_range",
        "redflag_option_D_required_intensity_outside_supported_range",
        "redflag_missing_source_range_for_efficiency_claim",
        "redflag_unexplained_coke_gap_still_hidden",
        "redflag_WAG_invariant_failed",
        "redflag_CO2_guard_failed",
    }
    for row in rows:
        assert expected_flags.issubset(row.keys())
        assert row["redflag_baseline_changed"] == "false"
        assert row["redflag_bf_coke_rate_changed"] == "false"
        assert row["redflag_kgf_coke_output_changed"] == "false"
        assert row["redflag_c5k_targets_changed"] == "false"
        assert row["redflag_c5m_b_kpis_changed"] == "false"
        assert row["redflag_unexplained_coke_gap_still_hidden"] == "false"
        assert row["redflag_WAG_invariant_failed"] == "false"
        assert row["redflag_CO2_guard_failed"] == "false"
        assert row["redflag_option_A_exceeds_KGF_anchor"] == "true"
        assert row["redflag_option_B_required_coke_rate_below_supported_range"] == "true"
        assert row["redflag_option_D_required_intensity_outside_supported_range"] == "true"
        assert row["redflag_missing_source_range_for_efficiency_claim"] == "false"
        assert int(row["baseline_hard_redflag_count"]) == 0
        assert int(row["option_redflag_count"]) == 3
