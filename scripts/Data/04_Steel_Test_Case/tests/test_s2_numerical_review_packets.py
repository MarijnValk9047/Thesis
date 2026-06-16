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
    NUMERICAL_REVIEW_PACKET_DASHBOARD,
    NUMERICAL_REVIEW_PACKET_DASHBOARD_COLUMNS,
    NUMERICAL_REVIEW_PACKET_DOC_DIR,
    NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES,
    NUMERICAL_REVIEW_PACKET_SUMMARY_COLUMNS,
    NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS,
    load_s2_candidate_review,
    validate_s2_candidate_review,
    validate_s2_numerical_review_packets,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
PACKET_DATA_ROOT = REVIEW_ROOT / "s2_numerical_review_packets"
PROMOTION_TEMPLATE = REVIEW_ROOT / "s2_promotion_decision_template.csv"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"

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


def test_s27f_review_packets_exist_and_validate():
    payload = validate_s2_numerical_review_packets(REVIEW_ROOT)

    assert payload["numerical_review_packet_files_checked"] == len(NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS)
    assert payload["numerical_review_packet_rows_checked"] == 15
    assert payload["numerical_review_packet_dashboard_present"] is True
    assert payload["numerical_review_packet_memos_present"] == len(NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES)


def test_s27f_machine_readable_packets_keep_review_only_statuses():
    for filename in NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS:
        frame = _load_packet(filename)
        assert list(frame.columns) == NUMERICAL_REVIEW_PACKET_SUMMARY_COLUMNS
        assert len(frame) > 0
        assert frame["reviewer_decision_required"].str.lower().eq("true").all()
        assert frame["codex_may_decide"].str.lower().eq("false").all()
        assert frame["approval_status"].str.lower().isin({"review_packet_only", "not_approved", "blocked", "defer_pending_review"}).all()
        assert frame["executable_status"].str.lower().eq("non_executable").all()
        assert frame["thesis_usability"].str.lower().eq("false").all()
        assert not frame["approval_status"].str.lower().eq("approved").any()


def test_s27f_category_specific_guardrails_hold():
    buffer_text = _load_packet("buffer_capacity_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    process_text = _load_packet("process_bounds_translation_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    target_text = _load_packet("production_target_review_packet.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")

    assert "cyc50" in buffer_text
    assert "capacity_approval" in buffer_text
    assert "multi_hour_or_multi_day" in buffer_text
    assert "liquid_steel" in buffer_text

    assert "annual_anchor" in process_text
    assert "hourly_cap" in process_text
    assert "online_hours" in process_text
    assert "availability" in process_text
    assert "utilisation" in process_text

    assert "route_specific" in target_text
    assert "validation_only" in target_text
    assert "shortfall" in target_text


def test_s27f_dashboard_exists_and_covers_required_decision_items():
    dashboard = pd.read_csv(NUMERICAL_REVIEW_PACKET_DASHBOARD, dtype=str, keep_default_na=False)
    assert list(dashboard.columns) == NUMERICAL_REVIEW_PACKET_DASHBOARD_COLUMNS
    assert len(dashboard) == 14
    assert set(dashboard["review_category"]) == {"buffer_capacity", "process_bounds_translation", "production_target"}
    assert dashboard["sensitivity_required"].str.lower().isin({"true", "false"}).all()
    assert dashboard["high_risk_flag"].str.lower().isin({"true", "false"}).all()

    assert "HDRI_DRI_surge_capacity" in set(dashboard["decision_item"])
    assert "cold_slab_WIP_capacity" in set(dashboard["decision_item"])
    assert "annual_to_hourly_translation_method" in set(dashboard["decision_item"])
    assert "target_basis_choice" in set(dashboard["decision_item"])


def test_s27f_candidate_review_payload_stays_non_executable_and_zero_approved():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)

    assert payload["numerical_review_packet_files_checked"] == 3
    assert payload["numerical_review_packet_rows_checked"] == 15
    assert payload["approved_rows"] == 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["candidate_review_executable_rows"] == 0

    assert len(PROMOTION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_s27f_memos_are_present_and_stay_out_of_blocked_scope():
    for filename, phrases in NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES.items():
        text = (NUMERICAL_REVIEW_PACKET_DOC_DIR / filename).read_text(encoding="utf-8").lower()
        for phrase in phrases:
            assert phrase in text
        for blocked_term in BLOCKED_EXECUTABLE_TERMS:
            assert blocked_term not in text


def test_s27f_governance_surface_stays_non_pyomo():
    source = inspect.getsource(governance_module).lower()
    assert "import pyomo" not in source
    assert "from pyomo" not in source
    assert "build_model(" not in source

