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
from steel.s4_4c5p_d_buffer_store_register_and_validation import (  # noqa: E402
    C5P_A_DIR,
    C5P_B_DIR,
    C5P_C_DIR,
    C5P_D_DIR,
    CAVEATS,
    FAILURE_FLAGS,
    REPORT_PATH,
    SOURCE_CARD,
    run_s4_4c5p_d_buffer_store_register_and_validation,
)


REQUIRED_OUTPUTS = [
    "c5_buffer_store_presence_matrix.csv",
    "c5_buffer_store_current_values.csv",
    "c5_buffer_store_validation_metrics.csv",
    "c5_buffer_store_anchor_gap_matrix.csv",
    "c5_buffer_store_source_card_cross_reference.csv",
    "c5_buffer_store_decision_register.csv",
    "c5_buffer_store_red_flags.csv",
    "c5_buffer_store_stage_gate.json",
    "s4_4c5p_d_stage_gate.json",
    "s4_4c5p_d_run_registry.csv",
    "s4_4c5p_d_summary.json",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5p_d_outputs() -> Path:
    run_s4_4c5p_d_buffer_store_register_and_validation()
    return C5P_D_DIR


def test_canonical_buffer_store_markdown(c5p_d_outputs: Path):
    assert c5p_d_outputs.exists()
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "executable input table" in text
    assert "not thesis-approved" in text
    for category in [
        "active_physical_store",
        "active_practically_nonbinding_bulk_solid_store",
        "active_interface_or_accounting_buffer",
        "structural_or_validation_anchor_only",
        "deferred_or_sensitivity_only",
        "blocked_as_store",
    ]:
        assert category in text

    assert "`hot_metal_store`" in text
    assert "500 t" in text
    assert "`oxygen_short_buffer`" in text
    assert "1670 m3" in text
    assert "100 t" in text
    assert "`dri_buffer`" in text
    assert "15.230 kt" in text
    assert "17.76 kt" in text
    assert "`bfg_cog_holders`" in text
    assert "`steam_store`" in text
    assert "`internal_scrap_loss_stream`" in text
    assert "`finished_product_accounting`" in text


def test_c5p_d_required_outputs_and_stage_gate(c5p_d_outputs: Path):
    for name in REQUIRED_OUTPUTS:
        path = c5p_d_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_d_outputs / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_buffer_store_register_validation"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["oxygen_buffer_mode"] == "balancing_buffer_only"
    assert gate["HSM_heat_case"] == "base_0_50"
    assert gate["steam_store_active"] is False
    assert gate["WAG_holder_hourly_store_active"] is False
    assert gate["hot_metal_store_active_base"] is False
    assert gate["denominator_status"] == "unresolved_until_residual_loads_and_boundary_complete"
    assert gate["electricity_accounting_status"] == "internal_offset_or_reporting_only_not_DA_market_revenue"
    assert gate["C1_24h_DRI_buffer_capacity_t"] == pytest.approx(15229.652603, abs=1e-6)
    assert gate["C1_24h_DRI_inventory_drift_t"] == pytest.approx(0.0, abs=1e-9)
    assert gate["bulk_solid_capacity_bind_count_max"] == pytest.approx(0.0, abs=1e-9)


def test_source_card_cross_reference_no_silent_promotion(c5p_d_outputs: Path):
    rows = _read_csv(c5p_d_outputs / "c5_buffer_store_source_card_cross_reference.csv")
    cards = {row["source_card"] for row in rows}
    assert {
        "PELLETIZING_Parameters.md",
        "DRP_Parameters.md",
        "EAF_Parameters.md",
        "DSP_Parameters.md",
        "LINDE_OXYGEN_Parameters.md",
        "BOILER_STEAM_CIRCUIT_Parameters.md",
        "IJ01_VN25_GENERATORS_Parameters.md",
        "HSM_Parameters.md",
        "HSM_Slab_Buffer_Parameters.md",
        "BUFFERS_STORAGE_Parameters.md",
    } <= cards
    assert all(row["mismatch_flag"] == "false" for row in rows)
    assert all(row["recommended_action"] != "promote_to_executable_input" for row in rows)


def test_buffer_store_presence_matrix(c5p_d_outputs: Path):
    rows = {row["buffer_id"]: row for row in _read_csv(c5p_d_outputs / "c5_buffer_store_presence_matrix.csv")}
    assert rows["coke_store"]["current_C5_status"] == "active_practically_nonbinding_bulk_solid_store"
    assert rows["sinter_store"]["current_C5_status"] == "active_practically_nonbinding_bulk_solid_store"
    assert rows["fired_pellets_proxy_store"]["current_C5_status"] == "active_practically_nonbinding_bulk_solid_store"
    assert rows["dri_buffer"]["current_C5_status"] == "active_physical_store"
    assert rows["dri_buffer"]["active_in_C0"] == "false"
    assert rows["dri_buffer"]["active_in_C1"] == "true"
    assert rows["oxygen_short_buffer"]["current_C5_status"] == "structural_or_validation_anchor_only"
    assert rows["steam_store"]["current_C5_status"] == "blocked_as_store"
    assert rows["bfg_cog_holders"]["current_C5_status"] == "blocked_as_store"
    assert rows["bofg_holder"]["current_C5_status"] == "blocked_as_store"
    assert rows["hot_metal_store"]["current_C5_status"] == "deferred_or_sensitivity_only"
    assert rows["liquid_steel_ladle_buffer"]["current_C5_status"] == "blocked_as_store"
    assert rows["finished_product_accounting"]["current_C5_status"] == "active_interface_or_accounting_buffer"


def test_capacity_terminal_and_no_free_source_checks(c5p_d_outputs: Path):
    rows = _read_csv(c5p_d_outputs / "c5_buffer_store_validation_metrics.csv")

    dri = next(
        row for row in rows
        if row["buffer_id"] == "dri_buffer" and row["configuration"] == C1 and int(row["horizon"]) == 24
    )
    assert _num(dri["capacity"]) == pytest.approx(15229.652603, abs=1e-6)
    assert _num(dri["start_inventory"]) == pytest.approx(7614.826301, abs=1e-6)
    assert _num(dri["end_inventory"]) == pytest.approx(7614.826301, abs=1e-6)
    assert _num(dri["annual_drift"]) == pytest.approx(0.0, abs=1e-9)
    assert dri["terminal_rule_pass"] == "true"
    assert dri["no_free_source_pass"] == "true"
    assert dri["no_free_battery_pass"] == "true"

    assert all(row["status"] == "pass" for row in rows)
    assert all(row["negative_inventory_count"] in {"", "0", "0.0"} for row in rows)
    assert all(row["terminal_rule_pass"] == "true" for row in rows)

    bulk = [row for row in rows if row["buffer_id"] in {"coke_store", "sinter_store", "fired_pellets_proxy_store"}]
    assert bulk
    assert all(_num(row["capacity_bind_count"]) == pytest.approx(0.0, abs=1e-9) for row in bulk)
    assert all(row["no_free_source_pass"] == "true" for row in bulk)

    oxygen = next(
        row for row in rows
        if row["buffer_id"] == "oxygen_short_buffer" and row["configuration"] == C0 and int(row["horizon"]) == 24
    )
    assert oxygen["status"] == "pass"
    assert "deferred_until_pressure" in oxygen["caveat"]
    assert _num(oxygen["start_inventory"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(oxygen["end_inventory"]) == pytest.approx(0.0, abs=1e-9)


def test_baseline_preservation_snapshots(c5p_d_outputs: Path):
    assert c5p_d_outputs.exists()

    generator = _keyed(_read_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv"))
    c0_gen = generator[(C0, 24)]
    c1_gen = generator[(C1, 24)]
    assert c0_gen["generator_layer_status"] == "C0_residual_wag_generator_interface_active"
    assert _num(c0_gen["total_generator_electricity_offset_MWh_e_y"]) == pytest.approx(2067664.90124, abs=1e-6)
    assert _num(c0_gen["residual_WAG_after_generators_and_flare_PJ_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(c1_gen["VN25_total_fuel_PJ_y"]) == pytest.approx(9.759416, abs=1e-6)
    assert _num(c1_gen["IJ01_total_fuel_PJ_y"]) == pytest.approx(0.077195, abs=1e-6)
    assert _num(c1_gen["generator_fuel_gap_unserved_PJ_y"]) == pytest.approx(4.763389, abs=1e-6)
    assert c1_gen["denominator_status"] == "unresolved_until_residual_loads_and_boundary_complete"

    steam = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv"))
    c0_steam = steam[(C0, 24)]
    assert _num(c0_steam["total_steam_demand_t_y"]) == pytest.approx(356130.613099, abs=1e-6)
    assert _num(c0_steam["total_steam_supply_t_y"]) == pytest.approx(356130.6131, abs=1e-6)
    assert _num(c0_steam["total_steam_spill_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(c0_steam["total_unserved_steam_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert c0_steam["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"

    oxygen = _keyed(_read_csv(C5P_A_DIR / "s4_4c5p_a_oxygen_demand_ledger.csv"))
    c1_oxygen = oxygen[(C1, 24)]
    assert _num(c1_oxygen["total_core_oxygen_demand_t_y"]) == pytest.approx(982143.7312, abs=1e-6)
    assert c1_oxygen["oxygen_demand_double_counted_kg_and_Nm3"] == "false"


def test_red_flags_and_parse_sanity(c5p_d_outputs: Path):
    for path in c5p_d_outputs.glob("*.csv"):
        assert _read_csv(path), path.name
    for path in c5p_d_outputs.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    redflags = _read_csv(c5p_d_outputs / "c5_buffer_store_red_flags.csv")[0]
    assert redflags["status"] == "pass_with_caveats"
    assert redflags["failure_count"] == "0"
    assert redflags["caveat_count"] == "13"
    for flag in FAILURE_FLAGS:
        assert redflags[flag] == "false"
    for caveat in CAVEATS:
        assert redflags[caveat] == "true"
