from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    BUFFER_SENSITIVITY_DIAGNOSTICS_MEMO,
    BUFFER_SENSITIVITY_PLAN_PATH,
    BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import LiquidSteelSmokeBuilderError, build_liquid_steel_smoke_model, validate_liquid_steel_smoke_inputs
from steel.liquid_steel_smoke_runner import run_liquid_steel_smoke_cases

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s210d_sensitivity_artifacts_exist_and_validate():
    assert BUFFER_SENSITIVITY_DIAGNOSTICS_MEMO.exists()
    assert BUFFER_SENSITIVITY_PLAN_PATH.exists()
    assert BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["buffer_sensitivity_diagnostics_memo_present"] is True
    assert payload["buffer_sensitivity_plan_rows_checked"] == 21
    assert payload["buffer_sensitivity_result_rows_checked"] == 21


def test_s210d_override_support_is_guarded_to_first_buffer_scope():
    prepared = validate_liquid_steel_smoke_inputs(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        inventory_mode="first_buffers",
        sensitivity_id="TEST_OVERRIDE",
        initial_inventory_fraction=0.25,
        capacity_multiplier_overrides={"c1_dri_hdri_buffer": 0.5},
    )
    active = {store.store_id: store for store in prepared.active_inventory_stores}
    assert active["c1_dri_hdri_buffer"].initial_inventory_fraction == 0.25
    assert active["c1_dri_hdri_buffer"].capacity_multiplier == 0.5
    assert active["c1_hot_metal_buffer"].initial_inventory_fraction == 0.25
    assert active["c1_hot_metal_buffer"].capacity_multiplier == 1.0

    model = build_liquid_steel_smoke_model(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        inventory_mode="first_buffers",
        sensitivity_id="TEST_OVERRIDE",
        initial_inventory_fraction=0.25,
        capacity_multiplier_overrides={"c1_dri_hdri_buffer": 0.5},
    )
    assert model.s2_metadata["sensitivity_id"] == "TEST_OVERRIDE"
    assert model.s2_metadata["initial_inventory_fraction_by_store"]["c1_dri_hdri_buffer"] == 0.25
    assert model.s2_metadata["capacity_multiplier_by_store"]["c1_dri_hdri_buffer"] == 0.5


def test_s210d_invalid_overrides_are_refused():
    with pytest.raises(LiquidSteelSmokeBuilderError, match="readiness-approved first-buffer stores"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            inventory_mode="first_buffers",
            capacity_multiplier_overrides={"c0_slab_wip_buffer": 1.0},
        )

    with pytest.raises(LiquidSteelSmokeBuilderError, match="within \\[0.0, 1.0\\]"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            inventory_mode="first_buffers",
            initial_inventory_fraction=1.25,
        )

    with pytest.raises(LiquidSteelSmokeBuilderError, match="<= 4.0"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            inventory_mode="first_buffers",
            capacity_multiplier_overrides={"c1_dri_hdri_buffer": 5.0},
        )

    with pytest.raises(LiquidSteelSmokeBuilderError, match="Zero-capacity override"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            inventory_mode="first_buffers",
            capacity_multiplier_overrides={"c0_hot_metal_buffer": 0.0},
        )


def test_s210d_runner_reports_sensitivity_metadata_in_build_only_mode(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C0_current_BF_BOF_reference",),
        horizon_hours=24,
        target_variant="feasible_smoke",
        inventory_mode="first_buffers",
        solve_if_available=False,
        output_root=tmp_path,
        sensitivity_id="C0_INIT_25PCT",
        initial_inventory_fraction=0.25,
        capacity_multiplier_overrides={"c0_hot_metal_buffer": 1.0},
    )
    result = payload["results"][0]
    assert result["sensitivity_id"] == "C0_INIT_25PCT"
    assert payload["sensitivity_id"] == "C0_INIT_25PCT"


def test_s210d_summary_register_preserves_non_thesis_outcomes():
    plan = _load_csv(BUFFER_SENSITIVITY_PLAN_PATH)
    results = _load_csv(BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH)

    assert len(plan) == 21
    assert plan["thesis_usability"].str.lower().eq("false").all()

    assert len(results) == 21
    assert results["thesis_usability"].str.lower().eq("false").all()
    assert results["shortfall_slack_active"].str.lower().eq("false").all()
    assert results["binary_count"].eq("0").all()
    assert results["solve_status"].eq("optimal").sum() == 19
    assert results["solve_status"].eq("infeasible").sum() == 2

    feasible = results.loc[results["solve_status"].eq("optimal")]
    stress = results.loc[results["target_variant"].eq("stress_infeasible_original")]
    assert feasible["any_store_hit_zero"].str.lower().eq("true").all()
    assert feasible["all_terminal_inventory_satisfied"].str.lower().eq("true").all()
    assert stress["solve_status"].eq("infeasible").all()

    no_surge = results.loc[results["sensitivity_id"].eq("C1_DRI_HDRI_0X_NO_SURGE")].iloc[0]
    assert no_surge["any_store_hit_capacity"].lower() == "true"


def test_s210d_zero_row_approved_surface_remains_intact():
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1
