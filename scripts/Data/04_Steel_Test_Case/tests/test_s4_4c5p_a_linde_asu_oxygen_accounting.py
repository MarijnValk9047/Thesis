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
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR  # noqa: E402
from steel.s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import C5O_A_DIR  # noqa: E402
from steel.s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff import C5O_B_DIR  # noqa: E402
from steel.s4_4c5o_c_dsp_downstream_physical_layer import C5O_C_DIR  # noqa: E402
from steel.s4_4c5p_a_linde_asu_oxygen_accounting import (  # noqa: E402
    C5P_A_DIR,
    STAGE,
    run_s4_4c5p_a_linde_asu_oxygen_accounting,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/LINDE_OXYGEN_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5p_a_outputs() -> Path:
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    return C5P_A_DIR


def test_c5p_a_required_outputs_and_stage_status(c5p_a_outputs: Path):
    required = [
        "s4_4c5p_a_stage_gate.json",
        "s4_4c5p_a_run_registry.csv",
        "s4_4c5p_a_linde_development_input_rows.csv",
        "s4_4c5p_a_linde_validation_anchors.csv",
        "s4_4c5p_a_oxygen_demand_ledger.csv",
        "s4_4c5p_a_asu_electricity_ledger.csv",
        "s4_4c5p_a_oxygen_buffer_dashboard.csv",
        "s4_4c5p_a_modelled_totals_delta.csv",
        "s4_4c5p_a_coke_governance_status.csv",
        "s4_4c5p_a_plant_kpi_table.csv",
        "s4_4c5p_a_compact_healthcheck.csv",
        "s4_4c5p_a_red_flags.csv",
        "s4_4c5p_a_compact_table_for_chat.csv",
        "s4_4c5p_a_linde_asu_oxygen_accounting_report.json",
        "s4_4c5p_a_summary.json",
    ]
    for name in required:
        path = c5p_a_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5p_a_outputs / "s4_4c5p_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_linde_asu_oxygen_accounting"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["ASU_mFRR_eligible_base"] is False
    assert gate["oxygen_strategic_storage_allowed"] is False
    assert gate["N2_Ar_dry_air_active"] is False
    assert gate["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"
    assert gate["denominator_status"] == "unresolved_until_Linde_boilers_generators_complete"


def test_linde_source_card_and_development_input_rows_are_governed(c5p_a_outputs: Path):
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE" in text
    assert "LINDE_O2_BUFFER_GEOMETRIC_VOLUME_M3" in text
    assert "DRP_OXYGEN_INPUT_NM3_PER_T_DRI" in text

    rows = _read_csv(c5p_a_outputs / "s4_4c5p_a_linde_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "LINDE_ASU_OUTPUT_BASIS",
        "LINDE_PRODUCTS_SCOPE",
        "LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE",
        "LINDE_O2_DENSITY_KG_PER_NM3",
        "LINDE_O2_NM3_PER_T_O2",
        "LINDE_O2_BUFFER_GEOMETRIC_VOLUME_M3",
        "LINDE_O2_BUFFER_MODE",
        "LINDE_O2_STRATEGIC_STORAGE_ALLOWED",
        "LINDE_ASU_MFRR_ELIGIBLE_BASE",
        "BF_OXYGEN_INPUT_NM3_PER_T_HM",
        "BOF_OXYGEN_INPUT_NM3_PER_T_LS",
        "EAF_OXYGEN_INPUT_NM3_PER_T_LS",
        "DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT_ACTIVE",
        "DRP_OXYGEN_INPUT_NM3_PER_T_DRI_VENDOR_CROSSCHECK",
        "C5M_F_COKE_RECONCILIATION_BASELINE_STATUS",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["source_card"].endswith("LINDE_OXYGEN_Parameters.md")
        assert row["input_status"].startswith("development")
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["caveat"]

    assert by_id["LINDE_PRODUCTS_SCOPE"]["base_value"] == "O2 active; Ar/N2/compressed dry air deferred"
    assert by_id["LINDE_ASU_MFRR_ELIGIBLE_BASE"]["base_value"] == "false"
    assert by_id["LINDE_O2_STRATEGIC_STORAGE_ALLOWED"]["base_value"] == "false"


def test_oxygen_demand_aggregation_and_no_double_count(c5p_a_outputs: Path):
    rows = _keyed(_read_csv(c5p_a_outputs / "s4_4c5p_a_oxygen_demand_ledger.csv"))
    c5k = _keyed(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    drp = _keyed(_read_csv(C5O_A_DIR / "s4_4c5o_a_drp_material_energy_ledger.csv"))
    eaf = _keyed(_read_csv(C5O_B_DIR / "s4_4c5o_b_eaf_material_energy_ledger.csv"))

    for config in (C0, C1):
        row = rows[(config, 24)]
        key = (config, 24)
        t_per_nm3 = 1.429 / 1000.0
        bf_nm3 = _num(c5k[key]["bf_hot_metal_normalised_site_t_y"]) * 43.0
        bof_nm3 = _num(c5k[key]["bof_oxygen_input_site_Nm3_y"])
        eaf_nm3 = _num(eaf[key]["EAF_LS_output_site_t_y"]) * 35.0
        drp_t = _num(drp[key]["DRP_oxygen_diagnostic_site_t_y"])
        drp_nm3 = drp_t / t_per_nm3 if drp_t else 0.0
        total_nm3 = bf_nm3 + bof_nm3 + eaf_nm3 + drp_nm3
        assert _num(row["BF_oxygen_demand_Nm3_y"]) == pytest.approx(bf_nm3, abs=1e-6)
        assert _num(row["BOF_oxygen_demand_Nm3_y"]) == pytest.approx(bof_nm3, abs=1e-6)
        assert _num(row["EAF_oxygen_demand_Nm3_y"]) == pytest.approx(eaf_nm3, abs=1e-6)
        assert _num(row["DRP_oxygen_demand_Nm3_y"]) == pytest.approx(drp_nm3, abs=1e-6)
        assert _num(row["total_core_oxygen_demand_Nm3_y"]) == pytest.approx(total_nm3, abs=1e-6)
        assert _num(row["total_core_oxygen_demand_t_y"]) == pytest.approx(total_nm3 * t_per_nm3, abs=1e-6)
        assert row["BOF_oxygen_kg_row_not_added_separately"] == "true"
        assert row["oxygen_demand_double_counted_kg_and_Nm3"] == "false"

    assert _num(rows[(C0, 24)]["EAF_oxygen_demand_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(rows[(C0, 24)]["DRP_oxygen_demand_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(rows[(C1, 24)]["EAF_oxygen_demand_t_y"]) > 0.0
    assert _num(rows[(C1, 24)]["DRP_oxygen_demand_t_y"]) > 0.0


def test_asu_electricity_formula_and_process_scope(c5p_a_outputs: Path):
    oxygen = _keyed(_read_csv(c5p_a_outputs / "s4_4c5p_a_oxygen_demand_ledger.csv"))
    asu = _keyed(_read_csv(c5p_a_outputs / "s4_4c5p_a_asu_electricity_ledger.csv"))
    totals = _keyed(_read_csv(c5p_a_outputs / "s4_4c5p_a_modelled_totals_delta.csv"))
    prior = _keyed(_read_csv(C5O_C_DIR / "s4_4c5o_c_modelled_totals_delta.csv"))
    for config in (C0, C1):
        key = (config, 24)
        oxygen_t = _num(oxygen[key]["total_core_oxygen_demand_t_y"])
        expected_mwh = oxygen_t * 0.400
        assert _num(asu[key]["ASU_electricity_MWh_y"]) == pytest.approx(expected_mwh, abs=1e-6)
        assert _num(asu[key]["ASU_average_MW"]) == pytest.approx(expected_mwh / 8760.0, abs=1e-9)
        assert asu[key]["ASU_mFRR_eligible_base"] == "false"
        assert asu[key]["ASU_DA_price_responsive"] == "false"
        assert asu[key]["ASU_electricity_scope"] == "modelled_process_electricity_current_C5_scope_not_full_site"
        assert _num(totals[key]["process_electricity_after_Linde_ASU_MWh_e_y"]) == pytest.approx(
            _num(prior[key]["process_electricity_after_DSP_MWh_e_y"]) + expected_mwh,
            abs=1e-6,
        )
        assert totals[key]["process_electricity_scope"] == "modelled_process_electricity_current_C5_scope_not_full_site"


def test_drp_oxygen_basis_crosscheck_not_additive(c5p_a_outputs: Path):
    rows = _keyed(_read_csv(c5p_a_outputs / "s4_4c5p_a_oxygen_demand_ledger.csv"))
    c0 = rows[(C0, 24)]
    c1 = rows[(C1, 24)]
    assert c0["DRP_oxygen_basis_requires_review"] == "false"
    assert c1["DRP_oxygen_basis_requires_review"] == "true"
    assert _num(c1["DRP_active_O2_coeff_Nm3_per_t_DRI"]) == pytest.approx(94.47165850244924)
    assert _num(c1["DRP_vendor_crosscheck_O2_coeff_Nm3_per_t_DRI"]) == pytest.approx(35.0)
    assert _num(c1["DRP_project_minus_vendor_O2_demand_t_y"]) > 0.0
    assert c1["DRP_project_and_vendor_added_together"] == "false"


def test_oxygen_buffer_is_balancing_only_not_storage_flex(c5p_a_outputs: Path):
    rows = _read_csv(c5p_a_outputs / "s4_4c5p_a_oxygen_buffer_dashboard.csv")
    for row in rows:
        assert row["O2_buffer_mode"] == "balancing_buffer_only"
        assert row["O2_buffer_geometric_volume_m3"] == "1670.0"
        assert row["O2_buffer_geometric_volume_status"] == "structural_anchor_only_not_model_ready_Nm3_capacity"
        assert row["O2_buffer_pressure_assumption_available"] == "false"
        assert row["O2_buffer_usable_capacity_Nm3"] == ""
        assert row["O2_buffer_terminal_status"] == "pass"
        assert row["O2_buffer_used_as_strategic_storage"] == "false"
        assert row["O2_buffer_strategic_storage_allowed"] == "false"
        assert row["O2_buffer_capacity_binds"] == "false"


def test_coke_governance_patch_and_denominator_status(c5p_a_outputs: Path):
    coke = _read_csv(c5p_a_outputs / "s4_4c5p_a_coke_governance_status.csv")
    assert len(coke) == 1
    assert coke[0]["current_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"
    assert coke[0]["external_unmodelled_coke_status"] == "fallback_only_not_active_baseline"
    assert coke[0]["thesis_usability"] == "false"
    assert coke[0]["equation_change_in_C5p_a"] == "false"

    health = _read_csv(c5p_a_outputs / "s4_4c5p_a_compact_healthcheck.csv")
    assert health
    for row in health:
        assert row["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"
        assert row["external_unmodelled_coke_status"] == "fallback_only_not_active_baseline"
        assert row["denominator_status"] == "unresolved_until_Linde_boilers_generators_complete"


def test_no_baseline_disturbance_and_red_flags_false(c5p_a_outputs: Path):
    health = _read_csv(c5p_a_outputs / "s4_4c5p_a_compact_healthcheck.csv")
    redflags = _read_csv(c5p_a_outputs / "s4_4c5p_a_red_flags.csv")
    c5l_d = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for row in health:
        key = (row["configuration"], int(row["horizon_hours"]))
        assert row["baseline_BOF_liquid_steel_site_t_y"]
        assert row["baseline_EAF_LS_output_site_t_y"]
        assert row["baseline_DSP_output_site_t_y"]
        assert row["HSM_heat_case"] == "base_0_50"
        assert c5l_d[key]["active_cap_case"] == "base_0_50"
        assert row["WAG_invariant_status_after_Linde_ASU"] == "pass"
        assert row["LHV_consistency_status_after_Linde_ASU"] == "pass"
        assert row["CO2_guard_status_after_Linde_ASU"] == "pass"

    failure_columns = [
        "LINDE_ASU_ACTIVE_WITHOUT_OXYGEN_DEMAND",
        "OXYGEN_DEMAND_DOUBLE_COUNTED_KG_AND_NM3",
        "OXYGEN_FREE_SUPPLY_WITHOUT_ASU_ELECTRICITY",
        "ASU_ELECTRICITY_MISSING",
        "O2_BUFFER_USED_AS_STRATEGIC_STORAGE",
        "O2_BUFFER_HAS_USABLE_NM3_FROM_GEOMETRIC_VOLUME_WITHOUT_PRESSURE_ASSUMPTION",
        "ASU_MFRR_ENABLED_IN_BASE",
        "LINDE_N2_ARGON_DRY_AIR_ACTIVE_IN_FIRST_O2_LAYER",
        "DRP_OXYGEN_BOTH_PROJECT_AND_VENDOR_ADDED",
        "BOF_DRP_EAF_BF_OUTPUTS_CHANGED_BY_LINDE_LAYER",
        "HSM_BASE_0_50_REVERTED",
        "COKE_RECONCILIATION_BASELINE_REOPENED",
        "DENOMINATOR_SILENTLY_FROZEN",
    ]
    for row in redflags:
        assert row["failure_count"] == "0"
        assert row["status"] == "pass_with_caveats"
        for column in failure_columns:
            assert row[column] == "false", (row["configuration"], row["horizon_hours"], column)
        assert row["O2_BUFFER_PRESSURE_NOT_SOURCE_BACKED"] == "true"
        assert row["LINDE_ASU_ELECTRICITY_NOT_FULL_SITE_ELECTRICITY"] == "true"
        assert row["DENOMINATOR_UNRESOLVED_UNTIL_UTILITIES_COMPLETE"] == "true"
        assert row["N2_ARGON_DRY_AIR_DEFERRED"] == "true"
