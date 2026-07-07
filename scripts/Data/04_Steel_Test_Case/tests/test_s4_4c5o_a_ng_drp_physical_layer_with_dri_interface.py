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
from steel.s4_4c5n_a_pefa_pelletizing_layer import C5N_A_DIR  # noqa: E402
from steel.s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy import C5N_B_DIR  # noqa: E402
from steel.s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import (  # noqa: E402
    C5O_A_DIR,
    STAGE,
    run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/DRP_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5o_a_outputs() -> Path:
    run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface()
    return C5O_A_DIR


def test_c5o_a_required_outputs_and_stage_status(c5o_a_outputs: Path):
    required = [
        "s4_4c5o_a_stage_gate.json",
        "s4_4c5o_a_run_registry.csv",
        "s4_4c5o_a_drp_development_input_rows.csv",
        "s4_4c5o_a_drp_validation_anchors.csv",
        "s4_4c5o_a_drp_activity_report.csv",
        "s4_4c5o_a_drp_material_energy_ledger.csv",
        "s4_4c5o_a_dri_buffer_interface_dashboard.csv",
        "s4_4c5o_a_pellet_burden_integration.csv",
        "s4_4c5o_a_modelled_totals_delta.csv",
        "s4_4c5o_a_plant_kpi_table.csv",
        "s4_4c5o_a_compact_healthcheck.csv",
        "s4_4c5o_a_red_flags.csv",
        "s4_4c5o_a_ng_drp_physical_layer_report.json",
        "s4_4c5o_a_summary.json",
    ]
    for name in required:
        path = c5o_a_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5o_a_outputs / "s4_4c5o_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_ng_drp_physical_layer_with_dri_interface"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["DRP_hydrogen_enabled_base"] is False
    assert gate["DRP_mFRR_eligible_base"] is False
    assert gate["DRP_tailgas_exportable_WAG"] is False
    assert gate["EAF_implemented_in_C5o_a"] is False


def test_drp_source_card_and_development_input_rows_are_governed(c5o_a_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "DRP_HYDROGEN_ENABLED_BASE" in text
    assert "DRP_MFRR_ELIGIBLE_BASE" in text
    assert "DRI buffer is not a free battery" in text

    rows = _read_csv(c5o_a_outputs / "s4_4c5o_a_drp_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "DRP_ROUTE_SCOPE",
        "DRP_TECHNOLOGY_BASE",
        "DRP_REDUCTANT_BASE",
        "DRP_HYDROGEN_ENABLED_BASE",
        "DRP_H2_INPUT_T_PER_T_DRI_BASE",
        "DRP_MFRR_ELIGIBLE_BASE",
        "DRP_EXPORTABLE_WAG_CARRIER",
        "DRP_C1_OUTPUT_ANNUAL_MT_Y",
        "DRP_PELLET_INPUT_T_PER_T_DRI",
        "DRP_NG_REDUCTION_GJ_PER_T_DRI",
        "DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI",
        "DRP_ELECTRICITY_MWH_PER_T_DRI",
        "DRP_CO2_CAPTURE_T_PER_T_DRI",
        "DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT",
        "DRI_BUFFER_CAPACITY_DAYS_BASE",
        "DRI_BUFFER_TERMINAL_RULE",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("DRP_Parameters.md")
        assert row["input_status"].startswith("development")
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]

    assert by_id["DRP_HYDROGEN_ENABLED_BASE"]["base_value"] == "false"
    assert by_id["DRP_MFRR_ELIGIBLE_BASE"]["base_value"] == "false"
    anchors = _read_csv(c5o_a_outputs / "s4_4c5o_a_drp_validation_anchors.csv")
    assert {row["anchor_status"] for row in anchors} >= {
        "validation_anchor_scaled_to_active_target_not_hourly_constraint",
        "validation_anchor_capture_stream_not_direct_emissions",
    }


def test_c0_drp_is_inactive_zero(c5o_a_outputs: Path):
    material = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_drp_material_energy_ledger.csv"))
    buffer_rows = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_dri_buffer_interface_dashboard.csv"))
    for horizon in (24, 168):
        row = material[(C0, horizon)]
        assert _num(row["DRI_output_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["pellets_to_DRP_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_NG_total_site_GJ_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_electricity_site_MWh_e_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_oxygen_diagnostic_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_CO2_capture_stream_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(buffer_rows[(C0, horizon)]["DRI_buffer_capacity_t"]) == pytest.approx(0.0, abs=1e-9)
        assert buffer_rows[(C0, horizon)]["temporary_DRI_to_future_EAF_interface_active"] == "false"


def test_c1_drp_formula_closure_and_active_scaling(c5o_a_outputs: Path):
    activity = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_drp_activity_report.csv"))
    material = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_drp_material_energy_ledger.csv"))
    c5n_b = _keyed(_read_csv(C5N_B_DIR / "s4_4c5n_b_pellet_balance_report.csv"))
    row = material[(C1, 24)]
    act = activity[(C1, 24)]
    dri = _num(row["DRI_output_site_t_y"])
    scale = _num(c5n_b[(C1, 24)]["scale_factor"])

    assert act["DRP_ACTIVE"] == "true"
    assert dri == pytest.approx(2.8e6 * scale, rel=1e-9)
    assert _num(act["DRP_raw_anchor_DRI_site_t_y"]) == pytest.approx(2.8e6, abs=1e-6)
    assert act["raw_anchor_used_as_hourly_constraint"] == "false"
    assert _num(row["pellets_to_DRP_site_t_y"]) == pytest.approx(dri * 1.351, abs=1e-6)
    assert _num(row["DRP_NG_reduction_site_GJ_y"]) == pytest.approx(dri * 8.1, abs=1e-6)
    assert _num(row["DRP_NG_process_furnace_site_GJ_y"]) == pytest.approx(dri * 1.8, abs=1e-6)
    assert _num(row["DRP_NG_total_site_GJ_y"]) == pytest.approx(_num(row["DRP_NG_reduction_site_GJ_y"]) + _num(row["DRP_NG_process_furnace_site_GJ_y"]), abs=1e-6)
    assert _num(row["DRP_electricity_site_MWh_e_y"]) == pytest.approx(dri * 0.0833, abs=1e-6)
    assert _num(row["DRP_oxygen_diagnostic_site_t_y"]) == pytest.approx(dri * 0.135, abs=1e-6)
    assert _num(row["DRP_CO2_capture_stream_site_t_y"]) == pytest.approx(dri * 0.286, abs=1e-6)


def test_pellet_burden_integration_replaces_placeholder_without_double_counting(c5o_a_outputs: Path):
    rows = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_pellet_burden_integration.csv"))
    c1 = rows[(C1, 24)]
    c0 = rows[(C0, 24)]

    assert c0["DRP_pellet_demand_double_counted"] == "false"
    assert _num(c0["used_DRP_pellet_demand_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert c1["integration_mode"] == "C5o_a_actual_DRP_input_replaces_C5n_b_context_placeholder"
    assert c1["DRP_pellet_demand_double_counted"] == "false"
    assert _num(c1["used_DRP_pellet_demand_site_t_y"]) == pytest.approx(_num(c1["C5o_a_actual_DRP_pellet_input_site_t_y"]), abs=1e-9)
    assert _num(c1["would_be_double_counted_DRP_pellet_demand_site_t_y"]) > _num(c1["used_DRP_pellet_demand_site_t_y"])
    assert c1["placeholder_match_status"] == "within_rounding_tolerance"
    assert c1["pellet_balance_with_C5o_a_DRP_input_within_tolerance"] == "true"
    assert _num(c1["pellet_gap_after_C5o_a_site_t_y"]) == pytest.approx(0.0, abs=1e-6)


def test_dri_buffer_interface_has_terminal_equality_and_no_hidden_slack(c5o_a_outputs: Path):
    buffer_rows = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_dri_buffer_interface_dashboard.csv"))
    material = _keyed(_read_csv(c5o_a_outputs / "s4_4c5o_a_drp_material_energy_ledger.csv"))
    row = buffer_rows[(C1, 24)]
    dri = _num(material[(C1, 24)]["DRI_output_site_t_y"])

    assert _num(row["DRI_buffer_capacity_t"]) == pytest.approx(2.0 * dri / 365.0, abs=1e-6)
    assert _num(row["DRI_inventory_start_t"]) == pytest.approx(0.5 * _num(row["DRI_buffer_capacity_t"]), abs=1e-6)
    assert _num(row["DRI_inventory_end_t"]) == pytest.approx(_num(row["DRI_inventory_start_t"]), abs=1e-6)
    assert _num(row["DRI_inventory_drift_t"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(row["DRI_to_future_EAF_placeholder_site_t_y"]) == pytest.approx(dri, abs=1e-6)
    assert row["temporary_DRI_to_future_EAF_interface_active"] == "true"
    assert row["EAF_NOT_YET_IMPLEMENTED_CAVEAT"] == "true"
    assert row["DRI_import_or_export_hidden_material_slack_active"] == "false"
    assert row["terminal_rule_status"] == "pass"


def test_no_wag_no_h2_no_mfrr_and_co2_guard(c5o_a_outputs: Path):
    material = _read_csv(c5o_a_outputs / "s4_4c5o_a_drp_material_energy_ledger.csv")
    activity = _read_csv(c5o_a_outputs / "s4_4c5o_a_drp_activity_report.csv")
    totals = _read_csv(c5o_a_outputs / "s4_4c5o_a_modelled_totals_delta.csv")
    for row in material:
        assert row["DRP_exportable_WAG_carrier"] == "false"
        assert _num(row["DRP_tailgas_to_BFG_COG_BOFG_site_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_useful_WAG_generation_site_MWh_y"]) == pytest.approx(0.0, abs=1e-9)
        assert _num(row["DRP_H2_input_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
        assert row["DRP_CO2_accounting_mode"] == "capture_stream_validation"
        assert row["DRP_capture_stream_added_to_direct_emissions_total"] == "false"
    for row in activity:
        assert row["DRP_HYDROGEN_ENABLED_BASE"] == "false"
        assert row["DRP_MFRR_ELIGIBLE_BASE"] == "false"
        assert row["DRP_DA_RESPONSIVE"] == "false"
    for row in totals:
        assert row["DRP_capture_stream_added_to_diagnostic_CO2_total"] == "false"
        assert row["CO2_guard_status_after_DRP"] == "pass"
        assert row["WAG_invariant_status_after_DRP"] == "pass"


def test_healthcheck_caveats_and_redflags(c5o_a_outputs: Path):
    health = _read_csv(c5o_a_outputs / "s4_4c5o_a_compact_healthcheck.csv")
    redflags = _read_csv(c5o_a_outputs / "s4_4c5o_a_red_flags.csv")
    assert len(health) == 4
    assert len(redflags) == 4
    c1_health = next(row for row in health if row["configuration"] == C1 and row["horizon_hours"] == "24")
    assert c1_health["status"] == "development_only"
    assert c1_health["thesis_usability"] == "false"
    assert c1_health["EAF_implemented_in_C5o_a"] == "false"
    assert "EAF_NOT_YET_IMPLEMENTED_CAVEAT" in c1_health["caveats"]
    assert "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT" in c1_health["caveats"]
    assert c1_health["red_flags"] == ""
    assert int(c1_health["failure_count"]) == 0

    for row in redflags:
        for key, value in row.items():
            if key.startswith("DRP_") and key not in {"DRP_CO2_CAPTURE_STREAM_VALIDATION_ONLY", "DRP_NOT_THESIS_APPROVED"}:
                assert value == "false"
        assert int(row["failure_count"]) == 0
        assert row["status"] == "pass_with_caveats"


def test_existing_c5n_b_and_c5n_a_baselines_remain_passed(c5o_a_outputs: Path):
    c5n_b_gate = json.loads((C5N_B_DIR / "s4_4c5n_b_stage_gate.json").read_text(encoding="utf-8"))
    c5n_a_gate = json.loads((C5N_A_DIR / "s4_4c5n_a_stage_gate.json").read_text(encoding="utf-8"))
    assert c5n_b_gate["decision"] == "pass_development_pellet_burden_balance_and_bulk_storage_policy"
    assert c5n_b_gate["bulk_solid_storage_capacity_mode"] == "practically_non_binding_bulk_solid_storage"
    assert c5n_a_gate["decision"] == "pass_development_pefa_pelletizing_layer"
    assert c5n_a_gate["thesis_usability"] is False
