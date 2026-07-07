from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import C0, C1, WAG_TOL_MWH  # noqa: E402
from steel.s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR  # noqa: E402
from steel.s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR  # noqa: E402
from steel.s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import C5L_A_DIR  # noqa: E402
from steel.s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat import (  # noqa: E402
    C5L_C_DIR,
    MATERIAL_ROUNDING_TOL_T_Y,
    REHEAT_CCR_GJ_PER_T_SLAB,
    REHEAT_DHCR_GJ_PER_T_SLAB,
    REHEAT_HCR_GJ_PER_T_SLAB,
    SLAB_STORE_CAPACITY_TOTAL_T,
)
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import (  # noqa: E402
    C5L_D_DIR,
    HSM_CO2_STATUS,
    HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
    HSM_HOT_CHARGE_CAP_MODE,
    HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES,
    HSM_HOT_CHARGE_SHARE_MAX_BASE,
    HSM_HOT_CHARGE_SHARE_MAX_HIGH,
    SCHNEIDER_SOURCE_ID,
    run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5l_d_outputs() -> Path:
    run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch()
    return C5L_D_DIR


def test_c5l_d_required_outputs_stage_gate_and_modes(c5l_d_outputs: Path):
    required = [
        "s4_4c5l_d_stage_gate.json",
        "s4_4c5l_d_run_registry.csv",
        "s4_4c5l_d_source_candidate_evidence.csv",
        "s4_4c5l_d_hot_charge_cap_input_rows.csv",
        "s4_4c5l_d_hot_charge_cap_report.csv",
        "s4_4c5l_d_hsm_reheat_controller_dashboard.csv",
        "s4_4c5l_d_hsm_reheat_controller_carrier_trace.csv",
        "s4_4c5l_d_wag_aggregate_invariant.csv",
        "s4_4c5l_d_lhv_consistency_checks.csv",
        "s4_4c5l_d_hsm_co2_accounting_dashboard.csv",
        "s4_4c5l_d_compact_table_for_chat.csv",
        "s4_4c5l_d_24h_summary.csv",
        "s4_4c5l_d_168h_summary.csv",
    ]
    for filename in required:
        path = c5l_d_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5l_d_outputs / "s4_4c5l_d_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["HSM_HOT_CHARGE_CAP_MODE"] == HSM_HOT_CHARGE_CAP_MODE
    assert gate["HSM_HOT_CHARGE_CAP_ACTIVE_CASE"] == HSM_HOT_CHARGE_CAP_ACTIVE_CASE
    assert gate["HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES"] == list(HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES)
    assert gate["HSM_HOT_CHARGE_SHARE_MAX_BASE"] == pytest.approx(0.50)
    assert gate["HSM_HOT_CHARGE_SHARE_MAX_HIGH"] == pytest.approx(0.80)
    assert gate["HSM_CO2_status"] == HSM_CO2_STATUS
    assert gate["sinter_implemented"] is False


def test_c5l_d_schneider_source_and_cap_rows_are_governed(c5l_d_outputs: Path):
    evidence = _read_csv(c5l_d_outputs / "s4_4c5l_d_source_candidate_evidence.csv")
    assert any(row["source_card_id"] == SCHNEIDER_SOURCE_ID and row["record_type"] == "source_card" for row in evidence)
    assert any(
        row["parameter_id"] == "HSM_HOT_CHARGE_SHARE_MAX_BASE"
        and _num(row["candidate_value"]) == pytest.approx(0.50)
        and row["thesis_usability"] == "false"
        and row["human_review_required"] == "true"
        and row["codex_may_decide"] == "false"
        and "locator pending" in row["locator_status"]
        for row in evidence
    )
    assert any(
        row["parameter_id"] == "HSM_HOT_CHARGE_SHARE_MAX_HIGH"
        and _num(row["candidate_value"]) == pytest.approx(0.80)
        and row["thesis_usability"] == "false"
        and row["human_review_required"] == "true"
        and row["codex_may_decide"] == "false"
        for row in evidence
    )

    inputs = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in inputs}
    assert by_id["HSM_HOT_CHARGE_CAP_MODE"]["base_value"] == HSM_HOT_CHARGE_CAP_MODE
    assert _num(by_id["HSM_HOT_CHARGE_SHARE_MAX_BASE"]["base_value"]) == pytest.approx(HSM_HOT_CHARGE_SHARE_MAX_BASE)
    assert _num(by_id["HSM_HOT_CHARGE_SHARE_MAX_HIGH"]["base_value"]) == pytest.approx(HSM_HOT_CHARGE_SHARE_MAX_HIGH)
    assert by_id["HSM_HOT_CHARGE_SHARE_MAX_BASE"]["input_status"] == "development_guardrail"
    assert by_id["HSM_HOT_CHARGE_SHARE_MAX_HIGH"]["input_status"] == "development_sensitivity"
    for parameter_id in [
        "HSM_HOT_CHARGE_CAP_MODE",
        "HSM_HOT_CHARGE_SHARE_MAX_BASE",
        "HSM_HOT_CHARGE_SHARE_MAX_HIGH",
    ]:
        row = by_id[parameter_id]
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"


def test_c5l_d_cap_cases_respect_hot_charge_caps_and_retain_references(c5l_d_outputs: Path):
    report = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"], row["cap_case"]): row for row in report}
    for config in (C0, C1):
        for horizon in ("24", "168"):
            uncapped = by_key[(config, horizon, "uncapped_c5l_c_reference")]
            base = by_key[(config, horizon, "base_0_50")]
            high = by_key[(config, horizon, "high_0_80")]
            assert uncapped["case_status"] == "reference_optimistic_uncapped_not_recommended_base"
            assert _num(base["combined_hot_charge_share"]) <= HSM_HOT_CHARGE_SHARE_MAX_BASE + 1e-9
            assert _num(high["combined_hot_charge_share"]) <= HSM_HOT_CHARGE_SHARE_MAX_HIGH + 1e-9
            assert _num(base["cold_charge_share"]) >= _num(high["cold_charge_share"]) >= _num(uncapped["cold_charge_share"])
            assert _num(base["hsm_reheat_heat_site_MWh_th_y"]) >= _num(uncapped["hsm_reheat_heat_site_MWh_th_y"])
            assert _num(uncapped["hsm_reheat_heat_site_MWh_th_y"]) <= _num(high["hsm_reheat_heat_site_MWh_th_y"]) <= _num(base["hsm_reheat_heat_site_MWh_th_y"])
            assert base["c5l_b_average_reheat_reference_retained"] == "true"


def test_c5l_d_charge_specific_reheat_units_and_rolling_electricity(c5l_d_outputs: Path):
    report = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    for row in report:
        expected_gj = (
            _num(row["hsm_from_age0_site_t_y"]) * REHEAT_DHCR_GJ_PER_T_SLAB
            + _num(row["hsm_from_age1_to_age6_site_t_y"]) * REHEAT_HCR_GJ_PER_T_SLAB
            + _num(row["hsm_from_cold_site_t_y"]) * REHEAT_CCR_GJ_PER_T_SLAB
        )
        assert _num(row["hsm_reheat_heat_site_GJ_y"]) == pytest.approx(expected_gj, abs=0.01)
        assert _num(row["hsm_reheat_heat_site_TWh_th_y"]) == pytest.approx(expected_gj / 3.6 / 1_000_000.0, abs=1e-6)
        assert "hsm_reheat_heat_site_TWh_th_y" in row
        assert "hsm_rolling_electricity_site_GWh_e_y" in row
        assert _num(row["hsm_rolling_electricity_site_GWh_e_y"]) == pytest.approx(_num(row["hsm_output_site_t_y"]) * 0.070 / 1000.0, abs=0.01)


def test_c5l_d_imported_slab_stays_cold_and_hsm_quantities_unchanged(c5l_d_outputs: Path):
    report = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    c5l_c = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_dashboard.csv")
    }
    c5l_a = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_report.csv")
    }
    for row in report:
        key = (row["configuration"], row["horizon_hours"])
        assert _num(row["imported_cold_slab_site_t_y"]) == pytest.approx(_num(c5l_c[key]["imported_cold_slab_site_t_y"]), abs=0.01)
        assert _num(row["hsm_slab_input_site_t_y"]) == pytest.approx(_num(c5l_c[key]["hsm_slab_input_site_t_y"]), abs=0.01)
        assert _num(row["hsm_output_site_t_y"]) == pytest.approx(_num(c5l_c[key]["hsm_output_site_t_y"]), abs=0.01)
        assert _num(row["hsm_slab_input_site_t_y"]) == pytest.approx(_num(c5l_a[key]["hsm_total_slab_input_site_t_y"]), abs=0.01)
        assert _num(row["hsm_output_site_t_y"]) == pytest.approx(_num(c5l_a[key]["hsm_output_site_t_y"]), abs=0.01)
        assert _num(row["hsm_slab_input_t_per_t_HRC"]) == pytest.approx(1.10)
        assert row["hsm_yield_1p0_active_base"] == "false"
        assert abs(_num(row["indicative_downstream_material_gap_site_t_y"])) <= MATERIAL_ROUNDING_TOL_T_Y


def test_c5l_d_preserves_c5k_targets_c1_split_and_c5j_coefficients(c5l_d_outputs: Path):
    report = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    for row in report:
        assert _num(row["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
    c5k = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")
    }
    assert _num(c5k[(C1, "24")]["bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
    assert _num(c5k[(C1, "24")]["eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)
    c5j_inputs = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in c5j_inputs}
    assert _num(by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.208)
    assert _num(by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.294)
    assert _num(by_id["BOF_BOFG_OUTPUT_NM3_PER_T_LS"]["base_value"]) == pytest.approx(75.0)


def test_c5l_d_buffer_capacity_terminal_policy_and_no_free_slab_battery(c5l_d_outputs: Path):
    report = _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    for row in report:
        assert row["terminal_total_policy_status"] == "pass"
        assert row["terminal_hot_policy_status"] == "pass"
        assert _num(row["capacity_hit_count"]) == pytest.approx(0.0)
        assert _num(row["hsm_from_cold_site_t_y"]) + _num(row["hsm_from_age0_site_t_y"]) + _num(row["hsm_from_age1_to_age6_site_t_y"]) == pytest.approx(_num(row["hsm_slab_input_site_t_y"]), abs=0.01)
        assert _num(row["hsm_from_cold_site_t_y"]) >= _num(row["imported_cold_slab_site_t_y"]) - 0.01
    assert SLAB_STORE_CAPACITY_TOTAL_T == pytest.approx(25_000.0)


def test_c5l_d_wag_controller_consumes_capped_reheat_and_guards_pass(c5l_d_outputs: Path):
    report = {
        (row["cap_case"], row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(c5l_d_outputs / "s4_4c5l_d_hot_charge_cap_report.csv")
    }
    controller = _read_csv(c5l_d_outputs / "s4_4c5l_d_hsm_reheat_controller_dashboard.csv")
    for row in controller:
        key = (row["cap_case"], row["configuration"], row["horizon_hours"])
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

    aggregate = _read_csv(c5l_d_outputs / "s4_4c5l_d_wag_aggregate_invariant.csv")
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)
    assert {row["cap_case"] for row in aggregate} == set(HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES)

    lhv = _read_csv(c5l_d_outputs / "s4_4c5l_d_lhv_consistency_checks.csv")
    assert all(row["status"] == "pass" for row in lhv)
    co2 = _read_csv(c5l_d_outputs / "s4_4c5l_d_hsm_co2_accounting_dashboard.csv")
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)
    assert all(row["derivation_status"] == HSM_CO2_STATUS for row in co2)


def test_c5l_d_forbidden_scope_and_stage_report_status(c5l_d_outputs: Path):
    gate = json.loads((c5l_d_outputs / "s4_4c5l_d_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["sinter_implemented"] is False
    assert gate["direct_WAG_market_valuation_added"] is False
    assert gate["WAG_export_revenue_added"] is False
    assert gate["product_revenue_added"] is False
    for path in c5l_d_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "direct wag market valuation" not in text
        assert "export revenue" not in text
        assert "product revenue" not in text
