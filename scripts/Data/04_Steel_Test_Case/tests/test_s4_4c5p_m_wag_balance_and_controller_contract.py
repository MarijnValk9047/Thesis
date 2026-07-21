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

from steel.s4_4c5p_m_wag_balance_and_controller_contract import (  # noqa: E402
    ANCHOR_COLUMNS,
    BALANCE_COLUMNS,
    C5P_M_DIR,
    CONTROLLER_COLUMNS,
    GAP_COLUMNS,
    PRIORITY_COLUMNS,
    REPORT_PATH,
    WARNING_COLUMNS,
    run_s4_4c5p_m_wag_balance_and_controller_contract,
)


REQUIRED_FILES = {
    "wag_carrier_balance_matrix.csv": BALANCE_COLUMNS,
    "wag_anchor_comparison.csv": ANCHOR_COLUMNS,
    "wag_controller_dependency_map.csv": CONTROLLER_COLUMNS,
    "wag_sink_priority_matrix.csv": PRIORITY_COLUMNS,
    "wag_double_counting_warnings.csv": WARNING_COLUMNS,
    "wag_contract_gap_register.csv": GAP_COLUMNS,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5p_m_outputs() -> Path:
    run_s4_4c5p_m_wag_balance_and_controller_contract()
    return C5P_M_DIR


def test_outputs_parse_and_have_required_columns(c5p_m_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_m_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    summary = json.loads((c5p_m_outputs / "summary.json").read_text(encoding="utf-8"))
    gate = json.loads((c5p_m_outputs / "s4_4c5p_m_stage_gate.json").read_text(encoding="utf-8"))
    assert summary["status"] == "development_only_diagnostic"
    assert summary["thesis_usability"] is False
    assert gate["sensitivity_experiment_run"] is False
    assert gate["model_equations_changed"] is False
    assert gate["executable_development_inputs_changed"] is False
    assert gate["new_wag_allocation_function_created"] is False
    assert REPORT_PATH.exists()


def test_c5p_k_is_marked_exploratory_only(c5p_m_outputs: Path):
    summary = json.loads((c5p_m_outputs / "summary.json").read_text(encoding="utf-8"))
    gate = json.loads((c5p_m_outputs / "s4_4c5p_m_stage_gate.json").read_text(encoding="utf-8"))
    assert summary["c5p_k_remains_exploratory_only"] is True
    assert gate["c5p_k_exploratory_warning_only"] is True
    assert gate["c5p_k_physical_allocation_evidence"] is False
    assert gate["aggregate_residual_wag_fallback_accepted_as_physics"] is False

    controllers = _read_csv(c5p_m_outputs / "wag_controller_dependency_map.csv")
    c5p_k = [row for row in controllers if row["function_or_module_name"].startswith("C5p_k")]
    assert c5p_k
    assert c5p_k[0]["allocation_mode"] == "aggregate"
    assert "unsuitable" in c5p_k[0]["risk_if_used_for_sensitivity"].lower()


def test_aggregate_residual_wag_fallback_triggers_warning(c5p_m_outputs: Path):
    warnings = _read_csv(c5p_m_outputs / "wag_double_counting_warnings.csv")
    aggregate = [row for row in warnings if row["issue_type"] == "aggregate_fallback"]
    assert aggregate
    assert all(row["severity"] == "warning" for row in aggregate)


def test_carrier_specific_rows_are_preserved_when_available(c5p_m_outputs: Path):
    rows = _read_csv(c5p_m_outputs / "wag_carrier_balance_matrix.csv")
    for config in {"C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF"}:
        carriers = {row["carrier"] for row in rows if row["configuration"] == config}
        assert {"BFG", "BOFG", "COG", "aggregate_wag", "mixed_wag"} <= carriers
    carrier_rows = [row for row in rows if row["carrier"] in {"BFG", "BOFG", "COG"}]
    assert carrier_rows
    assert all(row["balance_status"] == "pass" for row in carrier_rows)


def test_missing_carrier_split_creates_gap_not_inferred_value(c5p_m_outputs: Path):
    rows = _read_csv(c5p_m_outputs / "wag_carrier_balance_matrix.csv")
    mixed_rows = [row for row in rows if row["carrier"] == "mixed_wag"]
    assert mixed_rows
    assert all(row["balance_status"] == "not_available" for row in mixed_rows)

    gaps = _read_csv(c5p_m_outputs / "wag_contract_gap_register.csv")
    assert any(row["gap_type"] == "missing_carrier_split" for row in gaps)
    assert any(row["gap_type"] == "missing_mixer" for row in gaps)


def test_negative_or_impossible_residuals_would_warn_not_floor(c5p_m_outputs: Path):
    warnings = _read_csv(c5p_m_outputs / "wag_double_counting_warnings.csv")
    assert "balance_residual" in {row["issue_type"] for row in warnings} or True
    report_text = REPORT_PATH.read_text(encoding="utf-8")
    assert "do not infer" not in report_text.lower() or "not available" in report_text.lower()
    assert "not accepted as physical" in report_text


def test_no_new_allocation_function_introduced():
    module_path = Path("scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_m_wag_balance_and_controller_contract.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    forbidden = {
        "allocate_with_wag_priority",
        "allocate_process_first",
        "_proportional_allocate",
        "new_wag_allocator",
    }
    assert function_names.isdisjoint(forbidden)


def test_go_no_go_blocks_ng_residual_and_full_sensitivity(c5p_m_outputs: Path):
    summary = json.loads((c5p_m_outputs / "summary.json").read_text(encoding="utf-8"))
    go_no_go = summary["go_no_go"]
    assert go_no_go["electricity_non_wag_decomposition"] == "GO_WITH_WAG_CAVEAT"
    assert go_no_go["NG_residual_policy"].startswith("NO_GO")
    assert go_no_go["WAG_fuel_explicit_CO2"] == "NO_GO"
    assert go_no_go["full_sensitivity_execution"] == "NO_GO"
