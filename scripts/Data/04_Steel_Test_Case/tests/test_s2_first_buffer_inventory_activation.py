from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    BUFFER_INVENTORY_SMOKE_SUMMARY_PATH,
    LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_MEMO,
    PROMOTION_DECISION_TEMPLATE,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import (
    build_liquid_steel_smoke_model,
    validate_liquid_steel_smoke_inputs,
)
from steel.liquid_steel_smoke_runner import _available_solver, run_liquid_steel_smoke_cases

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_s210b_inventory_artifacts_exist_and_validate():
    assert LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_MEMO.exists()
    assert BUFFER_INVENTORY_SMOKE_SUMMARY_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["liquid_steel_first_buffer_inventory_activation_memo_present"] is True
    assert payload["buffer_inventory_smoke_summary_rows_checked"] == 4
    assert payload["buffer_inventory_active_store_rows_checked"] == 6


def test_s210b_first_buffers_mode_activates_only_ready_stores():
    c0_prepared = validate_liquid_steel_smoke_inputs(
        configuration_id="C0_current_BF_BOF_reference",
        inventory_mode="first_buffers",
    )
    c1_prepared = validate_liquid_steel_smoke_inputs(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        inventory_mode="first_buffers",
    )

    assert c0_prepared.validation_report.active_store_ids == ("c0_hot_metal_buffer",)
    assert set(c1_prepared.validation_report.active_store_ids) == {"c1_hot_metal_buffer", "c1_dri_hdri_buffer"}
    refused_reasons = {row.reason for row in c1_prepared.validation_report.refused_rows}
    assert "store_not_activation_ready" in refused_reasons


def test_s210b_inventory_model_couples_stores_to_process_flows():
    c0_model = build_liquid_steel_smoke_model(
        configuration_id="C0_current_BF_BOF_reference",
        inventory_mode="first_buffers",
    )
    c1_model = build_liquid_steel_smoke_model(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        inventory_mode="first_buffers",
    )

    assert c0_model.s2_metadata["inventory_scope_active"] is True
    assert c1_model.s2_metadata["inventory_scope_active"] is True
    assert c0_model.s2_model_stats.binaries == 0
    assert c1_model.s2_model_stats.binaries == 0

    c0_production = str(c0_model.internal_carrier_production["hot_metal", 0].expr)
    c0_consumption = str(c0_model.internal_carrier_consumption["hot_metal", 0].expr)
    assert "process_activity[c0_blast_furnace,0]" in c0_production
    assert "process_activity[c0_bof_converter,0]" in c0_consumption

    c1_hot_metal_production = str(c1_model.internal_carrier_production["hot_metal", 0].expr)
    c1_hot_metal_consumption = str(c1_model.internal_carrier_consumption["hot_metal", 0].expr)
    c1_dri_production = str(c1_model.internal_carrier_production["DRI_or_HDRI", 0].expr)
    c1_dri_consumption = str(c1_model.internal_carrier_consumption["DRI_or_HDRI", 0].expr)
    assert "process_activity[c1_blast_furnace,0]" in c1_hot_metal_production
    assert "process_activity[c1_bof_converter,0]" in c1_hot_metal_consumption
    assert "process_activity[c1_ng_drp,0]" in c1_dri_production
    assert "process_activity[c1_eaf,0]" in c1_dri_consumption


def test_s210b_inventory_builder_reads_dev_capacity_and_cyc50_boundary():
    c1_model = build_liquid_steel_smoke_model(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        inventory_mode="first_buffers",
    )
    assert c1_model.s2_metadata["active_store_count"] == 2
    assert set(c1_model.s2_metadata["active_store_ids"]) == {"c1_hot_metal_buffer", "c1_dri_hdri_buffer"}

    hot_metal_terminal = str(c1_model.terminal_inventory["c1_hot_metal_buffer"].expr)
    dri_terminal = str(c1_model.terminal_inventory["c1_dri_hdri_buffer"].expr)
    assert "159.8172" in hot_metal_terminal
    assert "209.284423516" in dri_terminal


def test_s210b_runner_reports_inventory_metadata_in_build_only_mode(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",),
        horizon_hours=24,
        target_variant="feasible_smoke",
        inventory_mode="first_buffers",
        solve_if_available=False,
        output_root=tmp_path,
    )
    result = payload["results"][0]
    run_dir = Path(result["run_dir"])

    resolved = _load_json(run_dir / "resolved_config.json")
    solve_summary = _load_json(run_dir / "solve_summary.json")
    model_stats = _load_json(run_dir / "model_stats.json")

    assert resolved["inventory_mode"] == "first_buffers"
    assert resolved["inventory_active"] is True
    assert resolved["active_store_count"] == 2
    assert set(resolved["active_store_ids"]) == {"c1_hot_metal_buffer", "c1_dri_hdri_buffer"}
    assert model_stats["inventory_active"] is True
    assert solve_summary["inventory_summary"]["inventory_active"] is True
    assert solve_summary["inventory_summary"]["active_store_count"] == 2
    assert solve_summary["inventory_summary"]["cyc50_satisfied"] is None


def test_s210b_runner_can_solve_feasible_case_with_first_buffers_when_solver_exists(tmp_path: Path):
    solver_name, _ = _available_solver()
    if solver_name is None:
        pytest.skip("No LP solver available for guarded first-buffer smoke solve test.")

    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C0_current_BF_BOF_reference",),
        horizon_hours=24,
        target_variant="feasible_smoke",
        inventory_mode="first_buffers",
        solve_if_available=True,
        output_root=tmp_path,
    )
    solve_summary = payload["results"][0]["solve_summary"]
    assert solve_summary["solver_name"] == solver_name
    assert solve_summary["termination_condition"] in {"optimal", "feasible"}
    assert solve_summary["inventory_summary"]["cyc50_satisfied"] is True
    assert solve_summary["production_target_achieved"] is not None


def test_s210b_summary_register_and_zero_row_surfaces_remain_guarded():
    summary = pd.read_csv(BUFFER_INVENTORY_SMOKE_SUMMARY_PATH, dtype=str, keep_default_na=False)
    assert len(summary) == 4
    assert summary["inventory_mode"].eq("first_buffers").all()
    assert summary["inventory_active"].str.lower().eq("true").all()
    assert summary["shortfall_slack_active"].str.lower().eq("false").all()
    assert summary["downstream_active"].str.lower().eq("false").all()
    assert summary["thesis_usability"].str.lower().eq("false").all()
    assert summary.loc[summary["configuration_id"].eq("C0_current_BF_BOF_reference"), "active_store_ids"].eq("c0_hot_metal_buffer").all()
    assert summary.loc[summary["configuration_id"].eq("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"), "active_store_ids"].eq("c1_dri_hdri_buffer;c1_hot_metal_buffer").all()

    assert len(PROMOTION_DECISION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_s210b_surface_excludes_later_stage_logic():
    import steel.liquid_steel_smoke_builder as builder_module
    import steel.liquid_steel_smoke_runner as runner_module

    builder_source = inspect.getsource(builder_module).lower()
    runner_source = inspect.getsource(runner_module).lower()
    for blocked_term in ("nonanticipativity", "scenario_probability", "submitted_bids", "reserve_capacity", "price_taking", "electrolyser"):
        assert blocked_term not in builder_source
        assert blocked_term not in runner_source
