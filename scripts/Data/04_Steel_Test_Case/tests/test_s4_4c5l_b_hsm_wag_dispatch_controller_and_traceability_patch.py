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
from steel.s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch import (  # noqa: E402
    C5L_B_DIR,
    CONTROLLER_IMPLEMENTATION_MODE,
    HSM_CO2_STATUS,
    HSM_REHEAT_CONTROLLER_MODE,
    WAG_TOL_MWH,
    run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5l_b_outputs() -> Path:
    run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch()
    return C5L_B_DIR


def test_c5l_b_required_outputs_and_stage_gate(c5l_b_outputs: Path):
    required = [
        "s4_4c5l_b_stage_gate.json",
        "s4_4c5l_b_run_registry.csv",
        "s4_4c5l_b_24h_summary.csv",
        "s4_4c5l_b_168h_summary.csv",
        "s4_4c5l_b_hsm_reheat_controller_input_rows.csv",
        "s4_4c5l_b_hsm_reheat_controller_dashboard.csv",
        "s4_4c5l_b_hsm_reheat_controller_carrier_trace.csv",
        "s4_4c5l_b_wag_generation_consumption_by_plant.csv",
        "s4_4c5l_b_wag_aggregate_invariant.csv",
        "s4_4c5l_b_lhv_consistency_checks.csv",
        "s4_4c5l_b_hsm_co2_accounting_dashboard.csv",
        "s4_4c5l_b_final_product_and_anchor_dashboard.csv",
        "s4_4c5l_b_delta_vs_c5l_a_dashboard.csv",
        "s4_4c5l_b_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5l_b_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5l_b_outputs / "s4_4c5l_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_hsm_wag_controller_traceability_patch"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["HSM_REHEAT_CONTROLLER_MODE"] == HSM_REHEAT_CONTROLLER_MODE
    assert gate["controller_implementation_mode"] == CONTROLLER_IMPLEMENTATION_MODE
    assert gate["lp_controller_used"] is False
    assert gate["max_HSM_unserved_reheat_site_MWh_y"] == pytest.approx(0.0)
    assert gate["max_abs_controller_balance_error_MWh_y"] <= WAG_TOL_MWH
    assert gate["max_abs_C5l_a_delta_site_MWh_y"] <= WAG_TOL_MWH
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["lhv_consistency_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["anchor_constraints_used_count"] == 0
    assert gate["c5k_targets_and_route_split_changed"] is False
    assert gate["c5l_a_downstream_routing_changed"] is False
    assert gate["slab_age_bucket_buffer_added"] is False
    assert gate["sinter_implemented"] is False
    assert gate["direct_WAG_market_valuation_added"] is False
    assert gate["WAG_export_revenue_added"] is False
    assert gate["product_revenue_added"] is False


def test_c5l_b_controller_mode_rows_are_governed(c5l_b_outputs: Path):
    rows = _read_csv(c5l_b_outputs / "s4_4c5l_b_hsm_reheat_controller_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    assert by_id["HSM_REHEAT_CONTROLLER_MODE"]["base_value"] == HSM_REHEAT_CONTROLLER_MODE
    assert by_id["HSM_REHEAT_CONTROLLER_IMPLEMENTATION_MODE"]["base_value"] == CONTROLLER_IMPLEMENTATION_MODE
    for parameter_id in ["HSM_REHEAT_CONTROLLER_MODE", "HSM_REHEAT_CONTROLLER_IMPLEMENTATION_MODE"]:
        row = by_id[parameter_id]
        assert row["input_status"] == "development_policy_target"
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"


def test_c5l_b_hsm_reheat_balance_closes_and_unserved_is_zero(c5l_b_outputs: Path):
    rows = _read_csv(c5l_b_outputs / "s4_4c5l_b_hsm_reheat_controller_dashboard.csv")
    assert rows
    for row in rows:
        assert row["hsm_reheat_controller_mode"] == HSM_REHEAT_CONTROLLER_MODE
        assert row["controller_implementation_mode"] == CONTROLLER_IMPLEMENTATION_MODE
        demand = _num(row["hsm_reheat_demand_site_MWh_y"])
        supplied = (
            _num(row["BFG_to_HSM_reheat_site_MWh_y"])
            + _num(row["COG_to_HSM_reheat_site_MWh_y"])
            + _num(row["BOFG_to_HSM_reheat_site_MWh_y"])
            + _num(row["NG_to_HSM_reheat_site_MWh_y"])
            + _num(row["HSM_unserved_reheat_site_MWh_y"])
        )
        assert supplied == pytest.approx(demand, abs=WAG_TOL_MWH)
        assert _num(row["HSM_unserved_reheat_site_MWh_y"]) == pytest.approx(0.0)
        assert _num(row["controller_balance_error_site_MWh_y"]) == pytest.approx(0.0, abs=WAG_TOL_MWH)
        assert row["status_detail"] == "pass"


def test_c5l_b_wag_allocation_is_carrier_separate_and_bounded(c5l_b_outputs: Path):
    trace = _read_csv(c5l_b_outputs / "s4_4c5l_b_hsm_reheat_controller_carrier_trace.csv")
    carrier_rows = [row for row in trace if row["carrier"] in {"BFG", "COG", "BOFG"}]
    assert {row["carrier"] for row in carrier_rows} == {"BFG", "COG", "BOFG"}
    for row in carrier_rows:
        used = _num(row["allocated_to_HSM_reheat_raw_MWh_y"])
        available = _num(row["available_after_KGF_BF_priority_raw_MWh_y"])
        residual = _num(row["residual_after_HSM_raw_MWh_y"])
        assert used <= available + WAG_TOL_MWH
        assert residual >= -WAG_TOL_MWH
        assert row["red_flags"] == ""

    aggregate = _read_csv(c5l_b_outputs / "s4_4c5l_b_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)


def test_c5l_b_lhv_co2_and_market_guards_pass(c5l_b_outputs: Path):
    lhv = _read_csv(c5l_b_outputs / "s4_4c5l_b_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)

    co2 = _read_csv(c5l_b_outputs / "s4_4c5l_b_hsm_co2_accounting_dashboard.csv")
    hsm = [row for row in co2 if row["emission_bucket"] == "HSM_reheat_CO2"]
    assert hsm
    assert all(row["derivation_status"] == HSM_CO2_STATUS for row in hsm)
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)

    for path in c5l_b_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "direct wag market valuation" not in text
        assert "export revenue" not in text
        assert "product revenue" not in text


def test_c5l_b_preserves_c5k_targets_and_c5l_a_routing(c5l_b_outputs: Path):
    summary = _read_csv(c5l_b_outputs / "s4_4c5l_b_24h_summary.csv")
    by_config = {row["configuration"]: row for row in summary}
    assert _num(by_config[C0]["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
    assert _num(by_config[C0]["c5k_bof_liquid_steel_site_t_y"]) == pytest.approx(6_750_000.0)
    assert _num(by_config[C0]["c5k_eaf_liquid_steel_site_t_y"]) == pytest.approx(0.0)
    assert _num(by_config[C1]["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
    assert _num(by_config[C1]["c5k_bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
    assert _num(by_config[C1]["c5k_eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)
    assert all(_num(row["C5l_a_material_gap_site_t_y"]) == pytest.approx(0.0) for row in summary)


def test_c5l_b_reports_final_product_proxy_and_anchor_gaps(c5l_b_outputs: Path):
    rows = _read_csv(c5l_b_outputs / "s4_4c5l_b_final_product_and_anchor_dashboard.csv")
    assert rows
    for row in rows:
        assert row["anchor_constraint_used"] == "false"
        proxy = _num(row["active_HSM_output_site_t_y"]) + _num(row["active_DSP_output_site_t_y"])
        assert _num(row["active_final_product_proxy_site_t_y"]) == pytest.approx(proxy)
        assert row["denominator_warning"] == "final_product_proxy_contains_HSM_HRC_plus_DSP_output_not_liquid_steel"
        assert row["superseded_policy_warning"] == "C5l_a downstream routing supersedes C5l scaled-public-output-driver policy"

    c1 = next(row for row in rows if row["configuration"] == C1 and row["horizon_hours"] == "24")
    assert _num(c1["active_final_product_proxy_site_t_y"]) == pytest.approx(1_350_000.0 + (5_400_000.0 + 600_000.0 * 6.75 / 6.8) / 1.10)


def test_c5l_b_no_slab_age_buffer_or_sinter_scope(c5l_b_outputs: Path):
    gate = json.loads((c5l_b_outputs / "s4_4c5l_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["slab_age_bucket_buffer_added"] is False
    assert gate["sinter_implemented"] is False
