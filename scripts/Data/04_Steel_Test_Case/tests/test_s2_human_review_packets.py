from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

import steel.governance as governance_module
from steel.governance import (
    HUMAN_REVIEW_PACKET_DASHBOARD,
    HUMAN_REVIEW_PACKET_DASHBOARD_COLUMNS,
    HUMAN_REVIEW_PACKET_DOC_DIR,
    HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES,
    HUMAN_REVIEW_PACKET_SUMMARY_COLUMNS,
    HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS,
    validate_s2_human_review_packets,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
PACKET_DATA_ROOT = REVIEW_ROOT / "s2_human_review_packets"

BLOCKED_EXECUTABLE_TERMS = (
    "phase 2",
    "phase 3",
    "full hydrogen",
    "on-site electrolysis",
    "hydrogen production",
    "hydrogen storage",
    "saf",
    "ccs",
    "d-only",
    "d+4",
    "da bidding",
    "stochastic",
    "mfrr",
    "cvar",
    "product revenue",
    "order book",
)


def _load_packet(filename: str) -> pd.DataFrame:
    return pd.read_csv(PACKET_DATA_ROOT / filename, dtype=str, keep_default_na=False)


def test_s27d_review_packets_exist_and_validate():
    payload = validate_s2_human_review_packets(REVIEW_ROOT)

    assert payload["human_review_packet_files_checked"] == len(HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS)
    assert payload["human_review_packet_rows_checked"] == 7
    assert payload["human_review_packet_dashboard_present"] is True
    assert payload["human_review_packet_memos_present"] == len(HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES)


def test_s27d_machine_readable_packets_keep_review_only_statuses():
    for filename in HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS:
        frame = _load_packet(filename)
        assert list(frame.columns) == HUMAN_REVIEW_PACKET_SUMMARY_COLUMNS
        assert len(frame) > 0
        assert frame["reviewer_decision_required"].str.lower().eq("true").all()
        assert frame["codex_may_decide"].str.lower().eq("false").all()
        assert frame["approval_status"].str.lower().isin({"review_packet_only", "not_approved", "blocked", "defer_pending_review"}).all()
        assert frame["executable_status"].str.lower().eq("non_executable").all()
        assert frame["thesis_usability"].str.lower().eq("false").all()
        assert not frame["candidate_source_table"].str.contains("validation_targets_candidate_review.csv", case=False).any()


def test_s27d_category_specific_guardrails_hold():
    endpoint = _load_packet("inventory_endpoint_policy_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    terminal = _load_packet("terminal_inventory_rules_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    initial = _load_packet("initial_inventory_rules_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")

    assert "cyc50" in endpoint
    assert "not_buffer_capacity_approval" in endpoint
    assert "operational_truth" in endpoint

    assert "fake_flexibility" in terminal
    assert "horizon_borrowing" in terminal
    assert "penalty" in terminal

    assert "percentage_of_capacity" in initial
    assert "absolute_quantity" in initial
    assert "store_capacity_approval" in initial


def test_s27d_dashboard_counts_match_packet_rows():
    dashboard = pd.read_csv(HUMAN_REVIEW_PACKET_DASHBOARD, dtype=str, keep_default_na=False)
    assert list(dashboard.columns) == HUMAN_REVIEW_PACKET_DASHBOARD_COLUMNS

    expected_counts = {
        "inventory_endpoint_policy": {
            "candidate_count": 3,
            "high_confidence_candidate_count": 3,
            "sensitivity_required_count": 3,
            "blocked_or_defer_count": 0,
            "missing_source_count": 0,
            "missing_unit_or_basis_count": 0,
            "human_decision_needed_count": 3,
        },
        "terminal_inventory_rules": {
            "candidate_count": 2,
            "high_confidence_candidate_count": 2,
            "sensitivity_required_count": 2,
            "blocked_or_defer_count": 2,
            "missing_source_count": 0,
            "missing_unit_or_basis_count": 0,
            "human_decision_needed_count": 2,
        },
        "initial_inventory_rules": {
            "candidate_count": 2,
            "high_confidence_candidate_count": 0,
            "sensitivity_required_count": 2,
            "blocked_or_defer_count": 2,
            "missing_source_count": 2,
            "missing_unit_or_basis_count": 2,
            "human_decision_needed_count": 2,
        },
    }

    for row in dashboard.to_dict(orient="records"):
        expected = expected_counts[row["review_category"]]
        for field_name, value in expected.items():
            assert int(row[field_name]) == value


def test_s27d_memos_are_present_and_stay_out_of_blocked_scope():
    for filename, phrases in HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES.items():
        text = (HUMAN_REVIEW_PACKET_DOC_DIR / filename).read_text(encoding="utf-8").lower()
        for phrase in phrases:
            assert phrase in text
        for blocked_term in BLOCKED_EXECUTABLE_TERMS:
            assert blocked_term not in text


def test_s27d_review_packet_governance_surface_stays_non_pyomo():
    source = inspect.getsource(governance_module).lower()
    assert "import pyomo" not in source
    assert "from pyomo" not in source
    assert "build_model(" not in source
