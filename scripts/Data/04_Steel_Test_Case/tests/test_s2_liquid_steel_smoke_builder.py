from __future__ import annotations

import inspect
from pathlib import Path
from shutil import copytree
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    LIQUID_STEEL_SMOKE_BUILDER_MODULE,
    LIQUID_STEEL_SMOKE_BUILDER_SCOPE_MEMO,
    PROVISIONAL_DEV_INPUT_ROOT,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import (
    LiquidSteelSmokeBuilderError,
    build_liquid_steel_smoke_model,
    validate_liquid_steel_smoke_inputs,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"
BLOCKED_EXECUTABLE_TERMS = (
    "phase 2",
    "phase 3",
    "full hydrogen",
    "on-site electrolysis",
    "hydrogen production",
    "hydrogen storage",
    "da bidding",
    "stochastic",
    "mfrr",
    "cvar",
    "product revenue",
    "order book",
)


def _copy_dev_root(tmp_path: Path) -> Path:
    copied_root = tmp_path / "s2_provisional_dev_input"
    copytree(PROVISIONAL_DEV_INPUT_ROOT, copied_root)
    return copied_root


def test_s29a_builder_artifacts_exist_and_governance_reports_them():
    assert LIQUID_STEEL_SMOKE_BUILDER_MODULE.exists()
    assert LIQUID_STEEL_SMOKE_BUILDER_SCOPE_MEMO.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["liquid_steel_smoke_builder_module_present"] is True
    assert payload["liquid_steel_smoke_builder_scope_memo_present"] is True


def test_s29a_builder_refuses_approved_input_surface():
    with pytest.raises(LiquidSteelSmokeBuilderError, match="s2_approved_model_input"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            provisional_dev_input_root=APPROVED_INPUT_ROOT,
        )


def test_s29a_builder_refuses_inventory_activation():
    with pytest.raises(LiquidSteelSmokeBuilderError, match="inventory activation"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            enable_inventory_rows=True,
        )


def test_s29a_builder_builds_c0_and_c1_continuous_lp_models():
    c0_model = build_liquid_steel_smoke_model(
        configuration_id="C0_current_BF_BOF_reference",
        horizon_hours=24,
    )
    c1_model = build_liquid_steel_smoke_model(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        horizon_hours=24,
    )

    for model in (c0_model, c1_model):
        assert model.s2_metadata["thesis_usability"] is False
        assert model.s2_metadata["input_surface"] == "s2_provisional_dev_input"
        assert model.s2_metadata["inventory_scope_active"] is False
        assert model.s2_metadata["downstream_scope_active"] is False
        assert model.s2_metadata["route_neutral_target"] is True
        assert model.s2_model_stats.binaries == 0
        assert model.s2_model_stats.variables > 0
        assert model.s2_model_stats.constraints > 0

    assert set(c0_model.PROCESSES.data()) == {"c0_blast_furnace", "c0_bof_converter"}
    assert set(c1_model.PROCESSES.data()) == {"c1_blast_furnace", "c1_bof_converter", "c1_ng_drp", "c1_eaf"}
    assert "shortfall" not in " ".join(c0_model.component_map().keys()).lower()


def test_s29a_builder_reports_refused_downstream_and_inventory_rows():
    report = validate_liquid_steel_smoke_inputs(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        horizon_hours=24,
    ).validation_report

    reasons = {row.reason for row in report.refused_rows}
    refused_by_table = {(row.table_name, row.row_id) for row in report.refused_rows}
    assert "inventory_scope_deferred" in reasons
    assert "downstream_or_casting_out_of_scope" in reasons
    assert ("process_bounds.csv", "DEV_PB_008") in refused_by_table
    assert ("conversion_coefficients.csv", "DEV_CC_008") in refused_by_table
    assert report.encountered_non_executable_row is True


def test_s29a_builder_refuses_approved_or_non_dev_rows_in_selected_scope(tmp_path: Path):
    dev_root = _copy_dev_root(tmp_path)
    bounds = pd.read_csv(dev_root / "process_bounds.csv", dtype=str, keep_default_na=False)
    bounds.loc[bounds["row_id"].eq("DEV_PB_001"), "approval_status"] = "approved"
    bounds.to_csv(dev_root / "process_bounds.csv", index=False)

    with pytest.raises(LiquidSteelSmokeBuilderError, match="approval_status=approved"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            provisional_dev_input_root=dev_root,
        )


def test_s29a_builder_refuses_targeted_non_executable_rows(tmp_path: Path):
    dev_root = _copy_dev_root(tmp_path)
    bounds = pd.read_csv(dev_root / "process_bounds.csv", dtype=str, keep_default_na=False)
    bounds.loc[bounds["row_id"].eq("DEV_PB_001"), "executable_status"] = "not_executable"
    bounds.to_csv(dev_root / "process_bounds.csv", index=False)

    with pytest.raises(LiquidSteelSmokeBuilderError, match="not_executable"):
        validate_liquid_steel_smoke_inputs(
            configuration_id="C0_current_BF_BOF_reference",
            provisional_dev_input_root=dev_root,
        )


def test_s29a_builder_keeps_route_neutral_horizon_total_targets():
    report = validate_liquid_steel_smoke_inputs(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        horizon_hours=168,
    ).validation_report
    assert report.consumed_production_target_rows == ("DEV_PT_004",)

    targets = pd.read_csv(PROVISIONAL_DEV_INPUT_ROOT / "production_targets.csv", dtype=str, keep_default_na=False)
    consumed = targets.loc[targets["row_id"].isin(report.consumed_production_target_rows)].iloc[0]
    assert consumed["carrier_id"] == "liquid_steel"
    assert "horizon_total_target" in consumed["target_name"]
    assert "route_neutral" in consumed["value_basis"]


def test_s29a_builder_surface_excludes_later_stage_logic():
    source = inspect.getsource(sys.modules["steel.liquid_steel_smoke_builder"]).lower()
    assert "binary" not in source
    assert "solverfactory" not in source
    assert "cvar" not in source
    assert "stochastic" not in source
    assert "da bidding" not in source
    assert "mfrr" not in source
    assert "product revenue" not in source
    for blocked_term in BLOCKED_EXECUTABLE_TERMS:
        assert blocked_term not in source
