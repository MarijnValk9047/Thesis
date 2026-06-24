from __future__ import annotations

import csv
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from .downstream_scheduling_inputs import AssetEnvelope, DownstreamAssumptions, load_downstream_assumptions
from .site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID


REPO_ROOT = Path(__file__).resolve().parents[4]
S2_DEV_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S2" / "s2_provisional_dev_input"
S3_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3"
S3_DEV_ROOT = S3_ROOT / "s3_provisional_dev_input"
S3_REVIEW_ROOT = S3_ROOT / "s3_candidate_review"

CALIBRATION_OVERLAY_PATH = S3_DEV_ROOT / "s3_3_site_scale_6_2Mt_calibration_overlay.csv"

HOURS_PER_YEAR = 8760.0
CALIBRATION_ANNUAL_FINAL_PRODUCT_T = 6_200_000.0
EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T = 6_750_000.0
SLAB_YARD_CAPACITY_T = 25_000.0
UNRESTRICTED_SLAB_REFERENCE_T = 68_000.0
HOT_METAL_BUFFER_CAPACITY_T = 500.0
DEFAULT_SEED = 202503
DEFAULT_MAX_CANDIDATES = 64
S3_3F_DEFAULT_MAX_CANDIDATES = 128
DRP_CAPACITY_PELLETS_TPH = 500.0
DRP_PELLETS_TO_DRI_EFFICIENCY = 0.74
EAF_DRI_TO_STEEL_EFFICIENCY = 0.95
DRP_NATURAL_GAS_M3_PER_T_PELLETS = 195.0

S3_3_OUTPUT_PATHS = {
    "production_scale": S3_REVIEW_ROOT / "s3_3_production_scale_and_capacity_register.csv",
    "target_register": S3_REVIEW_ROOT / "s3_3_visual_and_written_target_register.csv",
    "boundary_crosswalk": S3_REVIEW_ROOT / "s3_3_target_boundary_crosswalk.csv",
    "target_conflict": S3_REVIEW_ROOT / "s3_3_target_conflict_register.csv",
    "parameter_register": S3_REVIEW_ROOT / "s3_3_calibration_parameter_register.csv",
    "screening": S3_REVIEW_ROOT / "s3_3_parameter_screening_results.csv",
    "candidate_sets": S3_REVIEW_ROOT / "s3_3_candidate_parameter_sets.csv",
    "c0_24h": S3_REVIEW_ROOT / "s3_3_c0_24h_calibration_results.csv",
    "c0_168h": S3_REVIEW_ROOT / "s3_3_c0_168h_calibration_results.csv",
    "c1_holdout": S3_REVIEW_ROOT / "s3_3_c1_holdout_validation_results.csv",
    "behavioral": S3_REVIEW_ROOT / "s3_3_behavioral_validation_results.csv",
    "ensemble": S3_REVIEW_ROOT / "s3_3_selected_parameter_ensemble.csv",
    "selected_inputs": S3_REVIEW_ROOT / "s3_3_selected_calibrated_inputs.csv",
    "stage_gate": S3_REVIEW_ROOT / "s3_3_stage_gate_checklist.csv",
    "c1_structural_matrix": S3_REVIEW_ROOT / "s3_3a_c1_structural_diagnostic_matrix.csv",
    "c1_structural_results": S3_REVIEW_ROOT / "s3_3a_c1_structural_diagnostic_results.csv",
    "c1_diagnostic_decision_summary": S3_REVIEW_ROOT / "s3_3a_c1_diagnostic_decision_summary.csv",
    "c1_boundary_crosswalk_amendment": S3_REVIEW_ROOT / "s3_3a_c1_boundary_crosswalk_amendment.csv",
    "s3_3b_source_support": S3_REVIEW_ROOT / "s3_3b_c1_source_support_register.csv",
    "s3_3b_structural_change": S3_REVIEW_ROOT / "s3_3b_c1_structural_change_register.csv",
    "s3_3b_directional_validation": S3_REVIEW_ROOT / "s3_3b_c1_directional_validation_results.csv",
    "s3_3b_route_share_capacity": S3_REVIEW_ROOT / "s3_3b_c1_route_share_capacity_check.csv",
    "s3_3b_remaining_gap": S3_REVIEW_ROOT / "s3_3b_c1_remaining_gap_analysis.csv",
    "s3_3c_source_support": S3_REVIEW_ROOT / "s3_3c_utility_boundary_source_support_register.csv",
    "s3_3c_structural_change": S3_REVIEW_ROOT / "s3_3c_utility_boundary_structural_change_register.csv",
    "s3_3c_candidate_parameter": S3_REVIEW_ROOT / "s3_3c_utility_candidate_parameter_register.csv",
    "s3_3c_boundary_mapping": S3_REVIEW_ROOT / "s3_3c_boundary_mapping_table.csv",
    "s3_3c_c1_validation": S3_REVIEW_ROOT / "s3_3c_c1_validation_results.csv",
    "s3_3c_before_after": S3_REVIEW_ROOT / "s3_3c_c1_before_after_comparison.csv",
    "s3_3c_remaining_gap": S3_REVIEW_ROOT / "s3_3c_remaining_gap_analysis.csv",
    "s3_3d_assumption_review": S3_REVIEW_ROOT / "s3_3d_utility_assumption_review.csv",
    "s3_3d_promoted_candidate_parameter_set": S3_REVIEW_ROOT / "s3_3d_promoted_candidate_parameter_set.csv",
    "s3_3d_rejected_or_blocked_assumptions": S3_REVIEW_ROOT / "s3_3d_rejected_or_blocked_assumptions.csv",
    "s3_3d_inherited_residual_ng_audit": S3_REVIEW_ROOT / "s3_3d_inherited_residual_ng_audit.csv",
    "s3_3d_retained_ensemble_validation": S3_REVIEW_ROOT / "s3_3d_retained_ensemble_validation_results.csv",
    "s3_3d_before_after_summary": S3_REVIEW_ROOT / "s3_3d_c0_c1_before_after_summary.csv",
    "s3_3d_stage_gate_decision": S3_REVIEW_ROOT / "s3_3d_stage_gate_decision.csv",
    "s3_3e_decomposition_attempt": S3_REVIEW_ROOT / "s3_3e_inherited_ng_residual_decomposition_attempt.csv",
    "s3_3e_ng_component_candidates": S3_REVIEW_ROOT / "s3_3e_source_backed_ng_component_candidates.csv",
    "s3_3e_accept_reject_decisions": S3_REVIEW_ROOT / "s3_3e_decomposition_accept_reject_decisions.csv",
    "s3_3e_no_double_counting": S3_REVIEW_ROOT / "s3_3e_no_double_counting_check.csv",
    "s3_3e_validation_boundary_decision": S3_REVIEW_ROOT / "s3_3e_validation_boundary_decision.csv",
    "s3_3e_c1_validation_after_residual_resolution": S3_REVIEW_ROOT / "s3_3e_c1_validation_after_residual_resolution.csv",
    "s3_3e_stage_gate_decision": S3_REVIEW_ROOT / "s3_3e_stage_gate_decision.csv",
    "s3_3f_parameter_eligibility": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_parameter_eligibility.csv",
    "s3_3f_candidates": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_candidates.csv",
    "s3_3f_results": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_results.csv",
    "s3_3f_best_cases": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_best_cases.csv",
    "s3_3f_rejected_mechanisms": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_rejected_mechanisms.csv",
    "s3_3f_boundary_interpretation": S3_REVIEW_ROOT / "s3_3f_c1_bounded_alignment_boundary_interpretation.csv",
    "s3_3g_source_card_register": S3_REVIEW_ROOT / "s3_3g_athanasiadis_gas_network_source_card_register.csv",
    "s3_3g_parameter_eligibility": S3_REVIEW_ROOT / "s3_3g_c1_gas_sink_parameter_eligibility.csv",
    "s3_3g_cases": S3_REVIEW_ROOT / "s3_3g_c1_gas_sink_decomposition_cases.csv",
    "s3_3g_results": S3_REVIEW_ROOT / "s3_3g_c1_gas_sink_decomposition_results.csv",
    "s3_3g_best_cases": S3_REVIEW_ROOT / "s3_3g_c1_gas_sink_best_cases.csv",
    "s3_3g_remaining_gap": S3_REVIEW_ROOT / "s3_3g_c1_remaining_gap_analysis.csv",
    "s3_3g_boundary_decision_support": S3_REVIEW_ROOT / "s3_3g_boundary_decision_support.csv",
    "s3_3h_parameter_classification": S3_REVIEW_ROOT / "s3_3h_phased_parameter_classification.csv",
    "s3_3h_block_a_cases": S3_REVIEW_ROOT / "s3_3h_block_a_c1_boundary_cases.csv",
    "s3_3h_block_a_results": S3_REVIEW_ROOT / "s3_3h_block_a_c1_boundary_results.csv",
    "s3_3h_block_b_cases": S3_REVIEW_ROOT / "s3_3h_block_b_shared_parameter_cases.csv",
    "s3_3h_block_b_c0_results": S3_REVIEW_ROOT / "s3_3h_block_b_c0_regression_results.csv",
    "s3_3h_block_b_c1_results": S3_REVIEW_ROOT / "s3_3h_block_b_c1_results.csv",
    "s3_3h_best_case_comparison": S3_REVIEW_ROOT / "s3_3h_best_case_comparison.csv",
    "s3_3h_rejected_cases": S3_REVIEW_ROOT / "s3_3h_rejected_cases.csv",
    "s3_3h_remaining_gap": S3_REVIEW_ROOT / "s3_3h_remaining_gap_analysis.csv",
    "s3_3h_boundary_decision_support": S3_REVIEW_ROOT / "s3_3h_boundary_decision_support.csv",
}

S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR = {
    "disabled": 0.0,
    "low": 7.5,
    "central": 7.75,
    "high": 8.0,
}
S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3 = 0.03165
S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY = {
    "existing_calibrated": None,
    "low_public_candidate": 0.321,
    "central_public_candidate": 0.3715,
    "high_public_candidate": 0.422,
}


@dataclass(frozen=True)
class CalibrationParameter:
    parameter_id: str
    group: str
    unit: str
    activity_basis: str
    lower: float
    source_central: float
    upper: float
    status: str
    evidence_tier: str
    model_use_status: str
    source_or_policy_basis: str
    limitations: str
    sensitivity_status: str = "eligible"


def final_product_target_t(*, annual_t: float, horizon_hours: int) -> float:
    return annual_t * float(horizon_hours) / HOURS_PER_YEAR


def calibration_hourly_target_t() -> float:
    return CALIBRATION_ANNUAL_FINAL_PRODUCT_T / HOURS_PER_YEAR


def c1_capacity_implied_drp_eaf_share() -> float:
    return (
        DRP_CAPACITY_PELLETS_TPH
        * DRP_PELLETS_TO_DRI_EFFICIENCY
        * EAF_DRI_TO_STEEL_EFFICIENCY
        / calibration_hourly_target_t()
    )


def c1_capacity_implied_bf_bof_share() -> float:
    return 1.0 - c1_capacity_implied_drp_eaf_share()


def c1_s3_3b_route_shares() -> tuple[float, float, float, float]:
    return (c1_capacity_implied_bf_bof_share(), 0.55, 0.61, 0.68)


def _scale_envelope(envelope: AssetEnvelope, factor: float) -> AssetEnvelope:
    return AssetEnvelope(
        max_tph=envelope.max_tph * factor,
        min_tph=envelope.min_tph * factor,
        ramp_tph=envelope.ramp_tph * factor,
        min_up_steps=envelope.min_up_steps,
        min_down_steps=envelope.min_down_steps,
    )


def load_calibration_downstream_assumptions(
    *,
    configuration_id: str,
    horizon_hours: int,
    annual_final_product_t: float = CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
    bf_bof_share: float | None = None,
    slab_yard_capacity_t: float = SLAB_YARD_CAPACITY_T,
) -> DownstreamAssumptions:
    base = load_downstream_assumptions(configuration_id=configuration_id, horizon_hours=horizon_hours)
    target_t = final_product_target_t(annual_t=annual_final_product_t, horizon_hours=horizon_hours)
    target_q_total = target_t / float(horizon_hours)
    target_q_dsp = target_q_total * base.dsp_share
    target_q_hsm = target_q_total * (1.0 - base.dsp_share)

    if base.initial_cold_slab_inventory_t > slab_yard_capacity_t + 1e-9:
        raise ValueError("Preserved initial cold-slab inventory exceeds selected S3.3 slab-yard capacity.")

    resolved_bf_bof_share = base.bf_bof_share if bf_bof_share is None else float(bf_bof_share)
    if not 0.0 <= resolved_bf_bof_share <= 1.0:
        raise ValueError("BF-BOF route share must stay within [0, 1].")

    return replace(
        base,
        assumption_set_id="S3_3_SITE_SCALE_6_2MT_CALIBRATION_OVERLAY",
        final_product_target_t=target_t,
        bf_bof_share=resolved_bf_bof_share,
        drp_eaf_share=1.0 - resolved_bf_bof_share,
        slab_yard_capacity_t=slab_yard_capacity_t,
        initial_cold_slab_inventory_t=base.initial_cold_slab_inventory_t,
        secondary=_scale_envelope(base.secondary, target_q_total / base.q_avg_total_tph),
        caster=_scale_envelope(base.caster, target_q_total / base.q_avg_total_tph),
        dsp=_scale_envelope(base.dsp, target_q_dsp / base.q_avg_dsp_tph),
        reheater=_scale_envelope(base.reheater, target_q_hsm / base.q_avg_hsm_tph),
        hsm=_scale_envelope(base.hsm, target_q_hsm / base.q_avg_hsm_tph),
    )


def _read_s2_dev_csv(filename: str) -> pd.DataFrame:
    return pd.read_csv(S2_DEV_ROOT / filename, dtype=str, keep_default_na=False)


def hot_metal_initial_inventory_conflicts() -> list[dict[str, Any]]:
    inventories = _read_s2_dev_csv("initial_inventories.csv")
    rows = inventories.loc[inventories["carrier_id"].eq("hot_metal")]
    conflicts: list[dict[str, Any]] = []
    for row in rows.to_dict(orient="records"):
        value = float(row["value"])
        if value > HOT_METAL_BUFFER_CAPACITY_T + 1e-9:
            conflicts.append(
                {
                    "row_id": row["row_id"],
                    "configuration_id": row["configuration_id"],
                    "store_id": row["store_id"],
                    "initial_inventory_t": value,
                    "capacity_t": HOT_METAL_BUFFER_CAPACITY_T,
                }
            )
    return conflicts


def production_scale_and_capacity_rows() -> list[dict[str, Any]]:
    hourly = calibration_hourly_target_t()
    base_c0 = load_downstream_assumptions(configuration_id=C0_CONFIGURATION_ID, horizon_hours=24)
    base_annual = base_c0.final_product_target_t / 24.0 * HOURS_PER_YEAR
    return [
        {
            "register_id": "S33_SCALE_001",
            "item": "legacy_development_baseline",
            "configuration_or_case": "S2.13/S3.2 development baseline",
            "selected_value": base_annual,
            "unit": "t_final_product_per_year",
            "status": "preserved_not_overwritten",
            "source_or_policy_basis": "existing S2.13 common_final_product_target_24h",
            "scaling_policy": "none",
            "notes": "Approximately 2.98 Mt/y development scale remains available for regression.",
        },
        {
            "register_id": "S33_SCALE_002",
            "item": "central_calibration_scale",
            "configuration_or_case": "site_scale_6_2Mt_calibration",
            "selected_value": CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
            "unit": "t_final_product_per_year",
            "status": "selected_s3_3_calibration_overlay",
            "source_or_policy_basis": "user confirmed production-scale amendment",
            "scaling_policy": "target-derived downstream capacities may scale; source-specific absolute capacities are not silently scaled",
            "notes": "Average hourly target is 707.7625571 t/h.",
        },
        {
            "register_id": "S33_SCALE_003",
            "item": "calibration_24h_target",
            "configuration_or_case": "site_scale_6_2Mt_calibration",
            "selected_value": hourly * 24.0,
            "unit": "t_final_product_per_24h",
            "status": "selected_s3_3_calibration_overlay",
            "source_or_policy_basis": "6200000 / 8760 * 24",
            "scaling_policy": "horizon-scaled target",
            "notes": "",
        },
        {
            "register_id": "S33_SCALE_004",
            "item": "calibration_168h_target",
            "configuration_or_case": "site_scale_6_2Mt_calibration",
            "selected_value": hourly * 168.0,
            "unit": "t_final_product_per_168h",
            "status": "selected_s3_3_calibration_overlay",
            "source_or_policy_basis": "6200000 / 8760 * 168",
            "scaling_policy": "horizon-scaled target",
            "notes": "",
        },
        {
            "register_id": "S33_SCALE_005",
            "item": "cold_slab_yard_capacity",
            "configuration_or_case": "central_physical_capacity",
            "selected_value": SLAB_YARD_CAPACITY_T,
            "unit": "t_slab",
            "status": "fixed_physical_parameter",
            "source_or_policy_basis": "Athanasiadis public-thesis-derived S2.13a amendment",
            "scaling_policy": "absolute capacity not scaled with production target",
            "notes": "Initial cold inventory remains 1630.13544 t; terminal equals initial.",
        },
        {
            "register_id": "S33_SCALE_006",
            "item": "unrestricted_slab_reference",
            "configuration_or_case": "behavioural_validation_context",
            "selected_value": UNRESTRICTED_SLAB_REFERENCE_T,
            "unit": "t_slab",
            "status": "holdout_reference_not_base_capacity",
            "source_or_policy_basis": "human-reviewed target packet",
            "scaling_policy": "not used as physical base capacity",
            "notes": "Used only for unrestricted-store diagnostic context.",
        },
        {
            "register_id": "S33_SCALE_007",
            "item": "hot_metal_buffer_capacity",
            "configuration_or_case": "central_physical_capacity",
            "selected_value": HOT_METAL_BUFFER_CAPACITY_T,
            "unit": "t_hot_metal",
            "status": "fixed_physical_parameter",
            "source_or_policy_basis": "Athanasiadis Figure 65 human-reviewed target packet",
            "scaling_policy": "absolute capacity not scaled with production target",
            "notes": "Existing initial hot-metal inventory is below 500 t; no reset applied.",
        },
        {
            "register_id": "S33_SCALE_008",
            "item": "external_scale_stress",
            "configuration_or_case": "site_scale_6_75Mt_external_stress",
            "selected_value": EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T,
            "unit": "t_final_product_per_year",
            "status": "external_stress_only",
            "source_or_policy_basis": "Badarinath-aligned scale context",
            "scaling_policy": "not calibration base and no recalibration",
            "notes": "Retained for later scale stress, not central target.",
        },
    ]


def target_register_rows() -> list[dict[str, Any]]:
    common = {
        "source": "Athanasiadis thesis; human-reviewed S3.3 target packet",
        "confidence": "human_verified_public_thesis_locator_packet",
    }
    rows = [
        ("C0_FIG96_TOTAL_PRIMARY_PROXY", 96, 110, "The energy breakdown of the current configuration and the total energy consumption of the site", "C0_current_configuration", "reported total primary-energy proxy", 102.6289, "PJ/year", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "calibration", "soft", 10.0, "Coal includes coal-origin WAG energy; WAG is not added separately."),
        ("C0_FIG96_COAL_SHARE", 96, 110, "The energy breakdown of the current configuration and the total energy consumption of the site", "C0_current_configuration", "reported coal share including WAGs", 0.793, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "disputed/audit-only", "soft", 10.0, "Soft audit target only; not a hard score term."),
        ("C0_FIG96_ELECTRICITY_SHARE_DISPUTED", 96, 110, "The energy breakdown of the current configuration and the total energy consumption of the site", "C0_current_configuration", "reported electricity share", 0.093, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "disputed/audit-only", "low", 0.0, "Conflicts with Table 8 gross electricity; excluded from calibration score."),
        ("C0_FIG96_NG_SHARE", 96, 110, "The energy breakdown of the current configuration and the total energy consumption of the site", "C0_current_configuration", "reported natural-gas share", 0.114, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "disputed/audit-only", "soft", 10.0, "Soft audit target only."),
        ("C0_TABLE8_NATURAL_GAS_FLOW", 97, 111, "Main outputs of the central scenario of the yearly simulation for the current configuration", "C0_current_configuration", "natural-gas consumption average", 33243.63, "m3/h", "hourly_average", "gross", "external_energy_input", "model output", "calibration", "principal", 10.0, "Average hourly flow."),
        ("C0_TABLE8_DIRECT_CO2", 97, 111, "Main outputs of the central scenario of the yearly simulation for the current configuration", "C0_current_configuration", "CO2 emissions", 13365216.16, "t/year", "annual", "gross", "direct_site_emissions_boundary_uncertain", "model output", "calibration", "principal", 10.0, "Provisionally treated as direct-site emissions with boundary uncertainty flag."),
        ("C0_TABLE8_GROSS_ELECTRICITY", 97, 111, "Main outputs of the central scenario of the yearly simulation for the current configuration", "C0_current_configuration", "gross site electricity consumption", 3.17, "TWh/year", "annual", "gross", "gross_site_consumption", "model output", "calibration", "principal", 5.0, "Principal electricity target; distinct from net grid import."),
        ("C0_TABLE8_WAG_ELECTRICITY", 97, 111, "Main outputs of the central scenario of the yearly simulation for the current configuration", "C0_current_configuration", "WAG electricity generation", 2.74, "TWh/year", "annual", "gross_internal_generation", "internal_conversion_output", "model output", "calibration", "principal", 10.0, "WAG electricity output, not extra primary energy input."),
        ("C0_NORMAL_FLARE_FRACTION", 0, 0, "Figures 85-86 WAG behaviour", "C0_current_configuration", "normal-operation flare fraction of generated WAG energy", 0.02, "fraction", "annualised", "gross", "internal_conversion_residual", "qualitative behaviour", "calibration", "behavioural", 150.0, "Preferred <=2%; admissible <=5%."),
        ("C1_FIG104_TOTAL_PRIMARY_PROXY", 101, 115, "The energy breakdown of the Phase 1 configuration and the total energy consumption of the site", "C1_phase1_configuration", "reported total primary-energy proxy", 102.1941, "PJ/year", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "holdout validation", "soft", 10.0, "User previously referred to Figure 107; confirmed values correspond to Figure 104."),
        ("C1_FIG104_COAL_SHARE", 101, 115, "The energy breakdown of the Phase 1 configuration and the total energy consumption of the site", "C1_phase1_configuration", "reported coal share including WAGs", 0.401, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "holdout validation", "soft", 10.0, ""),
        ("C1_FIG104_ELECTRICITY_SHARE", 101, 115, "The energy breakdown of the Phase 1 configuration and the total energy consumption of the site", "C1_phase1_configuration", "reported electricity share", 0.172, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "holdout validation", "soft", 10.0, ""),
        ("C1_FIG104_NG_SHARE", 101, 115, "The energy breakdown of the Phase 1 configuration and the total energy consumption of the site", "C1_phase1_configuration", "reported natural-gas share", 0.427, "fraction", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "holdout validation", "soft", 10.0, ""),
        ("C1_TABLE9_NATURAL_GAS_FLOW", 102, 116, "Main outputs of the central scenario of the yearly simulation for the Phase 1 configuration", "C1_phase1_configuration", "natural-gas consumption average", 151673.52, "m3/h", "hourly_average", "gross", "external_energy_input", "model output", "holdout validation", "principal", 10.0, ""),
        ("C1_TABLE9_DIRECT_CO2", 102, 116, "Main outputs of the central scenario of the yearly simulation for the Phase 1 configuration", "C1_phase1_configuration", "CO2 emissions", 9107793.17, "t/year", "annual", "gross", "direct_site_emissions_boundary_uncertain", "model output", "holdout validation", "principal", 10.0, ""),
        ("C1_TABLE9_GROSS_ELECTRICITY", 102, 116, "Main outputs of the central scenario of the yearly simulation for the Phase 1 configuration", "C1_phase1_configuration", "gross site electricity consumption", 4.89, "TWh/year", "annual", "gross", "gross_site_consumption", "model output", "holdout validation", "principal", 5.0, ""),
        ("C1_TABLE9_WAG_ELECTRICITY", 102, 116, "Main outputs of the central scenario of the yearly simulation for the Phase 1 configuration", "C1_phase1_configuration", "WAG electricity generation", 1.23, "TWh/year", "annual", "gross_internal_generation", "internal_conversion_output", "model output", "holdout validation", "principal", 10.0, ""),
        ("C1_C0_RATIO_TOTAL_PRIMARY", 0, 0, "Derived cross-configuration ratio", "C1_over_C0", "total primary-energy proxy ratio", 0.9958, "ratio", "annual", "gross", "primary_proxy_carrier_accounting", "model output", "holdout validation", "ratio", 10.0, ""),
        ("C1_C0_RATIO_GROSS_ELECTRICITY", 0, 0, "Derived cross-configuration ratio", "C1_over_C0", "gross electricity ratio", 1.5426, "ratio", "annual", "gross", "gross_site_consumption", "model output", "holdout validation", "ratio", 10.0, ""),
        ("C1_C0_RATIO_WAG_ELECTRICITY", 0, 0, "Derived cross-configuration ratio", "C1_over_C0", "WAG electricity ratio", 0.4489, "ratio", "annual", "gross_internal_generation", "internal_conversion_output", "model output", "holdout validation", "ratio", 10.0, ""),
        ("C1_C0_RATIO_NG_FLOW", 0, 0, "Derived cross-configuration ratio", "C1_over_C0", "natural-gas-flow ratio", 4.5625, "ratio", "hourly_average", "gross", "external_energy_input", "model output", "holdout validation", "ratio", 10.0, ""),
        ("C1_C0_RATIO_CO2", 0, 0, "Derived cross-configuration ratio", "C1_over_C0", "CO2 ratio", 0.6815, "ratio", "annual", "gross", "direct_site_emissions_boundary_uncertain", "model output", "holdout validation", "ratio", 10.0, ""),
    ]
    return [
        {
            "target_id": row[0],
            "source": common["source"],
            "printed_page": row[1],
            "pdf_page": row[2],
            "figure_or_table_title": row[3],
            "configuration": row[4],
            "metric": row[5],
            "value": row[6],
            "unit": row[7],
            "annual_or_hourly_basis": row[8],
            "gross_or_net_basis": row[9],
            "primary_final_internal_conversion_basis": row[10],
            "source_type": row[11],
            "role": row[12],
            "confidence": row[13],
            "tolerance_pct": row[14],
            "notes": row[15],
        }
        for row in rows
    ]


def c0_calibration_target_rows() -> list[dict[str, Any]]:
    score_targets = {
        "C0_TABLE8_GROSS_ELECTRICITY",
        "C0_TABLE8_WAG_ELECTRICITY",
        "C0_TABLE8_NATURAL_GAS_FLOW",
        "C0_TABLE8_DIRECT_CO2",
        "C0_FIG96_TOTAL_PRIMARY_PROXY",
        "C0_NORMAL_FLARE_FRACTION",
    }
    return [row for row in target_register_rows() if row["target_id"] in score_targets]


def boundary_crosswalk_rows() -> list[dict[str, Any]]:
    return [
        {
            "crosswalk_id": "S33_CROSSWALK_001",
            "target_id": "C0_TABLE8_GROSS_ELECTRICITY",
            "model_metric": "gross_electricity_twh_per_year",
            "boundary_match": "direct",
            "gross_net_interpretation": "gross site electricity consumption",
            "double_counting_rule": "distinct from WAG electricity and net grid import",
            "score_role": "calibration_score",
            "notes": "",
        },
        {
            "crosswalk_id": "S33_CROSSWALK_002",
            "target_id": "C0_TABLE8_WAG_ELECTRICITY",
            "model_metric": "wag_electricity_twh_per_year",
            "boundary_match": "direct",
            "gross_net_interpretation": "internal WAG-to-power electricity output",
            "double_counting_rule": "reported separately; not added as primary energy input",
            "score_role": "calibration_score",
            "notes": "",
        },
        {
            "crosswalk_id": "S33_CROSSWALK_003",
            "target_id": "C0_TABLE8_NATURAL_GAS_FLOW",
            "model_metric": "natural_gas_m3_per_h",
            "boundary_match": "adapter_with_residual_site_ng_component",
            "gross_net_interpretation": "gross external NG flow",
            "double_counting_rule": "NG energy counted once through external gas import",
            "score_role": "calibration_score",
            "notes": "Residual C0 site NG demand is explicit in parameter register.",
        },
        {
            "crosswalk_id": "S33_CROSSWALK_004",
            "target_id": "C0_TABLE8_DIRECT_CO2",
            "model_metric": "direct_site_co2_t_per_year",
            "boundary_match": "provisional",
            "gross_net_interpretation": "direct site emissions proxy",
            "double_counting_rule": "Scope 2 reported separately",
            "score_role": "calibration_score",
            "notes": "Athanasiadis CO2 boundary remains uncertain.",
        },
        {
            "crosswalk_id": "S33_CROSSWALK_005",
            "target_id": "C0_FIG96_TOTAL_PRIMARY_PROXY",
            "model_metric": "athanasiadis_primary_proxy_pj_per_year",
            "boundary_match": "soft_proxy",
            "gross_net_interpretation": "coal-origin energy plus NG plus gross electricity",
            "double_counting_rule": "WAG fuel energy is internal conversion and not added again",
            "score_role": "soft_calibration_score",
            "notes": "Figure 96 electricity share remains disputed.",
        },
        {
            "crosswalk_id": "S33_CROSSWALK_006",
            "target_id": "C0_FIG96_ELECTRICITY_SHARE_DISPUTED",
            "model_metric": "electricity_share_athanasiadis_proxy",
            "boundary_match": "conflicting_source",
            "gross_net_interpretation": "reported Figure 96 share",
            "double_counting_rule": "excluded from hard score because Table 8 reports gross 3.17 TWh",
            "score_role": "audit_only",
            "notes": "Do not force Table 8 and Figure 96 electricity values simultaneously.",
        },
    ]


def c1_boundary_crosswalk_amendment_rows() -> list[dict[str, Any]]:
    """Diagnostic-only C1 boundary crosswalk rows.

    These rows do not amend approved inputs. They document how S3.3a compares
    fixed C0 parameter sets against Athanasiadis Phase 1 holdout targets.
    """

    return [
        {
            "crosswalk_id": "S33A_C1_CROSSWALK_001",
            "target_id": "C1_TABLE9_GROSS_ELECTRICITY",
            "model_metric": "gross_electricity_twh_per_year",
            "boundary_match": "diagnostic_direct",
            "gross_net_interpretation": "gross site electricity consumption",
            "double_counting_rule": "distinct from WAG electricity and net grid import",
            "score_role": "holdout_diagnostic_only",
            "approved_input_status": "not_approved_diagnostic_only",
            "notes": "S3.3a comparison row; does not enter C0 calibration or approved inputs.",
        },
        {
            "crosswalk_id": "S33A_C1_CROSSWALK_002",
            "target_id": "C1_TABLE9_WAG_ELECTRICITY",
            "model_metric": "wag_electricity_twh_per_year",
            "boundary_match": "diagnostic_direct",
            "gross_net_interpretation": "internal WAG-to-power electricity output",
            "double_counting_rule": "reported separately; WAG fuel energy is not primary input",
            "score_role": "holdout_diagnostic_only",
            "approved_input_status": "not_approved_diagnostic_only",
            "notes": "Diagnostic row for Phase 1 WAG electricity under C1 structural switches.",
        },
        {
            "crosswalk_id": "S33A_C1_CROSSWALK_003",
            "target_id": "C1_TABLE9_NATURAL_GAS_FLOW",
            "model_metric": "natural_gas_m3_per_h",
            "boundary_match": "diagnostic_adapter_with_explicit_residual_boundary_switch",
            "gross_net_interpretation": "gross external NG flow",
            "double_counting_rule": "NG energy counted once through external gas import",
            "score_role": "holdout_diagnostic_only",
            "approved_input_status": "not_approved_diagnostic_only",
            "notes": "Residual C1 NG boundary switch is diagnostic-only and source-needed.",
        },
        {
            "crosswalk_id": "S33A_C1_CROSSWALK_004",
            "target_id": "C1_TABLE9_DIRECT_CO2",
            "model_metric": "direct_site_co2_t_per_year",
            "boundary_match": "diagnostic_provisional",
            "gross_net_interpretation": "direct site emissions proxy",
            "double_counting_rule": "Scope 2 reported separately",
            "score_role": "holdout_diagnostic_only",
            "approved_input_status": "not_approved_diagnostic_only",
            "notes": "Athanasiadis Phase 1 CO2 boundary remains uncertain.",
        },
        {
            "crosswalk_id": "S33A_C1_CROSSWALK_005",
            "target_id": "C1_FIG104_TOTAL_PRIMARY_PROXY",
            "model_metric": "athanasiadis_primary_proxy_pj_per_year",
            "boundary_match": "diagnostic_soft_proxy",
            "gross_net_interpretation": "coal-origin energy plus NG plus gross electricity",
            "double_counting_rule": "WAG fuel energy is internal conversion and not added again",
            "score_role": "soft_holdout_diagnostic_only",
            "approved_input_status": "not_approved_diagnostic_only",
            "notes": "Figure 104 proxy used for C1 interpretation, not C0 tuning.",
        },
    ]


def s3_3b_source_support_rows() -> list[dict[str, Any]]:
    rows = [
        (
            "S33B_MECH_001",
            "BF7 closed in Phase 1",
            "A_PHASE1_CLOSURE_PAIR_001;STEEL-SC-0013;deepsearch_2",
            "Internal Phase 1 topology notes and climate-neutral pathways evidence",
            "docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md;research_memos/deepsearch_2_tata_ijmuiden_topology_validation_targets.md",
            "BF7 closes/replaced in preferred Phase 1 reading.",
            "qualitative",
            "C1 topology",
            "C1",
            "B/C",
            "source-backed enough",
            "represented through C1 route-share topology proxy; no asset-level BF7 unit split yet",
            "Public evidence supports closure but current MILP has aggregate BF-BOF route.",
        ),
        (
            "S33B_MECH_002",
            "KGF2 closed in Phase 1",
            "A_PHASE1_CLOSURE_PAIR_001;STEEL-SC-0013;deepsearch_2;deepsearch_4",
            "Internal Phase 1 topology and WAG evidence",
            "docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md;research_memos/deepsearch_4_wags_internal_energy_emissions.md",
            "KGF2 closes while KGF1 remains in default Phase 1.",
            "qualitative",
            "C1 coking topology",
            "C1",
            "B/C",
            "provisional-dev",
            "retain existing route-share-scaled coking proxy; do not invent a numeric KGF2-specific factor",
            "Exact KGF1/KGF2 COG split is not public in current source cards.",
        ),
        (
            "S33B_MECH_003",
            "KGF1 retained in Phase 1",
            "A_KGF1_PHASE1_001;deepsearch_2;deepsearch_4",
            "Internal retained coking assumption",
            "docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md",
            "KGF1 remains unless a separate early-closure scenario is declared.",
            "qualitative",
            "C1 coking topology",
            "C1",
            "B/C",
            "source-backed enough",
            "represented by keeping nonzero COG/coking proxy in C1",
            "Aggregate coking proxy cannot identify KGF1 independently.",
        ),
        (
            "S33B_MECH_004",
            "DRP natural-gas intensity",
            "STEEL-SC-0021;EVID-0067;s3_c1_route_energy_inputs",
            "Athanasiadis Phase 1 component input",
            "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_c1_route_energy_inputs.csv",
            DRP_NATURAL_GAS_M3_PER_T_PELLETS,
            "m3_NG/t_pellets",
            "pellets input",
            "C1",
            "B",
            "source-backed enough",
            "implemented via converted m3/t steel route coefficient; report explicit DRP NG separately",
            "Activity-basis conversion must remain visible.",
        ),
        (
            "S33B_MECH_005",
            "DRP capacity",
            "STEEL-SC-0021;EVID-0064",
            "Athanasiadis Phase 1 component capacity",
            "steel_candidate_parameter_evidence_register.csv",
            DRP_CAPACITY_PELLETS_TPH,
            "t_pellets/h",
            "pellets input",
            "C1",
            "B",
            "source-backed enough",
            "used to add capacity-implied C1 route-share diagnostic",
            "Capacity-implied route share is diagnostic/validation, not an approved exact route split.",
        ),
        (
            "S33B_MECH_006",
            "Pellets-to-DRI efficiency",
            "STEEL-SC-0021;EVID-0065",
            "Athanasiadis Phase 1 component coefficient",
            "steel_candidate_parameter_evidence_register.csv",
            DRP_PELLETS_TO_DRI_EFFICIENCY,
            "t_DRI/t_pellets",
            "pellets input",
            "C1",
            "B",
            "source-backed enough",
            "used in route-share capacity check and C1 route input conversion",
            "",
        ),
        (
            "S33B_MECH_007",
            "DRI-to-steel/EAF efficiency",
            "STEEL-SC-0021;EVID-0059",
            "Athanasiadis Phase 1 component coefficient",
            "steel_candidate_parameter_evidence_register.csv",
            EAF_DRI_TO_STEEL_EFFICIENCY,
            "t_steel/t_DRI",
            "DRI input",
            "C1",
            "B",
            "source-backed enough",
            "used in route-share capacity check and C1 route input conversion",
            "",
        ),
        (
            "S33B_MECH_008",
            "C1 route-share case near BF-BOF 0.50",
            "STEEL-SC-0021;EVID-0064;EVID-0065;EVID-0059",
            "Capacity-implied route split from public DRP capacity",
            "derived from 500*0.74*0.95 at 6.2 Mt/y",
            c1_capacity_implied_bf_bof_share(),
            "fraction BF-BOF",
            "annual final product throughput",
            "C1",
            "B/D",
            "provisional-dev",
            "implemented as added C1 diagnostic route-share case; existing 0.55/0.61/0.68 retained",
            "It is a capacity-implied diagnostic, not proof of Tata exact route share.",
        ),
        (
            "S33B_MECH_009",
            "Reduced C1 BFG/COG/BOFG production from topology",
            "deepsearch_4;S30B_WAG_POLICY",
            "WAG source volumes fall when BF7/KGF2 close and DRP/EAF enters",
            "docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md",
            "qualitative reduction in BF/coke/oxygas availability",
            "qualitative",
            "route/WAG source production",
            "C1",
            "C",
            "provisional-dev",
            "represented only through route-share-scaled BF-BOF/coking proxy; no arbitrary WAG cap",
            "Needs source-carded gas-source split for stronger implementation.",
        ),
        (
            "S33B_MECH_010",
            "C1 WAG hierarchy to process/steam/boiler before power",
            "S30B_WAG_POL_P5;deepsearch_4",
            "WAG allocation policy and MER-derived WAG use interpretation",
            "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_wag_policy_decision_register.csv",
            "process/self-use, steam/boiler, import-offset power, flare",
            "qualitative hierarchy",
            "WAG allocation",
            "C0/C1",
            "C/D",
            "source-backed enough",
            "already represented in model constraints; S3.3b reports WAG-use components",
            "Numeric C1 steam/boiler demand remains weak.",
        ),
        (
            "S33B_MECH_011",
            "C1 NG top-up/back-up for process heat/steam/boilers",
            "deepsearch_4;NG_TATA_VN25_TOPUP",
            "MER-derived VN25/top-up/back-up discussion",
            "docs/optimisation/steel/research_memos/deepsearch_4_wags_internal_energy_emissions.md",
            "NG top-up when product gases do not satisfy minimum fuel need",
            "qualitative",
            "process heat/steam/boiler NG",
            "C1",
            "C",
            "source-needed",
            "not implemented numerically in S3.3b",
            "No governed numeric top-up demand or efficiency was found; do not substitute S3.3a gap closure.",
        ),
        (
            "S33B_MECH_012",
            "Vattenfall/WAG generator/interface Phase 1 changes",
            "A_VATTENFALL_INTERFACE_001;STEEL-SC-0014;STEEL-SC-0015;deepsearch_7",
            "Vattenfall interface and WAG electricity evidence",
            "docs/optimisation/steel/STEEL_ASSUMPTION_REGISTER.md;research_memos/deepsearch_7_WAG.md",
            "Interface/generator behaviour changes are public qualitatively.",
            "qualitative",
            "WAG-to-power interface",
            "C1",
            "C",
            "source-needed",
            "not implemented as numeric availability cap",
            "No public unit-commitment/interface limit supports a specific C1 power reduction factor.",
        ),
        (
            "S33B_MECH_013",
            "C1 residual/process-boundary NG",
            "S3.3a diagnostics;C1 Table 9",
            "Diagnostic Table 9 gap interpretation",
            "s3_3a_c1_diagnostic_decision_summary.csv",
            "S3.3a 89.478 m3/t_final_product diagnostic symptom",
            "m3/t_final_product",
            "final product residual boundary",
            "C1",
            "D",
            "rejected",
            "not promoted; no generic residual gap-closure input added",
            "Could be missing DRP/process/boiler NG or boundary mismatch, but is not a source-carded input.",
        ),
        (
            "S33B_MECH_014",
            "C1 emissions boundary",
            "Athanasiadis Table 9;S3.3 boundary crosswalk",
            "Phase 1 CO2 holdout target",
            "s3_3_target_boundary_crosswalk.csv",
            "CO2 is treated as direct-site proxy with uncertainty flag.",
            "tCO2/y",
            "direct-site proxy",
            "C1",
            "C/D",
            "provisional-dev",
            "no structural change; keep boundary warning in directional validation",
            "Athanasiadis/public boundary may include components not fully represented.",
        ),
    ]
    return [
        {
            "mechanism_id": row[0],
            "mechanism_name": row[1],
            "source_card_ids": row[2],
            "source_title": row[3],
            "source_location_or_section": row[4],
            "extracted_value_or_statement": row[5],
            "unit": row[6],
            "activity_basis": row[7],
            "c0_c1_applicability": row[8],
            "evidence_tier": row[9],
            "model_use_status": row[10],
            "implementation_decision": row[11],
            "limitation": row[12],
        }
        for row in rows
    ]


def s3_3b_route_share_capacity_rows() -> list[dict[str, Any]]:
    final_tph = calibration_hourly_target_t()
    drp_eaf_tph = DRP_CAPACITY_PELLETS_TPH * DRP_PELLETS_TO_DRI_EFFICIENCY * EAF_DRI_TO_STEEL_EFFICIENCY
    implied_drp_share = drp_eaf_tph / final_tph
    route_rows = []
    for bf_share in c1_s3_3b_route_shares():
        drp_share = 1.0 - bf_share
        pellets_tph = final_tph * drp_share / (DRP_PELLETS_TO_DRI_EFFICIENCY * EAF_DRI_TO_STEEL_EFFICIENCY)
        route_rows.append(
            {
                "case_id": f"c1_bf_bof_share_{bf_share:.6f}",
                "bf_bof_share": bf_share,
                "drp_eaf_share": drp_share,
                "average_final_product_tph": final_tph,
                "source_drp_capacity_pellets_tph": DRP_CAPACITY_PELLETS_TPH,
                "capacity_implied_drp_eaf_output_tph": drp_eaf_tph,
                "capacity_implied_drp_eaf_share": implied_drp_share,
                "capacity_implied_bf_bof_share": 1.0 - implied_drp_share,
                "scenario_pellets_required_tph": pellets_tph,
                "drp_capacity_utilisation_proxy": pellets_tph / DRP_CAPACITY_PELLETS_TPH,
                "case_role": "capacity_implied_added_s3_3b" if abs(bf_share - (1.0 - implied_drp_share)) <= 1e-9 else "pre_existing_s3_3_holdout_route_share",
                "approved_input_status": "diagnostic_not_approved_input",
            }
        )
    return route_rows


def s3_3b_structural_change_rows() -> list[dict[str, Any]]:
    return [
        {
            "change_id": "S33B_CHANGE_001",
            "mechanism_id": "S33B_MECH_008",
            "change_type": "route_share_case_added",
            "implemented": "true",
            "source_or_basis": "DRP capacity 500 t pellets/h * 0.74 * 0.95 at 6.2 Mt/y",
            "approved_input_status": "diagnostic_not_approved_input",
            "notes": "Adds BF-BOF share near 0.503; keeps 0.55/0.61/0.68 cases.",
        },
        {
            "change_id": "S33B_CHANGE_002",
            "mechanism_id": "S33B_MECH_004",
            "change_type": "metric_boundary_reporting",
            "implemented": "true",
            "source_or_basis": "DRP NG 195 m3/t pellets, converted to route coefficient",
            "approved_input_status": "existing_provisional_dev_input",
            "notes": "Directional validation reports explicit DRP NG separately from inherited residual NG.",
        },
        {
            "change_id": "S33B_CHANGE_003",
            "mechanism_id": "S33B_MECH_010",
            "change_type": "metric_boundary_reporting",
            "implemented": "true",
            "source_or_basis": "Existing WAG hierarchy constraints",
            "approved_input_status": "existing_model_logic",
            "notes": "Reports WAG process, steam/boiler, reheating, and power uses.",
        },
        {
            "change_id": "S33B_CHANGE_004",
            "mechanism_id": "S33B_MECH_011",
            "change_type": "numeric_ng_topup",
            "implemented": "false",
            "source_or_basis": "Qualitative top-up evidence lacks governed numeric value",
            "approved_input_status": "source_needed",
            "notes": "No S3.3a NG gap-closure value promoted.",
        },
        {
            "change_id": "S33B_CHANGE_005",
            "mechanism_id": "S33B_MECH_012",
            "change_type": "numeric_wag_interface_reduction",
            "implemented": "false",
            "source_or_basis": "No source-carded C1 WAG-to-power availability factor",
            "approved_input_status": "source_needed",
            "notes": "No S3.3a WAG availability cap promoted.",
        },
    ]


def s3_3c_source_support_rows() -> list[dict[str, Any]]:
    rows = [
        (
            "S33C_MECH_001",
            "limited utility heat and steam boundary",
            "WAG-SC-014;WAG-SC-015;WAG-SC-016;WAG-SC-017;deepsearch_8:S3",
            "Tata site utility and Vattenfall interface evidence",
            "source-backed enough for structure; candidate-only for numerical dispatch",
            "Energiebedrijf/Vattenfall interface, gas/steam/electricity distribution, and broader site boundary are public.",
            "qualitative",
            "site utility boundary",
            "C1 holdout boundary interpretation",
            "candidate_boundary_extension",
            "Implement as explicit utility heat node; no unit commitment or Tata-exact dispatch.",
        ),
        (
            "S33C_MECH_002",
            "downstream/light-side natural-gas heat demand",
            "deepsearch_8:S3;PBL/TNO-style Tata reconstruction",
            "Downstream/light-side gas demand boundary evidence",
            "candidate input",
            "7.5-8.0",
            "PJ_NG_NCV/year",
            "annual downstream/light-side heat and utility boundary",
            "C1 boundary extension sensitivity",
            "candidate_input_not_approved",
            "Used as explicit downstream/utility demand evidence, not as C1 residual NG gap closure.",
        ),
        (
            "S33C_MECH_003",
            "Dutch natural-gas NCV conversion",
            "deepsearch_8 candidate library",
            "NCV conversion for downstream/light-side NG",
            "candidate input",
            S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3,
            "GJ/Nm3",
            "PJ/year to Nm3/h conversion",
            "reporting and comparison",
            "candidate_conversion_not_approved",
            "Separated from existing S3.1 model gas energy content; no hidden unit swap.",
        ),
        (
            "S33C_MECH_004",
            "WAG hierarchy to process/steam/heat before power and flare",
            "WAG-SC-007;WAG-SC-008;WAG-SC-018;s3_wag_policy_decision_register",
            "Internal co-product gas hierarchy evidence",
            "source-backed enough for structure",
            "process/heat/steam -> power -> flare",
            "allocation hierarchy",
            "WAG carrier balances",
            "C0/C1",
            "implemented_structure",
            "Still not a full Vattenfall dispatch model.",
        ),
        (
            "S33C_MECH_005",
            "WAG-to-power efficiency sensitivity",
            "STEEL-SC-0010;STEEL-WAG-EVID-0022;deepsearch_8:S2",
            "Integrated-mill gas-to-power efficiency",
            "candidate sensitivity",
            "0.321-0.422",
            "fraction LHV to electricity",
            "per GJ WAG fuel input",
            "C1 sensitivity only",
            "candidate_sensitivity_not_recalibration",
            "Does not create an arbitrary C1 WAG cap or availability factor.",
        ),
        (
            "S33C_MECH_006",
            "S3.3a rejected residuals remain rejected",
            "s3_3a_c1_diagnostic_decision_summary.csv;s3_3b_c1_source_support_register.csv",
            "Rejected diagnostic values",
            "rejected",
            "c1_wag_availability_factor=0.75; residual NG=89.478 m3/t_final_product",
            "diagnostic symptoms",
            "not model inputs",
            "C1",
            "not_promoted",
            "S3.3c must not use gap-closure scalars.",
        ),
    ]
    return [
        {
            "mechanism_id": row[0],
            "mechanism_name": row[1],
            "source_card_ids_or_evidence": row[2],
            "source_title": row[3],
            "source_card_status": row[4],
            "extracted_value_or_statement": row[5],
            "unit": row[6],
            "activity_basis": row[7],
            "c0_c1_applicability": row[8],
            "model_use_status": row[9],
            "limitation": row[10],
        }
        for row in rows
    ]


def s3_3c_structural_change_rows() -> list[dict[str, Any]]:
    return [
        {
            "change_id": "S33C_CHANGE_001",
            "mechanism_id": "S33C_MECH_001",
            "change_type": "utility_heat_node_added",
            "implemented": "true",
            "approved_input_status": "candidate_boundary_extension_not_approved_input",
            "notes": "Adds explicit downstream/light-side utility heat demand and WAG/NG service arcs.",
        },
        {
            "change_id": "S33C_CHANGE_002",
            "mechanism_id": "S33C_MECH_002",
            "change_type": "downstream_light_side_ng_candidate",
            "implemented": "true",
            "approved_input_status": "candidate_input_not_gap_closure",
            "notes": "Uses 7.5-8.0 PJ/y sensitivity as boundary evidence; not fitted to Table 9.",
        },
        {
            "change_id": "S33C_CHANGE_003",
            "mechanism_id": "S33C_MECH_005",
            "change_type": "wag_to_power_efficiency_sensitivity",
            "implemented": "true",
            "approved_input_status": "candidate_sensitivity_only",
            "notes": "Adds optional 0.321 public lower efficiency case without changing C0 calibrated parameter sets.",
        },
        {
            "change_id": "S33C_CHANGE_004",
            "mechanism_id": "S33C_MECH_006",
            "change_type": "blocked_arbitrary_gap_values",
            "implemented": "true",
            "approved_input_status": "blocked",
            "notes": "No S3.3a WAG availability factor or residual NG gap scalar is promoted.",
        },
    ]


def s3_3c_candidate_parameter_rows() -> list[dict[str, Any]]:
    hourly_final = calibration_hourly_target_t()
    rows: list[dict[str, Any]] = []
    for case_id, pj_per_year in S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR.items():
        nm3_per_h = (
            pj_per_year * 1_000_000.0 / HOURS_PER_YEAR / S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3
            if pj_per_year > 0
            else 0.0
        )
        rows.append(
            {
                "parameter_id": f"s3_3c_downstream_light_side_ng_{case_id}",
                "parameter_name": "downstream_light_side_utility_heat_boundary",
                "case_id": case_id,
                "selected_value": pj_per_year,
                "unit": "PJ_NG_NCV_per_year",
                "converted_nm3_per_h": nm3_per_h,
                "converted_nm3_per_t_final": nm3_per_h / hourly_final if hourly_final > 0 else 0.0,
                "activity_basis": "annual downstream/light-side site utility boundary",
                "source_or_policy_basis": "PBL/TNO-style Tata site reconstruction via S3.3c evidence audit",
                "evidence_tier": "C",
                "model_use_status": "candidate_boundary_extension",
                "approved_input_status": "not_approved_input",
                "limitations": "Not C1 residual gap closure; represents broader utility boundary evidence.",
            }
        )
    for case_id, value in S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY.items():
        rows.append(
            {
                "parameter_id": f"s3_3c_wag_to_power_efficiency_{case_id}",
                "parameter_name": "wag_to_power_efficiency_fraction",
                "case_id": case_id,
                "selected_value": "" if value is None else value,
                "unit": "fraction",
                "converted_nm3_per_h": "",
                "converted_nm3_per_t_final": "",
                "activity_basis": "per GJ WAG fuel input",
                "source_or_policy_basis": "STEEL-WAG-EVID-0022 public gas-to-power efficiency range",
                "evidence_tier": "B/C",
                "model_use_status": "candidate_sensitivity",
                "approved_input_status": "not_approved_input",
                "limitations": "Sensitivity only; not a C1 availability cap or Vattenfall dispatch truth.",
            }
        )
    return rows


def s3_3c_boundary_mapping_rows() -> list[dict[str, Any]]:
    return [
        {
            "boundary_item": "C1 Table 9 natural gas",
            "pre_s3_3c_status": "broader_boundary_holdout_context",
            "s3_3c_mapping": "DRP NG + inherited C0 residual NG + explicit downstream/light-side utility heat NG",
            "strict_validation_status": "directional_validation_only_until_source_review",
            "double_counting_rule": "Utility NG is external natural gas; WAG fuel energy is not added again as primary energy.",
        },
        {
            "boundary_item": "C1 Table 9 WAG electricity",
            "pre_s3_3c_status": "C1 WAG-to-power high versus target",
            "s3_3c_mapping": "WAG remaining after process, steam, reheating, utility heat and flare through power interface",
            "strict_validation_status": "directional_validation_only_until Vattenfall/interface evidence is approved",
            "double_counting_rule": "WAG electricity is internal conversion output, not extra primary input.",
        },
        {
            "boundary_item": "Figure 104 primary proxy",
            "pre_s3_3c_status": "soft broader-boundary holdout",
            "s3_3c_mapping": "external coal proxy + external natural gas + gross electricity; WAG not added separately",
            "strict_validation_status": "soft_holdout",
            "double_counting_rule": "Coal-origin WAG is not double-counted.",
        },
    ]


def s3_3d_utility_assumption_review_rows() -> list[dict[str, Any]]:
    return [
        {
            "assumption_id": "S33D_ASSUMP_001",
            "assumption_name": "limited utility heat and steam boundary structure",
            "s3_3c_source_mechanism_id": "S33C_MECH_001",
            "source_card_ids_or_evidence": "WAG-SC-014;WAG-SC-015;WAG-SC-016;WAG-SC-017;STEEL-WAG-EVID-0043",
            "low_value": "",
            "central_value": "qualitative interface abstraction",
            "high_value": "",
            "unit": "qualitative",
            "central_value_rationale": "Public evidence supports a site utility/interface boundary, not a unit-commitment model.",
            "classification": "boundary evidence",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "retain structure for provisional validation",
            "freeze_implication": "structure can remain, but numeric utility dispatch remains provisional",
        },
        {
            "assumption_id": "S33D_ASSUMP_002",
            "assumption_name": "downstream/light-side utility natural-gas boundary",
            "s3_3c_source_mechanism_id": "S33C_MECH_002",
            "source_card_ids_or_evidence": "PBL/TNO-style Tata reconstruction via S3.3c source-support register",
            "low_value": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "central_value": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "high_value": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "unit": "PJ_NG_NCV_per_year",
            "central_value_rationale": "Midpoint of the governed 7.5-8.0 PJ/y candidate boundary range.",
            "classification": "provisional input",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "use low/central/high only for retained-ensemble validation",
            "freeze_implication": "cannot freeze until source-card review promotes the boundary value or keeps Table 9 contextual",
        },
        {
            "assumption_id": "S33D_ASSUMP_003",
            "assumption_name": "Dutch natural-gas NCV conversion",
            "s3_3c_source_mechanism_id": "S33C_MECH_003",
            "source_card_ids_or_evidence": "S3.3c candidate conversion evidence",
            "low_value": S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3,
            "central_value": S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3,
            "high_value": S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3,
            "unit": "GJ_per_Nm3",
            "central_value_rationale": "Used only to convert the candidate PJ/y boundary to Nm3/h for validation reporting.",
            "classification": "candidate input",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "retain for transparent conversion in S3.3d artifacts",
            "freeze_implication": "requires normal input-governance promotion if carried forward",
        },
        {
            "assumption_id": "S33D_ASSUMP_004",
            "assumption_name": "WAG hierarchy before power and flare",
            "s3_3c_source_mechanism_id": "S33C_MECH_004",
            "source_card_ids_or_evidence": "WAG-SC-007;WAG-SC-008;WAG-SC-018;s3_wag_policy_decision_register",
            "low_value": "",
            "central_value": "process/steam/heat before power, flare last",
            "high_value": "",
            "unit": "qualitative hierarchy",
            "central_value_rationale": "Matches established S3 WAG allocation policy and prevents WAG double-counting.",
            "classification": "boundary evidence",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "retain as structural policy",
            "freeze_implication": "numeric heat/steam sinks still need governed values",
        },
        {
            "assumption_id": "S33D_ASSUMP_005",
            "assumption_name": "WAG-to-power efficiency sensitivity",
            "s3_3c_source_mechanism_id": "S33C_MECH_005",
            "source_card_ids_or_evidence": "STEEL-SC-0010;STEEL-WAG-EVID-0022",
            "low_value": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"],
            "central_value": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["central_public_candidate"],
            "high_value": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["high_public_candidate"],
            "unit": "fraction_LHV_to_electricity",
            "central_value_rationale": "Midpoint of the source-carded public 32.1-42.2% candidate efficiency range.",
            "classification": "sensitivity only",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "use low/central/high as retained-ensemble sensitivity, not as Tata dispatch truth",
            "freeze_implication": "not sufficient by itself to promote C1 validation",
        },
        {
            "assumption_id": "S33D_ASSUMP_006",
            "assumption_name": "Vattenfall/VN24/VN25/IJM-01 operating details",
            "s3_3c_source_mechanism_id": "S33C_MECH_001",
            "source_card_ids_or_evidence": "STEEL-WAG-EVID-0043;STEEL-WAG-EVID-0044;STEEL-WAG-EVID-0045",
            "low_value": "",
            "central_value": "interface context only",
            "high_value": "",
            "unit": "qualitative/context",
            "central_value_rationale": "Public records support interface existence but not dispatch or unit-commitment coefficients.",
            "classification": "context only",
            "approved_input_status": "not_approved_input",
            "s3_3d_decision": "do not model as plant-specific dispatch",
            "freeze_implication": "Table 9 WAG-power validation remains broader-boundary/contextual without stronger evidence",
        },
        {
            "assumption_id": "S33D_ASSUMP_007",
            "assumption_name": "generic S3.3a WAG availability factor",
            "s3_3c_source_mechanism_id": "S33C_MECH_006",
            "source_card_ids_or_evidence": "s3_3a_c1_structural_diagnostic_results.csv",
            "low_value": "",
            "central_value": "0.75",
            "high_value": "",
            "unit": "diagnostic_fraction",
            "central_value_rationale": "Diagnostic symptom only; not source-carded.",
            "classification": "rejected",
            "approved_input_status": "blocked",
            "s3_3d_decision": "not promoted",
            "freeze_implication": "must not be used for freeze",
        },
        {
            "assumption_id": "S33D_ASSUMP_008",
            "assumption_name": "generic S3.3a C1 NG gap-closure residual",
            "s3_3c_source_mechanism_id": "S33C_MECH_006",
            "source_card_ids_or_evidence": "s3_3a_c1_structural_diagnostic_results.csv",
            "low_value": "",
            "central_value": "89.478",
            "high_value": "",
            "unit": "m3_per_t_final_product",
            "central_value_rationale": "Back-calculated diagnostic gap closure only; not source-carded.",
            "classification": "rejected",
            "approved_input_status": "blocked",
            "s3_3d_decision": "not promoted",
            "freeze_implication": "must not be used for freeze",
        },
        {
            "assumption_id": "S33D_ASSUMP_009",
            "assumption_name": "inherited C0 residual natural-gas closure in C1",
            "s3_3c_source_mechanism_id": "S3.3 calibration parameter residual_c0_ng_m3_per_t_final",
            "source_card_ids_or_evidence": "s3_3_calibration_parameter_register.csv;s3_3_selected_parameter_ensemble.csv",
            "low_value": "",
            "central_value": "candidate-set-specific",
            "high_value": "",
            "unit": "m3_per_t_final_product",
            "central_value_rationale": "C0 calibration closure is carried into C1 validation unless explicitly decomposed.",
            "classification": "source needed",
            "approved_input_status": "blocked",
            "s3_3d_decision": "audit and block from freeze promotion",
            "freeze_implication": "S3.3 cannot freeze with this term ambiguous",
        },
    ]


def s3_3d_promoted_candidate_parameter_rows() -> list[dict[str, Any]]:
    return [
        {
            "parameter_set_id": "s3_3d_provisional_utility_low",
            "promotion_scope": "promoted_to_s3_3d_provisional_validation_only",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"],
            "classification": "provisional input",
            "approved_input_status": "not_approved_input",
            "source_basis": "low end of downstream/light-side boundary range plus public lower WAG-to-power sensitivity",
            "notes": "Retained for ensemble validation; not a freeze-ready approved input set.",
        },
        {
            "parameter_set_id": "s3_3d_provisional_utility_central",
            "promotion_scope": "promoted_to_s3_3d_provisional_validation_only",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["central_public_candidate"],
            "classification": "provisional input",
            "approved_input_status": "not_approved_input",
            "source_basis": "midpoint central values from governed candidate ranges",
            "notes": "Central S3.3d review case; not an approved input shell.",
        },
        {
            "parameter_set_id": "s3_3d_provisional_utility_high",
            "promotion_scope": "promoted_to_s3_3d_provisional_validation_only",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["high_public_candidate"],
            "classification": "sensitivity only",
            "approved_input_status": "not_approved_input",
            "source_basis": "high end of downstream/light-side boundary range plus public upper WAG-to-power sensitivity",
            "notes": "Upper sensitivity; not a Vattenfall/Tata dispatch claim.",
        },
    ]


def s3_3d_rejected_or_blocked_assumption_rows() -> list[dict[str, Any]]:
    return [
        {
            "assumption_id": "S33D_BLOCK_001",
            "assumption_name": "c1_wag_availability_factor_0_75",
            "blocked_value": 0.75,
            "unit": "fraction",
            "source_or_basis": "S3.3a diagnostic symptom",
            "rejection_reason": "not source-carded and would act as arbitrary C1 WAG cap",
            "final_status": "rejected",
        },
        {
            "assumption_id": "S33D_BLOCK_002",
            "assumption_name": "residual_ng_89_478_m3_per_t_final",
            "blocked_value": 89.478,
            "unit": "m3_per_t_final_product",
            "source_or_basis": "S3.3a Table 9 gap-closure back-calculation",
            "rejection_reason": "fitted residual gap closure, not explicit source-backed utility consumer",
            "final_status": "rejected",
        },
        {
            "assumption_id": "S33D_BLOCK_003",
            "assumption_name": "inherited_c0_residual_ng_in_c1",
            "blocked_value": "candidate-set-specific",
            "unit": "m3_per_t_final_product",
            "source_or_basis": "S3.3 C0 calibration residual_c0_ng_m3_per_t_final",
            "rejection_reason": "ambiguous C0 calibration closure carried into C1; not decomposed into retained process gas or utility consumer",
            "final_status": "blocked_for_freeze",
        },
    ]


def s3_3e_ng_component_candidate_rows() -> list[dict[str, Any]]:
    return [
        {
            "component_id": "S33E_NG_COMP_001",
            "component_name": "explicit NG-DRP natural gas",
            "source_card_or_register_ref": "STEEL-WAG-EVID-0067;S33B_MECH_004",
            "value_or_range": DRP_NATURAL_GAS_M3_PER_T_PELLETS,
            "unit": "m3_NG_per_t_pellets",
            "conversion_formula": "route DRI/EAF output / (0.74 * 0.95) * 195 m3/t_pellets",
            "activity_basis": "NG-DRP pellets input",
            "c0_c1_applicability": "C1",
            "confidence": "medium",
            "governance_status": "source-backed enough",
            "decomposition_decision": "accepted_already_represented",
            "double_counting_note": "Separate from inherited residual; not counted in downstream/light-side utility NG.",
        },
        {
            "component_id": "S33E_NG_COMP_002",
            "component_name": "downstream/light-side utility natural gas",
            "source_card_or_register_ref": "S33C_MECH_002;S33D_ASSUMP_002",
            "value_or_range": "7.5-8.0",
            "unit": "PJ_NG_NCV_per_year",
            "conversion_formula": "PJ/y * 1e6 / 8760 / 0.03165 GJ/Nm3",
            "activity_basis": "annual downstream/light-side utility boundary",
            "c0_c1_applicability": "C1 broader-boundary validation",
            "confidence": "medium",
            "governance_status": "provisional input",
            "decomposition_decision": "accepted_as_provisional_boundary_component_not_residual",
            "double_counting_note": "May not be used again to explain inherited residual NG.",
        },
        {
            "component_id": "S33E_NG_COMP_003",
            "component_name": "steam/boiler natural-gas top-up",
            "source_card_or_register_ref": "STEEL-WAG-EVID-0019;STEEL-WAG-EVID-0024;STEEL-WAG-EVID-0043",
            "value_or_range": "qualitative_only",
            "unit": "not_available",
            "conversion_formula": "not_available",
            "activity_basis": "steam or boiler interface",
            "c0_c1_applicability": "both or C1 context",
            "confidence": "medium structural, low numeric",
            "governance_status": "source-needed",
            "decomposition_decision": "rejected_for_numeric_decomposition",
            "double_counting_note": "No numeric top-up component available without fitted residual.",
        },
        {
            "component_id": "S33E_NG_COMP_004",
            "component_name": "retained BF/hot-stove auxiliary natural gas",
            "source_card_or_register_ref": "STEEL-WAG-EVID-0054;STEEL-WAG-EVID-0055;STEEL-WAG-EVID-0056",
            "value_or_range": "BFG/COG process-fuel values only",
            "unit": "Nm3_BFG_or_COG_per_t_hot_metal",
            "conversion_formula": "not_applicable_to_NG_residual",
            "activity_basis": "BF hot-metal activity",
            "c0_c1_applicability": "C0 reference context",
            "confidence": "medium for WAG process fuel, not NG",
            "governance_status": "rejected",
            "decomposition_decision": "rejected_not_natural_gas_component",
            "double_counting_note": "Would double count WAG process fuel if treated as NG.",
        },
        {
            "component_id": "S33E_NG_COMP_005",
            "component_name": "coking underfiring or coking steam demand",
            "source_card_or_register_ref": "STEEL-WAG-EVID-0052;STEEL-WAG-EVID-0053",
            "value_or_range": "3.2-3.9 GJ_fuel/t_coke; 0.06-0.80 GJ_steam/t_coke",
            "unit": "GJ_per_t_coke",
            "conversion_formula": "requires retained C1 coke activity and fuel split not governed here",
            "activity_basis": "onsite coke",
            "c0_c1_applicability": "C0; C1 only if retained coking split is source-carded",
            "confidence": "medium range, weak C1 applicability",
            "governance_status": "source-needed",
            "decomposition_decision": "rejected_for_c1_residual_decomposition",
            "double_counting_note": "Cannot allocate to NG without coking fuel split; may overlap WAG/coking accounting.",
        },
        {
            "component_id": "S33E_NG_COMP_006",
            "component_name": "gas enrichment or backup fuel",
            "source_card_or_register_ref": "STEEL-WAG-EVID-0024",
            "value_or_range": "qualitative_only",
            "unit": "not_available",
            "conversion_formula": "not_available",
            "activity_basis": "deficit off-gas treatment",
            "c0_c1_applicability": "both context",
            "confidence": "medium structural, no numeric coefficient",
            "governance_status": "source-needed",
            "decomposition_decision": "rejected_for_numeric_decomposition",
            "double_counting_note": "Could justify a future mechanism, not the inherited C0 residual value.",
        },
        {
            "component_id": "S33E_NG_COMP_007",
            "component_name": "inherited residual C0 natural gas closure",
            "source_card_or_register_ref": "S33D_RESIDUAL_NG audit",
            "value_or_range": "46.97 m3/t_final = 33243.607 m3/h at 6.2 Mt/y",
            "unit": "m3_NG_per_t_final_product",
            "conversion_formula": "46.97 * 6200000 / 8760",
            "activity_basis": "C0 calibration closure",
            "c0_c1_applicability": "C0 calibration only",
            "confidence": "high as audit identity, zero as C1 source support",
            "governance_status": "blocked",
            "decomposition_decision": "rejected_not_source_backed_c1_component",
            "double_counting_note": "Must be set to zero in C1 residual-resolution validation.",
        },
    ]


def s3_3e_static_decomposition_attempt_rows() -> list[dict[str, Any]]:
    inherited_m3_per_t = 46.97
    inherited_m3_per_h = inherited_m3_per_t * calibration_hourly_target_t()
    inherited_pj_per_year = inherited_m3_per_h * HOURS_PER_YEAR * S3_3C_NATURAL_GAS_NCV_GJ_PER_NM3 / 1_000_000.0
    return [
        {
            "attempt_id": "S33E_ATTEMPT_001",
            "option_attempted": "Option A source-backed inherited residual decomposition",
            "inherited_residual_ng_m3_per_t_final": inherited_m3_per_t,
            "inherited_residual_ng_m3_per_h": inherited_m3_per_h,
            "inherited_residual_ng_pj_per_year_ncv": inherited_pj_per_year,
            "component_search_result": "no source-backed retained C1 component found for full or material residual",
            "accepted_decomposition_m3_per_h": 0.0,
            "blocked_remainder_m3_per_h": inherited_m3_per_h,
            "decision": "Option A rejected; apply Option B validation-boundary downgrade",
            "notes": "Existing source cards support explicit DRP NG and provisional downstream utility NG, but not the inherited C0 residual as C1 process gas.",
        }
    ]


def s3_3e_accept_reject_decision_rows() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "S33E_DECISION_001",
            "item": "explicit DRP NG",
            "decision": "accept",
            "freeze_role": "strict internal process-network component",
            "reason": "Source-carded C1 DRP NG intensity and activity basis are explicit and already represented.",
        },
        {
            "decision_id": "S33E_DECISION_002",
            "item": "downstream/light-side utility NG",
            "decision": "retain_provisional",
            "freeze_role": "broader-boundary sensitivity/context",
            "reason": "Boundary evidence is useful but remains provisional and must not be used as fitted gap closure.",
        },
        {
            "decision_id": "S33E_DECISION_003",
            "item": "inherited C0 residual NG",
            "decision": "reject_for_c1",
            "freeze_role": "not freeze-relevant",
            "reason": "Equals C0 calibration closure and lacks source-backed C1 decomposition.",
        },
        {
            "decision_id": "S33E_DECISION_004",
            "item": "Table 9 carrier totals",
            "decision": "downgrade_to_contextual_holdout",
            "freeze_role": "directional broader-boundary reference",
            "reason": "Carrier totals include broader utility/site boundary not fully represented by the public MILP.",
        },
    ]


def s3_3e_validation_boundary_decision_rows() -> list[dict[str, Any]]:
    return [
        {
            "boundary_id": "S33E_BOUNDARY_001",
            "target_group": "Athanasiadis Table 9 carrier totals",
            "previous_role": "strict C1 principal holdout gate",
            "new_role": "broader-boundary contextual holdout",
            "strict_freeze_use": "false",
            "contextual_reporting_use": "true",
            "reason": "Inherited C0 residual cannot be decomposed into source-backed C1 gas consumers without hidden residual fitting.",
        },
        {
            "boundary_id": "S33E_BOUNDARY_002",
            "target_group": "current public MILP process-network checks",
            "previous_role": "implicit feasibility checks",
            "new_role": "strict S3.3e freeze checks",
            "strict_freeze_use": "true",
            "contextual_reporting_use": "false",
            "reason": "Production, terminal neutrality, material/energy/carbon accounting, and no-double-counting match the represented boundary.",
        },
        {
            "boundary_id": "S33E_BOUNDARY_003",
            "target_group": "C1 carrier-direction checks",
            "previous_role": "principal pass/fail target",
            "new_role": "directional site-level holdout",
            "strict_freeze_use": "false",
            "contextual_reporting_use": "true",
            "reason": "Reported to preserve transparency but not used as a freeze gate.",
        },
    ]


def s3_3f_parameter_eligibility_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    include_ids = {
        "residual_auxiliary_electricity_scale",
        "downstream_electricity_scale",
        "steam_process_heat_scale",
        "bfg_generation_nm3_per_t_hot_metal",
        "cog_generation_m3_per_t_dry_coal",
        "bofg_generation_nm3_per_t_liquid_steel",
        "wag_lhv_scale",
        "wag_to_power_efficiency_fraction",
        "wag_residual_utilisation_fraction",
        "coal_primary_energy_factor_gj_per_t_dry_coal",
        "bf_bof_aggregate_direct_co2_t_per_t_bof",
    }
    for parameter in calibration_parameters():
        eligible = parameter.parameter_id in include_ids
        exclusion_reason = ""
        lower = parameter.lower
        central = parameter.source_central
        upper = parameter.upper
        if parameter.parameter_id == "residual_c0_ng_m3_per_t_final":
            exclusion_reason = "blocked_for_c1_bounded_alignment_inherited_c0_residual_or_gap_closure"
        elif parameter.parameter_id == "drp_natural_gas_intensity":
            eligible = True
        elif parameter.parameter_id == "c1_route_share":
            eligible = True
            lower = c1_capacity_implied_bf_bof_share()
            central = 0.61
            upper = 0.68
            exclusion_reason = ""
        elif parameter.status != "calibratable" and parameter.parameter_id not in {"drp_natural_gas_intensity", "c1_route_share"}:
            exclusion_reason = "fixed_excluded_or_not_a_c1_bounded_alignment_parameter"
        rows.append(
            {
                "parameter_id": parameter.parameter_id,
                "parameter_group": parameter.group,
                "unit": parameter.unit,
                "activity_basis": parameter.activity_basis,
                "lower": lower,
                "central": central,
                "upper": upper,
                "evidence_tier": parameter.evidence_tier,
                "model_use_status": parameter.model_use_status,
                "source_or_policy_basis": parameter.source_or_policy_basis,
                "eligible_for_s3_3f": "true" if eligible else "false",
                "varied_in_search": "true" if eligible else "false",
                "exclusion_reason": exclusion_reason,
                "approved_input_status": "not_approved_input",
                "notes": "Existing governed/source-carded range reused for bounded C1 diagnostic only.",
            }
        )
    rows.extend(
        [
            {
                "parameter_id": "downstream_light_side_utility_ng_pj_per_year",
                "parameter_group": "downstream/light-side utility natural gas",
                "unit": "PJ_NG_NCV_per_year",
                "activity_basis": "annual downstream/light-side utility boundary",
                "lower": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["disabled"],
                "central": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
                "upper": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
                "evidence_tier": "D",
                "model_use_status": "provisional_validation_only_not_approved_input",
                "source_or_policy_basis": "S3.3c/S3.3d downstream/light-side utility boundary register",
                "eligible_for_s3_3f": "true",
                "varied_in_search": "true",
                "exclusion_reason": "",
                "approved_input_status": "not_approved_input",
                "notes": "Uses 0.0 plus 7.5-8.0 PJ/y governed candidate range; nonzero cases are broader-boundary diagnostics.",
            },
            {
                "parameter_id": "c1_wag_availability_factor",
                "parameter_group": "arbitrary C1 WAG availability correction",
                "unit": "fraction",
                "activity_basis": "WAG residual utilisation multiplier",
                "lower": "",
                "central": "",
                "upper": "",
                "evidence_tier": "not_source_carded",
                "model_use_status": "rejected",
                "source_or_policy_basis": "S3.3a/S3.3c/S3.3d rejection records",
                "eligible_for_s3_3f": "false",
                "varied_in_search": "false",
                "exclusion_reason": "no governed/source-carded lower-central-upper range; arbitrary diagnostic factor",
                "approved_input_status": "blocked",
                "notes": "S3.3f must not use the S3.3a arbitrary WAG availability switch.",
            },
            {
                "parameter_id": "c1_residual_ng_boundary_m3_per_t_final",
                "parameter_group": "C1 residual natural-gas gap closure",
                "unit": "m3/t_final_product",
                "activity_basis": "per tonne final product",
                "lower": "",
                "central": "",
                "upper": "",
                "evidence_tier": "not_source_carded",
                "model_use_status": "rejected",
                "source_or_policy_basis": "S3.3a/S3.3e rejection records",
                "eligible_for_s3_3f": "false",
                "varied_in_search": "false",
                "exclusion_reason": "back-calculated Table 9 residual gap closure is forbidden",
                "approved_input_status": "blocked",
                "notes": "S3.3f reports the remaining gap instead of closing it.",
            },
        ]
    )
    return rows


def s3_3f_rejected_mechanism_rows() -> list[dict[str, Any]]:
    return [
        {
            "mechanism_id": "S33F_REJECT_001",
            "mechanism": "inherited C0 residual NG carryover",
            "status": "rejected_not_run",
            "reason": "S3.3e classified residual_c0_ng_m3_per_t_final as a C0 calibration closure, not a C1 source-backed gas consumer.",
            "would_affect_target": "natural_gas",
            "approved_input_status": "blocked",
        },
        {
            "mechanism_id": "S33F_REJECT_002",
            "mechanism": "Table 9 back-calculated C1 residual NG term",
            "status": "rejected_not_run",
            "reason": "Would fit the target from the holdout value itself and violate the no residual gap-closure rule.",
            "would_affect_target": "natural_gas",
            "approved_input_status": "blocked",
        },
        {
            "mechanism_id": "S33F_REJECT_003",
            "mechanism": "arbitrary C1 WAG availability correction",
            "status": "rejected_not_run",
            "reason": "S3.3a diagnostic WAG factors lack source-carded lower/central/upper ranges.",
            "would_affect_target": "wag_electricity",
            "approved_input_status": "blocked",
        },
        {
            "mechanism_id": "S33F_REJECT_004",
            "mechanism": "arbitrary WAG-to-power cap or Vattenfall dispatch correction",
            "status": "rejected_not_run",
            "reason": "Only governed WAG-to-power efficiency and residual-utilisation ranges are eligible; no fitted cap is allowed.",
            "would_affect_target": "wag_electricity",
            "approved_input_status": "blocked",
        },
        {
            "mechanism_id": "S33F_REJECT_005",
            "mechanism": "unsupported missing-value zero",
            "status": "rejected_by_design",
            "reason": "Candidate construction only uses registered numeric ranges; missing bounds are excluded instead of silently filled.",
            "would_affect_target": "all",
            "approved_input_status": "blocked",
        },
    ]


def s3_3g_athanasiadis_gas_network_source_card_rows() -> list[dict[str, Any]]:
    return [
        {
            "source_card_id": "S33G_ATH_GAS_001",
            "source_item": "Section 3.3.2 Gas Network",
            "source_status": "existing_human_verified_source_packet_pdf_not_available_in_allowed_paths",
            "structure_or_value": "gas network controller with WAG and NG substitution pathways",
            "classification": "athanasiadis_source_backed_structure",
            "figure_or_table": "Section 3.3.2",
            "value": "",
            "unit": "",
            "c1_relevance": "Defines named gas sinks and internal WAG routing context.",
            "figure_caption_ambiguity_note": "PDF-direct check blocked because the thesis PDF was not present in the allowed checked locations.",
        },
        {
            "source_card_id": "S33G_ATH_GAS_002",
            "source_item": "main plants gas controller",
            "source_status": "existing_prompt_screenshot_and_research_memo_context",
            "structure_or_value": "HSM, Coking Plant 1, pelletizing firing, and pelletizing grinding gas-fuel pathways",
            "classification": "athanasiadis_source_backed_structure",
            "figure_or_table": "Figure 31 in extracted text; uploaded screenshot caption ambiguity recorded",
            "value": "",
            "unit": "",
            "c1_relevance": "Supports named process gas sinks but not every numeric allocation.",
            "figure_caption_ambiguity_note": "User notes screenshots show main-plants controller; extracted text maps this to Figure 31 while Figure 32 refers to boilers/steam.",
        },
        {
            "source_card_id": "S33G_ATH_GAS_003",
            "source_item": "boiler and steam demand gas controller",
            "source_status": "existing_prompt_screenshot_and_research_memo_context",
            "structure_or_value": "boilers consume WAGs and/or natural gas to satisfy plant and residual steam demand",
            "classification": "athanasiadis_model_assumption",
            "figure_or_table": "Figure 32 in extracted text",
            "value": "",
            "unit": "",
            "c1_relevance": "Supports explicit boiler_steam_ng and boiler_steam_wag diagnostic sinks.",
            "figure_caption_ambiguity_note": "Caption numbering not reverified against PDF because the PDF was not available locally in allowed paths.",
        },
        {
            "source_card_id": "S33G_ATH_GAS_004",
            "source_item": "Vattenfall generators IJ01, VN24, VN25",
            "source_status": "existing_prompt_screenshot_and_research_memo_context",
            "structure_or_value": "generator gas mixture limited by gas availability, contracts, prices, and LHV constraints; VN24 backup",
            "classification": "athanasiadis_model_assumption",
            "figure_or_table": "Figure 33 in extracted text",
            "value": "",
            "unit": "",
            "c1_relevance": "Supports LHV-limited WAG-to-power diagnostic mechanism, not a fitted WAG availability factor.",
            "figure_caption_ambiguity_note": "PDF-direct figure check not completed for lack of local PDF in allowed paths.",
        },
        {
            "source_card_id": "S33G_ATH_GAS_005",
            "source_item": "upper generator mixture heating value",
            "source_status": "source_needed_for_approved_input",
            "structure_or_value": "upper mixture heating value around 5",
            "classification": "diagnostic_only",
            "figure_or_table": "Figure 33 surrounding explanation",
            "value": 5.0,
            "unit": "MJ/m3",
            "c1_relevance": "Used only to label Vattenfall LHV-limited generation cases.",
            "figure_caption_ambiguity_note": "",
        },
        {
            "source_card_id": "S33G_ATH_GAS_006",
            "source_item": "COG lower heating value",
            "source_status": "source_needed_for_approved_input",
            "structure_or_value": "COG LHV",
            "classification": "diagnostic_only_numeric",
            "figure_or_table": "Gas-network explanation",
            "value": 18.5,
            "unit": "MJ/m3",
            "c1_relevance": "Classifies high-LHV gas injection paths.",
            "figure_caption_ambiguity_note": "",
        },
        {
            "source_card_id": "S33G_ATH_GAS_007",
            "source_item": "BOFG lower heating value",
            "source_status": "source_needed_for_approved_input",
            "structure_or_value": "BOFG LHV",
            "classification": "diagnostic_only_numeric",
            "figure_or_table": "Gas-network explanation",
            "value": 8.6,
            "unit": "MJ/m3",
            "c1_relevance": "Classifies pelletizing grinding fuel substitution path.",
            "figure_caption_ambiguity_note": "",
        },
        {
            "source_card_id": "S33G_ATH_GAS_008",
            "source_item": "BFG lower heating value",
            "source_status": "source_needed_for_approved_input",
            "structure_or_value": "BFG LHV",
            "classification": "diagnostic_only_numeric",
            "figure_or_table": "Gas-network explanation",
            "value": 3.85,
            "unit": "MJ/m3",
            "c1_relevance": "Classifies generator BFG-equivalent WAG use.",
            "figure_caption_ambiguity_note": "",
        },
        {
            "source_card_id": "S33G_ATH_GAS_009",
            "source_item": "NG lower heating value",
            "source_status": "source_needed_for_approved_input",
            "structure_or_value": "NG LHV",
            "classification": "diagnostic_only_numeric",
            "figure_or_table": "Gas-network explanation",
            "value": 37.5,
            "unit": "MJ/m3",
            "c1_relevance": "Classifies external NG sink energy basis.",
            "figure_caption_ambiguity_note": "",
        },
        {
            "source_card_id": "S33G_ATH_GAS_010",
            "source_item": "Phase 1 Table 9 / Figure 104",
            "source_status": "human_verified_s3_3_target_packet",
            "structure_or_value": "C1 target boundary used for diagnostic scoring only",
            "classification": "athanasiadis_source_backed_target",
            "figure_or_table": "Table 9 and Figure 104",
            "value": "",
            "unit": "",
            "c1_relevance": "C1 alignment score target; not used to back-calculate a residual.",
            "figure_caption_ambiguity_note": "",
        },
    ]


def s3_3g_gas_sink_parameter_eligibility_rows() -> list[dict[str, Any]]:
    hsm_low = 1.28 * CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 1_000_000.0
    hsm_central = 1.39 * CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 1_000_000.0
    hsm_high = 1.50 * CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 1_000_000.0
    pellet_central = DRP_CAPACITY_PELLETS_TPH * HOURS_PER_YEAR * 0.43 / 1_000_000.0
    common = {
        "c0_c1_applicability": "C1 diagnostic active; C0 calibration not retuned",
        "approved_input_status": "not_approved_input",
    }
    rows = [
        ("hsm_fuel_substitution_ng", "NG", hsm_low, hsm_central, hsm_high, "PJ_NG_NCV/year", "HSM/reheating fuel at 6.2 Mt/y final product", "public/source-carded numeric range", "S3.3g public reheating-furnace range 1.28-1.50 GJ/t_final from research memo", "true", "true", "false", "true", "false"),
        ("hsm_fuel_substitution_cog", "COG", "", "", "", "PJ_COG_NCV/year", "HSM/reheating fuel substitution", "source-needed", "Athanasiadis structure supports COG or NG, but no governed numeric COG allocation was found locally", "false", "false", "true", "false", "true"),
        ("coking_plant_1_bfg", "BFG", "", "", "", "PJ_BFG_NCV/year", "Coking Plant 1 fuel mix", "source-needed", "Athanasiadis structure supports BFG/COG/mix, but no governed numeric allocation was found locally", "false", "false", "true", "false", "true"),
        ("coking_plant_1_cog", "COG", "", "", "", "PJ_COG_NCV/year", "Coking Plant 1 fuel mix", "source-needed", "Athanasiadis structure supports BFG/COG/mix, but no governed numeric allocation was found locally", "false", "false", "true", "false", "true"),
        ("pelletizing_firing_ng", "NG", 0.80 * pellet_central, pellet_central, 1.20 * pellet_central, "PJ_NG_NCV/year", "0.43 GJ/t pellet at 500 t/h DRP pellet capacity", "governed provisional numeric range", "JRC/BREF-style pellet firing intensity from S3 research memo; +/-20 pct diagnostic envelope", "true", "true", "false", "true", "false"),
        ("pelletizing_firing_cog", "COG", "", "", "", "PJ_COG_NCV/year", "pelletizing firing fuel substitution", "source-needed", "Athanasiadis structure supports NG/COG/mix, but no governed COG split was found locally", "false", "false", "true", "false", "true"),
        ("pelletizing_grinding_ng", "NG", "", "", "", "PJ_NG_NCV/year", "pelletizing grinding fuel substitution", "source-needed", "Athanasiadis structure supports NG/BOFG/mix, but no governed numeric allocation was found locally", "false", "false", "true", "false", "true"),
        ("pelletizing_grinding_bofg", "BOFG", "", "", "", "PJ_BOFG_NCV/year", "pelletizing grinding fuel substitution", "source-needed", "Athanasiadis structure supports NG/BOFG/mix, but no governed BOFG split was found locally", "false", "false", "true", "false", "true"),
        ("boiler_steam_ng", "NG", 0.0, 1.0, 2.0, "PJ_NG_NCV/year", "boiler/steam demand allocation within S3.3c utility boundary", "diagnostic-only governed provisional range", "Athanasiadis boiler/steam structure plus S3.3c broader-boundary range; numeric split source-needed", "true", "true", "false", "true", "true"),
        ("boiler_steam_wag", "WAG", 0.0, 1.0, 2.0, "PJ_WAG_NCV/year", "boiler/steam demand allocation within S3.3c utility boundary", "diagnostic-only governed provisional range", "Athanasiadis boiler/steam structure plus S3.3c broader-boundary range; numeric split source-needed", "true", "false", "true", "false", "true"),
        ("vattenfall_generator_bfg_equivalent_wag", "BFG_equivalent_WAG", 0.50, 0.75, 1.00, "fraction", "WAG residual utilisation/interface limit", "existing governed range", "S3.3 calibration parameter wag_residual_utilisation_fraction", "true", "false", "true", "false", "true"),
        ("vattenfall_generator_high_lhv_injection_limit", "high_LHV_gas_limit", 5.0, 5.0, 5.0, "MJ/m3", "generator gas-mixture upper heating-value guardrail", "diagnostic-only source-needed numeric", "Athanasiadis gas-network explanation; PDF-direct source card still needed", "true", "false", "true", "false", "true"),
    ]
    return [
        {
            "sink_id": sink_id,
            "fuel": fuel,
            "lower": lower,
            "central": central,
            "upper": upper,
            "unit": unit,
            "basis": basis,
            "numeric_parameter_support": support,
            "source_or_policy_basis": source,
            "eligible_for_s3_3g_diagnostic_variation": eligible,
            "contributes_to_ng": contributes_ng,
            "contributes_to_wag_consumption": contributes_wag,
            "contributes_to_emissions": contributes_emissions,
            "source_needed_before_approved_input": source_needed,
            "model_use_status": "diagnostic_only",
            **common,
        }
        for (
            sink_id,
            fuel,
            lower,
            central,
            upper,
            unit,
            basis,
            support,
            source,
            eligible,
            contributes_ng,
            contributes_wag,
            contributes_emissions,
            source_needed,
        ) in rows
    ]


def s3_3h_phased_parameter_classification_rows() -> list[dict[str, Any]]:
    rows = [
        ("c1_route_share", "C1-only", "varied_block_a", "fraction BF-BOF", c1_capacity_implied_bf_bof_share(), 0.55, "C1 route-share scenario; not applied to C0 regression.", "source_carded_scenario"),
        ("hsm_fuel_substitution_ng", "C1-only", "varied_block_a", "PJ_NG_NCV/year", 7.936, 9.300, "HSM/reheating NG range from S3.3g source-card review.", "source_supported_numeric"),
        ("pelletizing_firing_ng", "C1-only", "varied_block_a", "PJ_NG_NCV/year", 1.50672, 2.26008, "Pelletizing firing NG range from S3.3g source-card review.", "governed_provisional_numeric"),
        ("boiler_steam_ng", "C1-only", "varied_block_a_gap_sizing", "PJ_NG_NCV/year", 0.0, 6.0, "0-2 PJ/y existing diagnostic range; 3/4/6 PJ/y labelled gap-sizing only.", "diagnostic_only_extended"),
        ("boiler_steam_wag", "C1-only", "varied_block_a_gap_sizing", "PJ_WAG_NCV/year", 0.0, 6.0, "0-2 PJ/y existing diagnostic range; 3/4/6 PJ/y labelled gap-sizing only.", "diagnostic_only_extended"),
        ("vattenfall_generator_bfg_equivalent_wag", "C1-only", "varied_block_a", "fraction", 0.50, 1.00, "C1-only Vattenfall/LHV interface diagnostic; not applied to C0 regression.", "existing_governed_diagnostic"),
        ("downstream_electricity_scale", "shared", "varied_block_b_with_c0_regression", "multiplier", 0.75, 1.50, "Grouped downstream and ASU electricity scale with governed range.", "governed_shared_parameter"),
        ("residual_auxiliary_electricity_scale", "shared", "varied_block_b_with_c0_regression", "multiplier", 1.00, 5.00, "Shared residual auxiliary electricity closure parameter.", "governed_shared_parameter"),
        ("wag_to_power_efficiency_fraction", "shared", "varied_block_b_with_c0_regression", "fraction", 0.321, 0.422, "Shared WAG-to-power efficiency range; not an arbitrary WAG availability factor.", "governed_shared_parameter"),
        ("wag_lhv_scale", "shared", "varied_block_b_with_c0_regression", "multiplier", 0.90, 1.10, "Shared grouped WAG LHV scale.", "governed_shared_parameter"),
        ("eaf_electricity_intensity", "shared", "not_varied_source_needed", "MWh/t", "", "", "Relevant category, but no independent governed S3.3 calibration knob exists in the current runner.", "source_needed_not_exposed"),
        ("drp_electricity_intensity", "shared", "not_varied_source_needed", "MWh/t", "", "", "Relevant category, but no independent governed S3.3 calibration knob exists in the current runner.", "source_needed_not_exposed"),
        ("residual_c0_ng_m3_per_t_final", "forbidden", "blocked", "m3/t_final_product", "", "", "Inherited C0 residual NG must not be used as C1 fit term.", "rejected_gap_closure"),
        ("c1_residual_ng_boundary_m3_per_t_final", "forbidden", "blocked", "m3/t_final_product", "", "", "Back-calculated Table 9 residual NG closure is forbidden.", "rejected_gap_closure"),
        ("c1_wag_availability_factor", "forbidden", "blocked", "fraction", "", "", "Arbitrary WAG availability factor remains forbidden.", "rejected_arbitrary_factor"),
    ]
    return [
        {
            "parameter_id": parameter_id,
            "parameter_class": parameter_class,
            "s3_3h_use": use,
            "unit": unit,
            "lower": lower,
            "upper": upper,
            "basis": basis,
            "source_status": source_status,
            "approved_input_status": "not_approved_input",
            "c0_retuned": "false",
            "notes": "S3.3h diagnostic alignment only; no freeze or S4 entry.",
        }
        for parameter_id, parameter_class, use, unit, lower, upper, basis, source_status in rows
    ]


def target_conflict_rows() -> list[dict[str, Any]]:
    return [
        {
            "conflict_id": "S33_CONFLICT_001",
            "target_ids": "C0_FIG96_ELECTRICITY_SHARE_DISPUTED;C0_TABLE8_GROSS_ELECTRICITY",
            "source_values": "Figure96 electricity share 9.3 pct implies about 2.651 TWh/year; Table8 reports 3.17 TWh/year",
            "decision": "Use c0_table8_primary for calibration; keep c0_figure96_reported as soft audit.",
            "source_inconsistency_flag": "true",
            "calibration_score_impact": "Figure 96 electricity share excluded from score.",
            "notes": "Reported Figure 96 carrier shares are not overwritten.",
        },
        {
            "conflict_id": "S33_CONFLICT_002",
            "target_ids": "C1_FIG104_TOTAL_PRIMARY_PROXY",
            "source_values": "User previously referred to Figure 107; confirmed values correspond to Figure 104.",
            "decision": "Record Figure 104 as holdout-validation source.",
            "source_inconsistency_flag": "false",
            "calibration_score_impact": "No C1 values enter C0 calibration score.",
            "notes": "",
        },
    ]


def calibration_parameters() -> list[CalibrationParameter]:
    return [
        CalibrationParameter("residual_auxiliary_electricity_scale", "residual auxiliary electricity", "multiplier", "residual MWh/t final product", 1.0, 1.0, 5.0, "calibratable", "D", "calibration_parameter", "S3.1 residual auxiliary electricity selected row with S3.3 calibration range", "Aggregate site-electricity closure; weakly physically identified."),
        CalibrationParameter("downstream_electricity_scale", "caster/DSP/HSM/ASU electricity intensity scales", "multiplier", "selected downstream and ASU MWh/t coefficients", 0.75, 1.0, 1.5, "calibratable", "D", "calibration_parameter", "S3.1 selected coefficient ranges", "Grouped scale cannot identify individual plant components."),
        CalibrationParameter("residual_c0_ng_m3_per_t_final", "residual C0 natural-gas demand", "m3/t_final_product", "per tonne final product", 0.0, 0.0, 70.0, "calibratable", "D", "calibration_parameter", "Explicit S3.3 residual site NG closure parameter", "Required because represented C0 process heat can be fully WAG-served."),
        CalibrationParameter("steam_process_heat_scale", "steam/boiler/process-heat demand scale", "multiplier", "WAG process and steam useful demand", 0.8, 1.0, 1.5, "calibratable", "D", "calibration_parameter", "S3.1 WAG heat-use assumptions", "Aggregates several heat sinks."),
        CalibrationParameter("bfg_generation_nm3_per_t_hot_metal", "BFG generation yield", "Nm3/t_hot_metal", "per tonne BF hot metal", 1200.0, 1600.0, 2000.0, "calibratable", "B/C", "calibration_parameter", "STEEL-SC-0001 JRC/BREF range", "Not Tata-exact."),
        CalibrationParameter("cog_generation_m3_per_t_dry_coal", "COG generation yield", "m3/t_dry_coal", "per tonne dry coal", 280.0, 365.0, 450.0, "calibratable", "B/C", "calibration_parameter", "STEEL-SC-0001 JRC/BREF range", "Not Tata-exact."),
        CalibrationParameter("bofg_generation_nm3_per_t_liquid_steel", "BOFG generation yield", "Nm3/t_liquid_steel", "per tonne BOF liquid steel", 50.0, 75.0, 100.0, "calibratable", "B/C", "calibration_parameter", "STEEL-SC-0001 JRC/BREF range", "Suppressed-combustion proxy."),
        CalibrationParameter("wag_lhv_scale", "carrier LHV scale", "multiplier", "BFG COG BOFG LHV values", 0.9, 1.0, 1.1, "calibratable", "B/C", "calibration_parameter", "S3.0b selected WAG LHV ranges collapsed to compact group", "Grouped LHV scale weakens carrier-level identifiability."),
        CalibrationParameter("wag_to_power_efficiency_fraction", "WAG-to-power efficiency", "fraction", "per GJ WAG fuel input", 0.321, 0.3715, 0.422, "calibratable", "B/C", "calibration_parameter", "S3.0b selected WAG-to-power efficiency range", "Interface proxy, not Vattenfall dispatch."),
        CalibrationParameter("wag_residual_utilisation_fraction", "WAG residual utilisation/interface limit", "fraction", "residual WAG after mandatory heat uses", 0.50, 0.50, 1.00, "calibratable", "D", "calibration_parameter", "S3.3 policy range extends S3.2 no-export interface to test near-zero normal flare", "Not export revenue; bounded internal generation only."),
        CalibrationParameter("coal_primary_energy_factor_gj_per_t_dry_coal", "coal/coke primary-energy factor", "GJ/t_dry_coal", "per tonne coking dry coal proxy", 25.0, 29.3, 52.0, "calibratable", "D", "calibration_parameter", "S3.3 Athanasiadis-compatible carrier proxy factor", "Primary-energy proxy only; not a WAG double-counting term."),
        CalibrationParameter("bf_bof_aggregate_direct_co2_t_per_t_bof", "BF-BOF/coking residual direct-emissions factor", "tCO2/t_BOF_liquid_steel", "per tonne BOF liquid steel", 1.6, 1.8, 2.5, "calibratable", "D", "calibration_parameter", "S3.2 BF-BOF aggregate direct CO2 proxy range extended for C0 target fitting", "Boundary uncertain; cannot be interpreted as Tata-exact."),
        CalibrationParameter("c1_route_share", "C1 route share", "fraction", "BF-BOF share", 0.55, 0.61, 0.68, "holdout/scenario", "D", "holdout_scenario", "User-confirmed C1 holdout route-share scenarios", "Not used in C0 calibration score."),
        CalibrationParameter("drp_natural_gas_intensity", "DRP NG intensity", "multiplier", "C1 DRP m3/t steel", 0.8, 1.0, 1.3, "holdout/scenario", "B", "holdout_sensitivity_only", "Athanasiadis C1 component source", "Not varied in S3.3 C0 calibration."),
        CalibrationParameter("da_prices", "price parameters", "not_applicable", "market prices", 0.0, 0.0, 0.0, "excluded", "not_applicable", "excluded", "S3.3 physical calibration policy", "Prices must not calibrate physical energy and emissions targets."),
        CalibrationParameter("production_target", "production target", "t/year", "annual final product", CALIBRATION_ANNUAL_FINAL_PRODUCT_T, CALIBRATION_ANNUAL_FINAL_PRODUCT_T, CALIBRATION_ANNUAL_FINAL_PRODUCT_T, "fixed physical", "D", "fixed_physical_parameter", "User-confirmed 6.2 Mt calibration scale", "Not varied."),
        CalibrationParameter("slab_yard_capacity", "storage capacity", "t_slab", "absolute cold slab yard", SLAB_YARD_CAPACITY_T, SLAB_YARD_CAPACITY_T, SLAB_YARD_CAPACITY_T, "fixed physical", "B", "fixed_physical_parameter", "Athanasiadis S2.13a amendment", "Not varied in base calibration."),
        CalibrationParameter("hot_metal_buffer_capacity", "storage capacity", "t_hot_metal", "absolute hot-metal buffer", HOT_METAL_BUFFER_CAPACITY_T, HOT_METAL_BUFFER_CAPACITY_T, HOT_METAL_BUFFER_CAPACITY_T, "fixed physical", "B", "fixed_physical_parameter", "Athanasiadis Figure 65", "Not varied."),
    ]


def parameter_register_rows() -> list[dict[str, Any]]:
    return [
        {
            "parameter_id": p.parameter_id,
            "parameter_group": p.group,
            "unit": p.unit,
            "activity_basis": p.activity_basis,
            "lower": p.lower,
            "central": p.source_central,
            "upper": p.upper,
            "source_or_policy_basis": p.source_or_policy_basis,
            "evidence_tier": p.evidence_tier,
            "model_use_status": p.model_use_status,
            "limitations": p.limitations,
            "sensitivity_status": p.sensitivity_status,
            "classification": p.status,
        }
        for p in calibration_parameters()
    ]


def eligible_calibration_parameters() -> list[CalibrationParameter]:
    return [p for p in calibration_parameters() if p.status == "calibratable"]


def source_central_parameter_set() -> dict[str, float]:
    return {p.parameter_id: p.source_central for p in eligible_calibration_parameters()}


def calibration_anchor_parameter_set() -> dict[str, float]:
    values = source_central_parameter_set()
    values.update(
        {
            "residual_auxiliary_electricity_scale": 3.85,
            "residual_c0_ng_m3_per_t_final": 46.97,
            "wag_residual_utilisation_fraction": 0.95,
            "coal_primary_energy_factor_gj_per_t_dry_coal": 44.0,
            "bf_bof_aggregate_direct_co2_t_per_t_bof": 2.15568,
        }
    )
    return values


def candidate_parameter_sets(*, seed: int = DEFAULT_SEED, max_candidates: int = DEFAULT_MAX_CANDIDATES) -> list[dict[str, Any]]:
    if max_candidates < 2:
        raise ValueError("max_candidates must be at least 2.")
    parameters = eligible_calibration_parameters()
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []

    source = source_central_parameter_set()
    rows.append({"candidate_id": "S33_CAND_000_SOURCE_CENTRAL", "candidate_role": "source_central", **source})
    if max_candidates > 1:
        anchor = calibration_anchor_parameter_set()
        rows.append({"candidate_id": "S33_CAND_001_CALIBRATION_ANCHOR", "candidate_role": "calibration_anchor", **anchor})

    envelope_variants = [
        ("S33_CAND_002_LOW_WAG_ENVELOPE", "low_energy_wag_envelope", {"bfg_generation_nm3_per_t_hot_metal": 1500.0, "cog_generation_m3_per_t_dry_coal": 345.0, "wag_lhv_scale": 0.99, "wag_residual_utilisation_fraction": 1.0}),
        ("S33_CAND_003_HIGH_WAG_ENVELOPE", "high_energy_wag_envelope", {"bfg_generation_nm3_per_t_hot_metal": 1630.0, "cog_generation_m3_per_t_dry_coal": 375.0, "wag_lhv_scale": 1.0, "wag_residual_utilisation_fraction": 0.97}),
        ("S33_CAND_004_LOW_ELECTRICITY_ENVELOPE", "low_electricity_envelope", {"residual_auxiliary_electricity_scale": 3.68, "downstream_electricity_scale": 1.0}),
        ("S33_CAND_005_HIGH_ELECTRICITY_ENVELOPE", "high_electricity_envelope", {"residual_auxiliary_electricity_scale": 4.04, "downstream_electricity_scale": 1.0}),
    ]
    for candidate_id, role, updates in envelope_variants:
        if len(rows) >= max_candidates:
            break
        values = calibration_anchor_parameter_set()
        values.update(updates)
        rows.append({"candidate_id": candidate_id, "candidate_role": role, **values})

    remaining = max_candidates - len(rows)
    if remaining <= 0:
        return rows[:max_candidates]

    samples_by_parameter: dict[str, list[float]] = {}
    for parameter in parameters:
        values = []
        for idx in range(remaining):
            unit = (idx + rng.random()) / float(remaining)
            values.append(parameter.lower + unit * (parameter.upper - parameter.lower))
        rng.shuffle(values)
        samples_by_parameter[parameter.parameter_id] = values

    start_index = len(rows)
    for idx in range(remaining):
        row = {
            "candidate_id": f"S33_CAND_{start_index + idx:03d}_LHS",
            "candidate_role": "latin_hypercube",
        }
        for parameter in parameters:
            row[parameter.parameter_id] = samples_by_parameter[parameter.parameter_id][idx]
        rows.append(row)
    return rows


def candidate_values(row: dict[str, Any] | pd.Series) -> dict[str, float]:
    return {
        p.parameter_id: float(row[p.parameter_id])
        for p in eligible_calibration_parameters()
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows supplied for {path.name}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_static_s3_3_governance_artifacts() -> dict[str, Path]:
    overlay_rows = [
        {
            "overlay_id": "site_scale_6_2Mt_calibration",
            "annual_final_product_t": CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
            "target_24h_t": final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=24),
            "target_168h_t": final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=168),
            "slab_yard_capacity_t": SLAB_YARD_CAPACITY_T,
            "hot_metal_buffer_capacity_t": HOT_METAL_BUFFER_CAPACITY_T,
            "dsp_share": 0.20,
            "legacy_baseline_preserved": "true",
            "approved_input_shell_populated": "false",
            "notes": "S3.3 provisional calibration overlay; does not overwrite S2.13/S3.2 development baseline.",
        }
    ]
    _write_csv(CALIBRATION_OVERLAY_PATH, overlay_rows)
    _write_csv(S3_3_OUTPUT_PATHS["production_scale"], production_scale_and_capacity_rows())
    _write_csv(S3_3_OUTPUT_PATHS["target_register"], target_register_rows())
    _write_csv(S3_3_OUTPUT_PATHS["boundary_crosswalk"], boundary_crosswalk_rows())
    _write_csv(S3_3_OUTPUT_PATHS["target_conflict"], target_conflict_rows())
    _write_csv(S3_3_OUTPUT_PATHS["parameter_register"], parameter_register_rows())
    return {"overlay": CALIBRATION_OVERLAY_PATH, **S3_3_OUTPUT_PATHS}
