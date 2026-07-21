from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_s_existing_wag_controller_integration_reconciliation import (  # noqa: E402
    ACTION_COLUMNS,
    ATH_ALIGNMENT_COLUMNS,
    FINDING_COLUMNS,
    IMPLEMENTATION_COLUMNS,
    OUTPUT_DIR,
    POLICY_COLUMNS,
    RECONCILIATION_COLUMNS,
    REPORT_PATH,
    VALIDATION_COLUMNS,
    run_s4_4c5p_s_existing_wag_controller_integration_reconciliation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_s_existing_wag_controller_integration_reconciliation()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "upstream_controller_implementation_register.csv": IMPLEMENTATION_COLUMNS,
        "controller_to_contract_reconciliation.csv": RECONCILIATION_COLUMNS,
        "horizon_boundary_findings.csv": FINDING_COLUMNS,
        "canonical_integration_policy.csv": POLICY_COLUMNS,
        "athanasiadis_methodology_alignment.csv": ATH_ALIGNMENT_COLUMNS,
        "integration_action_plan.csv": ACTION_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_s_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_existing_kgf_and_bf_controllers_are_recognised_but_not_duplicated(outputs: Path):
    rows = _read_csv(outputs / "controller_to_contract_reconciliation.csv")
    kgf_bf = [row for row in rows if row["controller"] in {"KGF_underfiring", "BF_hot_stove"}]
    assert kgf_bf
    assert all(row["reconciliation_status"] == "blocked_boundary_mismatch" for row in kgf_bf)
    assert all("do_not_add" in row["integration_decision"] for row in kgf_bf)


def test_pefa_explains_all_unclassified_carrier_gaps_at_24h_only(outputs: Path):
    rows = _read_csv(outputs / "controller_to_contract_reconciliation.csv")
    pefa = [row for row in rows if row["controller"] == "PEFA_total_gas_heat"]
    assert len(pefa) == 4
    assert all(row["upstream_horizon_hours"] == "24" for row in pefa)
    assert all(row["reconciliation_status"].startswith("matches_") for row in pefa)


def test_horizon_difference_is_reported_not_hidden(outputs: Path):
    rows = _read_csv(outputs / "horizon_boundary_findings.csv")
    pefa = [row for row in rows if row["controller"] == "PEFA_total_gas_heat"]
    assert pefa
    assert all(row["finding_type"] == "cross_horizon_annualisation" for row in pefa)


def test_stage_remains_diagnostic_and_blocks_full_integration(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_s_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["guardrails"]["new_physical_allocator_created"] is False
    assert gate["guardrails"]["model_equations_changed"] is False
    assert gate["go_no_go"]["canonical_ledger_integration_before_horizon_freeze"] == "NO_GO"
    assert gate["go_no_go"]["complete_physical_WAG_NG_allocation"] == "NO_GO"


def test_athanasiadis_alignment_is_architectural_not_numeric(outputs: Path):
    rows = _read_csv(outputs / "athanasiadis_methodology_alignment.csv")
    assert any(row["alignment_status"] == "aligned" for row in rows)
    assert any(row["alignment_status"] == "not_yet_aligned" for row in rows)
    assert "not a numeric replication" in REPORT_PATH.read_text(encoding="utf-8")
