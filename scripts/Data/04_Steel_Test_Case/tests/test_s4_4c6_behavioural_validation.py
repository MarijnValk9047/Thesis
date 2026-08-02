from __future__ import annotations

from dataclasses import replace
from datetime import date
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_behavioural_validation import (  # noqa: E402
    aggregate_path_feasibility_case_artifacts,
    CONFIGURATION_IDS,
    _base_context_config,
    _audit_aggregated_case_artifacts,
    _comparison_expected_objective_eur,
    _case_local_feasibility_patterns,
    _controlled_synthetic_feasibility_patterns,
    _final_periods,
    _load_reusable_planning_cache,
    _non_final_rolling_week_inputs,
    _phase_decision,
    _run_constraint_generated_case,
    _rolling_week_plant_checks,
    run_s0_c1_constraint_generation_gate,
    run_single_path_feasibility_case_gate,
    solve_constraint_generated_bid_plan,
    _validation_feasibility_patterns,
    _within_money_tolerance,
    _load_shape_library,
    audit_phase0_evidence,
    bf_own_capacity_utilisation,
    build_case_manifest,
    build_plant_eligibility_records,
    build_shadow_overlay,
    build_synthetic_bundles,
    dri_change_correlations,
    evaluate_plant_behaviour,
    load_behavioural_config,
    run_full_path_feasibility_behavioural_gate,
    run_non_final_rolling_week_gate,
    run_path_feasibility_blocker_gate,
    select_shadow_days,
)
from steel.s4_4c6_phase6d_eaf_heat_state_one_day import (  # noqa: E402
    EXPECTED_COST_INCUMBENT,
)
from steel.s4_4c6_representative_regime_counterfactual import (  # noqa: E402
    load_representative_config,
    load_study_frames,
)


@pytest.fixture(scope="module")
def governed_inputs() -> dict[str, object]:
    config = load_behavioural_config()
    representative = load_representative_config(config["representative_config"])
    frames = load_study_frames(representative)
    shape_library = _load_shape_library(frames)
    selection = select_shadow_days(config, frames, shape_library)
    synthetic = build_synthetic_bundles(config, frames, shape_library)
    overlay, _ = build_shadow_overlay(config, frames, shape_library, selection)
    manifest = build_case_manifest(config, selection)
    return {
        "config": config,
        "representative": representative,
        "frames": frames,
        "shape_library": shape_library,
        "selection": selection,
        "synthetic": synthetic,
        "synthetic_bundles": synthetic,
        "shadow_frames": replace(frames, qh_overlay=overlay),
        "manifest": manifest,
    }


def test_behavioural_contract_is_v1_donly_s10_and_maintenance_free() -> None:
    config = load_behavioural_config()
    contract = config["frozen_contract"]
    assert contract["planning_physical_tiebreak_mode"] == EXPECTED_COST_INCUMBENT
    assert not contract["planning_physical_tiebreak_solve_performed"]
    assert contract["bid_signature_symmetry_breaking"]
    assert contract["planning_solver_execution_mode"] == "sequential_pyomo"
    assert contract["gurobi_performance_options"] == {"MIPFocus": 1}
    assert contract["redispatch_physical_tiebreak_solve_performed"]
    assert contract["execution_recourse"]["active"]
    assert contract["execution_recourse"]["penalty_eur_per_mwh"] == pytest.approx(
        5000.0
    )
    assert not contract["forbidden_scope"]["imbalance_optimisation"]
    assert contract["forecast_horizon"] == "D_only"
    assert contract["scenario_count"] == 10
    assert contract["mip_gap_limit"] == pytest.approx(0.001)
    assert contract["economic_mip_gap_limit"] == pytest.approx(0.002)
    assert contract["price_insensitive_comparison_basis"] == (
        "frozen_flat80_dispatch_revalued_on_common_s10_without_replanning"
    )
    assert contract["physical_horizon_hours"] == 48
    assert not contract["weekly_eaf_maintenance_active"]
    assert not contract["annual_outage_active"]
    augmentation = contract["path_feasibility_augmentation"]
    assert augmentation == {
        "active": True,
        "lineage_role": "validation_derived_feasibility_only",
        "acceptance_contract": "canonical_bid_step_rank_mask_by_lead_position",
        "maximum_augmentation_rounds": 3,
        "maximum_patterns_added_per_round": 1,
        "bid_selection_mode": "expected_cost_incumbent",
        "unused_bid_step_fill": "analytical_zero_if_reconstruction_preserved",
        "additional_full_canonical_bid_milp_allowed": False,
        "economic_scenario_binary_incumbent_fix_required": False,
        "parent_round_restricted_bridge_active": True,
        "parent_round_bridge_fixed_scope": "economic_scenario_binaries_only",
        "parent_round_bridge_final_result_eligible": False,
        "parent_round_bridge_preservation_constraint_allowed": False,
        "parent_round_bridge_requires_full_expected_cost_resolve": True,
        "probability_allowed": False,
        "expected_cost_weight_allowed": False,
        "raw_shadow_price_transport_allowed": False,
        "final_test_period_source_allowed": False,
        "allowed_source_classes": [
            "development_shadow",
            "controlled_synthetic_validation",
        ],
        "controlled_synthetic_profiles_frozen_before_solve": True,
        "controlled_synthetic_pattern_application_scope": (
            "same_profile_development_only"
        ),
        "exact_zero_imbalance_required": True,
    }


def test_controlled_synthetic_patterns_are_non_final_and_probability_free(
    governed_inputs: dict[str, object],
) -> None:
    prepared = governed_inputs
    patterns = _controlled_synthetic_feasibility_patterns(prepared)
    assert len(patterns) == 4
    assert {row["source_profile_id"] for row in patterns} == {
        "S0_flat_reference",
        "S1_low_high_step",
        "S2_mirrored_step",
        "S3_negative_price_valley",
    }
    for pattern in patterns:
        assert pattern["source_class"] == "controlled_synthetic_validation"
        assert pattern["development_validation_case"]
        assert not pattern["development_shadow_case"]
        assert not pattern["final_test_case"]
        assert pattern["cutoff_status"] == (
            "pre_final_validation_only_not_origin_information"
        )
        assert not {
            "probability",
            "scenario_probability",
            "expected_cost_weight",
            "raw_prices_eur_per_mwh",
        }.intersection(pattern)


def test_combined_validation_pattern_library_is_deterministic_and_deduplicated(
    governed_inputs: dict[str, object],
) -> None:
    left = _validation_feasibility_patterns(governed_inputs)
    right = _validation_feasibility_patterns(governed_inputs)
    assert left == right
    acceptance_ids = {
        json.dumps(
            [
                row["market_grid"],
                row["bid_grid_id"],
                row["acceptance_mask_by_lead_position"],
            ],
            sort_keys=True,
        )
        for row in left
    }
    assert len(acceptance_ids) == len(left)
    assert {row["source_class"] for row in left} == {
        "development_shadow",
        "controlled_synthetic_validation",
    }


def test_synthetic_patterns_are_applied_only_to_the_matching_development_profile(
    governed_inputs: dict[str, object],
) -> None:
    manifest = governed_inputs["manifest"]
    assert isinstance(manifest, pd.DataFrame)
    s0 = manifest.loc[manifest["case_id"].eq("S0_C1_responsive")].iloc[0]
    s1 = manifest.loc[manifest["case_id"].eq("S1_C1_responsive")].iloc[0]
    for case, expected_profile in (
        (s0, "S0_flat_reference"),
        (s1, "S1_low_high_step"),
    ):
        patterns = _case_local_feasibility_patterns(
            governed_inputs, case.to_dict()
        )
        synthetic = [
            row
            for row in patterns
            if row["source_class"] == "controlled_synthetic_validation"
        ]
        assert len(synthetic) == 1
        assert synthetic[0]["source_profile_id"] == expected_profile
    shadow_case = manifest.loc[manifest["phase"].eq("shadow")].iloc[0]
    assert all(
        row["source_class"] == "development_shadow"
        for row in _case_local_feasibility_patterns(
            governed_inputs, shadow_case.to_dict()
        )
    )


def test_blocker_gate_persists_compact_three_process_reproducibility_hashes() -> None:
    source = inspect.getsource(run_path_feasibility_blocker_gate)
    for field in (
        "repaired_bid_curve_sha256",
        "repaired_scenario_dispatch_sha256",
        "repaired_clearing_sha256",
        "repaired_physical_dispatch_sha256",
        "repaired_next_state_sha256",
    ):
        assert field in source


def test_final_weeks_are_excluded_from_shadow_selection(governed_inputs: dict[str, object]) -> None:
    config = governed_inputs["config"]
    selection = governed_inputs["selection"]
    assert isinstance(config, dict)
    assert isinstance(selection, pd.DataFrame)
    periods = _final_periods(config)
    for day_text in selection["day"]:
        day = date.fromisoformat(day_text)
        assert all(not (start <= day <= end) for start, end in periods)
        assert min(
            (start - day).days if day < start else (day - end).days
            for start, end in periods
        ) >= 28
    assert not selection["final_test_case"].any()
    assert selection["development_shadow_case"].all()


def test_shadow_selection_is_deterministic_and_separated(governed_inputs: dict[str, object]) -> None:
    config = governed_inputs["config"]
    frames = governed_inputs["frames"]
    shape_library = governed_inputs["shape_library"]
    selected = governed_inputs["selection"]
    repeated = select_shadow_days(config, frames, shape_library)
    pd.testing.assert_frame_equal(selected, repeated)
    days = [date.fromisoformat(value) for value in selected["day"]]
    assert min(
        abs((left - right).days)
        for index, left in enumerate(days)
        for right in days[index + 1 :]
    ) >= 28


def test_shadow_overlay_is_exactly_mean_preserving(governed_inputs: dict[str, object]) -> None:
    overlay, _ = build_shadow_overlay(
        governed_inputs["config"],
        governed_inputs["frames"],
        governed_inputs["shape_library"],
        governed_inputs["selection"],
    )
    grouped = overlay.groupby(
        ["week_id", "path_kind", "scenario_id", "hour_start_utc"]
    )
    assert grouped.size().eq(4).all()
    assert grouped["quarterhour_delta"].mean().abs().max() <= 1e-10
    assert overlay["counterfactual"].all()


def test_synthetic_profiles_preserve_s10_probabilities_and_crn(governed_inputs: dict[str, object]) -> None:
    bundles = governed_inputs["synthetic"]
    reference = bundles["S0_flat_reference"][0]
    assert len(reference.scenario_prices) == 10
    assert sum(reference.scenario_probabilities.values()) == pytest.approx(1.0)
    reference_central = np.repeat(np.full(24, 160.0), 4)
    for profile_id, (bundle, _) in bundles.items():
        assert bundle.scenario_probabilities == reference.scenario_probabilities
        central = np.repeat(
            governed_inputs["config"]["synthetic"]["point_profiles_eur_per_mwh"][profile_id],
            4,
        )
        for scenario_id in bundle.scenario_prices:
            np.testing.assert_allclose(
                np.asarray(bundle.scenario_prices[scenario_id]) - central,
                np.asarray(reference.scenario_prices[scenario_id]) - reference_central,
                atol=1e-10,
                rtol=0.0,
            )


def test_synthetic_s30_uses_governed_support(
    governed_inputs: dict[str, object],
) -> None:
    bundles = build_synthetic_bundles(
        governed_inputs["config"],
        governed_inputs["frames"],
        governed_inputs["shape_library"],
        scenario_count=30,
    )
    bundle, actual = bundles["S0_flat_reference"]
    assert len(bundle.scenario_prices) == 30
    assert len(bundle.timestamps_utc) == len(actual.timestamps_utc) == 96
    assert sum(bundle.scenario_probabilities.values()) == pytest.approx(1.0)


def test_s0_c1_reusable_plan_has_matching_inputs_and_optimality_proof(
    governed_inputs: dict[str, object],
) -> None:
    config = governed_inputs["config"]
    bundle, actual = governed_inputs["synthetic"]["S0_flat_reference"]
    plan = _load_reusable_planning_cache(
        config["reusable_planning_cache"]["S0_C1_responsive"],
        bundle=bundle,
        actual=actual,
        configuration=CONFIGURATION_IDS["C1"],
        policy="QH-S10",
    )
    assert plan.solver["expected_cost_optimality_proof"] == (
        "frozen_parent_optimum_plus_current_feasibility_proof"
    )
    assert plan.solver["bid_curve_canonicalisation_performed"]
    assert plan.solver["bid_curve_canonical_tiebreak"] == (
        "minimum_total_volume_then_highest_willingness_price"
    )


def test_money_reconstruction_gate_matches_phase6d_numerical_slack() -> None:
    assert _within_money_tolerance(0.010000025853514671, 0.01)
    assert not _within_money_tolerance(0.010002, 0.01)


def test_flat80_dispatch_is_revalued_on_common_s10_without_replanning(
    governed_inputs: dict[str, object],
) -> None:
    bundle, _ = governed_inputs["synthetic"]["S1_low_high_step"]
    interval_count = len(bundle.timestamps_utc)
    imports = np.linspace(1.0, 2.0, interval_count)
    non_price_cost = 1234.5
    flat_cost = float(np.dot(imports, np.full(interval_count, 80.0)))
    plan = SimpleNamespace(
        policy="price-insensitive",
        scenario_dispatch=[
            {
                "economic_horizon_active": True,
                "scenario_id": "flat80",
                "market_interval_index": index,
                "planned_net_grid_import_mwh": float(imports[index]),
                "scenario_price_eur_per_mwh": 80.0,
            }
            for index in range(interval_count)
        ],
        solver={"expected_cost_reconstructed_eur": non_price_cost + flat_cost},
    )
    expected_prices = sum(
        float(bundle.scenario_probabilities[scenario_id])
        * np.asarray(prices, dtype=float)
        for scenario_id, prices in bundle.scenario_prices.items()
    )
    assert _comparison_expected_objective_eur(plan, bundle) == pytest.approx(
        non_price_cost + float(np.dot(imports, expected_prices))
    )


def test_synthetic_day_averages_are_frozen(governed_inputs: dict[str, object]) -> None:
    bundles = governed_inputs["synthetic"]
    expected = {
        "S0_flat_reference": 160.0,
        "S1_low_high_step": 160.0,
        "S2_mirrored_step": 160.0,
        "S3_negative_price_valley": 160.0,
    }
    for profile_id, mean in expected.items():
        assert np.mean(bundles[profile_id][0].point_prices) == pytest.approx(mean)


def test_case_manifest_has_fail_closed_nine_plus_thirteen_matrix(governed_inputs: dict[str, object]) -> None:
    manifest = build_case_manifest(
        governed_inputs["config"], governed_inputs["selection"]
    )
    assert len(manifest[manifest["phase"].eq("synthetic")]) == 9
    assert len(manifest[manifest["phase"].eq("shadow")]) == 13
    assert not manifest["final_test_case"].any()
    assert set(manifest["scenario_count"]) == {10}


def test_plant_eligibility_is_deterministic_and_frozen_before_solve(
    governed_inputs: dict[str, object],
) -> None:
    manifest = build_case_manifest(
        governed_inputs["config"], governed_inputs["selection"]
    )
    selected = manifest[
        manifest["case_id"].isin(
            ["S0_C1_responsive", "S1_C1_responsive", "S2_C1_responsive"]
        )
    ]
    prepared = {
        "config": governed_inputs["config"],
        "synthetic_bundles": governed_inputs["synthetic"],
    }
    first = build_plant_eligibility_records(prepared, selected)
    second = build_plant_eligibility_records(prepared, selected)
    assert first == second
    assert all(row["determination_stage"] == "pre_solve" for row in first)
    assert not any(row["uses_dispatch_or_actual_prices"] for row in first)
    assert not any(row["final_test_case"] for row in first)
    eaf = {
        row["case_id"]: row
        for row in first
        if row["mechanism"] == "eaf_heat_timing"
    }
    # S0 has a flat hourly anchor but the governed QH shape is intentionally
    # non-flat, so eligibility follows the actual ex-ante QH support.
    assert eaf["S0_C1_responsive"]["eligibility_status"] == "applicable"
    assert eaf["S1_C1_responsive"]["eligibility_status"] == "applicable"
    assert eaf["S2_C1_responsive"]["eligibility_status"] == "applicable"
    vn25 = [row for row in first if row["mechanism"] == "vn25_generation"]
    assert {row["case_id"] for row in vn25 if row["eligibility_status"] == "applicable"} == {
        "S0_C1_responsive",
        "S1_C1_responsive",
        "S2_C1_responsive",
    }


def test_route_substitution_is_pre_solve_not_applicable_with_frozen_reason(
    governed_inputs: dict[str, object],
) -> None:
    manifest = build_case_manifest(
        governed_inputs["config"], governed_inputs["selection"]
    )
    selected = manifest[manifest["case_id"].eq("S1_C1_responsive")]
    rows = build_plant_eligibility_records(
        {
            "config": governed_inputs["config"],
            "synthetic_bundles": governed_inputs["synthetic"],
        },
        selected,
    )
    route = next(
        row
        for row in rows
        if row["mechanism"] == "drp_eaf_vs_bf_bof_route_substitution"
    )
    assert route["eligibility_status"] == "not_applicable"
    assert route["binding_reason"] == (
        "frozen_one_day_route_quota_contract_does_not_prove_substitution_headroom"
    )


def test_final_case_is_rejected_from_plant_eligibility(
    governed_inputs: dict[str, object],
) -> None:
    manifest = build_case_manifest(
        governed_inputs["config"], governed_inputs["selection"]
    )
    selected = manifest[manifest["case_id"].eq("S1_C1_responsive")].copy()
    selected.loc[:, "final_test_case"] = True
    with pytest.raises(Exception, match="final-week case"):
        build_plant_eligibility_records(
            {
                "config": governed_inputs["config"],
                "synthetic_bundles": governed_inputs["synthetic"],
            },
            selected,
        )


def test_full_path_gate_flushes_eligibility_before_first_case_solve() -> None:
    source = inspect.getsource(run_full_path_feasibility_behavioural_gate)
    write_position = source.index('"plant_eligibility_manifest.json"')
    solve_loop_position = source.index("for case in selected.to_dict")
    assert write_position < solve_loop_position


def test_applicable_plant_checks_are_hard_and_attribute_named_response(
    governed_inputs: dict[str, object],
) -> None:
    manifest = build_case_manifest(
        governed_inputs["config"], governed_inputs["selection"]
    )
    selected = manifest[
        manifest["case_id"].isin(
            ["S1_C1_responsive", "S2_C1_responsive", "S3_C1_responsive"]
        )
    ]
    eligibility = build_plant_eligibility_records(
        {
            "config": governed_inputs["config"],
            "synthetic_bundles": governed_inputs["synthetic"],
        },
        selected,
    )
    common = {
        "phase": "synthetic",
        "ij01_named_ng_mwh": 0.0,
        "eaf_arc_cheap_mwh": 120.0,
        "eaf_arc_expensive_mwh": 20.0,
        "eaf_heat_starts_cheap": 4.0,
        "eaf_heat_starts_expensive": 2.0,
        "eaf_total_electricity_mwh": 500.0,
        "produced_t": 1000.0,
        "eaf_heat_starts": 6.0,
        "eaf_heat_taps": 6.0,
        "eaf_liquid_steel_output_t": 900.0,
        "eaf_dri_input_t": 700.0,
        "eaf_scrap_input_t": 200.0,
        "bf6_throughput_t": 600.0,
        "bof_throughput_t": 590.0,
        "hsm_throughput_t": 800.0,
        "dsp_output_t": 200.0,
        "vn25_above_break_even_interval_count": 48,
        "vn25_below_break_even_interval_count": 48,
        "vn25_electricity_above_break_even_mean_mwh_per_qh": 10.0,
        "vn25_electricity_below_break_even_mean_mwh_per_qh": 2.0,
        "net_import_above_break_even_mean_mwh_per_qh": 5.0,
        "net_import_below_break_even_mean_mwh_per_qh": 20.0,
        "vn25_electricity_mwh": 500.0,
        "vn25_named_ng_mwh": 0.0,
        "vn25_wag_mwh": 100.0,
        "flare_above_break_even_mean_mwh_per_qh": 0.0,
        "flare_below_break_even_mean_mwh_per_qh": 1.0,
        "response_materiality_threshold_mwh": 1.0,
    }
    results = pd.DataFrame(
        [{**common, "case_id": case_id} for case_id in selected["case_id"]]
    )
    checks = evaluate_plant_behaviour(results, eligibility, phase="synthetic")
    assert checks
    assert all(row["status"] == "pass" for row in checks if row["hard_gate"])
    named = next(
        row
        for row in checks
        if row["check_id"]
        == "at_least_one_named_eligible_c1_mechanism_responds_materially"
    )
    assert named["hard_gate"]
    assert named["status"] == "pass"


def test_v1_propagates_and_redispatch_tiebreak_contract_remains() -> None:
    representative = load_representative_config()
    context = _base_context_config(
        representative, market_granularity="quarterhour", horizon_hours=24
    )
    assert context.config["planning_physical_tiebreak_mode"] == EXPECTED_COST_INCUMBENT
    assert context.config["solver_seed"] == 0
    assert context.config["parent_round_restricted_bridge_active"]
    contract = representative["experiment_contract"]
    assert not contract["planning_physical_tiebreak_solve_performed"]
    assert contract["redispatch_physical_tiebreak_solve_performed"]


def test_constraint_generation_reuses_only_the_proven_parent_round_plan() -> None:
    source = inspect.getsource(solve_constraint_generated_bid_plan)
    assert "previous_round_plan: SteelBidPlan | None = None" in source
    assert "previous_round_plan if selected_paths else None" in source
    assert "previous_round_plan = plan" in source


def test_augmented_case_accepts_only_proven_hard_zero_conditional_recovery() -> None:
    source = inspect.getsource(_run_constraint_generated_case)
    assert 'conditional_gate["minimum_imbalance_mwh"]' in source
    assert '"hard_zero_economic_resolve_performed"' in source
    assert 'conditional_gate.get("economic_result_accepted", False)' in source
    assert 'conditional_gate.get("abc_comparison_eligible", False)' in source
    assert "still required the minimum-imbalance solve" not in source


def test_s0_gate_reads_conditional_imbalance_status_from_redispatch_solver() -> None:
    source = inspect.getsource(run_s0_c1_constraint_generation_gate)
    assert 'outcome["solver"]["redispatch"][' in source
    assert 'result["conditional_minimum_imbalance_solve_performed"]' not in source
    assert '"solver_diagnostics_artifact": "solver_diagnostics.json"' in source


def test_single_case_continuation_is_non_final_and_does_not_run_cross_case_gate() -> None:
    source = inspect.getsource(run_single_path_feasibility_case_gate)
    assert 'if bool(case["final_test_case"])' in source
    assert '"trajectory_count": 1' in source
    assert '"cross_case_plant_evaluation_pending": True' in source
    assert "evaluate_plant_behaviour(" not in source


def test_case_aggregation_is_solver_free_and_requires_exact_phase_coverage() -> None:
    source = inspect.getsource(aggregate_path_feasibility_case_artifacts)
    assert "solver.solve" not in source
    assert 'set(result_ids) != expected_ids' in source
    assert 'raw_text.split("=", 1)' in source
    assert "_audit_aggregated_case_artifacts(" in source
    assert '"case_artifact_reuse_audit.json"' in source
    assert 'if str(row["case_id"]) in expected_ids' in source
    assert "_apply_physical_comparison_contract(" in source
    assert '"comparison_contracts_reconstructed_from_frozen_config": True' in source
    assert '"solver_runs_started": 0' in source
    assert '"final_test_periods_read_or_solved": False' in source


def test_aggregate_reuse_audit_preserves_benchmark_scenario_semantics() -> None:
    source = inspect.getsource(_audit_aggregated_case_artifacts)
    assert 'result.get("policy") == "responsive"' in source
    assert 'else 1' in source
    assert 'float(planning["scenario_probability_sum"])' in source


def test_non_final_rolling_week_contract_and_inputs_are_frozen_and_leakage_free(
    governed_inputs: dict[str, object],
) -> None:
    rolling = _non_final_rolling_week_inputs(governed_inputs)
    contract = rolling["contract"]
    assert contract["week_start"] == "2025-06-16"
    assert contract["week_end"] == "2025-06-22"
    assert rolling["week_start"].weekday() == 0
    assert (rolling["week_end"] - rolling["week_start"]).days == 6
    assert len(rolling["experiments"]) == 6
    assert len(rolling["cases"]) == 42
    assert not rolling["cases"]["final_test_case"].any()
    assert not rolling["experiments"]["final_test_case"].any()
    assert set(rolling["experiments"]["configuration"]) == {"C0", "C1"}
    assert set(rolling["experiments"]["arm"]) == {
        "A_hourly",
        "B_qh_flat",
        "C_qh_shape",
    }
    assert len(rolling["prior_source_days"]) >= 3
    assert all(
        date.fromisoformat(str(pattern["source_delivery_day"]))
        < rolling["week_start"]
        for pattern in rolling["patterns"]
    )
    assert {str(pattern["market_grid"]) for pattern in rolling["patterns"]} == {
        "hourly",
        "quarterhour",
    }
    assert not any(bool(pattern["final_test_case"]) for pattern in rolling["patterns"])
    assert rolling["overlay"]["counterfactual"].all()


def test_non_final_rolling_week_runner_is_checkpointed_and_fail_closed() -> None:
    source = inspect.getsource(run_non_final_rolling_week_gate)
    assert "solve_constraint_generated_bid_plan(" in source
    assert "imbalance_penalty_eur_per_mwh=5000.0" in source
    assert '"resume_authorized": True' in source
    assert "_assert_run_execution_authorized(output, resume=False)" in source
    assert 'state.executed_hours != int(before["executed_hours"]) + 24' in source
    assert 'state.executed_hours == 168' in source
    assert 'a["expected_objective_lower_bound_eur"]' in source
    assert '- b["expected_objective_upper_bound_eur"]' in source
    assert 'a["expected_objective_upper_bound_eur"]' in source
    assert '- b["expected_objective_lower_bound_eur"]' in source
    assert '"final_test_periods_read_or_solved": False' in source
    assert 'output / "run_summary.json"' in source
    assert '"retention_status": "ignored_local_governed_diagnostic"' in source
    assert '"git_eligible": False' in source
    assert 'reason="non_final_rolling_week_gate_failed_closed"' in source


def test_rolling_week_plant_gate_requires_named_response_and_output_invariance() -> None:
    rows: list[dict[str, object]] = []
    for configuration in ("C0", "C1"):
        for arm_index, arm in enumerate(("A_hourly", "B_qh_flat", "C_qh_shape")):
            for offset in range(7):
                rows.append(
                    {
                        "phase": "rolling_validation",
                        "configuration": configuration,
                        "arm": arm,
                        "delivery_day": f"2025-06-{16 + offset:02d}",
                        "ij01_named_ng_mwh": 0.0,
                        "response_materiality_threshold_mwh": 1.0,
                        "eaf_arc_mwh": 100.0 + (arm_index if configuration == "C1" else 0.0),
                        "eaf_arc_cheap_mwh": 60.0,
                        "eaf_arc_expensive_mwh": 40.0,
                        "drp_electricity_mwh": 50.0,
                        "vn25_electricity_mwh": 20.0,
                        "boiler_named_ng_mwh": 10.0,
                        "flare_mwh": 5.0,
                        "produced_t": 1000.0,
                        "hsm_throughput_t": 800.0,
                        "dsp_output_t": 200.0,
                        "steam_unserved_t": 0.0,
                    }
                )
    eligibility = [
        {
            "phase": "rolling_validation",
            "configuration": "C1",
            "mechanism": "eaf_heat_timing",
            "eligibility_status": "applicable",
            "determination_stage": "pre_solve",
            "uses_dispatch_or_actual_prices": False,
            "final_test_case": False,
            "binding_reason": "c1_responsive_nonflat_profile",
        },
        {
            "phase": "rolling_validation",
            "configuration": "C1",
            "mechanism": "drp_eaf_vs_bf_bof_route_substitution",
            "eligibility_status": "not_applicable",
            "determination_stage": "pre_solve",
            "uses_dispatch_or_actual_prices": False,
            "final_test_case": False,
            "binding_reason": (
                "frozen_one_day_route_quota_contract_does_not_prove_"
                "substitution_headroom"
            ),
        },
    ]
    checks = _rolling_week_plant_checks(pd.DataFrame(rows), eligibility)
    assert checks
    assert all(row["status"] == "pass" for row in checks if row["hard_gate"])
    response = next(
        row for row in checks if row["check_id"] == "rolling_c1_named_physical_response"
    )
    assert response["status"] == "pass"


def test_fixed_residual_services_do_not_depend_on_price_profile() -> None:
    representative = load_representative_config()
    context = _base_context_config(
        representative, market_granularity="quarterhour", horizon_hours=24
    )
    frozen = {
        "electricity": dict(context.site_background_by_configuration),
        "ng": dict(context.site_ng_by_configuration),
        "steam": dict(context.site_steam_by_configuration),
        "co2": dict(context.site_co2_by_configuration),
    }
    repeated = _base_context_config(
        representative, market_granularity="quarterhour", horizon_hours=24
    )
    assert frozen["electricity"] == dict(repeated.site_background_by_configuration)
    assert frozen["ng"] == dict(repeated.site_ng_by_configuration)
    assert frozen["steam"] == dict(repeated.site_steam_by_configuration)
    assert frozen["co2"] == dict(repeated.site_co2_by_configuration)


def test_dri_metric_correlates_price_with_changes_not_levels() -> None:
    prices = [1.0, 2.0, 3.0, 4.0]
    inventory = [101.0, 103.0, 106.0, 110.0]
    pearson, spearman = dri_change_correlations(
        prices, inventory, initial_inventory=100.0
    )
    assert pearson == pytest.approx(1.0)
    assert spearman == pytest.approx(1.0)


def test_bf_utilisation_uses_own_interval_capacity() -> None:
    assert bf_own_capacity_utilisation([20.0, 25.0], [40.0, 50.0]) == pytest.approx(
        0.5
    )
    assert bf_own_capacity_utilisation([20.0], [None]) is None


def test_positive_economic_effect_is_not_an_acceptance_condition() -> None:
    config = load_behavioural_config()
    assert not config["directional_hypotheses"]["positive_economic_effect_required"]
    assert not config["frozen_contract"].get("positive_economic_effect_required", False)


def test_sources_are_directional_not_numerical_targets() -> None:
    hypotheses = load_behavioural_config()["directional_hypotheses"]
    assert not hypotheses["numerical_source_calibration_targets_allowed"]
    assert hypotheses["dri_metric"].endswith("not_level")
    assert hypotheses["bf_utilisation_denominator"] == "own_represented_interval_capacity"


def test_phase0_evidence_is_reused_without_new_solves() -> None:
    rows = audit_phase0_evidence(load_behavioural_config())
    assert len(rows) == 7
    assert all(row["reusable"] for row in rows)
    assert not any(row["new_solve_required"] for row in rows)


def test_gate_sequence_fails_closed_when_a_synthetic_case_is_missing() -> None:
    decision = _phase_decision(
        phase="synthetic",
        expected_case_ids={"a", "b"},
        results=[{"case_id": "a", "phase": "synthetic", "case_status": "pass"}],
        physical_checks=[],
        economic_checks=[],
    )
    assert decision["status"] == "block"
    assert decision["missing_or_failed_case_ids"] == ["b"]
    assert decision["blocking_case_diagnostics"] == []


def test_phase_decision_preserves_concise_blocking_diagnostic() -> None:
    decision = _phase_decision(
        phase="synthetic",
        expected_case_ids={"a"},
        results=[
            {
                "case_id": "a",
                "phase": "synthetic",
                "case_status": "infeasible",
                "error_type": "BehaviouralRedispatchInfeasible",
                "failure_diagnostic": json.dumps(
                    {
                        "failure_stage": "actual_price_bid_clearing_to_physical_redispatch",
                        "interpretation": "no_complete_recourse_path",
                        "cleared_import_total_mwh": 10.0,
                        "irrelevant_large_detail": {"omit": True},
                    }
                ),
            }
        ],
        physical_checks=[],
        economic_checks=[],
    )
    assert decision["blocking_case_diagnostics"] == [
        {
            "case_id": "a",
            "case_status": "infeasible",
            "error_type": "BehaviouralRedispatchInfeasible",
            "failure_stage": "actual_price_bid_clearing_to_physical_redispatch",
            "interpretation": "no_complete_recourse_path",
            "cleared_import_total_mwh": 10.0,
        }
    ]


def test_lineage_is_diagnostic_and_not_final_evidence() -> None:
    config = load_behavioural_config()
    assert config["run_class"] == "diagnostic_validation"
    assert "not final regime evidence" in config["lineage_role"]
    assert not config["git_eligible"]
