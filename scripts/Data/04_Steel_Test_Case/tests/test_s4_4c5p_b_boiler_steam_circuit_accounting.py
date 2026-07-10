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
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR  # noqa: E402
from steel.s4_4c5p_a_linde_asu_oxygen_accounting import C5P_A_DIR  # noqa: E402
from steel.s4_4c5p_b_boiler_steam_circuit_accounting import (  # noqa: E402
    BOILER_UNITS,
    C5P_B_DIR,
    DENOMINATOR_STATUS,
    STAGE,
    STEG11,
    TG2,
    run_s4_4c5p_b_boiler_steam_circuit_accounting,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _keyed_unit(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in rows}


@pytest.fixture(scope="module")
def c5p_b_outputs() -> Path:
    run_s4_4c5p_b_boiler_steam_circuit_accounting()
    return C5P_B_DIR


def test_c5p_b_required_outputs_and_stage_status(c5p_b_outputs: Path):
    required = [
        "s4_4c5p_b_stage_gate.json",
        "s4_4c5p_b_run_registry.csv",
        "s4_4c5p_b_boiler_steam_development_input_rows.csv",
        "s4_4c5p_b_steam_bus_rows.csv",
        "s4_4c5p_b_fuel_eligibility_rows.csv",
        "s4_4c5p_b_existing_steam_demand_mapping.csv",
        "s4_4c5p_b_steam_demand_by_pressure.csv",
        "s4_4c5p_b_boiler_steam_supply_by_unit.csv",
        "s4_4c5p_b_steg11_chp_ledger.csv",
        "s4_4c5p_b_tg2_steam_turbine_ledger.csv",
        "s4_4c5p_b_reducer_flow_ledger.csv",
        "s4_4c5p_b_steam_bus_balance.csv",
        "s4_4c5p_b_boiler_fuel_allocation.csv",
        "s4_4c5p_b_wag_residual_after_steam.csv",
        "s4_4c5p_b_internal_electricity_ledger.csv",
        "s4_4c5p_b_modelled_totals_delta.csv",
        "s4_4c5p_b_plant_kpi_table.csv",
        "s4_4c5p_b_compact_healthcheck.csv",
        "s4_4c5p_b_red_flags.csv",
        "s4_4c5p_b_compact_table_for_chat.csv",
        "s4_4c5p_b_boiler_steam_circuit_report.json",
        "s4_4c5p_b_summary.json",
    ]
    for name in required:
        path = c5p_b_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5p_b_outputs / "s4_4c5p_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_boiler_steam_circuit_accounting"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["boiler_steg_tg2_mFRR_enabled_base"] is False
    assert gate["STEG11_market_electricity_revenue_active"] is False
    assert gate["TG2_market_electricity_revenue_active"] is False
    assert gate["Vattenfall_generators_modelled"] is False
    assert gate["denominator_status"] == DENOMINATOR_STATUS


def test_source_card_and_development_input_migration(c5p_b_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    for token in ["BOILER_C1_K15K16", "BOILER_C2_K23K24", "BOILER_C2_K41", "STEG11", "TG2"]:
        assert token in text

    rows = _read_csv(c5p_b_outputs / "s4_4c5p_b_boiler_steam_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "BOILER_C1_K15K16_STEAM_MAX_T_H",
        "BOILER_C1_K15K16_FUEL_MWH_PER_T_STEAM",
        "BOILER_C2_K23K24_STEAM_MAX_T_H",
        "BOILER_C2_K23K24_FUEL_MWH_PER_T_STEAM",
        "BOILER_C2_K41_STEAM_MAX_T_H",
        "BOILER_C2_K41_FUEL_MWH_PER_T_STEAM",
        "STEG11_THERMAL_INPUT_MAX_MWTH",
        "STEG11_MARKET_ELECTRICITY_REVENUE_ACTIVE",
        "TG2_INPUT_CARRIER",
        "TG2_MARKET_ELECTRICITY_REVENUE_ACTIVE",
        "STEAM_STORAGE_ACTIVE_BASE",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("BOILER_STEAM_CIRCUIT_Parameters.md")
        assert row["input_status"].startswith("development")
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]
    assert by_id["STEG11_MARKET_ELECTRICITY_REVENUE_ACTIVE"]["base_value"] == "false"
    assert by_id["TG2_MARKET_ELECTRICITY_REVENUE_ACTIVE"]["base_value"] == "false"
    assert by_id["STEAM_STORAGE_ACTIVE_BASE"]["base_value"] == "false"

    buses = _read_csv(c5p_b_outputs / "s4_4c5p_b_steam_bus_rows.csv")
    bus_ids = {row["bus_id"] for row in buses}
    assert {"steam_72bar", "steam_45bar", "steam_15bar", "steam_spill_diagnostic"} <= bus_ids
    assert not any(row["bus_id"].startswith(("IJM01", "VN24", "VN25")) for row in buses)


def test_fuel_eligibility_forbidden_routes_and_tg2_steam_only(c5p_b_outputs: Path):
    rows = _read_csv(c5p_b_outputs / "s4_4c5p_b_fuel_eligibility_rows.csv")
    by_unit_carrier = {(row["unit_id"], row["input_carrier"]): row for row in rows}
    for carrier in ("BFG", "COG", "NG"):
        assert by_unit_carrier[("BOILER_C1_K15K16", carrier)]["allowed"] == "true"
        assert by_unit_carrier[("BOILER_C2_K23K24", carrier)]["allowed"] == "true"
    assert by_unit_carrier[("BOILER_C2_K41", "BFG")]["allowed"] == "true"
    assert by_unit_carrier[("BOILER_C2_K41", "NG")]["allowed"] == "true"
    assert by_unit_carrier[("BOILER_C2_K41", "COG")]["allowed"] == "false"
    assert by_unit_carrier[("STEG11_CHP", "BFG")]["allowed"] == "true"
    assert by_unit_carrier[("STEG11_CHP", "NG")]["allowed"] == "true"
    assert by_unit_carrier[("STEG11_CHP", "COG")]["allowed"] == "false"
    assert by_unit_carrier[("TG2_STEAM_TURBINE", "steam_72bar")]["allowed"] == "true"
    for carrier in ("BFG", "COG", "NG", "BOFG"):
        assert by_unit_carrier[("TG2_STEAM_TURBINE", carrier)]["allowed"] == "false"
    for unit in ("BOILER_C1_K15K16", "BOILER_C2_K23K24", "BOILER_C2_K41", "STEG11_CHP"):
        assert by_unit_carrier[(unit, "BOFG")]["allowed"] == "false"
        assert by_unit_carrier[(unit, "BOFG")]["direct_WAG_market_value_active"] == "false"


def test_boiler_conversion_capacity_and_unit_convention(c5p_b_outputs: Path):
    supply = _keyed_unit(_read_csv(c5p_b_outputs / "s4_4c5p_b_boiler_steam_supply_by_unit.csv"))
    fuel = _keyed_unit(_read_csv(c5p_b_outputs / "s4_4c5p_b_boiler_fuel_allocation.csv"))
    for config in (C0, C1):
        for unit_id, params in BOILER_UNITS.items():
            row = supply[(config, 24, unit_id)]
            fuel_row = fuel[(config, 24, unit_id)]
            steam = _num(row["steam_output_t_y"])
            required = steam * params["fuel_mwh_per_t_steam"]
            assert _num(row["fuel_heat_required_MWh_LHV_y"]) == pytest.approx(required, abs=1e-6)
            assert _num(fuel_row["total_fuel_allocated_MWh_LHV_y"]) == pytest.approx(required, abs=1e-6)
            assert steam <= params["steam_max_t_h"] * 8760.0 + 1e-6
            assert row["capacity_exceeded"] == "false"
            assert "MWh_LHV" in fuel_row["fuel_unit_convention"]
            assert params["fuel_mwh_per_t_steam"] * 3.6 > 0.0


def test_steg11_conversion_capacity_and_accounting_only(c5p_b_outputs: Path):
    rows = _keyed(_read_csv(c5p_b_outputs / "s4_4c5p_b_steg11_chp_ledger.csv"))
    fuel = _keyed_unit(_read_csv(c5p_b_outputs / "s4_4c5p_b_boiler_fuel_allocation.csv"))
    for config in (C0, C1):
        row = rows[(config, 24)]
        steam = _num(row["steam_output_72bar_t_y"])
        expected_fuel = steam * STEG11["fuel_mwh_per_t_steam"]
        expected_power = steam * STEG11["electricity_mwh_per_t_steam"]
        assert _num(row["fuel_heat_required_MWh_LHV_y"]) == pytest.approx(expected_fuel, abs=1e-6)
        assert _num(row["electricity_output_MWh_e_y"]) == pytest.approx(expected_power, abs=1e-6)
        assert _num(row["average_fuel_heat_MWth"]) <= STEG11["thermal_input_max_mwth"] + 1e-9
        assert _num(row["average_electricity_MWe"]) <= STEG11["electricity_max_mwe"] + 1e-9
        assert row["capacity_exceeded"] == "false"
        assert row["electricity_accounting_status"] == "accounting_only_reporting_only_not_DA_market_revenue"
        assert row["market_electricity_revenue_active"] == "false"
        assert row["mFRR_enabled_base"] == "false"
        assert _num(fuel[(config, 24, "STEG11_CHP")]["COG_MWh_LHV_y"]) == 0.0


def test_tg2_conversion_capacity_and_no_fuel_input(c5p_b_outputs: Path):
    rows = _keyed(_read_csv(c5p_b_outputs / "s4_4c5p_b_tg2_steam_turbine_ledger.csv"))
    for config in (C0, C1):
        row = rows[(config, 24)]
        steam = _num(row["steam_72bar_input_t_y"])
        assert steam <= TG2["steam_flow_max_t_h"] * 8760.0 + 1e-6
        assert _num(row["electricity_output_MWh_e_y"]) == pytest.approx(
            steam * TG2["electricity_mwh_per_t_steam_main"], abs=1e-6
        )
        assert _num(row["steam_15bar_output_t_y"]) == pytest.approx(steam, abs=1e-9)
        assert _num(row["average_electricity_MWe"]) <= TG2["electricity_max_mwe"] + 1e-9
        assert _num(row["fuel_input_MWh_LHV_y"]) == 0.0
        assert row["capacity_exceeded"] == "false"
        assert row["market_electricity_revenue_active"] == "false"
        assert row["mFRR_enabled_base"] == "false"


def test_steam_bus_balances_spill_and_unserved_visible(c5p_b_outputs: Path):
    rows = _read_csv(c5p_b_outputs / "s4_4c5p_b_steam_bus_balance.csv")
    assert {(row["pressure_level"]) for row in rows} == {"steam_72bar", "steam_45bar", "steam_15bar"}
    for row in rows:
        assert abs(_num(row["balance_error_t_y"])) <= 1e-6
        assert row["spill_visible"] == "true"
        assert row["hidden_slack_active"] == "false"
        assert row["status"] == "pass"
    standard = [row for row in rows if int(row["horizon_hours"]) == 24]
    assert sum(_num(row["unserved_steam_t_y"]) for row in standard) == pytest.approx(0.0, abs=1e-9)
    assert sum(_num(row["steam_spill_t_y"]) for row in standard) == pytest.approx(0.0, abs=1e-9)


def test_no_fake_flexibility_market_logic_or_vattenfall_generation(c5p_b_outputs: Path):
    totals = _read_csv(c5p_b_outputs / "s4_4c5p_b_modelled_totals_delta.csv")
    electricity = _read_csv(c5p_b_outputs / "s4_4c5p_b_internal_electricity_ledger.csv")
    residual = _read_csv(c5p_b_outputs / "s4_4c5p_b_wag_residual_after_steam.csv")
    for row in totals:
        assert row["process_electricity_netting_applied"] == "false"
        assert row["electricity_accounting_status"] == "accounting_only_reporting_only_not_DA_market_revenue"
    for row in electricity:
        assert row["process_electricity_netting_applied"] == "false"
        assert row["counted_as_Vattenfall_generation"] == "false"
        assert row["full_site_net_electricity_claimed"] == "false"
        assert row["market_revenue_active"] == "false"
    for row in residual:
        assert row["steam_layer_BOFG_allowed"] == "false"
        assert row["WAG_direct_market_value_active"] == "false"
        assert row["WAG_export_revenue_active"] == "false"
        assert row["Vattenfall_generators_status"] == "deferred_not_modelled_in_C5p_b"


def test_baseline_preservation_coke_hsm_linde_and_denominator(c5p_b_outputs: Path):
    p_b = _keyed(_read_csv(c5p_b_outputs / "s4_4c5p_b_modelled_totals_delta.csv"))
    p_a = _keyed(_read_csv(C5P_A_DIR / "s4_4c5p_a_modelled_totals_delta.csv"))
    c5l_d = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for config in (C0, C1):
        key = (config, 24)
        assert _num(p_b[key]["process_electricity_after_Linde_ASU_MWh_e_y"]) == pytest.approx(
            _num(p_a[key]["process_electricity_after_Linde_ASU_MWh_e_y"]), abs=1e-6
        )
        assert p_b[key]["process_electricity_after_boiler_steam_MWh_e_y"] == p_b[key]["process_electricity_after_Linde_ASU_MWh_e_y"]
        assert p_b[key]["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"
        assert p_b[key]["external_unmodelled_coke_status"] == "fallback_only_not_active_baseline"
        assert p_b[key]["HSM_heat_case"] == "base_0_50"
        assert c5l_d[key]["active_cap_case"] == "base_0_50"
        assert p_b[key]["denominator_status"] == DENOMINATOR_STATUS


def test_healthcheck_redflags_and_required_caveats(c5p_b_outputs: Path):
    health = _read_csv(c5p_b_outputs / "s4_4c5p_b_compact_healthcheck.csv")
    redflags = _read_csv(c5p_b_outputs / "s4_4c5p_b_red_flags.csv")
    for row in health:
        assert row["boiler_steam_layer_active"] == "true"
        assert row["steam_pressure_buses_present"] == "true"
        assert _num(row["total_steam_demand_t_y"]) > 0.0
        assert _num(row["total_steam_supply_t_y"]) == pytest.approx(_num(row["total_steam_demand_t_y"]), abs=2e-6)
        assert _num(row["total_unserved_steam_t_y"]) == 0.0
        assert _num(row["total_steam_spill_t_y"]) == 0.0
        assert _num(row["K41_COG_MWh_LHV_y"]) == 0.0
        assert _num(row["STEG11_COG_MWh_LHV_y"]) == 0.0
        assert row["mFRR_disabled_for_boilers_STEG11_TG2"] == "true"
        assert row["Vattenfall_generators_deferred_status"] == "VATTENFALL_GENERATORS_DEFERRED"
        assert row["failure_count"] == "0"
        for caveat in [
            "STEAM_MASS_FLOW_NOT_ENTHALPY_MODEL",
            "STEAM_RESIDUAL_DEMAND_MISSING_OR_DEFERRED",
            "STEAM_PRESSURE_LEVEL_ASSUMED_FOR_EXISTING_DEMAND",
            "STEG11_ELECTRICITY_ACCOUNTING_ONLY",
            "TG2_ELECTRICITY_ACCOUNTING_ONLY",
            "DENOMINATOR_UNRESOLVED_UNTIL_GENERATOR_INTERFACE_AND_RESIDUAL_LOADS",
        ]:
            assert caveat in row["caveats"]
    for row in redflags:
        assert row["failure_count"] == "0"
        assert row["status"] == "pass_with_caveats"
        for failure in [
            "STEAM_BUS_MISSING",
            "STEAM_UNSERVED_NONZERO",
            "STEAM_SPILL_HIDDEN",
            "K41_COG_USED",
            "STEG11_COG_USED",
            "BOFG_USED_BY_STEAM_LAYER_WITHOUT_GOVERNED_SOURCE",
            "TG2_FUEL_INPUT_NONZERO",
            "STEG11_OR_TG2_MARKET_REVENUE_ACTIVE",
            "BOILER_STEG_TG2_MFRR_ENABLED_IN_BASE",
            "WAG_DIRECT_MARKET_VALUE_ACTIVE",
            "DENOMINATOR_SILENTLY_FROZEN",
        ]:
            assert row[failure] == "false", failure
