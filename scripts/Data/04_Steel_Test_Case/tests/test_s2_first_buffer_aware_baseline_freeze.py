from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    BUFFER_AWARE_NEXT_CHECK_REGISTER_PATH,
    FIRST_BUFFER_AWARE_BASELINE_SUMMARY_PATH,
    INVENTORY_USE_INTERPRETATION_PATH,
    LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_MEMO,
    PROMOTION_DECISION_TEMPLATE,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s210c_freeze_artifacts_exist_and_validate():
    assert LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_MEMO.exists()
    assert INVENTORY_USE_INTERPRETATION_PATH.exists()
    assert FIRST_BUFFER_AWARE_BASELINE_SUMMARY_PATH.exists()
    assert BUFFER_AWARE_NEXT_CHECK_REGISTER_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["liquid_steel_first_buffer_aware_baseline_freeze_memo_present"] is True
    assert payload["inventory_use_interpretation_rows_checked"] == 3
    assert payload["first_buffer_aware_baseline_rows_checked"] == 4
    assert payload["buffer_aware_next_check_rows_checked"] == 9


def test_s210c_interpretation_and_baseline_summary_preserve_non_thesis_boundaries():
    interpretation = _load_csv(INVENTORY_USE_INTERPRETATION_PATH)
    baseline = _load_csv(FIRST_BUFFER_AWARE_BASELINE_SUMMARY_PATH)

    assert len(interpretation) == 3
    assert interpretation["thesis_usability"].str.lower().eq("false").all()
    assert interpretation["hit_zero"].str.lower().eq("true").all()
    assert interpretation["hit_capacity"].str.lower().eq("false").all()
    assert interpretation["terminal_satisfied"].str.lower().eq("true").all()
    assert interpretation["acceptable_for_24h_smoke"].str.lower().eq("true").all()
    assert interpretation["acceptable_for_one_week_without_more_checks"].str.lower().eq("false").all()
    assert interpretation.loc[interpretation["store_id"].str.contains("hot_metal"), "interpretation"].str.lower().str.contains("synchronisation only").all()
    assert interpretation.loc[interpretation["store_id"].eq("c1_dri_hdri_buffer"), "interpretation"].str.lower().str.contains("short-term surge only").all()

    assert len(baseline) == 4
    assert baseline["thesis_usability"].str.lower().eq("false").all()
    feasible = baseline.loc[baseline["target_variant"].eq("feasible_smoke")]
    stress = baseline.loc[baseline["target_variant"].eq("stress_infeasible_original")]
    assert feasible["solve_status"].eq("optimal").all()
    assert feasible["any_store_hit_zero"].str.lower().eq("true").all()
    assert feasible["all_terminal_inventory_satisfied"].str.lower().eq("true").all()
    assert stress["solve_status"].eq("infeasible").all()


def test_s210c_next_checks_keep_one_week_and_later_scope_blocked():
    next_checks = _load_csv(BUFFER_AWARE_NEXT_CHECK_REGISTER_PATH)
    assert len(next_checks) == 9
    assert next_checks["current_status"].eq("blocked_pending_review").all()
    assert "one_week_buffer_aware_run_gate" in set(next_checks["next_check"])
    assert "downstream_hsm_activation_gate" in set(next_checks["next_check"])
    assert "s3_energy_cost_emissions_entry_gate" in set(next_checks["next_check"])
    assert next_checks["forbidden_shortcut"].str.lower().str.contains("do_not").all()


def test_s210c_zero_row_approved_surface_and_template_remain_intact():
    assert len(PROMOTION_DECISION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1
