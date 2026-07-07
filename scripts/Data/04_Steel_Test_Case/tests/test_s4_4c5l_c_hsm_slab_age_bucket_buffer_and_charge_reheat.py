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
from steel.s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat import (  # noqa: E402
    C5L_C_DIR,
    HSM_CO2_STATUS,
    MATERIAL_ROUNDING_TOL_T_Y,
    REHEAT_CCR_GJ_PER_T_SLAB,
    REHEAT_DHCR_GJ_PER_T_SLAB,
    REHEAT_HCR_GJ_PER_T_SLAB,
    SLAB_BUFFER_MODE,
    SLAB_STORE_CAPACITY_TOTAL_T,
    SOURCE_CARD,
    WAG_TOL_MWH,
    run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5l_c_outputs() -> Path:
    run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat()
    return C5L_C_DIR


def test_c5l_c_source_card_outputs_and_stage_gate(c5l_c_outputs: Path):
    assert SOURCE_CARD.exists()
    text = SOURCE_CARD.read_text(encoding="utf-8").lower()
    assert "candidate source-card memo" in text
    assert "thesis usability: false" in text
    assert "not exact tata truth" in text
    assert "hsm_yield = 1.0" in text

    required = [
        "s4_4c5l_c_stage_gate.json",
        "s4_4c5l_c_run_registry.csv",
        "s4_4c5l_c_24h_summary.csv",
        "s4_4c5l_c_168h_summary.csv",
        "s4_4c5l_c_slab_buffer_input_rows.csv",
        "s4_4c5l_c_slab_age_bucket_hourly.csv",
        "s4_4c5l_c_slab_buffer_dashboard.csv",
        "s4_4c5l_c_hsm_charge_reheat_dashboard.csv",
        "s4_4c5l_c_hsm_reheat_controller_dashboard.csv",
        "s4_4c5l_c_hsm_reheat_controller_carrier_trace.csv",
        "s4_4c5l_c_wag_generation_consumption_by_plant.csv",
        "s4_4c5l_c_wag_aggregate_invariant.csv",
        "s4_4c5l_c_lhv_consistency_checks.csv",
        "s4_4c5l_c_hsm_co2_accounting_dashboard.csv",
        "s4_4c5l_c_final_product_and_anchor_dashboard.csv",
        "s4_4c5l_c_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5l_c_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5l_c_outputs / "s4_4c5l_c_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_hsm_slab_age_bucket_buffer_and_charge_reheat"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["SLAB_BUFFER_MODE"] == SLAB_BUFFER_MODE
    assert gate["SLAB_STORE_CAPACITY_TOTAL_T"] == pytest.approx(25_000.0)
    assert gate["INITIAL_COLD_SLAB_INVENTORY_T"] == pytest.approx(12_500.0)
    assert gate["TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL"] is True
    assert gate["TERMINAL_HOT_SLAB_INVENTORY_ZERO"] is True
    assert gate["HSM_yield_1p0_active_base"] is False
    assert gate["max_capacity_hit_count"] == pytest.approx(0.0)
    assert gate["max_abs_downstream_material_gap_t_y"] <= MATERIAL_ROUNDING_TOL_T_Y
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["lhv_consistency_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["HSM_CO2_status"] == HSM_CO2_STATUS
    assert gate["sinter_implemented"] is False


def test_c5l_c_buffer_input_rows_are_governed(c5l_c_outputs: Path):
    rows = _read_csv(c5l_c_outputs / "s4_4c5l_c_slab_buffer_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    assert by_id["SLAB_BUFFER_MODE"]["base_value"] == SLAB_BUFFER_MODE
    assert _num(by_id["SLAB_STORE_CAPACITY_TOTAL_T"]["base_value"]) == pytest.approx(25_000.0)
    assert _num(by_id["INITIAL_COLD_SLAB_INVENTORY_T"]["base_value"]) == pytest.approx(12_500.0)
    assert _num(by_id["REHEAT_DHCR_GJ_PER_T_SLAB"]["base_value"]) == pytest.approx(0.335)
    assert _num(by_id["REHEAT_HCR_GJ_PER_T_SLAB"]["base_value"]) == pytest.approx(0.878)
    assert _num(by_id["REHEAT_CCR_GJ_PER_T_SLAB"]["base_value"]) == pytest.approx(1.338)
    assert _num(by_id["HSM_SLAB_INPUT_T_PER_T_HRC"]["base_value"]) == pytest.approx(1.10)
    assert _num(by_id["HSM_YIELD_1P0_ACTIVE_BASE"]["base_value"]) == pytest.approx(0.0)
    for parameter_id in [
        "SLAB_BUFFER_MODE",
        "SLAB_STORE_CAPACITY_TOTAL_T",
        "INITIAL_COLD_SLAB_INVENTORY_T",
        "REHEAT_DHCR_GJ_PER_T_SLAB",
        "REHEAT_HCR_GJ_PER_T_SLAB",
        "REHEAT_CCR_GJ_PER_T_SLAB",
    ]:
        row = by_id[parameter_id]
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"


def test_c5l_c_hourly_age_buckets_are_nonnegative_finite_and_not_double_used(c5l_c_outputs: Path):
    hourly = _read_csv(c5l_c_outputs / "s4_4c5l_c_slab_age_bucket_hourly.csv")
    assert len(hourly) == 2 * (24 + 168)
    for row in hourly:
        assert row["slab_buffer_mode"] == SLAB_BUFFER_MODE
        total_start = _num(row["total_slab_inventory_start_t"])
        total_end = _num(row["total_slab_inventory_end_t"])
        assert total_start <= SLAB_STORE_CAPACITY_TOTAL_T
        assert total_end <= SLAB_STORE_CAPACITY_TOTAL_T
        assert row["capacity_exceeded"] == "false"
        assert row["status"] == "pass"
        assert abs(_num(row["inventory_balance_error_t"])) <= 1e-6
        for idx in range(7):
            start = _num(row[f"slab_age{idx}_inventory_start_t"])
            end = _num(row[f"slab_age{idx}_inventory_end_t"])
            used = _num(row[f"hsm_from_age{idx}_t"])
            assert start >= -1e-9
            assert end >= -1e-9
            assert used <= start + 1e-9
        cold_start = _num(row["slab_cold_inventory_start_t"])
        cold_end = _num(row["slab_cold_inventory_end_t"])
        cold_used = _num(row["hsm_from_cold_t"])
        imported = _num(row["external_slab_import_to_cold_t"])
        assert cold_start >= -1e-9
        assert cold_end >= -1e-9
        assert cold_used <= cold_start + imported + 1e-9


def test_c5l_c_terminal_policy_and_imported_slab_cold_route(c5l_c_outputs: Path):
    report = _read_csv(c5l_c_outputs / "s4_4c5l_c_slab_buffer_dashboard.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for row in report:
        assert row["terminal_total_policy_status"] == "pass"
        assert row["terminal_hot_policy_status"] == "pass"
        assert _num(row["terminal_total_slab_inventory_t"]) == pytest.approx(12_500.0)
        assert _num(row["terminal_hot_slab_inventory_t"]) == pytest.approx(0.0)
        assert _num(row["capacity_hit_count"]) == pytest.approx(0.0)
        assert row["import_convention"] == "imported_slab_enters_cold_inventory_and_is_same_hour_available"
    assert _num(by_key[(C0, "24")]["imported_cold_slab_site_t_y"]) == pytest.approx(0.0)
    assert _num(by_key[(C1, "24")]["imported_cold_slab_site_t_y"]) == pytest.approx(600_000.0 * 6.75 / 6.8, abs=0.01)


def test_c5l_c_preserves_c5k_and_c5l_a_routing_quantities(c5l_c_outputs: Path):
    report = _read_csv(c5l_c_outputs / "s4_4c5l_c_slab_buffer_dashboard.csv")
    for row in report:
        assert row["downstream_routing_mode"] == "liquid_steel_80_20_to_DSP_HSM_with_imported_slab"
        assert _num(row["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(row["dsp_output_site_t_y"]) == pytest.approx(1_350_000.0)
        assert _num(row["hsm_slab_input_t_per_t_HRC"]) == pytest.approx(1.10)
        assert row["hsm_yield_1p0_active_base"] == "false"
        assert _num(row["hsm_output_site_t_y"]) == pytest.approx(_num(row["hsm_slab_input_site_t_y"]) / 1.10, abs=0.01)
        assert abs(_num(row["indicative_downstream_material_gap_site_t_y"])) <= MATERIAL_ROUNDING_TOL_T_Y
    c0 = next(row for row in report if row["configuration"] == C0 and row["horizon_hours"] == "24")
    c1 = next(row for row in report if row["configuration"] == C1 and row["horizon_hours"] == "24")
    assert _num(c0["hsm_from_age0_site_t_y"]) == pytest.approx(5_400_000.0, abs=0.01)
    assert _num(c1["hsm_from_age0_site_t_y"]) == pytest.approx(5_400_000.0, abs=0.01)


def test_c5l_c_charge_specific_reheat_and_units(c5l_c_outputs: Path):
    report = _read_csv(c5l_c_outputs / "s4_4c5l_c_hsm_charge_reheat_dashboard.csv")
    for row in report:
        expected_gj = (
            _num(row["hsm_from_age0_site_t_y"]) * REHEAT_DHCR_GJ_PER_T_SLAB
            + _num(row["hsm_from_age1_to_age6_site_t_y"]) * REHEAT_HCR_GJ_PER_T_SLAB
            + _num(row["hsm_from_cold_site_t_y"]) * REHEAT_CCR_GJ_PER_T_SLAB
        )
        assert _num(row["hsm_reheat_heat_site_GJ_y"]) == pytest.approx(expected_gj, abs=0.01)
        assert _num(row["hsm_reheat_heat_site_MWh_th_y"]) == pytest.approx(expected_gj / 3.6, abs=0.01)
        assert "hsm_reheat_heat_site_TWh_th_y" in row
        assert "hsm_rolling_electricity_site_GWh_e_y" in row
        assert _num(row["hsm_rolling_electricity_site_GWh_e_y"]) == pytest.approx(_num(row["hsm_output_site_t_y"]) * 0.070 / 1000.0, abs=0.01)
        assert _num(row["reheat_delta_vs_C5l_b_average_site_MWh_y"]) < 0.0


def test_c5l_c_wag_controller_uses_charge_specific_reheat(c5l_c_outputs: Path):
    report = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(c5l_c_outputs / "s4_4c5l_c_slab_buffer_dashboard.csv")
    }
    controller = _read_csv(c5l_c_outputs / "s4_4c5l_c_hsm_reheat_controller_dashboard.csv")
    for row in controller:
        key = (row["configuration"], row["horizon_hours"])
        assert row["status"] == "pass"
        assert _num(row["hsm_reheat_demand_site_MWh_y"]) == pytest.approx(_num(report[key]["hsm_reheat_heat_site_MWh_th_y"]), abs=WAG_TOL_MWH)
        supplied = (
            _num(row["BFG_to_HSM_reheat_site_MWh_y"])
            + _num(row["COG_to_HSM_reheat_site_MWh_y"])
            + _num(row["BOFG_to_HSM_reheat_site_MWh_y"])
            + _num(row["NG_to_HSM_reheat_site_MWh_y"])
            + _num(row["HSM_unserved_reheat_site_MWh_y"])
        )
        assert supplied == pytest.approx(_num(row["hsm_reheat_demand_site_MWh_y"]), abs=WAG_TOL_MWH)
        assert _num(row["HSM_unserved_reheat_site_MWh_y"]) == pytest.approx(0.0)
        assert _num(row["controller_balance_error_site_MWh_y"]) == pytest.approx(0.0, abs=WAG_TOL_MWH)


def test_c5l_c_wag_lhv_and_co2_guards_pass(c5l_c_outputs: Path):
    aggregate = _read_csv(c5l_c_outputs / "s4_4c5l_c_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)

    lhv = _read_csv(c5l_c_outputs / "s4_4c5l_c_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)

    co2 = _read_csv(c5l_c_outputs / "s4_4c5l_c_hsm_co2_accounting_dashboard.csv")
    hsm = [row for row in co2 if row["emission_bucket"] == "HSM_reheat_CO2"]
    assert hsm
    assert all(row["derivation_status"] == HSM_CO2_STATUS for row in hsm)
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)


def test_c5l_c_forbidden_scope_guards(c5l_c_outputs: Path):
    gate = json.loads((c5l_c_outputs / "s4_4c5l_c_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["sinter_implemented"] is False
    assert gate["direct_WAG_market_valuation_added"] is False
    assert gate["WAG_export_revenue_added"] is False
    assert gate["product_revenue_added"] is False
    for path in c5l_c_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "direct wag market valuation" not in text
        assert "export revenue" not in text
        assert "product revenue" not in text
