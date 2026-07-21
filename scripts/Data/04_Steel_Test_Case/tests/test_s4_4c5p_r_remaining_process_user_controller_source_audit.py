from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_r_remaining_process_user_controller_source_audit import (  # noqa: E402
    ACTION_COLUMNS,
    AUDIT_COLUMNS,
    EVIDENCE_COLUMNS,
    OUTPUT_DIR,
    READINESS_COLUMNS,
    REPORT_PATH,
    UNRESOLVED_COLUMNS,
    run_s4_4c5p_r_remaining_process_user_controller_source_audit,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_r_remaining_process_user_controller_source_audit()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "process_user_controller_source_audit.csv": AUDIT_COLUMNS,
        "source_card_evidence_matrix.csv": EVIDENCE_COLUMNS,
        "controller_activation_readiness.csv": READINESS_COLUMNS,
        "unresolved_process_use_mapping.csv": UNRESOLVED_COLUMNS,
        "next_hardening_actions.csv": ACTION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_r_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_kgf_is_cog_self_use_not_a_free_mixed_gas_sink(outputs: Path):
    rows = _read_csv(outputs / "process_user_controller_source_audit.csv")
    kgf = next(row for row in rows if row["process_user_id"] == "KGF_underfiring")
    assert kgf["allowed_carriers"] == "COG only in Tata-inspired base"
    assert "BFG; BOFG; NG" in kgf["blocked_or_deferred_carriers"]
    assert kgf["readiness_status"] == "implemented_upstream_reconciliation_required"


def test_pefa_total_demand_is_not_converted_into_an_invented_stage_split(outputs: Path):
    rows = _read_csv(outputs / "controller_activation_readiness.csv")
    pefa = next(row for row in rows if row["process_user_id"] == "PEFA_total_gas_heat")
    assert pefa["quantitative_demand_ready"] == "yes_total_only"
    assert pefa["physical_allocation_status"] == "implemented_upstream_horizon_reconciliation_required"
    assert "24-hour" in pefa["gating_reason"]


def test_existing_hsm_and_sinter_outputs_remain_diagnostic_only(outputs: Path):
    rows = _read_csv(outputs / "controller_activation_readiness.csv")
    statuses = {row["process_user_id"]: row["physical_allocation_status"] for row in rows}
    assert statuses["HSM_WBW"] == "accepted_diagnostic_only"
    assert statuses["Sinter"] == "accepted_diagnostic_only"


def test_unclassified_process_use_is_visible_and_not_reallocated(outputs: Path):
    rows = _read_csv(outputs / "unresolved_process_use_mapping.csv")
    unresolved = [row for row in rows if float(row["unclassified_process_use_PJ_y"]) > 0]
    assert unresolved
    assert all(row["current_handling"] == "visible gap; not reallocated" for row in unresolved)


def test_stage_gate_blocks_migration_and_full_physical_allocation(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_r_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["status"] == "source_to_controller_readiness_audited"
    assert gate["guardrails"]["new_physical_allocator_created"] is False
    assert gate["go_no_go"]["complete_physical_WAG_NG_allocation"] == "NO_GO"
    assert gate["go_no_go"]["executable_input_migration"] == "NO_GO"


def test_report_is_explicit_about_scope(outputs: Path):
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "source-to-controller readiness audit only" in report
    assert "migration, economics and DA: NO-GO" in report
