from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import C0, C1, WAG_TOL_MWH  # noqa: E402
from steel.s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR  # noqa: E402
from steel.s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR  # noqa: E402
from steel.s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR  # noqa: E402
from steel.s4_4c5m_sinter_minimal_parameterisation import (  # noqa: E402
    C5M_DIR,
    SINTER_PER_T_HOT_METAL_C0,
    SINTER_PER_T_HOT_METAL_C1,
)
from steel.s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics import (  # noqa: E402
    C5M_A_DIR,
    HEALTHCHECK_SECTIONS,
    SINTER_C0_COUPLING_MODE,
    SINTER_C1_COUPLING_MODE,
    run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5m_a_outputs() -> Path:
    run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics()
    return C5M_A_DIR


def test_c5m_a_required_outputs_and_stage_status(c5m_a_outputs: Path):
    required = [
        "s4_4c5m_a_stage_gate.json",
        "s4_4c5m_a_run_registry.csv",
        "s4_4c5m_a_healthcheck.csv",
        "s4_4c5m_a_healthcheck.json",
        "s4_4c5m_a_change_detection.csv",
        "s4_4c5m_a_compact_table_for_chat.csv",
        "s4_4c5m_a_summary.json",
    ]
    for filename in required:
        path = c5m_a_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
        else:
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5m_a_outputs / "s4_4c5m_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_sinter_coupling_caveat_and_model_health_diagnostics"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["warning_count"] == 0
    assert gate["redflag_count"] == 0


def test_c5m_a_sinter_coupling_caveat_fields(c5m_a_outputs: Path):
    rows = _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    assert rows
    for row in rows:
        assert row["SINTER_C0_COUPLING_MODE"] == SINTER_C0_COUPLING_MODE
        assert row["SINTER_C1_COUPLING_MODE"] == SINTER_C1_COUPLING_MODE
        assert row["SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE"] == "false"
        assert row["SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING"] == "true"
        assert row["SINTER_C0_RATIO_FORMULA"] == "3.7 / 6.3"
        assert row["SINTER_C1_RATIO_FORMULA"] == "2.8 / 2.8"
        assert _num(row["SINTER_C0_RATIO_VALUE"]) == pytest.approx(SINTER_PER_T_HOT_METAL_C0, abs=1e-6)
        assert _num(row["SINTER_C1_RATIO_VALUE"]) == pytest.approx(SINTER_PER_T_HOT_METAL_C1, abs=1e-9)
        assert "site-average BF6+BF7" in row["sinter_coupling_caveat"]
        assert "retained-BF6" in row["sinter_coupling_caveat"]
        assert "not basecase" in row["sinter_coupling_warning_c1_lower_ratio"]


def test_c5m_a_healthcheck_major_sections_and_required_fields(c5m_a_outputs: Path):
    rows = _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    required_fields = {
        "stage_id",
        "dependency_chain",
        "thesis_usability",
        "solver_status",
        "failure_count",
        "warning_count",
        "anchor_constraints_used",
        "active_hsm_heat_case",
        "active_production_target_site_t_y",
        "active_C1_route_split",
        "total_liquid_steel_target_site_t_y",
        "bof_liquid_steel_site_t_y",
        "eaf_liquid_steel_site_t_y",
        "bf_hot_metal_site_t_y",
        "sinter_output_site_t_y",
        "hsm_output_site_t_y",
        "dsp_output_site_t_y",
        "final_product_proxy_hsm_plus_dsp_site_t_y",
        "sinter_iron_ore_bus0_input_site_t_y",
        "hsm_slab_input_site_t_y",
        "total_modelled_process_electricity_site_MWh_e_y",
        "hsm_reheat_site_TWh_th_y",
        "sinter_gas_demand_site_MWh_LHV_y",
        "sinter_steam_demand_site_t_y",
        "BFG_gross_generated_site_MWh_y",
        "COG_gross_generated_site_MWh_y",
        "BOFG_gross_generated_site_MWh_y",
        "BF_hot_stove_BFG_use_site_MWh_y",
        "KGF_COG_self_use_site_MWh_y",
        "BF_aggregate_CO2_site_t_y",
        "BOF_direct_CO2_diagnostic_site_t_y",
        "Sinter_aggregate_CO2_diagnostic_site_t_y",
        "total_modelled_aggregate_direct_CO2_diagnostic_site_t_y",
    }
    for row in rows:
        assert required_fields.issubset(row.keys())
        assert set(row["major_sections_present"].split(";")) == set(HEALTHCHECK_SECTIONS)

    health_json = json.loads((c5m_a_outputs / "s4_4c5m_a_healthcheck.json").read_text(encoding="utf-8"))
    assert set(health_json["healthcheck_sections"]) == set(HEALTHCHECK_SECTIONS)
    assert len(health_json["rows"]) == len(rows)


def test_c5m_a_red_flags_are_present_and_false(c5m_a_outputs: Path):
    rows = _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    expected_flags = {
        "redflag_anchor_constraint_used",
        "redflag_wag_invariant_failed",
        "redflag_lhv_failed",
        "redflag_co2_double_counting_failed",
        "redflag_negative_inventory",
        "redflag_unserved_process_energy",
        "redflag_bf_hot_metal_surplus_nonzero",
        "redflag_downstream_material_gap_nonzero",
        "redflag_sinter_wag_production_present",
        "redflag_sinter_bfg_or_bofg_use_present",
        "redflag_hsm_reheat_labelled_as_electricity",
        "redflag_steam_reporting_only_instead_of_active_proxy",
        "redflag_c5k_targets_changed",
        "redflag_c5j_bof_coefficients_changed",
        "redflag_c5l_d_hsm_heat_case_changed",
    }
    for row in rows:
        assert expected_flags.issubset(row.keys())
        assert all(row[flag] == "false" for flag in expected_flags)
        assert _num(row["failure_count"]) == 0.0


def test_c5m_a_preserves_c5m_numerical_outputs(c5m_a_outputs: Path):
    health = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    }
    c5m_report = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5M_DIR / "s4_4c5m_sinter_report.csv")
    }
    c5m_controller = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")
    }
    c5m_steam = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5M_DIR / "s4_4c5m_sinter_steam_proxy_dashboard.csv")
    }
    for key, row in health.items():
        old = c5m_report[key]
        ctrl = c5m_controller[key]
        steam = c5m_steam[key]
        assert _num(row["sinter_output_site_t_y"]) == pytest.approx(_num(old["sinter_output_site_t_y"]), abs=0.01)
        assert _num(row["sinter_iron_ore_bus0_input_site_t_y"]) == pytest.approx(_num(old["sinter_iron_ore_bus0_input_site_t_y"]), abs=0.01)
        assert _num(row["sinter_gas_demand_site_MWh_LHV_y"]) == pytest.approx(_num(ctrl["sinter_gas_demand_site_MWh_y"]), abs=WAG_TOL_MWH)
        assert _num(row["sinter_steam_demand_site_t_y"]) == pytest.approx(_num(steam["sinter_steam_demand_site_t_y"]), abs=0.01)
        assert _num(row["Sinter_aggregate_CO2_diagnostic_site_t_y"]) == pytest.approx(_num(old["sinter_aggregate_CO2_site_t_y"]), abs=0.1)

    change = _read_csv(c5m_a_outputs / "s4_4c5m_a_change_detection.csv")
    assert all(row["status"] == "pass" for row in change)
    assert all(abs(_num(row["delta_value"])) <= max(1.0, WAG_TOL_MWH) for row in change)


def test_c5m_a_preserves_c5k_c5j_and_c5l_d_context(c5m_a_outputs: Path):
    rows = _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    c5k = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")
    }
    for row in rows:
        key = (row["configuration"], row["horizon_hours"])
        assert _num(row["total_liquid_steel_target_site_t_y"]) == pytest.approx(_num(c5k[key]["active_total_liquid_steel_target_site_t_y"]), abs=0.01)
        assert _num(row["active_production_target_site_t_y"]) == pytest.approx(6_750_000.0)
    assert _num(c5k[(C1, "24")]["bof_liquid_steel_site_t_y"]) == pytest.approx(3_400_000.0)
    assert _num(c5k[(C1, "24")]["eaf_liquid_steel_site_t_y"]) == pytest.approx(3_350_000.0)

    c5j_inputs = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    c5j_by_id = {row["parameter_id"]: row for row in c5j_inputs}
    assert _num(c5j_by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C0"]["base_value"]) == pytest.approx(0.208)
    assert _num(c5j_by_id["BOF_SCRAP_INPUT_T_PER_T_LS_C1"]["base_value"]) == pytest.approx(0.294)
    assert _num(c5j_by_id["BOF_BOFG_OUTPUT_NM3_PER_T_LS"]["base_value"]) == pytest.approx(75.0)

    c5l_d = {
        (row["configuration"], row["horizon_hours"]): row
        for row in _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
        if row["cap_case"] == "base_0_50"
    }
    for row in rows:
        key = (row["configuration"], row["horizon_hours"])
        assert row["active_hsm_heat_case"] == "base_0_50"
        assert _num(row["hsm_reheat_site_TWh_th_y"]) == pytest.approx(_num(c5l_d[key]["hsm_reheat_heat_site_TWh_th_y"]), abs=1e-9)


def test_c5m_a_sinter_wag_steam_and_guard_status(c5m_a_outputs: Path):
    rows = _read_csv(c5m_a_outputs / "s4_4c5m_a_healthcheck.csv")
    for row in rows:
        assert row["WAG_invariant_status"] == "pass"
        assert row["LHV_consistency_status"] == "pass"
        assert row["CO2_double_counting_guard_status"] == "pass"
        assert row["active_fuel_combustion_CO2_double_count_risk_flag"] == "false"
        assert row["negative_inventory_flags"] == "false"
        assert _num(row["steam_unserved_site_t_y"]) == 0.0
        assert _num(row["NG_to_HSM_site_MWh_y"]) == 0.0
        assert _num(row["NG_to_Sinter_site_MWh_y"]) == 0.0
        assert _num(row["HSM_unserved_reheat_site_MWh_y"]) == 0.0
        assert _num(row["Sinter_gas_unserved_site_MWh_y"]) == 0.0
        assert _num(row["COG_to_Sinter_site_MWh_y"]) == pytest.approx(_num(row["sinter_gas_demand_site_MWh_LHV_y"]), abs=WAG_TOL_MWH)
        assert row["C1_Sinter_operational_band_used_as_ramp_constraint"] == "false"
