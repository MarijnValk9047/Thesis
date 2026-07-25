from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.c5_tata_benchmark_prescreen import (
    C0,
    C1,
    DEFAULT_CONFIG_PATH,
    PrescreenError,
    build_boundary_bridge_audit,
    build_prescreen,
    build_user_authorized_prescreen,
    candidate_definitions,
    load_config,
)

USER_AUTHORIZED_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs/steel_c5_user_authorized_full_site_emulation.yaml"
)


def test_historical_candidate_design_remains_bounded_provenance():
    config = load_config(DEFAULT_CONFIG_PATH)
    candidates = candidate_definitions(config)
    assert len(candidates) == 22
    assert {row["wag_normalized_position"] for row in candidates} == {
        index / 10 for index in range(11)
    }
    assert {row["vn25_electricity_efficiency"] for row in candidates} == {
        0.34,
        0.345,
    }
    assert len([row for row in candidates if row["source_baseline"]]) == 1
    assert all(1200 <= row["bfg_generation_nm3_per_t_hot_metal"] <= 2000 for row in candidates)
    assert all(280 <= row["cog_generation_m3_per_t_dry_coal"] <= 450 for row in candidates)
    assert all(50 <= row["bofg_generation_nm3_per_t_liquid_steel"] <= 100 for row in candidates)


def test_prescreen_fails_closed_when_scored_rows_are_not_calibration_targets():
    config = load_config(DEFAULT_CONFIG_PATH)
    with pytest.raises(PrescreenError, match="not active calibration targets"):
        build_prescreen(config)


def test_boundary_bridge_audit_is_derived_from_accepted_ledgers():
    config = load_config(DEFAULT_CONFIG_PATH)
    derived = build_boundary_bridge_audit(config)
    assert [row["configuration_id"] for row in derived] == [C0, C1]
    assert all(
        row["boundary_class"] == "comparable_only_after_boundary_bridge"
        and row["export_status"] == "prohibited"
        and abs(row["gap_decomposition_residual_twh_y"]) <= 1e-12
        for row in derived
    )
    assert derived[0]["NG_generator_electricity_twh_y"] == pytest.approx(0.0)
    assert derived[1]["NG_generator_electricity_twh_y"] == pytest.approx(0.066938008)
    assert derived[1]["WAG_generator_electricity_twh_y"] == pytest.approx(0.676757530)
    assert derived[1]["generator_internal_electricity_total_twh_y"] == pytest.approx(
        derived[1]["WAG_generator_electricity_twh_y"]
        + derived[1]["NG_generator_electricity_twh_y"]
    )

    output_root = Path(__file__).resolve().parents[4] / config["output_root"]
    with (output_root / "athanasiadis_wag_electricity_boundary_bridge_audit.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        snapshot = list(csv.DictReader(handle))
    assert len(snapshot) == 2
    for actual, expected in zip(snapshot, derived):
        assert actual["configuration_id"] == expected["configuration_id"]
        for field in (
            "WAG_generator_electricity_twh_y",
            "NG_generator_electricity_twh_y",
            "generator_internal_electricity_total_twh_y",
            "technical_WAG_potential_twh_y",
            "WAG_electricity_gap_twh_y",
            "reconstructed_carrier_residual_mwh_y",
        ):
            assert float(actual[field]) == pytest.approx(float(expected[field]), abs=1e-8)


def test_generated_checkpoint_three_remains_historical_and_checkpoint_eight_is_closed():
    config = load_config(DEFAULT_CONFIG_PATH)
    output_root = Path(__file__).resolve().parents[4] / config["output_root"]
    summary = json.loads((output_root / "run_summary.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((output_root / "checkpoint_state.json").read_text(encoding="utf-8"))
    assert summary["historical_prescreen_candidate_count"] == 22
    assert summary["candidate_count"] == 5
    assert summary["retained_candidate_count"] == 0
    assert summary["retained_rolling_candidate_count"] == 0
    assert set(summary["scored_target_ids"]) == {
        "mer_c0_kgf1_coke_1_0",
        "mer_c0_kgf2_coke_0_8",
        "mer_c1_kgf1_coke_1_0",
        "mer_c0_pefa_output_4_6",
        "mer_c1_pefa_output_4_0_5_0",
    }
    assert summary["independent_validation_in_score"] is False
    assert summary["decision"] == "source_valid_emulation_rejected"
    assert summary["status"] == "source_valid_emulation_rejected"
    assert summary["independent_review_required"] is False
    assert summary["independent_reviewer_decision"] == "complete"
    assert summary["promotion_status"] == "source_valid_emulation_rejected"
    assert checkpoint["completed_checkpoint"] == 8
    assert checkpoint["calibration_authorized"] is False
    assert checkpoint["rolling_or_solver_run_performed"] is False
    assert checkpoint["retained_rolling_candidate_count"] == 0
    assert checkpoint["checkpoint_9_status"] == "not_started_no_eligible_promoted_candidate"


def test_user_authorized_design_has_baseline_plus_27_one_family_candidates():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    result = build_user_authorized_prescreen(config)
    candidates = result["candidates"]
    assert len(candidates) == 28
    assert sum(row["source_baseline"] for row in candidates) == 1
    assert {row["background_share"] for row in candidates if not row["source_baseline"]} == {
        0.05, 0.15, 0.25
    }
    central = {"BFG": 1600.0, "COG": 365.0, "BOFG": 75.0}
    for row in candidates:
        moved_carriers = [
            carrier
            for carrier, value in central.items()
            if row[f"{carrier}_yield"] != value
        ]
        assert len(moved_carriers) <= 1
        if row["parameter_family"] == "named_process_electricity_intensity":
            assert moved_carriers == []
            assert row["electricity_intensity_scale"] in {0.75, 1.25}


def test_user_authorized_named_electricity_selection_is_result_independent():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    result = build_user_authorized_prescreen(config)
    baseline = result["baseline"]["configurations"]
    assert baseline[C0]["selected_electricity_process"] == "BF"
    assert baseline[C1]["selected_electricity_process"] == "EAF_arc"
    selected = [
        row for row in result["candidates"]
        if row["parameter_family"] == "named_process_electricity_intensity"
    ]
    assert selected
    assert {row["selected_electricity_process_c0"] for row in selected} == {"BF"}
    assert {row["selected_electricity_process_c1"] for row in selected} == {"EAF_arc"}
    assert all("largest baseline" in row["selection_rule"] for row in selected)


def test_user_authorized_scores_stay_separate_and_co2_bridge_is_visible():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    result = build_user_authorized_prescreen(config)
    assert len(result["retained"]) == 5
    assert result["retained"][0]["candidate_id"] == "source_driven_baseline"
    for row in result["scorecard"]:
        assert row["score_families_kept_separate"] is True
        assert "selection_score_explained_sum" not in row
        for prefix in ("c0_gross", "c1_gross", "c0_wag", "c1_wag", "c0_ng", "c1_ng"):
            assert f"{prefix}_absolute_relative_error" in row
    first_order = [row for row in result["co2"] if row["ledger"] == "first_order_full_site_CO2"]
    mode_b = [row for row in result["co2"] if row["ledger"] == "Mode_B_explicit_fuel_CO2"]
    assert len(first_order) == len(mode_b) == 56
    assert all(row["explicit_nonnegative_constant_mt"] >= 0 for row in first_order)
    assert all(row["total_mt"] <= row["target_mt"] + 1e-9 for row in first_order)
    assert all(row["included_in_mode_b"] is False for row in first_order)
    assert all(row["included_in_mode_b"] is True for row in mode_b)


def test_checkpoint3_retention_repairs_background_controls_and_dominance():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    result = build_user_authorized_prescreen(config)
    retained = [row["candidate_id"] for row in result["retained"]]
    assert retained == [
        "source_driven_baseline",
        "bg25_central_no_movement",
        "bg15_central_no_movement",
        "bg25_single_process_electricity_high",
        "bg25_cog_yield_high",
    ]
    by_id = {row["candidate_id"]: row for row in result["scorecard"]}
    assert by_id["bg25_central_no_movement"]["source_deviation_yield_relative_sum"] == 0.0
    assert by_id["bg15_central_no_movement"]["source_deviation_yield_relative_sum"] == 0.0
    cog = by_id["bg25_cog_yield_high"]
    for dominated_id in ("bg25_bfg_yield_high", "bg25_bofg_yield_high"):
        dominated = by_id[dominated_id]
        assert cog["c0_gross_absolute_relative_error"] == dominated["c0_gross_absolute_relative_error"]
        assert cog["c1_gross_absolute_relative_error"] == dominated["c1_gross_absolute_relative_error"]
        assert cog["c0_wag_absolute_relative_error"] <= dominated["c0_wag_absolute_relative_error"]
        assert cog["c1_wag_absolute_relative_error"] < dominated["c1_wag_absolute_relative_error"]
        assert cog["source_deviation_yield_relative_sum"] < dominated["source_deviation_yield_relative_sum"]
        assert dominated["retained"] is False
        assert "excluded_strictly_dominated" in dominated["retention_reason"]


def test_user_authorized_guardrails_and_raw_anchor_use_are_explicit():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    result = build_user_authorized_prescreen(config)
    assert len(result["guardrails"]) == 56
    assert all(not row["unit_failure"] for row in result["guardrails"])
    assert all(not row["carrier_eligibility_failure"] for row in result["guardrails"])
    assert all(not row["double_counting_failure"] for row in result["guardrails"])
    assert all(not row["background_residual_mixing_failure"] for row in result["guardrails"])
    assert all(abs(row["electricity_identity_residual_mwh"]) <= 1e-6 for row in result["guardrails"])
    assert all(row["residual_ng_reported_only"] for row in result["ng"])
    baseline = next(row for row in result["scorecard"] if row["source_baseline"])
    assert baseline["c0_wag_target"] == pytest.approx(2.74)
    assert baseline["c1_wag_target"] == pytest.approx(1.23)


def test_generated_user_authorized_checkpoint_three_bundle_is_minimal_and_complete():
    config = load_config(USER_AUTHORIZED_CONFIG_PATH)
    output_root = Path(__file__).resolve().parents[4] / config["output_root"]
    required = {
        "target_overlay_snapshot.csv",
        "parameter_overlay_snapshot.csv",
        "candidate_scorecard.csv",
        "background_sensitivity.csv",
        "wag_reconciliation.csv",
        "ng_comparison.csv",
        "co2_ledgers.csv",
        "parameter_movements_and_exceptions.csv",
        "physical_guardrails.csv",
        "input_manifest.json",
        "resolved_config.yaml",
        "run_summary.json",
        "checkpoint_state.json",
        "registry_entry.json",
        "code_version.json",
        "warnings_and_limitations.md",
        "README.md",
    }
    assert required.issubset({path.name for path in output_root.iterdir()})
    summary = json.loads((output_root / "run_summary.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((output_root / "checkpoint_state.json").read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["candidate_count"] == 28
    assert summary["structured_candidate_count"] == 27
    assert summary["retained_candidate_count"] <= 5
    assert summary["retained_candidate_ids"] == [
        "source_driven_baseline",
        "bg25_central_no_movement",
        "bg15_central_no_movement",
        "bg25_single_process_electricity_high",
        "bg25_cog_yield_high",
    ]
    assert summary["retained_structured_background_shares"] == [0.15, 0.25]
    assert summary["retained_ranking_background_boundary_dominated"] is False
    assert summary["solver_or_rolling_run_performed"] is False
    assert checkpoint["completed_checkpoint"] == 3
    assert checkpoint["calibration_promotion_authorized"] is False
