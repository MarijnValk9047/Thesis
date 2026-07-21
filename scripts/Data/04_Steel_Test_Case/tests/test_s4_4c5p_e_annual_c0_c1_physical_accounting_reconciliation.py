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
from steel.s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation import (  # noqa: E402
    ANCHOR_COLUMNS,
    BUFFER_COLUMNS,
    C5P_A_DIR,
    C5P_B_DIR,
    C5P_C_DIR,
    C5P_D_DIR,
    C5P_E_DIR,
    CO2_COLUMNS,
    CONFIG_COLUMNS,
    DECISION_COLUMNS,
    ELECTRICITY_COLUMNS,
    FAILURE_FLAGS,
    FLOW_COLUMNS,
    LEVER_COLUMNS,
    NG_COLUMNS,
    REDFLAG_COLUMNS,
    REPORT_PATH,
    WAG_LEDGER_COLUMNS,
    run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation,
)


REQUIRED_FILES = {
    "c5_annual_anchor_reconciliation_matrix.csv": ANCHOR_COLUMNS,
    "c5_annual_config_comparison.csv": CONFIG_COLUMNS,
    "c5_annual_flow_balance_by_carrier.csv": FLOW_COLUMNS,
    "c5_annual_wag_ledger_point_reconciliation.csv": WAG_LEDGER_COLUMNS,
    "c5_annual_electricity_boundary_diagnostics.csv": ELECTRICITY_COLUMNS,
    "c5_annual_ng_boundary_diagnostics.csv": NG_COLUMNS,
    "c5_annual_co2_boundary_diagnostics.csv": CO2_COLUMNS,
    "c5_annual_buffer_store_summary.csv": BUFFER_COLUMNS,
    "c5_candidate_parameter_levers.csv": LEVER_COLUMNS,
    "c5_annual_reconciliation_decision_register.csv": DECISION_COLUMNS,
    "c5_annual_reconciliation_red_flags.csv": REDFLAG_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5p_e_outputs() -> Path:
    run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation()
    return C5P_E_DIR


def test_c5p_e_outputs_parse_and_have_required_columns(c5p_e_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_e_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    for name in ["s4_4c5p_e_stage_gate.json", "s4_4c5p_e_summary.json"]:
        json.loads((c5p_e_outputs / name).read_text(encoding="utf-8"))
    assert _read_csv(c5p_e_outputs / "s4_4c5p_e_run_registry.csv")
    assert REPORT_PATH.exists()

    gate = json.loads((c5p_e_outputs / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_annual_reconciliation_diagnostic"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["failure_count"] == 0
    assert gate["denominator_status"] == "unresolved_until_residual_loads_and_boundary_complete"
    assert gate["electricity_accounting_status"] == "internal_offset_or_reporting_only_not_DA_market_revenue"
    assert gate["electricity_boundary_status"] == "incomplete_reporting_only_not_full_site_net_import"
    assert gate["ng_boundary_status"] == "incomplete_no_full_site_NG_claim"
    assert gate["co2_boundary_status"] == "component_diagnostic_only_not_ETS_ready"


def test_anchor_roles_are_context_or_validation_not_constraints(c5p_e_outputs: Path):
    rows = _read_csv(c5p_e_outputs / "c5_annual_anchor_reconciliation_matrix.csv")
    by_id = {(row["anchor_id"], row["configuration"]): row for row in rows}

    c0_2twh = by_id[("current_vattenfall_residual_gas_electricity_context", C0)]
    assert c0_2twh["anchor_role"] == "validation_anchor"
    assert c0_2twh["interpretation"] == "expected_due_to_validation_anchor_not_input"
    assert "not enforced" in c0_2twh["caveat"]

    c0_power = by_id[("current_tata_average_power_context", C0)]
    assert c0_power["anchor_role"] == "context_anchor"
    assert c0_power["raw_source_anchor"] == "360"

    c0_770 = by_id[("transferred_power_plants_total_capacity_context", C0)]
    assert c0_770["anchor_role"] == "context_anchor"
    assert c0_770["raw_source_anchor"] == "770"
    assert "not VN25/IJ01 unit capacity" in c0_770["caveat"]

    for row in rows:
        assert row["current_status"] != "executable_constraint_without_interpretation"
        assert row["anchor_role"] != "hourly_dispatch_schedule"


def test_domain_coverage_and_c0_c1_presence(c5p_e_outputs: Path):
    rows = _read_csv(c5p_e_outputs / "c5_annual_anchor_reconciliation_matrix.csv")
    domains = {row["domain"] for row in rows}
    assert {
        "production_downstream",
        "materials",
        "coke_sinter",
        "electricity",
        "oxygen_asu",
        "boiler_steam",
        "generator_wag",
        "natural_gas",
        "co2",
        "buffers_stores",
    } <= domains
    assert {C0, C1} <= {row["configuration"] for row in rows}

    flow = _read_csv(c5p_e_outputs / "c5_annual_flow_balance_by_carrier.csv")
    for config in [C0, C1]:
        carriers = {row["carrier"] for row in flow if row["configuration"] == config}
        assert {"BFG", "BOFG", "COG", "NG", "WAG_total_reporting_only"} <= carriers


def test_wag_ledger_points_keep_source_and_controller_scopes_separate(c5p_e_outputs: Path):
    flow = _read_csv(c5p_e_outputs / "c5_annual_flow_balance_by_carrier.csv")
    ledger = _read_csv(c5p_e_outputs / "c5_annual_wag_ledger_point_reconciliation.csv")
    by_flow = {(row["configuration"], row["carrier"]): row for row in flow}

    for row in ledger:
        key = (row["configuration"], row["carrier"])
        assert row["ledger_contract_status"] == "historical_cross_stage_scope_not_single_closed_chain"
        assert _num(row["source_gross_generation_MWh_LHV_y"]) >= _num(row["network_available_after_self_use_MWh_LHV_y"])
        assert _num(row["source_gross_generation_MWh_LHV_y"]) == pytest.approx(
            _num(row["mandatory_source_self_use_MWh_LHV_y"])
            + _num(row["network_available_after_self_use_MWh_LHV_y"]),
            abs=1e-6,
        )
        assert _num(row["c5p_e_controller_reconciled_supply_before_steam_MWh_LHV_y"]) == pytest.approx(
            _num(by_flow[key]["generated_or_supplied"]), abs=1e-6
        )
        assert by_flow[key]["ledger_point"] == "controller_reconciled_supply_before_steam_not_source_generation"


def test_c5_baseline_preservation_snapshots(c5p_e_outputs: Path):
    gate = json.loads((c5p_e_outputs / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["C0_final_product_proxy_t_y"] == pytest.approx(6259090.90891, abs=1e-6)
    assert gate["C1_final_product_proxy_t_y"] == pytest.approx(6800534.76175, abs=1e-6)
    assert gate["C0_generator_electricity_TWh_y"] == pytest.approx(2.067665, abs=1e-6)
    assert gate["C0_generator_2TWh_gap_TWh_y"] == pytest.approx(0.067665, abs=1e-6)
    assert gate["C1_generator_fuel_gap_PJ_y"] == pytest.approx(4.763389, abs=1e-6)

    p_d_gate = json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8"))
    assert p_d_gate["C1_24h_DRI_buffer_capacity_t"] == pytest.approx(15229.652603, abs=1e-6)
    assert p_d_gate["C1_24h_DRI_inventory_drift_t"] == pytest.approx(0.0, abs=1e-9)

    p_c = _keyed(_read_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv"))
    assert _num(p_c[(C1, 24)]["generator_fuel_gap_unserved_PJ_y"]) == pytest.approx(4.763389, abs=1e-6)
    assert p_c[(C1, 24)]["denominator_status"] == "unresolved_until_residual_loads_and_boundary_complete"

    p_b = _keyed(_read_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv"))
    assert _num(p_b[(C0, 24)]["total_steam_demand_t_y"]) == pytest.approx(356130.613099, abs=1e-6)
    assert _num(p_b[(C0, 24)]["total_unserved_steam_t_y"]) == pytest.approx(0.0, abs=1e-9)

    p_a = _keyed(_read_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv"))
    assert _num(p_a[(C1, 24)]["total_core_oxygen_demand_t_y"]) == pytest.approx(982143.7312, abs=1e-6)
    assert p_a[(C1, 24)]["coke_reconciliation_baseline_status"] == "C5m_f_bounded_coke_reconciliation_active_development_baseline"


def test_gap_classification_and_major_issues_visible(c5p_e_outputs: Path):
    rows = _read_csv(c5p_e_outputs / "c5_annual_anchor_reconciliation_matrix.csv")
    assert all(row["interpretation"] for row in rows)
    assert all(row["candidate_parameter_lever_ids"] for row in rows)

    c1_gap = next(
        row for row in rows
        if row["anchor_id"] == "generator_fuel_gap" and row["configuration"] == C1
    )
    assert _num(c1_gap["model_output"]) == pytest.approx(4.763389, abs=1e-6)
    assert c1_gap["interpretation"] == "requires_source_review"

    final_rows = [row for row in rows if "final_product_proxy" in row["anchor_id"]]
    assert final_rows
    assert any(row["interpretation"] == "expected_due_to_boundary_scope" for row in final_rows)

    decisions = {row["decision_id"]: row for row in _read_csv(c5p_e_outputs / "c5_annual_reconciliation_decision_register.csv")}
    assert decisions["DEC_PROD_DENOMINATOR"]["current_status"] == "unresolved"
    assert decisions["DEC_C1_GENERATOR_GAP"]["current_status"] == "explicit_gap_reported"


def test_candidate_parameter_levers_are_register_only(c5p_e_outputs: Path):
    rows = _read_csv(c5p_e_outputs / "c5_candidate_parameter_levers.csv")
    lever_ids = {row["lever_id"] for row in rows}
    assert {
        "LEV_PROD_DENOMINATOR_ROUTE_SCALING",
        "LEV_DRP_OXYGEN_BASIS_REVIEW",
        "LEV_C1_GENERATOR_ANCHOR_INTERPRETATION",
        "LEV_ELECTRICITY_RESIDUAL_BOUNDARY",
        "LEV_NG_RESIDUAL_BOUNDARY",
        "LEV_CO2_BOUNDARY_AND_FACTORS",
        "LEV_BUFFER_STORE_SENSITIVITY_REGISTER",
        "LEV_DISABLE_FORBIDDEN_MARKET_FEATURES",
    } <= lever_ids
    assert all(row["expected_direction_if_increased"] for row in rows)
    assert all(row["expected_direction_if_decreased"] for row in rows)
    assert all(row["review_priority"] for row in rows)
    assert all(row["sensitivity_required"] in {"true", "false"} for row in rows)
    assert all(row["can_be_changed_before_commit"] == "false" for row in rows)


def test_red_flags_absent_and_boundary_caveats_present(c5p_e_outputs: Path):
    rows = _read_csv(c5p_e_outputs / "c5_annual_reconciliation_red_flags.csv")
    failures = [row for row in rows if row["severity"] == "failure"]
    caveats = [row for row in rows if row["severity"] == "caveat"]
    assert failures
    assert caveats
    assert all(row["active"] == "false" for row in failures)
    for flag in FAILURE_FLAGS:
        assert any(row["red_flag"] == flag for row in failures)

    caveat_names = {row["red_flag"] for row in caveats if row["active"] == "true"}
    assert {
        "ELECTRICITY_BOUNDARY_INCOMPLETE",
        "NG_BOUNDARY_INCOMPLETE",
        "CO2_BOUNDARY_INCOMPLETE",
        "DENOMINATOR_UNRESOLVED",
        "NOT_THESIS_APPROVED",
    } <= caveat_names

    electricity = _read_csv(c5p_e_outputs / "c5_annual_electricity_boundary_diagnostics.csv")
    assert all(row["can_be_used_for_economics_now"] == "false" for row in electricity)
    assert all(row["boundary_status"] == "incomplete_reporting_only_not_full_site_net_import" for row in electricity)
