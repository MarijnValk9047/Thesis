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
from steel.s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit import (  # noqa: E402
    C5M_D_DIR,
    STAGE,
    run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5m_d_outputs() -> Path:
    run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit()
    return C5M_D_DIR


def test_c5m_d_required_outputs_and_stage_status(c5m_d_outputs: Path):
    required = [
        "s4_4c5m_d_stage_gate.json",
        "s4_4c5m_d_run_registry.csv",
        "s4_4c5m_d_bf_coke_demand_driver_consistency_audit.csv",
        "s4_4c5m_d_kgf_current_vs_public_anchor_audit.csv",
        "s4_4c5m_d_bounded_reconciliation_scenarios.csv",
        "s4_4c5m_d_kpi_propagation.csv",
        "s4_4c5m_d_efficiency_intensity_what_if.csv",
        "s4_4c5m_d_recommendation.csv",
        "s4_4c5m_d_red_flags.csv",
        "s4_4c5m_d_compact_table_for_chat.csv",
        "s4_4c5m_d_driver_consistency_and_bounded_reconciliation_report.json",
        "s4_4c5m_d_summary.json",
    ]
    for filename in required:
        path = c5m_d_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_d_outputs / "s4_4c5m_d_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_driver_consistency_and_bounded_reconciliation_audit"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["baseline_unchanged_confirmation"] is True
    assert gate["failure_count"] == 0
    assert gate["baseline_hard_redflag_count"] == 0
    assert gate["driver_mismatch_count"] == 4
    assert gate["bounded_C5k_low_rate_public_anchor_closure_count"] == 4


def test_c5m_d_driver_consistency_audit(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_bf_coke_demand_driver_consistency_audit.csv")
    assert rows
    for row in rows:
        implied = _num(row["BF_coke_demand_from_C5m_c_site_t_y"]) / _num(row["active_BF_coke_rate_t_per_t_HM"])
        assert _num(row["implied_BF_hot_metal_from_coke_demand_site_t_y"]) == pytest.approx(implied, abs=1e-6)
        assert row["BF_COKE_DEMAND_DRIVER_SOURCE"] == "C5h/C5m_c_pre_normalisation_BF_hot_metal_driver"
        assert row["C5K_NO_BUFFER_DRIVER_SOURCE"] == "C5k_bf_hot_metal_normalised_site_t_y"
        assert _num(row["C5k_no_buffer_BF_hot_metal_normalised_site_t_y"]) > 0.0
        assert _num(row["C5k_BOF_hot_metal_input_site_t_y"]) == pytest.approx(
            _num(row["C5k_no_buffer_BF_hot_metal_normalised_site_t_y"]), abs=1e-6
        )
        assert row["BF_COKE_DEMAND_DRIVER_MATCHES_C5K_NO_BUFFER_HM"] == "false"
        assert row["redflag_bf_coke_demand_driver_mismatch"] == "true"
        assert _num(row["difference_implied_driver_minus_C5k_no_buffer_HM_t_y"]) > 1.0


def test_c5m_d_kgf_current_vs_public_anchor_audit(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_kgf_current_vs_public_anchor_audit.csv")
    assert rows
    for row in rows:
        assert _num(row["current_C5_KGF_coke_output_site_t_y"]) > 0.0
        assert _num(row["public_KGF_anchor_output_site_t_y"]) > 0.0
        assert _num(row["gap_current_minus_public_anchor_t_y"]) == pytest.approx(
            _num(row["current_C5_KGF_coke_output_site_t_y"]) - _num(row["public_KGF_anchor_output_site_t_y"]),
            abs=1e-6,
        )
        assert row["redflag_kgf_current_output_below_public_anchor"] == "true"
        assert "active_C5f_production_scaled" in row["current_output_basis"]
        assert "validation_anchor" in row["public_anchor_basis"]


def test_c5m_d_all_bounded_reconciliation_scenarios_exist_and_compute_gaps(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_bounded_reconciliation_scenarios.csv")
    scenario_ids = {
        "S0_current_rate_current_KGF",
        "S1_low_rate_current_KGF",
        "S2_current_rate_public_KGF_anchor",
        "S3_low_rate_public_KGF_anchor",
        "S4_solve_rate_current_KGF",
        "S5_solve_rate_public_KGF_anchor",
        "S6_solve_KGF_current_rate",
        "S7_solve_KGF_low_rate",
    }
    driver_bases = {"current_C5m_c_coke_demand_driver", "C5k_no_buffer_BF_hot_metal_driver"}
    grouped = {}
    for row in rows:
        grouped.setdefault((row["configuration"], int(row["horizon_hours"]), row["driver_basis"]), set()).add(row["scenario_id"])
        assert row["driver_basis"] in driver_bases
        assert _num(row["BF_coke_demand_site_t_y"]) == pytest.approx(
            _num(row["BF_driver_used_site_t_y"]) * _num(row["BF_coke_rate_t_per_t_HM"]),
            abs=5.0,
        )
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(
            _num(row["KGF_output_site_t_y"]) - _num(row["BF_coke_demand_site_t_y"]),
            abs=1e-6,
        )
        assert row["baseline_changed"] == "false"
        assert row["BF_coke_rate_range_status"] in {
            "within_supported_range",
            "below_supported_range",
            "above_supported_range",
            "no_governed_range",
        }
    assert grouped
    for seen in grouped.values():
        assert seen == scenario_ids


def test_c5m_d_c5k_driver_low_rate_public_anchor_closes_gap(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_bounded_reconciliation_scenarios.csv")
    matches = [
        row for row in rows
        if row["driver_basis"] == "C5k_no_buffer_BF_hot_metal_driver"
        and row["scenario_id"] == "S3_low_rate_public_KGF_anchor"
    ]
    assert len(matches) == 4
    for row in matches:
        assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(BF_COKE_RATE_LOW, abs=1e-12)
        assert row["gap_closed"] == "true"
        assert row["within_BF_coke_rate_range"] == "true"
        assert row["within_near_public_KGF_anchor"] == "true"
        assert row["required_KGF_output_exceeds_public_anchor"] == "false"
        assert row["source_support_status"] == "evidence_bounded_scenario_candidate"


def test_c5m_d_solve_scenarios_check_ranges_and_anchors(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_bounded_reconciliation_scenarios.csv")
    for row in rows:
        if row["scenario_id"] == "S4_solve_rate_current_KGF":
            assert row["gap_closed"] == "true"
            assert _num(row["BF_coke_rate_t_per_t_HM"]) == pytest.approx(
                _num(row["KGF_output_site_t_y"]) / _num(row["BF_driver_used_site_t_y"]),
                abs=1e-6,
            )
        if row["scenario_id"] == "S6_solve_KGF_current_rate":
            assert row["gap_closed"] == "true"
            assert _num(row["KGF_output_site_t_y"]) == pytest.approx(
                _num(row["BF_driver_used_site_t_y"]) * BF_COKE_RATE_T_PER_T_HM,
                abs=1e-6,
            )
        if row["scenario_id"] == "S5_solve_rate_public_KGF_anchor" and row["driver_basis"] == "C5k_no_buffer_BF_hot_metal_driver":
            assert row["within_BF_coke_rate_range"] == "true"
            assert row["required_KGF_output_exceeds_public_anchor"] == "false"


def test_c5m_d_kpi_propagation_for_changed_kgf_output(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_kpi_propagation.csv")
    assert rows
    for row in rows:
        assert abs(_num(row["delta_KGF_coke_output_t_y"])) > 1.0
        assert row["baseline_changed"] == "false"
        assert "delta_dry_coal_input_t_y" in row
        assert "delta_KGF_electricity_MWh_y" in row
        assert "delta_KGF_steam_proxy_MWh_y" in row
        assert "delta_COG_generation_MWh_LHV_y" in row
        assert "delta_KGF_underfiring_MWh_LHV_y" in row
        assert "delta_net_COG_surplus_MWh_LHV_y" in row
        assert "delta_KGF_CO2_t_y" in row
        if row["scenario_id"] in {"S2_current_rate_public_KGF_anchor", "S3_low_rate_public_KGF_anchor"}:
            assert row["merely_moves_current_C5_output_back_to_public_anchor"] == "true"


def test_c5m_d_efficiency_intensity_what_if_table(c5m_d_outputs: Path):
    rows = _read_csv(c5m_d_outputs / "s4_4c5m_d_efficiency_intensity_what_if.csv")
    assert rows
    assert {row["metric"] for row in rows}.issuperset(
        {
            "coal_input_t_per_t_coke",
            "COG_yield_Nm3_per_t_coke",
            "underfiring_GJ_per_t_coke",
            "electricity_MWh_per_t_coke",
            "steam_GJ_per_t_coke",
            "steam_mass_t_per_t_coke",
            "direct_CO2_t_per_t_coke",
        }
    )
    assert any(row["range_status"] != "within_supported_range" for row in rows)
    for row in rows:
        assert _num(row["KGF_output_scale_factor"]) > 1.0
        assert _num(row["required_intensity_if_total_KPI_held_constant"]) == pytest.approx(
            _num(row["active_intensity"]) / _num(row["KGF_output_scale_factor"]),
            abs=5e-4,
        )
        assert row["baseline_changed"] == "false"


def test_c5m_d_recommendation_and_red_flags(c5m_d_outputs: Path):
    recommendation = _read_csv(c5m_d_outputs / "s4_4c5m_d_recommendation.csv")[0]
    assert recommendation["driver_mismatch_present"] == "true"
    assert recommendation["bounded_C5k_driver_low_rate_public_anchor_closure_available"] == "true"
    assert recommendation["external_unmodelled_coke_still_necessary_after_bounded_audit"] == "false"
    assert recommendation["baseline_changed"] == "false"
    assert "repair/report-align BF coke demand" in recommendation["recommended_next_action"]

    redflags = _read_csv(c5m_d_outputs / "s4_4c5m_d_red_flags.csv")
    expected = {
        "redflag_baseline_changed",
        "redflag_bf_coke_demand_driver_mismatch",
        "redflag_kgf_current_output_below_public_anchor",
        "redflag_required_bf_coke_rate_below_supported_range",
        "redflag_required_kgf_output_exceeds_public_anchor",
        "redflag_efficiency_required_outside_supported_range",
        "redflag_unexplained_coke_gap_still_hidden",
        "redflag_WAG_invariant_failed",
        "redflag_CO2_guard_failed",
    }
    for row in redflags:
        assert expected.issubset(row.keys())
        assert row["redflag_baseline_changed"] == "false"
        assert row["redflag_bf_coke_demand_driver_mismatch"] == "true"
        assert row["redflag_kgf_current_output_below_public_anchor"] == "true"
        assert row["redflag_unexplained_coke_gap_still_hidden"] == "false"
        assert row["redflag_WAG_invariant_failed"] == "false"
        assert row["redflag_CO2_guard_failed"] == "false"
        assert int(row["baseline_hard_redflag_count"]) == 0
