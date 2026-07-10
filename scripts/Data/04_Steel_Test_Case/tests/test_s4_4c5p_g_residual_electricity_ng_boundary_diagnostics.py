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
from steel.s4_4c5p_g_residual_electricity_ng_boundary_diagnostics import (  # noqa: E402
    C5P_A_DIR,
    C5P_B_DIR,
    C5P_C_DIR,
    C5P_D_DIR,
    C5P_E_DIR,
    C5P_F_DIR,
    C5P_G_DIR,
    DECISION_COLUMNS,
    ELECTRICITY_ANCHOR_COLUMNS,
    ELECTRICITY_BOUNDARY_COLUMNS,
    ELECTRICITY_COMPONENT_COLUMNS,
    ELECTRICITY_POLICY_COLUMNS,
    NG_ANCHOR_COLUMNS,
    NG_BOUNDARY_COLUMNS,
    NG_COMPONENT_COLUMNS,
    NG_POLICY_COLUMNS,
    REDFLAG_COLUMNS,
    REPORT_PATH,
    run_s4_4c5p_g_residual_electricity_ng_boundary_diagnostics,
)


REQUIRED_FILES = {
    "c5_residual_electricity_component_balance.csv": ELECTRICITY_COMPONENT_COLUMNS,
    "c5_residual_electricity_boundary_matrix.csv": ELECTRICITY_BOUNDARY_COLUMNS,
    "c5_residual_electricity_anchor_gap_options.csv": ELECTRICITY_ANCHOR_COLUMNS,
    "c5_residual_electricity_policy_options.csv": ELECTRICITY_POLICY_COLUMNS,
    "c5_residual_ng_component_balance.csv": NG_COMPONENT_COLUMNS,
    "c5_residual_ng_boundary_matrix.csv": NG_BOUNDARY_COLUMNS,
    "c5_residual_ng_anchor_gap_options.csv": NG_ANCHOR_COLUMNS,
    "c5_residual_ng_policy_options.csv": NG_POLICY_COLUMNS,
    "c5_residual_energy_boundary_decision_register.csv": DECISION_COLUMNS,
    "c5_residual_energy_boundary_red_flags.csv": REDFLAG_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5p_g_outputs() -> Path:
    run_s4_4c5p_g_residual_electricity_ng_boundary_diagnostics()
    return C5P_G_DIR


def test_c5p_g_outputs_parse_and_have_required_columns(c5p_g_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_g_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    for name in ["s4_4c5p_g_stage_gate.json", "s4_4c5p_g_summary.json"]:
        json.loads((c5p_g_outputs / name).read_text(encoding="utf-8"))
    assert _read_csv(c5p_g_outputs / "s4_4c5p_g_run_registry.csv")
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_g_outputs / "s4_4c5p_g_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_residual_electricity_ng_boundary_diagnostics"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["residual_electricity_load_active"] is False
    assert gate["residual_ng_load_active"] is False
    assert gate["economics_readiness"] == "NO_GO"
    assert gate["DA_readiness"] == "NO_GO"


def test_c5p_g_preserves_current_c5_stage_metrics(c5p_g_outputs: Path):
    gate = json.loads((c5p_g_outputs / "s4_4c5p_g_stage_gate.json").read_text(encoding="utf-8"))
    p_f_gate = json.loads((C5P_F_DIR / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8"))
    p_e_gate = json.loads((C5P_E_DIR / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8"))
    p_d_gate = json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8"))

    assert gate["denominator_status"] == p_f_gate["denominator_status"]
    assert p_f_gate["recommended_denominator_policy"] == "dual_reporting_primary_active_LS_target_secondary_final_product_proxy_diagnostic_not_frozen"
    assert p_e_gate["C0_generator_2TWh_gap_TWh_y"] == pytest.approx(0.067665, abs=1e-6)
    assert p_e_gate["C1_generator_fuel_gap_PJ_y"] == pytest.approx(4.763389, abs=1e-6)
    assert p_d_gate["C1_24h_DRI_buffer_capacity_t"] == pytest.approx(15229.652603, abs=1e-6)

    p_c = _keyed(_read_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv"))
    assert p_c[(C1, 24)]["generator_electricity_value_mode"] == "offset_site_grid_import"
    assert p_c[(C1, 24)]["DA_market_revenue_active"] == "false"
    assert p_c[(C1, 24)]["export_revenue_enabled_base"] == "false"

    p_b = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv"))
    assert _num(p_b[(C0, 24)]["total_steam_demand_t_y"]) == pytest.approx(356130.613099, abs=1e-6)
    assert _num(p_b[(C1, 24)]["total_unserved_steam_t_y"]) == pytest.approx(0.0, abs=1e-9)

    p_a = _keyed(_read_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv"))
    assert _num(p_a[(C1, 24)]["total_core_oxygen_demand_t_y"]) == pytest.approx(982143.7312, abs=1e-6)
    assert p_a[(C1, 24)]["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"


def test_electricity_boundary_exposes_c0_over_offset_without_full_site_claim(c5p_g_outputs: Path):
    matrix = {row["configuration"]: row for row in _read_csv(c5p_g_outputs / "c5_residual_electricity_boundary_matrix.csv")}
    c0 = matrix[C0]
    c1 = matrix[C1]

    assert _num(c0["gross_modelled_process_demand_twh"]) == pytest.approx(1.742724, abs=1e-6)
    assert _num(c0["wag_generator_offset_twh"]) == pytest.approx(2.067665, abs=1e-6)
    assert _num(c0["modelled_exposure_pre_floor_twh"]) == pytest.approx(-0.324941, abs=1e-6)
    assert _num(c0["modelled_exposure_post_floor_twh"]) == pytest.approx(0.0, abs=1e-9)
    assert c0["residual_electricity_load_active"] == "false"
    assert c0["full_site_net_import_claimed"] == "false"

    assert _num(c1["gross_modelled_process_demand_twh"]) == pytest.approx(3.03375, abs=1e-6)
    assert _num(c1["modelled_exposure_post_floor_twh"]) == pytest.approx(2.098472, abs=1e-6)
    assert c1["full_site_net_import_claimed"] == "false"

    components = _read_csv(c5p_g_outputs / "c5_residual_electricity_component_balance.csv")
    classes = {row["component_class"] for row in components}
    assert {"modelled_demand", "internal_offset_or_reporting_generation", "context_anchor", "validation_anchor", "residual_missing"} <= classes
    c0_residual = next(row for row in components if row["configuration"] == C0 and row["electricity_component"] == "residual_electricity_load_missing")
    assert c0_residual["included_in_current_modelled_process_demand"] == "false"


def test_electricity_anchors_are_context_or_validation_only(c5p_g_outputs: Path):
    anchors = _read_csv(c5p_g_outputs / "c5_residual_electricity_anchor_gap_options.csv")
    by_id = {(row["configuration"], row["anchor_id"]): row for row in anchors}
    assert by_id[(C0, "current_tata_average_power_360MW")]["anchor_role"] == "context_anchor"
    assert by_id[(C0, "current_total_site_consumption_3TWh")]["option_status"] == "not_active"
    assert by_id[(C0, "current_vattenfall_residual_gas_electricity_2TWh")]["anchor_role"] == "validation_anchor"
    assert by_id[(C0, "current_vattenfall_residual_gas_electricity_2TWh")]["residual_load_option_id"] == "not_residual_load"
    assert all(row["option_status"] == "not_active" for row in anchors)


def test_ng_boundary_components_are_component_level_only(c5p_g_outputs: Path):
    matrix = {row["configuration"]: row for row in _read_csv(c5p_g_outputs / "c5_residual_ng_boundary_matrix.csv")}
    c0 = matrix[C0]
    c1 = matrix[C1]

    assert _num(c0["total_modelled_ng_pj"]) == pytest.approx(0.0, abs=1e-9)
    assert c0["residual_ng_load_active"] == "false"
    assert c0["full_site_ng_claimed"] == "false"
    assert _num(c1["drp_ng_pj"]) == pytest.approx(27.516175, abs=1e-6)
    assert _num(c1["eaf_ng_pj"]) == pytest.approx(0.1675, abs=1e-6)
    assert _num(c1["generator_ng_pj"]) == pytest.approx(4.1, abs=1e-6)
    assert _num(c1["boiler_steam_ng_pj"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(c1["pefa_ng_pj"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(c1["total_modelled_ng_pj"]) == pytest.approx(31.783675, abs=1e-6)
    assert c1["full_site_ng_claimed"] == "false"

    components = _read_csv(c5p_g_outputs / "c5_residual_ng_component_balance.csv")
    assert any(row["ng_component"] == "residual_or_unmodelled_NG_missing" and row["included_in_current_modelled_ng"] == "false" for row in components)
    assert any(row["ng_component"] == "boiler_steam_NG_backup" and row["annual_value_pj"] == "0" for row in components)
    assert any(row["ng_component"] == "PEFA_NG_backup" and row["annual_value_pj"] == "0" for row in components)


def test_residual_policy_options_are_registered_not_applied(c5p_g_outputs: Path):
    electricity_options = {row["option_id"]: row for row in _read_csv(c5p_g_outputs / "c5_residual_electricity_policy_options.csv")}
    ng_options = {row["option_id"]: row for row in _read_csv(c5p_g_outputs / "c5_residual_ng_policy_options.csv")}
    assert electricity_options["E"]["recommended_status"] == "recommended_next_implementation_path"
    assert electricity_options["B"]["recommended_status"] == "not_recommended_without_source_review"
    assert ng_options["E"]["recommended_status"] == "recommended_current_policy"
    assert ng_options["B"]["recommended_status"] == "preferred_if_evidence_is_available"

    decisions = {row["decision_id"]: row for row in _read_csv(c5p_g_outputs / "c5_residual_energy_boundary_decision_register.csv")}
    assert decisions["DEC_RESIDUAL_ELECTRICITY_POLICY"]["must_fix_before_economics"] == "true"
    assert decisions["DEC_RESIDUAL_NG_POLICY"]["must_fix_before_co2"] == "true"
    assert decisions["DEC_ECONOMICS_DA_READINESS"]["current_status"] == "NO_GO"


def test_red_flags_absent_and_boundary_caveats_present(c5p_g_outputs: Path):
    rows = _read_csv(c5p_g_outputs / "c5_residual_energy_boundary_red_flags.csv")
    failures = [row for row in rows if row["severity"] == "failure"]
    caveats = [row for row in rows if row["severity"] == "caveat"]
    assert failures
    assert all(row["active"] == "false" for row in failures)
    active_caveats = {row["red_flag"] for row in caveats if row["active"] == "true"}
    assert {
        "RESIDUAL_ELECTRICITY_NG_DIAGNOSTIC_ONLY",
        "ELECTRICITY_BOUNDARY_INCOMPLETE",
        "NG_BOUNDARY_INCOMPLETE",
        "C0_ELECTRICITY_OVER_OFFSET_OR_ZERO_EXPOSURE_REQUIRES_POLICY",
        "ECONOMICS_NO_GO",
        "NOT_THESIS_APPROVED",
    } <= active_caveats
