from __future__ import annotations

import csv
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5_anchor_route_denominator_diagnostics import (  # noqa: E402
    ANCHOR_COLUMNS,
    DECISION_COLUMNS,
    DENOM_COLUMNS,
    OUT_DIR,
    REPORT_PATH,
    ROUTE_COLUMNS,
    UTILITY_COLUMNS,
    build_outputs,
)
from steel.s4_4c5p_a_linde_asu_oxygen_accounting import (  # noqa: E402
    run_s4_4c5p_a_linde_asu_oxygen_accounting,
)
from steel.s4_4c5p_b_boiler_steam_circuit_accounting import (  # noqa: E402
    run_s4_4c5p_b_boiler_steam_circuit_accounting,
)
from steel.s4_4c5p_c_ij01_vn25_generator_interface_accounting import (  # noqa: E402
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_c5_anchor_route_diagnostics_outputs_parse_and_have_required_columns():
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    run_s4_4c5p_b_boiler_steam_circuit_accounting()
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting()
    result = build_outputs()
    assert result["status"] == "pass_diagnostic_only"
    assert REPORT_PATH.exists()

    expected = {
        OUT_DIR / "c5_anchor_reconciliation_matrix.csv": ANCHOR_COLUMNS,
        OUT_DIR / "c5_reconciliation_decision_register.csv": DECISION_COLUMNS,
        OUT_DIR / "c5_final_product_denominator_diagnostics.csv": DENOM_COLUMNS,
        OUT_DIR / "c5_route_origin_and_scrap_diagnostics.csv": ROUTE_COLUMNS,
        OUT_DIR / "c5_utility_readiness_diagnostics.csv": UTILITY_COLUMNS,
    }
    for path, columns in expected.items():
        rows = _read_csv(path)
        assert rows, path
        assert set(columns).issubset(rows[0].keys())


def test_c5_anchor_route_diagnostics_cover_required_decisions_and_caveats():
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    run_s4_4c5p_b_boiler_steam_circuit_accounting()
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting()
    build_outputs()

    anchor_rows = _read_csv(OUT_DIR / "c5_anchor_reconciliation_matrix.csv")
    anchor_ids = {row["anchor_id"] for row in anchor_rows}
    for required in {
        "final_product_proxy",
        "eaf_dri_input",
        "dsp_output",
        "bf_coke_demand",
        "drp_oxygen",
        "eaf_oxygen",
        "process_electricity_total",
        "diagnostic_co2_total",
        "linde_total_oxygen_demand",
        "linde_asu_electricity",
        "linde_residual_unmodelled_oxygen",
        "steam_total_demand",
        "steam_supply_total",
        "steam_72bar_supply",
        "steam_45bar_supply",
        "steam_15bar_process_load",
        "steam_spill_total",
        "steam_unserved_total",
        "boiler_k15k16_steam_capacity",
        "boiler_k23k24_steam_capacity",
        "boiler_k41_steam_capacity",
        "steg11_steam_capacity",
        "steg11_electricity_capacity",
        "tg2_steam_capacity",
        "tg2_electricity_capacity",
        "wag_to_steam",
        "ng_backup_for_steam",
        "remaining_wag_after_steam",
        "steg11_electricity",
        "tg2_electricity",
        "steam_circuit_internal_electricity",
        "generator_dispatch_mode",
        "generator_electricity_value_mode",
        "c0_generator_option_b_status",
        "c0_generator_interface_total_fuel",
        "c0_generator_electricity_validation_anchor",
        "c0_generator_electricity_offset_actual",
        "c0_generator_electricity_gap_to_validation_anchor",
        "c0_generator_efficiency_development_only",
        "vn25_generator_role",
        "ij01_generator_role",
        "vn24_backup_status",
        "vn25_generator_fuel",
        "ij01_generator_fuel",
        "generator_total_with_flare",
        "generator_fuel_gap",
        "generator_flare_or_spill",
        "generator_electricity_offset",
        "vn25_electricity_offset",
        "ij01_electricity_offset",
        "remaining_wag_after_generators",
        "process_electricity_after_generator_offset_reporting_only",
        "current_product_gas_reuse_context",
        "current_vattenfall_residual_gas_electricity_context",
        "current_tata_average_power_context",
        "transferred_power_plants_total_capacity_context",
        "athanasiadis_vn25_capacity_precedent",
        "generator_ij01_base_variant_total_fuel",
    }:
        assert required in anchor_ids

    decisions = _read_csv(OUT_DIR / "c5_reconciliation_decision_register.csv")
    decision_ids = {row["decision_id"] for row in decisions}
    assert "C5_DECISION_FINAL_DENOMINATOR" in decision_ids
    assert "C5_DECISION_COKE_RECONCILIATION" in decision_ids
    assert "C5_DECISION_EAF_DRI_COEFF" in decision_ids
    coke_decision = next(row for row in decisions if row["decision_id"] == "C5_DECISION_COKE_RECONCILIATION")
    assert "active development baseline" in coke_decision["current_choice"]
    assert "fallback-only" in coke_decision["current_choice"]
    denom_decision = next(row for row in decisions if row["decision_id"] == "C5_DECISION_FINAL_DENOMINATOR")
    assert "Do not choose yet" in denom_decision["recommended_action"]
    assert "generator/interface" in denom_decision["recommended_action"]

    route_rows = _read_csv(OUT_DIR / "c5_route_origin_and_scrap_diagnostics.csv")
    assert any(
        row["topic"] == "DSP_route_origin"
        and row["status"] == "route_origin_not_fully_tracked"
        for row in route_rows
    )
    assert any(
        row["topic"] == "internal_scrap"
        and row["flow_or_asset"] == "DSP_internal_scrap_loss"
        and row["status"] == "reporting_only"
        for row in route_rows
    )

    utility_rows = _read_csv(OUT_DIR / "c5_utility_readiness_diagnostics.csv")
    utility_areas = {row["utility_area"] for row in utility_rows}
    assert {"Linde_ASU_oxygen", "boilers_steam", "Vattenfall_IJ01_VN25_generators"}.issubset(
        utility_areas
    )
    linde = next(row for row in utility_rows if row["utility_area"] == "Linde_ASU_oxygen")
    assert linde["current_status"] == "implemented_accounting_only_after_C5p_a"
    steam = next(row for row in utility_rows if row["utility_area"] == "boilers_steam")
    assert steam["current_status"] == "implemented_accounting_only_after_C5p_b"
    assert "accounting-only" in steam["current_supply_available"]
    assert "generator_interface" in steam["recommended_stage"]
    generators = next(row for row in utility_rows if row["utility_area"] == "Vattenfall_IJ01_VN25_generators")
    assert generators["current_status"] == "implemented_accounting_only_after_C5p_c"
    assert "C0 residual-WAG interface" in generators["current_supply_available"]
    assert "No export revenue" in generators["caveat"]
    residual_electricity = next(row for row in utility_rows if row["utility_area"] == "residual_electricity")
    assert residual_electricity["current_status"] == "process_scope_plus_internal_offsets_reporting_only"

    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "diagnostic-only review" in report
    assert "C1 has only a pooled liquid-steel-to-DSP interface" in report
    assert "A future economics denominator must be frozen" in report
    assert "C5p_b adds mass-flow steam buses" in report
    assert "C5p_c adds carrier-specific C1 IJ01/VN25 accounting plus a C0 residual-WAG-derived generator-interface offset" in report
    assert "denominator remains unresolved after C5p_c" in report
