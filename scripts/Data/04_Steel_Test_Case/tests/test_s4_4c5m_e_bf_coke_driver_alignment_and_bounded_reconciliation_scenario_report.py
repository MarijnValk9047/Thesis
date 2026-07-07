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
from steel.s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report import (  # noqa: E402
    C5M_E_DIR,
    STAGE,
    run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5m_e_outputs() -> Path:
    run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report()
    return C5M_E_DIR


def test_c5m_e_required_outputs_and_stage_status(c5m_e_outputs: Path):
    required = [
        "s4_4c5m_e_stage_gate.json",
        "s4_4c5m_e_run_registry.csv",
        "s4_4c5m_e_repaired_coke_balance.csv",
        "s4_4c5m_e_pre_repair_comparison.csv",
        "s4_4c5m_e_kgf_anchor_context.csv",
        "s4_4c5m_e_bounded_reconciliation_scenarios.csv",
        "s4_4c5m_e_kpi_impact_diagnostics.csv",
        "s4_4c5m_e_recommendation.csv",
        "s4_4c5m_e_red_flags.csv",
        "s4_4c5m_e_compact_table_for_chat.csv",
        "s4_4c5m_e_bf_coke_driver_alignment_report.json",
        "s4_4c5m_e_summary.json",
    ]
    for filename in required:
        path = c5m_e_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_e_outputs / "s4_4c5m_e_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_bf_coke_driver_alignment_report"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["baseline_driver_repair_confirmation"] is True
    assert gate["no_coefficient_change_confirmation"] is True
    assert gate["driver_mismatch_count_after_repair"] == 0
    assert gate["failure_count"] == 0


def test_c5m_e_bf_coke_demand_uses_c5k_no_buffer_driver(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_repaired_coke_balance.csv")
    assert rows
    for row in rows:
        driver = _num(row["C5k_no_buffer_BF_hot_metal_site_t_y"])
        demand = _num(row["BF_coke_demand_site_t_y"])
        assert row["BF_HM_driver_used"] == "C5k_no_buffer_BF_hot_metal_normalised_site_t_y"
        assert demand == pytest.approx(driver * BF_COKE_RATE_T_PER_T_HM, abs=1e-6)
        assert _num(row["implied_BF_HM_from_coke_demand_site_t_y"]) == pytest.approx(driver, abs=1e-6)
        assert _num(row["driver_mismatch_residual_t_y"]) == pytest.approx(0.0, abs=1e-6)
        assert row["BF_COKE_DEMAND_DRIVER_MATCHES_C5K_NO_BUFFER_HM"] == "true"
        assert row["redflag_bf_coke_demand_driver_mismatch"] == "false"
        assert row["status"] == "pass_repaired_driver_aligned_to_C5k_no_buffer_HM"


def test_c5m_e_repair_reduces_coke_demand_and_reports_updated_gap(c5m_e_outputs: Path):
    repaired = _keyed(_read_csv(c5m_e_outputs / "s4_4c5m_e_repaired_coke_balance.csv"))
    comparison = _keyed(_read_csv(c5m_e_outputs / "s4_4c5m_e_pre_repair_comparison.csv"))
    assert repaired
    for key, row in repaired.items():
        comp = comparison[key]
        assert _num(comp["repaired_BF_coke_demand_site_t_y"]) == pytest.approx(_num(row["BF_coke_demand_site_t_y"]), abs=1e-6)
        assert _num(comp["delta_BF_coke_demand_site_t_y"]) < 0.0
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(
            _num(row["KGF_coke_output_site_t_y"]) - _num(row["BF_coke_demand_site_t_y"]),
            abs=1e-6,
        )
        assert _num(comp["repaired_driver_mismatch_t_y"]) == pytest.approx(0.0, abs=1e-6)
        assert comp["driver_repair_changed_only_BF_coke_demand_ledger"] == "true"

    c0 = next(row for row in repaired.values() if row["configuration"].startswith("C0") and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in repaired.values() if row["configuration"].startswith("C1") and int(row["horizon_hours"]) == 24)
    assert _num(c0["coke_gap_Mt_y"]) == pytest.approx(-0.516, abs=0.005)
    assert _num(c1["coke_gap_Mt_y"]) == pytest.approx(-0.320, abs=0.005)


def test_c5m_e_baseline_coefficients_and_kgf_kpis_unchanged(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_repaired_coke_balance.csv")
    for row in rows:
        assert _num(row["BF_COKE_RATE_T_PER_T_HM"]) == pytest.approx(BF_COKE_RATE_T_PER_T_HM, abs=1e-12)
        assert row["BF_coke_rate_changed"] == "false"
        assert row["KGF_output_changed"] == "false"
        assert row["KGF_baseline_kpis_unchanged"] == "true"
        assert row["WAG_generation_changed"] == "false"
        assert row["WAG_invariant_status"] == "pass"
        assert row["CO2_double_counting_guard_status"] == "pass"
        assert row["HSM_heat_case"] == "base_0_50"


def test_c5m_e_reports_raw_and_active_scaled_kgf_anchors(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_kgf_anchor_context.csv")
    assert rows
    for row in rows:
        raw = _num(row["raw_public_KGF_anchor_site_t_y"])
        active_scaled = _num(row["active_scaled_public_KGF_anchor_site_t_y"])
        assert raw > 0.0
        assert active_scaled > 0.0
        assert active_scaled <= raw
        assert row["raw_anchor_basis"].endswith("validation_anchor_not_dispatch_constraint")
        assert row["active_scaled_anchor_basis"].startswith("raw_public_KGF_anchor_scaled")
        assert row["KGF_output_changed_in_baseline"] == "false"


def test_c5m_e_all_bounded_reconciliation_scenarios_exist(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_bounded_reconciliation_scenarios.csv")
    expected = {
        "A1_current_rate_current_KGF",
        "A2_low_rate_current_KGF",
        "A3_required_rate_current_KGF",
        "B1_current_rate_raw_public_anchor",
        "B2_low_rate_raw_public_anchor",
        "B3_required_rate_raw_public_anchor",
        "C1_current_rate_active_scaled_anchor",
        "C2_low_rate_active_scaled_anchor",
        "C3_required_rate_active_scaled_anchor",
    }
    grouped: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        grouped.setdefault((row["configuration"], int(row["horizon_hours"])), set()).add(row["scenario_id"])
        assert _num(row["BF_coke_demand_site_t_y"]) == pytest.approx(
            _num(row["BF_HM_driver_site_t_y"]) * _num(row["BF_coke_rate_t_per_t_HM"]),
            abs=1.0,
        )
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(
            _num(row["KGF_output_assumption_site_t_y"]) - _num(row["BF_coke_demand_site_t_y"]),
            abs=1e-6,
        )
        assert row["baseline_changed"] == "false"
    assert grouped
    for seen in grouped.values():
        assert seen == expected


def test_c5m_e_required_bf_coke_rates_are_range_checked(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_bounded_reconciliation_scenarios.csv")
    for row in rows:
        if row["scenario_id"] in {"A3_required_rate_current_KGF", "B3_required_rate_raw_public_anchor", "C3_required_rate_active_scaled_anchor"}:
            assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(
                _num(row["KGF_output_assumption_site_t_y"]) / _num(row["BF_HM_driver_site_t_y"]),
                abs=1e-6,
            )
        if row["scenario_id"] == "A3_required_rate_current_KGF":
            assert row["BF_coke_rate_range_status"] == "below_supported_range"
            assert row["gap_closed"] == "true"
        if row["scenario_id"] == "C3_required_rate_active_scaled_anchor":
            assert row["BF_coke_rate_range_status"] == "within_supported_range"
            assert row["gap_closed"] == "true"
            assert row["source_support_status"] == "active_scaled_public_anchor_evidence_bounded_scenario"


def test_c5m_e_low_rate_anchor_scenarios_close_without_baseline_change(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_bounded_reconciliation_scenarios.csv")
    matches = [row for row in rows if row["scenario_id"] in {"B2_low_rate_raw_public_anchor", "C2_low_rate_active_scaled_anchor"}]
    assert len(matches) == 8
    for row in matches:
        assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(BF_COKE_RATE_LOW, abs=1e-12)
        assert row["gap_closed"] == "true"
        assert row["BF_coke_rate_within_governed_range"] == "true"
        assert row["baseline_or_sensitivity_classification"] == "evidence_bounded_sensitivity_candidate"
        assert row["baseline_changed"] == "false"


def test_c5m_e_kpi_impacts_for_kgf_anchor_scenarios_are_reported(c5m_e_outputs: Path):
    rows = _read_csv(c5m_e_outputs / "s4_4c5m_e_kpi_impact_diagnostics.csv")
    assert rows
    scenario_ids = {row["scenario_id"] for row in rows}
    assert {
        "B1_current_rate_raw_public_anchor",
        "B2_low_rate_raw_public_anchor",
        "B3_required_rate_raw_public_anchor",
        "C1_current_rate_active_scaled_anchor",
        "C2_low_rate_active_scaled_anchor",
        "C3_required_rate_active_scaled_anchor",
    }.issubset(scenario_ids)
    for row in rows:
        assert _num(row["delta_KGF_coke_output_t_y"]) > 0.0
        assert _num(row["delta_dry_coal_input_t_y"]) > 0.0
        assert _num(row["delta_KGF_electricity_MWh_y"]) > 0.0
        assert _num(row["delta_KGF_steam_proxy_MWh_y"]) > 0.0
        assert _num(row["delta_raw_clean_COG_generation_MWh_LHV_y"]) > 0.0
        assert _num(row["delta_KGF_underfiring_MWh_LHV_y"]) > 0.0
        assert _num(row["delta_net_COG_surplus_MWh_LHV_y"]) > 0.0
        assert _num(row["delta_KGF_CO2_t_y"]) > 0.0
        assert row["kpi_deltas_reported"] == "true"
        assert row["baseline_changed"] == "false"


def test_c5m_e_recommendation_and_redflags(c5m_e_outputs: Path):
    recommendations = _read_csv(c5m_e_outputs / "s4_4c5m_e_recommendation.csv")
    for row in recommendations:
        assert row["driver_mismatch_resolved"] == "true"
        assert row["external_unmodelled_coke_recommended_now"] == "false"
        assert row["recommendation_priority"] == "next_candidate_reconciliation_active_scaled_KGF_anchor_plus_required_BF_coke_rate_sensitivity"
        assert row["active_scaled_anchor_required_rate_status"] == "within_supported_range"
        assert row["baseline_changed"] == "false"

    redflags = _read_csv(c5m_e_outputs / "s4_4c5m_e_red_flags.csv")
    expected = {
        "redflag_baseline_changed_unexpectedly",
        "redflag_bf_coke_demand_driver_mismatch",
        "redflag_bf_coke_rate_changed",
        "redflag_kgf_output_changed",
        "redflag_c5k_targets_changed",
        "redflag_c5j_bof_coefficients_changed",
        "redflag_c5l_d_hsm_heat_case_changed",
        "redflag_c5m_sinter_outputs_changed",
        "redflag_wag_invariant_failed",
        "redflag_co2_guard_failed",
        "redflag_required_bf_coke_rate_outside_range_in_recommended_scenario",
        "redflag_kgf_anchor_scenario_changes_kpis_without_reporting",
    }
    for row in redflags:
        assert expected.issubset(row.keys())
        for flag in expected:
            assert row[flag] == "false"
        assert int(row["hard_redflag_count"]) == 0
        assert row["status"] == "pass_repaired_driver_and_bounded_scenario_report"
