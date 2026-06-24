from __future__ import annotations

from pathlib import Path
import sys

import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.downstream_scheduling_inputs import load_downstream_assumptions  # noqa: E402
from steel.site_calibration_inputs import (  # noqa: E402
    CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
    DRP_CAPACITY_PELLETS_TPH,
    DRP_NATURAL_GAS_M3_PER_T_PELLETS,
    DRP_PELLETS_TO_DRI_EFFICIENCY,
    EAF_DRI_TO_STEEL_EFFICIENCY,
    EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T,
    HOT_METAL_BUFFER_CAPACITY_T,
    SLAB_YARD_CAPACITY_T,
    S3_3F_DEFAULT_MAX_CANDIDATES,
    S3_3_OUTPUT_PATHS,
    S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR,
    S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3,
    S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY,
    UNRESTRICTED_SLAB_REFERENCE_T,
    boundary_crosswalk_rows,
    c0_calibration_target_rows,
    c1_boundary_crosswalk_amendment_rows,
    c1_capacity_implied_bf_bof_share,
    c1_capacity_implied_drp_eaf_share,
    c1_s3_3b_route_shares,
    calibration_parameters,
    candidate_parameter_sets,
    final_product_target_t,
    hot_metal_initial_inventory_conflicts,
    load_calibration_downstream_assumptions,
    parameter_register_rows,
    production_scale_and_capacity_rows,
    s3_3b_route_share_capacity_rows,
    s3_3b_source_support_rows,
    s3_3b_structural_change_rows,
    s3_3c_boundary_mapping_rows,
    s3_3c_candidate_parameter_rows,
    s3_3c_source_support_rows,
    s3_3c_structural_change_rows,
    s3_3d_promoted_candidate_parameter_rows,
    s3_3d_rejected_or_blocked_assumption_rows,
    s3_3d_utility_assumption_review_rows,
    s3_3e_accept_reject_decision_rows,
    s3_3e_ng_component_candidate_rows,
    s3_3g_athanasiadis_gas_network_source_card_rows,
    s3_3g_gas_sink_parameter_eligibility_rows,
    s3_3h_phased_parameter_classification_rows,
    s3_3f_parameter_eligibility_rows,
    s3_3f_rejected_mechanism_rows,
    s3_3e_static_decomposition_attempt_rows,
    s3_3e_validation_boundary_decision_rows,
    target_conflict_rows,
    target_register_rows,
)
from steel.site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID  # noqa: E402


def test_production_scale_targets_and_legacy_baseline_are_separate():
    assert CALIBRATION_ANNUAL_FINAL_PRODUCT_T == pytest.approx(6_200_000.0)
    assert CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 8760.0 == pytest.approx(707.7625571)
    assert final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=24) == pytest.approx(
        16986.3013699
    )
    assert final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=168) == pytest.approx(
        118904.1095890
    )

    legacy = load_downstream_assumptions(configuration_id=C0_CONFIGURATION_ID, horizon_hours=24)
    assert legacy.final_product_target_t == pytest.approx(8150.6772)
    assert legacy.final_product_target_t != pytest.approx(
        final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=24)
    )
    assert EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T == pytest.approx(6_750_000.0)


def test_storage_capacity_policy_preserves_absolute_initial_inventory():
    assumptions = load_calibration_downstream_assumptions(configuration_id=C1_CONFIGURATION_ID, horizon_hours=24)
    assert assumptions.slab_yard_capacity_t == pytest.approx(SLAB_YARD_CAPACITY_T)
    assert assumptions.initial_cold_slab_inventory_t == pytest.approx(1630.13544)
    assert assumptions.initial_cold_slab_inventory_t != pytest.approx(SLAB_YARD_CAPACITY_T / 2.0)
    assert assumptions.terminal_cold_inventory_ratio == pytest.approx(1.0)
    assert HOT_METAL_BUFFER_CAPACITY_T == pytest.approx(500.0)
    assert not hot_metal_initial_inventory_conflicts()
    assert UNRESTRICTED_SLAB_REFERENCE_T == pytest.approx(68_000.0)


def test_production_scale_capacity_register_documents_scaling_boundary():
    rows = production_scale_and_capacity_rows()
    by_item = {row["item"]: row for row in rows}
    assert by_item["central_calibration_scale"]["selected_value"] == pytest.approx(6_200_000.0)
    assert by_item["legacy_development_baseline"]["status"] == "preserved_not_overwritten"
    assert by_item["cold_slab_yard_capacity"]["scaling_policy"] == "absolute capacity not scaled with production target"
    assert by_item["hot_metal_buffer_capacity"]["selected_value"] == pytest.approx(500.0)
    assert "source-specific absolute capacities are not silently scaled" in by_item["central_calibration_scale"]["scaling_policy"]


def test_target_register_contains_confirmed_targets_and_conflict_policy():
    targets = {row["target_id"]: row for row in target_register_rows()}
    required = {
        "C0_FIG96_TOTAL_PRIMARY_PROXY",
        "C0_FIG96_ELECTRICITY_SHARE_DISPUTED",
        "C0_TABLE8_GROSS_ELECTRICITY",
        "C0_TABLE8_WAG_ELECTRICITY",
        "C0_TABLE8_NATURAL_GAS_FLOW",
        "C0_TABLE8_DIRECT_CO2",
        "C1_FIG104_TOTAL_PRIMARY_PROXY",
        "C1_TABLE9_GROSS_ELECTRICITY",
        "C1_TABLE9_WAG_ELECTRICITY",
        "C1_TABLE9_NATURAL_GAS_FLOW",
        "C1_TABLE9_DIRECT_CO2",
        "C1_C0_RATIO_NG_FLOW",
    }
    assert required.issubset(targets)
    assert targets["C0_FIG96_ELECTRICITY_SHARE_DISPUTED"]["role"] == "disputed/audit-only"
    assert targets["C0_TABLE8_GROSS_ELECTRICITY"]["role"] == "calibration"
    assert "Figure 104" in targets["C1_FIG104_TOTAL_PRIMARY_PROXY"]["notes"]

    conflicts = target_conflict_rows()
    assert conflicts[0]["source_inconsistency_flag"] == "true"
    assert "excluded from score" in conflicts[0]["calibration_score_impact"]


def test_boundary_crosswalk_keeps_wag_and_grid_metrics_distinct():
    rows = {row["target_id"]: row for row in boundary_crosswalk_rows()}
    assert rows["C0_TABLE8_GROSS_ELECTRICITY"]["model_metric"] == "gross_electricity_twh_per_year"
    assert rows["C0_TABLE8_WAG_ELECTRICITY"]["model_metric"] == "wag_electricity_twh_per_year"
    assert "not added as primary energy input" in rows["C0_TABLE8_WAG_ELECTRICITY"]["double_counting_rule"]
    assert rows["C0_FIG96_TOTAL_PRIMARY_PROXY"]["score_role"] == "soft_calibration_score"


def test_s3_3a_c1_boundary_crosswalk_is_diagnostic_only():
    rows = {row["target_id"]: row for row in c1_boundary_crosswalk_amendment_rows()}
    required = {
        "C1_TABLE9_GROSS_ELECTRICITY",
        "C1_TABLE9_WAG_ELECTRICITY",
        "C1_TABLE9_NATURAL_GAS_FLOW",
        "C1_TABLE9_DIRECT_CO2",
        "C1_FIG104_TOTAL_PRIMARY_PROXY",
    }
    assert required.issubset(rows)
    assert rows["C1_TABLE9_GROSS_ELECTRICITY"]["model_metric"] == "gross_electricity_twh_per_year"
    assert rows["C1_TABLE9_WAG_ELECTRICITY"]["model_metric"] == "wag_electricity_twh_per_year"
    assert rows["C1_TABLE9_NATURAL_GAS_FLOW"]["model_metric"] == "natural_gas_m3_per_h"
    assert "not_approved_diagnostic_only" in {
        row["approved_input_status"] for row in c1_boundary_crosswalk_amendment_rows()
    }
    assert "not added again" in rows["C1_FIG104_TOTAL_PRIMARY_PROXY"]["double_counting_rule"]


def test_parameter_register_classifies_fixed_calibration_holdout_and_excluded_rows():
    rows = {row["parameter_id"]: row for row in parameter_register_rows()}
    assert rows["production_target"]["classification"] == "fixed physical"
    assert rows["slab_yard_capacity"]["classification"] == "fixed physical"
    assert rows["hot_metal_buffer_capacity"]["classification"] == "fixed physical"
    assert rows["residual_auxiliary_electricity_scale"]["classification"] == "calibratable"
    assert rows["bfg_generation_nm3_per_t_hot_metal"]["classification"] == "calibratable"
    assert rows["c1_route_share"]["classification"] == "holdout/scenario"
    assert rows["da_prices"]["classification"] == "excluded"
    assert rows["da_prices"]["model_use_status"] == "excluded"
    assert "c1_wag_availability_factor" not in rows
    assert "c1_retained_coking_wag_displacement_factor" not in rows
    assert "c1_residual_ng_boundary_m3_per_t_final" not in rows
    assert rows["drp_natural_gas_intensity"]["model_use_status"] == "holdout_sensitivity_only"


def test_candidate_generation_is_reproducible_and_within_ranges():
    first = candidate_parameter_sets(seed=202503, max_candidates=12)
    second = candidate_parameter_sets(seed=202503, max_candidates=12)
    assert first == second
    assert first[0]["candidate_id"] == "S33_CAND_000_SOURCE_CENTRAL"
    assert first[1]["candidate_id"] == "S33_CAND_001_CALIBRATION_ANCHOR"

    ranges = {p.parameter_id: (p.lower, p.upper) for p in calibration_parameters() if p.status == "calibratable"}
    for candidate in first:
        for parameter_id, (lower, upper) in ranges.items():
            assert lower <= float(candidate[parameter_id]) <= upper


def test_c0_calibration_score_targets_do_not_leak_c1_holdout_targets():
    score_targets = c0_calibration_target_rows()
    assert score_targets
    assert all(row["target_id"].startswith("C0_") for row in score_targets)
    assert not any("C1" in row["target_id"] for row in score_targets)
    assert "C0_FIG96_ELECTRICITY_SHARE_DISPUTED" not in {row["target_id"] for row in score_targets}


def test_cross_configuration_ratio_targets_are_registered_correctly():
    targets = {row["target_id"]: row for row in target_register_rows()}
    assert targets["C1_C0_RATIO_TOTAL_PRIMARY"]["value"] == pytest.approx(0.9958)
    assert targets["C1_C0_RATIO_GROSS_ELECTRICITY"]["value"] == pytest.approx(1.5426)
    assert targets["C1_C0_RATIO_WAG_ELECTRICITY"]["value"] == pytest.approx(0.4489)
    assert targets["C1_C0_RATIO_NG_FLOW"]["value"] == pytest.approx(4.5625)
    assert targets["C1_C0_RATIO_CO2"]["value"] == pytest.approx(0.6815)


def test_new_s3_3_modules_do_not_introduce_market_or_risk_logic():
    module_text = "\n".join(
        (TEST_CASE_ROOT / "steel" / name).read_text(encoding="utf-8").lower()
        for name in ("site_calibration_inputs.py", "site_validation_metrics.py", "site_calibration_runner.py")
    )
    forbidden = ("settlement", "bid_clearing", "activation_revenue")
    assert all(token not in module_text for token in forbidden)
    assert '"da_prices", "price parameters"' in module_text
    assert "cvar_logic_active" in module_text
    assert "mfrr_logic_active" in module_text
    assert "wag_generator_interface_outage" in module_text
    assert "flare_increase_vs_normal" in module_text
    assert "diagnose-c1-structure" in module_text
    assert "diagnostic_only" in module_text
    assert "c0_candidate_parameters_fixed" in module_text


def test_s3_3a_diagnostic_artifacts_are_candidate_review_outputs_only():
    assert S3_3_OUTPUT_PATHS["c1_structural_matrix"].name == "s3_3a_c1_structural_diagnostic_matrix.csv"
    assert S3_3_OUTPUT_PATHS["c1_structural_results"].name == "s3_3a_c1_structural_diagnostic_results.csv"
    assert S3_3_OUTPUT_PATHS["c1_diagnostic_decision_summary"].name == "s3_3a_c1_diagnostic_decision_summary.csv"
    assert S3_3_OUTPUT_PATHS["c1_boundary_crosswalk_amendment"].name == (
        "s3_3a_c1_boundary_crosswalk_amendment.csv"
    )
    assert "s3_candidate_review" in S3_3_OUTPUT_PATHS["c1_structural_results"].as_posix()


def test_s3_3a_runner_keeps_diagnostic_switches_out_of_approved_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "approved_inputs_populated" in runner_text
    assert "not_approved_diagnostic_only" in runner_text
    assert "market_logic_active" in runner_text
    assert "stochastic_logic_active" in runner_text
    assert "mfrr_logic_active" in runner_text
    forbidden = ("create_s4", "bidding", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3b_capacity_implied_route_share_is_added_without_removing_existing_cases():
    drp_output_tph = DRP_CAPACITY_PELLETS_TPH * DRP_PELLETS_TO_DRI_EFFICIENCY * EAF_DRI_TO_STEEL_EFFICIENCY
    average_output_tph = CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 8760.0
    assert drp_output_tph == pytest.approx(351.5)
    assert c1_capacity_implied_drp_eaf_share() == pytest.approx(drp_output_tph / average_output_tph)
    assert c1_capacity_implied_drp_eaf_share() == pytest.approx(0.49663548, abs=1e-8)
    assert c1_capacity_implied_bf_bof_share() == pytest.approx(0.50336452, abs=1e-8)
    assert c1_s3_3b_route_shares()[0] == pytest.approx(c1_capacity_implied_bf_bof_share())
    assert c1_s3_3b_route_shares()[1:] == (0.55, 0.61, 0.68)


def test_s3_3b_source_support_classifies_mechanisms_before_use():
    rows = {row["mechanism_id"]: row for row in s3_3b_source_support_rows()}
    assert rows["S33B_MECH_001"]["model_use_status"] == "source-backed enough"
    assert rows["S33B_MECH_002"]["implementation_decision"].startswith("retain existing route-share-scaled")
    assert rows["S33B_MECH_004"]["extracted_value_or_statement"] == pytest.approx(DRP_NATURAL_GAS_M3_PER_T_PELLETS)
    assert rows["S33B_MECH_008"]["model_use_status"] == "provisional-dev"
    assert rows["S33B_MECH_011"]["model_use_status"] == "source-needed"
    assert rows["S33B_MECH_012"]["model_use_status"] == "source-needed"
    assert rows["S33B_MECH_013"]["model_use_status"] == "rejected"
    assert "89.478" in str(rows["S33B_MECH_013"]["extracted_value_or_statement"])


def test_s3_3b_structural_changes_do_not_promote_s3_3a_fit_values():
    changes = {row["change_id"]: row for row in s3_3b_structural_change_rows()}
    assert changes["S33B_CHANGE_001"]["implemented"] == "true"
    assert changes["S33B_CHANGE_004"]["implemented"] == "false"
    assert changes["S33B_CHANGE_005"]["implemented"] == "false"
    combined_text = "\n".join(str(row) for row in changes.values())
    assert "0.75" not in combined_text
    assert "89.478" not in combined_text


def test_s3_3b_route_capacity_register_documents_drp_ng_basis():
    rows = s3_3b_route_share_capacity_rows()
    first = rows[0]
    assert first["bf_bof_share"] == pytest.approx(c1_capacity_implied_bf_bof_share())
    assert first["drp_capacity_utilisation_proxy"] == pytest.approx(1.0)
    assert first["case_role"] == "capacity_implied_added_s3_3b"
    legacy_cases = {round(row["bf_bof_share"], 2) for row in rows[1:]}
    assert legacy_cases == {0.55, 0.61, 0.68}


def test_s3_3b_runner_and_metrics_keep_gas_components_distinct():
    metrics_text = (TEST_CASE_ROOT / "steel" / "site_validation_metrics.py").read_text(encoding="utf-8")
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "explicit_drp_natural_gas_m3_per_h" in metrics_text
    assert "residual_ng_m3_per_h" in metrics_text
    assert "steam_boiler_natural_gas_m3_per_h" in metrics_text
    assert "wag_power_fuel_use_pj_per_year" in metrics_text
    assert "validate-c1-s3-3b" in runner_text
    assert "s3_3a_wag_availability_factor_promoted" in runner_text
    assert "s3_3a_ng_gap_closure_promoted" in runner_text


def test_s3_3c_candidate_utility_boundary_is_not_residual_gap_closure():
    rows = {row["parameter_id"]: row for row in s3_3c_candidate_parameter_rows()}
    central = rows["s3_3c_downstream_light_side_ng_central"]
    assert central["selected_value"] == pytest.approx(S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"])
    expected_nm3_h = (
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"]
        * 1_000_000.0
        / 8760.0
        / S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3
    )
    assert central["converted_nm3_per_h"] == pytest.approx(expected_nm3_h)
    assert central["approved_input_status"] == "not_approved_input"
    assert "not c1 residual gap closure" in central["limitations"].lower()


def test_s3_3c_source_and_change_register_block_s3_3a_fit_values():
    support = {row["mechanism_id"]: row for row in s3_3c_source_support_rows()}
    assert support["S33C_MECH_002"]["model_use_status"] == "candidate_input_not_approved"
    assert support["S33C_MECH_006"]["model_use_status"] == "not_promoted"
    assert "89.478" in str(support["S33C_MECH_006"]["extracted_value_or_statement"])

    changes = {row["change_id"]: row for row in s3_3c_structural_change_rows()}
    assert changes["S33C_CHANGE_001"]["implemented"] == "true"
    assert changes["S33C_CHANGE_004"]["approved_input_status"] == "blocked"
    combined = "\n".join(str(row) for row in changes.values())
    assert "c1_wag_availability_factor = 0.75" not in combined
    assert "residual NG = 89.478" not in combined


def test_s3_3c_boundary_mapping_keeps_c1_table9_contextual_until_utility_boundary_active():
    rows = {row["boundary_item"]: row for row in s3_3c_boundary_mapping_rows()}
    assert rows["C1 Table 9 natural gas"]["s3_3c_mapping"].startswith("DRP NG")
    assert "Utility NG is external natural gas" in rows["C1 Table 9 natural gas"]["double_counting_rule"]
    assert "internal conversion output" in rows["C1 Table 9 WAG electricity"]["double_counting_rule"]


def test_s3_3c_runner_and_metrics_report_utility_heat_without_market_logic():
    metrics_text = (TEST_CASE_ROOT / "steel" / "site_validation_metrics.py").read_text(encoding="utf-8")
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    builder_text = (TEST_CASE_ROOT / "steel" / "site_energy_economic_builder.py").read_text(encoding="utf-8")
    assert "utility_heat_natural_gas_m3_per_h" in metrics_text
    assert "wag_utility_heat_use_pj_per_year" in metrics_text
    assert "downstream_light_side_utility_heat_balance" in builder_text
    assert "validate-c1-s3-3c" in runner_text
    assert "generic_residual_ng_gap_closure_used" in runner_text
    forbidden = ("bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3d_assumption_review_classifies_s3_3c_values_before_validation():
    rows = {row["assumption_id"]: row for row in s3_3d_utility_assumption_review_rows()}
    assert rows["S33D_ASSUMP_002"]["classification"] == "provisional input"
    assert rows["S33D_ASSUMP_002"]["central_value"] == pytest.approx(
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"]
    )
    assert rows["S33D_ASSUMP_005"]["classification"] == "sensitivity only"
    assert rows["S33D_ASSUMP_005"]["central_value"] == pytest.approx(
        S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["central_public_candidate"]
    )
    assert rows["S33D_ASSUMP_007"]["classification"] == "rejected"
    assert rows["S33D_ASSUMP_008"]["classification"] == "rejected"
    assert rows["S33D_ASSUMP_009"]["approved_input_status"] == "blocked"


def test_s3_3d_provisional_parameter_set_is_not_an_approved_input_shell():
    rows = {row["parameter_set_id"]: row for row in s3_3d_promoted_candidate_parameter_rows()}
    assert set(rows) == {
        "s3_3d_provisional_utility_low",
        "s3_3d_provisional_utility_central",
        "s3_3d_provisional_utility_high",
    }
    assert rows["s3_3d_provisional_utility_central"]["downstream_light_side_ng_pj_per_year"] == pytest.approx(
        7.75
    )
    assert rows["s3_3d_provisional_utility_central"]["wag_to_power_efficiency_fraction"] == pytest.approx(
        0.3715
    )
    assert all(row["approved_input_status"] == "not_approved_input" for row in rows.values())
    assert all("provisional_validation_only" in row["promotion_scope"] for row in rows.values())


def test_s3_3d_rejected_and_blocked_assumptions_keep_fit_values_out_of_freeze():
    rows = {row["assumption_id"]: row for row in s3_3d_rejected_or_blocked_assumption_rows()}
    assert rows["S33D_BLOCK_001"]["final_status"] == "rejected"
    assert rows["S33D_BLOCK_002"]["final_status"] == "rejected"
    assert rows["S33D_BLOCK_003"]["final_status"] == "blocked_for_freeze"
    assert rows["S33D_BLOCK_002"]["blocked_value"] == pytest.approx(89.478)
    assert "not decomposed" in rows["S33D_BLOCK_003"]["rejection_reason"]


def test_s3_3d_runner_retains_ensemble_validation_without_s4_or_market_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "validate-c1-s3-3d" in runner_text
    assert "freeze_eligible_c1_pass" in runner_text
    assert "inherited_c0_calibration_artifact_non_promotable" in runner_text
    assert "s3_3d_candidate_values_promoted_to_approved_inputs" in runner_text
    forbidden = ("create_s4", "bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3e_component_audit_accepts_only_source_backed_explicit_ng_components():
    rows = {row["component_id"]: row for row in s3_3e_ng_component_candidate_rows()}
    assert rows["S33E_NG_COMP_001"]["decomposition_decision"] == "accepted_already_represented"
    assert rows["S33E_NG_COMP_001"]["value_or_range"] == pytest.approx(DRP_NATURAL_GAS_M3_PER_T_PELLETS)
    assert rows["S33E_NG_COMP_002"]["governance_status"] == "provisional input"
    assert rows["S33E_NG_COMP_003"]["governance_status"] == "source-needed"
    assert rows["S33E_NG_COMP_004"]["decomposition_decision"] == "rejected_not_natural_gas_component"
    assert rows["S33E_NG_COMP_007"]["governance_status"] == "blocked"


def test_s3_3e_option_a_attempt_falls_back_to_boundary_downgrade():
    attempt = s3_3e_static_decomposition_attempt_rows()[0]
    assert attempt["option_attempted"] == "Option A source-backed inherited residual decomposition"
    assert attempt["accepted_decomposition_m3_per_h"] == pytest.approx(0.0)
    assert attempt["blocked_remainder_m3_per_h"] == pytest.approx(46.97 * (6_200_000.0 / 8760.0))
    assert "Option B" in attempt["decision"]

    decisions = {row["item"]: row for row in s3_3e_accept_reject_decision_rows()}
    assert decisions["inherited C0 residual NG"]["decision"] == "reject_for_c1"
    assert decisions["Table 9 carrier totals"]["decision"] == "downgrade_to_contextual_holdout"


def test_s3_3e_boundary_decision_removes_table9_from_strict_freeze_gate():
    rows = {row["target_group"]: row for row in s3_3e_validation_boundary_decision_rows()}
    assert rows["Athanasiadis Table 9 carrier totals"]["strict_freeze_use"] == "false"
    assert rows["Athanasiadis Table 9 carrier totals"]["contextual_reporting_use"] == "true"
    assert rows["current public MILP process-network checks"]["strict_freeze_use"] == "true"
    assert rows["C1 carrier-direction checks"]["new_role"] == "directional site-level holdout"


def test_s3_3e_runner_uses_residual_override_without_new_market_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "resolve-inherited-ng-s3-3e" in runner_text
    assert "residual_ng_m3_per_t_final_override=0.0" in runner_text
    assert "contextual_broader_boundary_holdout" in runner_text
    assert "strict_current_public_boundary_pass" in runner_text
    forbidden = ("create_s4", "bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3f_bounded_alignment_paths_are_candidate_review_outputs_only():
    assert S3_3F_DEFAULT_MAX_CANDIDATES == 128
    expected = {
        "s3_3f_parameter_eligibility": "s3_3f_c1_bounded_alignment_parameter_eligibility.csv",
        "s3_3f_candidates": "s3_3f_c1_bounded_alignment_candidates.csv",
        "s3_3f_results": "s3_3f_c1_bounded_alignment_results.csv",
        "s3_3f_best_cases": "s3_3f_c1_bounded_alignment_best_cases.csv",
        "s3_3f_rejected_mechanisms": "s3_3f_c1_bounded_alignment_rejected_mechanisms.csv",
        "s3_3f_boundary_interpretation": "s3_3f_c1_bounded_alignment_boundary_interpretation.csv",
    }
    for key, filename in expected.items():
        assert S3_3_OUTPUT_PATHS[key].name == filename
        assert "s3_candidate_review" in S3_3_OUTPUT_PATHS[key].as_posix()


def test_s3_3f_parameter_eligibility_blocks_residuals_and_arbitrary_wag_factor():
    rows = {row["parameter_id"]: row for row in s3_3f_parameter_eligibility_rows()}
    assert rows["residual_c0_ng_m3_per_t_final"]["eligible_for_s3_3f"] == "false"
    assert "inherited_c0_residual" in rows["residual_c0_ng_m3_per_t_final"]["exclusion_reason"]
    assert rows["c1_residual_ng_boundary_m3_per_t_final"]["eligible_for_s3_3f"] == "false"
    assert rows["c1_wag_availability_factor"]["eligible_for_s3_3f"] == "false"
    assert rows["c1_wag_availability_factor"]["approved_input_status"] == "blocked"
    assert rows["c1_route_share"]["eligible_for_s3_3f"] == "true"
    assert rows["c1_route_share"]["lower"] == pytest.approx(c1_capacity_implied_bf_bof_share())
    assert rows["downstream_light_side_utility_ng_pj_per_year"]["upper"] == pytest.approx(8.0)
    assert rows["drp_natural_gas_intensity"]["eligible_for_s3_3f"] == "true"


def test_s3_3f_rejected_mechanism_register_documents_no_gap_closure():
    rows = {row["mechanism_id"]: row for row in s3_3f_rejected_mechanism_rows()}
    assert rows["S33F_REJECT_001"]["status"] == "rejected_not_run"
    assert rows["S33F_REJECT_002"]["status"] == "rejected_not_run"
    assert rows["S33F_REJECT_003"]["status"] == "rejected_not_run"
    combined = "\n".join(str(row) for row in rows.values())
    assert "gap-closure" in combined
    assert "arbitrary" in combined


def test_s3_3f_runner_is_diagnostic_only_without_new_market_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "diagnose-c1-bounded-alignment" in runner_text
    assert "bounded C1 alignment diagnostic" in runner_text
    assert "residual_ng_m3_per_t_final_override=0.0" in runner_text
    assert "arbitrary_wag_availability_factor_used" in runner_text
    assert "approved_inputs_populated" in runner_text
    forbidden = ("create_s4", "bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3g_gas_sink_paths_are_candidate_review_outputs_only():
    expected = {
        "s3_3g_source_card_register": "s3_3g_athanasiadis_gas_network_source_card_register.csv",
        "s3_3g_parameter_eligibility": "s3_3g_c1_gas_sink_parameter_eligibility.csv",
        "s3_3g_cases": "s3_3g_c1_gas_sink_decomposition_cases.csv",
        "s3_3g_results": "s3_3g_c1_gas_sink_decomposition_results.csv",
        "s3_3g_best_cases": "s3_3g_c1_gas_sink_best_cases.csv",
        "s3_3g_remaining_gap": "s3_3g_c1_remaining_gap_analysis.csv",
        "s3_3g_boundary_decision_support": "s3_3g_boundary_decision_support.csv",
    }
    for key, filename in expected.items():
        assert S3_3_OUTPUT_PATHS[key].name == filename
        assert "s3_candidate_review" in S3_3_OUTPUT_PATHS[key].as_posix()


def test_s3_3g_source_card_register_records_gas_network_ambiguity_and_lhvs():
    rows = s3_3g_athanasiadis_gas_network_source_card_rows()
    combined = "\n".join(str(row) for row in rows)
    assert "Figure 31" in combined
    assert "Figure 32" in combined
    assert "Figure 33" in combined
    assert "PDF-direct check blocked" in combined
    assert "18.5" in combined
    assert "8.6" in combined
    assert "3.85" in combined
    assert "37.5" in combined


def test_s3_3g_gas_sink_eligibility_separates_structure_from_numeric_support():
    rows = {row["sink_id"]: row for row in s3_3g_gas_sink_parameter_eligibility_rows()}
    assert rows["hsm_fuel_substitution_ng"]["eligible_for_s3_3g_diagnostic_variation"] == "true"
    assert rows["pelletizing_firing_ng"]["eligible_for_s3_3g_diagnostic_variation"] == "true"
    assert rows["hsm_fuel_substitution_cog"]["eligible_for_s3_3g_diagnostic_variation"] == "false"
    assert rows["hsm_fuel_substitution_cog"]["source_needed_before_approved_input"] == "true"
    assert rows["boiler_steam_ng"]["model_use_status"] == "diagnostic_only"
    assert rows["vattenfall_generator_high_lhv_injection_limit"]["source_needed_before_approved_input"] == "true"


def test_s3_3g_runner_is_diagnostic_only_without_residual_or_s4_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "diagnose-c1-gas-sink-decomposition" in runner_text
    assert "S3.3g C1 gas-sink decomposition diagnostic" in runner_text
    assert "residual_ng_m3_per_t_final_override=0.0" in runner_text
    assert "residual_c1_gap_closure_used" in runner_text
    assert "arbitrary_wag_availability_factor_used" in runner_text
    forbidden = ("create_s4", "bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)


def test_s3_3h_phased_diagnostic_paths_are_candidate_review_outputs_only():
    expected = {
        "s3_3h_parameter_classification": "s3_3h_phased_parameter_classification.csv",
        "s3_3h_block_a_cases": "s3_3h_block_a_c1_boundary_cases.csv",
        "s3_3h_block_a_results": "s3_3h_block_a_c1_boundary_results.csv",
        "s3_3h_block_b_cases": "s3_3h_block_b_shared_parameter_cases.csv",
        "s3_3h_block_b_c0_results": "s3_3h_block_b_c0_regression_results.csv",
        "s3_3h_block_b_c1_results": "s3_3h_block_b_c1_results.csv",
        "s3_3h_best_case_comparison": "s3_3h_best_case_comparison.csv",
        "s3_3h_rejected_cases": "s3_3h_rejected_cases.csv",
        "s3_3h_remaining_gap": "s3_3h_remaining_gap_analysis.csv",
        "s3_3h_boundary_decision_support": "s3_3h_boundary_decision_support.csv",
    }
    for key, filename in expected.items():
        assert S3_3_OUTPUT_PATHS[key].name == filename
        assert "s3_candidate_review" in S3_3_OUTPUT_PATHS[key].as_posix()


def test_s3_3h_parameter_classification_separates_blocks_and_forbidden_terms():
    rows = {row["parameter_id"]: row for row in s3_3h_phased_parameter_classification_rows()}
    assert rows["c1_route_share"]["parameter_class"] == "C1-only"
    assert rows["boiler_steam_ng"]["s3_3h_use"] == "varied_block_a_gap_sizing"
    assert rows["downstream_electricity_scale"]["parameter_class"] == "shared"
    assert rows["residual_auxiliary_electricity_scale"]["s3_3h_use"] == "varied_block_b_with_c0_regression"
    assert rows["eaf_electricity_intensity"]["s3_3h_use"] == "not_varied_source_needed"
    assert rows["drp_electricity_intensity"]["source_status"] == "source_needed_not_exposed"
    assert rows["residual_c0_ng_m3_per_t_final"]["parameter_class"] == "forbidden"
    assert rows["c1_wag_availability_factor"]["s3_3h_use"] == "blocked"


def test_s3_3h_runner_is_phased_diagnostic_without_residual_or_s4_logic():
    runner_text = (TEST_CASE_ROOT / "steel" / "site_calibration_runner.py").read_text(encoding="utf-8")
    assert "diagnose-c1-phased-boundary-c0-preserving" in runner_text
    assert "S3.3h phased C1 boundary and C0-preserving shared-parameter diagnostic" in runner_text
    assert "residual_ng_m3_per_t_final_override=0.0" in runner_text
    assert "c0_within_calibration_tolerance" in runner_text
    assert "improves_c1_but_breaks_c0" in runner_text
    forbidden = ("create_s4", "bid_clearing", "settlement_results", "cvar_objective", "mfrr_capacity")
    assert all(token not in runner_text.lower() for token in forbidden)
