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
    DEV_INPUT_READINESS_MEMO,
    EARLY_SENSITIVITY_REQUIRED_PARAMETERS,
    MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO,
    MINIMAL_NUMERICAL_POLICY_REQUIRED_CLUSTERS,
    MINIMAL_NUMERICAL_POLICY_REQUIRED_ITEMS,
    PROVISIONAL_DEV_INPUT_FILE_SPECS,
    PROVISIONAL_DEV_INPUT_INDEX_PATH,
    PROVISIONAL_DEV_INPUT_README,
    PROVISIONAL_DEV_INPUT_ROOT,
    load_s2_candidate_review,
    load_s2_provisional_dev_input,
    validate_s2_candidate_review,
    validate_s2_minimal_numerical_policy_bundle,
    validate_s2_provisional_dev_input,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
DECISION_BUNDLE_PATH = REVIEW_ROOT / "s2_minimal_numerical_policy_decision_bundle.csv"
SCREENING_PLAN_PATH = REVIEW_ROOT / "s2_early_sensitivity_screening_plan.csv"
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


def _load_decision_bundle() -> pd.DataFrame:
    return pd.read_csv(DECISION_BUNDLE_PATH, dtype=str, keep_default_na=False)


def _load_dev_table(filename: str) -> pd.DataFrame:
    return pd.read_csv(PROVISIONAL_DEV_INPUT_ROOT / filename, dtype=str, keep_default_na=False)


def test_s27g_s28a_memo_and_register_exist_and_validate():
    assert MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO.exists()
    assert DECISION_BUNDLE_PATH.exists()
    assert SCREENING_PLAN_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_minimal_numerical_policy_bundle(review_bundle)
    assert payload["minimal_numerical_policy_bundle_memo_present"] is True
    assert payload["minimal_numerical_policy_decision_rows_checked"] == 27
    assert payload["early_sensitivity_screening_plan_rows_checked"] == 5


def test_s27g_s28a_decision_register_has_required_clusters_and_items():
    frame = _load_decision_bundle()
    assert len(frame) == 27
    assert MINIMAL_NUMERICAL_POLICY_REQUIRED_CLUSTERS.issubset(set(frame["decision_cluster"]))
    assert MINIMAL_NUMERICAL_POLICY_REQUIRED_ITEMS.issubset(set(frame["decision_item"]))
    assert frame["executable_status"].str.lower().eq("non_executable").all()
    assert frame["thesis_usability"].str.lower().eq("false").all()
    assert frame["approval_status"].str.lower().isin(
        {
            "human_policy_recorded",
            "numerical_policy_recorded",
            "provisional_structure_recorded",
            "sensitivity_strategy_recorded",
            "not_approved_numerical",
            "blocked_until_later_review",
        }
    ).all()
    assert not frame["approval_status"].str.lower().eq("approved").any()


def test_s27g_s28a_screening_plan_covers_required_parameters():
    plan = pd.read_csv(SCREENING_PLAN_PATH, dtype=str, keep_default_na=False)
    assert len(plan) == 5
    assert EARLY_SENSITIVITY_REQUIRED_PARAMETERS.issubset(set(plan["sensitivity_parameter"]))
    assert plan["thesis_use_status"].str.lower().eq("false").all()
    assert plan["executable_status"].str.lower().eq("non_executable").all()
    assert plan["approval_status"].str.lower().eq("screening_plan_only").all()


def test_s27g_s28a_provisional_dev_pack_exists_and_validates():
    assert PROVISIONAL_DEV_INPUT_README.exists()
    assert DEV_INPUT_READINESS_MEMO.exists()
    for filename in PROVISIONAL_DEV_INPUT_FILE_SPECS:
        assert (PROVISIONAL_DEV_INPUT_ROOT / filename).exists()
    assert PROVISIONAL_DEV_INPUT_INDEX_PATH.exists()

    bundle = load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT)
    payload = validate_s2_provisional_dev_input(bundle)
    assert payload["dev_input_readiness_memo_present"] is True
    assert payload["provisional_dev_input_files_checked"] == 11
    assert payload["provisional_dev_input_index_rows_checked"] == 9
    assert payload["provisional_dev_input_approved_rows"] == 0
    assert payload["provisional_dev_input_thesis_usable_rows"] == 0


def test_s27g_s28a_dev_pack_rows_keep_non_thesis_and_non_approved_status():
    for filename in PROVISIONAL_DEV_INPUT_FILE_SPECS:
        frame = _load_dev_table(filename)
        if "thesis_usability" in frame.columns:
            assert frame["thesis_usability"].str.lower().eq("false").all()
        if "approval_status" in frame.columns:
            assert not frame["approval_status"].str.lower().eq("approved").any()
        if "reviewer_decision_required" in frame.columns:
            assert frame["reviewer_decision_required"].str.lower().eq("true").all()
        if "codex_may_decide" in frame.columns:
            assert frame["codex_may_decide"].str.lower().eq("false").all()

        dev_rows = frame["executable_status"].str.lower().eq("dev_executable_only") if "executable_status" in frame.columns else pd.Series([], dtype=bool)
        if dev_rows.any():
            assert frame.loc[dev_rows, "approval_status"].str.lower().eq("provisional_development_only").all()


def test_s27g_s28a_dev_pack_guardrails_hold():
    inventory_text = _load_dev_table("inventory_endpoint_policies.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    store_text = _load_dev_table("store_capacities.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    process_text = _load_dev_table("process_bounds.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    target_text = _load_dev_table("production_targets.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")

    assert "cyc50" in inventory_text
    assert "not_capacity_approval" in inventory_text
    assert "multi_hour_or_multi_day" in store_text
    assert "annual_anchor_requires_translation" in process_text
    assert "route_neutral" in target_text


def test_s27g_s28a_approved_inputs_and_template_remain_zero_row():
    assert len(PROMOTION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_s27g_s28a_candidate_review_payload_reports_new_surfaces():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)

    assert payload["minimal_numerical_policy_bundle_memo_present"] is True
    assert payload["minimal_numerical_policy_decision_rows_checked"] == 27
    assert payload["early_sensitivity_screening_plan_rows_checked"] == 5
    assert payload["dev_input_readiness_memo_present"] is True
    assert payload["provisional_dev_input_files_checked"] == 11
    assert payload["provisional_dev_input_index_rows_checked"] == 9
    assert payload["provisional_dev_input_approved_rows"] == 0
    assert payload["provisional_dev_input_thesis_usable_rows"] == 0
    assert payload["approved_rows"] == 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["approved_input_executable_rows"] == 0 if "approved_input_executable_rows" in payload else True


def test_s27g_s28a_governance_surface_stays_non_pyomo_and_out_of_blocked_scope():
    source = inspect.getsource(governance_module).lower()
    assert "import pyomo" not in source
    assert "from pyomo" not in source
    assert "build_model(" not in source

    combined_text = (
        MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO.read_text(encoding="utf-8").lower()
        + DECISION_BUNDLE_PATH.read_text(encoding="utf-8").lower()
        + SCREENING_PLAN_PATH.read_text(encoding="utf-8").lower()
        + PROVISIONAL_DEV_INPUT_README.read_text(encoding="utf-8").lower()
        + DEV_INPUT_READINESS_MEMO.read_text(encoding="utf-8").lower()
    )
    for blocked_term in BLOCKED_EXECUTABLE_TERMS:
        if blocked_term in combined_text:
            bundle = load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT)
            for frame in bundle.tables.values():
                if "executable_status" in frame.columns:
                    assert not frame["executable_status"].str.lower().eq("executable").any()

