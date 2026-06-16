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
    ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH,
    WEEKLY_SMOKE_TARGET_AUDIT_PATH,
    ZERO_HIT_ATTRIBUTION_REGISTER_PATH,
    ZERO_HIT_WEEK_GATE_MEMO,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import build_liquid_steel_smoke_model
from steel.liquid_steel_smoke_runner import run_liquid_steel_smoke_cases

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s210ef_gate_artifacts_exist_and_validate():
    assert ZERO_HIT_WEEK_GATE_MEMO.exists()
    assert ZERO_HIT_ATTRIBUTION_REGISTER_PATH.exists()
    assert WEEKLY_SMOKE_TARGET_AUDIT_PATH.exists()
    assert ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["zero_hit_week_gate_memo_present"] is True
    assert payload["zero_hit_attribution_rows_checked"] == 6
    assert payload["weekly_smoke_target_audit_rows_checked"] == 2
    assert payload["one_week_buffer_smoke_rows_checked"] == 2


def test_s210ef_diagnostic_objective_is_opt_in_and_default_objective_stays_unchanged():
    default_model = build_liquid_steel_smoke_model(
        configuration_id="C0_current_BF_BOF_reference",
        horizon_hours=24,
        inventory_mode="first_buffers",
    )
    diagnostic_model = build_liquid_steel_smoke_model(
        configuration_id="C0_current_BF_BOF_reference",
        horizon_hours=24,
        inventory_mode="first_buffers",
        objective_type="diagnostic_maximise_min_inventory_margin",
    )

    assert default_model.s2_metadata["objective_type"] == "minimise_overproduction_dev_only"
    assert diagnostic_model.s2_metadata["objective_type"] == "diagnostic_maximise_min_inventory_margin"
    assert default_model.s2_metadata["shortfall_slack_active"] is False
    assert diagnostic_model.s2_metadata["shortfall_slack_active"] is False
    assert default_model.s2_model_stats.binaries == 0
    assert diagnostic_model.s2_model_stats.binaries == 0


def test_s210ef_runner_supports_168h_build_only_with_explicit_diagnostic_objective(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C0_current_BF_BOF_reference",),
        horizon_hours=168,
        target_variant="feasible_smoke_168h",
        inventory_mode="first_buffers",
        objective_type="diagnostic_maximise_min_inventory_margin",
        solve_if_available=False,
        output_root=tmp_path,
        sensitivity_id="TEST_WEEKLY_BUILD_ONLY",
    )
    result = payload["results"][0]
    assert payload["objective_type"] == "diagnostic_maximise_min_inventory_margin"
    assert result["solve_summary"]["objective_type"] == "diagnostic_maximise_min_inventory_margin"
    assert result["input_validation_summary"]["horizon_hours"] == 168


def test_s210ef_zero_hit_register_records_benign_gate_and_non_thesis_status():
    register = _load_csv(ZERO_HIT_ATTRIBUTION_REGISTER_PATH)
    assert len(register) == 6
    assert register["thesis_usability"].str.lower().eq("false").all()

    diagnostic_rows = register.loc[register["objective_type"].eq("diagnostic_maximise_min_inventory_margin")]
    assert diagnostic_rows["solve_status"].str.lower().eq("optimal").all()
    assert diagnostic_rows["zero_hit_reduced_vs_default"].str.lower().eq("true").all()
    assert diagnostic_rows["benign_gate_result"].eq("passed").all()
    assert diagnostic_rows["one_week_allowed"].str.lower().eq("true").all()

    stress_rows = register.loc[register["target_variant"].eq("stress_infeasible_original")]
    assert stress_rows["solve_status"].str.lower().eq("infeasible").all()
    assert stress_rows["stress_case_preserved_if_applicable"].str.lower().eq("true").all()


def test_s210ef_weekly_summary_stays_non_thesis_and_guarded():
    summary = _load_csv(ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH)
    assert len(summary) == 2
    assert summary["horizon_hours"].eq("168").all()
    assert summary["target_variant"].eq("feasible_smoke_168h").all()
    assert summary["objective_type"].eq("diagnostic_maximise_min_inventory_margin").all()
    assert summary["solve_status"].str.lower().eq("optimal").all()
    assert summary["shortfall_slack_active"].str.lower().eq("false").all()
    assert summary["downstream_active"].str.lower().eq("false").all()
    assert summary["thesis_usability"].str.lower().eq("false").all()
    assert summary["any_store_hit_zero"].str.lower().eq("false").all()
    assert summary["any_store_hit_capacity"].str.lower().eq("false").all()
    assert summary["all_terminal_inventory_satisfied"].str.lower().eq("true").all()


def test_s210ef_memo_records_that_one_week_was_opened_for_benign_reason():
    memo = ZERO_HIT_WEEK_GATE_MEMO.read_text(encoding="utf-8").lower()
    assert "one-week was opened" in memo or "one week was opened" in memo
    assert "benign" in memo
    assert "why outputs remain non-thesis" in memo
    assert "why s3 is still not entered in this task" in memo


def test_s210ef_surface_stays_out_of_later_stage_scope():
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1

    source = inspect.getsource(sys.modules["steel.liquid_steel_smoke_runner"]).lower()
    assert "reserve_capacity" not in source
    assert "scenario_probability" not in source
    assert "submitted_bids" not in source

    register_text = (
        ZERO_HIT_ATTRIBUTION_REGISTER_PATH.read_text(encoding="utf-8").lower()
        + ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH.read_text(encoding="utf-8").lower()
    )
    for blocked_term in ("da bidding", "stochastic", "mfrr", "cvar", "product revenue", "order book"):
        assert blocked_term not in register_text
