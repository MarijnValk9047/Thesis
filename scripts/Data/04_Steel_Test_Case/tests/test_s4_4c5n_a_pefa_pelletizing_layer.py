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
from steel.s4_4c5n_a_pefa_pelletizing_layer import (  # noqa: E402
    C5N_A_DIR,
    STAGE,
    run_s4_4c5n_a_pefa_pelletizing_layer,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5n_a_outputs() -> Path:
    run_s4_4c5n_a_pefa_pelletizing_layer()
    return C5N_A_DIR


def test_c5n_a_required_outputs_and_stage_status(c5n_a_outputs: Path):
    required = [
        "s4_4c5n_a_stage_gate.json",
        "s4_4c5n_a_run_registry.csv",
        "s4_4c5n_a_pefa_development_input_rows.csv",
        "s4_4c5n_a_pefa_validation_anchors.csv",
        "s4_4c5n_a_pefa_activity_report.csv",
        "s4_4c5n_a_pefa_material_ledger.csv",
        "s4_4c5n_a_pefa_electricity_ledger.csv",
        "s4_4c5n_a_pefa_gas_controller_dashboard.csv",
        "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv",
        "s4_4c5n_a_modelled_totals_delta.csv",
        "s4_4c5n_a_pefa_compact_healthcheck.csv",
        "s4_4c5n_a_red_flags.csv",
        "s4_4c5n_a_compact_table_for_chat.csv",
        "s4_4c5n_a_pefa_pelletizing_report.json",
        "s4_4c5n_a_summary.json",
    ]
    for filename in required:
        path = c5n_a_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5n_a_outputs / "s4_4c5n_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage"] == STAGE
    assert gate["decision"] == "pass_development_pefa_pelletizing_layer"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["PEFA_WAG_generation_expected_zero"] is True
    assert gate["PEFA_BFG_allowed"] is False


def test_pefa_development_input_rows_are_governed(c5n_a_outputs: Path):
    rows = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "PEFA_IRON_ORE_INPUT_T_PER_T_PELLETS",
        "PEFA_ELECTRICITY_MWH_PER_T",
        "PEFA_GAS_FUEL_TOTAL_GJ_PER_T",
        "PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T",
        "PEFA_DIRECT_CO2_T_PER_T",
        "PEFA_WASTE_GAS_FLOW_NM3_PER_T",
        "PEFA_MALERIJ_ALLOWED_FUELS",
        "PEFA_BRANDERIJ_ALLOWED_FUELS",
        "PEFA_BFG_ALLOWED",
    }
    assert required.issubset(by_id)
    for row in rows:
        assert row["source_card"].endswith("PELLETIZING_Parameters.md")
        assert row["input_status"] == "development_candidate"
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]

    anchors = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_validation_anchors.csv")
    assert {row["anchor_status"] for row in anchors} == {"validation_anchor_not_dispatch_constraint"}


def test_pefa_activity_uses_existing_scaled_anchor_convention(c5n_a_outputs: Path):
    rows = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_activity_report.csv"))
    c0 = rows[(C0, 24)]
    c1 = rows[(C1, 24)]
    assert _num(c0["PEFA_output_site_t_y"]) == pytest.approx(4.6e6 * 6.75 / 7.2, abs=1e-6)
    assert _num(c1["PEFA_output_site_t_y"]) == pytest.approx(5.0e6 * 6.75 / 6.8, abs=1e-6)
    for row in rows.values():
        assert row["PEFA_OPERATION_CLASS"] == "continuous_upstream_process_not_DA_responsive"
        assert row["PEFA_ACTIVITY_MODE"] == "fixed_profile_scaled_to_active_target"
        assert row["PEFA_DA_RESPONSIVE"] == "false"
        assert row["anchor_used_as_hourly_cap"] == "false"
        assert row["price_response_test_status"] == "not_applicable_no_PEFA_DA_mode_in_C5n_a"


def test_pefa_formula_closure(c5n_a_outputs: Path):
    activity = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_activity_report.csv"))
    material = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_material_ledger.csv"))
    electricity = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_electricity_ledger.csv"))
    gas = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_gas_controller_dashboard.csv"))
    co2 = _keyed(_read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv"))
    for key, row in activity.items():
        output = _num(row["PEFA_output_site_t_y"])
        assert _num(material[key]["PEFA_iron_ore_input_site_t_y"]) == pytest.approx(0.950 * output, abs=1e-6)
        assert _num(material[key]["fired_pellets_output_site_t_y"]) == pytest.approx(output, abs=1e-6)
        assert _num(electricity[key]["PEFA_electricity_site_MWh_e_y"]) == pytest.approx(0.0213 * output, abs=1e-6)
        assert _num(gas[key]["PEFA_gas_heat_demand_site_GJ_y"]) == pytest.approx(0.320 * output, abs=1e-6)
        assert _num(co2[key]["PEFA_coke_breeze_or_anthracite_site_GJ_y"]) == pytest.approx(0.342 * output, abs=1e-6)
        assert _num(co2[key]["PEFA_diagnostic_CO2_site_t_y"]) == pytest.approx(0.105 * output, abs=1e-6)
        assert _num(co2[key]["PEFA_waste_gas_flow_site_Nm3_y"]) == pytest.approx(2170.0 * output, abs=1e-3)


def test_pefa_wag_eligibility_and_no_wag_generation(c5n_a_outputs: Path):
    gas = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_gas_controller_dashboard.csv")
    co2 = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv")
    for row in gas:
        assert row["PEFA_MALERIJ_ALLOWED_FUELS"] == "BOFG;NG"
        assert row["PEFA_BRANDERIJ_ALLOWED_FUELS"] == "COG;NG"
        assert row["PEFA_BFG_ALLOWED"] == "false"
        assert _num(row["BFG_to_PEFA_site_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["PEFA_DIRECT_WAG_MARKET_VALUE"] == "false"
        assert row["PEFA_STAGE_GAS_SPLIT_REQUIRED"] == "false"
    for row in co2:
        assert _num(row["PEFA_useful_WAG_generation_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["PEFA_waste_gas_reporting_only"] == "true"
        assert row["PEFA_waste_gas_in_WAG_balance"] == "false"


def test_pefa_heat_service_and_ng_reporting(c5n_a_outputs: Path):
    rows = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_gas_controller_dashboard.csv")
    for row in rows:
        assert _num(row["PEFA_malerij_heat_site_MWh_y"]) + _num(row["PEFA_branderij_heat_site_MWh_y"]) == pytest.approx(
            _num(row["PEFA_gas_heat_demand_site_MWh_y"]),
            abs=1e-6,
        )
        assert _num(row["PEFA_unserved_heat_site_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["PEFA_NG_backup_site_MWh_y"]) >= 0.0
        assert row["status"] == "pass"
        assert row["PEFA_STAGE_ALLOCATION_DEGENERATE_OR_IMPLAUSIBLE"] == "false"


def test_pefa_healthcheck_integration_and_redflags(c5n_a_outputs: Path):
    health = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_compact_healthcheck.csv")
    redflags = _read_csv(c5n_a_outputs / "s4_4c5n_a_red_flags.csv")
    assert len(health) == 4
    assert len(redflags) == 4
    for row in health:
        assert row["plant_or_controller"] == "PEFA_Pelletizing_Plant"
        assert row["stage_status"] == "development_only"
        assert row["thesis_usability"] == "false"
        assert _num(row["electricity_MWh_y"]) > 0.0
        assert _num(row["gas_heat_MWh_y"]) > 0.0
        assert row["PEFA_steam_status"] == "deferred_no_source"
        assert row["PEFA_DA_RESPONSIVE"] == "false"
        assert row["red_flags"] == ""
        assert int(row["failure_count"]) == 0
    for row in redflags:
        for key, value in row.items():
            if key.startswith("PEFA_"):
                assert value == "false"
        assert int(row["failure_count"]) == 0
        assert row["status"] == "pass"


def test_pefa_before_after_deltas_and_existing_baseline_status(c5n_a_outputs: Path):
    rows = _read_csv(c5n_a_outputs / "s4_4c5n_a_modelled_totals_delta.csv")
    assert rows
    for row in rows:
        assert _num(row["process_electricity_after_PEFA_MWh_e_y"]) == pytest.approx(
            _num(row["process_electricity_before_PEFA_MWh_e_y"]) + _num(row["PEFA_electricity_delta_MWh_e_y"]),
            abs=1e-6,
        )
        assert _num(row["diagnostic_CO2_after_PEFA_t_y"]) == pytest.approx(
            _num(row["diagnostic_CO2_before_PEFA_t_y"]) + _num(row["PEFA_CO2_delta_t_y"]),
            abs=1e-6,
        )
        assert _num(row["PEFA_BFG_consumption_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["HSM_heat_case"] == "base_0_50"
        assert row["WAG_invariant_status_before_PEFA"] == "pass"
        assert row["CO2_guard_status_before_PEFA"] == "pass"


def test_pefa_co2_guard_and_steam_status(c5n_a_outputs: Path):
    rows = _read_csv(c5n_a_outputs / "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv")
    for row in rows:
        assert row["PEFA_CO2_MODE"] == "aggregate_diagnostic"
        assert row["PEFA_fuel_explicit_CO2_active"] == "false"
        assert row["PEFA_CO2_double_count_guard_status"] == "pass"
        assert row["PEFA_direct_CO2_range_low_t_per_t"] == "0.017"
        assert row["PEFA_direct_CO2_range_high_t_per_t"] == "0.193"
