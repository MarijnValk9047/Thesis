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
from steel.s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import (  # noqa: E402
    C5L_A_DIR,
    DOWNSTREAM_ROUTING_MODE,
    DSP_LS_SHARE,
    HOT_CHARGE_ENERGY_SAVING_STATUS,
    HSM_BUFFER_MODE,
    HSM_CO2_STATUS,
    HSM_INTERNAL_SLAB_SHARE,
    HSM_REHEAT_POLICY,
    WAG_TOL_MWH,
    run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5l_a_outputs() -> Path:
    run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch()
    return C5L_A_DIR


def test_c5l_a_required_outputs_and_stage_gate(c5l_a_outputs: Path):
    required = [
        "s4_4c5l_a_stage_gate.json",
        "s4_4c5l_a_run_registry.csv",
        "s4_4c5l_a_24h_summary.csv",
        "s4_4c5l_a_168h_summary.csv",
        "s4_4c5l_a_downstream_routing_input_rows.csv",
        "s4_4c5l_a_downstream_routing_report.csv",
        "s4_4c5l_a_hsm_buffer_scaffold_dashboard.csv",
        "s4_4c5l_a_slab_balance_dashboard.csv",
        "s4_4c5l_a_anchor_gap_dashboard.csv",
        "s4_4c5l_a_hsm_fuel_mix_dashboard.csv",
        "s4_4c5l_a_wag_generation_consumption_by_plant.csv",
        "s4_4c5l_a_wag_aggregate_invariant.csv",
        "s4_4c5l_a_lhv_consistency_checks.csv",
        "s4_4c5l_a_hsm_co2_accounting_dashboard.csv",
        "s4_4c5l_a_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5l_a_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5l_a_outputs / "s4_4c5l_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_downstream_routing_and_hsm_buffer_patch"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["DOWNSTREAM_ROUTING_MODE"] == DOWNSTREAM_ROUTING_MODE
    assert gate["DSP_LS_SHARE"] == pytest.approx(0.20)
    assert gate["HSM_INTERNAL_SLAB_SHARE"] == pytest.approx(0.80)
    assert gate["HSM_BUFFER_MODE"] == HSM_BUFFER_MODE
    assert gate["HSM_REHEAT_POLICY"] == HSM_REHEAT_POLICY
    assert gate["max_abs_downstream_material_gap_t_y"] == pytest.approx(0.0)
    assert gate["no_unbounded_slab_storage_status"] == "pass_routing_scaffold_only_no_storage_state"
    assert gate["hot_charge_energy_saving_status"] == HOT_CHARGE_ENERGY_SAVING_STATUS
    assert gate["wag_invariant_fail_count"] == 0
    assert gate["co2_double_counting_guard_status"] == "pass"
    assert gate["HSM_CO2_status"] == HSM_CO2_STATUS
    assert gate["anchor_constraints_used_count"] == 0
    assert gate["forbidden_next_plant_work_included"] is False


def test_c5l_a_policy_rows_are_explicit_and_governed(c5l_a_outputs: Path):
    rows = _read_csv(c5l_a_outputs / "s4_4c5l_a_downstream_routing_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    assert by_id["DOWNSTREAM_ROUTING_MODE"]["base_value"] == DOWNSTREAM_ROUTING_MODE
    assert _num(by_id["DSP_LS_SHARE"]["base_value"]) == pytest.approx(DSP_LS_SHARE)
    assert _num(by_id["HSM_INTERNAL_SLAB_SHARE"]["base_value"]) == pytest.approx(HSM_INTERNAL_SLAB_SHARE)
    assert by_id["HSM_BUFFER_MODE"]["base_value"] == HSM_BUFFER_MODE
    assert by_id["HSM_REHEAT_POLICY"]["base_value"] == HSM_REHEAT_POLICY
    assert by_id["HOT_CHARGE_ENERGY_SAVING_STATUS"]["base_value"] == HOT_CHARGE_ENERGY_SAVING_STATUS
    assert _num(by_id["HSM_SLAB_INPUT_T_PER_T_HRC"]["base_value"]) == pytest.approx(1.10)
    for parameter_id in ["DOWNSTREAM_ROUTING_MODE", "DSP_LS_SHARE", "HSM_INTERNAL_SLAB_SHARE", "HSM_BUFFER_MODE"]:
        row = by_id[parameter_id]
        assert row["input_status"] == "development_policy_target"
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["constraint_used"] == "false"


def test_c5l_a_80_20_routing_and_zero_material_gap(c5l_a_outputs: Path):
    report = _read_csv(c5l_a_outputs / "s4_4c5l_a_downstream_routing_report.csv")
    by_key = {(row["configuration"], row["horizon_hours"]): row for row in report}
    for horizon in ("24", "168"):
        for config in (C0, C1):
            row = by_key[(config, horizon)]
            active = _num(row["active_total_liquid_steel_target_site_t_y"])
            imported = _num(row["imported_slab_site_t_y"])
            assert row["downstream_routing_mode"] == DOWNSTREAM_ROUTING_MODE
            assert _num(row["dsp_output_site_t_y"]) == pytest.approx(active * 0.20)
            assert _num(row["internal_slab_to_hsm_site_t_y"]) == pytest.approx(active * 0.80)
            total_slab = active * 0.80 + imported
            assert _num(row["hsm_total_slab_input_site_t_y"]) == pytest.approx(total_slab)
            assert _num(row["hsm_output_site_t_y"]) == pytest.approx(total_slab / 1.10)
            assert _num(row["hsm_internal_loss_or_scrap_site_t_y"]) == pytest.approx(total_slab - total_slab / 1.10)
            assert _num(row["indicative_downstream_material_gap_site_t_y"]) == pytest.approx(0.0)

        c0 = by_key[(C0, horizon)]
        assert _num(c0["dsp_output_site_t_y"]) == pytest.approx(1_350_000.0)
        assert _num(c0["internal_slab_to_hsm_site_t_y"]) == pytest.approx(5_400_000.0)
        assert _num(c0["hsm_total_slab_input_site_t_y"]) == pytest.approx(5_400_000.0)
        assert _num(c0["hsm_output_site_t_y"]) == pytest.approx(5_400_000.0 / 1.10)

        c1 = by_key[(C1, horizon)]
        imported_c1 = 600_000.0 * 6.75 / 6.8
        assert _num(c1["imported_slab_site_t_y"]) == pytest.approx(imported_c1)
        assert _num(c1["hsm_imported_cold_slab_input_site_t_y"]) == pytest.approx(imported_c1)
        assert _num(c1["hsm_total_slab_input_site_t_y"]) == pytest.approx(5_400_000.0 + imported_c1)


def test_c5l_a_preserves_c5k_policy_and_route_split(c5l_a_outputs: Path):
    report = _read_csv(c5l_a_outputs / "s4_4c5l_a_downstream_routing_report.csv")
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

    c5k_gate = json.loads((C5K_DIR / "s4_4c5k_stage_gate.json").read_text(encoding="utf-8"))
    assert c5k_gate["decision"] == "pass_development_production_policy_and_route_split_normalisation"


def test_c5l_a_anchor_gaps_are_validation_only(c5l_a_outputs: Path):
    anchors = _read_csv(c5l_a_outputs / "s4_4c5l_a_anchor_gap_dashboard.csv")
    assert anchors
    assert all(row["constraint_used"] == "false" for row in anchors)
    assert all(row["anchor_status"] == "validation_context_only" for row in anchors)
    c0_hsm = next(row for row in anchors if row["configuration"] == C0 and row["metric"] == "HSM_rolled_coils_context_t_y" and row["horizon_hours"] == "24")
    c1_import = next(row for row in anchors if row["configuration"] == C1 and row["metric"] == "imported_slab_context_t_y" and row["horizon_hours"] == "24")
    assert _num(c0_hsm["anchor_quantity"]) == pytest.approx(5_400_000.0)
    assert _num(c0_hsm["model_site_quantity"]) == pytest.approx(5_400_000.0 / 1.10)
    assert _num(c1_import["anchor_quantity"]) == pytest.approx(600_000.0)
    assert _num(c1_import["model_site_quantity"]) == pytest.approx(600_000.0 * 6.75 / 6.8)


def test_c5l_a_buffer_scaffold_has_no_storage_and_imported_slab_is_cold(c5l_a_outputs: Path):
    rows = _read_csv(c5l_a_outputs / "s4_4c5l_a_hsm_buffer_scaffold_dashboard.csv")
    assert rows
    for row in rows:
        assert row["hsm_buffer_mode"] == HSM_BUFFER_MODE
        assert row["storage_state_created"] == "false"
        assert row["terminal_inventory_policy"] == "not_applicable_no_storage_state"
        assert row["status"] == "routing_scaffold_only_no_unbounded_storage"
        assert row["hot_charge_energy_saving_status"] == HOT_CHARGE_ENERGY_SAVING_STATUS
        assert _num(row["hsm_total_slab_input_site_t_y"]) == pytest.approx(
            _num(row["hsm_hot_slab_input_site_t_y"])
            + _num(row["hsm_cold_slab_input_site_t_y"])
            + _num(row["hsm_imported_cold_slab_input_site_t_y"])
        )
        if row["configuration"] == C1:
            assert _num(row["hsm_imported_cold_slab_input_site_t_y"]) > 0.0


def test_c5l_a_reheat_labels_are_thermal_and_no_hot_charge_saving(c5l_a_outputs: Path):
    report = _read_csv(c5l_a_outputs / "s4_4c5l_a_downstream_routing_report.csv")
    for row in report:
        assert row["hsm_reheat_policy"] == HSM_REHEAT_POLICY
        assert row["hot_charge_energy_saving_status"] == HOT_CHARGE_ENERGY_SAVING_STATUS
        assert "hsm_reheat_heat_demand_site_TWh_th_y" in row
        assert "hsm_reheat_heat_demand_site_TWh_LHV_y" in row
        assert "hsm_rolling_electricity_site_GWh_e_y" in row
        hsm_output = _num(row["hsm_output_site_t_y"])
        assert _num(row["hsm_reheat_heat_demand_site_GJ_y"]) == pytest.approx(hsm_output * 1.35)
        assert _num(row["hsm_reheat_heat_demand_site_TWh_th_y"]) == pytest.approx(hsm_output * 1.35 / 3.6 / 1_000_000.0)
        assert _num(row["hsm_rolling_electricity_site_GWh_e_y"]) == pytest.approx(hsm_output * 0.070 / 1000.0)


def test_c5l_a_wag_and_co2_guards_pass(c5l_a_outputs: Path):
    aggregate = _read_csv(c5l_a_outputs / "s4_4c5l_a_wag_aggregate_invariant.csv")
    assert aggregate
    assert all(row["status"] == "pass" for row in aggregate)
    assert all(abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH for row in aggregate)

    co2 = _read_csv(c5l_a_outputs / "s4_4c5l_a_hsm_co2_accounting_dashboard.csv")
    hsm = [row for row in co2 if row["emission_bucket"] == "HSM_reheat_CO2"]
    assert hsm
    assert all(row["derivation_status"] == HSM_CO2_STATUS for row in hsm)
    assert all(row["included_in_objective_ETS_cost"] == "false" for row in co2)

    lhv = _read_csv(c5l_a_outputs / "s4_4c5l_a_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)


def test_c5l_a_no_sinter_or_forbidden_scope(c5l_a_outputs: Path):
    gate = json.loads((c5l_a_outputs / "s4_4c5l_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["forbidden_next_plant_work_included"] is False
    for path in c5l_a_outputs.glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        assert "product revenue" not in text
        assert "export revenue" not in text
        assert "direct wag market valuation" not in text
        assert "free slab battery" not in text
