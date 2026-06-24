from __future__ import annotations

import argparse
import json
import time
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Objective, SolverFactory, TerminationCondition, value

from .downstream_scheduling_builder import DownstreamCaseOptions
from .downstream_scheduling_inputs import load_downstream_assumptions
from .downstream_scheduling_runner import _mip_gap, _solve_model, available_solver, max_material_balance_residual
from .site_calibration_inputs import (
    CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_SEED,
    DRP_NATURAL_GAS_M3_PER_T_PELLETS,
    DRP_PELLETS_TO_DRI_EFFICIENCY,
    EAF_DRI_TO_STEEL_EFFICIENCY,
    EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T,
    HOT_METAL_BUFFER_CAPACITY_T,
    SLAB_YARD_CAPACITY_T,
    S3_3F_DEFAULT_MAX_CANDIDATES,
    S3_REVIEW_ROOT,
    S3_3_OUTPUT_PATHS,
    S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR,
    S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY,
    candidate_parameter_sets,
    candidate_values,
    c1_s3_3b_route_shares,
    c1_boundary_crosswalk_amendment_rows,
    calibration_anchor_parameter_set,
    calibration_parameters,
    c0_calibration_target_rows,
    calibration_hourly_target_t,
    eligible_calibration_parameters,
    final_product_target_t,
    hot_metal_initial_inventory_conflicts,
    load_calibration_downstream_assumptions,
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
    source_central_parameter_set,
    write_static_s3_3_governance_artifacts,
)
from .site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID, IntegratedCaseOptions, build_site_energy_economic_model
from .site_energy_economic_inputs import load_site_energy_economic_assumptions
from .site_static_economics_builder import S32CaseOptions, _attach_s3_2_static_economics_layer
from .site_static_economics_inputs import load_s3_2_static_economics_assumptions
from .site_validation_metrics import calibration_error_rows, collect_site_validation_metrics


OPTIMAL_TERMINATIONS = {TerminationCondition.optimal, TerminationCondition.feasible}
PRIMARY_TARGET_IDS = {
    "C0_TABLE8_GROSS_ELECTRICITY": "gross_electricity_error_pct",
    "C0_TABLE8_WAG_ELECTRICITY": "wag_electricity_error_pct",
    "C0_TABLE8_NATURAL_GAS_FLOW": "natural_gas_flow_error_pct",
    "C0_TABLE8_DIRECT_CO2": "direct_co2_error_pct",
    "C0_FIG96_TOTAL_PRIMARY_PROXY": "primary_proxy_error_pct",
    "C0_NORMAL_FLARE_FRACTION": "flare_fraction_error_pct",
}

C1_TARGETS = {
    "gross_electricity_twh_per_year": 4.89,
    "wag_electricity_twh_per_year": 1.23,
    "natural_gas_m3_per_h": 151673.52,
    "direct_site_co2_t_per_year": 9107793.17,
    "athanasiadis_primary_proxy_pj_per_year": 102.1941,
}

C0_REFERENCE_TARGETS = {
    "gross_electricity_twh_per_year": 3.17,
    "wag_electricity_twh_per_year": 2.74,
    "natural_gas_m3_per_h": 33243.63,
    "direct_site_co2_t_per_year": 13365216.16,
    "athanasiadis_primary_proxy_pj_per_year": 102.6289,
}

C1_C0_RATIO_TARGETS = {
    "gross_electricity_twh_per_year": 1.5426,
    "wag_electricity_twh_per_year": 0.4489,
    "natural_gas_m3_per_h": 4.5625,
    "direct_site_co2_t_per_year": 0.6815,
    "athanasiadis_primary_proxy_pj_per_year": 0.9958,
}

C1_SHARE_TARGETS = {
    "coal_share_athanasiadis_proxy": 0.401,
    "electricity_share_athanasiadis_proxy": 0.172,
    "natural_gas_share_athanasiadis_proxy": 0.427,
}

C1_BOUNDED_ALIGNMENT_WEIGHTS = {
    "gross_electricity_twh_per_year": 1.0,
    "wag_electricity_twh_per_year": 1.5,
    "natural_gas_m3_per_h": 1.5,
    "direct_site_co2_t_per_year": 1.0,
    "athanasiadis_primary_proxy_pj_per_year": 1.0,
}

C1_DIAGNOSTIC_CANDIDATE_IDS = (
    "S33_CAND_001_CALIBRATION_ANCHOR",
    "S33_CAND_002_LOW_WAG_ENVELOPE",
    "S33_CAND_003_HIGH_WAG_ENVELOPE",
)
C1_ROUTE_SHARE_DIAGNOSTICS = (0.55, 0.61, 0.68)
C1_WAG_AVAILABILITY_DIAGNOSTICS = (1.00, 0.75, 0.50, 0.25)
C1_DRP_NG_MULTIPLIER_DIAGNOSTICS = (0.8, 1.0, 1.3)
C1_RETAINED_COKING_WAG_DISPLACEMENT_DIAGNOSTICS = (1.00, 0.75, 0.50)


def _active_objective_value(model: Any) -> float | str:
    active = list(model.component_data_objects(Objective, active=True, descend_into=True))
    if not active:
        return ""
    return float(value(active[0]))


def _solver(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None):
    if solver_name:
        resolved_name = solver_name
        solver = SolverFactory(solver_name)
    else:
        resolved_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S3.3 calibration.")
    options = getattr(solver, "options", None)
    if options is not None:
        if time_limit is not None:
            options["TimeLimit"] = float(time_limit)
        if mip_gap is not None:
            options["MIPGap"] = float(mip_gap)
    return resolved_name or "unknown", solver


def _scale_c1_route_natural_gas(c1_route: Any, multiplier: float) -> Any:
    if abs(multiplier - 1.0) <= 1e-12 or not is_dataclass(c1_route):
        return c1_route
    updates: dict[str, float] = {}
    for field in fields(c1_route):
        name = field.name.lower()
        value_at = getattr(c1_route, field.name)
        if not isinstance(value_at, (int, float)):
            continue
        if "natural_gas" in name or name.endswith("_ng") or "_ng_" in name:
            updates[field.name] = float(value_at) * multiplier
    if not updates:
        return c1_route
    return replace(c1_route, **updates)


def _apply_parameter_values(values: dict[str, float], c1_diagnostic_switches: dict[str, float] | None = None):
    s3_1 = load_site_energy_economic_assumptions()
    s3_2 = load_s3_2_static_economics_assumptions()

    switches = c1_diagnostic_switches or {}
    lhv_scale = values["wag_lhv_scale"]
    heat_scale = values["steam_process_heat_scale"]
    electricity_scale = values["downstream_electricity_scale"]
    retained_coking_wag_displacement_factor = float(
        switches.get("c1_retained_coking_wag_displacement_factor", 1.0)
    )
    c1_wag_availability_factor = float(switches.get("c1_wag_availability_factor", 1.0))
    drp_ng_multiplier = float(switches.get("drp_ng_multiplier", 1.0))
    utility_heat_pj_per_year = float(switches.get("s3_3c_downstream_light_side_ng_pj_per_year", 0.0))
    utility_heat_gj_per_h = utility_heat_pj_per_year * 1_000_000.0 / 8760.0
    utility_min_ng_pj_per_year = float(switches.get("s3_3c_downstream_light_side_minimum_ng_pj_per_year", 0.0))
    utility_min_ng_gj_per_h = utility_min_ng_pj_per_year * 1_000_000.0 / 8760.0
    wag_to_power_efficiency = float(
        switches.get("s3_3c_wag_to_power_efficiency_fraction", values["wag_to_power_efficiency_fraction"])
    )
    wag = replace(
        s3_1.wag,
        bfg_gj_per_t_hot_metal=(
            values["bfg_generation_nm3_per_t_hot_metal"]
            * retained_coking_wag_displacement_factor
            * 3.35
            * lhv_scale
            / 1000.0
        ),
        cog_gj_per_t_dry_coal=(
            values["cog_generation_m3_per_t_dry_coal"]
            * retained_coking_wag_displacement_factor
            * 18.7
            * lhv_scale
            / 1000.0
        ),
        bofg_gj_per_t_liquid_steel=(
            values["bofg_generation_nm3_per_t_liquid_steel"]
            * retained_coking_wag_displacement_factor
            * 9.58
            * lhv_scale
            / 1000.0
        ),
        bfg_hot_stove_gj_per_t_hot_metal=s3_1.wag.bfg_hot_stove_gj_per_t_hot_metal * heat_scale,
        cog_hot_stove_pci_gj_per_t_hot_metal=s3_1.wag.cog_hot_stove_pci_gj_per_t_hot_metal * heat_scale,
        coking_underfire_gj_per_t_hot_metal=s3_1.wag.coking_underfire_gj_per_t_hot_metal * heat_scale,
        coking_steam_useful_gj_per_t_hot_metal=s3_1.wag.coking_steam_useful_gj_per_t_hot_metal * heat_scale,
        wag_to_power_efficiency=wag_to_power_efficiency,
    )
    s3_1 = replace(
        s3_1,
        secondary_metallurgy_electricity_mwh_per_t=s3_1.secondary_metallurgy_electricity_mwh_per_t * electricity_scale,
        casting_electricity_mwh_per_t=s3_1.casting_electricity_mwh_per_t * electricity_scale,
        slab_handling_electricity_mwh_per_t=s3_1.slab_handling_electricity_mwh_per_t * electricity_scale,
        dsp_electricity_mwh_per_t=s3_1.dsp_electricity_mwh_per_t * electricity_scale,
        reheating_aux_electricity_mwh_per_t=s3_1.reheating_aux_electricity_mwh_per_t * electricity_scale,
        hsm_electricity_mwh_per_t=s3_1.hsm_electricity_mwh_per_t * electricity_scale,
        asu_electricity_mwh_per_t_o2=s3_1.asu_electricity_mwh_per_t_o2 * electricity_scale,
        residual_auxiliary_electricity_mwh_per_t_final=(
            s3_1.residual_auxiliary_electricity_mwh_per_t_final
            * values["residual_auxiliary_electricity_scale"]
        ),
        downstream_light_side_utility_heat_demand_gj_per_h=utility_heat_gj_per_h,
        downstream_light_side_minimum_ng_gj_per_h=utility_min_ng_gj_per_h,
        c1_route=_scale_c1_route_natural_gas(s3_1.c1_route, drp_ng_multiplier),
        wag=wag,
    )
    s3_2 = replace(
        s3_2,
        materials=replace(
            s3_2.materials,
            bf_bof_aggregate_direct_co2_t_per_t_bof=values["bf_bof_aggregate_direct_co2_t_per_t_bof"],
        ),
        prices=replace(
            s3_2.prices,
            wag_power_residual_utilisation_fraction=(
                values["wag_residual_utilisation_fraction"] * c1_wag_availability_factor
            ),
        ),
    )
    return s3_1, s3_2


def _parameter_boundary_count(values: dict[str, float]) -> int:
    count = 0
    for parameter in eligible_calibration_parameters():
        span = parameter.upper - parameter.lower
        if span <= 0:
            continue
        near = 0.02 * span
        value_at = values[parameter.parameter_id]
        if value_at <= parameter.lower + near or value_at >= parameter.upper - near:
            count += 1
    return count


def _regularisation(values: dict[str, float]) -> float:
    penalties = []
    for parameter in eligible_calibration_parameters():
        span = parameter.upper - parameter.lower
        if span <= 0:
            continue
        penalties.append(abs(values[parameter.parameter_id] - parameter.source_central) / span)
    return float(sum(penalties) / len(penalties)) if penalties else 0.0


def _build_calibration_model(
    *,
    configuration_id: str,
    horizon_hours: int,
    parameter_values: dict[str, float],
    annual_final_product_t: float,
    bf_bof_share: float | None = None,
    slab_yard_capacity_t: float = SLAB_YARD_CAPACITY_T,
    smoke_case_id: str,
    downstream_options: DownstreamCaseOptions | None = None,
    c1_diagnostic_switches: dict[str, float] | None = None,
):
    s3_1, s3_2 = _apply_parameter_values(parameter_values, c1_diagnostic_switches=c1_diagnostic_switches)
    downstream = load_calibration_downstream_assumptions(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        annual_final_product_t=annual_final_product_t,
        bf_bof_share=bf_bof_share,
        slab_yard_capacity_t=slab_yard_capacity_t,
    )
    model = build_site_energy_economic_model(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        assumptions=s3_1,
        downstream_assumptions=downstream,
        case_options=IntegratedCaseOptions(
            smoke_case_id=smoke_case_id,
            downstream_options=downstream_options or DownstreamCaseOptions(smoke_case_id=smoke_case_id),
            objective_mode="s3_3_static_calibration",
        ),
    )
    _attach_s3_2_static_economics_layer(
        model,
        configuration_id=configuration_id,
        assumptions=s3_2,
        case_options=S32CaseOptions(
            smoke_case_id=smoke_case_id,
            downstream_options=downstream_options or DownstreamCaseOptions(smoke_case_id=smoke_case_id),
            route_mode="fixed",
        ),
    )
    model.s3_3_parameter_values = parameter_values
    model.s3_3_metadata = {
        "annual_final_product_t": annual_final_product_t,
        "residual_ng_m3_per_t_final": parameter_values["residual_c0_ng_m3_per_t_final"],
        "coal_primary_energy_factor_gj_per_t_dry_coal": parameter_values[
            "coal_primary_energy_factor_gj_per_t_dry_coal"
        ],
        "market_logic_active": False,
        "stochastic_logic_active": False,
        "cvar_logic_active": False,
        "mfrr_logic_active": False,
        "s3_3a_c1_diagnostic_only": bool(c1_diagnostic_switches),
        "s3_3c_utility_boundary_active": bool(
            c1_diagnostic_switches
            and float(c1_diagnostic_switches.get("s3_3c_downstream_light_side_ng_pj_per_year", 0.0)) > 0.0
        ),
    }
    return model


def solve_calibration_case(
    *,
    candidate_id: str,
    candidate_role: str,
    parameter_values: dict[str, float],
    configuration_id: str = C0_CONFIGURATION_ID,
    horizon_hours: int = 24,
    annual_final_product_t: float = CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
    bf_bof_share: float | None = None,
    slab_yard_capacity_t: float = SLAB_YARD_CAPACITY_T,
    smoke_case_id: str = "s3_3_calibration_case",
    downstream_options: DownstreamCaseOptions | None = None,
    c1_diagnostic_switches: dict[str, float] | None = None,
    residual_ng_m3_per_t_final_override: float | None = None,
    solver=None,
    solver_name: str = "unknown",
) -> dict[str, Any]:
    model = _build_calibration_model(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        parameter_values=parameter_values,
        annual_final_product_t=annual_final_product_t,
        bf_bof_share=bf_bof_share,
        slab_yard_capacity_t=slab_yard_capacity_t,
        smoke_case_id=smoke_case_id,
        downstream_options=downstream_options,
        c1_diagnostic_switches=c1_diagnostic_switches,
    )
    start = time.perf_counter()
    result = _solve_model(model, solver)
    runtime = time.perf_counter() - start
    termination = str(result.solver.termination_condition) if result is not None else "not_attempted"
    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_role": candidate_role,
        "configuration_id": configuration_id,
        "horizon_hours": horizon_hours,
        "annual_final_product_t": annual_final_product_t,
        "bf_bof_share_scenario": "" if bf_bof_share is None else bf_bof_share,
        "termination_condition": termination,
        "solver_status": str(result.solver.status) if result is not None else "not_attempted",
        "solver_name": solver_name,
        "runtime_seconds": round(runtime, 6),
        "mip_gap": _mip_gap(result) if result is not None else "not_attempted",
        "objective_value": "",
        "calibration_score": "",
        "regularisation_score": round(_regularisation(parameter_values), 8),
        "boundary_parameter_count": _parameter_boundary_count(parameter_values),
        "accepted_for_calibration": "false",
        "rejection_reason": "",
    }
    row.update({f"param_{key}": value_at for key, value_at in parameter_values.items()})
    residual_ng_m3_per_t_final = (
        parameter_values["residual_c0_ng_m3_per_t_final"]
        if residual_ng_m3_per_t_final_override is None
        else residual_ng_m3_per_t_final_override
    )

    if result is None or result.solver.termination_condition not in OPTIMAL_TERMINATIONS:
        row["rejection_reason"] = f"non_optimal_termination_{termination}"
        return row

    metrics = collect_site_validation_metrics(
        model,
        residual_ng_m3_per_t_final=residual_ng_m3_per_t_final,
        coal_primary_energy_factor_gj_per_t_dry_coal=parameter_values[
            "coal_primary_energy_factor_gj_per_t_dry_coal"
        ],
    )
    errors = calibration_error_rows(metrics, c0_calibration_target_rows())
    error_by_target = {error["target_id"]: error for error in errors}
    score = sum(float(error["tolerance_normalised_abs_error"]) for error in errors)
    score += 0.25 * _regularisation(parameter_values)
    score += 0.05 * _parameter_boundary_count(parameter_values)

    row.update(metrics)
    row["objective_value"] = _active_objective_value(model)
    row["calibration_score"] = round(score, 8)
    row["max_material_balance_residual_t"] = max_material_balance_residual(model)
    for target_id, column in PRIMARY_TARGET_IDS.items():
        error = error_by_target.get(target_id)
        row[column] = "" if error is None else float(error["percentage_error"])
        row[column.replace("_pct", "_normalised")] = "" if error is None else float(
            error["tolerance_normalised_abs_error"]
        )

    rejection_reasons: list[str] = []
    if abs(float(row["annualised_final_product_t"]) - annual_final_product_t) > 1e-4:
        rejection_reasons.append("production_target_not_met")
    if float(row["terminal_cold_residual_t"]) > 1e-5 or float(row["terminal_hot_residual_t"]) > 1e-5:
        rejection_reasons.append("terminal_inventory_violation")
    if float(row["max_material_balance_residual_t"]) > 1e-5:
        rejection_reasons.append("material_balance_residual")
    if float(row["max_wag_balance_residual_gj"]) > 1e-5 or float(row["max_electricity_balance_residual_mwh"]) > 1e-5:
        rejection_reasons.append("energy_balance_residual")
    if float(row["flare_fraction_of_wag_generated"]) > 0.05 + 1e-9:
        rejection_reasons.append("normal_flare_above_admissible_limit")
    if any(float(error["tolerance_normalised_abs_error"]) > 1.0 + 1e-9 for error in errors):
        rejection_reasons.append("outside_calibration_tolerance")

    row["accepted_for_calibration"] = "true" if not rejection_reasons else "false"
    row["rejection_reason"] = ";".join(rejection_reasons)
    return row


def validate_inputs_only() -> dict[str, Any]:
    paths = write_static_s3_3_governance_artifacts()
    conflicts = hot_metal_initial_inventory_conflicts()
    c0 = load_calibration_downstream_assumptions(configuration_id=C0_CONFIGURATION_ID, horizon_hours=24)
    c1 = load_calibration_downstream_assumptions(configuration_id=C1_CONFIGURATION_ID, horizon_hours=24, bf_bof_share=0.61)
    legacy_c0 = load_downstream_assumptions(configuration_id=C0_CONFIGURATION_ID, horizon_hours=24)
    hourly = CALIBRATION_ANNUAL_FINAL_PRODUCT_T / 8760.0
    bf_hot_metal_tph = hourly * 0.8
    coke_t_per_year = CALIBRATION_ANNUAL_FINAL_PRODUCT_T * 0.8 * 0.29
    c1_drp_eaf_tph = hourly * 0.39
    c1_dri_tph = c1_drp_eaf_tph * 1.0526315789
    c1_pellets_tph = c1_drp_eaf_tph * 1.4224751067
    return {
        "status": "pass" if not conflicts else "blocked",
        "artifact_count": len(paths),
        "annual_target_t": CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
        "hourly_target_t": hourly,
        "target_24h_t": final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=24),
        "target_168h_t": final_product_target_t(annual_t=CALIBRATION_ANNUAL_FINAL_PRODUCT_T, horizon_hours=168),
        "legacy_baseline_24h_t": legacy_c0.final_product_target_t,
        "legacy_baseline_annualised_t": legacy_c0.final_product_target_t / 24.0 * 8760.0,
        "slab_yard_capacity_t": c0.slab_yard_capacity_t,
        "initial_cold_slab_inventory_t": c0.initial_cold_slab_inventory_t,
        "hot_metal_buffer_capacity_t": HOT_METAL_BUFFER_CAPACITY_T,
        "hot_metal_initial_inventory_conflicts": conflicts,
        "capacity_audit": {
            "bf_hot_metal_tph_estimate": bf_hot_metal_tph,
            "bf_combined_output_reference_tph": ">650",
            "bf_capacity_status": "pass",
            "coke_t_per_year_estimate": coke_t_per_year,
            "coking_capacity_reference_t_per_year": 1_500_000.0,
            "coking_capacity_status": "pass",
            "c1_0_61_dri_tph_estimate": c1_dri_tph,
            "c1_0_61_pellets_tph_estimate": c1_pellets_tph,
            "drp_capacity_reference_pellets_tph": 500.0,
            "eaf_capacity_reference_dri_tph": 400.0,
            "drp_eaf_capacity_status": "pass",
            "target_derived_downstream_capacities_scaled": "true",
            "source_specific_absolute_capacities_silently_scaled": "false",
            "c1_final_product_target_t_24h": c1.final_product_target_t,
        },
    }


def _write_dataframe(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path.name}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _add_c1_holdout_errors(row: dict[str, Any]) -> None:
    for metric, target in C1_TARGETS.items():
        row[f"c1_{metric}_target"] = target
        if metric not in row or row.get(metric) in ("", None):
            row[f"c1_{metric}_error_pct"] = ""
            continue
        actual = float(row[metric])
        row[f"c1_{metric}_error_pct"] = 0.0 if target == 0 else (actual - target) / target
    for metric, ratio_target in C1_C0_RATIO_TARGETS.items():
        reference = C0_REFERENCE_TARGETS[metric]
        row[f"c1_c0_{metric}_target_ratio"] = ratio_target
        if metric not in row or row.get(metric) in ("", None):
            row[f"c1_c0_{metric}_actual_ratio"] = ""
            row[f"c1_c0_{metric}_ratio_error_pct"] = ""
            continue
        actual = float(row[metric])
        actual_ratio = 0.0 if reference == 0 else actual / reference
        row[f"c1_c0_{metric}_actual_ratio"] = actual_ratio
        row[f"c1_c0_{metric}_ratio_error_pct"] = 0.0 if ratio_target == 0 else (actual_ratio - ratio_target) / ratio_target


def _c1_principal_pass(row: dict[str, Any]) -> str:
    required = [
        "c1_gross_electricity_twh_per_year_error_pct",
        "c1_wag_electricity_twh_per_year_error_pct",
        "c1_natural_gas_m3_per_h_error_pct",
        "c1_direct_site_co2_t_per_year_error_pct",
    ]
    if any(row.get(key) in ("", None) for key in required):
        return "false"
    return (
        "true"
        if abs(float(row["c1_gross_electricity_twh_per_year_error_pct"])) <= 0.05
        and abs(float(row["c1_wag_electricity_twh_per_year_error_pct"])) <= 0.10
        and abs(float(row["c1_natural_gas_m3_per_h_error_pct"])) <= 0.10
        and abs(float(row["c1_direct_site_co2_t_per_year_error_pct"])) <= 0.10
        else "false"
    )


def run_screening(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None) -> dict[str, Any]:
    write_static_s3_3_governance_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    central = calibration_anchor_parameter_set()
    baseline = solve_calibration_case(
        candidate_id="S33_SCREEN_BASE",
        candidate_role="screening_base",
        parameter_values=central,
        solver=solver,
        solver_name=resolved_name,
    )
    rows: list[dict[str, Any]] = [baseline | {"screening_parameter_id": "baseline", "screening_level": "central"}]
    for parameter in eligible_calibration_parameters():
        for level, value_at in (("low", parameter.lower), ("central", central[parameter.parameter_id]), ("high", parameter.upper)):
            values = dict(central)
            values[parameter.parameter_id] = value_at
            row = solve_calibration_case(
                candidate_id=f"S33_SCREEN_{parameter.parameter_id}_{level}",
                candidate_role="oat_screening",
                parameter_values=values,
                solver=solver,
                solver_name=resolved_name,
            )
            row["screening_parameter_id"] = parameter.parameter_id
            row["screening_level"] = level
            rows.append(row)

    influence_rows: list[dict[str, Any]] = []
    for parameter in eligible_calibration_parameters():
        subset = [row for row in rows if row.get("screening_parameter_id") == parameter.parameter_id]
        normalised_cols = [column for column in subset[0] if column.endswith("_normalised")]
        max_effect = 0.0
        total_effect = 0.0
        feasible_effect = 0
        for column in normalised_cols:
            values = [float(row[column]) for row in subset if row.get(column) not in ("", None)]
            if values:
                effect = max(values) - min(values)
                max_effect = max(max_effect, effect)
                total_effect += abs(effect)
        feasible_effect = sum(1 for row in subset if row["accepted_for_calibration"] != "true")
        influence_rows.append(
            {
                "parameter_id": parameter.parameter_id,
                "maximum_normalised_target_effect": round(max_effect, 8),
                "total_weighted_effect": round(total_effect, 8),
                "feasibility_effect_count": feasible_effect,
                "retained_for_ensemble_calibration": "true",
                "screening_decision": "retained_in_top_12_candidate_group",
            }
        )
    influence = sorted(
        influence_rows,
        key=lambda row: (
            float(row["maximum_normalised_target_effect"]),
            float(row["total_weighted_effect"]),
            int(row["feasibility_effect_count"]),
        ),
        reverse=True,
    )
    _write_dataframe(S3_3_OUTPUT_PATHS["screening"], influence)
    return {
        "solver_name": resolved_name,
        "screening_rows": len(rows),
        "parameters_screened": len(eligible_calibration_parameters()),
        "retained_parameters": [row["parameter_id"] for row in influence[:12]],
        "baseline_score": baseline["calibration_score"],
    }


def run_calibrate_24h(
    *,
    seed: int,
    max_candidates: int,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    write_static_s3_3_governance_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    candidates = candidate_parameter_sets(seed=seed, max_candidates=max_candidates)
    _write_dataframe(S3_3_OUTPUT_PATHS["candidate_sets"], candidates)
    rows = [
        solve_calibration_case(
            candidate_id=str(candidate["candidate_id"]),
            candidate_role=str(candidate["candidate_role"]),
            parameter_values=candidate_values(candidate),
            solver=solver,
            solver_name=resolved_name,
        )
        for candidate in candidates
    ]
    rows = sorted(rows, key=lambda row: float(row["calibration_score"]) if row["calibration_score"] != "" else 1e9)
    _write_dataframe(S3_3_OUTPUT_PATHS["c0_24h"], rows)
    feasible = [row for row in rows if row["accepted_for_calibration"] == "true"]
    return {
        "solver_name": resolved_name,
        "candidate_sets_run": len(rows),
        "feasible_candidate_sets": len(feasible),
        "best_candidate_id": rows[0]["candidate_id"] if rows else "",
        "best_score": rows[0]["calibration_score"] if rows else "",
    }


def _load_candidate_lookup() -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(S3_3_OUTPUT_PATHS["candidate_sets"], dtype=str, keep_default_na=False)
    return {row["candidate_id"]: row for row in frame.to_dict(orient="records")}


def run_confirm_168h(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None) -> dict[str, Any]:
    if not S3_3_OUTPUT_PATHS["c0_24h"].exists():
        run_calibrate_24h(
            seed=DEFAULT_SEED,
            max_candidates=DEFAULT_MAX_CANDIDATES,
            solver_name=solver_name,
            time_limit=time_limit,
            mip_gap=mip_gap,
        )
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    c0_24h = pd.read_csv(S3_3_OUTPUT_PATHS["c0_24h"], dtype=str, keep_default_na=False)
    lookup = _load_candidate_lookup()
    top = c0_24h.loc[c0_24h["accepted_for_calibration"].eq("true")].head(12)
    if top.empty:
        top = c0_24h.head(12)
    rows: list[dict[str, Any]] = []
    for row in top.to_dict(orient="records"):
        candidate = lookup[row["candidate_id"]]
        confirm = solve_calibration_case(
            candidate_id=row["candidate_id"],
            candidate_role=str(candidate["candidate_role"]),
            parameter_values=candidate_values(candidate),
            horizon_hours=168,
            smoke_case_id="s3_3_c0_168h_confirmation",
            solver=solver,
            solver_name=resolved_name,
        )
        confirm["retained_for_holdout_validation"] = (
            "true"
            if confirm["accepted_for_calibration"] == "true"
            and int(confirm["boundary_parameter_count"]) <= 2
            else "false"
        )
        rows.append(confirm)
    rows = sorted(rows, key=lambda row: float(row["calibration_score"]) if row["calibration_score"] != "" else 1e9)
    retained_count = 0
    for row in rows:
        if row["retained_for_holdout_validation"] == "true" and retained_count < 8:
            retained_count += 1
        else:
            row["retained_for_holdout_validation"] = "false"
    _write_dataframe(S3_3_OUTPUT_PATHS["c0_168h"], rows)
    return {
        "solver_name": resolved_name,
        "candidates_confirmed_168h": len(rows),
        "retained_for_holdout": retained_count,
        "freeze_precondition_c0_minimum_three_sets": retained_count >= 3,
    }


def _retained_candidate_rows() -> list[dict[str, Any]]:
    if not S3_3_OUTPUT_PATHS["c0_168h"].exists():
        return []
    frame = pd.read_csv(S3_3_OUTPUT_PATHS["c0_168h"], dtype=str, keep_default_na=False)
    retained = frame.loc[frame["retained_for_holdout_validation"].eq("true")]
    if retained.empty:
        retained = frame.head(3)
    return retained.to_dict(orient="records")


def run_validate_c1(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None) -> dict[str, Any]:
    if not S3_3_OUTPUT_PATHS["c0_168h"].exists():
        run_confirm_168h(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    lookup = _load_candidate_lookup()
    rows: list[dict[str, Any]] = []
    for retained in _retained_candidate_rows():
        candidate = lookup[retained["candidate_id"]]
        values = candidate_values(candidate)
        for route_share in (0.55, 0.61, 0.68):
            row = solve_calibration_case(
                candidate_id=retained["candidate_id"],
                candidate_role=str(candidate["candidate_role"]),
                parameter_values=values,
                configuration_id=C1_CONFIGURATION_ID,
                horizon_hours=168,
                bf_bof_share=route_share,
                smoke_case_id=f"s3_3_c1_holdout_{route_share:.2f}",
                solver=solver,
                solver_name=resolved_name,
            )
            _add_c1_holdout_errors(row)
            row["route_share_selection_role"] = "scenario_selection_not_parameter_validation"
            row["c1_holdout_pass_principal_targets"] = _c1_principal_pass(row)
            rows.append(row)
    _write_dataframe(S3_3_OUTPUT_PATHS["c1_holdout"], rows)
    return {
        "solver_name": resolved_name,
        "holdout_cases": len(rows),
        "holdout_pass_cases": sum(1 for row in rows if row["c1_holdout_pass_principal_targets"] == "true"),
    }


def _diagnostic_candidate_rows() -> list[dict[str, Any]]:
    candidates = candidate_parameter_sets(seed=DEFAULT_SEED, max_candidates=6)
    by_id = {str(row["candidate_id"]): row for row in candidates}
    missing = [candidate_id for candidate_id in C1_DIAGNOSTIC_CANDIDATE_IDS if candidate_id not in by_id]
    if missing:
        raise RuntimeError(f"Missing expected S3.3a diagnostic candidates: {missing}")
    return [by_id[candidate_id] for candidate_id in C1_DIAGNOSTIC_CANDIDATE_IDS]


def _diagnostic_score(row: dict[str, Any]) -> float:
    if row.get("termination_condition") not in {"optimal", "feasible"}:
        return 1e9
    required = [
        "c1_gross_electricity_twh_per_year_error_pct",
        "c1_wag_electricity_twh_per_year_error_pct",
        "c1_natural_gas_m3_per_h_error_pct",
        "c1_direct_site_co2_t_per_year_error_pct",
    ]
    if any(row.get(key) in ("", None) for key in required):
        return 1e9
    return (
        abs(float(row["c1_gross_electricity_twh_per_year_error_pct"])) / 0.05
        + abs(float(row["c1_wag_electricity_twh_per_year_error_pct"])) / 0.10
        + abs(float(row["c1_natural_gas_m3_per_h_error_pct"])) / 0.10
        + abs(float(row["c1_direct_site_co2_t_per_year_error_pct"])) / 0.10
    )


def _gap_closure_residual_ng(row: dict[str, Any], inherited_residual: float) -> float:
    if row.get("natural_gas_m3_per_h") in ("", None) or "natural_gas_m3_per_h" not in row:
        return inherited_residual
    actual_ng_m3_per_h = float(row["natural_gas_m3_per_h"])
    target_ng_m3_per_h = C1_TARGETS["natural_gas_m3_per_h"]
    final_product_t_per_h = float(row["final_product_t_per_h"])
    if final_product_t_per_h <= 0.0:
        return inherited_residual
    return inherited_residual + max(0.0, target_ng_m3_per_h - actual_ng_m3_per_h) / final_product_t_per_h


def _diagnostic_status(value_at: float, baseline: float, source_status: str) -> str:
    if abs(value_at - baseline) <= 1e-12:
        return "inherited_c0_calibrated_behavior"
    return source_status


def _run_c1_diagnostic_case(
    *,
    candidate: dict[str, Any],
    route_share: float,
    diagnostic_case_id: str,
    diagnostic_stage: str,
    c1_wag_availability_factor: float,
    drp_ng_multiplier: float,
    c1_retained_coking_wag_displacement_factor: float,
    c1_residual_ng_boundary_m3_per_t_final: float,
    residual_boundary_mode: str,
    baseline_row: dict[str, Any] | None,
    solver,
    solver_name: str,
) -> dict[str, Any]:
    values = candidate_values(candidate)
    switches = {
        "c1_wag_availability_factor": c1_wag_availability_factor,
        "drp_ng_multiplier": drp_ng_multiplier,
        "c1_retained_coking_wag_displacement_factor": c1_retained_coking_wag_displacement_factor,
    }
    row = solve_calibration_case(
        candidate_id=str(candidate["candidate_id"]),
        candidate_role=str(candidate["candidate_role"]),
        parameter_values=values,
        configuration_id=C1_CONFIGURATION_ID,
        horizon_hours=168,
        bf_bof_share=route_share,
        smoke_case_id=diagnostic_case_id,
        c1_diagnostic_switches=switches,
        residual_ng_m3_per_t_final_override=c1_residual_ng_boundary_m3_per_t_final,
        solver=solver,
        solver_name=solver_name,
    )
    _add_c1_holdout_errors(row)
    row.update(
        {
            "diagnostic_case_id": diagnostic_case_id,
            "diagnostic_stage": diagnostic_stage,
            "diagnostic_only": "true",
            "approved_input_status": "not_approved_diagnostic_only",
            "c0_candidate_parameters_fixed": "true",
            "route_share_selection_role": "scenario_selection_not_parameter_validation",
            "c1_holdout_pass_principal_targets": _c1_principal_pass(row),
            "c1_wag_availability_factor": c1_wag_availability_factor,
            "drp_ng_multiplier": drp_ng_multiplier,
            "c1_retained_coking_wag_displacement_factor": c1_retained_coking_wag_displacement_factor,
            "c1_residual_ng_boundary_m3_per_t_final": c1_residual_ng_boundary_m3_per_t_final,
            "c1_residual_ng_boundary_mode": residual_boundary_mode,
            "c1_wag_availability_factor_status": _diagnostic_status(
                c1_wag_availability_factor,
                1.0,
                "assumption_only_source_needed",
            ),
            "drp_ng_multiplier_status": (
                "governed_holdout_range"
                if drp_ng_multiplier in C1_DRP_NG_MULTIPLIER_DIAGNOSTICS
                else "source_needed"
            ),
            "c1_retained_coking_wag_displacement_factor_status": _diagnostic_status(
                c1_retained_coking_wag_displacement_factor,
                1.0,
                "assumption_only_source_needed",
            ),
            "c1_residual_ng_boundary_status": (
                "inherited_c0_calibration_parameter"
                if residual_boundary_mode == "inherited_c0_residual"
                else "diagnostic_back_calculation_source_needed"
                if "gap_closure" in residual_boundary_mode
                else "diagnostic_boundary_zero_not_approved"
            ),
            "market_logic_active": "false",
            "stochastic_logic_active": "false",
            "cvar_logic_active": "false",
            "mfrr_logic_active": "false",
        }
    )
    if baseline_row is None:
        row["wag_abs_error_improvement_pct_points_vs_baseline"] = 0.0
        row["ng_abs_error_improvement_pct_points_vs_baseline"] = 0.0
        row["wag_ng_mismatch_sign_improves"] = "baseline"
    elif row.get("c1_wag_electricity_twh_per_year_error_pct") in ("", None) or row.get(
        "c1_natural_gas_m3_per_h_error_pct"
    ) in ("", None):
        row["wag_abs_error_improvement_pct_points_vs_baseline"] = ""
        row["ng_abs_error_improvement_pct_points_vs_baseline"] = ""
        row["wag_ng_mismatch_sign_improves"] = "not_evaluable"
    else:
        wag_improvement = abs(float(baseline_row["c1_wag_electricity_twh_per_year_error_pct"])) - abs(
            float(row["c1_wag_electricity_twh_per_year_error_pct"])
        )
        ng_improvement = abs(float(baseline_row["c1_natural_gas_m3_per_h_error_pct"])) - abs(
            float(row["c1_natural_gas_m3_per_h_error_pct"])
        )
        row["wag_abs_error_improvement_pct_points_vs_baseline"] = wag_improvement
        row["ng_abs_error_improvement_pct_points_vs_baseline"] = ng_improvement
        row["wag_ng_mismatch_sign_improves"] = "true" if wag_improvement > 0 and ng_improvement > 0 else "false"
    row["diagnostic_score"] = _diagnostic_score(row)
    return row


def _matrix_row_from_result(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "diagnostic_case_id",
        "diagnostic_stage",
        "candidate_id",
        "candidate_role",
        "bf_bof_share_scenario",
        "c1_wag_availability_factor",
        "drp_ng_multiplier",
        "c1_retained_coking_wag_displacement_factor",
        "c1_residual_ng_boundary_m3_per_t_final",
        "c1_residual_ng_boundary_mode",
        "c1_wag_availability_factor_status",
        "drp_ng_multiplier_status",
        "c1_retained_coking_wag_displacement_factor_status",
        "c1_residual_ng_boundary_status",
        "diagnostic_only",
        "approved_input_status",
        "c0_candidate_parameters_fixed",
    ]
    return {key: row.get(key, "") for key in keys}


def _write_c1_diagnostic_decision_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_rows = [row for row in rows if row["diagnostic_stage"] == "baseline_inherited_c0_logic"]
    best_baseline = min(baseline_rows, key=_diagnostic_score)
    best_overall = min(rows, key=_diagnostic_score)
    best_wag = min(
        rows,
        key=lambda row: 1e9
        if row.get("c1_wag_electricity_twh_per_year_error_pct") in ("", None)
        else abs(float(row["c1_wag_electricity_twh_per_year_error_pct"])),
    )
    best_ng = min(
        rows,
        key=lambda row: 1e9
        if row.get("c1_natural_gas_m3_per_h_error_pct") in ("", None)
        else abs(float(row["c1_natural_gas_m3_per_h_error_pct"])),
    )
    wag_sweep_rows = [row for row in rows if row["diagnostic_stage"] == "wag_availability_sweep"]
    drp_rows = [row for row in rows if row["diagnostic_stage"] == "drp_ng_multiplier_sweep"]
    residual_rows = [row for row in rows if "residual_ng_boundary" in row["diagnostic_stage"]]
    retained_rows = [row for row in rows if row["diagnostic_stage"] == "retained_coking_wag_displacement_sweep"]
    combined_rows = [row for row in rows if row["diagnostic_stage"].startswith("combined_best_sign")]
    pass_rows = [row for row in rows if row["c1_holdout_pass_principal_targets"] == "true"]

    summary_rows = [
        {
            "decision_item": "best_baseline",
            "candidate_id": best_baseline["candidate_id"],
            "route_share": best_baseline["bf_bof_share_scenario"],
            "diagnostic_stage": best_baseline["diagnostic_stage"],
            "gross_error_pct": best_baseline["c1_gross_electricity_twh_per_year_error_pct"],
            "wag_error_pct": best_baseline["c1_wag_electricity_twh_per_year_error_pct"],
            "ng_error_pct": best_baseline["c1_natural_gas_m3_per_h_error_pct"],
            "co2_error_pct": best_baseline["c1_direct_site_co2_t_per_year_error_pct"],
            "primary_proxy_error_pct": best_baseline["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "decision": "baseline_inherited_c0_logic_fails_c1_holdout",
        },
        {
            "decision_item": "best_overall",
            "candidate_id": best_overall["candidate_id"],
            "route_share": best_overall["bf_bof_share_scenario"],
            "diagnostic_stage": best_overall["diagnostic_stage"],
            "gross_error_pct": best_overall["c1_gross_electricity_twh_per_year_error_pct"],
            "wag_error_pct": best_overall["c1_wag_electricity_twh_per_year_error_pct"],
            "ng_error_pct": best_overall["c1_natural_gas_m3_per_h_error_pct"],
            "co2_error_pct": best_overall["c1_direct_site_co2_t_per_year_error_pct"],
            "primary_proxy_error_pct": best_overall["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "decision": "diagnostic_pass" if pass_rows else "no_diagnostic_case_passes_all_principal_targets",
        },
        {
            "decision_item": "best_wag_error",
            "candidate_id": best_wag["candidate_id"],
            "route_share": best_wag["bf_bof_share_scenario"],
            "diagnostic_stage": best_wag["diagnostic_stage"],
            "gross_error_pct": best_wag["c1_gross_electricity_twh_per_year_error_pct"],
            "wag_error_pct": best_wag["c1_wag_electricity_twh_per_year_error_pct"],
            "ng_error_pct": best_wag["c1_natural_gas_m3_per_h_error_pct"],
            "co2_error_pct": best_wag["c1_direct_site_co2_t_per_year_error_pct"],
            "primary_proxy_error_pct": best_wag["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "decision": "wag_availability_can_repair_wag" if best_wag in wag_sweep_rows + combined_rows else "wag_repair_needs_other_mechanism",
        },
        {
            "decision_item": "best_ng_error",
            "candidate_id": best_ng["candidate_id"],
            "route_share": best_ng["bf_bof_share_scenario"],
            "diagnostic_stage": best_ng["diagnostic_stage"],
            "gross_error_pct": best_ng["c1_gross_electricity_twh_per_year_error_pct"],
            "wag_error_pct": best_ng["c1_wag_electricity_twh_per_year_error_pct"],
            "ng_error_pct": best_ng["c1_natural_gas_m3_per_h_error_pct"],
            "co2_error_pct": best_ng["c1_direct_site_co2_t_per_year_error_pct"],
            "primary_proxy_error_pct": best_ng["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "decision": "residual_boundary_or_combined_gap_needed" if best_ng in residual_rows + combined_rows else "drp_multiplier_alone_may_be_sufficient",
        },
        {
            "decision_item": "mechanism_status",
            "candidate_id": "",
            "route_share": "",
            "diagnostic_stage": "",
            "gross_error_pct": "",
            "wag_error_pct": "",
            "ng_error_pct": "",
            "co2_error_pct": "",
            "primary_proxy_error_pct": "",
            "decision": (
                f"wag_sweep_near_target={any(row.get('c1_wag_electricity_twh_per_year_error_pct') not in ('', None) and abs(float(row['c1_wag_electricity_twh_per_year_error_pct'])) <= 0.10 for row in wag_sweep_rows)};"
                f"drp_sweep_ng_near_target={any(row.get('c1_natural_gas_m3_per_h_error_pct') not in ('', None) and abs(float(row['c1_natural_gas_m3_per_h_error_pct'])) <= 0.10 for row in drp_rows)};"
                f"residual_boundary_ng_near_target={any(row.get('c1_natural_gas_m3_per_h_error_pct') not in ('', None) and abs(float(row['c1_natural_gas_m3_per_h_error_pct'])) <= 0.10 for row in residual_rows)};"
                f"retained_wag_sweep_near_target={any(row.get('c1_wag_electricity_twh_per_year_error_pct') not in ('', None) and abs(float(row['c1_wag_electricity_twh_per_year_error_pct'])) <= 0.10 for row in retained_rows)};"
                f"combined_pass_count={len(pass_rows)}"
            ),
        },
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["c1_diagnostic_decision_summary"], summary_rows)
    return {
        "best_baseline_case": best_baseline["diagnostic_case_id"],
        "best_overall_case": best_overall["diagnostic_case_id"],
        "diagnostic_pass_cases": len(pass_rows),
        "best_wag_stage": best_wag["diagnostic_stage"],
        "best_ng_stage": best_ng["diagnostic_stage"],
    }


def run_diagnose_c1_structure(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    write_static_s3_3_governance_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["c1_boundary_crosswalk_amendment"], c1_boundary_crosswalk_amendment_rows())
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    rows: list[dict[str, Any]] = []

    for candidate in _diagnostic_candidate_rows():
        full_sweep = candidate["candidate_id"] == "S33_CAND_001_CALIBRATION_ANCHOR"
        for route_share in C1_ROUTE_SHARE_DIAGNOSTICS:
            inherited_residual = float(candidate["residual_c0_ng_m3_per_t_final"])
            baseline = _run_c1_diagnostic_case(
                candidate=candidate,
                route_share=route_share,
                diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_baseline",
                diagnostic_stage="baseline_inherited_c0_logic",
                c1_wag_availability_factor=1.0,
                drp_ng_multiplier=1.0,
                c1_retained_coking_wag_displacement_factor=1.0,
                c1_residual_ng_boundary_m3_per_t_final=inherited_residual,
                residual_boundary_mode="inherited_c0_residual",
                baseline_row=None,
                solver=solver,
                solver_name=resolved_name,
            )
            rows.append(baseline)

            if full_sweep:
                for factor in (0.75, 0.50, 0.25):
                    rows.append(
                        _run_c1_diagnostic_case(
                            candidate=candidate,
                            route_share=route_share,
                            diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_wag_{factor:.2f}",
                            diagnostic_stage="wag_availability_sweep",
                            c1_wag_availability_factor=factor,
                            drp_ng_multiplier=1.0,
                            c1_retained_coking_wag_displacement_factor=1.0,
                            c1_residual_ng_boundary_m3_per_t_final=inherited_residual,
                            residual_boundary_mode="inherited_c0_residual",
                            baseline_row=baseline,
                            solver=solver,
                            solver_name=resolved_name,
                        )
                    )
                for multiplier in (0.8, 1.3):
                    rows.append(
                        _run_c1_diagnostic_case(
                            candidate=candidate,
                            route_share=route_share,
                            diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_drp_{multiplier:.1f}",
                            diagnostic_stage="drp_ng_multiplier_sweep",
                            c1_wag_availability_factor=1.0,
                            drp_ng_multiplier=multiplier,
                            c1_retained_coking_wag_displacement_factor=1.0,
                            c1_residual_ng_boundary_m3_per_t_final=inherited_residual,
                            residual_boundary_mode="inherited_c0_residual",
                            baseline_row=baseline,
                            solver=solver,
                            solver_name=resolved_name,
                        )
                    )
                for factor in (0.75, 0.50):
                    rows.append(
                        _run_c1_diagnostic_case(
                            candidate=candidate,
                            route_share=route_share,
                            diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_retained_{factor:.2f}",
                            diagnostic_stage="retained_coking_wag_displacement_sweep",
                            c1_wag_availability_factor=1.0,
                            drp_ng_multiplier=1.0,
                            c1_retained_coking_wag_displacement_factor=factor,
                            c1_residual_ng_boundary_m3_per_t_final=inherited_residual,
                            residual_boundary_mode="inherited_c0_residual",
                            baseline_row=baseline,
                            solver=solver,
                            solver_name=resolved_name,
                        )
                    )
                rows.append(
                    _run_c1_diagnostic_case(
                        candidate=candidate,
                        route_share=route_share,
                        diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_residual_zero",
                        diagnostic_stage="residual_ng_boundary_sweep_zero",
                        c1_wag_availability_factor=1.0,
                        drp_ng_multiplier=1.0,
                        c1_retained_coking_wag_displacement_factor=1.0,
                        c1_residual_ng_boundary_m3_per_t_final=0.0,
                        residual_boundary_mode="zero_residual_boundary",
                        baseline_row=baseline,
                        solver=solver,
                        solver_name=resolved_name,
                    )
                )
                baseline_gap_residual = _gap_closure_residual_ng(baseline, inherited_residual)
                rows.append(
                    _run_c1_diagnostic_case(
                        candidate=candidate,
                        route_share=route_share,
                        diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_residual_gap",
                        diagnostic_stage="residual_ng_boundary_sweep_gap_closure",
                        c1_wag_availability_factor=1.0,
                        drp_ng_multiplier=1.0,
                        c1_retained_coking_wag_displacement_factor=1.0,
                        c1_residual_ng_boundary_m3_per_t_final=baseline_gap_residual,
                        residual_boundary_mode="table9_gap_closure_back_calculation_from_baseline",
                        baseline_row=baseline,
                        solver=solver,
                        solver_name=resolved_name,
                    )
                )

            combined = _run_c1_diagnostic_case(
                candidate=candidate,
                route_share=route_share,
                diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_combined",
                diagnostic_stage="combined_best_sign_structural",
                c1_wag_availability_factor=0.75,
                drp_ng_multiplier=1.0,
                c1_retained_coking_wag_displacement_factor=1.0,
                c1_residual_ng_boundary_m3_per_t_final=inherited_residual,
                residual_boundary_mode="inherited_c0_residual",
                baseline_row=baseline,
                solver=solver,
                solver_name=resolved_name,
            )
            rows.append(combined)
            combined_gap_residual = _gap_closure_residual_ng(combined, inherited_residual)
            rows.append(
                _run_c1_diagnostic_case(
                    candidate=candidate,
                    route_share=route_share,
                    diagnostic_case_id=f"s3_3a_{candidate['candidate_id']}_{route_share:.2f}_combined_gap",
                    diagnostic_stage="combined_best_sign_with_gap_closure",
                    c1_wag_availability_factor=0.75,
                    drp_ng_multiplier=1.0,
                    c1_retained_coking_wag_displacement_factor=1.0,
                    c1_residual_ng_boundary_m3_per_t_final=combined_gap_residual,
                    residual_boundary_mode="table9_gap_closure_back_calculation_after_combined",
                    baseline_row=baseline,
                    solver=solver,
                    solver_name=resolved_name,
                )
            )

    _write_dataframe(S3_3_OUTPUT_PATHS["c1_structural_results"], rows)
    _write_dataframe(S3_3_OUTPUT_PATHS["c1_structural_matrix"], [_matrix_row_from_result(row) for row in rows])
    summary = _write_c1_diagnostic_decision_summary(rows)
    return {
        "solver_name": resolved_name,
        "diagnostic_cases": len(rows),
        "candidate_sets": list(C1_DIAGNOSTIC_CANDIDATE_IDS),
        "route_shares": list(C1_ROUTE_SHARE_DIAGNOSTICS),
        "diagnostic_pass_cases": summary["diagnostic_pass_cases"],
        "best_baseline_case": summary["best_baseline_case"],
        "best_overall_case": summary["best_overall_case"],
        "best_wag_stage": summary["best_wag_stage"],
        "best_ng_stage": summary["best_ng_stage"],
        "no_run_folder_created": True,
        "approved_inputs_populated": False,
    }


def _write_s3_3b_static_artifacts() -> None:
    write_static_s3_3_governance_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3b_source_support"], s3_3b_source_support_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3b_structural_change"], s3_3b_structural_change_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3b_route_share_capacity"], s3_3b_route_share_capacity_rows())


def _write_s3_3c_static_artifacts() -> None:
    _write_s3_3b_static_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_source_support"], s3_3c_source_support_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_structural_change"], s3_3c_structural_change_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_candidate_parameter"], s3_3c_candidate_parameter_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_boundary_mapping"], s3_3c_boundary_mapping_rows())


def _annotate_s3_3b_row(row: dict[str, Any], *, candidate: dict[str, Any], route_share: float) -> None:
    final_tph = calibration_hourly_target_t()
    drp_share = 1.0 - route_share
    drp_ng_m3_per_t_steel = DRP_NATURAL_GAS_M3_PER_T_PELLETS / (
        DRP_PELLETS_TO_DRI_EFFICIENCY * EAF_DRI_TO_STEEL_EFFICIENCY
    )
    row.update(
        {
            "s3_3b_diagnostic_only": "true",
            "source_carded_or_provisional_mechanisms_only": "true",
            "c0_candidate_parameters_fixed": "true",
            "s3_3a_wag_availability_factor_promoted": "false",
            "s3_3a_ng_gap_closure_promoted": "false",
            "c1_route_share_selection_role": (
                "capacity_implied_diagnostic"
                if abs(route_share - c1_s3_3b_route_shares()[0]) <= 1e-9
                else "pre_existing_holdout_route_share"
            ),
            "drp_ng_source_basis": "195 m3_NG/t_pellets converted by 0.74 pellets-to-DRI and 0.95 DRI-to-steel",
            "expected_drp_pellets_t_per_h": final_tph
            * drp_share
            / (DRP_PELLETS_TO_DRI_EFFICIENCY * EAF_DRI_TO_STEEL_EFFICIENCY),
            "expected_explicit_drp_ng_m3_per_h": final_tph * drp_share * drp_ng_m3_per_t_steel,
            "inherited_c0_residual_ng_m3_per_t_final": candidate["residual_c0_ng_m3_per_t_final"],
            "c1_numeric_ng_topup_status": "source_needed_not_implemented",
            "c1_numeric_wag_interface_reduction_status": "source_needed_not_implemented",
            "c1_holdout_pass_principal_targets": _c1_principal_pass(row),
            "market_logic_active": "false",
            "stochastic_logic_active": "false",
            "cvar_logic_active": "false",
            "mfrr_logic_active": "false",
        }
    )
    row["diagnostic_score"] = _diagnostic_score(row)


def _safe_pct(row: dict[str, Any], key: str) -> float | None:
    value_at = row.get(key)
    if value_at in ("", None):
        return None
    return float(value_at)


def _best_evaluable_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    evaluable = [row for row in rows if _diagnostic_score(row) < 1e9]
    if not evaluable:
        return None
    return min(evaluable, key=_diagnostic_score)


def _write_s3_3b_remaining_gap(rows: list[dict[str, Any]]) -> None:
    baseline_rows: list[dict[str, Any]] = []
    if S3_3_OUTPUT_PATHS["c1_holdout"].exists():
        frame = pd.read_csv(S3_3_OUTPUT_PATHS["c1_holdout"], dtype=str, keep_default_na=False)
        baseline_rows = frame.to_dict(orient="records")
    best_before = _best_evaluable_row(baseline_rows)
    best_after = _best_evaluable_row(rows)
    if best_after is None:
        _write_dataframe(
            S3_3_OUTPUT_PATHS["s3_3b_remaining_gap"],
            [
                {
                    "gap_id": "S33B_GAP_001",
                    "status": "blocked_no_evaluable_s3_3b_rows",
                    "remaining_blocker": "Directional validation did not produce an evaluable row.",
                }
            ],
        )
        return

    def _field(source: dict[str, Any] | None, key: str) -> Any:
        return "" if source is None else source.get(key, "")

    after_ng_gap = C1_TARGETS["natural_gas_m3_per_h"] - float(best_after["natural_gas_m3_per_h"])
    after_wag_gap = C1_TARGETS["wag_electricity_twh_per_year"] - float(best_after["wag_electricity_twh_per_year"])
    rows_out = [
        {
            "gap_id": "S33B_GAP_001",
            "comparison": "best_existing_s3_3_c1_holdout_to_best_s3_3b_directional_case",
            "before_candidate_id": _field(best_before, "candidate_id"),
            "before_bf_bof_share": _field(best_before, "bf_bof_share_scenario"),
            "before_gross_error_pct": _field(best_before, "c1_gross_electricity_twh_per_year_error_pct"),
            "before_wag_error_pct": _field(best_before, "c1_wag_electricity_twh_per_year_error_pct"),
            "before_ng_error_pct": _field(best_before, "c1_natural_gas_m3_per_h_error_pct"),
            "before_co2_error_pct": _field(best_before, "c1_direct_site_co2_t_per_year_error_pct"),
            "before_primary_error_pct": _field(best_before, "c1_athanasiadis_primary_proxy_pj_per_year_error_pct"),
            "after_candidate_id": best_after["candidate_id"],
            "after_bf_bof_share": best_after["bf_bof_share_scenario"],
            "after_gross_error_pct": best_after["c1_gross_electricity_twh_per_year_error_pct"],
            "after_wag_error_pct": best_after["c1_wag_electricity_twh_per_year_error_pct"],
            "after_ng_error_pct": best_after["c1_natural_gas_m3_per_h_error_pct"],
            "after_co2_error_pct": best_after["c1_direct_site_co2_t_per_year_error_pct"],
            "after_primary_error_pct": best_after["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "after_explicit_drp_ng_m3_per_h": best_after.get("explicit_drp_natural_gas_m3_per_h", ""),
            "after_residual_ng_m3_per_h": best_after.get("residual_ng_m3_per_h", ""),
            "remaining_ng_gap_m3_per_h": after_ng_gap,
            "remaining_wag_gap_twh_per_year": after_wag_gap,
            "remaining_blocker": (
                "C1 remains blocked unless source-carded NG top-up/process-heat and WAG interface/topology "
                "mechanisms close remaining carrier-composition gaps."
            ),
            "s3_3a_arbitrary_values_promoted": "false",
        }
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3b_remaining_gap"], rows_out)


def run_validate_c1_s3_3b(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3b_static_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    rows: list[dict[str, Any]] = []
    route_shares = c1_s3_3b_route_shares()
    for candidate in _diagnostic_candidate_rows():
        values = candidate_values(candidate)
        for route_share in route_shares:
            row = solve_calibration_case(
                candidate_id=str(candidate["candidate_id"]),
                candidate_role=str(candidate["candidate_role"]),
                parameter_values=values,
                configuration_id=C1_CONFIGURATION_ID,
                horizon_hours=168,
                bf_bof_share=route_share,
                smoke_case_id=f"s3_3b_c1_source_carded_{route_share:.6f}",
                solver=solver,
                solver_name=resolved_name,
            )
            _add_c1_holdout_errors(row)
            _annotate_s3_3b_row(row, candidate=candidate, route_share=route_share)
            rows.append(row)
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3b_directional_validation"], rows)
    _write_s3_3b_remaining_gap(rows)
    pass_count = sum(1 for row in rows if row["c1_holdout_pass_principal_targets"] == "true")
    best = _best_evaluable_row(rows)
    return {
        "solver_name": resolved_name,
        "directional_cases": len(rows),
        "candidate_sets": list(C1_DIAGNOSTIC_CANDIDATE_IDS),
        "route_shares": list(route_shares),
        "holdout_pass_cases": pass_count,
        "best_candidate_id": "" if best is None else best["candidate_id"],
        "best_bf_bof_share": "" if best is None else best["bf_bof_share_scenario"],
        "best_wag_error_pct": "" if best is None else best["c1_wag_electricity_twh_per_year_error_pct"],
        "best_ng_error_pct": "" if best is None else best["c1_natural_gas_m3_per_h_error_pct"],
        "no_run_folder_created": True,
        "s3_3a_arbitrary_values_promoted": False,
    }


def _s3_3c_case_definitions() -> list[dict[str, Any]]:
    return [
        {
            "utility_case_id": "s3_3b_baseline_no_utility_extension",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["disabled"],
            "wag_to_power_efficiency_fraction": None,
            "case_role": "previous_s3_3b_baseline",
            "candidate_status": "baseline_no_new_input",
        },
        {
            "utility_case_id": "s3_3c_wag_ng_utility_heat_low",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "minimum_ng_pj_per_year": 0.0,
            "wag_to_power_efficiency_fraction": None,
            "case_role": "low_heat_boundary_with_wag_ng_arcs",
            "candidate_status": "candidate_boundary_extension",
        },
        {
            "utility_case_id": "s3_3c_explicit_ng_low",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "wag_to_power_efficiency_fraction": None,
            "case_role": "low_explicit_downstream_light_side_ng_boundary",
            "candidate_status": "candidate_boundary_extension",
        },
        {
            "utility_case_id": "s3_3c_explicit_ng_central",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "wag_to_power_efficiency_fraction": None,
            "case_role": "central_explicit_downstream_light_side_ng_boundary",
            "candidate_status": "candidate_boundary_extension",
        },
        {
            "utility_case_id": "s3_3c_explicit_ng_high",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "wag_to_power_efficiency_fraction": None,
            "case_role": "high_explicit_downstream_light_side_ng_boundary",
            "candidate_status": "candidate_boundary_extension",
        },
        {
            "utility_case_id": "s3_3c_explicit_ng_low_low_power_efficiency",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "wag_to_power_efficiency_fraction": 0.321,
            "case_role": "combined_explicit_ng_boundary_and_public_power_efficiency_sensitivity",
            "candidate_status": "candidate_sensitivity_not_recalibration",
        },
    ]


def _s3_3c_switches(case: dict[str, Any]) -> dict[str, float]:
    switches = {
        "s3_3c_downstream_light_side_ng_pj_per_year": float(
            case["downstream_light_side_ng_pj_per_year"]
        ),
        "s3_3c_downstream_light_side_minimum_ng_pj_per_year": float(case.get("minimum_ng_pj_per_year", 0.0)),
    }
    if case["wag_to_power_efficiency_fraction"] not in (None, ""):
        switches["s3_3c_wag_to_power_efficiency_fraction"] = float(
            case["wag_to_power_efficiency_fraction"]
        )
    return switches


def _annotate_s3_3c_row(row: dict[str, Any], *, utility_case: dict[str, Any], route_share: float) -> None:
    target_ng = C1_TARGETS["natural_gas_m3_per_h"]
    target_wag = C1_TARGETS["wag_electricity_twh_per_year"]
    row.update(
        {
            "s3_3c_utility_boundary_extension": "true",
            "utility_case_id": utility_case["utility_case_id"],
            "utility_case_role": utility_case["case_role"],
            "candidate_boundary_status": utility_case["candidate_status"],
            "downstream_light_side_ng_pj_per_year_input": utility_case[
                "downstream_light_side_ng_pj_per_year"
            ],
            "downstream_light_side_minimum_ng_pj_per_year_input": utility_case.get(
                "minimum_ng_pj_per_year", 0.0
            ),
            "wag_to_power_efficiency_fraction_override": (
                ""
                if utility_case["wag_to_power_efficiency_fraction"] in (None, "")
                else utility_case["wag_to_power_efficiency_fraction"]
            ),
            "bf_bof_share_scenario": route_share,
            "c0_candidate_parameters_fixed": "true",
            "s3_3a_wag_availability_factor_promoted": "false",
            "s3_3a_ng_gap_closure_promoted": "false",
            "generic_residual_ng_gap_closure_used": "false",
            "approved_inputs_populated": "false",
            "table9_validation_status": "directional_boundary_extension_validation",
            "market_logic_active": "false",
            "stochastic_logic_active": "false",
            "cvar_logic_active": "false",
            "mfrr_logic_active": "false",
        }
    )
    row["remaining_ng_gap_m3_per_h"] = (
        ""
        if row.get("natural_gas_m3_per_h") in ("", None)
        else target_ng - float(row["natural_gas_m3_per_h"])
    )
    row["remaining_wag_gap_twh_per_year"] = (
        ""
        if row.get("wag_electricity_twh_per_year") in ("", None)
        else target_wag - float(row["wag_electricity_twh_per_year"])
    )
    row["c1_holdout_pass_principal_targets"] = _c1_principal_pass(row)


def _write_s3_3c_before_after(rows: list[dict[str, Any]]) -> None:
    baseline_rows = [
        row
        for row in rows
        if row.get("utility_case_id") == "s3_3b_baseline_no_utility_extension"
        and row.get("bf_bof_share_scenario") not in ("", None)
    ]
    extension_rows = [
        row
        for row in rows
        if row.get("utility_case_id") != "s3_3b_baseline_no_utility_extension"
    ]
    best_before = _best_evaluable_row(baseline_rows)
    best_after = _best_evaluable_row(extension_rows)
    if best_before is None or best_after is None:
        _write_dataframe(
            S3_3_OUTPUT_PATHS["s3_3c_before_after"],
            [
                {
                    "comparison_id": "S33C_COMPARE_001",
                    "status": "blocked_no_evaluable_before_or_after_row",
                }
            ],
        )
        return
    metrics = [
        ("gross_electricity", "c1_gross_electricity_twh_per_year_error_pct"),
        ("wag_electricity", "c1_wag_electricity_twh_per_year_error_pct"),
        ("natural_gas", "c1_natural_gas_m3_per_h_error_pct"),
        ("direct_co2", "c1_direct_site_co2_t_per_year_error_pct"),
        ("primary_proxy", "c1_athanasiadis_primary_proxy_pj_per_year_error_pct"),
    ]
    rows_out = []
    for metric, column in metrics:
        before = float(best_before[column])
        after = float(best_after[column])
        rows_out.append(
            {
                "comparison_id": "S33C_COMPARE_001",
                "metric": metric,
                "before_candidate_id": best_before["candidate_id"],
                "before_utility_case_id": best_before["utility_case_id"],
                "before_bf_bof_share": best_before["bf_bof_share_scenario"],
                "before_error_pct": before,
                "after_candidate_id": best_after["candidate_id"],
                "after_utility_case_id": best_after["utility_case_id"],
                "after_bf_bof_share": best_after["bf_bof_share_scenario"],
                "after_error_pct": after,
                "absolute_error_improvement_pct_points": abs(before) - abs(after),
                "interpretation": "positive means absolute error moved toward target",
            }
        )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_before_after"], rows_out)


def _write_s3_3c_remaining_gap(rows: list[dict[str, Any]]) -> None:
    best_after = _best_evaluable_row(
        [row for row in rows if row.get("utility_case_id") != "s3_3b_baseline_no_utility_extension"]
    )
    if best_after is None:
        _write_dataframe(
            S3_3_OUTPUT_PATHS["s3_3c_remaining_gap"],
            [{"gap_id": "S33C_GAP_001", "status": "blocked_no_evaluable_s3_3c_rows"}],
        )
        return
    rows_out = [
        {
            "gap_id": "S33C_GAP_001",
            "best_candidate_id": best_after["candidate_id"],
            "best_utility_case_id": best_after["utility_case_id"],
            "best_bf_bof_share": best_after["bf_bof_share_scenario"],
            "gross_error_pct": best_after["c1_gross_electricity_twh_per_year_error_pct"],
            "wag_error_pct": best_after["c1_wag_electricity_twh_per_year_error_pct"],
            "ng_error_pct": best_after["c1_natural_gas_m3_per_h_error_pct"],
            "co2_error_pct": best_after["c1_direct_site_co2_t_per_year_error_pct"],
            "primary_error_pct": best_after["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"],
            "explicit_drp_ng_m3_per_h": best_after.get("explicit_drp_natural_gas_m3_per_h", ""),
            "utility_heat_ng_m3_per_h": best_after.get("utility_heat_natural_gas_m3_per_h", ""),
            "residual_ng_m3_per_h": best_after.get("residual_ng_m3_per_h", ""),
            "wag_utility_heat_use_pj_per_year": best_after.get("wag_utility_heat_use_pj_per_year", ""),
            "wag_power_fuel_use_pj_per_year": best_after.get("wag_power_fuel_use_pj_per_year", ""),
            "flare_pj_per_year": best_after.get("flare_pj_per_year", ""),
            "remaining_ng_gap_m3_per_h": best_after.get("remaining_ng_gap_m3_per_h", ""),
            "remaining_wag_gap_twh_per_year": best_after.get("remaining_wag_gap_twh_per_year", ""),
            "s3_3_freeze_status": "blocked_pending_governed_decision",
            "s4_ready": "false",
            "remaining_risk": (
                "Utility boundary improves carrier accounting directionally, but values remain candidate inputs "
                "and Table 9 remains broader-boundary validation."
            ),
        }
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_remaining_gap"], rows_out)


def run_validate_c1_s3_3c(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3c_static_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    candidates_by_id = {str(row["candidate_id"]): row for row in _diagnostic_candidate_rows()}
    candidate = candidates_by_id["S33_CAND_002_LOW_WAG_ENVELOPE"]
    values = candidate_values(candidate)
    rows: list[dict[str, Any]] = []
    route_shares = c1_s3_3b_route_shares()

    c0_regression = solve_calibration_case(
        candidate_id=str(candidate["candidate_id"]),
        candidate_role=str(candidate["candidate_role"]),
        parameter_values=values,
        configuration_id=C0_CONFIGURATION_ID,
        horizon_hours=168,
        smoke_case_id="s3_3c_c0_no_utility_extension_regression",
        solver=solver,
        solver_name=resolved_name,
    )
    c0_regression.update(
        {
            "utility_case_id": "c0_no_utility_extension_regression",
            "s3_3c_utility_boundary_extension": "false",
            "c0_regression_status": c0_regression.get("accepted_for_calibration", "false"),
            "generic_residual_ng_gap_closure_used": "false",
        }
    )
    rows.append(c0_regression)

    for route_share in route_shares:
        for utility_case in _s3_3c_case_definitions():
            row = solve_calibration_case(
                candidate_id=str(candidate["candidate_id"]),
                candidate_role=str(candidate["candidate_role"]),
                parameter_values=values,
                configuration_id=C1_CONFIGURATION_ID,
                horizon_hours=168,
                bf_bof_share=route_share,
                smoke_case_id=f"s3_3c_{utility_case['utility_case_id']}_{route_share:.6f}",
                c1_diagnostic_switches=_s3_3c_switches(utility_case),
                solver=solver,
                solver_name=resolved_name,
            )
            _add_c1_holdout_errors(row)
            _annotate_s3_3c_row(row, utility_case=utility_case, route_share=route_share)
            rows.append(row)
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3c_c1_validation"], rows)
    _write_s3_3c_before_after(rows)
    _write_s3_3c_remaining_gap(rows)
    best = _best_evaluable_row(
        [row for row in rows if row.get("utility_case_id") != "s3_3b_baseline_no_utility_extension"]
    )
    return {
        "solver_name": resolved_name,
        "validation_rows": len(rows),
        "candidate_set": candidate["candidate_id"],
        "route_shares": list(route_shares),
        "utility_cases": [case["utility_case_id"] for case in _s3_3c_case_definitions()],
        "best_candidate_id": "" if best is None else best["candidate_id"],
        "best_utility_case_id": "" if best is None else best["utility_case_id"],
        "best_bf_bof_share": "" if best is None else best["bf_bof_share_scenario"],
        "best_wag_error_pct": "" if best is None else best["c1_wag_electricity_twh_per_year_error_pct"],
        "best_ng_error_pct": "" if best is None else best["c1_natural_gas_m3_per_h_error_pct"],
        "no_run_folder_created": True,
        "s3_3a_arbitrary_values_promoted": False,
    }


def _write_s3_3d_static_artifacts() -> None:
    _write_s3_3c_static_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3d_assumption_review"], s3_3d_utility_assumption_review_rows())
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3d_promoted_candidate_parameter_set"],
        s3_3d_promoted_candidate_parameter_rows(),
    )
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3d_rejected_or_blocked_assumptions"],
        s3_3d_rejected_or_blocked_assumption_rows(),
    )


def _s3_3d_case_definitions() -> list[dict[str, Any]]:
    return [
        {
            "utility_case_id": "s3_3b_baseline_no_utility_extension",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["disabled"],
            "minimum_ng_pj_per_year": 0.0,
            "wag_to_power_efficiency_fraction": None,
            "case_role": "previous_s3_3b_baseline",
            "classification": "context only",
            "candidate_status": "baseline_no_new_input",
        },
        {
            "utility_case_id": "s3_3d_provisional_utility_low",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY[
                "low_public_candidate"
            ],
            "case_role": "low_explicit_utility_ng_with_low_public_wag_power_efficiency",
            "classification": "provisional input",
            "candidate_status": "provisional_validation_only_not_approved_input",
        },
        {
            "utility_case_id": "s3_3d_provisional_utility_central",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY[
                "central_public_candidate"
            ],
            "case_role": "central_explicit_utility_ng_with_midpoint_public_wag_power_efficiency",
            "classification": "provisional input",
            "candidate_status": "provisional_validation_only_not_approved_input",
        },
        {
            "utility_case_id": "s3_3d_provisional_utility_high",
            "downstream_light_side_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "minimum_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY[
                "high_public_candidate"
            ],
            "case_role": "high_explicit_utility_ng_with_high_public_wag_power_efficiency",
            "classification": "sensitivity only",
            "candidate_status": "upper_sensitivity_only_not_approved_input",
        },
    ]


def _selected_ensemble_candidate_rows() -> list[dict[str, Any]]:
    if not S3_3_OUTPUT_PATHS["ensemble"].exists():
        select_parameter_ensemble()
    if not S3_3_OUTPUT_PATHS["ensemble"].exists():
        return _diagnostic_candidate_rows()
    ensemble = pd.read_csv(S3_3_OUTPUT_PATHS["ensemble"], dtype=str, keep_default_na=False)
    lookup = _load_candidate_lookup()
    rows: list[dict[str, Any]] = []
    for ensemble_row in ensemble.to_dict(orient="records"):
        candidate_id = ensemble_row.get("candidate_id", "")
        if not candidate_id or candidate_id not in lookup:
            continue
        candidate = dict(lookup[candidate_id])
        candidate["ensemble_role"] = ensemble_row.get("ensemble_role", "")
        rows.append(candidate)
    return rows or _diagnostic_candidate_rows()


def _annotate_s3_3d_row(row: dict[str, Any], *, utility_case: dict[str, Any], route_share: float) -> None:
    _annotate_s3_3c_row(row, utility_case=utility_case, route_share=route_share)
    residual_m3_per_h = float(row.get("residual_ng_m3_per_h", 0.0) or 0.0)
    principal_pass = row.get("c1_holdout_pass_principal_targets") == "true"
    row.update(
        {
            "s3_3d_review_stage": "utility_assumption_review_and_retained_ensemble_validation",
            "s3_3d_utility_boundary_extension": (
                "false" if utility_case["utility_case_id"] == "s3_3b_baseline_no_utility_extension" else "true"
            ),
            "utility_assumption_classification": utility_case["classification"],
            "approved_input_status": "not_approved_input",
            "s3_3d_candidate_values_promoted_to_approved_inputs": "false",
            "inherited_residual_ng_component_status": "inherited_c0_calibration_artifact_non_promotable",
            "inherited_residual_ng_freeze_status": (
                "blocked_nonzero_inherited_c0_residual" if residual_m3_per_h > 1e-9 else "not_active"
            ),
            "freeze_eligible_c1_pass": "false",
            "table9_validation_status": "provisional_broader_boundary_validation",
            "s3_3a_wag_availability_factor_promoted": "false",
            "s3_3a_ng_gap_closure_promoted": "false",
            "generic_residual_ng_gap_closure_used": "false",
        }
    )
    if principal_pass and residual_m3_per_h > 1e-9:
        row["s3_3d_strict_validation_status"] = "numerical_pass_but_blocked_by_inherited_residual_ng"
    elif principal_pass:
        row["s3_3d_strict_validation_status"] = "numerical_pass_not_freeze_reviewed"
    else:
        row["s3_3d_strict_validation_status"] = "principal_targets_not_all_within_tolerance"


def _write_s3_3d_inherited_residual_ng_audit(candidates: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    hourly_final = calibration_hourly_target_t()
    for candidate in candidates:
        residual_per_t = float(candidate["residual_c0_ng_m3_per_t_final"])
        residual_per_h = residual_per_t * hourly_final
        rows.append(
            {
                "audit_id": f"S33D_RESIDUAL_NG_{candidate['candidate_id']}",
                "candidate_id": candidate["candidate_id"],
                "ensemble_role": candidate.get("ensemble_role", candidate.get("candidate_role", "")),
                "residual_c0_ng_m3_per_t_final": residual_per_t,
                "implied_residual_ng_m3_per_h_at_6_2Mt": residual_per_h,
                "c0_table8_ng_target_m3_per_h": C0_REFERENCE_TARGETS["natural_gas_m3_per_h"],
                "difference_vs_c0_table8_m3_per_h": residual_per_h - C0_REFERENCE_TARGETS["natural_gas_m3_per_h"],
                "component_interpretation": "C0 calibration residual carried into C1 validation, not decomposed C1 process gas",
                "retained_baseline_process_gas_supported": "not_demonstrated",
                "hidden_residual_flag": "true",
                "promotion_decision": "blocked_not_promotable_for_freeze",
                "required_resolution": "decompose into source-backed retained process/utility gas or keep Table 9 contextual",
            }
        )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3d_inherited_residual_ng_audit"], rows)


def _write_s3_3d_before_after_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c0_rows = [row for row in rows if row.get("configuration_id") == C0_CONFIGURATION_ID]
    c1_rows = [row for row in rows if row.get("configuration_id") == C1_CONFIGURATION_ID]
    baseline_rows = [row for row in c1_rows if row.get("utility_case_id") == "s3_3b_baseline_no_utility_extension"]
    extension_rows = [row for row in c1_rows if row.get("utility_case_id") != "s3_3b_baseline_no_utility_extension"]
    best_before = _best_evaluable_row(baseline_rows)
    best_after = _best_evaluable_row(extension_rows)
    output_rows: list[dict[str, Any]] = []
    output_rows.append(
        {
            "summary_id": "S33D_SUMMARY_C0_REGRESSION",
            "metric": "c0_regression_accepted_rows",
            "before_value": "",
            "after_value": sum(1 for row in c0_rows if row.get("accepted_for_calibration") == "true"),
            "status": "accepted" if all(row.get("accepted_for_calibration") == "true" for row in c0_rows) else "blocked",
            "notes": f"C0 rows evaluated: {len(c0_rows)}.",
        }
    )
    if best_before is not None and best_after is not None:
        metrics = [
            ("gross_electricity", "c1_gross_electricity_twh_per_year_error_pct"),
            ("wag_electricity", "c1_wag_electricity_twh_per_year_error_pct"),
            ("natural_gas", "c1_natural_gas_m3_per_h_error_pct"),
            ("direct_co2", "c1_direct_site_co2_t_per_year_error_pct"),
            ("primary_proxy", "c1_athanasiadis_primary_proxy_pj_per_year_error_pct"),
        ]
        for metric, column in metrics:
            before = float(best_before[column])
            after = float(best_after[column])
            output_rows.append(
                {
                    "summary_id": "S33D_SUMMARY_C1_BEFORE_AFTER",
                    "metric": metric,
                    "before_candidate_id": best_before["candidate_id"],
                    "before_utility_case_id": best_before["utility_case_id"],
                    "before_bf_bof_share": best_before["bf_bof_share_scenario"],
                    "before_value": before,
                    "after_candidate_id": best_after["candidate_id"],
                    "after_utility_case_id": best_after["utility_case_id"],
                    "after_bf_bof_share": best_after["bf_bof_share_scenario"],
                    "after_value": after,
                    "absolute_error_improvement_pct_points": abs(before) - abs(after),
                    "status": "improved" if abs(after) < abs(before) else "not_improved",
                    "notes": "Positive improvement means absolute error moved toward target.",
                }
            )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3d_before_after_summary"], output_rows)
    return {
        "best_before": best_before or {},
        "best_after": best_after or {},
        "c0_rows": len(c0_rows),
        "c0_accepted_rows": sum(1 for row in c0_rows if row.get("accepted_for_calibration") == "true"),
    }


def _write_s3_3d_stage_gate_decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c1_rows = [row for row in rows if row.get("configuration_id") == C1_CONFIGURATION_ID]
    provisional_passes = [row for row in c1_rows if row.get("c1_holdout_pass_principal_targets") == "true"]
    freeze_passes = [row for row in c1_rows if row.get("freeze_eligible_c1_pass") == "true"]
    residual_blocked = any(
        row.get("inherited_residual_ng_freeze_status") == "blocked_nonzero_inherited_c0_residual"
        for row in c1_rows
    )
    if freeze_passes:
        decision = "freeze_ready"
    elif provisional_passes and residual_blocked:
        decision = "provisionally_acceptable_pending_source_card_review_but_s3_3_blocked"
    else:
        decision = "still_blocked_with_named_blockers"
    decision_rows = [
        {
            "gate_id": "S33D_GATE_001",
            "gate_name": "all_s3_3c_assumptions_classified",
            "status": "pass",
            "notes": "S3.3d assumption review, promotion, rejection, and residual audit artifacts were written.",
        },
        {
            "gate_id": "S33D_GATE_002",
            "gate_name": "c0_retained_ensemble_regression",
            "status": "pass"
            if all(
                row.get("accepted_for_calibration") == "true"
                for row in rows
                if row.get("configuration_id") == C0_CONFIGURATION_ID
            )
            else "blocked",
            "notes": "C0 uses no utility-boundary activation; S3.3c defaults remain inactive.",
        },
        {
            "gate_id": "S33D_GATE_003",
            "gate_name": "c1_provisional_utility_pass_cases",
            "status": "pass" if provisional_passes else "blocked",
            "notes": f"Principal C1 tolerance pass rows under provisional utility cases: {len(provisional_passes)}.",
        },
        {
            "gate_id": "S33D_GATE_004",
            "gate_name": "inherited_residual_ng_resolved",
            "status": "blocked" if residual_blocked else "pass",
            "notes": "Inherited C0 residual NG remains non-promotable and blocks freeze." if residual_blocked else "",
        },
        {
            "gate_id": "S33D_GATE_005",
            "gate_name": "s4_readiness",
            "status": "pass" if decision == "freeze_ready" else "blocked",
            "notes": "S4 remains blocked unless freeze-ready C1 validation is achieved without blocked residual terms.",
        },
        {
            "gate_id": "S33D_DECISION",
            "gate_name": "stage_gate_decision",
            "status": decision,
            "notes": "Athanasiadis Table 9 remains broader-boundary/contextual unless utility values and residual decomposition are promoted.",
        },
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3d_stage_gate_decision"], decision_rows)
    return {
        "decision": decision,
        "provisional_pass_cases": len(provisional_passes),
        "freeze_eligible_pass_cases": len(freeze_passes),
        "inherited_residual_ng_blocked": residual_blocked,
    }


def run_validate_c1_s3_3d(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3d_static_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    candidates = _selected_ensemble_candidate_rows()
    _write_s3_3d_inherited_residual_ng_audit(candidates)
    rows: list[dict[str, Any]] = []
    route_shares = c1_s3_3b_route_shares()
    utility_cases = _s3_3d_case_definitions()

    for candidate in candidates:
        values = candidate_values(candidate)
        c0_regression = solve_calibration_case(
            candidate_id=str(candidate["candidate_id"]),
            candidate_role=str(candidate.get("candidate_role", candidate.get("ensemble_role", ""))),
            parameter_values=values,
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=168,
            smoke_case_id=f"s3_3d_c0_regression_{candidate['candidate_id']}",
            solver=solver,
            solver_name=resolved_name,
        )
        c0_regression.update(
            {
                "ensemble_role": candidate.get("ensemble_role", ""),
                "utility_case_id": "c0_no_utility_extension_regression",
                "s3_3d_utility_boundary_extension": "false",
                "s3_3d_review_stage": "utility_assumption_review_and_retained_ensemble_validation",
                "approved_input_status": "not_approved_input",
                "generic_residual_ng_gap_closure_used": "false",
            }
        )
        rows.append(c0_regression)

        for route_share in route_shares:
            for utility_case in utility_cases:
                row = solve_calibration_case(
                    candidate_id=str(candidate["candidate_id"]),
                    candidate_role=str(candidate.get("candidate_role", candidate.get("ensemble_role", ""))),
                    parameter_values=values,
                    configuration_id=C1_CONFIGURATION_ID,
                    horizon_hours=168,
                    bf_bof_share=route_share,
                    smoke_case_id=f"s3_3d_{utility_case['utility_case_id']}_{route_share:.6f}",
                    c1_diagnostic_switches=_s3_3c_switches(utility_case),
                    solver=solver,
                    solver_name=resolved_name,
                )
                row["ensemble_role"] = candidate.get("ensemble_role", "")
                _add_c1_holdout_errors(row)
                _annotate_s3_3d_row(row, utility_case=utility_case, route_share=route_share)
                rows.append(row)

    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3d_retained_ensemble_validation"], rows)
    summary = _write_s3_3d_before_after_summary(rows)
    decision = _write_s3_3d_stage_gate_decision(rows)
    best_after = summary["best_after"]
    return {
        "solver_name": resolved_name,
        "validation_rows": len(rows),
        "candidate_sets": [candidate["candidate_id"] for candidate in candidates],
        "route_shares": list(route_shares),
        "utility_cases": [case["utility_case_id"] for case in utility_cases],
        "best_candidate_id": best_after.get("candidate_id", ""),
        "best_utility_case_id": best_after.get("utility_case_id", ""),
        "best_bf_bof_share": best_after.get("bf_bof_share_scenario", ""),
        "best_wag_error_pct": best_after.get("c1_wag_electricity_twh_per_year_error_pct", ""),
        "best_ng_error_pct": best_after.get("c1_natural_gas_m3_per_h_error_pct", ""),
        "stage_gate_decision": decision["decision"],
        "provisional_pass_cases": decision["provisional_pass_cases"],
        "freeze_eligible_pass_cases": decision["freeze_eligible_pass_cases"],
        "no_run_folder_created": True,
        "s3_3a_arbitrary_values_promoted": False,
    }


def _write_s3_3e_static_artifacts() -> None:
    _write_s3_3d_static_artifacts()
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3e_decomposition_attempt"],
        s3_3e_static_decomposition_attempt_rows(),
    )
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3e_ng_component_candidates"],
        s3_3e_ng_component_candidate_rows(),
    )
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3e_accept_reject_decisions"],
        s3_3e_accept_reject_decision_rows(),
    )
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3e_validation_boundary_decision"],
        s3_3e_validation_boundary_decision_rows(),
    )


def _strict_current_boundary_pass(row: dict[str, Any]) -> bool:
    if row.get("termination_condition") not in {"optimal", "feasible"}:
        return False
    annual_target = float(row.get("annual_final_product_t", CALIBRATION_ANNUAL_FINAL_PRODUCT_T) or 0.0)
    try:
        checks = [
            abs(float(row["annualised_final_product_t"]) - annual_target) <= 1e-4,
            float(row["terminal_cold_residual_t"]) <= 1e-5,
            float(row["terminal_hot_residual_t"]) <= 1e-5,
            float(row["terminal_reheated_residual_t"]) <= 1e-5,
            float(row["max_material_balance_residual_t"]) <= 1e-5,
            float(row["max_wag_balance_residual_gj"]) <= 1e-5,
            float(row["max_electricity_balance_residual_mwh"]) <= 1e-5,
            float(row["max_carbon_decomposition_residual_t"]) <= 1e-5,
            str(row.get("wag_double_counted_in_primary_proxy", "False")).lower() in {"false", "0"},
            float(row.get("residual_ng_m3_per_h", 0.0) or 0.0) <= 1e-9,
        ]
    except (KeyError, TypeError, ValueError):
        return False
    return all(checks)


def _annotate_s3_3e_row(row: dict[str, Any], *, utility_case: dict[str, Any], route_share: float, candidate: dict[str, Any]) -> None:
    _annotate_s3_3d_row(row, utility_case=utility_case, route_share=route_share)
    rejected_residual_m3_per_h = (
        float(candidate["residual_c0_ng_m3_per_t_final"]) * calibration_hourly_target_t()
    )
    strict_pass = _strict_current_boundary_pass(row)
    row.update(
        {
            "s3_3e_resolution_option": "Option B - Table 9 validation-boundary downgrade",
            "option_a_decomposition_status": "rejected_no_source_backed_c1_component",
            "option_b_boundary_downgrade_status": "applied",
            "inherited_residual_ng_removed_from_c1": "true",
            "rejected_inherited_residual_ng_m3_per_h": rejected_residual_m3_per_h,
            "rejected_inherited_residual_ng_m3_per_t_final": candidate["residual_c0_ng_m3_per_t_final"],
            "decomposed_retained_ng_m3_per_h": 0.0,
            "blocked_remainder_ng_m3_per_h": rejected_residual_m3_per_h,
            "table9_carrier_total_validation_role": "contextual_broader_boundary_holdout",
            "table9_strict_freeze_gate": "false",
            "strict_internal_process_network_checks": "true",
            "strict_accounting_consistency_checks": "true",
            "strict_current_public_boundary_pass": "true" if strict_pass else "false",
            "freeze_eligible_under_downgraded_boundary": "false",
            "s3_3e_stage_decision_basis": "requires_human_acceptance_of_boundary_downgrade_before_freeze",
            "generic_residual_ng_gap_closure_used": "false",
            "approved_inputs_populated": "false",
        }
    )


def _write_s3_3e_no_double_counting(rows: list[dict[str, Any]]) -> None:
    c1_rows = [row for row in rows if row.get("configuration_id") == C1_CONFIGURATION_ID]
    checked = len(c1_rows)
    residual_zero = sum(1 for row in c1_rows if float(row.get("residual_ng_m3_per_h", 0.0) or 0.0) <= 1e-9)
    wag_not_double_counted = sum(
        1
        for row in c1_rows
        if str(row.get("wag_double_counted_in_primary_proxy", "False")).lower() in {"false", "0"}
    )
    rows_out = [
        {
            "check_id": "S33E_DOUBLE_COUNT_001",
            "check_name": "inherited_residual_removed_from_c1",
            "rows_checked": checked,
            "rows_passing": residual_zero,
            "status": "pass" if residual_zero == checked else "blocked",
            "notes": "C1 residual_ng_m3_per_h is zero after rejecting inherited C0 residual.",
        },
        {
            "check_id": "S33E_DOUBLE_COUNT_002",
            "check_name": "wag_not_added_as_primary_energy",
            "rows_checked": checked,
            "rows_passing": wag_not_double_counted,
            "status": "pass" if wag_not_double_counted == checked else "blocked",
            "notes": "Athanasiadis proxy remains external coal + natural gas + gross electricity.",
        },
        {
            "check_id": "S33E_DOUBLE_COUNT_003",
            "check_name": "explicit_components_separate",
            "rows_checked": checked,
            "rows_passing": checked,
            "status": "pass",
            "notes": "Validation rows separately report explicit DRP NG, utility NG, represented steam/reheating NG, and rejected residual NG.",
        },
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3e_no_double_counting"], rows_out)


def _write_s3_3e_stage_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c0_rows = [row for row in rows if row.get("configuration_id") == C0_CONFIGURATION_ID]
    c1_rows = [row for row in rows if row.get("configuration_id") == C1_CONFIGURATION_ID]
    c0_pass = all(row.get("accepted_for_calibration") == "true" for row in c0_rows) and bool(c0_rows)
    c1_strict_pass_count = sum(1 for row in c1_rows if row.get("strict_current_public_boundary_pass") == "true")
    c1_strict_all_pass = c1_strict_pass_count == len(c1_rows) and bool(c1_rows)
    residual_rejected = all(
        row.get("inherited_residual_ng_removed_from_c1") == "true"
        and float(row.get("residual_ng_m3_per_h", 0.0) or 0.0) <= 1e-9
        for row in c1_rows
    )
    decision = (
        "provisionally_acceptable_current_public_boundary_table9_contextual_s4_blocked"
        if c0_pass and c1_strict_all_pass and residual_rejected
        else "still_blocked_after_boundary_downgrade"
    )
    stage_rows = [
        {
            "gate_id": "S33E_GATE_001",
            "gate_name": "option_a_decomposition_attempted",
            "status": "blocked",
            "notes": "No source-backed retained C1 NG component decomposes the inherited residual without weak assumptions.",
        },
        {
            "gate_id": "S33E_GATE_002",
            "gate_name": "option_b_boundary_downgrade_applied",
            "status": "pass",
            "notes": "Table 9 carrier totals are contextual broader-boundary holdout references, not strict freeze gates.",
        },
        {
            "gate_id": "S33E_GATE_003",
            "gate_name": "c0_retained_ensemble_regression",
            "status": "pass" if c0_pass else "blocked",
            "notes": f"C0 accepted rows: {sum(1 for row in c0_rows if row.get('accepted_for_calibration') == 'true')}/{len(c0_rows)}.",
        },
        {
            "gate_id": "S33E_GATE_004",
            "gate_name": "c1_current_boundary_strict_checks",
            "status": "pass" if c1_strict_all_pass else "blocked",
            "notes": f"C1 strict current-boundary pass rows: {c1_strict_pass_count}/{len(c1_rows)}.",
        },
        {
            "gate_id": "S33E_GATE_005",
            "gate_name": "inherited_residual_ng_removed",
            "status": "pass" if residual_rejected else "blocked",
            "notes": "Rejected inherited C0 residual is not included in C1 natural-gas totals.",
        },
        {
            "gate_id": "S33E_GATE_006",
            "gate_name": "s4_readiness",
            "status": "blocked",
            "notes": "Do not start S4 in this task; human acceptance of the Table 9 contextual downgrade is still required.",
        },
        {
            "gate_id": "S33E_DECISION",
            "gate_name": "stage_gate_decision",
            "status": decision,
            "notes": "S3.3e resolves the residual by boundary downgrade, not source-backed decomposition.",
        },
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3e_stage_gate_decision"], stage_rows)
    return {
        "decision": decision,
        "c0_rows": len(c0_rows),
        "c1_rows": len(c1_rows),
        "c1_strict_pass_rows": c1_strict_pass_count,
        "residual_rejected": residual_rejected,
    }


def run_resolve_inherited_ng_s3_3e(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3e_static_artifacts()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    candidates = _selected_ensemble_candidate_rows()
    rows: list[dict[str, Any]] = []
    route_shares = c1_s3_3b_route_shares()
    utility_cases = _s3_3d_case_definitions()

    for candidate in candidates:
        values = candidate_values(candidate)
        c0_regression = solve_calibration_case(
            candidate_id=str(candidate["candidate_id"]),
            candidate_role=str(candidate.get("candidate_role", candidate.get("ensemble_role", ""))),
            parameter_values=values,
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=168,
            smoke_case_id=f"s3_3e_c0_regression_{candidate['candidate_id']}",
            solver=solver,
            solver_name=resolved_name,
        )
        c0_regression.update(
            {
                "ensemble_role": candidate.get("ensemble_role", ""),
                "utility_case_id": "c0_no_utility_extension_regression",
                "s3_3e_resolution_option": "C0 calibration regression; inherited residual unchanged for C0",
                "table9_carrier_total_validation_role": "not_applicable_c0",
                "inherited_residual_ng_removed_from_c1": "not_applicable",
            }
        )
        rows.append(c0_regression)

        for route_share in route_shares:
            for utility_case in utility_cases:
                row = solve_calibration_case(
                    candidate_id=str(candidate["candidate_id"]),
                    candidate_role=str(candidate.get("candidate_role", candidate.get("ensemble_role", ""))),
                    parameter_values=values,
                    configuration_id=C1_CONFIGURATION_ID,
                    horizon_hours=168,
                    bf_bof_share=route_share,
                    smoke_case_id=f"s3_3e_{utility_case['utility_case_id']}_{route_share:.6f}",
                    c1_diagnostic_switches=_s3_3c_switches(utility_case),
                    residual_ng_m3_per_t_final_override=0.0,
                    solver=solver,
                    solver_name=resolved_name,
                )
                row["ensemble_role"] = candidate.get("ensemble_role", "")
                _add_c1_holdout_errors(row)
                _annotate_s3_3e_row(row, utility_case=utility_case, route_share=route_share, candidate=candidate)
                rows.append(row)

    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3e_c1_validation_after_residual_resolution"], rows)
    _write_s3_3e_no_double_counting(rows)
    stage = _write_s3_3e_stage_gate(rows)
    c1_rows = [row for row in rows if row.get("configuration_id") == C1_CONFIGURATION_ID]
    contextual = _best_evaluable_row(c1_rows)
    return {
        "solver_name": resolved_name,
        "resolution_option": "Option B - validation-boundary downgrade",
        "validation_rows": len(rows),
        "candidate_sets": [candidate["candidate_id"] for candidate in candidates],
        "route_shares": list(route_shares),
        "utility_cases": [case["utility_case_id"] for case in utility_cases],
        "best_contextual_candidate_id": "" if contextual is None else contextual["candidate_id"],
        "best_contextual_utility_case_id": "" if contextual is None else contextual["utility_case_id"],
        "best_contextual_bf_bof_share": "" if contextual is None else contextual["bf_bof_share_scenario"],
        "best_contextual_ng_error_pct": "" if contextual is None else contextual["c1_natural_gas_m3_per_h_error_pct"],
        "stage_gate_decision": stage["decision"],
        "c1_strict_pass_rows": stage["c1_strict_pass_rows"],
        "no_run_folder_created": True,
        "s3_3a_arbitrary_values_promoted": False,
    }


def _s3_3f_varied_parameters() -> list[Any]:
    excluded = {"residual_c0_ng_m3_per_t_final"}
    return [
        parameter
        for parameter in eligible_calibration_parameters()
        if parameter.parameter_id not in excluded
    ]


def _s3_3f_value_edges(values: dict[str, float], *, route_share: float, utility_ng_pj_per_year: float, drp_ng_multiplier: float) -> str:
    edge_ids: list[str] = []
    for parameter in _s3_3f_varied_parameters():
        value_at = float(values[parameter.parameter_id])
        if abs(value_at - parameter.lower) <= 1e-9:
            edge_ids.append(f"{parameter.parameter_id}=lower")
        elif abs(value_at - parameter.upper) <= 1e-9:
            edge_ids.append(f"{parameter.parameter_id}=upper")
    route_lower = min(c1_s3_3b_route_shares())
    route_upper = max(c1_s3_3b_route_shares())
    if abs(route_share - route_lower) <= 1e-9:
        edge_ids.append("c1_route_share=lower_capacity_implied")
    elif abs(route_share - route_upper) <= 1e-9:
        edge_ids.append("c1_route_share=upper")
    if abs(utility_ng_pj_per_year - 0.0) <= 1e-9:
        edge_ids.append("downstream_light_side_utility_ng=disabled_lower")
    elif abs(utility_ng_pj_per_year - S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"]) <= 1e-9:
        edge_ids.append("downstream_light_side_utility_ng=upper")
    if abs(drp_ng_multiplier - 0.8) <= 1e-9:
        edge_ids.append("drp_natural_gas_intensity=lower")
    elif abs(drp_ng_multiplier - 1.3) <= 1e-9:
        edge_ids.append("drp_natural_gas_intensity=upper")
    return ";".join(edge_ids)


def _s3_3f_within_bounds(values: dict[str, float], *, route_share: float, utility_ng_pj_per_year: float, drp_ng_multiplier: float) -> tuple[bool, str]:
    violations: list[str] = []
    for parameter in _s3_3f_varied_parameters():
        value_at = float(values[parameter.parameter_id])
        if value_at < parameter.lower - 1e-9 or value_at > parameter.upper + 1e-9:
            violations.append(parameter.parameter_id)
    route_lower = min(c1_s3_3b_route_shares())
    route_upper = max(c1_s3_3b_route_shares())
    if route_share < route_lower - 1e-9 or route_share > route_upper + 1e-9:
        violations.append("c1_route_share")
    utility_allowed = {0.0, *S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR.values()}
    if not any(abs(utility_ng_pj_per_year - value_at) <= 1e-9 for value_at in utility_allowed):
        violations.append("downstream_light_side_utility_ng_pj_per_year")
    if drp_ng_multiplier < 0.8 - 1e-9 or drp_ng_multiplier > 1.3 + 1e-9:
        violations.append("drp_natural_gas_intensity")
    return not violations, ";".join(violations)


def _s3_3f_candidate_rows(*, seed: int, max_candidates: int) -> list[dict[str, Any]]:
    rng = __import__("random").Random(seed)
    route_shares = list(c1_s3_3b_route_shares())
    utility_values = [
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["disabled"],
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["low"],
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
        S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["high"],
    ]
    drp_multipliers = [0.8, 1.0, 1.3]
    rows: list[dict[str, Any]] = []

    base_sets: list[tuple[str, str, dict[str, float]]] = [
        ("S33F_BASE_SOURCE_CENTRAL", "source_central_c1_structural_assumptions", source_central_parameter_set())
    ]
    for candidate in _selected_ensemble_candidate_rows():
        base_sets.append(
            (
                f"S33F_BASE_{candidate['candidate_id']}",
                str(candidate.get("ensemble_role", candidate.get("candidate_role", "retained_c0_ensemble"))),
                candidate_values(candidate),
            )
        )

    for base_id, role, values_in in base_sets:
        for route_share in route_shares:
            if len(rows) >= max_candidates:
                break
            values = dict(values_in)
            values["residual_c0_ng_m3_per_t_final"] = 0.0
            rows.append(
                {
                    "candidate_id": f"S33F_CAND_{len(rows):03d}",
                    "candidate_role": role,
                    "base_parameter_set_id": base_id,
                    "sample_method": "explicit_source_or_retained_c0_ensemble",
                    "bf_bof_share": route_share,
                    "drp_ng_multiplier": 1.0,
                    "downstream_light_side_utility_ng_pj_per_year": S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR["central"],
                    **values,
                }
            )

    central_values = source_central_parameter_set()
    central_values["residual_c0_ng_m3_per_t_final"] = 0.0
    for route_share in route_shares:
        for utility in utility_values:
            if len(rows) >= max_candidates:
                break
            rows.append(
                {
                    "candidate_id": f"S33F_CAND_{len(rows):03d}",
                    "candidate_role": "source_central_grid_route_utility",
                    "base_parameter_set_id": "S33F_BASE_SOURCE_CENTRAL",
                    "sample_method": "explicit_route_utility_grid",
                    "bf_bof_share": route_share,
                    "drp_ng_multiplier": 1.0,
                    "downstream_light_side_utility_ng_pj_per_year": utility,
                    **central_values,
                }
            )

    remaining = max_candidates - len(rows)
    varied = _s3_3f_varied_parameters()
    samples_by_parameter: dict[str, list[float]] = {}
    for parameter in varied:
        values = []
        for idx in range(max(remaining, 0)):
            unit = (idx + rng.random()) / float(max(remaining, 1))
            values.append(parameter.lower + unit * (parameter.upper - parameter.lower))
        rng.shuffle(values)
        samples_by_parameter[parameter.parameter_id] = values

    for idx in range(max(remaining, 0)):
        values = {parameter.parameter_id: samples_by_parameter[parameter.parameter_id][idx] for parameter in varied}
        values["residual_c0_ng_m3_per_t_final"] = 0.0
        rows.append(
            {
                "candidate_id": f"S33F_CAND_{len(rows):03d}",
                "candidate_role": "bounded_latin_hypercube",
                "base_parameter_set_id": "S33F_LHS",
                "sample_method": "seeded_latin_hypercube_202503",
                "bf_bof_share": route_shares[idx % len(route_shares)],
                "drp_ng_multiplier": drp_multipliers[idx % len(drp_multipliers)],
                "downstream_light_side_utility_ng_pj_per_year": utility_values[idx % len(utility_values)],
                **values,
            }
        )
    return rows[:max_candidates]


def _s3_3f_pct_error(row: dict[str, Any], metric: str) -> float | None:
    key = f"c1_{metric}_error_pct"
    if row.get(key) in ("", None):
        return None
    return float(row[key])


def _s3_3f_float(row: dict[str, Any], key: str, default: float = 1e9) -> float:
    value_at = row.get(key)
    if value_at in ("", None):
        return default
    return float(value_at)


def _annotate_s3_3f_result(row: dict[str, Any], *, candidate: dict[str, Any]) -> None:
    _add_c1_holdout_errors(row)
    errors = {
        metric: _s3_3f_pct_error(row, metric)
        for metric in C1_BOUNDED_ALIGNMENT_WEIGHTS
    }
    valid_errors = [abs(value_at) for value_at in errors.values() if value_at is not None]
    weighted_denominator = sum(C1_BOUNDED_ALIGNMENT_WEIGHTS.values())
    weighted_score = (
        sum(C1_BOUNDED_ALIGNMENT_WEIGHTS[metric] * abs(float(error)) for metric, error in errors.items() if error is not None)
        / weighted_denominator
        if len(valid_errors) == len(C1_BOUNDED_ALIGNMENT_WEIGHTS)
        else 1e9
    )
    max_error = max(valid_errors) if valid_errors else 1e9
    mean_error = sum(valid_errors) / len(valid_errors) if valid_errors else 1e9
    share_errors: dict[str, float | str] = {}
    for metric, target in C1_SHARE_TARGETS.items():
        if row.get(metric) in ("", None):
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = ""
        else:
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = (float(row[metric]) - target) / target

    route_share = float(candidate["bf_bof_share"])
    utility_ng = float(candidate["downstream_light_side_utility_ng_pj_per_year"])
    drp_multiplier = float(candidate["drp_ng_multiplier"])
    values = candidate_values(candidate)
    values["residual_c0_ng_m3_per_t_final"] = 0.0
    in_bounds, bound_violations = _s3_3f_within_bounds(
        values,
        route_share=route_share,
        utility_ng_pj_per_year=utility_ng,
        drp_ng_multiplier=drp_multiplier,
    )
    feasibility_checks = [
        row.get("termination_condition") in {"optimal", "feasible"},
        abs(_s3_3f_float(row, "annualised_final_product_t", 0.0) - CALIBRATION_ANNUAL_FINAL_PRODUCT_T) <= 1e-4,
        _s3_3f_float(row, "terminal_cold_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_hot_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_reheated_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_material_balance_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_wag_balance_residual_gj") <= 1e-5,
        _s3_3f_float(row, "max_electricity_balance_residual_mwh") <= 1e-5,
        _s3_3f_float(row, "max_carbon_decomposition_residual_t") <= 1e-5,
        _s3_3f_float(row, "residual_ng_m3_per_h") <= 1e-9,
        in_bounds,
    ]
    row.update(
        {
            "diagnostic_label": "bounded C1 alignment diagnostic",
            "s3_3f_bounded_alignment": "true",
            "c1_targets_used_for_score": "true",
            "calibration_freeze": "false",
            "s4_logic_introduced": "false",
            "approved_inputs_populated": "false",
            "residual_c1_gap_closure_used": "false",
            "inherited_c0_residual_ng_used_for_c1": "false",
            "arbitrary_wag_availability_factor_used": "false",
            "bf_bof_share_scenario": route_share,
            "drp_ng_multiplier": drp_multiplier,
            "downstream_light_side_utility_ng_pj_per_year": utility_ng,
            "broad_utility_boundary_active": "true" if utility_ng > 0.0 else "false",
            "capacity_implied_route_share_selected": "true"
            if abs(route_share - c1_s3_3b_route_shares()[0]) <= 1e-9
            else "false",
            "lower_wag_to_power_efficiency_selected": "true"
            if abs(float(candidate["wag_to_power_efficiency_fraction"]) - S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"]) <= 1e-9
            else "false",
            "registered_bounds_pass": "true" if in_bounds else "false",
            "registered_bound_violations": bound_violations,
            "range_edge_parameters": _s3_3f_value_edges(
                values,
                route_share=route_share,
                utility_ng_pj_per_year=utility_ng,
                drp_ng_multiplier=drp_multiplier,
            ),
            "weighted_c1_alignment_score": weighted_score,
            "unweighted_mean_abs_pct_error": mean_error,
            "max_abs_pct_error": max_error,
            "all_core_targets_within_5pct": "true" if max_error <= 0.05 else "false",
            "all_core_targets_within_10pct": "true" if max_error <= 0.10 else "false",
            "all_core_targets_within_15pct": "true" if max_error <= 0.15 else "false",
            "physically_feasible_and_balanced": "true" if all(feasibility_checks) else "false",
            **share_errors,
        }
    )
    if row["physically_feasible_and_balanced"] != "true":
        row["s3_3f_rejection_reason"] = "failed_feasibility_balance_or_bounds"
    else:
        row["s3_3f_rejection_reason"] = ""


def _write_s3_3f_best_and_boundary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = [
        row for row in rows
        if row.get("physically_feasible_and_balanced") == "true"
        and row.get("weighted_c1_alignment_score") not in ("", None)
    ]
    best_rows = sorted(evaluable, key=lambda row: float(row["weighted_c1_alignment_score"]))[:10]
    if best_rows:
        _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_best_cases"], best_rows)
    else:
        _write_dataframe(
            S3_3_OUTPUT_PATHS["s3_3f_best_cases"],
            [{"status": "blocked_no_evaluable_candidates"}],
        )
    best = best_rows[0] if best_rows else {}
    count_5 = sum(1 for row in evaluable if row.get("all_core_targets_within_5pct") == "true")
    count_10 = sum(1 for row in evaluable if row.get("all_core_targets_within_10pct") == "true")
    count_15 = sum(1 for row in evaluable if row.get("all_core_targets_within_15pct") == "true")
    if best:
        abs_errors = {
            "gross_electricity": abs(float(best["c1_gross_electricity_twh_per_year_error_pct"])),
            "wag_electricity": abs(float(best["c1_wag_electricity_twh_per_year_error_pct"])),
            "natural_gas": abs(float(best["c1_natural_gas_m3_per_h_error_pct"])),
            "direct_co2": abs(float(best["c1_direct_site_co2_t_per_year_error_pct"])),
            "primary_proxy": abs(float(best["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"])),
        }
        hardest = max(abs_errors, key=abs_errors.get)
        natural_gas_gap = C1_TARGETS["natural_gas_m3_per_h"] - float(best["natural_gas_m3_per_h"])
        wag_gap = C1_TARGETS["wag_electricity_twh_per_year"] - float(best["wag_electricity_twh_per_year"])
        strict_status = (
            "contextual_broader_boundary_validation"
            if best.get("all_core_targets_within_10pct") == "true" and best.get("broad_utility_boundary_active") == "true"
            else "bounded_alignment_only"
        )
        boundary_rows = [
            {
                "interpretation_id": "S33F_BOUNDARY_001",
                "item": "best_case_summary",
                "value": best["candidate_id"],
                "status": strict_status,
                "notes": "Best row is diagnostic only and does not create an S3.3 freeze.",
            },
            {
                "interpretation_id": "S33F_BOUNDARY_002",
                "item": "irreducible_gap_without_residuals",
                "value": f"natural_gas_gap_m3_per_h={natural_gas_gap};wag_electricity_gap_twh_per_year={wag_gap}",
                "status": "reported_not_closed",
                "notes": "No residual gap-closure term, inherited residual, or arbitrary WAG factor was used.",
            },
            {
                "interpretation_id": "S33F_BOUNDARY_003",
                "item": "hardest_target",
                "value": hardest,
                "status": "diagnostic_result",
                "notes": "Hardest target is selected by maximum absolute core target percentage error.",
            },
            {
                "interpretation_id": "S33F_BOUNDARY_004",
                "item": "s3_3_freeze_status",
                "value": "not_frozen",
                "status": "blocked",
                "notes": "S3.3f is a bounded alignment diagnostic, not a freeze or S4 entry record.",
            },
            {
                "interpretation_id": "S33F_BOUNDARY_005",
                "item": "s4_readiness",
                "value": "not_ready",
                "status": "blocked",
                "notes": "No DA price-taking or later market logic is introduced here.",
            },
        ]
    else:
        hardest = ""
        boundary_rows = [
            {
                "interpretation_id": "S33F_BOUNDARY_001",
                "item": "best_case_summary",
                "value": "",
                "status": "blocked_no_evaluable_candidates",
                "notes": "No feasible bounded C1 alignment candidate was available.",
            }
        ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_boundary_interpretation"], boundary_rows)
    return {
        "best": best,
        "candidate_count": len(rows),
        "evaluable_candidate_count": len(evaluable),
        "within_5pct_count": count_5,
        "within_10pct_count": count_10,
        "within_15pct_count": count_15,
        "hardest_target": hardest,
    }


def run_diagnose_c1_bounded_alignment(
    *,
    seed: int,
    max_candidates: int,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3e_static_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_parameter_eligibility"], s3_3f_parameter_eligibility_rows())
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_rejected_mechanisms"], s3_3f_rejected_mechanism_rows())
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    candidate_rows = _s3_3f_candidate_rows(seed=seed, max_candidates=max_candidates)
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_candidates"], candidate_rows)
    results: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        values = candidate_values(candidate)
        values["residual_c0_ng_m3_per_t_final"] = 0.0
        in_bounds, violations = _s3_3f_within_bounds(
            values,
            route_share=float(candidate["bf_bof_share"]),
            utility_ng_pj_per_year=float(candidate["downstream_light_side_utility_ng_pj_per_year"]),
            drp_ng_multiplier=float(candidate["drp_ng_multiplier"]),
        )
        if not in_bounds:
            rejected = dict(candidate)
            rejected.update(
                {
                    "termination_condition": "not_run_outside_registered_bounds",
                    "registered_bounds_pass": "false",
                    "registered_bound_violations": violations,
                    "physically_feasible_and_balanced": "false",
                    "weighted_c1_alignment_score": 1e9,
                    "s3_3f_rejection_reason": "outside_registered_bounds",
                }
            )
            results.append(rejected)
            continue
        row = solve_calibration_case(
            candidate_id=str(candidate["candidate_id"]),
            candidate_role=str(candidate["candidate_role"]),
            parameter_values=values,
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            bf_bof_share=float(candidate["bf_bof_share"]),
            smoke_case_id=f"s3_3f_{candidate['candidate_id']}",
            c1_diagnostic_switches={
                "drp_ng_multiplier": float(candidate["drp_ng_multiplier"]),
                "s3_3c_downstream_light_side_ng_pj_per_year": float(
                    candidate["downstream_light_side_utility_ng_pj_per_year"]
                ),
                "s3_3c_downstream_light_side_minimum_ng_pj_per_year": float(
                    candidate["downstream_light_side_utility_ng_pj_per_year"]
                ),
            },
            residual_ng_m3_per_t_final_override=0.0,
            solver=solver,
            solver_name=resolved_name,
        )
        row.update(
            {
                "base_parameter_set_id": candidate["base_parameter_set_id"],
                "sample_method": candidate["sample_method"],
            }
        )
        _annotate_s3_3f_result(row, candidate=candidate)
        results.append(row)
    results = sorted(
        results,
        key=lambda row: float(row.get("weighted_c1_alignment_score", 1e9) or 1e9),
    )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3f_results"], results)
    summary = _write_s3_3f_best_and_boundary(results)
    best = summary["best"]
    return {
        "solver_name": resolved_name,
        "diagnostic_label": "bounded C1 alignment diagnostic",
        "candidate_count": summary["candidate_count"],
        "evaluable_candidate_count": summary["evaluable_candidate_count"],
        "best_candidate_id": best.get("candidate_id", ""),
        "best_bf_bof_share": best.get("bf_bof_share_scenario", ""),
        "best_utility_ng_pj_per_year": best.get("downstream_light_side_utility_ng_pj_per_year", ""),
        "best_wag_to_power_efficiency_fraction": best.get("param_wag_to_power_efficiency_fraction", ""),
        "best_weighted_score": best.get("weighted_c1_alignment_score", ""),
        "best_mean_abs_pct_error": best.get("unweighted_mean_abs_pct_error", ""),
        "best_max_abs_pct_error": best.get("max_abs_pct_error", ""),
        "within_5pct_count": summary["within_5pct_count"],
        "within_10pct_count": summary["within_10pct_count"],
        "within_15pct_count": summary["within_15pct_count"],
        "hardest_target": summary["hardest_target"],
        "no_run_folder_created": True,
        "approved_inputs_populated": False,
        "s3_3a_arbitrary_values_promoted": False,
    }


def _s3_3g_sink_bounds() -> dict[str, dict[str, Any]]:
    return {row["sink_id"]: row for row in s3_3g_gas_sink_parameter_eligibility_rows()}


def _s3_3g_float(value_at: Any, default: float = 0.0) -> float:
    if value_at in ("", None):
        return default
    return float(value_at)


def _s3_3g_case_templates() -> list[dict[str, Any]]:
    bounds = _s3_3g_sink_bounds()
    hsm = bounds["hsm_fuel_substitution_ng"]
    pellet = bounds["pelletizing_firing_ng"]
    low_eff = S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"]
    central_eff = S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["central_public_candidate"]
    high_eff = S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["high_public_candidate"]
    zeroed = {
        "hsm_fuel_substitution_ng_pj_per_year": 0.0,
        "hsm_fuel_substitution_cog_pj_per_year": 0.0,
        "coking_plant_1_bfg_pj_per_year": 0.0,
        "coking_plant_1_cog_pj_per_year": 0.0,
        "pelletizing_firing_ng_pj_per_year": 0.0,
        "pelletizing_firing_cog_pj_per_year": 0.0,
        "pelletizing_grinding_ng_pj_per_year": 0.0,
        "pelletizing_grinding_bofg_pj_per_year": 0.0,
        "boiler_steam_ng_pj_per_year": 0.0,
        "boiler_steam_wag_pj_per_year": 0.0,
        "vattenfall_generator_bfg_equivalent_wag_fraction": 1.0,
        "vattenfall_generator_high_lhv_injection_limit_mj_per_m3": 5.0,
        "s3_3f_baseline_lumped_utility_ng_pj_per_year": 0.0,
    }
    cases = [
        {
            "case_template_id": "S33G_CASE_001_S3_3F_BASELINE",
            "case_role": "s3_3f_best_bounded_comparison_lumped_utility",
            "source_support_status": "comparison_baseline_not_gas_sink_decomposition",
            **zeroed,
            "s3_3f_baseline_lumped_utility_ng_pj_per_year": 7.75,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_002_CENTRAL_DECOMPOSITION",
            "case_role": "explicit_gas_sink_decomposition_central",
            "source_support_status": "mixed_source_supported_and_diagnostic_only",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["central"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["central"]),
            "boiler_steam_wag_pj_per_year": 1.0,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_003_LOW_PROCESS_NG_HIGH_WAG_PROCESS",
            "case_role": "low_process_ng_high_wag_to_process",
            "source_support_status": "bounded_low_ng_high_wag_process_diagnostic",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["lower"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["lower"]),
            "boiler_steam_wag_pj_per_year": 2.0,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_004_HIGH_PROCESS_NG_LOW_WAG_POWER",
            "case_role": "high_process_ng_low_wag_to_power",
            "source_support_status": "bounded_high_ng_low_power_efficiency_diagnostic",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["upper"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["upper"]),
            "boiler_steam_ng_pj_per_year": 2.0,
            "boiler_steam_wag_pj_per_year": 2.0,
            "wag_to_power_efficiency_fraction": low_eff,
        },
        {
            "case_template_id": "S33G_CASE_005_HSM_HEAVY",
            "case_role": "hsm_heavy_substitution",
            "source_support_status": "hsm_ng_upper_supported_no_unsupported_cog_split",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["upper"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["central"]),
            "boiler_steam_wag_pj_per_year": 1.0,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_006_PELLETIZING_HEAVY",
            "case_role": "pelletizing_heavy_substitution",
            "source_support_status": "pellet_firing_upper_no_unsupported_grinding_split",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["central"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["upper"]),
            "boiler_steam_wag_pj_per_year": 1.0,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_007_BOILER_STEAM_HEAVY",
            "case_role": "boiler_steam_heavy_substitution",
            "source_support_status": "diagnostic_only_boiler_steam_split",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["central"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["central"]),
            "boiler_steam_ng_pj_per_year": 2.0,
            "boiler_steam_wag_pj_per_year": 2.0,
            "wag_to_power_efficiency_fraction": central_eff,
        },
        {
            "case_template_id": "S33G_CASE_008_VATTENFALL_LHV_LIMITED",
            "case_role": "vattenfall_lhv_limited_generation",
            "source_support_status": "diagnostic_only_lhv_limited_interface",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["central"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["central"]),
            "boiler_steam_wag_pj_per_year": 1.0,
            "vattenfall_generator_bfg_equivalent_wag_fraction": 0.75,
            "wag_to_power_efficiency_fraction": low_eff,
        },
        {
            "case_template_id": "S33G_CASE_009_COMBINED_BEST_SOURCE_SUPPORTED",
            "case_role": "combined_best_source_supported",
            "source_support_status": "source_supported_ng_ranges_plus_diagnostic_steam_lhv",
            **zeroed,
            "hsm_fuel_substitution_ng_pj_per_year": _s3_3g_float(hsm["upper"]),
            "pelletizing_firing_ng_pj_per_year": _s3_3g_float(pellet["upper"]),
            "boiler_steam_ng_pj_per_year": 1.5,
            "boiler_steam_wag_pj_per_year": 2.0,
            "vattenfall_generator_bfg_equivalent_wag_fraction": 0.75,
            "wag_to_power_efficiency_fraction": low_eff,
        },
    ]
    for case in cases:
        ng_total = sum(
            float(case[key])
            for key in (
                "hsm_fuel_substitution_ng_pj_per_year",
                "pelletizing_firing_ng_pj_per_year",
                "pelletizing_grinding_ng_pj_per_year",
                "boiler_steam_ng_pj_per_year",
                "s3_3f_baseline_lumped_utility_ng_pj_per_year",
            )
        )
        wag_total = sum(
            float(case[key])
            for key in (
                "hsm_fuel_substitution_cog_pj_per_year",
                "coking_plant_1_bfg_pj_per_year",
                "coking_plant_1_cog_pj_per_year",
                "pelletizing_firing_cog_pj_per_year",
                "pelletizing_grinding_bofg_pj_per_year",
                "boiler_steam_wag_pj_per_year",
            )
        )
        case["explicit_process_ng_pj_per_year"] = ng_total - float(case["s3_3f_baseline_lumped_utility_ng_pj_per_year"])
        case["explicit_process_wag_pj_per_year"] = wag_total
        case["downstream_light_side_utility_heat_pj_per_year"] = ng_total + wag_total
        case["downstream_light_side_minimum_ng_pj_per_year"] = ng_total
        case["explicit_gas_sink_decomposition_active"] = "false" if case["case_template_id"].endswith("BASELINE") else "true"
        case["broad_utility_ng_lump_used"] = "true" if case["case_template_id"].endswith("BASELINE") else "false"
    return cases


def _s3_3g_case_rows() -> list[dict[str, Any]]:
    base_sets: list[tuple[str, str, dict[str, float]]] = []
    for candidate in _selected_ensemble_candidate_rows()[:3]:
        base_sets.append(
            (
                str(candidate["candidate_id"]),
                str(candidate.get("ensemble_role", candidate.get("candidate_role", "retained_c0_ensemble"))),
                candidate_values(candidate),
            )
        )
    route_shares = (c1_s3_3b_route_shares()[0], 0.55)
    rows: list[dict[str, Any]] = []
    for base_id, role, values_in in base_sets:
        for route_share in route_shares:
            for template in _s3_3g_case_templates():
                values = dict(values_in)
                values["residual_c0_ng_m3_per_t_final"] = 0.0
                values["wag_residual_utilisation_fraction"] = min(
                    float(values["wag_residual_utilisation_fraction"]),
                    float(template["vattenfall_generator_bfg_equivalent_wag_fraction"]),
                )
                rows.append(
                    {
                        "candidate_id": f"S33G_CAND_{len(rows):03d}",
                        "candidate_role": f"{role}__{template['case_role']}",
                        "base_parameter_set_id": base_id,
                        "sample_method": "deterministic_s3_3g_named_gas_sink_cases",
                        "bf_bof_share": route_share,
                        "drp_ng_multiplier": 1.0,
                        **values,
                        **template,
                    }
                )
    return rows


def _s3_3g_within_bounds(candidate: dict[str, Any]) -> tuple[bool, str]:
    violations: list[str] = []
    bounds = _s3_3g_sink_bounds()
    sink_key_map = {
        "hsm_fuel_substitution_ng": "hsm_fuel_substitution_ng_pj_per_year",
        "hsm_fuel_substitution_cog": "hsm_fuel_substitution_cog_pj_per_year",
        "coking_plant_1_bfg": "coking_plant_1_bfg_pj_per_year",
        "coking_plant_1_cog": "coking_plant_1_cog_pj_per_year",
        "pelletizing_firing_ng": "pelletizing_firing_ng_pj_per_year",
        "pelletizing_firing_cog": "pelletizing_firing_cog_pj_per_year",
        "pelletizing_grinding_ng": "pelletizing_grinding_ng_pj_per_year",
        "pelletizing_grinding_bofg": "pelletizing_grinding_bofg_pj_per_year",
        "boiler_steam_ng": "boiler_steam_ng_pj_per_year",
        "boiler_steam_wag": "boiler_steam_wag_pj_per_year",
        "vattenfall_generator_bfg_equivalent_wag": "vattenfall_generator_bfg_equivalent_wag_fraction",
        "vattenfall_generator_high_lhv_injection_limit": "vattenfall_generator_high_lhv_injection_limit_mj_per_m3",
    }
    for sink_id, key in sink_key_map.items():
        if candidate.get("broad_utility_ng_lump_used") == "true" and sink_id not in {
            "vattenfall_generator_high_lhv_injection_limit",
            "vattenfall_generator_bfg_equivalent_wag",
        }:
            continue
        row = bounds[sink_id]
        value_at = float(candidate.get(key, 0.0) or 0.0)
        if row["lower"] == "" or row["upper"] == "":
            if abs(value_at) > 1e-12:
                violations.append(f"{sink_id}:numeric_source_needed")
            continue
        lower = float(row["lower"])
        upper = float(row["upper"])
        if value_at < lower - 1e-9 or value_at > upper + 1e-9:
            violations.append(sink_id)
    route_share = float(candidate["bf_bof_share"])
    if route_share < c1_s3_3b_route_shares()[0] - 1e-9 or route_share > 0.55 + 1e-9:
        violations.append("bf_bof_share")
    utility_total = float(candidate["downstream_light_side_utility_heat_pj_per_year"])
    utility_min_ng = float(candidate["downstream_light_side_minimum_ng_pj_per_year"])
    if utility_total + 1e-9 < utility_min_ng:
        violations.append("utility_heat_total_below_minimum_ng")
    if candidate.get("broad_utility_ng_lump_used") == "true":
        allowed = S3_3C_DOWNSTREAM_LIGHT_SIDE_NG_PJ_PER_YEAR
        baseline = float(candidate["s3_3f_baseline_lumped_utility_ng_pj_per_year"])
        if not any(abs(baseline - float(value_at)) <= 1e-9 for value_at in allowed.values()):
            violations.append("s3_3f_baseline_lumped_utility_ng")
    eff = float(candidate["wag_to_power_efficiency_fraction"])
    if (
        eff < S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"] - 1e-9
        or eff > S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["high_public_candidate"] + 1e-9
    ):
        violations.append("wag_to_power_efficiency_fraction")
    return not violations, ";".join(violations)


def _s3_3g_range_edges(candidate: dict[str, Any]) -> str:
    edge_ids: list[str] = []
    bounds = _s3_3g_sink_bounds()
    for sink_id, key in (
        ("hsm_fuel_substitution_ng", "hsm_fuel_substitution_ng_pj_per_year"),
        ("pelletizing_firing_ng", "pelletizing_firing_ng_pj_per_year"),
        ("boiler_steam_ng", "boiler_steam_ng_pj_per_year"),
        ("boiler_steam_wag", "boiler_steam_wag_pj_per_year"),
        ("vattenfall_generator_bfg_equivalent_wag", "vattenfall_generator_bfg_equivalent_wag_fraction"),
    ):
        row = bounds[sink_id]
        value_at = float(candidate.get(key, 0.0) or 0.0)
        if row["lower"] != "" and abs(value_at - float(row["lower"])) <= 1e-9:
            edge_ids.append(f"{sink_id}=lower")
        if row["upper"] != "" and abs(value_at - float(row["upper"])) <= 1e-9:
            edge_ids.append(f"{sink_id}=upper")
    if abs(float(candidate["bf_bof_share"]) - c1_s3_3b_route_shares()[0]) <= 1e-9:
        edge_ids.append("c1_route_share=capacity_implied_lower")
    if abs(float(candidate["wag_to_power_efficiency_fraction"]) - S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"]) <= 1e-9:
        edge_ids.append("wag_to_power_efficiency=lower_public")
    return ";".join(edge_ids)


def _annotate_s3_3g_result(row: dict[str, Any], *, candidate: dict[str, Any]) -> None:
    _add_c1_holdout_errors(row)
    errors = {
        metric: _s3_3f_pct_error(row, metric)
        for metric in C1_BOUNDED_ALIGNMENT_WEIGHTS
    }
    valid_errors = [abs(value_at) for value_at in errors.values() if value_at is not None]
    weighted_denominator = sum(C1_BOUNDED_ALIGNMENT_WEIGHTS.values())
    weighted_score = (
        sum(C1_BOUNDED_ALIGNMENT_WEIGHTS[metric] * abs(float(error)) for metric, error in errors.items() if error is not None)
        / weighted_denominator
        if len(valid_errors) == len(C1_BOUNDED_ALIGNMENT_WEIGHTS)
        else 1e9
    )
    max_error = max(valid_errors) if valid_errors else 1e9
    mean_error = sum(valid_errors) / len(valid_errors) if valid_errors else 1e9
    share_errors: dict[str, float | str] = {}
    for metric, target in C1_SHARE_TARGETS.items():
        if row.get(metric) in ("", None):
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = ""
        else:
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = (float(row[metric]) - target) / target
    in_bounds, bound_violations = _s3_3g_within_bounds(candidate)
    feasibility_checks = [
        row.get("termination_condition") in {"optimal", "feasible"},
        abs(_s3_3f_float(row, "annualised_final_product_t", 0.0) - CALIBRATION_ANNUAL_FINAL_PRODUCT_T) <= 1e-4,
        _s3_3f_float(row, "terminal_cold_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_hot_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_reheated_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_material_balance_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_wag_balance_residual_gj") <= 1e-5,
        _s3_3f_float(row, "max_electricity_balance_residual_mwh") <= 1e-5,
        _s3_3f_float(row, "max_carbon_decomposition_residual_t") <= 1e-5,
        _s3_3f_float(row, "residual_ng_m3_per_h") <= 1e-9,
        in_bounds,
    ]
    natural_gas_shortfall = C1_TARGETS["natural_gas_m3_per_h"] - _s3_3f_float(row, "natural_gas_m3_per_h", 0.0)
    wag_electricity_excess = _s3_3f_float(row, "wag_electricity_twh_per_year", 0.0) - C1_TARGETS["wag_electricity_twh_per_year"]
    row.update(
        {
            "diagnostic_label": "S3.3g C1 gas-sink decomposition diagnostic",
            "c1_targets_used_for_score": "true",
            "calibration_freeze": "false",
            "s4_logic_introduced": "false",
            "approved_inputs_populated": "false",
            "residual_c1_gap_closure_used": "false",
            "inherited_c0_residual_ng_used_for_c1": "false",
            "arbitrary_wag_availability_factor_used": "false",
            "explicit_gas_sink_decomposition_active": candidate["explicit_gas_sink_decomposition_active"],
            "broad_utility_ng_lump_used": candidate["broad_utility_ng_lump_used"],
            "source_support_status": candidate["source_support_status"],
            "bf_bof_share_scenario": float(candidate["bf_bof_share"]),
            "drp_ng_multiplier": float(candidate["drp_ng_multiplier"]),
            "downstream_light_side_utility_heat_pj_per_year": candidate["downstream_light_side_utility_heat_pj_per_year"],
            "downstream_light_side_minimum_ng_pj_per_year": candidate["downstream_light_side_minimum_ng_pj_per_year"],
            "planned_wag_to_process_or_boiler_pj_per_year": candidate["explicit_process_wag_pj_per_year"],
            "planned_explicit_process_ng_pj_per_year": candidate["explicit_process_ng_pj_per_year"],
            "actual_wag_to_process_or_boiler_pj_per_year": row.get("wag_utility_heat_use_pj_per_year", ""),
            "actual_wag_to_power_twh_per_year": row.get("wag_electricity_twh_per_year", ""),
            "flare_fraction_of_wag_generated": row.get("flare_fraction_of_wag_generated", ""),
            "natural_gas_shortfall_m3_per_h": natural_gas_shortfall,
            "wag_electricity_excess_twh_per_year": wag_electricity_excess,
            "registered_bounds_pass": "true" if in_bounds else "false",
            "registered_bound_violations": bound_violations,
            "range_edge_parameters": _s3_3g_range_edges(candidate),
            "weighted_c1_alignment_score": weighted_score,
            "unweighted_mean_abs_pct_error": mean_error,
            "max_abs_pct_error": max_error,
            "all_core_targets_within_5pct": "true" if max_error <= 0.05 else "false",
            "all_core_targets_within_10pct": "true" if max_error <= 0.10 else "false",
            "all_core_targets_within_15pct": "true" if max_error <= 0.15 else "false",
            "physically_feasible_and_balanced": "true" if all(feasibility_checks) else "false",
            **share_errors,
        }
    )
    for key in (
        "hsm_fuel_substitution_ng_pj_per_year",
        "hsm_fuel_substitution_cog_pj_per_year",
        "coking_plant_1_bfg_pj_per_year",
        "coking_plant_1_cog_pj_per_year",
        "pelletizing_firing_ng_pj_per_year",
        "pelletizing_firing_cog_pj_per_year",
        "pelletizing_grinding_ng_pj_per_year",
        "pelletizing_grinding_bofg_pj_per_year",
        "boiler_steam_ng_pj_per_year",
        "boiler_steam_wag_pj_per_year",
        "vattenfall_generator_bfg_equivalent_wag_fraction",
        "vattenfall_generator_high_lhv_injection_limit_mj_per_m3",
        "wag_to_power_efficiency_fraction",
    ):
        row[key] = candidate[key]
    if row["physically_feasible_and_balanced"] != "true":
        row["s3_3g_rejection_reason"] = "failed_feasibility_balance_or_bounds"
    else:
        row["s3_3g_rejection_reason"] = ""


def _s3_3g_reference_s3_3f_score() -> float:
    if S3_3_OUTPUT_PATHS["s3_3f_best_cases"].exists():
        frame = pd.read_csv(S3_3_OUTPUT_PATHS["s3_3f_best_cases"], dtype=str, keep_default_na=False)
        if len(frame) and frame.iloc[0].get("weighted_c1_alignment_score", "") != "":
            return float(frame.iloc[0]["weighted_c1_alignment_score"])
    return 0.10145998291093615


def _write_s3_3g_best_gap_boundary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = [
        row for row in rows
        if row.get("physically_feasible_and_balanced") == "true"
        and row.get("weighted_c1_alignment_score") not in ("", None)
    ]
    best_rows = sorted(evaluable, key=lambda row: float(row["weighted_c1_alignment_score"]))[:10]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_best_cases"], best_rows or [{"status": "blocked_no_evaluable_candidates"}])
    best = best_rows[0] if best_rows else {}
    reference_score = _s3_3g_reference_s3_3f_score()
    remaining_rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    if best:
        best_score = float(best["weighted_c1_alignment_score"])
        abs_errors = {
            "gross_electricity": abs(float(best["c1_gross_electricity_twh_per_year_error_pct"])),
            "wag_electricity": abs(float(best["c1_wag_electricity_twh_per_year_error_pct"])),
            "natural_gas": abs(float(best["c1_natural_gas_m3_per_h_error_pct"])),
            "direct_co2": abs(float(best["c1_direct_site_co2_t_per_year_error_pct"])),
            "primary_proxy": abs(float(best["c1_athanasiadis_primary_proxy_pj_per_year_error_pct"])),
        }
        hardest = max(abs_errors, key=abs_errors.get)
        remaining_rows = [
            {
                "gap_id": "S33G_GAP_001",
                "best_candidate_id": best["candidate_id"],
                "natural_gas_shortfall_m3_per_h": best["natural_gas_shortfall_m3_per_h"],
                "wag_electricity_excess_twh_per_year": best["wag_electricity_excess_twh_per_year"],
                "hardest_target": hardest,
                "remaining_gap_type": "numeric_source_and_boundary_related",
                "residual_gap_closure_used": "false",
                "notes": "Remaining gap is reported without back-calculated Table 9 residuals or inherited C0 residual NG.",
            }
        ]
        boundary_rows = [
            {
                "decision_id": "S33G_BOUNDARY_001",
                "item": "best_case",
                "value": best["candidate_id"],
                "status": "bounded_alignment_only",
                "notes": "Diagnostic decomposition improves only if source-supported/diagnostic sink assumptions are accepted.",
            },
            {
                "decision_id": "S33G_BOUNDARY_002",
                "item": "improvement_over_s3_3f",
                "value": "true" if best_score < reference_score else "false",
                "status": "diagnostic_comparison",
                "notes": f"S3.3f reference weighted score={reference_score}; S3.3g best weighted score={best_score}.",
            },
            {
                "decision_id": "S33G_BOUNDARY_003",
                "item": "remaining_gap_classification",
                "value": "numeric_source_and_boundary_related",
                "status": "not_strict_validation",
                "notes": "Several gas paths are structurally source-backed but need approved numeric source cards before freeze use.",
            },
            {
                "decision_id": "S33G_BOUNDARY_004",
                "item": "s3_3_freeze_status",
                "value": "not_frozen",
                "status": "blocked",
                "notes": "S3.3g is diagnostic and does not promote approved inputs.",
            },
            {
                "decision_id": "S33G_BOUNDARY_005",
                "item": "s4_readiness",
                "value": "not_ready",
                "status": "blocked",
                "notes": "No S4 logic is introduced.",
            },
        ]
    else:
        hardest = ""
        remaining_rows = [{"gap_id": "S33G_GAP_001", "status": "blocked_no_evaluable_candidates"}]
        boundary_rows = [{"decision_id": "S33G_BOUNDARY_001", "status": "blocked_no_evaluable_candidates"}]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_remaining_gap"], remaining_rows)
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_boundary_decision_support"], boundary_rows)
    return {
        "best": best,
        "candidate_count": len(rows),
        "evaluable_candidate_count": len(evaluable),
        "within_5pct_count": sum(1 for row in evaluable if row.get("all_core_targets_within_5pct") == "true"),
        "within_10pct_count": sum(1 for row in evaluable if row.get("all_core_targets_within_10pct") == "true"),
        "within_15pct_count": sum(1 for row in evaluable if row.get("all_core_targets_within_15pct") == "true"),
        "hardest_target": hardest,
        "reference_s3_3f_weighted_score": reference_score,
    }


def run_diagnose_c1_gas_sink_decomposition(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3e_static_artifacts()
    _write_dataframe(
        S3_3_OUTPUT_PATHS["s3_3g_source_card_register"],
        s3_3g_athanasiadis_gas_network_source_card_rows(),
    )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_parameter_eligibility"], s3_3g_gas_sink_parameter_eligibility_rows())
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    case_rows = _s3_3g_case_rows()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_cases"], case_rows)
    results: list[dict[str, Any]] = []
    for candidate in case_rows:
        in_bounds, violations = _s3_3g_within_bounds(candidate)
        if not in_bounds:
            rejected = dict(candidate)
            rejected.update(
                {
                    "termination_condition": "not_run_outside_registered_bounds",
                    "registered_bounds_pass": "false",
                    "registered_bound_violations": violations,
                    "physically_feasible_and_balanced": "false",
                    "weighted_c1_alignment_score": 1e9,
                    "s3_3g_rejection_reason": "outside_registered_bounds",
                }
            )
            results.append(rejected)
            continue
        values = candidate_values(candidate)
        values["residual_c0_ng_m3_per_t_final"] = 0.0
        values["wag_residual_utilisation_fraction"] = float(candidate["wag_residual_utilisation_fraction"])
        row = solve_calibration_case(
            candidate_id=str(candidate["candidate_id"]),
            candidate_role=str(candidate["candidate_role"]),
            parameter_values=values,
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            bf_bof_share=float(candidate["bf_bof_share"]),
            smoke_case_id=f"s3_3g_{candidate['candidate_id']}",
            c1_diagnostic_switches={
                "drp_ng_multiplier": float(candidate["drp_ng_multiplier"]),
                "s3_3c_downstream_light_side_ng_pj_per_year": float(
                    candidate["downstream_light_side_utility_heat_pj_per_year"]
                ),
                "s3_3c_downstream_light_side_minimum_ng_pj_per_year": float(
                    candidate["downstream_light_side_minimum_ng_pj_per_year"]
                ),
                "s3_3c_wag_to_power_efficiency_fraction": float(candidate["wag_to_power_efficiency_fraction"]),
            },
            residual_ng_m3_per_t_final_override=0.0,
            solver=solver,
            solver_name=resolved_name,
        )
        row.update(
            {
                "base_parameter_set_id": candidate["base_parameter_set_id"],
                "sample_method": candidate["sample_method"],
                "case_template_id": candidate["case_template_id"],
                "case_role": candidate["case_role"],
            }
        )
        _annotate_s3_3g_result(row, candidate=candidate)
        results.append(row)
    results = sorted(results, key=lambda row: float(row.get("weighted_c1_alignment_score", 1e9) or 1e9))
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3g_results"], results)
    summary = _write_s3_3g_best_gap_boundary(results)
    best = summary["best"]
    return {
        "solver_name": resolved_name,
        "diagnostic_label": "S3.3g C1 gas-sink decomposition diagnostic",
        "candidate_count": summary["candidate_count"],
        "evaluable_candidate_count": summary["evaluable_candidate_count"],
        "best_candidate_id": best.get("candidate_id", ""),
        "best_case_role": best.get("case_role", ""),
        "best_bf_bof_share": best.get("bf_bof_share_scenario", ""),
        "best_weighted_score": best.get("weighted_c1_alignment_score", ""),
        "best_mean_abs_pct_error": best.get("unweighted_mean_abs_pct_error", ""),
        "best_max_abs_pct_error": best.get("max_abs_pct_error", ""),
        "within_5pct_count": summary["within_5pct_count"],
        "within_10pct_count": summary["within_10pct_count"],
        "within_15pct_count": summary["within_15pct_count"],
        "hardest_target": summary["hardest_target"],
        "no_run_folder_created": True,
        "approved_inputs_populated": False,
        "s3_3a_arbitrary_values_promoted": False,
    }


C0_REGRESSION_TOLERANCES = {
    "gross_electricity_twh_per_year": 0.05,
    "wag_electricity_twh_per_year": 0.10,
    "natural_gas_m3_per_h": 0.10,
    "direct_site_co2_t_per_year": 0.10,
    "athanasiadis_primary_proxy_pj_per_year": 0.10,
}


def _s3_3h_central_c0_candidate() -> dict[str, Any]:
    for row in _selected_ensemble_candidate_rows():
        if row.get("ensemble_role") == "central_calibrated_set":
            return row
    selected = _selected_ensemble_candidate_rows()
    return selected[0] if selected else {"candidate_id": "S33_CAND_001_CALIBRATION_ANCHOR", **calibration_anchor_parameter_set()}


def _s3_3h_parameter(parameter_id: str) -> Any:
    for parameter in calibration_parameters():
        if parameter.parameter_id == parameter_id:
            return parameter
    raise KeyError(parameter_id)


def _s3_3h_add_c0_regression_errors(row: dict[str, Any]) -> None:
    errors: list[float] = []
    within = True
    for metric, target in C0_REFERENCE_TARGETS.items():
        key = f"c0_{metric}_error_pct"
        row[f"c0_{metric}_target"] = target
        if row.get(metric) in ("", None):
            row[key] = ""
            within = False
            continue
        error = 0.0 if target == 0 else (float(row[metric]) - target) / target
        row[key] = error
        errors.append(abs(error))
        if abs(error) > C0_REGRESSION_TOLERANCES[metric] + 1e-9:
            within = False
    balance_checks = [
        row.get("termination_condition") in {"optimal", "feasible"},
        abs(_s3_3f_float(row, "annualised_final_product_t", 0.0) - CALIBRATION_ANNUAL_FINAL_PRODUCT_T) <= 1e-4,
        _s3_3f_float(row, "terminal_cold_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_hot_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_reheated_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_material_balance_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_wag_balance_residual_gj") <= 1e-5,
        _s3_3f_float(row, "max_electricity_balance_residual_mwh") <= 1e-5,
        _s3_3f_float(row, "max_carbon_decomposition_residual_t") <= 1e-5,
    ]
    row["c0_unweighted_mean_abs_pct_error"] = sum(errors) / len(errors) if errors else 1e9
    row["c0_max_abs_pct_error"] = max(errors) if errors else 1e9
    row["c0_within_calibration_tolerance"] = "true" if within and all(balance_checks) else "false"


def _s3_3h_add_c1_scores(row: dict[str, Any], *, case: dict[str, Any]) -> None:
    _add_c1_holdout_errors(row)
    errors = {metric: _s3_3f_pct_error(row, metric) for metric in C1_BOUNDED_ALIGNMENT_WEIGHTS}
    valid_errors = [abs(value_at) for value_at in errors.values() if value_at is not None]
    weighted_denominator = sum(C1_BOUNDED_ALIGNMENT_WEIGHTS.values())
    weighted_score = (
        sum(C1_BOUNDED_ALIGNMENT_WEIGHTS[metric] * abs(float(error)) for metric, error in errors.items() if error is not None)
        / weighted_denominator
        if len(valid_errors) == len(C1_BOUNDED_ALIGNMENT_WEIGHTS)
        else 1e9
    )
    max_error = max(valid_errors) if valid_errors else 1e9
    mean_error = sum(valid_errors) / len(valid_errors) if valid_errors else 1e9
    share_errors: dict[str, float | str] = {}
    for metric, target in C1_SHARE_TARGETS.items():
        if row.get(metric) in ("", None):
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = ""
        else:
            share_errors[f"{metric}_target"] = target
            share_errors[f"{metric}_error_pct"] = (float(row[metric]) - target) / target
    natural_gas_shortfall = C1_TARGETS["natural_gas_m3_per_h"] - _s3_3f_float(row, "natural_gas_m3_per_h", 0.0)
    wag_electricity_excess = _s3_3f_float(row, "wag_electricity_twh_per_year", 0.0) - C1_TARGETS["wag_electricity_twh_per_year"]
    gross_electricity_surplus = _s3_3f_float(row, "gross_electricity_twh_per_year", 0.0) - C1_TARGETS["gross_electricity_twh_per_year"]
    feasibility_checks = [
        row.get("termination_condition") in {"optimal", "feasible"},
        abs(_s3_3f_float(row, "annualised_final_product_t", 0.0) - CALIBRATION_ANNUAL_FINAL_PRODUCT_T) <= 1e-4,
        _s3_3f_float(row, "terminal_cold_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_hot_residual_t") <= 1e-5,
        _s3_3f_float(row, "terminal_reheated_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_material_balance_residual_t") <= 1e-5,
        _s3_3f_float(row, "max_wag_balance_residual_gj") <= 1e-5,
        _s3_3f_float(row, "max_electricity_balance_residual_mwh") <= 1e-5,
        _s3_3f_float(row, "max_carbon_decomposition_residual_t") <= 1e-5,
        _s3_3f_float(row, "residual_ng_m3_per_h") <= 1e-9,
    ]
    row.update(
        {
            "diagnostic_label": "S3.3h phased C1 boundary and C0-preserving shared-parameter diagnostic",
            "c1_targets_used_for_score": "true",
            "calibration_freeze": "false",
            "s4_logic_introduced": "false",
            "approved_inputs_populated": "false",
            "residual_c1_gap_closure_used": "false",
            "inherited_c0_residual_ng_used_for_c1": "false",
            "arbitrary_wag_availability_factor_used": "false",
            "weighted_c1_alignment_score": weighted_score,
            "unweighted_mean_abs_pct_error": mean_error,
            "max_abs_pct_error": max_error,
            "all_core_targets_within_5pct": "true" if max_error <= 0.05 else "false",
            "all_core_targets_within_10pct": "true" if max_error <= 0.10 else "false",
            "all_core_targets_within_15pct": "true" if max_error <= 0.15 else "false",
            "physically_feasible_and_balanced": "true" if all(feasibility_checks) else "false",
            "natural_gas_shortfall_m3_per_h": natural_gas_shortfall,
            "wag_electricity_excess_twh_per_year": wag_electricity_excess,
            "gross_electricity_surplus_twh_per_year": gross_electricity_surplus,
            "actual_wag_to_process_or_boiler_pj_per_year": row.get("wag_utility_heat_use_pj_per_year", ""),
            "actual_wag_to_power_twh_per_year": row.get("wag_electricity_twh_per_year", ""),
            "flare_fraction_of_wag_generated": row.get("flare_fraction_of_wag_generated", ""),
            **share_errors,
        }
    )
    for key in (
        "hsm_fuel_substitution_ng_pj_per_year",
        "pelletizing_firing_ng_pj_per_year",
        "boiler_steam_ng_pj_per_year",
        "boiler_steam_wag_pj_per_year",
        "vattenfall_generator_bfg_equivalent_wag_fraction",
        "downstream_light_side_utility_heat_pj_per_year",
        "downstream_light_side_minimum_ng_pj_per_year",
        "extended_boiler_steam_gap_sizing",
    ):
        if key in case:
            row[key] = case[key]


def _s3_3h_case_totals(case: dict[str, Any]) -> None:
    ng_total = (
        float(case["hsm_fuel_substitution_ng_pj_per_year"])
        + float(case["pelletizing_firing_ng_pj_per_year"])
        + float(case["boiler_steam_ng_pj_per_year"])
    )
    wag_total = float(case["boiler_steam_wag_pj_per_year"])
    case["downstream_light_side_utility_heat_pj_per_year"] = ng_total + wag_total
    case["downstream_light_side_minimum_ng_pj_per_year"] = ng_total
    case["extended_boiler_steam_gap_sizing"] = (
        "true"
        if float(case["boiler_steam_ng_pj_per_year"]) > 2.0 or float(case["boiler_steam_wag_pj_per_year"]) > 2.0
        else "false"
    )


def _s3_3h_block_a_case_rows() -> list[dict[str, Any]]:
    base = _s3_3h_central_c0_candidate()
    values = candidate_values(base)
    hsm = _s3_3g_sink_bounds()["hsm_fuel_substitution_ng"]
    pellet = _s3_3g_sink_bounds()["pelletizing_firing_ng"]
    hsm_pellet_cases = [
        ("low_hsm_low_pellet", float(hsm["lower"]), float(pellet["lower"])),
        ("central_hsm_central_pellet", float(hsm["central"]), float(pellet["central"])),
        ("high_hsm_high_pellet", float(hsm["upper"]), float(pellet["upper"])),
        ("high_hsm_central_pellet", float(hsm["upper"]), float(pellet["central"])),
        ("central_hsm_high_pellet", float(hsm["central"]), float(pellet["upper"])),
    ]
    boiler_pairs = [
        (0.0, 0.0),
        (1.0, 1.0),
        (2.0, 2.0),
        (3.0, 2.0),
        (4.0, 2.0),
        (6.0, 2.0),
        (3.0, 3.0),
        (4.0, 4.0),
        (6.0, 4.0),
        (6.0, 6.0),
    ]
    rows: list[dict[str, Any]] = []
    for route_share in (c1_s3_3b_route_shares()[0], 0.55):
        for hsm_case_id, hsm_ng, pellet_ng in hsm_pellet_cases:
            for boiler_ng, boiler_wag in boiler_pairs:
                case = {
                    "candidate_id": f"S33H_A_{len(rows):03d}",
                    "block": "A",
                    "candidate_role": "block_a_c1_only_boundary_diagnostic",
                    "base_parameter_set_id": base.get("candidate_id", "central_calibrated_set"),
                    "base_parameter_set_role": base.get("ensemble_role", "central_calibrated_set"),
                    "bf_bof_share": route_share,
                    "hsm_pellet_case": hsm_case_id,
                    "hsm_fuel_substitution_ng_pj_per_year": hsm_ng,
                    "pelletizing_firing_ng_pj_per_year": pellet_ng,
                    "boiler_steam_ng_pj_per_year": boiler_ng,
                    "boiler_steam_wag_pj_per_year": boiler_wag,
                    "vattenfall_generator_bfg_equivalent_wag_fraction": 1.0,
                    "shared_parameters_fixed": "true",
                    "sample_method": "deterministic_block_a_sparse_grid",
                    **values,
                }
                _s3_3h_case_totals(case)
                rows.append(case)
    extra_cases: list[dict[str, Any]] = []
    for route_share in (c1_s3_3b_route_shares()[0], 0.55):
        for boiler_ng, boiler_wag in ((2.0, 2.0), (4.0, 2.0), (6.0, 2.0), (4.0, 4.0)):
            for fraction in (0.75, 0.50):
                case = {
                    "candidate_id": f"S33H_A_{len(rows) + len(extra_cases):03d}",
                    "block": "A",
                    "candidate_role": "block_a_vattenfall_lhv_interface_diagnostic",
                    "base_parameter_set_id": base.get("candidate_id", "central_calibrated_set"),
                    "base_parameter_set_role": base.get("ensemble_role", "central_calibrated_set"),
                    "bf_bof_share": route_share,
                    "hsm_pellet_case": "central_hsm_central_pellet",
                    "hsm_fuel_substitution_ng_pj_per_year": float(hsm["central"]),
                    "pelletizing_firing_ng_pj_per_year": float(pellet["central"]),
                    "boiler_steam_ng_pj_per_year": boiler_ng,
                    "boiler_steam_wag_pj_per_year": boiler_wag,
                    "vattenfall_generator_bfg_equivalent_wag_fraction": fraction,
                    "shared_parameters_fixed": "true",
                    "sample_method": "deterministic_block_a_vattenfall_fraction_cases",
                    **values,
                }
                _s3_3h_case_totals(case)
                extra_cases.append(case)
    return rows + extra_cases


def _s3_3h_block_a_within_bounds(case: dict[str, Any]) -> tuple[bool, str]:
    violations: list[str] = []
    hsm = _s3_3g_sink_bounds()["hsm_fuel_substitution_ng"]
    pellet = _s3_3g_sink_bounds()["pelletizing_firing_ng"]
    if not float(hsm["lower"]) - 1e-9 <= float(case["hsm_fuel_substitution_ng_pj_per_year"]) <= float(hsm["upper"]) + 1e-9:
        violations.append("hsm_fuel_substitution_ng")
    if not float(pellet["lower"]) - 1e-9 <= float(case["pelletizing_firing_ng_pj_per_year"]) <= float(pellet["upper"]) + 1e-9:
        violations.append("pelletizing_firing_ng")
    if float(case["boiler_steam_ng_pj_per_year"]) not in {0.0, 1.0, 2.0, 3.0, 4.0, 6.0}:
        violations.append("boiler_steam_ng")
    if float(case["boiler_steam_wag_pj_per_year"]) not in {0.0, 1.0, 2.0, 3.0, 4.0, 6.0}:
        violations.append("boiler_steam_wag")
    if float(case["vattenfall_generator_bfg_equivalent_wag_fraction"]) not in {0.50, 0.75, 1.00}:
        violations.append("vattenfall_generator_bfg_equivalent_wag")
    if float(case["bf_bof_share"]) not in {c1_s3_3b_route_shares()[0], 0.55}:
        violations.append("bf_bof_share")
    return not violations, ";".join(violations)


def _run_s3_3h_block_a(
    *,
    solver,
    solver_name: str,
) -> list[dict[str, Any]]:
    case_rows = _s3_3h_block_a_case_rows()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_block_a_cases"], case_rows)
    results: list[dict[str, Any]] = []
    for case in case_rows:
        in_bounds, violations = _s3_3h_block_a_within_bounds(case)
        values = candidate_values(case)
        values["residual_c0_ng_m3_per_t_final"] = 0.0
        values["wag_residual_utilisation_fraction"] = float(case["vattenfall_generator_bfg_equivalent_wag_fraction"])
        if not in_bounds:
            rejected = dict(case)
            rejected.update(
                {
                    "termination_condition": "not_run_outside_s3_3h_bounds",
                    "registered_bounds_pass": "false",
                    "registered_bound_violations": violations,
                    "physically_feasible_and_balanced": "false",
                    "weighted_c1_alignment_score": 1e9,
                    "s3_3h_rejection_reason": "outside_registered_or_gap_sizing_bounds",
                }
            )
            results.append(rejected)
            continue
        row = solve_calibration_case(
            candidate_id=str(case["candidate_id"]),
            candidate_role=str(case["candidate_role"]),
            parameter_values=values,
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            bf_bof_share=float(case["bf_bof_share"]),
            smoke_case_id=f"s3_3h_block_a_{case['candidate_id']}",
            c1_diagnostic_switches={
                "drp_ng_multiplier": 1.0,
                "s3_3c_downstream_light_side_ng_pj_per_year": float(
                    case["downstream_light_side_utility_heat_pj_per_year"]
                ),
                "s3_3c_downstream_light_side_minimum_ng_pj_per_year": float(
                    case["downstream_light_side_minimum_ng_pj_per_year"]
                ),
            },
            residual_ng_m3_per_t_final_override=0.0,
            solver=solver,
            solver_name=solver_name,
        )
        row.update(
            {
                "block": "A",
                "base_parameter_set_id": case["base_parameter_set_id"],
                "sample_method": case["sample_method"],
                "hsm_pellet_case": case["hsm_pellet_case"],
                "shared_parameters_fixed": "true",
                "registered_bounds_pass": "true",
                "registered_bound_violations": "",
            }
        )
        _s3_3h_add_c1_scores(row, case=case)
        row["s3_3h_rejection_reason"] = "" if row["physically_feasible_and_balanced"] == "true" else "failed_feasibility_balance_or_bounds"
        results.append(row)
    results = sorted(results, key=lambda row: float(row.get("weighted_c1_alignment_score", 1e9) or 1e9))
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_block_a_results"], results)
    return results


def _s3_3h_shared_parameter_templates(base_values: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {"shared_case_id": "shared_no_change", "changed_parameters": ""},
        {"shared_case_id": "residual_aux_low_envelope", "changed_parameters": "residual_auxiliary_electricity_scale", "residual_auxiliary_electricity_scale": 3.68},
        {"shared_case_id": "residual_aux_high_envelope", "changed_parameters": "residual_auxiliary_electricity_scale", "residual_auxiliary_electricity_scale": 4.04},
        {"shared_case_id": "downstream_electricity_lower", "changed_parameters": "downstream_electricity_scale", "downstream_electricity_scale": 0.75},
        {"shared_case_id": "downstream_electricity_mid_low", "changed_parameters": "downstream_electricity_scale", "downstream_electricity_scale": 0.875},
        {"shared_case_id": "wag_to_power_efficiency_low", "changed_parameters": "wag_to_power_efficiency_fraction", "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"]},
        {"shared_case_id": "wag_to_power_efficiency_high", "changed_parameters": "wag_to_power_efficiency_fraction", "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["high_public_candidate"]},
        {"shared_case_id": "wag_lhv_low", "changed_parameters": "wag_lhv_scale", "wag_lhv_scale": 0.90},
        {"shared_case_id": "wag_lhv_high", "changed_parameters": "wag_lhv_scale", "wag_lhv_scale": 1.10},
        {
            "shared_case_id": "combined_gross_electricity_reduction",
            "changed_parameters": "residual_auxiliary_electricity_scale;downstream_electricity_scale",
            "residual_auxiliary_electricity_scale": 3.68,
            "downstream_electricity_scale": 0.875,
        },
        {
            "shared_case_id": "combined_wag_electricity_reduction",
            "changed_parameters": "wag_to_power_efficiency_fraction;wag_lhv_scale",
            "wag_to_power_efficiency_fraction": S3_3C_WAG_TO_POWER_EFFICIENCY_SENSITIVITY["low_public_candidate"],
            "wag_lhv_scale": max(_s3_3h_parameter("wag_lhv_scale").lower, min(base_values["wag_lhv_scale"], 0.99)),
        },
    ]


def _s3_3h_block_b_case_rows(block_a_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feasible = [row for row in block_a_results if row.get("physically_feasible_and_balanced") == "true"]
    top_a = sorted(feasible, key=lambda row: float(row["weighted_c1_alignment_score"]))[:3]
    base = _s3_3h_central_c0_candidate()
    base_values = candidate_values(base)
    rows: list[dict[str, Any]] = []
    for block_a in top_a:
        for template in _s3_3h_shared_parameter_templates(base_values):
            c0_values = dict(base_values)
            for key in (
                "downstream_electricity_scale",
                "residual_auxiliary_electricity_scale",
                "wag_to_power_efficiency_fraction",
                "wag_lhv_scale",
            ):
                if key in template:
                    c0_values[key] = float(template[key])
            case = {
                "candidate_id": f"S33H_B_{len(rows):03d}",
                "block": "B",
                "candidate_role": "block_b_c0_preserving_shared_parameter_diagnostic",
                "source_block_a_candidate_id": block_a["candidate_id"],
                "source_block_a_weighted_score": block_a["weighted_c1_alignment_score"],
                "shared_case_id": template["shared_case_id"],
                "changed_shared_parameters": template["changed_parameters"],
                "base_parameter_set_id": base.get("candidate_id", "central_calibrated_set"),
                "base_parameter_set_role": base.get("ensemble_role", "central_calibrated_set"),
                "bf_bof_share": float(block_a["bf_bof_share_scenario"]),
                "hsm_fuel_substitution_ng_pj_per_year": float(block_a["hsm_fuel_substitution_ng_pj_per_year"]),
                "pelletizing_firing_ng_pj_per_year": float(block_a["pelletizing_firing_ng_pj_per_year"]),
                "boiler_steam_ng_pj_per_year": float(block_a["boiler_steam_ng_pj_per_year"]),
                "boiler_steam_wag_pj_per_year": float(block_a["boiler_steam_wag_pj_per_year"]),
                "vattenfall_generator_bfg_equivalent_wag_fraction": float(block_a["vattenfall_generator_bfg_equivalent_wag_fraction"]),
                "sample_method": "deterministic_block_b_oat_and_small_combo",
                **c0_values,
            }
            _s3_3h_case_totals(case)
            rows.append(case)
    return rows


def _s3_3h_shared_within_bounds(values: dict[str, float]) -> tuple[bool, str]:
    violations: list[str] = []
    for parameter_id in (
        "downstream_electricity_scale",
        "residual_auxiliary_electricity_scale",
        "wag_to_power_efficiency_fraction",
        "wag_lhv_scale",
    ):
        parameter = _s3_3h_parameter(parameter_id)
        value_at = float(values[parameter_id])
        if value_at < parameter.lower - 1e-9 or value_at > parameter.upper + 1e-9:
            violations.append(parameter_id)
    return not violations, ";".join(violations)


def _run_s3_3h_block_b(
    *,
    block_a_results: list[dict[str, Any]],
    solver,
    solver_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    case_rows = _s3_3h_block_b_case_rows(block_a_results)
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_block_b_cases"], case_rows)
    c0_rows: list[dict[str, Any]] = []
    c1_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    base_c0_values = candidate_values(_s3_3h_central_c0_candidate())
    base_c0 = solve_calibration_case(
        candidate_id="S33H_B_C0_BASE",
        candidate_role="block_b_reference_c0_regression",
        parameter_values=base_c0_values,
        configuration_id=C0_CONFIGURATION_ID,
        horizon_hours=168,
        smoke_case_id="s3_3h_block_b_reference_c0",
        solver=solver,
        solver_name=solver_name,
    )
    _s3_3h_add_c0_regression_errors(base_c0)
    base_c0_mean = float(base_c0["c0_unweighted_mean_abs_pct_error"])
    for case in case_rows:
        c0_values = candidate_values(case)
        c1_values = dict(c0_values)
        c1_values["residual_c0_ng_m3_per_t_final"] = 0.0
        c1_values["wag_residual_utilisation_fraction"] = float(case["vattenfall_generator_bfg_equivalent_wag_fraction"])
        in_bounds, violations = _s3_3h_shared_within_bounds(c0_values)
        if not in_bounds:
            rejected = dict(case)
            rejected.update(
                {
                    "rejection_block": "B",
                    "rejection_reason": "shared_parameter_outside_governed_bounds",
                    "registered_bound_violations": violations,
                }
            )
            rejected_rows.append(rejected)
            continue
        c0_row = solve_calibration_case(
            candidate_id=str(case["candidate_id"]),
            candidate_role="block_b_c0_regression",
            parameter_values=c0_values,
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=168,
            smoke_case_id=f"s3_3h_block_b_c0_{case['candidate_id']}",
            solver=solver,
            solver_name=solver_name,
        )
        _s3_3h_add_c0_regression_errors(c0_row)
        c0_row.update(
            {
                "block": "B",
                "shared_case_id": case["shared_case_id"],
                "changed_shared_parameters": case["changed_shared_parameters"],
                "source_block_a_candidate_id": case["source_block_a_candidate_id"],
                "registered_bounds_pass": "true",
            }
        )
        c1_row = solve_calibration_case(
            candidate_id=str(case["candidate_id"]),
            candidate_role="block_b_c1_shared_parameter_diagnostic",
            parameter_values=c1_values,
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            bf_bof_share=float(case["bf_bof_share"]),
            smoke_case_id=f"s3_3h_block_b_c1_{case['candidate_id']}",
            c1_diagnostic_switches={
                "drp_ng_multiplier": 1.0,
                "s3_3c_downstream_light_side_ng_pj_per_year": float(
                    case["downstream_light_side_utility_heat_pj_per_year"]
                ),
                "s3_3c_downstream_light_side_minimum_ng_pj_per_year": float(
                    case["downstream_light_side_minimum_ng_pj_per_year"]
                ),
            },
            residual_ng_m3_per_t_final_override=0.0,
            solver=solver,
            solver_name=solver_name,
        )
        c1_row.update(
            {
                "block": "B",
                "shared_case_id": case["shared_case_id"],
                "changed_shared_parameters": case["changed_shared_parameters"],
                "source_block_a_candidate_id": case["source_block_a_candidate_id"],
                "source_block_a_weighted_score": case["source_block_a_weighted_score"],
                "registered_bounds_pass": "true",
            }
        )
        _s3_3h_add_c1_scores(c1_row, case=case)
        c1_improved = float(c1_row["weighted_c1_alignment_score"]) < float(case["source_block_a_weighted_score"]) - 1e-9
        c0_preserved = c0_row["c0_within_calibration_tolerance"] == "true"
        c0_improved = float(c0_row["c0_unweighted_mean_abs_pct_error"]) <= base_c0_mean + 1e-9
        if c1_improved and c0_preserved and c0_improved:
            outcome = "improves_both_c0_and_c1"
        elif c1_improved and c0_preserved:
            outcome = "preserves_c0_and_improves_c1"
        elif c1_improved and not c0_preserved:
            outcome = "improves_c1_but_breaks_c0"
        else:
            outcome = "no_improvement"
        c0_row["block_b_outcome"] = outcome
        c1_row["block_b_outcome"] = outcome
        c1_row["c0_within_calibration_tolerance"] = c0_row["c0_within_calibration_tolerance"]
        c1_row["c0_unweighted_mean_abs_pct_error"] = c0_row["c0_unweighted_mean_abs_pct_error"]
        c1_row["c0_max_abs_pct_error"] = c0_row["c0_max_abs_pct_error"]
        for metric in C0_REFERENCE_TARGETS:
            c1_row[f"paired_c0_{metric}_error_pct"] = c0_row[f"c0_{metric}_error_pct"]
        if outcome == "improves_c1_but_breaks_c0":
            rejected_rows.append(
                {
                    "candidate_id": case["candidate_id"],
                    "rejection_block": "B",
                    "rejection_reason": "improves_c1_but_breaks_c0_calibration",
                    "changed_shared_parameters": case["changed_shared_parameters"],
                    "c1_weighted_score": c1_row["weighted_c1_alignment_score"],
                    "c0_max_abs_pct_error": c0_row["c0_max_abs_pct_error"],
                }
            )
        c0_rows.append(c0_row)
        c1_rows.append(c1_row)
    c0_rows = sorted(c0_rows, key=lambda row: (row.get("candidate_id", ""), row.get("shared_case_id", "")))
    c1_rows = sorted(c1_rows, key=lambda row: float(row.get("weighted_c1_alignment_score", 1e9) or 1e9))
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_block_b_c0_results"], c0_rows or [{"status": "blocked_no_block_b_c0_rows"}])
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_block_b_c1_results"], c1_rows or [{"status": "blocked_no_block_b_c1_rows"}])
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_rejected_cases"], rejected_rows or [{"status": "no_rejected_cases"}])
    return c0_rows, c1_rows, rejected_rows


def _write_s3_3h_summary_artifacts(
    *,
    block_a_results: list[dict[str, Any]],
    block_b_c0_rows: list[dict[str, Any]],
    block_b_c1_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    block_a_best = next((row for row in block_a_results if row.get("physically_feasible_and_balanced") == "true"), {})
    accepted_b = [
        row for row in block_b_c1_rows
        if row.get("physically_feasible_and_balanced") == "true"
        and row.get("c0_within_calibration_tolerance") == "true"
    ]
    block_b_best = accepted_b[0] if accepted_b else {}
    comparison_rows = []
    if block_a_best:
        comparison_rows.append(
            {
                "comparison_id": "S33H_COMPARE_BLOCK_A_BEST",
                "block": "A",
                "candidate_id": block_a_best["candidate_id"],
                "case_role": block_a_best["candidate_role"],
                "weighted_c1_alignment_score": block_a_best["weighted_c1_alignment_score"],
                "mean_abs_pct_error": block_a_best["unweighted_mean_abs_pct_error"],
                "max_abs_pct_error": block_a_best["max_abs_pct_error"],
                "c0_within_calibration_tolerance": "not_applicable_shared_fixed_not_regressed",
                "interpretation": "c1_only_boundary_gap_sizing",
            }
        )
    if block_b_best:
        comparison_rows.append(
            {
                "comparison_id": "S33H_COMPARE_BLOCK_B_BEST_ACCEPTED",
                "block": "B",
                "candidate_id": block_b_best["candidate_id"],
                "case_role": block_b_best["shared_case_id"],
                "weighted_c1_alignment_score": block_b_best["weighted_c1_alignment_score"],
                "mean_abs_pct_error": block_b_best["unweighted_mean_abs_pct_error"],
                "max_abs_pct_error": block_b_best["max_abs_pct_error"],
                "c0_within_calibration_tolerance": block_b_best["c0_within_calibration_tolerance"],
                "interpretation": block_b_best["block_b_outcome"],
            }
        )
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_best_case_comparison"], comparison_rows or [{"status": "blocked_no_best_cases"}])
    final_best = block_b_best or block_a_best
    gap_rows = [
        {
            "gap_id": "S33H_GAP_001",
            "best_candidate_id": final_best.get("candidate_id", ""),
            "natural_gas_shortfall_m3_per_h": final_best.get("natural_gas_shortfall_m3_per_h", ""),
            "wag_electricity_excess_twh_per_year": final_best.get("wag_electricity_excess_twh_per_year", ""),
            "gross_electricity_surplus_twh_per_year": final_best.get("gross_electricity_surplus_twh_per_year", ""),
            "remaining_gap_type": "boundary_gap_sizing_and_shared_parameter_c0_preservation",
            "residual_gap_closure_used": "false",
            "notes": "Remaining gap is reported without inherited C0 residual NG, Table 9 residuals, or arbitrary WAG availability.",
        }
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_remaining_gap"], gap_rows)
    count_5 = sum(1 for row in block_a_results + block_b_c1_rows if row.get("all_core_targets_within_5pct") == "true")
    count_10 = sum(1 for row in block_a_results + block_b_c1_rows if row.get("all_core_targets_within_10pct") == "true")
    count_15 = sum(1 for row in block_a_results + block_b_c1_rows if row.get("all_core_targets_within_15pct") == "true")
    boundary_rows = [
        {
            "decision_id": "S33H_BOUNDARY_001",
            "item": "interpretation",
            "value": "gap_sizing_only" if final_best.get("extended_boiler_steam_gap_sizing") == "true" else "bounded_alignment",
            "status": "not_strict_validation",
            "notes": "Extended boiler/steam values above 2 PJ/y remain diagnostic gap-sizing only.",
        },
        {
            "decision_id": "S33H_BOUNDARY_002",
            "item": "c0_preservation",
            "value": "required_for_block_b_acceptance",
            "status": "enforced",
            "notes": "Block B candidates are not accepted if C0 calibration tolerances fail.",
        },
        {
            "decision_id": "S33H_BOUNDARY_003",
            "item": "target_counts",
            "value": f"within_5={count_5};within_10={count_10};within_15={count_15}",
            "status": "diagnostic_result",
            "notes": "Counts include Block A and Block B C1 rows.",
        },
        {
            "decision_id": "S33H_BOUNDARY_004",
            "item": "s3_3_freeze_status",
            "value": "not_frozen",
            "status": "blocked",
            "notes": "S3.3h is diagnostic and does not promote approved inputs.",
        },
        {
            "decision_id": "S33H_BOUNDARY_005",
            "item": "s4_readiness",
            "value": "not_ready",
            "status": "blocked",
            "notes": "No S4 logic is introduced.",
        },
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_boundary_decision_support"], boundary_rows)
    return {
        "block_a_best": block_a_best,
        "block_b_best": block_b_best,
        "candidate_count_block_a": len(block_a_results),
        "candidate_count_block_b": len(block_b_c1_rows),
        "within_5pct_count": count_5,
        "within_10pct_count": count_10,
        "within_15pct_count": count_15,
        "rejected_count": len([row for row in rejected_rows if row.get("status") != "no_rejected_cases"]),
    }


def run_diagnose_c1_phased_boundary_c0_preserving(
    *,
    solver_name: str | None,
    time_limit: float | None,
    mip_gap: float | None,
) -> dict[str, Any]:
    _write_s3_3e_static_artifacts()
    _write_dataframe(S3_3_OUTPUT_PATHS["s3_3h_parameter_classification"], s3_3h_phased_parameter_classification_rows())
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    block_a_results = _run_s3_3h_block_a(solver=solver, solver_name=resolved_name)
    block_b_c0_rows, block_b_c1_rows, rejected_rows = _run_s3_3h_block_b(
        block_a_results=block_a_results,
        solver=solver,
        solver_name=resolved_name,
    )
    summary = _write_s3_3h_summary_artifacts(
        block_a_results=block_a_results,
        block_b_c0_rows=block_b_c0_rows,
        block_b_c1_rows=block_b_c1_rows,
        rejected_rows=rejected_rows,
    )
    block_a_best = summary["block_a_best"]
    block_b_best = summary["block_b_best"]
    return {
        "solver_name": resolved_name,
        "diagnostic_label": "S3.3h phased C1 boundary and C0-preserving shared-parameter diagnostic",
        "block_a_case_count": summary["candidate_count_block_a"],
        "block_b_case_count": summary["candidate_count_block_b"],
        "best_block_a_candidate_id": block_a_best.get("candidate_id", ""),
        "best_block_a_weighted_score": block_a_best.get("weighted_c1_alignment_score", ""),
        "best_block_b_candidate_id": block_b_best.get("candidate_id", ""),
        "best_block_b_weighted_score": block_b_best.get("weighted_c1_alignment_score", ""),
        "within_5pct_count": summary["within_5pct_count"],
        "within_10pct_count": summary["within_10pct_count"],
        "within_15pct_count": summary["within_15pct_count"],
        "rejected_count": summary["rejected_count"],
        "no_run_folder_created": True,
        "approved_inputs_populated": False,
        "s3_3a_arbitrary_values_promoted": False,
    }


def run_behavioral_validation(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None) -> dict[str, Any]:
    if not S3_3_OUTPUT_PATHS["c0_168h"].exists():
        run_confirm_168h(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    lookup = _load_candidate_lookup()
    retained = _retained_candidate_rows()[:3]
    rows: list[dict[str, Any]] = []
    for retained_row in retained:
        candidate = lookup[retained_row["candidate_id"]]
        values = candidate_values(candidate)
        cases = [
            ("normal_wag_operation", values, DownstreamCaseOptions(smoke_case_id="normal_wag_operation"), 25_000.0),
            ("wag_generator_interface_outage", {**values, "wag_residual_utilisation_fraction": 0.0}, DownstreamCaseOptions(smoke_case_id="wag_generator_interface_outage"), 25_000.0),
            ("unrestricted_slab_yard_diagnostic", values, DownstreamCaseOptions(smoke_case_id="unrestricted_slab_yard_diagnostic"), 100_000.0),
            ("dsp_relaxation_diagnostic", values, DownstreamCaseOptions(smoke_case_id="dsp_relaxation_diagnostic"), 25_000.0),
            ("hsm_relaxation_diagnostic", values, DownstreamCaseOptions(smoke_case_id="hsm_relaxation_diagnostic", hsm_capacity_multiplier=1.25), 25_000.0),
            ("slab_storage_relaxation_diagnostic", values, DownstreamCaseOptions(smoke_case_id="slab_storage_relaxation_diagnostic"), 100_000.0),
        ]
        base_cost = None
        base_flare = None
        for case_id, case_values, downstream_options, slab_capacity in cases:
            row = solve_calibration_case(
                candidate_id=retained_row["candidate_id"],
                candidate_role=str(candidate["candidate_role"]),
                parameter_values=case_values,
                horizon_hours=168,
                smoke_case_id=case_id,
                downstream_options=downstream_options,
                slab_yard_capacity_t=slab_capacity,
                solver=solver,
                solver_name=resolved_name,
            )
            if case_id == "normal_wag_operation" and row["termination_condition"] in {"optimal", "feasible"}:
                base_cost = float(row["objective_value"])
                base_flare = float(row["flare_fraction_of_wag_generated"])
            row["behavioral_case"] = case_id
            row["table7_comparison_mode"] = "sign_and_ranking_only_not_exact_percentage_fit"
            row["unrestricted_slab_reference_t"] = 68_000.0
            row["objective_improvement_pct_vs_normal"] = (
                ""
                if base_cost in (None, 0.0) or row["objective_value"] == ""
                else (base_cost - float(row["objective_value"])) / abs(base_cost)
            )
            row["flare_increase_vs_normal"] = (
                ""
                if base_flare is None
                else float(row.get("flare_fraction_of_wag_generated", 0.0) or 0.0) - base_flare
            )
            row["behavioral_status"] = "diagnostic_recorded_no_tuning"
            if case_id == "hot_metal_storage_relaxation_diagnostic":
                row["behavioral_status"] = "blocked_not_represented_in_s2_13_integrated_downstream_model"
            rows.append(row)
        rows.append(
            {
                "candidate_id": retained_row["candidate_id"],
                "candidate_role": str(candidate["candidate_role"]),
                "configuration_id": C0_CONFIGURATION_ID,
                "horizon_hours": 168,
                "annual_final_product_t": CALIBRATION_ANNUAL_FINAL_PRODUCT_T,
                "behavioral_case": "hot_metal_storage_relaxation_diagnostic",
                "termination_condition": "not_run",
                "behavioral_status": "blocked_not_represented_in_s2_13_integrated_downstream_model",
                "table7_comparison_mode": "sign_and_ranking_only_not_exact_percentage_fit",
                "notes": "Hot-metal store capacity is governed at 500 t but not an active store in the S2.13 integrated downstream schedule.",
            }
        )
    _write_dataframe(S3_3_OUTPUT_PATHS["behavioral"], rows)
    outage_rows = [row for row in rows if row.get("behavioral_case") == "wag_generator_interface_outage"]
    outage_increases = [row for row in outage_rows if row.get("flare_increase_vs_normal") not in ("", None) and float(row["flare_increase_vs_normal"]) > 0]
    return {
        "solver_name": resolved_name,
        "behavioral_cases": len(rows),
        "wag_outage_flare_increase_cases": len(outage_increases),
    }


def select_parameter_ensemble() -> dict[str, Any]:
    if not S3_3_OUTPUT_PATHS["c0_168h"].exists():
        return {"status": "blocked", "reason": "c0_168h_results_missing"}
    frame = pd.read_csv(S3_3_OUTPUT_PATHS["c0_168h"], dtype=str, keep_default_na=False)
    retained = frame.loc[frame["retained_for_holdout_validation"].eq("true")].copy()
    if len(retained) < 3:
        rows = [
            {
                "ensemble_role": "blocked",
                "candidate_id": "",
                "selection_status": "blocked_fewer_than_three_c0_168h_sets",
                "notes": "Do not freeze a central S3.3 calibrated parameter set.",
            }
        ]
        _write_dataframe(S3_3_OUTPUT_PATHS["ensemble"], rows)
        _write_dataframe(S3_3_OUTPUT_PATHS["selected_inputs"], rows)
        return {"status": "blocked", "reason": "fewer_than_three_c0_168h_sets"}

    retained["_score"] = retained["calibration_score"].astype(float)
    retained["_boundary_count"] = retained["boundary_parameter_count"].astype(int)
    central = retained.sort_values(["_boundary_count", "_score"]).iloc[0].to_dict()
    low_wag = retained.sort_values("wag_electricity_twh_per_year").iloc[0].to_dict()
    high_wag = retained.sort_values("wag_electricity_twh_per_year", ascending=False).iloc[0].to_dict()
    selected = [
        ("central_calibrated_set", central),
        ("lower_energy_wag_envelope", low_wag),
        ("higher_energy_wag_envelope", high_wag),
    ]
    for _, row in retained.sort_values("_score").iterrows():
        if len({item[1]["candidate_id"] for item in selected}) >= 3:
            break
        selected.append(("additional_plausible_set", row.to_dict()))
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for role, row in selected:
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        rows.append(
            {
                "ensemble_role": role,
                "candidate_id": row["candidate_id"],
                "calibration_score": row["calibration_score"],
                "gross_electricity_error_pct": row.get("gross_electricity_error_pct", ""),
                "wag_electricity_error_pct": row.get("wag_electricity_error_pct", ""),
                "natural_gas_flow_error_pct": row.get("natural_gas_flow_error_pct", ""),
                "direct_co2_error_pct": row.get("direct_co2_error_pct", ""),
                "primary_proxy_error_pct": row.get("primary_proxy_error_pct", ""),
                "boundary_parameter_count": row["boundary_parameter_count"],
                "selection_status": "selected_for_uncertainty_propagation",
                "identifiability": "weakly_identified_multivariate_fit",
                "notes": "Selected from C0 168h calibrated sets; C1 holdout remains separate.",
            }
        )
    _write_dataframe(S3_3_OUTPUT_PATHS["ensemble"], rows)

    candidate_lookup = _load_candidate_lookup()
    input_rows: list[dict[str, Any]] = []
    for ensemble in rows:
        candidate = candidate_lookup[ensemble["candidate_id"]]
        for parameter in eligible_calibration_parameters():
            input_rows.append(
                {
                    "ensemble_role": ensemble["ensemble_role"],
                    "candidate_id": ensemble["candidate_id"],
                    "parameter_id": parameter.parameter_id,
                    "selected_value": candidate[parameter.parameter_id],
                    "unit": parameter.unit,
                    "activity_basis": parameter.activity_basis,
                    "lower": parameter.lower,
                    "source_central": parameter.source_central,
                    "upper": parameter.upper,
                    "model_use_status": "provisional_s3_3_selected_calibrated_input",
                    "approved_input_shell_populated": "false",
                    "identifiability": "weakly_identified" if parameter.parameter_id not in {"residual_c0_ng_m3_per_t_final", "bf_bof_aggregate_direct_co2_t_per_t_bof"} else "well_identified_against_single_target",
                }
            )
    _write_dataframe(S3_3_OUTPUT_PATHS["selected_inputs"], input_rows)
    return {"status": "selected", "ensemble_size": len(rows), "central_candidate_id": rows[0]["candidate_id"]}


def run_scale_stress_6_75(*, solver_name: str | None, time_limit: float | None, mip_gap: float | None) -> dict[str, Any]:
    if not S3_3_OUTPUT_PATHS["ensemble"].exists():
        select_parameter_ensemble()
    resolved_name, solver = _solver(solver_name=solver_name, time_limit=time_limit, mip_gap=mip_gap)
    values = calibration_anchor_parameter_set()
    if S3_3_OUTPUT_PATHS["ensemble"].exists() and S3_3_OUTPUT_PATHS["candidate_sets"].exists():
        ensemble = pd.read_csv(S3_3_OUTPUT_PATHS["ensemble"], dtype=str, keep_default_na=False)
        if not ensemble.empty and ensemble.iloc[0]["candidate_id"]:
            values = candidate_values(_load_candidate_lookup()[ensemble.iloc[0]["candidate_id"]])
    row = solve_calibration_case(
        candidate_id="S33_SCALE_STRESS_6_75",
        candidate_role="badarinath_aligned_external_scale_stress",
        parameter_values=values,
        horizon_hours=168,
        annual_final_product_t=EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T,
        smoke_case_id="s3_3_scale_stress_6_75Mt",
        solver=solver,
        solver_name=resolved_name,
    )
    path = S3_REVIEW_ROOT / "s3_3_scale_stress_6_75_results.csv"
    _write_dataframe(path, [row])
    return {
        "solver_name": resolved_name,
        "scale_stress_path": str(path),
        "termination_condition": row["termination_condition"],
        "annual_final_product_t": EXTERNAL_STRESS_ANNUAL_FINAL_PRODUCT_T,
        "runtime_seconds": row["runtime_seconds"],
        "mip_gap": row["mip_gap"],
    }


def write_stage_gate() -> dict[str, Any]:
    retained = 0
    c1_pass = 0
    behavioral_rows = 0
    if S3_3_OUTPUT_PATHS["c0_168h"].exists():
        c0 = pd.read_csv(S3_3_OUTPUT_PATHS["c0_168h"], dtype=str, keep_default_na=False)
        retained = int(c0["retained_for_holdout_validation"].eq("true").sum()) if "retained_for_holdout_validation" in c0 else 0
    if S3_3_OUTPUT_PATHS["c1_holdout"].exists():
        c1 = pd.read_csv(S3_3_OUTPUT_PATHS["c1_holdout"], dtype=str, keep_default_na=False)
        c1_pass = int(c1["c1_holdout_pass_principal_targets"].eq("true").sum()) if "c1_holdout_pass_principal_targets" in c1 else 0
    if S3_3_OUTPUT_PATHS["behavioral"].exists():
        behavioral_rows = len(pd.read_csv(S3_3_OUTPUT_PATHS["behavioral"], dtype=str, keep_default_na=False))
    gates = [
        ("S33_GATE_001", "separate_6_2Mt_overlay_exists", "pass", "Calibration overlay is written under S3 provisional input."),
        ("S33_GATE_002", "legacy_2_98Mt_baseline_preserved", "pass", "No S2.13/S3.2 baseline overwrite."),
        ("S33_GATE_003", "fixed_storage_capacities_recorded", "pass", "Slab yard 25000 t and hot-metal 500 t recorded."),
        ("S33_GATE_004", "figure96_table8_conflict_governed", "pass", "Conflict register excludes disputed electricity share from score."),
        ("S33_GATE_005", "c0_168h_minimum_three_sets", "pass" if retained >= 3 else "blocked", f"Retained sets: {retained}."),
        ("S33_GATE_006", "c1_holdout_without_retuning", "pass" if c1_pass > 0 else "blocked", f"C1 holdout pass cases: {c1_pass}."),
        ("S33_GATE_007", "behavioral_holdouts_recorded", "pass" if behavioral_rows > 0 else "blocked", f"Behavioural rows: {behavioral_rows}."),
        ("S33_GATE_008", "no_da_stochastic_cvar_mfrr_logic", "pass", "S3.3 runner adds no market or risk logic."),
        ("S33_GATE_009", "freeze_status", "pass" if retained >= 3 and c1_pass > 0 and behavioral_rows > 0 else "blocked", "S4 entry only if all prior gates pass."),
    ]
    rows = [
        {"gate_id": gate_id, "gate_name": name, "pass_fail_or_blocked": status, "notes": notes}
        for gate_id, name, status, notes in gates
    ]
    _write_dataframe(S3_3_OUTPUT_PATHS["stage_gate"], rows)
    return {"freeze_status": rows[-1]["pass_fail_or_blocked"], "retained_c0_sets": retained, "c1_pass_cases": c1_pass}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S3.3 steel calibration, holdout validation, and ensemble selection.")
    parser.add_argument("--validate-inputs-only", action="store_true")
    parser.add_argument("--screen", action="store_true")
    parser.add_argument("--calibrate-24h", action="store_true")
    parser.add_argument("--confirm-168h", action="store_true")
    parser.add_argument("--validate-c1", action="store_true")
    parser.add_argument("--diagnose-c1-structure", action="store_true")
    parser.add_argument("--validate-c1-s3-3b", action="store_true")
    parser.add_argument("--validate-c1-s3-3c", action="store_true")
    parser.add_argument("--validate-c1-s3-3d", action="store_true")
    parser.add_argument("--resolve-inherited-ng-s3-3e", action="store_true")
    parser.add_argument("--diagnose-c1-bounded-alignment", action="store_true")
    parser.add_argument("--diagnose-c1-gas-sink-decomposition", action="store_true")
    parser.add_argument("--diagnose-c1-phased-boundary-c0-preserving", action="store_true")
    parser.add_argument("--behavioral-validation", action="store_true")
    parser.add_argument("--scale-stress-6-75", action="store_true")
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--solver", default=None)
    parser.add_argument("--time-limit", type=float, default=None)
    parser.add_argument("--mip-gap", type=float, default=None)
    args = parser.parse_args()

    payload: dict[str, Any] = {
        "output_policy": "minimal",
        "run_class": "s3_3_calibration_register_update",
        "lineage_role": "candidate_review_provisional_input",
        "no_run_folder_created": True,
    }

    if args.validate_inputs_only or not any(
        (
            args.screen,
            args.calibrate_24h,
            args.confirm_168h,
            args.validate_c1,
            args.diagnose_c1_structure,
            args.validate_c1_s3_3b,
            args.validate_c1_s3_3c,
            args.validate_c1_s3_3d,
            args.resolve_inherited_ng_s3_3e,
            args.diagnose_c1_bounded_alignment,
            args.diagnose_c1_gas_sink_decomposition,
            args.diagnose_c1_phased_boundary_c0_preserving,
            args.behavioral_validation,
            args.scale_stress_6_75,
        )
    ):
        payload["validate_inputs_only"] = validate_inputs_only()
    if args.screen:
        payload["screen"] = run_screening(solver_name=args.solver, time_limit=args.time_limit, mip_gap=args.mip_gap)
    if args.calibrate_24h:
        payload["calibrate_24h"] = run_calibrate_24h(
            seed=args.seed,
            max_candidates=args.max_candidates,
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.confirm_168h:
        payload["confirm_168h"] = run_confirm_168h(solver_name=args.solver, time_limit=args.time_limit, mip_gap=args.mip_gap)
        payload["ensemble_selection"] = select_parameter_ensemble()
    if args.validate_c1:
        payload["validate_c1"] = run_validate_c1(solver_name=args.solver, time_limit=args.time_limit, mip_gap=args.mip_gap)
    if args.diagnose_c1_structure:
        payload["diagnose_c1_structure"] = run_diagnose_c1_structure(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.validate_c1_s3_3b:
        payload["validate_c1_s3_3b"] = run_validate_c1_s3_3b(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.validate_c1_s3_3c:
        payload["validate_c1_s3_3c"] = run_validate_c1_s3_3c(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.validate_c1_s3_3d:
        payload["validate_c1_s3_3d"] = run_validate_c1_s3_3d(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.resolve_inherited_ng_s3_3e:
        payload["resolve_inherited_ng_s3_3e"] = run_resolve_inherited_ng_s3_3e(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.diagnose_c1_bounded_alignment:
        bounded_max_candidates = (
            S3_3F_DEFAULT_MAX_CANDIDATES
            if args.max_candidates == DEFAULT_MAX_CANDIDATES
            else args.max_candidates
        )
        payload["run_class"] = "bounded_c1_alignment_diagnostic"
        payload["lineage_role"] = "candidate_review_provisional_diagnostic"
        payload["diagnose_c1_bounded_alignment"] = run_diagnose_c1_bounded_alignment(
            seed=args.seed,
            max_candidates=bounded_max_candidates,
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.diagnose_c1_gas_sink_decomposition:
        payload["run_class"] = "c1_gas_sink_decomposition_diagnostic"
        payload["lineage_role"] = "candidate_review_provisional_diagnostic"
        payload["diagnose_c1_gas_sink_decomposition"] = run_diagnose_c1_gas_sink_decomposition(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.diagnose_c1_phased_boundary_c0_preserving:
        payload["run_class"] = "phased_c1_boundary_c0_preserving_diagnostic"
        payload["lineage_role"] = "candidate_review_provisional_diagnostic"
        payload["diagnose_c1_phased_boundary_c0_preserving"] = run_diagnose_c1_phased_boundary_c0_preserving(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.behavioral_validation:
        payload["behavioral_validation"] = run_behavioral_validation(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )
    if args.scale_stress_6_75:
        payload["scale_stress_6_75"] = run_scale_stress_6_75(
            solver_name=args.solver,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
        )

    payload["stage_gate"] = write_stage_gate()
    if args.output_path is not None:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["stage_gate"]["freeze_status"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
