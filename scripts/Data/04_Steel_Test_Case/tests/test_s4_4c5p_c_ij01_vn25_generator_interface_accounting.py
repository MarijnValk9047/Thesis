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
from steel.s4_4c5p_b_boiler_steam_circuit_accounting import C5P_B_DIR  # noqa: E402
from steel.s4_4c5p_c_ij01_vn25_generator_interface_accounting import (  # noqa: E402
    C5P_C_DIR,
    C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV,
    C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y,
    C0_GENERATOR_INTERFACE_STATUS,
    C0_GENERATOR_INTERFACE_UNIT,
    C1_PREFERRED_TOTAL_ANCHORS_PJ,
    DENOMINATOR_STATUS,
    ELECTRICITY_ACCOUNTING_STATUS,
    GENERATOR_DISPATCH_MODE,
    GENERATOR_ELECTRICITY_VALUE_MODE,
    GENERATOR_UNITS,
    PJ_TO_MWH,
    STAGE,
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md")
REQUIRED_CAVEATS = {
    "C0_GENERATOR_INTERFACE_DEVELOPMENT_ONLY",
    "C0_RESIDUAL_WAG_GENERATOR_INTERFACE_ACTIVE",
    "C0_GENERATOR_2TWH_VALIDATION_ANCHOR_ONLY",
    "C0_GENERATOR_CARRIER_SPLIT_UNDERPARAMETERISED",
    "C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY",
    "C0_GENERATOR_EFFICIENCY_DEVELOPMENT_ONLY",
    "C0_GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "C0_PRODUCT_GAS_REUSE_CONTEXT_ONLY",
    "CURRENT_TATA_AVG_POWER_CONTEXT_ONLY",
    "GENERATOR_INTERFACE_DEVELOPMENT_ONLY",
    "GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "GENERATOR_EXPORT_REVENUE_DEFERRED",
    "GENERATOR_PRICE_RESPONSIVE_MODE_DEFERRED",
    "GENERATOR_MFRR_DEFERRED",
    "VN24_BACKUP_DEFERRED",
    "IJ01_CHP_STEAM_OUTPUT_DEFERRED",
    "IJ01_ELECTRICITY_CONVERSION_DEFERRED",
    "VN25_EFFICIENCY_DEVELOPMENT_ONLY",
    "ATHANASIADIS_CAPACITY_PRECEDENT_ONLY",
    "TRANSFERRED_770MW_TOTAL_CAPACITY_CONTEXT_ONLY",
    "TABLE_5_5_ANNUAL_ANCHORS_NOT_HOURLY_SCHEDULES",
    "IJ01_HOURS_TEXT_TABLE_CONFLICT",
    "WAG_GAS_QUALITY_WOBBE_DEFERRED",
    "CO2_FUEL_EXPLICIT_DEFERRED",
    "FULL_SITE_ELECTRICITY_BOUNDARY_INCOMPLETE",
    "DENOMINATOR_UNRESOLVED_UNTIL_RESIDUAL_LOADS_AND_BOUNDARY_COMPLETE",
    "GENERATOR_NOT_THESIS_APPROVED",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _unit(rows: list[dict[str, str]], config: str, unit_id: str, horizon: int = 24) -> dict[str, str]:
    for row in rows:
        if row["configuration"] == config and int(row["horizon_hours"]) == horizon and row["unit_id"] == unit_id:
            return row
    raise KeyError((config, horizon, unit_id))


@pytest.fixture(scope="module")
def c5p_c_outputs() -> Path:
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting()
    return C5P_C_DIR


def test_c5p_c_required_outputs_and_stage_gate(c5p_c_outputs: Path):
    required = [
        "s4_4c5p_c_stage_gate.json",
        "s4_4c5p_c_run_registry.csv",
        "s4_4c5p_c_generator_development_input_rows.csv",
        "s4_4c5p_c_generator_bus_rows.csv",
        "s4_4c5p_c_generator_fuel_eligibility_rows.csv",
        "s4_4c5p_c_generator_anchor_comparison.csv",
        "s4_4c5p_c_generator_fuel_allocation.csv",
        "s4_4c5p_c_generator_electricity_ledger.csv",
        "s4_4c5p_c_wag_residual_after_generators.csv",
        "s4_4c5p_c_modelled_totals_delta.csv",
        "s4_4c5p_c_plant_kpi_table.csv",
        "s4_4c5p_c_compact_healthcheck.csv",
        "s4_4c5p_c_red_flags.csv",
        "s4_4c5p_c_compact_table_for_chat.csv",
        "s4_4c5p_c_generator_interface_report.json",
        "s4_4c5p_c_summary.json",
    ]
    for name in required:
        path = c5p_c_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5p_c_outputs / "s4_4c5p_c_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_generator_interface_accounting"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["generator_dispatch_mode"] == GENERATOR_DISPATCH_MODE
    assert gate["generator_electricity_value_mode"] == GENERATOR_ELECTRICITY_VALUE_MODE
    assert gate["generator_export_revenue_enabled_base"] is False
    assert gate["generator_price_responsive_dispatch_base"] is False
    assert gate["generator_mFRR_enabled_base"] is False
    assert gate["VN25_enabled_base"] is True
    assert gate["IJ01_enabled_base"] is True
    assert gate["VN24_enabled_base"] is False
    assert gate["full_site_net_electricity_claimed"] is False
    assert gate["DA_market_revenue_active"] is False
    assert gate["denominator_status"] == DENOMINATOR_STATUS
    assert gate["C0_24h_generator_layer_status"] == C0_GENERATOR_INTERFACE_STATUS
    assert gate["C0_24h_generator_electricity_validation_anchor_TWh_e_y"] == pytest.approx(2.0)
    assert gate["C0_24h_generator_electricity_actual_TWh_e_y"] == pytest.approx(2.067665, abs=1e-6)
    assert gate["C0_24h_generator_electricity_gap_to_validation_anchor_TWh_e_y"] == pytest.approx(0.067665, abs=1e-6)
    assert gate["C0_24h_generator_electric_efficiency_dev"] == pytest.approx(C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV)
    assert gate["C0_24h_generator_fuel_PJ_y"] == pytest.approx(21.892922, abs=1e-6)


def test_source_card_and_input_migration(c5p_c_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    for token in [
        "VN25",
        "IJ01",
        "VN24",
        "GENERATOR_DISPATCH_MODE",
        "fixed_or_validation_scaled_interface",
        "offset_site_grid_import",
        "GENERATOR_EXPORT_REVENUE_ENABLED_BASE",
        "GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE",
        "GENERATOR_MFRR_ENABLED_BASE",
        "Table 5.5",
        "770 MW",
    ]:
        assert token in text

    rows = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "GENERATOR_DISPATCH_MODE",
        "GENERATOR_ELECTRICITY_VALUE_MODE",
        "GENERATOR_EXPORT_REVENUE_ENABLED_BASE",
        "GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE",
        "GENERATOR_MFRR_ENABLED_BASE",
        "GENERIC_WAG_TO_GENERATORS_ACTIVE",
        "C0_GENERATOR_INTERFACE_STATUS",
        "C0_GENERATOR_INTERFACE_UNIT",
        "C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y",
        "C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV",
        "C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY",
        "VN25_ENABLED_BASE",
        "IJ01_ENABLED_BASE",
        "VN24_ENABLED_BASE",
        "VN25_TOTAL_FUEL_C1_PJ_Y",
        "IJ01_TOTAL_FUEL_C1_PJ_Y",
        "GENERATOR_FLARE_C1_PJ_Y",
        "GENERATOR_TOTAL_FUEL_C1_PJ_Y",
        "VN25_ELECTRIC_CAPACITY_MW_DEV",
        "TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW",
        "IJ01_ELECTRIC_EFFICIENCY_DEV",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("IJ01_VN25_GENERATORS_Parameters.md")
        assert row["input_status"]
        assert row["thesis_usability"] == "false"
        assert row["source_or_candidate_evidence"]
        assert row["caveat"]
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
    assert by_id["GENERATOR_DISPATCH_MODE"]["base_value"] == GENERATOR_DISPATCH_MODE
    assert by_id["GENERATOR_EXPORT_REVENUE_ENABLED_BASE"]["base_value"] == "false"
    assert by_id["GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE"]["base_value"] == "false"
    assert by_id["GENERATOR_MFRR_ENABLED_BASE"]["base_value"] == "false"
    assert by_id["VN25_ENABLED_BASE"]["base_value"] == "true"
    assert by_id["IJ01_ENABLED_BASE"]["base_value"] == "true"
    assert by_id["VN24_ENABLED_BASE"]["base_value"] == "false"
    assert by_id["C0_GENERATOR_INTERFACE_STATUS"]["base_value"] == C0_GENERATOR_INTERFACE_STATUS
    assert by_id["C0_GENERATOR_INTERFACE_UNIT"]["base_value"] == C0_GENERATOR_INTERFACE_UNIT
    assert _num(by_id["C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y"]["base_value"]) == pytest.approx(2_000_000.0)
    assert _num(by_id["C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV"]["base_value"]) == pytest.approx(0.34)
    assert by_id["C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY"]["base_value"] == "true"
    assert _num(by_id["VN25_TOTAL_FUEL_C1_PJ_Y"]["base_value"]) == pytest.approx(13.7)
    assert by_id["IJ01_ELECTRIC_EFFICIENCY_DEV"]["input_status"] == "development_deferred"


def test_fuel_eligibility_and_carrier_separation(c5p_c_outputs: Path):
    rows = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_fuel_eligibility_rows.csv")
    by_unit_carrier = {(row["unit_id"], row["input_carrier"]): row for row in rows}
    for carrier in ("BFG", "BOFG", "COG", "NG"):
        assert by_unit_carrier[("VN25", carrier)]["allowed"] == "true"
    for carrier in ("BFG", "BOFG", "COG"):
        assert by_unit_carrier[("IJ01", carrier)]["allowed"] == "true"
    assert by_unit_carrier[("IJ01", "NG")]["allowed"] == "false"
    for carrier in ("BFG", "BOFG", "COG", "NG", "GENERIC_WAG"):
        assert by_unit_carrier[("VN24", carrier)]["allowed"] == "false"
    for unit_id in ("VN25", "IJ01", "VN24"):
        assert by_unit_carrier[(unit_id, "GENERIC_WAG")]["allowed"] == "false"
        assert by_unit_carrier[(unit_id, "GENERIC_WAG")]["generic_wag_carrier_active"] == "false"
    assert {row["input_carrier"] for row in rows if row["allowed"] == "true"} == {"BFG", "BOFG", "COG", "NG"}

    buses = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_bus_rows.csv")
    bus_ids = {row["bus_id"] for row in buses}
    assert {"bfg_bus", "bofg_bus", "cog_bus", "natural_gas_bus", "electricity_internal_bus"} <= bus_ids
    assert "generic_wag_bus" not in bus_ids


def test_c1_preferred_and_sensitivity_anchors(c5p_c_outputs: Path):
    anchors = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_anchor_comparison.csv")
    by_anchor = {
        (row["configuration"], int(row["horizon_hours"]), row["anchor_id"]): row
        for row in anchors
    }
    assert _num(by_anchor[(C1, 24, "VN25_BFG_fuel")]["anchor_value_PJ_y"]) == pytest.approx(8.4)
    assert _num(by_anchor[(C1, 24, "VN25_BOFG_fuel")]["anchor_value_PJ_y"]) == pytest.approx(1.2)
    assert _num(by_anchor[(C1, 24, "VN25_COG_fuel")]["anchor_value_PJ_y"]) == pytest.approx(0.1)
    assert _num(by_anchor[(C1, 24, "VN25_NG_fuel")]["anchor_value_PJ_y"]) == pytest.approx(4.1)
    assert _num(by_anchor[(C1, 24, "VN25_total_fuel")]["anchor_value_PJ_y"]) == pytest.approx(13.7)
    assert _num(by_anchor[(C1, 24, "IJ01_total_fuel")]["anchor_value_PJ_y"]) == pytest.approx(0.8)
    assert _num(by_anchor[(C1, 24, "generator_flare")]["anchor_value_PJ_y"]) == pytest.approx(0.1)
    assert _num(by_anchor[(C1, 24, "generator_total_with_flare")]["anchor_value_PJ_y"]) == pytest.approx(14.6)
    assert by_anchor[(C1, 24, "VN25_total_fuel")]["anchor_status"] == "C1_preferred_validation_anchor_not_hourly_dispatch"
    assert by_anchor[(C1, 24, "VN25_total_fuel")]["active_base"] == "true"
    assert by_anchor[(C0, 24, "C0_generator_interface_total_fuel")]["anchor_status"] == C0_GENERATOR_INTERFACE_STATUS
    assert by_anchor[(C0, 24, "C0_generator_interface_total_fuel")]["active_base"] == "true"
    assert _num(by_anchor[(C0, 24, "C0_generator_interface_total_fuel")]["anchor_value_PJ_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(by_anchor[(C0, 24, "C0_generator_interface_total_fuel")]["model_value_PJ_y"]) == pytest.approx(21.892922, abs=1e-6)
    assert _num(by_anchor[(C0, 24, "CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY_TWH_Y")]["context_anchor_value"]) == pytest.approx(2.0)
    assert _num(by_anchor[(C0, 24, "CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY_TWH_Y")]["context_model_value"]) == pytest.approx(2.067665, abs=1e-6)
    assert _num(by_anchor[(C0, 24, "CURRENT_PRODUCT_GAS_REUSE_ANNUAL_PJ_Y")]["context_anchor_value"]) == pytest.approx(54.0)
    assert _num(by_anchor[(C0, 24, "CURRENT_TATA_AVG_ELECTRIC_POWER_MW")]["context_anchor_value"]) == pytest.approx(360.0)
    assert _num(by_anchor[(C0, 24, "TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW")]["context_anchor_value"]) == pytest.approx(770.0)

    dev = {row["parameter_id"]: row for row in _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_development_input_rows.csv")}
    assert dev["GENERATOR_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y"]["input_status"] == "sensitivity_anchor_deferred_not_active_base"
    assert dev["GENERATOR_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y"]["active_base"] == "false"


def test_generator_interface_accounting_no_market_layer(c5p_c_outputs: Path):
    fuel_rows = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_fuel_allocation.csv")
    electricity = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_generator_electricity_ledger.csv"))
    for config in (C0, C1):
        for unit_id in ("VN25", "IJ01"):
            row = _unit(fuel_rows, config, unit_id)
            carrier_total = sum(_num(row[f"{carrier}_MWh_LHV_y"]) for carrier in ("BFG", "BOFG", "COG", "NG"))
            assert _num(row["total_fuel_allocated_MWh_LHV_y"]) == pytest.approx(carrier_total, abs=1e-6)
            assert row["generic_WAG_carrier_active"] == "false"
            assert row["market_revenue_active"] == "false"
            assert row["price_responsive_dispatch_active"] == "false"
            assert row["mFRR_enabled_base"] == "false"
            assert row["annual_anchor_not_hourly_dispatch_constraint"] == "true"

    c1_vn25 = _unit(fuel_rows, C1, "VN25")
    c1_elec = electricity[(C1, 24)]
    expected_vn25_elec = _num(c1_vn25["total_fuel_allocated_MWh_LHV_y"]) * GENERATOR_UNITS["VN25"]["electric_efficiency_dev"]
    assert _num(c1_elec["VN25_electricity_offset_MWh_e_y"]) == pytest.approx(expected_vn25_elec, abs=1e-6)
    assert _num(c1_elec["IJ01_electricity_offset_MWh_e_y"]) == 0.0
    assert _num(c1_elec["total_generator_electricity_offset_MWh_e_y"]) == pytest.approx(expected_vn25_elec, abs=1e-6)
    assert c1_elec["electricity_accounting_status"] == ELECTRICITY_ACCOUNTING_STATUS
    assert c1_elec["DA_market_revenue_active"] == "false"
    assert c1_elec["export_revenue_active"] == "false"
    assert c1_elec["price_responsive_dispatch_active"] == "false"
    assert c1_elec["mFRR_enabled_base"] == "false"
    assert c1_elec["full_site_net_electricity_claimed"] == "false"


def test_c0_option_b_residual_wag_fuel_and_validation_anchor_accounting(c5p_c_outputs: Path):
    fuel_rows = _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_fuel_allocation.csv")
    residual = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_wag_residual_after_generators.csv"))
    electricity = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_generator_electricity_ledger.csv"))
    health = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_compact_healthcheck.csv"))

    c0_fuel = _unit(fuel_rows, C0, C0_GENERATOR_INTERFACE_UNIT)
    c0_residual = residual[(C0, 24)]
    c0_elec = electricity[(C0, 24)]
    c0_health = health[(C0, 24)]

    available = (
        _num(c0_residual["available_BFG_after_steam_MWh_LHV_y"])
        + _num(c0_residual["available_BOFG_after_steam_MWh_LHV_y"])
        + _num(c0_residual["available_COG_after_steam_MWh_LHV_y"])
    )
    consumed = _num(c0_residual["WAG_to_generators_MWh_LHV_y"])
    expected_fuel = available

    assert c0_health["generator_layer_status"] == C0_GENERATOR_INTERFACE_STATUS
    assert _num(c0_fuel["BFG_MWh_LHV_y"]) > 0.0
    assert _num(c0_fuel["BOFG_MWh_LHV_y"]) > 0.0
    assert _num(c0_fuel["COG_MWh_LHV_y"]) > 0.0
    assert _num(c0_fuel["NG_MWh_LHV_y"]) == 0.0
    assert _num(c0_fuel["total_fuel_allocated_MWh_LHV_y"]) == pytest.approx(expected_fuel, abs=1e-6)
    assert consumed == pytest.approx(expected_fuel, abs=1e-6)
    assert consumed <= available + 1e-6
    assert _num(c0_residual["generator_fuel_gap_unserved_MWh_LHV_y"]) == 0.0
    assert _num(c0_residual["residual_WAG_after_generators_and_flare_MWh_LHV_y"]) == pytest.approx(0.0, abs=1e-6)
    assert c0_fuel["carrier_split_status"] == "proportional_split_over_governed_residual_BFG_BOFG_COG_after_steam"
    assert c0_fuel["generic_WAG_carrier_active"] == "false"
    expected_electricity = expected_fuel * C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV
    expected_gap = (expected_electricity - C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y) / 1_000_000.0
    assert _num(c0_elec["C0_generator_electricity_validation_anchor_TWh_e_y"]) == pytest.approx(2.0)
    assert _num(c0_elec["C0_generator_electricity_actual_TWh_e_y"]) == pytest.approx(expected_electricity / 1_000_000.0, abs=1e-6)
    assert _num(c0_elec["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"]) == pytest.approx(expected_gap, abs=1e-6)
    assert _num(c0_elec["C0_generator_electricity_actual_TWh_e_y"]) != pytest.approx(2.0, abs=1e-6)
    assert _num(c0_elec["C0_generator_electric_efficiency_dev"]) == pytest.approx(C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV)
    assert _num(c0_elec["total_generator_electricity_offset_MWh_e_y"]) == pytest.approx(expected_electricity, abs=1e-6)
    assert c0_elec["electricity_accounting_status"] == ELECTRICITY_ACCOUNTING_STATUS
    assert c0_elec["DA_market_revenue_active"] == "false"
    assert c0_elec["export_revenue_active"] == "false"
    assert c0_elec["mFRR_enabled_base"] == "false"
    assert c0_elec["full_site_net_electricity_claimed"] == "false"


def test_no_fake_wag_flexibility_and_residual_reporting(c5p_c_outputs: Path):
    residual = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_wag_residual_after_generators.csv"))
    steam = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv"))
    for config in (C0, C1):
        row = residual[(config, 24)]
        available = (
            _num(row["available_BFG_after_steam_MWh_LHV_y"])
            + _num(row["available_BOFG_after_steam_MWh_LHV_y"])
            + _num(row["available_COG_after_steam_MWh_LHV_y"])
        )
        consumed = _num(row["WAG_to_generators_MWh_LHV_y"])
        assert consumed <= available + 1e-6
        assert row["WAG_direct_market_value_active"] == "false"
        assert row["WAG_export_revenue_active"] == "false"
        assert row["generic_WAG_carrier_active"] == "false"
        assert _num(row["available_BFG_after_steam_MWh_LHV_y"]) == pytest.approx(
            _num(steam[(config, 24)]["residual_BFG_after_steam_MWh_LHV_y"]), abs=1e-6
        )

    c1 = residual[(C1, 24)]
    assert _num(c1["generator_fuel_gap_unserved_MWh_LHV_y"]) > 0.0
    assert _num(c1["generator_flare_or_spill_MWh_LHV_y"]) == pytest.approx(0.1 * PJ_TO_MWH, abs=1e-6)
    assert _num(c1["residual_WAG_after_generators_and_flare_MWh_LHV_y"]) > 0.0


def test_capacity_efficiency_and_thesis_caveats(c5p_c_outputs: Path):
    electricity = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_generator_electricity_ledger.csv"))
    c1 = electricity[(C1, 24)]
    assert c1["VN25_capacity_context_status"] == "ATHANASIADIS_CAPACITY_PRECEDENT_ONLY"
    assert _num(c1["VN25_capacity_context_MW_dev"]) == pytest.approx(350.0)
    assert c1["VN25_capacity_exceeded_dev_context"] == "false"
    assert c1["IJ01_electricity_conversion_status"] == "IJ01_ELECTRICITY_CONVERSION_DEFERRED"
    assert c1["IJ01_steam_or_heat_output_status"] == "IJ01_CHP_STEAM_OUTPUT_DEFERRED"

    dev = {row["parameter_id"]: row for row in _read_csv(c5p_c_outputs / "s4_4c5p_c_generator_development_input_rows.csv")}
    assert _num(dev["TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW"]["base_value"]) == pytest.approx(770.0)
    assert "never a VN25/IJ01 unit capacity" in dev["TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW"]["caveat"]
    assert "not public Tata capacity" in dev["VN25_ELECTRIC_CAPACITY_MW_DEV"]["caveat"]
    assert dev["IJ01_STEAM_OUTPUT_STATUS"]["input_status"] == "development_deferred"


def test_electricity_ledger_separates_generator_steam_and_boundary_status(c5p_c_outputs: Path):
    electricity = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_generator_electricity_ledger.csv"))
    steam_elec = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_internal_electricity_ledger.csv"))
    totals = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_modelled_totals_delta.csv"))
    for config in (C0, C1):
        row = electricity[(config, 24)]
        assert "VN25_electricity_offset_MWh_e_y" in row
        assert "IJ01_electricity_offset_MWh_e_y" in row
        assert _num(row["steam_circuit_electricity_MWh_e_y"]) == pytest.approx(
            _num(steam_elec[(config, 24)]["total_steam_circuit_electricity_output_MWh_e_y"]), abs=1e-6
        )
        assert row["full_site_net_electricity_claimed"] == "false"
        assert row["DA_market_revenue_active"] == "false"
        assert totals[(config, 24)]["full_site_net_electricity_claimed"] == "false"
        assert totals[(config, 24)]["denominator_status"] == DENOMINATOR_STATUS


def test_baseline_preservation_boiler_hsm_coke_denominator(c5p_c_outputs: Path):
    steam_health = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv"))
    assert _num(steam_health[(C0, 24)]["total_steam_demand_t_y"]) == pytest.approx(356130.613099, abs=1e-3)
    assert _num(steam_health[(C0, 24)]["total_steam_supply_t_y"]) == pytest.approx(356130.6131, abs=1e-3)
    assert _num(steam_health[(C1, 24)]["total_steam_demand_t_y"]) == pytest.approx(165461.611488, abs=1e-3)
    assert _num(steam_health[(C1, 24)]["total_steam_supply_t_y"]) == pytest.approx(165461.611488, abs=1e-3)
    assert _num(steam_health[(C0, 24)]["total_steam_spill_t_y"]) == 0.0
    assert _num(steam_health[(C1, 24)]["total_unserved_steam_t_y"]) == 0.0

    health = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_compact_healthcheck.csv"))
    for config in (C0, C1):
        row = health[(config, 24)]
        assert row["HSM_heat_case"] == "base_0_50"
        assert row["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"
        assert row["external_unmodelled_coke_status"] == "fallback_only_not_active_baseline"
        assert row["denominator_status"] == DENOMINATOR_STATUS
        assert row["steam_layer_failure_count"] == "0"


def test_healthcheck_red_flags_and_required_caveats(c5p_c_outputs: Path):
    health = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_compact_healthcheck.csv"))
    redflags = _read_csv(c5p_c_outputs / "s4_4c5p_c_red_flags.csv")
    for config in (C0, C1):
        row = health[(config, 24)]
        assert row["failure_count"] == "0"
        assert set(row["caveats"].split(";")) == REQUIRED_CAVEATS
        assert row["VN25_enabled_base"] == "true"
        assert row["IJ01_enabled_base"] == "true"
        assert row["VN24_enabled_base"] == "false"
        assert row["VN24_status"] == "cold_backup_reserve_only_inactive_base"
        assert row["export_revenue_enabled_base"] == "false"
        assert row["price_responsive_dispatch_base"] == "false"
        assert row["mFRR_enabled_base"] == "false"

    for row in redflags:
        assert row["failure_count"] == "0"
        assert row["status"] == "pass_with_caveats"
        for field, value in row.items():
            if field.startswith(("C0_", "GENERATOR_", "WAG_", "GENERIC_", "BFG_", "VN24_", "IJ01_", "FULL_", "DENOMINATOR_")):
                if field in REQUIRED_CAVEATS:
                    continue
                assert value == "false", field


def test_diagnostics_artifacts_parse_and_generator_key_metrics(c5p_c_outputs: Path):
    for path in c5p_c_outputs.glob("*.csv"):
        assert _read_csv(path), path.name
    for path in c5p_c_outputs.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    health = _keyed(_read_csv(c5p_c_outputs / "s4_4c5p_c_compact_healthcheck.csv"))
    c0 = health[(C0, 24)]
    c1 = health[(C1, 24)]
    assert c0["generator_layer_status"] == C0_GENERATOR_INTERFACE_STATUS
    assert _num(c0["C0_generator_total_fuel_PJ_y"]) == pytest.approx(21.892922, abs=1e-6)
    assert _num(c0["C0_generator_electricity_actual_TWh_e_y"]) == pytest.approx(2.067665, abs=1e-6)
    assert _num(c0["C0_generator_electricity_validation_anchor_TWh_e_y"]) == pytest.approx(2.0, abs=1e-9)
    assert _num(c0["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"]) == pytest.approx(0.067665, abs=1e-6)
    assert _num(c0["residual_WAG_after_generators_and_flare_PJ_y"]) == pytest.approx(0.0, abs=1e-6)
    assert _num(c1["VN25_total_fuel_anchor_PJ_y"]) == pytest.approx(C1_PREFERRED_TOTAL_ANCHORS_PJ["VN25"])
    assert _num(c1["IJ01_total_fuel_anchor_PJ_y"]) == pytest.approx(C1_PREFERRED_TOTAL_ANCHORS_PJ["IJ01"])
    assert _num(c1["VN25_total_fuel_PJ_y"]) == pytest.approx(9.759416, abs=1e-6)
    assert _num(c1["IJ01_total_fuel_PJ_y"]) == pytest.approx(0.077195, abs=1e-6)
    assert _num(c1["generator_flare_or_spill_PJ_y"]) == pytest.approx(0.1, abs=1e-6)
    assert _num(c1["total_generator_electricity_offset_MWh_e_y"]) == pytest.approx(935277.350579, abs=1e-6)
    assert _num(c1["residual_WAG_after_generators_and_flare_PJ_y"]) == pytest.approx(0.737782, abs=1e-6)
