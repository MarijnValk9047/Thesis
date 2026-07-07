from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import (  # noqa: E402
    C0,
    C1,
    KGF_UNDERFIRING_GJ_PER_T_COKE,
    WAG_TOL_MWH,
)
from steel.s4_4c5h_blast_furnace_controller_parameterisation import (  # noqa: E402
    BF_HOT_STOVE_DEMAND_MWH_PER_T_HM,
    BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM,
)
from steel.s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR  # noqa: E402
from steel.s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR  # noqa: E402
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import (  # noqa: E402
    C5L_D_DIR,
    HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
)
from steel.s4_4c5m_sinter_minimal_parameterisation import (  # noqa: E402
    C5M_DIR,
    SOURCE_CARD,
    SINTER_ALLOWED_GAS_CARRIERS,
    SINTER_CO2_ACCOUNTING_MODE,
    SINTER_COG_INPUT_GJ_PER_T_SINTER,
    SINTER_COG_INPUT_MWH_PER_T_SINTER,
    SINTER_DIRECT_CO2_T_PER_T_SINTER,
    SINTER_ELECTRICITY_MWH_PER_T_SINTER,
    SINTER_IRON_ORE_INPUT_T_PER_T_SINTER,
    SINTER_PER_T_HOT_METAL_C0,
    SINTER_PER_T_HOT_METAL_C1,
    SINTER_PROCESS_CLASS,
    SINTER_STEAM_INPUT_T_PER_T_SINTER,
    SINTER_STEAM_MODE,
    run_s4_4c5m_sinter_minimal_parameterisation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5m_outputs() -> Path:
    run_s4_4c5m_sinter_minimal_parameterisation()
    return C5M_DIR


def test_c5m_required_outputs_stage_gate_and_pattern(c5m_outputs: Path):
    required = [
        "s4_4c5m_stage_gate.json",
        "s4_4c5m_run_registry.csv",
        "s4_4c5m_source_candidate_evidence.csv",
        "s4_4c5m_sinter_development_input_rows.csv",
        "s4_4c5m_sinter_hourly_flows.csv",
        "s4_4c5m_sinter_report.csv",
        "s4_4c5m_sinter_material_route_dashboard.csv",
        "s4_4c5m_sinter_utility_dashboard.csv",
        "s4_4c5m_sinter_steam_proxy_dashboard.csv",
        "s4_4c5m_sinter_electricity_ledger.csv",
        "s4_4c5m_sinter_gas_wag_controller_dashboard.csv",
        "s4_4c5m_sinter_gas_wag_controller_trace.csv",
        "s4_4c5m_wag_generation_consumption_by_plant.csv",
        "s4_4c5m_wag_aggregate_invariant.csv",
        "s4_4c5m_lhv_consistency_checks.csv",
        "s4_4c5m_sinter_co2_accounting_dashboard.csv",
        "s4_4c5m_anchor_gap_dashboard.csv",
        "s4_4c5m_compact_table_for_chat.csv",
        "s4_4c5m_24h_summary.csv",
        "s4_4c5m_168h_summary.csv",
    ]
    for filename in required:
        path = c5m_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5m_outputs / "s4_4c5m_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_sinter_minimal_parameterisation"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert "development_input_rows" in gate["existing_pattern_audit_summary"]
    assert gate["inherited_hsm_heat_case"] == HSM_HOT_CHARGE_CAP_ACTIVE_CASE == "base_0_50"
    assert gate["sinter_allowed_gas_carriers"] == list(SINTER_ALLOWED_GAS_CARRIERS)
    assert gate["sinter_wag_production_flag"] is False
    assert gate["anchor_constraints_used"] == 0
    assert gate["C5l_d_base_0_50_inherited"] is True


def test_c5m_source_card_and_governed_development_rows(c5m_outputs: Path):
    assert SOURCE_CARD.exists()
    source_text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "Thesis usability: false" in source_text
    assert "Sinter is a WAG consumer only" in source_text
    assert "not Tata-validated" in source_text

    evidence = _read_csv(c5m_outputs / "s4_4c5m_source_candidate_evidence.csv")
    assert any(row["record_type"] == "source_card" and row["thesis_usability"] == "false" for row in evidence)

    inputs = _read_csv(c5m_outputs / "s4_4c5m_sinter_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in inputs}
    required = {
        "SINTER_BUS0": "iron_ore",
        "SINTER_PROCESS_CLASS": SINTER_PROCESS_CLASS,
        "SINTER_IRON_ORE_INPUT_T_PER_T_SINTER": SINTER_IRON_ORE_INPUT_T_PER_T_SINTER,
        "SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0": 1.23,
        "SINTER_ELECTRICITY_MWH_PER_T_SINTER": SINTER_ELECTRICITY_MWH_PER_T_SINTER,
        "SINTER_COG_INPUT_GJ_PER_T_SINTER": SINTER_COG_INPUT_GJ_PER_T_SINTER,
        "SINTER_COG_INPUT_MWH_PER_T_SINTER": SINTER_COG_INPUT_MWH_PER_T_SINTER,
        "SINTER_STEAM_INPUT_T_PER_T_SINTER": SINTER_STEAM_INPUT_T_PER_T_SINTER,
        "SINTER_DIRECT_CO2_T_PER_T_SINTER": SINTER_DIRECT_CO2_T_PER_T_SINTER,
        "SINTER_CO2_ACCOUNTING_MODE": SINTER_CO2_ACCOUNTING_MODE,
    }
    for parameter_id, expected in required.items():
        assert parameter_id in by_id
        row = by_id[parameter_id]
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"
        if isinstance(expected, str):
            assert row["base_value"] == expected
        else:
            assert _num(row["base_value"]) == pytest.approx(expected, abs=1e-6)

    assert by_id["SINTER_ELECTRICITY_MWH_PER_T_SINTER"]["low_value"] == "0.0256"
    assert by_id["SINTER_ELECTRICITY_MWH_PER_T_SINTER"]["high_value"] == "0.0431"
    assert by_id["SINTER_COG_INPUT_GJ_PER_T_SINTER"]["low_value"] == "0.035"
    assert by_id["SINTER_COG_INPUT_GJ_PER_T_SINTER"]["high_value"] == "0.185"
    assert by_id["SINTER_STEAM_INPUT_T_PER_T_SINTER"]["low_value"] == "0.003"
    assert by_id["SINTER_STEAM_INPUT_T_PER_T_SINTER"]["high_value"] == "0.021"
    assert by_id["SINTER_DIRECT_CO2_T_PER_T_SINTER"]["low_value"] == "0.162"
    assert by_id["SINTER_DIRECT_CO2_T_PER_T_SINTER"]["high_value"] == "0.368"


def test_c5m_per_timestep_driver_and_ratios(c5m_outputs: Path):
    hourly = _read_csv(c5m_outputs / "s4_4c5m_sinter_hourly_flows.csv")
    assert len(hourly) == 2 * (24 + 168)
    assert {row["sinter_driver_mode"] for row in hourly} == {"BF_hot_metal_coupled"}
    for row in hourly:
        expected = _num(row["bf_hot_metal_output_site_t"]) * _num(row["sinter_per_t_hot_metal"])
        assert _num(row["sinter_output_site_t"]) == pytest.approx(expected, abs=1e-4)

    report = _read_csv(c5m_outputs / "s4_4c5m_sinter_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for horizon in ("24", "168"):
        assert _num(by_key[(C0, horizon)]["sinter_per_t_hot_metal"]) == pytest.approx(3.7 / 6.3, abs=1e-6)
        assert _num(by_key[(C1, horizon)]["sinter_per_t_hot_metal"]) == pytest.approx(2.8 / 2.8, abs=1e-9)
        assert _num(by_key[(C0, horizon)]["sinter_output_site_t_y"]) == pytest.approx(3_468_752, rel=5e-4)
        assert _num(by_key[(C1, horizon)]["sinter_output_site_t_y"]) == pytest.approx(2_801_600, rel=5e-4)


def test_c5m_anchors_are_reported_not_constraints_or_ramps(c5m_outputs: Path):
    report = _read_csv(c5m_outputs / "s4_4c5m_sinter_report.csv")
    anchors = _read_csv(c5m_outputs / "s4_4c5m_anchor_gap_dashboard.csv")
    assert report
    assert anchors
    assert all(row["anchor_constraints_used"] == "0" for row in report)
    assert all(row["constraint_used"] == "false" for row in anchors)
    assert any(abs(_num(row["raw_MER_sinter_gap_site_t_y"])) > 1.0 for row in report if row["configuration"] == C0)
    for row in report:
        if row["configuration"] == C1:
            assert row["C1_operational_flex_band_status"] in {
                "within_context_band_not_ramp",
                "near_upper_bound_context_gap_not_ramp",
            }
        assert "ramp" not in row["deferred_items"].lower() or "ramp_flex_scheduling" in row["deferred_items"]


def test_c5m_sinter_gas_controller_allowed_carriers_and_no_wag_production(c5m_outputs: Path):
    report = _read_csv(c5m_outputs / "s4_4c5m_sinter_report.csv")
    controller = _read_csv(c5m_outputs / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")
    trace = _read_csv(c5m_outputs / "s4_4c5m_sinter_gas_wag_controller_trace.csv")
    for row in report:
        assert row["sinter_allowed_gas_carriers"] == "COG;NG"
        assert row["sinter_wag_production_flag"] == "false"
        assert row["no_sinter_wag_production_status"] == "pass"

    for row in controller:
        assert row["status"] == "pass"
        assert row["fixed_plant_priority_imposed"] == "false"
        assert _num(row["BFG_to_Sinter_site_MWh_y"]) == 0.0
        assert _num(row["BOFG_to_Sinter_site_MWh_y"]) == 0.0
        assert _num(row["Sinter_gas_unserved_site_MWh_y"]) == 0.0
        supplied = _num(row["COG_to_Sinter_site_MWh_y"]) + _num(row["NG_to_Sinter_site_MWh_y"])
        assert supplied == pytest.approx(_num(row["sinter_gas_demand_site_MWh_y"]), abs=WAG_TOL_MWH)
        hsm_supplied = (
            _num(row["BFG_to_HSM_site_MWh_y"])
            + _num(row["COG_to_HSM_site_MWh_y"])
            + _num(row["BOFG_to_HSM_site_MWh_y"])
            + _num(row["NG_to_HSM_site_MWh_y"])
            + _num(row["HSM_unserved_reheat_site_MWh_y"])
        )
        assert hsm_supplied == pytest.approx(_num(row["hsm_reheat_demand_site_MWh_y"]), abs=WAG_TOL_MWH)

    for row in trace:
        if row["sink_id"] == "Sinter_gas" and row["carrier"] in {"BFG", "BOFG"}:
            assert row["eligible_for_sink"] == "false"
            assert _num(row["allocated_site_MWh_LHV_y"]) == 0.0

    wag_rows = _read_csv(c5m_outputs / "s4_4c5m_wag_generation_consumption_by_plant.csv")
    sinter_rows = [row for row in wag_rows if row.get("plant_id") == "Sinter_Plant"]
    assert sinter_rows
    assert all(_num(row["generated_MWh_LHV_y"]) == 0.0 for row in sinter_rows)


def test_c5m_steam_and_electricity_are_active_demands(c5m_outputs: Path):
    steam = _read_csv(c5m_outputs / "s4_4c5m_sinter_steam_proxy_dashboard.csv")
    electricity = _read_csv(c5m_outputs / "s4_4c5m_sinter_electricity_ledger.csv")
    report = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(c5m_outputs / "s4_4c5m_sinter_report.csv")
    }
    for row in steam:
        assert row["steam_mode"] == SINTER_STEAM_MODE
        assert row["steam_supply_mode"] == "proxy_supply_until_steam_network"
        assert row["status"] == "pass"
        assert _num(row["sinter_steam_proxy_supply_site_t_y"]) == pytest.approx(_num(row["sinter_steam_demand_site_t_y"]))
        assert _num(row["sinter_steam_unserved_site_t_y"]) == 0.0

    for row in electricity:
        key = (row["configuration"], row["horizon_hours"])
        assert row["status"] == "process_electricity_demand_added"
        assert row["electricity_price_response_asset"] == "false"
        assert row["DA_bidding_or_settlement_added"] == "false"
        assert _num(row["electricity_site_MWh_e_y"]) == pytest.approx(_num(report[key]["sinter_output_site_t_y"]) * SINTER_ELECTRICITY_MWH_PER_T_SINTER, abs=0.1)


def test_c5m_sinter_co2_aggregate_counter_and_double_count_guard(c5m_outputs: Path):
    report = _read_csv(c5m_outputs / "s4_4c5m_sinter_report.csv")
    co2 = _read_csv(c5m_outputs / "s4_4c5m_sinter_co2_accounting_dashboard.csv")
    for row in report:
        expected = _num(row["sinter_output_site_t_y"]) * SINTER_DIRECT_CO2_T_PER_T_SINTER
        assert _num(row["sinter_aggregate_CO2_site_t_y"]) == pytest.approx(expected, abs=0.1)
        assert row["sinter_CO2_accounting_mode"] == SINTER_CO2_ACCOUNTING_MODE
        assert row["CO2_double_counting_guard_status"] == "pass"

    aggregate = [row for row in co2 if row["emission_bucket"] == "Sinter_aggregate_CO2_diagnostic"]
    combustion = [row for row in co2 if row["emission_bucket"] == "Sinter_COG_NG_combustion_CO2"]
    assert aggregate and combustion
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)
    assert all(row["included_in_total_direct_CO2"] == "false" for row in combustion)
    assert all("would_double_count" in row["double_counting_risk"] for row in combustion)


def test_c5m_wag_lhv_and_inherited_hsm_baseline(c5m_outputs: Path):
    aggregate = _read_csv(c5m_outputs / "s4_4c5m_wag_aggregate_invariant.csv")
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)

    lhv = _read_csv(c5m_outputs / "s4_4c5m_lhv_consistency_checks.csv")
    assert all(row["status"] == "pass" for row in lhv)

    controller = _read_csv(c5m_outputs / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")
    c5l_d = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for row in controller:
        assert row["inherited_hsm_heat_case"] == "base_0_50"
        assert _num(row["hsm_reheat_demand_site_MWh_y"]) == pytest.approx(_num(c5l_d[(row["configuration"], row["horizon_hours"])]["hsm_reheat_heat_site_MWh_th_y"]), abs=WAG_TOL_MWH)


def test_c5m_preserves_upstream_policies_and_forbidden_scope(c5m_outputs: Path):
    c5k = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")
    }
    assert _num(c5k[(C0, "24")]["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
    assert _num(c5k[(C1, "24")]["bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
    assert _num(c5k[(C1, "24")]["eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)

    c5j_inputs = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    c5j_by_id = {row["parameter_id"]: row for row in c5j_inputs}
    assert _num(c5j_by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.208)
    assert _num(c5j_by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.294)
    assert _num(c5j_by_id["BOF_BOFG_OUTPUT_NM3_PER_T_LS"]["base_value"]) == pytest.approx(75.0)

    assert BF_HOT_STOVE_DEMAND_MWH_PER_T_HM == pytest.approx(BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM / 3.6)
    assert KGF_UNDERFIRING_GJ_PER_T_COKE == pytest.approx(3.55)

    gate = json.loads((c5m_outputs / "s4_4c5m_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["C5k_production_targets_and_route_split_changed"] is False
    assert gate["C5j_BOF_coefficients_changed"] is False
    assert gate["C5h_BF_hot_stove_convention_changed"] is False
    assert gate["KGF_COG_self_use_convention_changed"] is False
    assert gate["Sinter_ramp_or_DA_price_response_added"] is False
    assert gate["ETS_objective_steering_added"] is False
    assert gate["WAG_market_valuation_added"] is False
    assert gate["WAG_export_revenue_added"] is False

    for path in c5m_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "product revenue" not in text
        assert "wag export revenue" not in text
        assert "direct wag market valuation" not in text
        assert "cvar" not in text
        assert "mfr.r" not in text
