from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c_unified_physical_modelbuilder import (  # noqa: E402
    DEFAULT_BUILD_AUDIT_CSV_PATH,
    DEFAULT_CONSTRAINT_AUDIT_CSV_PATH,
    DEFAULT_HOURLY_CSV_PATH,
    DEFAULT_REPORT_JSON_PATH,
    DEFAULT_STAGE_GATE_JSON_PATH,
    run_s44c_unified_physical_regression,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_s4_4c_attempts_c0_and_c1_through_same_runner():
    report = run_s44c_unified_physical_regression(run_id="pytest_s44c_no_write", write_report=False)
    audits = {row["configuration_id"]: row for row in report["configuration_build_audit"]}

    assert set(audits) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
    }
    assert audits["C0_current_BF_BOF_reference"]["build_status"] == "blocked_missing_inputs"
    assert audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["build_status"] == "solved"
    assert report["stage_gate"]["decision"] == "pass_with_limitations_to_s4_4d"


def test_s4_4c_c1_physical_regression_enforces_target_and_terminal_rule():
    report = run_s44c_unified_physical_regression(run_id="pytest_s44c_physical", write_report=False)
    c1 = next(
        row
        for row in report["configuration_build_audit"]
        if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )

    assert c1["solver_status"] == "ok"
    assert c1["termination_condition"] == "optimal"
    assert c1["binary_count"] > 0
    assert abs(float(c1["final_product_residual_t"])) <= 1e-6
    assert abs(float(c1["dri_terminal_residual_t"])) <= 1e-6
    assert float(c1["electricity_mwh"]) > 0.0
    assert float(c1["natural_gas_nm3"]) > 0.0


def test_s4_4c_constraint_audit_includes_implemented_and_blocked_families():
    report = run_s44c_unified_physical_regression(run_id="pytest_s44c_constraints", write_report=False)
    rows = report["constraint_audit"]
    implemented = {
        (row["configuration_id"], row["constraint_family"])
        for row in rows
        if row["implemented"] == "yes"
    }
    blocked = {
        (row["configuration_id"], row["constraint_family"])
        for row in rows
        if row["implemented"] == "no"
    }

    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "capacity_bounds") in implemented
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "DRI_buffer_balance") in implemented
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "final_product_fulfilment") in implemented
    assert ("C0_current_BF_BOF_reference", "process_activity") in blocked
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "WAG_steam_grid_balance") in blocked


def test_s4_4c_writes_parseable_reports():
    run_s44c_unified_physical_regression(run_id="pytest_s44c_write", write_report=True)

    report = json.loads(DEFAULT_REPORT_JSON_PATH.read_text(encoding="utf-8"))
    gate = json.loads(DEFAULT_STAGE_GATE_JSON_PATH.read_text(encoding="utf-8"))
    build_rows = _read_csv(DEFAULT_BUILD_AUDIT_CSV_PATH)
    constraint_rows = _read_csv(DEFAULT_CONSTRAINT_AUDIT_CSV_PATH)
    hourly_rows = _read_csv(DEFAULT_HOURLY_CSV_PATH)

    assert report["hourly_da_price_taking_active"] is False
    assert gate["product_revenue_active"] is False
    assert gate["export_revenue_active"] is False
    assert gate["grid_tariff_objective_active"] is False
    assert gate["direct_wag_market_valuation_active"] is False
    assert gate["co2_ets_objective_active"] is False
    assert gate["invalid_input_rows_used_count"] == 0
    assert len(build_rows) == 2
    assert constraint_rows
    assert len(hourly_rows) == 48
