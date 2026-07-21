from __future__ import annotations

import ast
import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_o_wag_controller_contract_hardening import (  # noqa: E402
    ALLOCATION_LEDGER_COLUMNS,
    ATHANASIADIS_COLUMNS,
    BLOCKED_COLUMNS,
    C5P_O_DIR,
    C5P_K_EXCLUSION_COLUMNS,
    CALL_TRACE_COLUMNS,
    INTERFACE_COLUMNS,
    REPORT_PATH,
    VALIDATION_COLUMNS,
    run_s4_4c5p_o_wag_controller_contract_hardening,
)


REQUIRED_FILES = {
    "wag_contract_interface_ledger.csv": INTERFACE_COLUMNS,
    "wag_controller_call_trace.csv": CALL_TRACE_COLUMNS,
    "wag_carrier_sink_allocation_ledger.csv": ALLOCATION_LEDGER_COLUMNS,
    "wag_contract_validation_checks.csv": VALIDATION_COLUMNS,
    "athanasiadis_alignment_matrix.csv": ATHANASIADIS_COLUMNS,
    "c5p_k_exclusion_audit.csv": C5P_K_EXCLUSION_COLUMNS,
    "wag_contract_blocked_cases.csv": BLOCKED_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5p_o_outputs() -> Path:
    run_s4_4c5p_o_wag_controller_contract_hardening()
    return C5P_O_DIR


def test_outputs_parse_and_have_required_columns(c5p_o_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_o_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    summary = json.loads((c5p_o_outputs / "summary.json").read_text(encoding="utf-8"))
    gate = json.loads((c5p_o_outputs / "s4_4c5p_o_stage_gate.json").read_text(encoding="utf-8"))
    assert summary["status"] == "development_only_diagnostic_interface"
    assert summary["thesis_usability"] is False
    assert gate["contract_status"] == "diagnostic_interface_ready"
    assert gate["guardrails"]["model_equations_changed"] is False
    assert gate["guardrails"]["executable_development_inputs_changed"] is False
    assert gate["guardrails"]["source_cards_changed"] is False
    assert gate["guardrails"]["raw_pdfs_inspected"] is False
    assert REPORT_PATH.exists()


def test_no_new_allocation_algorithm_is_introduced():
    module_path = Path("scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_o_wag_controller_contract_hardening.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    forbidden = {
        "allocate_with_wag_priority",
        "allocate_process_first",
        "_proportional_allocate",
        "new_wag_allocator",
        "dispatch_wag_to_common_plants",
    }
    assert function_names.isdisjoint(forbidden)


def test_c5p_k_outputs_are_never_physical_allocation_evidence(c5p_o_outputs: Path):
    rows = _read_csv(c5p_o_outputs / "c5p_k_exclusion_audit.csv")
    assert rows
    assert all(row["allowed_future_use"] != "physical_allocation" for row in rows)
    assert any(row["allowed_future_use"] in {"warning_only", "blocked"} for row in rows)

    gate = json.loads((c5p_o_outputs / "s4_4c5p_o_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["guardrails"]["c5p_k_physical_allocation_use"] is False
    assert gate["c5p_k_policy"] == "warning_context_only_not_physical_allocation_evidence"


def test_aggregate_wag_cannot_feed_physical_allocation(c5p_o_outputs: Path):
    rows = _read_csv(c5p_o_outputs / "wag_contract_interface_ledger.csv")
    aggregate = [row for row in rows if row["carrier"] == "aggregate_wag"]
    assert aggregate
    assert all(row["allocation_mode"] == "aggregate_reporting_only" for row in aggregate)
    assert all(row["can_feed_physical_allocation"] == "no" for row in aggregate)


def test_mixed_wag_cannot_have_quantitative_physical_status(c5p_o_outputs: Path):
    rows = _read_csv(c5p_o_outputs / "wag_contract_interface_ledger.csv")
    mixed = [row for row in rows if row["carrier"] == "mixed_wag"]
    assert mixed
    assert all(row["allocation_mode"] == "structural_only" for row in mixed)
    assert all(row["quantitative_status"] == "structural_only" for row in mixed)
    assert all(row["can_feed_physical_allocation"] == "no" for row in mixed)


def test_cog_bfg_bofg_rows_remain_carrier_specific(c5p_o_outputs: Path):
    rows = _read_csv(c5p_o_outputs / "wag_carrier_sink_allocation_ledger.csv")
    for config in {"C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF"}:
        carriers = {row["carrier"] for row in rows if row["configuration"] == config}
        assert {"COG", "BFG", "BOFG"} <= carriers
    carrier_rows = [row for row in rows if row["carrier"] in {"COG", "BFG", "BOFG"}]
    assert all(row["carrier_split_quality"] == "explicit" for row in carrier_rows)
    assert all(row["accepted_for_contract"] == "yes" for row in carrier_rows)


def test_missing_common_plant_wag_ng_split_creates_blocked_rows(c5p_o_outputs: Path):
    blocked = _read_csv(c5p_o_outputs / "wag_contract_blocked_cases.csv")
    assert any(row["sink_or_stage"] == "common_plant_WAG_NG_split" for row in blocked)
    assert any("NG_residual" in row["blocks_future_stage"] for row in blocked)

    checks = _read_csv(c5p_o_outputs / "wag_contract_validation_checks.csv")
    split_check = [row for row in checks if row["check_type"] == "no_ng_split_invention"]
    assert split_check
    assert split_check[0]["status"] == "blocked"


def test_ng_is_external_backup_not_wag(c5p_o_outputs: Path):
    rules_path = Path("data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_n_wag_controller_contract_proposal/wag_controller_contract_rules.csv")
    rules = _read_csv(rules_path)
    ng_rules = [row for row in rules if row["carrier"] == "NG"]
    assert ng_rules
    assert "external/back-up" in ng_rules[0]["contract_statement"]


def test_no_co2_fuel_explicit_mode_is_unlocked(c5p_o_outputs: Path):
    gate = json.loads((c5p_o_outputs / "s4_4c5p_o_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["guardrails"]["co2_fuel_explicit_mode_unlocked"] is False
    assert gate["go_no_go"]["wag_fuel_explicit_co2"] == "NO_GO"
    checks = _read_csv(c5p_o_outputs / "wag_contract_validation_checks.csv")
    assert any(row["check_type"] == "no_co2_mixed_mode" and row["status"] == "blocked" for row in checks)


def test_stage_gate_keeps_economics_and_da_no_go(c5p_o_outputs: Path):
    gate = json.loads((c5p_o_outputs / "s4_4c5p_o_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["economics_readiness"] == "NO_GO"
    assert gate["go_no_go"]["DA_readiness"] == "NO_GO"
    assert gate["guardrails"]["economics_or_da_active"] is False


def test_athanasiadis_alignment_is_architecture_only(c5p_o_outputs: Path):
    rows = _read_csv(c5p_o_outputs / "athanasiadis_alignment_matrix.csv")
    assert rows
    assert all(row["locator_status"] in {"partial", "indirect", "missing_or_indirect"} for row in rows)
    assert all("no raw PDF" in row["caveat"] for row in rows)
    assert not any("official Tata truth" in row["caveat"] and "not" not in row["caveat"] for row in rows)


def test_report_has_critical_review_section(c5p_o_outputs: Path):
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "How to critically review this WAG implementation" in report
    assert "C5p_k remains warning/context only" in report
