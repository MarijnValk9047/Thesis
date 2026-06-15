from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    PROMOTION_DECISION_TEMPLATE_COLUMNS,
    PROMOTION_PROTOCOL_FILE_SPECS,
    PROMOTION_PROTOCOL_REQUIRED_CATEGORIES,
    PROMOTION_REVIEW_CRITERIA_FILE_SPECS,
    load_s2_approved_model_input,
    load_s2_candidate_review,
    validate_s2_approved_model_input,
    validate_s2_candidate_review,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"
PROTOCOL_MEMO = TEST_CASE_ROOT.parents[2] / "docs" / "optimisation" / "steel" / "STEEL_S2_APPROVED_INPUT_PROMOTION_PROTOCOL.md"

BLOCKED_EXECUTABLE_TERMS = (
    "phase 2",
    "phase 3",
    "full_hydrogen",
    "on_site_electrolysis",
    "hydrogen_production",
    "hydrogen_storage",
    "saf",
    "ccs",
    "d_only",
    "d+4",
    "d_plus_4",
    "da bidding",
    "stochastic",
    "mfrr",
    "cvar",
    "product revenue",
    "order book",
)


def test_promotion_protocol_memo_exists_and_states_core_governance_rules():
    assert PROTOCOL_MEMO.exists()
    text = PROTOCOL_MEMO.read_text(encoding="utf-8").lower()
    for phrase in (
        "codex may prepare review packets but may not approve rows",
        "explicit user/thesis-review approval is required",
        "approval and executable status are separate gates",
        "annual-to-hourly translation approval",
        "cyc50",
    ):
        assert phrase in text


def test_protocol_register_exists_and_covers_required_categories():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    protocol_name = next(iter(PROMOTION_PROTOCOL_FILE_SPECS))
    protocol = review_bundle.tables[protocol_name]

    assert set(protocol["category"]).issuperset(PROMOTION_PROTOCOL_REQUIRED_CATEGORIES)
    assert protocol["executable_status"].eq("non_executable").all()
    assert protocol["thesis_usability"].astype(str).str.lower().eq("false").all()
    assert protocol["approval_status"].isin({"protocol_only", "not_approved", "blocked"}).all()
    assert protocol["user_review_required"].astype(str).str.lower().eq("true").all()
    assert protocol["executable_gate_required"].astype(str).str.lower().eq("true").all()
    assert protocol["codex_allowed_role"].str.lower().str.contains("prepare_review_packet").any()
    assert protocol["codex_forbidden_role"].str.lower().str.contains("approve").all()
    assert protocol.loc[protocol["category"].eq("validation_targets"), "forbidden_action"].str.lower().str.contains("constraint").all()
    assert protocol.loc[protocol["category"].eq("annual_to_hourly_translation"), "approval_blocker"].str.lower().str.contains("annual").all()
    assert protocol.loc[protocol["category"].eq("annual_to_hourly_translation"), "approval_blocker"].str.lower().str.contains("hourly").all()


def test_review_criteria_files_exist_and_keep_reviewer_authority():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    expected_basenames = {Path(name).name for name in PROMOTION_REVIEW_CRITERIA_FILE_SPECS}
    actual_basenames = {Path(name).name for name in review_bundle.tables if "s2_promotion_review_criteria/" in name}
    assert actual_basenames == expected_basenames

    for name in PROMOTION_REVIEW_CRITERIA_FILE_SPECS:
        frame = review_bundle.tables[name]
        assert len(frame) > 0
        assert frame["reviewer_decision_required"].astype(str).str.lower().eq("true").all()
        assert frame["codex_may_check"].astype(str).str.lower().eq("true").all()
        assert frame["codex_may_decide"].astype(str).str.lower().eq("false").all()
        assert frame["approval_status"].isin({"protocol_only", "not_approved", "blocked"}).all()

    inventory_text = review_bundle.tables["s2_promotion_review_criteria/inventory_endpoint_policies_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    assert inventory_text.str.contains("endpoint policy").any()
    assert inventory_text.str.contains("capacity").any()

    validation_text = review_bundle.tables["s2_promotion_review_criteria/validation_targets_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    assert validation_text.str.contains("constraint").any()

    target_text = review_bundle.tables["s2_promotion_review_criteria/production_targets_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    assert target_text.str.contains("target basis|target_basis", regex=True).any()

    bounds_text = review_bundle.tables["s2_promotion_review_criteria/process_bounds_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    assert bounds_text.str.contains("annual-to-hourly|annual to hourly", regex=True).any()
    assert bounds_text.str.contains("operating envelope").any()

    capacity_text = review_bundle.tables["s2_promotion_review_criteria/store_capacities_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    assert capacity_text.str.contains("flexibility").any()
    assert capacity_text.str.contains("risk").any()


def test_promotion_decision_template_exists_and_is_header_only():
    template_path = REVIEW_ROOT / "s2_promotion_decision_template.csv"
    assert template_path.exists()
    frame = pd.read_csv(template_path, dtype=str, keep_default_na=False)
    assert list(frame.columns) == PROMOTION_DECISION_TEMPLATE_COLUMNS
    assert len(frame) == 0


def test_governance_payload_and_approved_input_counts_remain_zero():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    approved_input_bundle = load_s2_approved_model_input(APPROVED_INPUT_ROOT)
    review_payload = validate_s2_candidate_review(review_bundle)
    approved_payload = validate_s2_approved_model_input(approved_input_bundle)

    assert review_payload["approved_rows"] == 0
    assert review_payload["thesis_grade_numerical_rows"] == 0
    assert review_payload["candidate_review_executable_rows"] == 0
    assert review_payload["promotion_protocol_rows_checked"] == 18
    assert review_payload["promotion_review_criteria_files_checked"] == 8
    assert review_payload["promotion_decision_template_rows"] == 0

    assert approved_payload["approved_input_total_rows"] == 0
    assert approved_payload["approved_input_approved_rows"] == 0
    assert approved_payload["approved_input_thesis_grade_numerical_rows"] == 0
    assert approved_payload["approved_input_executable_rows"] == 0


def test_promotion_governance_surface_stays_non_pyomo_and_non_executable():
    import steel.governance as governance_module

    source = inspect.getsource(governance_module).lower()
    assert "pyomo" not in source
    assert "build_model(" not in source

    protocol_text = (REVIEW_ROOT / "s2_approved_input_promotion_protocol.csv").read_text(encoding="utf-8").lower()
    criteria_text = "\n".join(
        (REVIEW_ROOT / relative_path).read_text(encoding="utf-8").lower()
        for relative_path in PROMOTION_REVIEW_CRITERIA_FILE_SPECS
    )
    for token in BLOCKED_EXECUTABLE_TERMS:
        if token in protocol_text or token in criteria_text:
            review_bundle = load_s2_candidate_review(REVIEW_ROOT)
            protocol_name = next(iter(PROMOTION_PROTOCOL_FILE_SPECS))
            assert review_bundle.tables[protocol_name]["executable_status"].eq("non_executable").all()
