from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys

import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    LIQUID_STEEL_SMOKE_DIAGNOSTICS_MEMO,
    LIQUID_STEEL_SMOKE_RUNNER_MODULE,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import LiquidSteelSmokeBuilderError
from steel.liquid_steel_smoke_runner import _available_solver, run_liquid_steel_smoke_cases

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_s29b_runner_artifacts_exist_and_governance_reports_them():
    assert LIQUID_STEEL_SMOKE_RUNNER_MODULE.exists()
    assert LIQUID_STEEL_SMOKE_DIAGNOSTICS_MEMO.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["liquid_steel_smoke_runner_module_present"] is True
    assert payload["liquid_steel_smoke_diagnostics_memo_present"] is True


def test_s29b_c0_build_only_run_produces_guarded_diagnostics(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C0_current_BF_BOF_reference",),
        horizon_hours=24,
        solve_if_available=False,
        output_root=tmp_path,
    )
    result = payload["results"][0]
    run_dir = Path(result["run_dir"])

    assert payload["thesis_usability"] is False
    assert result["solve_summary"]["solve_status"] == "not_attempted_solver_unavailable"
    assert run_dir.exists()

    resolved = _load_json(run_dir / "resolved_config.json")
    manifest = _load_json(run_dir / "input_manifest.json")
    model_stats = _load_json(run_dir / "model_stats.json")
    validation = _load_json(run_dir / "input_validation_summary.json")
    solve_summary = _load_json(run_dir / "solve_summary.json")

    assert resolved["thesis_usability"] is False
    assert resolved["target_variant"] == "feasible_smoke"
    assert resolved["input_surface"] == "s2_provisional_dev_input"
    assert resolved["approved_input_used"] is False
    assert resolved["inventory_active"] is False
    assert resolved["downstream_active"] is False
    assert resolved["energy_cost_emissions_active"] is False
    assert resolved["market_logic_active"] is False
    assert manifest["input_surface"] == "s2_provisional_dev_input"
    assert manifest["selected_target_variant"] == "feasible_smoke"
    assert model_stats["binary_count"] == 0
    assert model_stats["target_variant"] == "feasible_smoke"
    assert model_stats["objective_type"] == "minimise_overproduction_dev_only"
    assert model_stats["shortfall_slack_active"] is False
    assert model_stats["inventory_active"] is False
    assert model_stats["downstream_active"] is False
    assert "c0_blast_furnace" in model_stats["active_process_units"]
    assert validation["encountered_non_executable_row"] is True
    assert validation["selected_target_variant"] == "feasible_smoke"
    assert validation["capacity_diagnostic"]["hard_target_without_slack"] is True
    assert validation["capacity_diagnostic"]["likely_infeasible_due_capacity_gap"] is False
    assert solve_summary["hard_target_without_slack"] is True
    assert solve_summary["target_variant"] == "feasible_smoke"
    assert solve_summary["production_target_value"] == model_stats["target_value"]
    assert solve_summary["production_target_achieved"] is None
    assert solve_summary["overproduction"] is None
    assert solve_summary["production_target_residual"] is None


def test_s29b_c1_build_only_run_produces_guarded_diagnostics(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",),
        horizon_hours=24,
        solve_if_available=False,
        output_root=tmp_path,
    )
    result = payload["results"][0]
    run_dir = Path(result["run_dir"])

    model_stats = _load_json(run_dir / "model_stats.json")
    validation = _load_json(run_dir / "input_validation_summary.json")

    assert model_stats["binary_count"] == 0
    assert set(model_stats["active_process_units"]) == {"c1_blast_furnace", "c1_bof_converter", "c1_ng_drp", "c1_eaf"}
    assert validation["selected_target_variant"] == "feasible_smoke"
    assert validation["capacity_diagnostic"]["likely_infeasible_due_capacity_gap"] is False
    refused_reasons = {row["reason"] for row in validation["refused_rows"]["rows"]}
    assert "inventory_scope_deferred" in refused_reasons
    assert "downstream_or_casting_out_of_scope" in refused_reasons


def test_s29c_runner_can_select_stress_infeasible_original_variant(tmp_path: Path):
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",),
        horizon_hours=24,
        target_variant="stress_infeasible_original",
        solve_if_available=False,
        output_root=tmp_path,
    )
    result = payload["results"][0]
    run_dir = Path(result["run_dir"])

    resolved = _load_json(run_dir / "resolved_config.json")
    validation = _load_json(run_dir / "input_validation_summary.json")
    solve_summary = _load_json(run_dir / "solve_summary.json")

    assert payload["target_variant"] == "stress_infeasible_original"
    assert resolved["target_variant"] == "stress_infeasible_original"
    assert resolved["objective_type"] == "minimise_overproduction_dev_only"
    assert resolved["shortfall_slack_active"] is False
    assert validation["selected_target_variant"] == "stress_infeasible_original"
    assert validation["capacity_diagnostic"]["likely_infeasible_due_capacity_gap"] is True
    assert solve_summary["target_variant"] == "stress_infeasible_original"


def test_s29c_runner_can_attempt_a_real_feasible_smoke_solve_when_solver_exists(tmp_path: Path):
    solver_name, _solver = _available_solver()
    if solver_name is None:
        pytest.skip("No LP solver available for guarded smoke solve test.")

    payload = run_liquid_steel_smoke_cases(
        configuration_ids=("C0_current_BF_BOF_reference",),
        horizon_hours=24,
        target_variant="feasible_smoke",
        solve_if_available=True,
        output_root=tmp_path,
    )
    result = payload["results"][0]
    solve_summary = result["solve_summary"]

    assert solve_summary["solver_name"] == solver_name
    assert solve_summary["hard_target_without_slack"] is True
    assert solve_summary["termination_condition"] in {"optimal", "feasible"}
    assert solve_summary["production_target_achieved"] is not None
    assert solve_summary["overproduction"] is not None
    assert solve_summary["production_target_residual"] is not None
    assert solve_summary["overproduction_positive"] in {True, False}
    assert solve_summary["overproduction_diagnostic_hint"] is not None


def test_s29b_runner_refuses_approved_input_surface(tmp_path: Path):
    with pytest.raises(LiquidSteelSmokeBuilderError, match="s2_approved_model_input"):
        run_liquid_steel_smoke_cases(
            configuration_ids=("C0_current_BF_BOF_reference",),
            horizon_hours=24,
            solve_if_available=False,
            provisional_dev_input_root=APPROVED_INPUT_ROOT,
            output_root=tmp_path,
        )


def test_s29b_runner_surface_excludes_later_stage_logic():
    source = inspect.getsource(sys.modules["steel.liquid_steel_smoke_runner"]).lower()
    assert "from pyomo.environ import binary" not in source
    assert "nonanticipativity" not in source
    assert "scenario_probability" not in source
    assert "submitted_bids" not in source
    assert "reserve_capacity" not in source
