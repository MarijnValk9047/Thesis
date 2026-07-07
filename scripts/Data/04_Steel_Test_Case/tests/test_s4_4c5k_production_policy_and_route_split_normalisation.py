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
from steel.s4_4c5k_production_policy_and_route_split_normalisation import (  # noqa: E402
    C5K_DIR,
    WAG_TOL_MWH,
    run_s4_4c5k_production_policy_and_route_split_normalisation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5k_outputs() -> Path:
    run_s4_4c5k_production_policy_and_route_split_normalisation()
    return C5K_DIR


def test_c5k_required_outputs_exist_parse_and_stage_gate(c5k_outputs: Path):
    required = [
        "s4_4c5k_stage_gate.json",
        "s4_4c5k_run_registry.csv",
        "s4_4c5k_production_policy_input_rows.csv",
        "s4_4c5k_bof_osf_coefficient_rows_inherited_from_c5j.csv",
        "s4_4c5k_24h_summary.csv",
        "s4_4c5k_168h_summary.csv",
        "s4_4c5k_route_split_normalisation_report.csv",
        "s4_4c5k_bf_bof_hot_metal_coupling_dashboard.csv",
        "s4_4c5k_validation_anchor_gap_dashboard.csv",
        "s4_4c5k_wag_generation_consumption_by_plant.csv",
        "s4_4c5k_wag_aggregate_invariant.csv",
        "s4_4c5k_bof_co2_accounting_dashboard.csv",
        "s4_4c5k_lhv_consistency_checks.csv",
        "s4_4c5k_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5k_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5k_outputs / "s4_4c5k_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_production_policy_and_route_split_normalisation"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["active_C0_total_liquid_steel_target_t_y"] == pytest.approx(6_750_000.0)
    assert gate["active_C1_total_liquid_steel_target_t_y"] == pytest.approx(6_750_000.0)
    assert gate["active_C1_retained_BOF_liquid_steel_target_t_y"] == pytest.approx(3_400_000.0)
    assert gate["active_C1_EAF_liquid_steel_target_t_y"] == pytest.approx(3_350_000.0)
    assert gate["BF_TO_BOF_HOT_METAL_BUFFER_ACTIVE"] is False
    assert gate["BF_HM_EQUALS_BOF_HM_INPUT_NO_BUFFER"] is True
    assert gate["remaining_BF_hot_metal_surplus_max_abs_t_y"] == pytest.approx(0.0)
    assert gate["anchor_constraints_used_count"] == 0
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["HSM_WBW_implemented"] is False


def test_c5k_policy_rows_are_governed_development_targets(c5k_outputs: Path):
    rows = _read_csv(c5k_outputs / "s4_4c5k_production_policy_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "C0_TOTAL_LIQUID_STEEL_TARGET_MT_Y": 6.75,
        "C0_BOF_LIQUID_STEEL_TARGET_MT_Y": 6.75,
        "C0_EAF_LIQUID_STEEL_TARGET_MT_Y": 0.0,
        "C1_TOTAL_LIQUID_STEEL_TARGET_MT_Y": 6.75,
        "C1_RETAINED_BOF_LIQUID_STEEL_TARGET_MT_Y": 3.40,
        "C1_EAF_LIQUID_STEEL_TARGET_MT_Y": 3.35,
        "BF_TO_BOF_HOT_METAL_BUFFER_ACTIVE": 0.0,
        "BF_HM_EQUALS_BOF_HM_INPUT_NO_BUFFER": 1.0,
    }
    for parameter_id, value in required.items():
        row = by_id[parameter_id]
        assert _num(row["base_value"]) == pytest.approx(value)
        assert row["input_status"] == "development_policy_target"
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["evidence_strength"] == "modelling_policy_with_public_context"
        assert row["constraint_used"] == "false"
        assert row["active_target"] == "true"

    context_rows = [row for row in rows if row["input_status"] == "validation_context_anchor"]
    assert context_rows
    assert all(row["constraint_used"] == "false" for row in context_rows)
    assert all(row["active_target"] == "false" for row in context_rows)


def test_c5k_route_split_and_bof_derived_metrics(c5k_outputs: Path):
    report = _read_csv(c5k_outputs / "s4_4c5k_route_split_normalisation_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for horizon in ("24", "168"):
        c0 = by_key[(C0, horizon)]
        assert _num(c0["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c0["bof_liquid_steel_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c0["eaf_liquid_steel_site_t_y"]) == pytest.approx(0.0)
        assert _num(c0["bof_hot_metal_input_site_t_y"]) == pytest.approx(5_906_250.0)
        assert _num(c0["bof_scrap_input_site_t_y"]) == pytest.approx(1_404_000.0)

        c1 = by_key[(C1, horizon)]
        assert _num(c1["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c1["bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
        assert _num(c1["eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)
        assert _num(c1["route_split_sum_site_t_y"]) == pytest.approx(6_750_000.0)
        assert c1["route_split_sum_matches_target"] == "true"
        assert _num(c1["bof_hot_metal_input_site_t_y"]) == pytest.approx(2_801_600.0)
        assert _num(c1["bof_scrap_input_site_t_y"]) == pytest.approx(999_600.0)
        assert _num(c1["bof_oxygen_input_site_Nm3_y"]) == pytest.approx(187_000_000.0)
        assert _num(c1["bof_electricity_site_MWh_y"]) == pytest.approx(91_120.0)
        assert _num(c1["bof_bofg_output_site_PJ_LHV_y"]) == pytest.approx(2.193, rel=1e-6)
        assert _num(c1["bof_direct_co2_site_t_y"]) == pytest.approx(280_500.0)


def test_c5k_bf_hot_metal_equals_bof_input_no_buffer(c5k_outputs: Path):
    coupling = _read_csv(c5k_outputs / "s4_4c5k_bf_bof_hot_metal_coupling_dashboard.csv")
    assert coupling
    for row in coupling:
        assert row["bf_to_bof_hot_metal_buffer_active"] == "false"
        assert row["bf_hm_equals_bof_hm_input_no_buffer"] == "true"
        assert row["coupling_mode"] == "annual_equality_no_buffer_diagnostic"
        assert _num(row["normalised_bf_hot_metal_output_site_t_y"]) == pytest.approx(_num(row["bof_hot_metal_input_site_t_y"]))
        assert _num(row["remaining_surplus_site_t_y"]) == pytest.approx(0.0)
        assert row["status"] == "pass"


def test_c5k_bof_coefficients_are_unchanged_from_c5j(c5k_outputs: Path):
    rows = {row["parameter_id"]: row for row in _read_csv(c5k_outputs / "s4_4c5k_bof_osf_coefficient_rows_inherited_from_c5j.csv")}
    assert _num(rows["BOF_HOT_METAL_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.875)
    assert _num(rows["BOF_SCRAP_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.208)
    assert _num(rows["BOF_HOT_METAL_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.824)
    assert _num(rows["BOF_SCRAP_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.294)
    assert _num(rows["BOF_BOFG_OUTPUT_NM3_PER_T_LS"]["base_value"]) == pytest.approx(75.0)
    assert _num(rows["BOF_DIRECT_CO2_T_PER_T_LS"]["base_value"]) == pytest.approx(0.0825)
    assert _num(rows["BOFG_LHV_MJ_PER_NM3"]["base_value"]) == pytest.approx(8.6)


def test_c5k_anchors_are_context_gaps_not_constraints(c5k_outputs: Path):
    anchors = _read_csv(c5k_outputs / "s4_4c5k_validation_anchor_gap_dashboard.csv")
    assert anchors
    assert all(row["constraint_used"] == "false" for row in anchors)
    assert all(row["anchor_status"] == "validation_context_only" for row in anchors)
    c0_72 = next(row for row in anchors if row["configuration"] == C0 and row["metric"] == "MER_reference_liquid_steel_context_t_y")
    c1_68 = next(row for row in anchors if row["configuration"] == C1 and row["metric"] == "MER_heracless_liquid_steel_context_t_y")
    assert _num(c0_72["model_site_quantity"]) == pytest.approx(6_750_000.0)
    assert _num(c0_72["anchor_quantity"]) == pytest.approx(7_200_000.0)
    assert _num(c1_68["model_site_quantity"]) == pytest.approx(6_750_000.0)
    assert _num(c1_68["anchor_quantity"]) == pytest.approx(6_800_000.0)


def test_c5k_wag_invariant_and_lhv_still_pass(c5k_outputs: Path):
    aggregate = _read_csv(c5k_outputs / "s4_4c5k_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)

    lhv = _read_csv(c5k_outputs / "s4_4c5k_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)


def test_c5k_co2_guard_and_non_scope_flags(c5k_outputs: Path):
    co2 = _read_csv(c5k_outputs / "s4_4c5k_bof_co2_accounting_dashboard.csv")
    assert co2
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)
    assert all(row["status"] == "pass" for row in co2)

    compact = _read_csv(c5k_outputs / "s4_4c5k_compact_table_for_chat.csv")
    assert compact
    assert all("HSM" not in row["plant"] for row in compact)
