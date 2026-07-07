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
from steel.s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR  # noqa: E402
from steel.s4_4c5l_hsm_wbw_minimal_integration import (  # noqa: E402
    C5L_DIR,
    HSM_CO2_STATUS,
    HSM_OUTPUT_DRIVER_MODE,
    SOURCE_CARD,
    WAG_TOL_MWH,
    run_s4_4c5l_hsm_wbw_minimal_integration,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5l_outputs() -> Path:
    run_s4_4c5l_hsm_wbw_minimal_integration()
    return C5L_DIR


def test_c5l_source_card_exists_and_is_candidate_only():
    assert SOURCE_CARD.exists()
    text = SOURCE_CARD.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "candidate source-card" in lowered
    assert "thesis usability: false" in lowered
    assert "not exact tata truth" in lowered
    assert "HSM_SLAB_INPUT_T_PER_T_HRC" in text
    assert "HSM_REHEAT_ENERGY_GJ_PER_T_HRC" in text
    assert "HSM_OUTPUT_DRIVER_MODE" in text
    assert "validation/reporting targets only" in lowered


def test_c5l_required_outputs_exist_parse_and_stage_gate(c5l_outputs: Path):
    required = [
        "s4_4c5l_stage_gate.json",
        "s4_4c5l_run_registry.csv",
        "s4_4c5l_24h_summary.csv",
        "s4_4c5l_168h_summary.csv",
        "s4_4c5l_hsm_wbw_development_input_rows.csv",
        "s4_4c5l_hsm_wbw_parameter_register.csv",
        "s4_4c5l_hsm_wbw_report.csv",
        "s4_4c5l_hsm_wbw_anchor_gap_dashboard.csv",
        "s4_4c5l_hsm_wbw_slab_balance_dashboard.csv",
        "s4_4c5l_hsm_wbw_fuel_mix_dashboard.csv",
        "s4_4c5l_wag_generation_consumption_by_plant.csv",
        "s4_4c5l_wag_aggregate_invariant.csv",
        "s4_4c5l_lhv_consistency_checks.csv",
        "s4_4c5l_hsm_co2_accounting_dashboard.csv",
        "s4_4c5l_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5l_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5l_outputs / "s4_4c5l_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_hsm_wbw_minimal_integration"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["source_card_present"] is True
    assert gate["HSM_OUTPUT_DRIVER_MODE"] == HSM_OUTPUT_DRIVER_MODE
    assert gate["C0_HSM_output_site_t_y"] == pytest.approx(5_062_500.0)
    assert gate["C1_HSM_output_site_t_y"] == pytest.approx(5_500_000.0 * 6.75 / 6.8)
    assert gate["C1_imported_slab_driver_site_t_y"] == pytest.approx(600_000.0 * 6.75 / 6.8)
    assert gate["hsm_wag_producer_rows_nonzero_count"] == 0
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["HSM_CO2_derivation_status"] == HSM_CO2_STATUS
    assert gate["anchor_constraints_used_count"] == 0
    assert gate["no_free_slab_battery_status"] == "pass_no_slab_storage_created"
    assert gate["direct_WAG_market_valuation_added"] is False
    assert gate["WAG_export_revenue_added"] is False
    assert gate["product_revenue_added"] is False


def test_c5l_hsm_input_rows_are_governed_development_inputs(c5l_outputs: Path):
    rows = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "HSM_OUTPUT_DRIVER_MODE",
        "HSM_SLAB_INPUT_T_PER_T_HRC",
        "HSM_REHEAT_ENERGY_GJ_PER_T_HRC",
        "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC",
        "HSM_REHEAT_FUEL_CARRIER_BFG",
        "HSM_REHEAT_FUEL_CARRIER_COG",
        "HSM_REHEAT_FUEL_CARRIER_BOFG",
        "HSM_REHEAT_FUEL_CARRIER_NG",
    }
    assert required.issubset(by_id)
    assert _num(by_id["HSM_SLAB_INPUT_T_PER_T_HRC"]["base_value"]) == pytest.approx(1.10)
    assert _num(by_id["HSM_REHEAT_ENERGY_GJ_PER_T_HRC"]["base_value"]) == pytest.approx(1.35)
    assert _num(by_id["HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC"]["base_value"]) == pytest.approx(0.070)
    assert _num(by_id["HSM_SLAB_INPUT_T_PER_T_HRC"]["low_value"]) == pytest.approx(1.07)
    assert _num(by_id["HSM_SLAB_INPUT_T_PER_T_HRC"]["high_value"]) == pytest.approx(1.15)
    for row in rows:
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"


def test_c5l_preserves_c5k_target_and_route_split(c5l_outputs: Path):
    report = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for horizon in ("24", "168"):
        c0 = by_key[(C0, horizon)]
        assert _num(c0["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c0["c5k_bof_liquid_steel_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c0["c5k_eaf_liquid_steel_site_t_y"]) == pytest.approx(0.0)
        c1 = by_key[(C1, horizon)]
        assert _num(c1["active_total_liquid_steel_target_site_t_y"]) == pytest.approx(6_750_000.0)
        assert _num(c1["c5k_bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
        assert _num(c1["c5k_eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)


def test_c5l_scaled_hsm_drivers_and_equations(c5l_outputs: Path):
    report = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for horizon in ("24", "168"):
        c0 = by_key[(C0, horizon)]
        assert _num(c0["downstream_scale_to_active_target"]) == pytest.approx(6.75 / 7.2)
        assert _num(c0["hsm_output_site_t_y"]) == pytest.approx(5_062_500.0)
        assert _num(c0["dsp_output_site_t_y"]) == pytest.approx(1_406_250.0)
        assert _num(c0["imported_slab_site_t_y"]) == pytest.approx(0.0)
        assert _num(c0["hsm_slab_input_site_t_y"]) == pytest.approx(5_062_500.0 * 1.10)
        assert _num(c0["hsm_internal_loss_or_scrap_site_t_y"]) == pytest.approx(506_250.0)
        assert _num(c0["hsm_reheat_heat_demand_site_GJ_y"]) == pytest.approx(5_062_500.0 * 1.35)
        assert _num(c0["hsm_reheat_heat_demand_site_MWh_y"]) == pytest.approx(5_062_500.0 * 1.35 / 3.6)
        assert _num(c0["hsm_rolling_electricity_site_MWh_y"]) == pytest.approx(5_062_500.0 * 0.070)

        c1 = by_key[(C1, horizon)]
        scale = 6.75 / 6.8
        hsm = 5_500_000.0 * scale
        imported = 600_000.0 * scale
        assert _num(c1["downstream_scale_to_active_target"]) == pytest.approx(scale)
        assert _num(c1["hsm_output_site_t_y"]) == pytest.approx(hsm)
        assert _num(c1["dsp_output_site_t_y"]) == pytest.approx(1_500_000.0 * scale)
        assert _num(c1["imported_slab_site_t_y"]) == pytest.approx(imported)
        assert _num(c1["hsm_slab_input_site_t_y"]) == pytest.approx(hsm * 1.10)
        assert _num(c1["hsm_internal_loss_or_scrap_site_t_y"]) == pytest.approx(hsm * 0.10)
        assert _num(c1["hsm_reheat_heat_demand_site_GJ_y"]) == pytest.approx(hsm * 1.35)
        assert _num(c1["hsm_rolling_electricity_site_MWh_y"]) == pytest.approx(hsm * 0.070)


def test_c5l_validation_anchors_are_gap_rows_not_constraints(c5l_outputs: Path):
    anchors = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_anchor_gap_dashboard.csv")
    assert anchors
    assert all(row["constraint_used"] == "false" for row in anchors)
    assert all(row["anchor_status"] == "validation_context_only" for row in anchors)
    c1_import = next(row for row in anchors if row["configuration"] == C1 and row["metric"] == "imported_slab_context_t_y")
    assert _num(c1_import["anchor_quantity"]) == pytest.approx(600_000.0)
    assert _num(c1_import["model_site_quantity"]) == pytest.approx(600_000.0 * 6.75 / 6.8)


def test_c5l_slab_gap_reported_no_free_storage(c5l_outputs: Path):
    slab = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_slab_balance_dashboard.csv")
    assert slab
    for row in slab:
        assert row["no_free_slab_battery_status"] == "pass_no_slab_storage_created"
        assert row["status"] == "gap_reported_not_forced"
        expected_gap = (
            _num(row["active_total_liquid_steel_target_site_t_y"])
            + _num(row["imported_slab_driver_site_t_y"])
            - _num(row["dsp_output_driver_site_t_y"])
            - _num(row["hsm_slab_input_site_t_y"])
        )
        assert _num(row["indicative_downstream_material_gap_site_t_y"]) == pytest.approx(expected_gap)


def test_c5l_hsm_is_wag_sink_not_producer_and_uses_eligible_carriers(c5l_outputs: Path):
    wag = _read_csv(c5l_outputs / "s4_4c5l_wag_generation_consumption_by_plant.csv")
    hsm_rows = [row for row in wag if row["plant_id"] == "HSM_WBW"]
    assert hsm_rows
    assert {row["carrier"] for row in hsm_rows}.issubset({"BFG", "COG", "BOFG"})
    assert all(_num(row["generated_MWh_LHV_y"]) == 0.0 for row in hsm_rows)
    assert all(_num(row["consumed_direct_MWh_LHV_y"]) >= 0.0 for row in hsm_rows)

    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    c5k_site = {
        (row["configuration"], row["horizon_hours"], row["carrier"]): row
        for row in c5k_wag
        if row["plant_id"] == "SITE_TOTAL"
    }
    for row in hsm_rows:
        source = c5k_site[(row["configuration"], row["horizon_hours"], row["carrier"])]
        available = _num(source["generated_MWh_LHV_y"]) - _num(source["consumed_direct_MWh_LHV_y"])
        assert _num(row["consumed_direct_MWh_LHV_y"]) <= available + WAG_TOL_MWH

    fuel = _read_csv(c5l_outputs / "s4_4c5l_hsm_wbw_fuel_mix_dashboard.csv")
    assert {row["carrier"] for row in fuel}.issubset({"BFG", "COG", "BOFG", "NG"})
    assert all(row["eligible"] == "true" for row in fuel)


def test_c5l_wag_lhv_and_co2_guards_pass(c5l_outputs: Path):
    aggregate = _read_csv(c5l_outputs / "s4_4c5l_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)

    lhv = _read_csv(c5l_outputs / "s4_4c5l_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)

    co2 = _read_csv(c5l_outputs / "s4_4c5l_hsm_co2_accounting_dashboard.csv")
    hsm = [row for row in co2 if row["emission_bucket"] == "HSM_reheat_CO2"]
    assert hsm
    assert all(row["derivation_status"] == HSM_CO2_STATUS for row in hsm)
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)


def test_c5l_no_forbidden_market_or_storage_terms(c5l_outputs: Path):
    for path in c5l_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "product revenue" not in text
        assert "export revenue" not in text
        assert "direct wag market valuation" not in text
        assert "free slab battery" not in text

    modelbuilder = Path("scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py").read_text(encoding="utf-8")
    for forbidden_literal in ("1.10", "1.35", "0.070"):
        assert forbidden_literal not in modelbuilder
