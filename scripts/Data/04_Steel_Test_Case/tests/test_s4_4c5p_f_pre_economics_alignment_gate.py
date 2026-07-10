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
from steel.s4_4c5p_f_pre_economics_alignment_gate import (  # noqa: E402
    ANCHOR_POLICY_COLUMNS,
    BLOCKER_COLUMNS,
    C5P_F_DIR,
    DECISION_COLUMNS,
    DENOMINATOR_COLUMNS,
    DRP_OXYGEN_COLUMNS,
    GENERATOR_GAP_COLUMNS,
    LEVER_TRIAGE_COLUMNS,
    REDFLAG_COLUMNS,
    REPORT_PATH,
    SLAB_ROUTE_COLUMNS,
    run_s4_4c5p_f_pre_economics_alignment_gate,
)


REQUIRED_FILES = {
    "c5_pre_economics_alignment_decision_register.csv": DECISION_COLUMNS,
    "c5_downstream_denominator_alignment.csv": DENOMINATOR_COLUMNS,
    "c5_imported_slab_and_route_alignment.csv": SLAB_ROUTE_COLUMNS,
    "c5_c1_generator_wag_gap_decomposition.csv": GENERATOR_GAP_COLUMNS,
    "c5_drp_oxygen_basis_review.csv": DRP_OXYGEN_COLUMNS,
    "c5_anchor_acceptance_policy.csv": ANCHOR_POLICY_COLUMNS,
    "c5_pre_economics_blocker_list.csv": BLOCKER_COLUMNS,
    "c5_pre_economics_parameter_lever_triage.csv": LEVER_TRIAGE_COLUMNS,
    "c5_pre_economics_red_flags.csv": REDFLAG_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5p_f_outputs() -> Path:
    run_s4_4c5p_f_pre_economics_alignment_gate()
    return C5P_F_DIR


def test_c5p_f_outputs_parse_and_have_required_columns(c5p_f_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_f_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    for name in ["s4_4c5p_f_stage_gate.json", "s4_4c5p_f_summary.json"]:
        json.loads((c5p_f_outputs / name).read_text(encoding="utf-8"))
    assert _read_csv(c5p_f_outputs / "s4_4c5p_f_run_registry.csv")
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_f_outputs / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_pre_economics_alignment_gate"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["denominator_status"] == "unresolved_until_residual_loads_and_boundary_complete"
    assert gate["economics_readiness"] == "NO_GO"
    assert gate["DA_readiness"] == "NO_GO"
    assert gate["residual_electricity_ng_diagnostics_status"] == "GO"


def test_c5p_f_does_not_change_c5p_e_baseline_metrics(c5p_f_outputs: Path):
    gate = json.loads((c5p_f_outputs / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["C1_generator_fuel_gap_PJ_y"] == pytest.approx(4.763389, abs=1e-6)
    assert gate["C1_generator_BFG_gap_PJ_y"] == pytest.approx(4.740584, abs=1e-6)
    assert gate["electricity_accounting_status"] == "internal_offset_or_reporting_only_not_DA_market_revenue"
    assert gate["generator_electricity_value_mode"] == "offset_site_grid_import"
    assert gate["electricity_boundary_status"] == "incomplete_reporting_only_not_full_site_net_import"
    assert gate["ng_boundary_status"] == "incomplete_no_full_site_NG_claim"
    assert gate["co2_boundary_status"] == "component_diagnostic_only_not_ETS_ready"


def test_downstream_denominator_policy_is_unresolved_and_dual_reporting(c5p_f_outputs: Path):
    rows = _read_csv(c5p_f_outputs / "c5_downstream_denominator_alignment.csv")
    by_metric = {(row["configuration"], row["metric"]): row for row in rows}

    c0_target = by_metric[(C0, "active liquid steel target")]
    assert _num(c0_target["current_model_output"]) == pytest.approx(6750000.0)
    assert _num(c0_target["absolute_gap_to_active_scaled"]) == pytest.approx(0.0)
    assert _num(c0_target["absolute_gap_to_raw"]) == pytest.approx(-450000.0)

    c1_final = by_metric[(C1, "final-product proxy")]
    assert _num(c1_final["current_model_output"]) == pytest.approx(6800534.76175, abs=1e-6)
    assert c1_final["denominator_implication"] == "secondary diagnostic only"
    assert "do_not_freeze_denominator" in c1_final["recommended_policy"]

    decisions = {row["decision_id"]: row for row in _read_csv(c5p_f_outputs / "c5_pre_economics_alignment_decision_register.csv")}
    assert decisions["DEC_DENOMINATOR_POLICY"]["recommended_option"] == "C_dual_reporting_primary_active_target_secondary_final_product_proxy_diagnostic"
    assert decisions["DEC_DENOMINATOR_POLICY"]["must_fix_before_commit"] == "false"
    assert decisions["DEC_DENOMINATOR_POLICY"]["must_fix_before_economics"] == "true"


def test_imported_slab_and_route_policy_are_not_promoted(c5p_f_outputs: Path):
    rows = _read_csv(c5p_f_outputs / "c5_imported_slab_and_route_alignment.csv")
    by_route = {(row["configuration"], row["flow_or_route"]): row for row in rows}
    assert by_route[(C1, "imported_slab_anchor")]["raw_anchor"] == "600000"
    assert by_route[(C1, "imported_slab_anchor")]["route_policy_status"] == "validation_context_not_exogenous_store"
    assert by_route[("C0_C1", "final_product_proxy_primary_denominator")]["current_model_output"] == "secondary_diagnostic_only"
    assert by_route[("C0_C1", "C5l_d_HSM_WBW_hot_charge_case")]["current_model_output"] == "base_0_50"


def test_c1_generator_gap_is_decomposed_not_hidden_or_forced(c5p_f_outputs: Path):
    rows = _read_csv(c5p_f_outputs / "c5_c1_generator_wag_gap_decomposition.csv")
    by_carrier = {row["carrier"]: row for row in rows}
    assert _num(by_carrier["BFG"]["generator_gap"]) == pytest.approx(4.740584, abs=1e-6)
    assert _num(by_carrier["BOFG"]["generator_gap"]) == pytest.approx(0.022805, abs=1e-6)
    assert _num(by_carrier["COG"]["generator_gap"]) == pytest.approx(0.0, abs=1e-6)
    assert _num(by_carrier["NG"]["generator_gap"]) == pytest.approx(0.0, abs=1e-6)
    assert _num(by_carrier["total_preferred_anchor_gap_reported"]["generator_gap"]) == pytest.approx(4.763389, abs=1e-6)
    assert "do not create fuel" in by_carrier["BFG"]["recommended_action"]

    redflags = _read_csv(c5p_f_outputs / "c5_pre_economics_red_flags.csv")
    active_failures = [row for row in redflags if row["severity"] == "failure" and row["active"] == "true"]
    assert active_failures == []


def test_drp_oxygen_basis_review_preserves_current_base(c5p_f_outputs: Path):
    rows = _read_csv(c5p_f_outputs / "c5_drp_oxygen_basis_review.csv")
    by_id = {row["oxygen_basis_id"]: row for row in rows}
    active = by_id["active_project_basis"]
    vendor = by_id["vendor_crosscheck_basis"]
    midpoint = by_id["midpoint_sensitivity"]

    assert _num(active["equivalent_t_per_t_dri"]) == pytest.approx(0.135, abs=1e-9)
    assert _num(active["annual_o2_demand_kt_y"]) == pytest.approx(375.220566, abs=1e-6)
    assert active["recommended_base_status"] == "preserve_current_base_pending_source_review"
    assert _num(vendor["equivalent_nm3_per_t_dri"]) == pytest.approx(35.0, abs=1e-9)
    assert _num(vendor["equivalent_t_per_t_dri"]) == pytest.approx(0.050015, abs=1e-6)
    assert vendor["recommended_base_status"] == "not_base_without_source_card_review"
    assert midpoint["recommended_base_status"] == "sensitivity_only_not_base"


def test_anchor_acceptance_policy_blocks_constraint_misuse(c5p_f_outputs: Path):
    rows = _read_csv(c5p_f_outputs / "c5_anchor_acceptance_policy.csv")
    by_family = {row["anchor_family"]: row for row in rows}
    assert by_family["raw_MER_public_anchors"]["executable_constraint_allowed"] == "false"
    assert by_family["annual_not_hourly"]["executable_constraint_allowed"] == "false_as_hourly_schedule"
    assert by_family["annual_generator_and_utility_anchors"]["validation_gap_allowed"] == "true"
    assert "pass_within_tolerance" in by_family["acceptance_classes"]["acceptance_tolerance"]


def test_blockers_and_lever_triage_go_no_go_status(c5p_f_outputs: Path):
    blockers = {row["blocker_id"]: row for row in _read_csv(c5p_f_outputs / "c5_pre_economics_blocker_list.csv")}
    assert blockers["BLK_OUTPUT_POLICY_REVIEW"]["blocks_commit"] == "true"
    assert blockers["BLK_DENOMINATOR_UNRESOLVED"]["blocks_economics"] == "true"
    assert blockers["BLK_RESIDUAL_ENERGY_BOUNDARIES"]["blocks_economics"] == "true"

    levers = {row["lever_id"]: row for row in _read_csv(c5p_f_outputs / "c5_pre_economics_parameter_lever_triage.csv")}
    assert levers["LEV_DRP_OXYGEN_BASIS_REVIEW"]["classification"] == "must_review_before_economics"
    assert levers["LEV_C1_GENERATOR_ANCHOR_INTERPRETATION"]["classification"] == "must_review_before_economics"
    assert levers["LEV_FORBIDDEN_MARKET_FEATURES"]["classification"] == "not_recommended"
    assert levers["LEV_RESIDUAL_ELECTRICITY_BOUNDARY"]["recommended_status"] == "next_stage"
