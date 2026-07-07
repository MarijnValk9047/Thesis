from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5h_blast_furnace_controller_parameterisation import (  # noqa: E402
    BF_BFG_OUTPUT_MWH_PER_T_HM,
    BF_BFG_OUTPUT_NM3_PER_T_HM,
    BF_COKE_RATE_T_PER_T_HM,
    BF_CO2_COUNTER_AGG_T_PER_T_HM,
    BF_ELECTRICITY_MWH_PER_T_HM,
    BF_HOT_STOVE_DEMAND_MWH_PER_T_HM,
    BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM,
    BF_OXYGEN_INPUT_KG_PER_T_HM,
    BF_PCI_COAL_INPUT_T_PER_T_HM,
    BF_STEAM_MWH_PER_T_HM,
    BFG_LHV_MJ_PER_NM3,
    C5G_DIR,
    C5H_DIR,
    C1,
    SOURCE_CARD,
    WAG_TOL_MWH,
    run_s4_4c5h_blast_furnace_controller_parameterisation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5h_outputs() -> Path:
    run_s4_4c5h_blast_furnace_controller_parameterisation()
    return C5H_DIR


def test_c5h_source_card_controller_policy_updated():
    text = SOURCE_CARD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "Controller_Blast_Furnace" in text
    assert "WAGs_BF_Hot_Stove" in text
    assert "must not directly consume WAGs" in text
    assert "BFG_LHV_MJ_PER_NM3" in text
    assert "3.85" in text
    assert "3.3" in text and "Retire from base" in text
    assert "4.72 GJ/t HM" in text and "Do not use" in text
    assert "1600" in text and "1.711111" in text and "6.16" in text
    assert "aggregate_hot_metal_counter" in text
    assert "exact tata truth" in lowered


def test_c5h_required_outputs_exist_and_parse(c5h_outputs: Path):
    required = [
        "s4_4c5h_stage_gate.json",
        "s4_4c5h_run_registry.csv",
        "s4_4c5h_24h_summary.csv",
        "s4_4c5h_168h_summary.csv",
        "s4_4c5h_bf_parameter_values.csv",
        "s4_4c5h_bf_process_diagnostics.csv",
        "s4_4c5h_bf_controller_flows_hourly.csv",
        "s4_4c5h_bf_hot_stove_controller_dashboard.csv",
        "s4_4c5h_bfg_gross_self_use_surplus_dashboard.csv",
        "s4_4c5h_coke_balance_kgf_to_bf.csv",
        "s4_4c5h_bf_anchor_gap_dashboard.csv",
        "s4_4c5h_bf_co2_accounting_dashboard.csv",
        "s4_4c5h_wag_generation_consumption_by_plant.csv",
        "s4_4c5h_wag_aggregate_invariant.csv",
        "s4_4c5h_energy_by_plant.csv",
        "s4_4c5h_emissions_by_plant.csv",
        "s4_4c5h_plant_conversion_ratios.csv",
        "s4_4c5h_lhv_consistency_checks.csv",
        "s4_4c5h_anchor_gap_dashboard.csv",
        "s4_4c5h_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5h_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5h_outputs / "s4_4c5h_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_bf_controller_parameterisation_with_open_coke_and_co2_gaps"
    assert gate["BF_process_direct_WAG_input_allowed"] is False
    assert gate["c1_bf6_active"] is True
    assert gate["c1_bf7_inactive"] is True
    assert gate["wag_aggregate_invariant_fail_count"] == 0
    assert gate["lhv_consistency_fail_count"] == 0


def test_c5h_bf_topology_and_process_coefficients(c5h_outputs: Path):
    rows = _read_csv(c5h_outputs / "s4_4c5h_bf_process_diagnostics.csv")
    by_key = {(row["configuration"], row["horizon_hours"], row["plant_id"]): row for row in rows}
    for horizon in ("24", "168"):
        assert by_key[("C0_current_BF_BOF_reference", horizon, "BF6")]["active"] == "true"
        assert by_key[("C0_current_BF_BOF_reference", horizon, "BF7")]["active"] == "true"
        assert by_key[(C1, horizon, "BF6")]["active"] == "true"
        assert by_key[(C1, horizon, "BF7")]["active"] == "false"
        assert _num(by_key[(C1, horizon, "BF7")]["hot_metal_site_t_y"]) == 0.0

    for row in rows:
        hm = _num(row["hot_metal_raw_t_y"])
        if row["active"] != "true":
            continue
        assert row["bus0_basis"] == "hot_metal_basis_with_coke_equivalent_reporting"
        assert row["BF_process_direct_gas_input_status"] == "no_direct_WAG_or_gas_input_controller_only"
        assert _num(row["coke_demand_raw_t_y"]) == pytest.approx(hm * BF_COKE_RATE_T_PER_T_HM)
        assert _num(row["PCI_raw_t_y"]) == pytest.approx(hm * BF_PCI_COAL_INPUT_T_PER_T_HM)
        assert _num(row["oxygen_raw_kg_y"]) == pytest.approx(hm * BF_OXYGEN_INPUT_KG_PER_T_HM)
        assert _num(row["electricity_raw_MWh_y"]) == pytest.approx(hm * BF_ELECTRICITY_MWH_PER_T_HM)
        assert _num(row["steam_raw_MWh_proxy_y"]) == pytest.approx(hm * BF_STEAM_MWH_PER_T_HM)
        assert _num(row["BFG_gross_raw_Nm3_y"]) == pytest.approx(hm * BF_BFG_OUTPUT_NM3_PER_T_HM)
        assert _num(row["BFG_gross_raw_MWh_LHV_y"]) == pytest.approx(hm * BF_BFG_OUTPUT_MWH_PER_T_HM)
        assert _num(row["BF_hot_stove_demand_raw_MWh_y"]) == pytest.approx(hm * BF_HOT_STOVE_DEMAND_MWH_PER_T_HM)
        assert _num(row["BF_CO2_counter_raw_t_y"]) == pytest.approx(hm * BF_CO2_COUNTER_AGG_T_PER_T_HM)

    assert BF_BFG_OUTPUT_MWH_PER_T_HM == pytest.approx(1600.0 * BFG_LHV_MJ_PER_NM3 / 3600.0)
    assert BF_HOT_STOVE_DEMAND_MWH_PER_T_HM == pytest.approx(BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM / 3.6)


def test_c5h_controller_balance_and_bfg_surplus(c5h_outputs: Path):
    controller = _read_csv(c5h_outputs / "s4_4c5h_bf_hot_stove_controller_dashboard.csv")
    assert all(row["status"] == "pass" for row in controller)
    for row in controller:
        raw_inputs = (
            _num(row["BFG_input_raw_MWh_y"])
            + _num(row["COG_input_raw_MWh_y"])
            + _num(row["BOFG_input_raw_MWh_y"])
            + _num(row["NG_input_raw_MWh_y"])
        )
        assert raw_inputs == pytest.approx(_num(row["BF_hot_stove_heat_output_raw_MWh_y"]))
        assert _num(row["COG_input_raw_MWh_y"]) == 0.0
        assert _num(row["BOFG_input_raw_MWh_y"]) == 0.0
        assert _num(row["NG_input_raw_MWh_y"]) == 0.0

    bfg = _read_csv(c5h_outputs / "s4_4c5h_bfg_gross_self_use_surplus_dashboard.csv")
    assert all(row["status"] == "pass" for row in bfg)
    for row in bfg:
        gross = _num(row["BFG_gross_raw_MWh_LHV_y"])
        self_use = _num(row["BFG_to_Controller_BF_raw_MWh_y"])
        surplus = _num(row["BFG_surplus_to_WAG_raw_MWh_y"])
        assert gross == pytest.approx(self_use + surplus)
        assert surplus >= 0.0


def test_c5h_general_wag_uses_net_bfg_surplus(c5h_outputs: Path):
    bf = _read_csv(c5h_outputs / "s4_4c5h_bf_process_diagnostics.csv")
    aggregate = _read_csv(c5h_outputs / "s4_4c5h_wag_aggregate_invariant.csv")
    c5g_aggregate = _read_csv(C5G_DIR / "s4_4c5g_wag_aggregate_invariant.csv")
    for config in ("C0_current_BF_BOF_reference", C1):
        for horizon in ("24", "168"):
            for basis, bf_field, agg_field in (
                ("raw", "BFG_surplus_to_WAG_raw_MWh_y", "BFG_generated_MWh_y"),
                ("site_scaled", "BFG_surplus_to_WAG_site_MWh_y", "BFG_generated_MWh_y"),
            ):
                bf_surplus = sum(
                    _num(row[bf_field])
                    for row in bf
                    if row["configuration"] == config and row["horizon_hours"] == horizon
                )
                agg = next(row for row in aggregate if row["configuration"] == config and row["horizon_hours"] == horizon and row["scale_basis"] == basis)
                old = next(row for row in c5g_aggregate if row["configuration"] == config and row["horizon_hours"] == horizon and row["scale_basis"] == basis)
                assert _num(agg[agg_field]) == pytest.approx(bf_surplus)
                assert _num(agg[agg_field]) < _num(old[agg_field])

    for row in aggregate:
        generated = _num(row["total_WAG_generated_MWh_y"])
        accounted = _num(row["total_WAG_accounted_MWh_y"])
        assert generated == pytest.approx(accounted, abs=WAG_TOL_MWH)
        assert _num(row["total_WAG_flared_MWh_y"]) <= generated + WAG_TOL_MWH
        assert row["status"] == "pass"


def test_c5h_coke_balance_reported_not_forced(c5h_outputs: Path):
    coke = _read_csv(c5h_outputs / "s4_4c5h_coke_balance_kgf_to_bf.csv")
    assert coke
    assert all(row["constraint_used"] == "false" for row in coke)
    assert any(row["status"] == "gap_reported_not_forced" for row in coke)
    for row in coke:
        gap = _num(row["kgf_coke_available_site_t_y"]) - _num(row["bf_coke_demand_site_t_y"])
        assert _num(row["coke_balance_gap_site_t_y"]) == pytest.approx(gap)


def test_c5h_bf_co2_aggregate_mode_no_double_count(c5h_outputs: Path):
    co2 = _read_csv(c5h_outputs / "s4_4c5h_bf_co2_accounting_dashboard.csv")
    aggregate = [row for row in co2 if row["emission_bucket"] == "BF_aggregate_hot_metal_counter"]
    diagnostic = [row for row in co2 if row["emission_bucket"] == "BFG_downstream_combustion_CO2_potential_diagnostic"]
    assert aggregate and diagnostic
    assert all(row["accounting_convention"] == "aggregate_hot_metal_counter" for row in aggregate)
    assert all(row["included_in_total_direct_CO2"] == "true" for row in aggregate)
    assert all(row["included_in_total_direct_CO2"] == "false" for row in diagnostic)
    assert all("would_double_count" in row["double_counting_risk"] for row in diagnostic)


def test_c5h_no_retired_policy_strings_in_outputs(c5h_outputs: Path):
    for path in c5h_outputs.glob("*"):
        text = path.read_text(encoding="utf-8")
        assert "9 PJ" not in text
        assert "50/50" not in text
        assert "50_50" not in text
        assert "product revenue" not in text.lower()
        assert "direct wag market value" not in text.lower()
