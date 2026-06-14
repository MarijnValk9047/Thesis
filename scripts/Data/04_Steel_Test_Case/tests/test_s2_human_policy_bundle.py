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
    FUTURE_PARAMETER_REVIEW_BACKLOG_REQUIRED_CATEGORIES,
    HUMAN_POLICY_DECISION_BUNDLE_MEMO,
    HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_CLUSTERS,
    HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_ITEMS,
    validate_s2_candidate_review,
    load_s2_candidate_review,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
DECISION_BUNDLE_PATH = REVIEW_ROOT / "s2_human_policy_decision_bundle.csv"
BACKLOG_PATH = REVIEW_ROOT / "s2_future_parameter_review_backlog.csv"

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


def _load_decisions() -> pd.DataFrame:
    return pd.read_csv(DECISION_BUNDLE_PATH, dtype=str, keep_default_na=False)


def test_s27e_human_policy_bundle_memo_exists():
    assert HUMAN_POLICY_DECISION_BUNDLE_MEMO.exists()
    text = HUMAN_POLICY_DECISION_BUNDLE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in (
        "records the current human modelling-policy decisions",
        "not a codex approval artifact",
        "approved-input tables remain empty",
        "endpoint policy decision",
        "buffer classification decision",
        "process-bound policy decision",
        "production target policy decision",
        "sensitivity strategy decision",
    ):
        assert phrase in text


def test_s27e_human_policy_decision_register_exists_and_has_required_structure():
    frame = _load_decisions()
    assert len(frame) == 26
    assert HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_CLUSTERS.issubset(set(frame["decision_cluster"]))
    assert HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_ITEMS.issubset(set(frame["decision_item"]))
    assert frame["executable_status"].str.lower().eq("non_executable").all()
    assert frame["thesis_usability"].str.lower().eq("false").all()
    assert frame["approval_status"].str.lower().isin(
        {
            "human_policy_recorded",
            "convention_recorded",
            "sensitivity_strategy_recorded",
            "not_approved_numerical",
            "blocked_until_later_review",
        }
    ).all()
    assert not frame["approval_status"].str.lower().str.fullmatch("approved").any()


def test_s27e_required_policy_content_is_recorded():
    frame = _load_decisions()
    joined = frame.astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")

    assert "50pct_of_later_approved_store_capacity" in joined
    assert "terminal_inventory_equals_beginning_inventory" in joined
    assert "not_main_strategic_flexibility" in joined
    assert "positive_magnitudes_with_explicit_role_fields" in joined
    assert "annual_public_values_are_validation_or_scaling_anchors_only" in joined
    assert "no_route_specific_production_target" in joined
    assert "without_capacity_approval" in joined


def test_s27e_specific_policy_rows_match_expected_governance_intent():
    frame = _load_decisions().set_index("decision_item")

    assert "capacity_approval" in frame.loc["CYC50_endpoint_policy_base_case", "notes"].lower()
    assert "not_main_strategic_flexibility" in frame.loc["hot_slab_WIP_thermal_transfer_classification", "notes"].lower()
    assert "positive_magnitudes_with_explicit_role_fields" in frame.loc["positive_magnitude_coefficients", "human_decision"].lower()
    assert "annual_public_values_are_validation_or_scaling_anchors_only" in frame.loc["annual_to_hourly_translation_required", "human_decision"].lower()


def test_s27e_no_exact_executable_numerical_values_are_introduced():
    frame = _load_decisions()
    disallowed_numeric_patterns = (
        " tonnes",
        " t/h",
        " mt/y",
        " pj/y",
        " €/mwh",
        " €/kg",
        " eur/mwh",
        " eur/kg",
    )
    for column in ("human_decision", "modelling_interpretation", "unresolved_blocker", "notes"):
        text = frame[column].str.lower().str.cat(sep=" ")
        for token in disallowed_numeric_patterns:
            assert token not in text


def test_s27e_future_review_backlog_exists_and_covers_high_risk_categories():
    backlog = pd.read_csv(BACKLOG_PATH, dtype=str, keep_default_na=False)
    assert len(backlog) == 12
    assert FUTURE_PARAMETER_REVIEW_BACKLOG_REQUIRED_CATEGORIES.issubset(set(backlog["parameter_category"]))
    assert backlog["review_priority"].isin({"high", "medium", "low"}).all()
    assert backlog["sensitivity_likely_required"].str.lower().isin({"true", "false"}).all()
    assert backlog.loc[backlog["parameter_category"].eq("store_capacity_sensitivity_ranges"), "review_priority"].iloc[0] == "high"


def test_s27e_payload_reports_policy_bundle_and_backlog():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)

    assert payload["human_policy_bundle_memo_present"] is True
    assert payload["human_policy_decision_rows_checked"] == 26
    assert payload["future_parameter_review_backlog_rows_checked"] == 12
    assert payload["approved_rows"] == 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["candidate_review_executable_rows"] == 0


def test_s27e_policy_bundle_stays_non_pyomo_and_non_executable():
    source = inspect.getsource(governance_module).lower()
    assert "import pyomo" not in source
    assert "from pyomo" not in source
    assert "build_model(" not in source

    memo_text = HUMAN_POLICY_DECISION_BUNDLE_MEMO.read_text(encoding="utf-8").lower()
    decision_text = DECISION_BUNDLE_PATH.read_text(encoding="utf-8").lower()
    backlog_text = BACKLOG_PATH.read_text(encoding="utf-8").lower()
    for blocked_term in BLOCKED_EXECUTABLE_TERMS:
        if blocked_term in memo_text or blocked_term in decision_text or blocked_term in backlog_text:
            frame = _load_decisions()
            assert frame["executable_status"].str.lower().eq("non_executable").all()
