from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_t_horizon_and_gross_net_boundary_bridge import (  # noqa: E402
    ATH_COLUMNS,
    BRIDGE_COLUMNS,
    HORIZON_COLUMNS,
    MIX_COLUMNS,
    OUTPUT_DIR,
    PROCESS_COLUMNS,
    Q_COMPARISON_COLUMNS,
    REPORT_PATH,
    STATUS_COLUMNS,
    VALIDATION_COLUMNS,
    run_s4_4c5p_t_horizon_and_gross_net_boundary_bridge,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_t_horizon_and_gross_net_boundary_bridge()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "controller_mix_24h_contract_candidate.csv": MIX_COLUMNS,
        "process_reconciliation_24h.csv": PROCESS_COLUMNS,
        "horizon_selection_audit.csv": HORIZON_COLUMNS,
        "c5p_q_horizon_comparison.csv": Q_COMPARISON_COLUMNS,
        "gross_net_boundary_bridge.csv": BRIDGE_COLUMNS,
        "controller_integration_status.csv": STATUS_COLUMNS,
        "athanasiadis_methodology_alignment.csv": ATH_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_t_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_candidate_horizon_is_24h(outputs: Path):
    rows = _read_csv(outputs / "controller_mix_24h_contract_candidate.csv")
    assert rows
    assert {row["horizon_hours"] for row in rows} == {"24"}


def test_all_carrier_process_totals_reconcile_with_pefa(outputs: Path):
    rows = _read_csv(outputs / "process_reconciliation_24h.csv")
    assert len(rows) == 6
    assert all(row["reconciliation_status"] == "pass" for row in rows)
    assert all(abs(float(row["residual_unclassified_PJ_y"])) <= 1e-5 for row in rows)


def test_pefa_is_present_without_a_fixed_stage_share(outputs: Path):
    rows = _read_csv(outputs / "controller_mix_24h_contract_candidate.csv")
    pefa = [row for row in rows if row["sink_or_controller"].startswith("PEFA")]
    assert {row["carrier"] for row in pefa} == {"COG", "BOFG", "NG"}
    assert all("no_fixed_stage_share" in row["allocation_mode"] for row in pefa)


def test_kgf_and_bf_are_not_added_as_duplicate_sinks(outputs: Path):
    bridge = _read_csv(outputs / "gross_net_boundary_bridge.csv")
    assert {row["controller"] for row in bridge} == {"KGF_underfiring", "BF_hot_stove"}
    assert all(row["bridge_status"] == "blocked_no_scale_or_boundary_mapping_selected" for row in bridge)
    mix = _read_csv(outputs / "controller_mix_24h_contract_candidate.csv")
    assert not any(row["sink_or_controller"] in {"KGF_underfiring", "BF_hot_stove"} for row in mix)


def test_stage_does_not_modify_existing_contract_or_unlock_next_layers(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_t_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["canonical_candidate_horizon_hours"] == 24
    assert gate["guardrails"]["C5p_q_modified"] is False
    assert gate["guardrails"]["C5p_o_carrier_totals_modified"] is False
    assert gate["go_no_go"]["C5p_q_migration"] == "REVIEW_REQUIRED"
    assert gate["go_no_go"]["complete_physical_WAG_NG_allocation"] == "NO_GO"


def test_athanasiadis_comparison_is_methodological_only(outputs: Path):
    rows = _read_csv(outputs / "athanasiadis_methodology_alignment.csv")
    assert any(row["alignment_status"].startswith("aligned") for row in rows)
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "not a numeric replication" in report
