from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.c5_transparent_emulation_prescreen import (  # noqa: E402
    DEFAULT_CONFIG,
    REJECTION_CODES,
    _candidate_rows,
    _family_error_rows,
    _kgf_baseline_mt_y,
    _pefa_baseline_mt_y,
    _scorecard_rows,
    _structural_checks,
    _target_rows,
    load_prescreen_config,
)


RUN_DIR = ROOT / "data/03_Optimisation/runs/steel_c5_tata_benchmark_v1_20260721"


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_design_is_one_round_one_family_five_points_and_no_solver():
    config = load_prescreen_config(DEFAULT_CONFIG)
    assert config["design"]["round_count"] == 1
    assert config["design"]["maximum_rounds"] == 2
    assert config["design"]["parameter_family_count"] == 1
    assert config["design"]["maximum_parameter_families"] == 2
    assert config["design"]["overlay_candidates"]["c0_pefa_mt_y"] == 4.6
    assert config["design"]["overlay_candidates"]["c1_pefa_mt_y"] == [4.0, 4.25, 4.5, 4.75, 5.0]
    assert config["design"]["source_central"]["c1_pefa_mt_y"] == config["design"]["source_ranges"]["c1_pefa_mt_y"][1] == 5.0
    assert config["design"]["annual_band_not_hourly_flexibility"] is True
    assert config["prohibitions"]["solver_runs_enabled"] is False
    assert config["prohibitions"]["held_out_dri_target_used"] is False
    assert config["prohibitions"]["held_out_periods_used"] is False


def test_pefa_hard_linkage_gates_reject_every_overlay_before_rolling():
    config = load_prescreen_config(DEFAULT_CONFIG)
    targets = _target_rows(config)
    kgf = _kgf_baseline_mt_y(config)
    pefa = _pefa_baseline_mt_y(config)
    candidates = _candidate_rows(config, pefa)
    family = _family_error_rows(
        candidates=candidates,
        targets=targets,
        kgf_baseline=kgf,
        config=config,
    )
    scorecard = _scorecard_rows(candidates=candidates, family_rows=family, config=config)
    checks = _structural_checks(config)

    assert len(candidates) == 6
    overlays = [row for row in scorecard if row["candidate_id"] != "source_driven_baseline"]
    assert len(overlays) == 5
    assert not any(row["rolling_eligible"] for row in scorecard)
    assert {row["hard_rejection_count"] for row in overlays} == {len(REJECTION_CODES)}
    assert {row["hard_rejection_codes"] for row in overlays} == {";".join(REJECTION_CODES)}
    assert [row["check_id"] for row in checks if row["status"] == "fail"] == [
        "pefa_output_to_bf_or_drp_consumption",
        "fired_pellet_inventory_identity",
        "fired_pellet_terminal_use_reconciliation",
    ]


def test_separate_family_errors_and_penalties_are_explicit():
    scorecard = _rows(RUN_DIR / "checkpoint8_candidate_scorecard.csv")
    assert len(scorecard) == 6
    best_raw_fit = next(row for row in scorecard if row["candidate_id"] == "pefa_c0_4p60_c1_5p00")
    assert float(best_raw_fit["pefa_family_mean_absolute_normalised_error"]) == 0.0
    assert float(best_raw_fit["kgf_family_mean_absolute_normalised_error"]) > 0.0
    assert float(best_raw_fit["direct_target_overlap_penalty_weighted"]) == 0.25
    assert float(best_raw_fit["source_central_deviation_penalty_weighted"]) == 0.0
    assert best_raw_fit["prescreen_decision"] == "rejected_before_rolling"
    assert best_raw_fit["rolling_eligible"] == "False"

    family = _rows(RUN_DIR / "checkpoint8_target_family_errors.csv")
    assert {row["target_family"] for row in family} == {
        "kgf_annual_coke_output",
        "pefa_annual_fired_pellet_output",
    }
    assert {row["held_out_target_used"] for row in family} == {"False"}
    assert {row["held_out_period_used"] for row in family} == {"False"}
    assert all(row["model_value_raw"] and row["signed_residual_raw"] for row in family)


def test_checkpoint_closeout_retains_source_baseline_and_skips_rolling():
    state = json.loads((RUN_DIR / "checkpoint_state.json").read_text(encoding="utf-8"))
    assert state["completed_checkpoint"] == 8
    assert state["analytical_overlay_candidate_count"] == 5
    assert state["retained_rolling_candidate_count"] == 0
    assert state["checkpoint_9_status"] == "not_started_no_eligible_promoted_candidate"
    assert state["checkpoint_10_status"] == "not_applicable_no_retained_candidate"
    assert state["promotion_status"] == "source_valid_emulation_rejected"
    assert state["decision"] == "source_valid_emulation_rejected"
    assert state["status"] == "source_valid_emulation_rejected"
    assert state["independent_review_required"] is False
    assert state["independent_reviewer_decision"] == "complete"
    assert state["rolling_or_solver_run_performed"] is False
    assert state["held_out_targets_used"] is False
    assert state["held_out_periods_used"] is False
    assert state["source_driven_behavioural_validation"] == "complete"
    assert state["strict_independent_quantitative_mer_validation_family_count"] == 0
    assert state["mer_c1_dri_output_2_8_role"] == "scenario_definition_consistency_check"
    assert state["source_baseline_retention_evidence_basis"] == (
        "physical_and_behavioural_not_independent_quantitative_MER_validation"
    )

    rolling = _rows(RUN_DIR / "checkpoint9_rolling_candidate_decision.csv")
    assert rolling == [
        {
            "checkpoint": "9",
            "status": "not_started_no_eligible_promoted_candidate",
            "retained_candidate_count": "0",
            "rolling_candidate_count": "0",
            "validation_period_count_used": "0",
            "solver_run_performed": "False",
            "decision": "source_valid_emulation_rejected",
            "source_driven_baseline_retained": "True",
            "checkpoint_10_status": "not_applicable_no_retained_candidate",
            "reason": ";".join(REJECTION_CODES),
        }
    ]
