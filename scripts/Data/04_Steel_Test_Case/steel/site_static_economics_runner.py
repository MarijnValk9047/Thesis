from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Constraint, Objective, TerminationCondition, value

from .downstream_scheduling_builder import DownstreamCaseOptions
from .downstream_scheduling_inputs import load_downstream_assumptions
from .downstream_scheduling_runner import (
    _mip_gap,
    _solve_model,
    available_solver,
    max_material_balance_residual,
)
from .site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID
from .site_energy_economic_inputs import WAG_CARRIERS
from .site_static_economics_builder import (
    S32CaseOptions,
    build_site_static_economics_model,
    c1_endogenous_route_options,
)
from .site_static_economics_inputs import load_s3_2_static_economics_assumptions


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RESULT_REGISTER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s3_2_smoke_and_168h_result_register.csv"
)
OPTIMAL_TERMINATIONS = {TerminationCondition.optimal, TerminationCondition.feasible}
C0_REFERENCE_WAG_GJ_24H = 57391.51057


@dataclass(frozen=True)
class S32SmokeCase:
    smoke_case: str
    configuration_id: str
    horizon_hours: int
    downstream_options: DownstreamCaseOptions
    expected_outcome: str
    route_mode: str = "fixed"
    s3_2_sensitivity_case: str = "central"
    slab_capacity_case: str = "central_25000t"
    bf_bof_share_override: float | None = None
    notes: str = ""


def required_s3_2_smoke_cases() -> tuple[S32SmokeCase, ...]:
    return (
        S32SmokeCase(
            smoke_case="c0_static_economic_24h",
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="c0_static_economic_24h"),
            expected_outcome="optimal",
            notes="C0 static material-energy-carbon baseline.",
        ),
        S32SmokeCase(
            smoke_case="c1_fixed_61_39_static_economic_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="c1_fixed_61_39_static_economic_24h"),
            expected_outcome="optimal",
            notes="C1 fixed 0.61/0.39 static material-energy-carbon baseline.",
        ),
        S32SmokeCase(
            smoke_case="c1_endogenous_route_static_economics_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=c1_endogenous_route_options("c1_endogenous_route_static_economics_24h"),
            expected_outcome="optimal",
            route_mode="endogenous_bounded",
            notes="C1 endogenous bounded route-choice diagnostic.",
        ),
        S32SmokeCase(
            smoke_case="recoverable_hsm_outage_static_economics_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(
                smoke_case_id="recoverable_hsm_outage_static_economics_24h",
                hsm_unavailable_hours=(8, 9, 10, 11),
                hsm_capacity_multiplier=1.15,
            ),
            expected_outcome="optimal",
            notes="Recoverable HSM outage under static economics.",
        ),
        S32SmokeCase(
            smoke_case="cold_heavy_static_economics_24h",
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(
                smoke_case_id="cold_heavy_static_economics_24h",
                hsm_unavailable_hours=(8, 9, 10, 11),
                hsm_capacity_multiplier=1.15,
                require_cold_slab_creation=True,
            ),
            expected_outcome="optimal",
            notes="Cold-heavy diagnostic under static economics.",
        ),
        S32SmokeCase(
            smoke_case="hard_target_stress_infeasible_static_economics_24h",
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(
                smoke_case_id="hard_target_stress_infeasible_static_economics_24h",
                hsm_unavailable_hours=(6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
                hsm_capacity_multiplier=0.5,
            ),
            expected_outcome="infeasible",
            notes="Hard target stress infeasibility must remain infeasible.",
        ),
    )


def required_s3_2_168h_cases() -> tuple[S32SmokeCase, ...]:
    return (
        S32SmokeCase(
            smoke_case="c0_static_economic_168h",
            configuration_id=C0_CONFIGURATION_ID,
            horizon_hours=168,
            downstream_options=DownstreamCaseOptions(smoke_case_id="c0_static_economic_168h"),
            expected_outcome="optimal",
            notes="C0 168h static economic baseline.",
        ),
        S32SmokeCase(
            smoke_case="c1_fixed_61_39_static_economic_168h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            downstream_options=DownstreamCaseOptions(smoke_case_id="c1_fixed_61_39_static_economic_168h"),
            expected_outcome="optimal",
            notes="C1 fixed 0.61/0.39 168h static economic baseline.",
        ),
        S32SmokeCase(
            smoke_case="c1_endogenous_route_static_economics_168h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=168,
            downstream_options=c1_endogenous_route_options("c1_endogenous_route_static_economics_168h"),
            expected_outcome="optimal",
            route_mode="endogenous_bounded",
            notes="C1 endogenous bounded 168h route-choice diagnostic.",
        ),
    )


def s3_2_sensitivity_cases() -> tuple[S32SmokeCase, ...]:
    return (
        S32SmokeCase(
            smoke_case="sensitivity_slab_yard_legacy_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_slab_yard_legacy_24h"),
            expected_outcome="optimal",
            slab_capacity_case="legacy_12h_derived",
            notes="Legacy slab-yard capacity sensitivity.",
        ),
        S32SmokeCase(
            smoke_case="sensitivity_slab_yard_upper_50000t_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_slab_yard_upper_50000t_24h"),
            expected_outcome="optimal",
            slab_capacity_case="upper_50000t",
            notes="Upper diagnostic slab-yard capacity sensitivity.",
        ),
        S32SmokeCase(
            smoke_case="sensitivity_low_static_prices_and_coefficients_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_low_static_prices_and_coefficients_24h"),
            expected_outcome="optimal",
            s3_2_sensitivity_case="low",
            notes="Grouped low material-energy-carbon price and WAG-interface sensitivity.",
        ),
        S32SmokeCase(
            smoke_case="sensitivity_high_static_prices_and_coefficients_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_high_static_prices_and_coefficients_24h"),
            expected_outcome="optimal",
            s3_2_sensitivity_case="high",
            notes="Grouped high material-energy-carbon price and WAG-interface sensitivity.",
        ),
        S32SmokeCase(
            smoke_case="sensitivity_fixed_route_055_bf_bof_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_fixed_route_055_bf_bof_24h"),
            expected_outcome="optimal",
            bf_bof_share_override=0.55,
            notes="Fixed-route sensitivity with 0.55 BF-BOF share.",
        ),
        S32SmokeCase(
            smoke_case="sensitivity_fixed_route_068_bf_bof_24h",
            configuration_id=C1_CONFIGURATION_ID,
            horizon_hours=24,
            downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_fixed_route_068_bf_bof_24h"),
            expected_outcome="optimal",
            bf_bof_share_override=0.68,
            notes="Fixed-route sensitivity with 0.68 BF-BOF share.",
        ),
    )


def _is_feasible(result) -> bool:
    return result is not None and result.solver.termination_condition in OPTIMAL_TERMINATIONS


def _round(value_obj: float | str, digits: int = 6) -> float | str:
    if value_obj == "":
        return ""
    return round(float(value_obj), digits)


def _safe_value(expr) -> float | str:
    try:
        return float(value(expr))
    except Exception:
        return ""


def _sum_expr(model, component_name: str) -> float:
    component = getattr(model, component_name)
    return float(sum(value(component[t]) for t in model.TIME))


def _sum_carrier_expr(model, component_name: str, carrier: str) -> float:
    component = getattr(model, component_name)
    return float(sum(value(component[carrier, t]) for t in model.TIME))


def _objective_value(model) -> float | str:
    active = list(model.component_data_objects(Objective, active=True, descend_into=True))
    if not active:
        return ""
    return float(value(active[0]))


def _max_constraint_residual(constraints) -> float:
    residuals = []
    for constraint in constraints:
        body = float(value(constraint.body))
        if constraint.equality:
            residuals.append(abs(body - float(value(constraint.lower))))
    return 0.0 if not residuals else max(residuals)


def _max_wag_balance_residual(model) -> float:
    return _max_constraint_residual(model.wag_carrier_balance.values())


def _max_electricity_balance_residual(model) -> float:
    return _max_constraint_residual(model.grid_import_balance.values())


def _max_carbon_decomposition_residual(model) -> float:
    residuals = []
    for component_name in ("drp_direct_co2_decomposition", "bf_bof_direct_co2_decomposition"):
        residuals.extend(getattr(model, component_name).values())
    return _max_constraint_residual(residuals)


def _cost_sum_residual(model) -> float:
    parts = (
        value(model.total_material_cost_eur)
        + value(model.electricity_cost_eur)
        + value(model.natural_gas_cost_eur)
        + value(model.gross_direct_co2_cost_eur)
    )
    return abs(value(model.total_static_operating_cost_eur) - parts)


def _terminal_cold_deviation(model) -> float:
    assumptions = model.s2_13_assumptions
    return abs(
        float(value(model.cold_slab_inventory[max(model.TIME)]))
        - assumptions.initial_cold_slab_inventory_t * assumptions.terminal_cold_inventory_ratio
    )


def _terminal_hot_total(model) -> float:
    last = max(model.TIME)
    return float(sum(value(model.hot_slab_inventory[age, last]) for age in model.HOT_AGES))


def _downstream_assumptions_for_case(case: S32SmokeCase):
    assumptions = load_downstream_assumptions(
        configuration_id=case.configuration_id,
        horizon_hours=case.horizon_hours,
    )
    legacy_capacity = 12.0 * assumptions.q_avg_hsm_tph
    if case.slab_capacity_case == "legacy_12h_derived":
        assumptions = replace(assumptions, slab_yard_capacity_t=legacy_capacity)
    elif case.slab_capacity_case == "upper_50000t":
        assumptions = replace(assumptions, slab_yard_capacity_t=50000.0)
    elif case.slab_capacity_case != "central_25000t":
        raise ValueError(f"Unsupported slab_capacity_case={case.slab_capacity_case!r}.")
    if case.bf_bof_share_override is not None:
        assumptions = replace(
            assumptions,
            bf_bof_share=case.bf_bof_share_override,
            drp_eaf_share=1.0 - case.bf_bof_share_override,
        )
    return assumptions


def _feasible_row(case: S32SmokeCase, model, result, runtime: float, solver_name: str) -> dict[str, Any]:
    stats = model.s3_2_model_stats
    final_product = value(model.horizon_final_product_output)
    route_total = value(model.route_total_liquid_steel_source)
    bf_bof_share = value(model.bof_route_total) / route_total if route_total else 0.0
    drp_eaf_share = value(model.eaf_route_total) / route_total if route_total else 0.0
    c0_reference = C0_REFERENCE_WAG_GJ_24H * (case.horizon_hours / 24.0)
    total_wag = value(model.horizon_total_wag_generated_gj)
    return {
        "result_id": f"S32_{case.smoke_case}",
        "smoke_case": case.smoke_case,
        "configuration_id": case.configuration_id,
        "horizon_hours": case.horizon_hours,
        "assumption_set_id": model.s3_2_assumptions.assumption_set_id,
        "sensitivity_case": model.s3_2_assumptions.sensitivity_case,
        "slab_capacity_case": case.slab_capacity_case,
        "slab_yard_capacity_t": _round(model.s2_13_assumptions.slab_yard_capacity_t),
        "initial_cold_slab_inventory_t": _round(model.s2_13_assumptions.initial_cold_slab_inventory_t),
        "route_mode": case.route_mode,
        "objective_type": model.s3_2_metadata["objective_type"],
        "static_cost_result": "true",
        "solver_name": solver_name,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value": _round(value(model.total_static_operating_cost_eur)),
        "runtime_seconds": round(runtime, 6),
        "mip_gap": _mip_gap(result),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": _round(model.s2_13_assumptions.final_product_target_t),
        "final_product_output_t": _round(final_product),
        "liquid_steel_input_t": _round(value(model.horizon_liquid_steel_input)),
        "bof_liquid_steel_t": _round(value(model.bof_route_total)),
        "eaf_liquid_steel_t": _round(value(model.eaf_route_total)),
        "bf_bof_share": _round(bf_bof_share, 9),
        "drp_eaf_share": _round(drp_eaf_share, 9),
        "wag_share_vs_c0": _round(total_wag / c0_reference, 9),
        "dsp_output_t": _round(value(model.horizon_dsp_output)),
        "hsm_output_t": _round(value(model.horizon_hsm_output)),
        "hot_charge_t": _round(value(model.horizon_hot_charge_tonnage)),
        "cold_slab_to_yard_t": _round(value(model.horizon_hot_slab_to_cold)),
        "reheated_t": _round(value(model.horizon_reheated_tonnage)),
        "max_cold_slab_inventory_t": _round(max(float(value(model.cold_slab_inventory[t])) for t in model.TIME)),
        "avg_cold_slab_inventory_t": _round(sum(float(value(model.cold_slab_inventory[t])) for t in model.TIME) / len(model.TIME)),
        "terminal_cold_slab_deviation_t": _round(_terminal_cold_deviation(model), 9),
        "terminal_hot_slab_t": _round(_terminal_hot_total(model), 9),
        "terminal_reheated_queue_t": _round(float(value(model.reheated_slab_queue[max(model.TIME)])), 9),
        "startup_count": _round(value(model.horizon_startup_count)),
        "coking_coal_t": _round(_sum_expr(model, "coking_coal_t")),
        "purchased_coke_t": _round(_sum_expr(model, "purchased_coke_t")),
        "iron_ore_sinter_feed_t": _round(_sum_expr(model, "iron_ore_sinter_feed_t")),
        "bf_pellets_t": _round(_sum_expr(model, "bf_pellets_t")),
        "dr_pellets_t": _round(_sum_expr(model, "dr_pellets_t")),
        "scrap_t": _round(_sum_expr(model, "bof_scrap_t") + _sum_expr(model, "eaf_scrap_t")),
        "flux_t": _round(_sum_expr(model, "bf_bof_flux_t") + _sum_expr(model, "eaf_flux_t")),
        "electrode_t": _round(_sum_expr(model, "eaf_electrode_t")),
        "gross_electricity_mwh": _round(value(model.horizon_gross_electricity_mwh)),
        "wag_power_output_mwh": _round(value(model.horizon_wag_power_output_mwh)),
        "grid_import_mwh": _round(value(model.horizon_grid_import_mwh)),
        "natural_gas_import_gj": _round(value(model.horizon_natural_gas_import_gj)),
        "drp_natural_gas_m3": _round(value(model.horizon_drp_natural_gas_m3)),
        "reheating_heat_gj": _round(value(model.horizon_reheating_heat_gj)),
        "bfg_generated_gj": _round(_sum_expr(model, "bfg_generated_gj")),
        "cog_generated_gj": _round(_sum_expr(model, "cog_generated_gj")),
        "bofg_generated_gj": _round(_sum_expr(model, "bofg_generated_gj")),
        "total_wag_generated_gj": _round(total_wag),
        "wag_process_use_gj": _round(sum(_sum_carrier_expr(model, "wag_process_use_gj", c) for c in WAG_CARRIERS)),
        "wag_steam_boiler_use_gj": _round(sum(_sum_carrier_expr(model, "wag_steam_boiler_use_gj", c) for c in WAG_CARRIERS)),
        "wag_reheating_use_gj": _round(sum(_sum_carrier_expr(model, "wag_reheating_use_gj", c) for c in WAG_CARRIERS)),
        "wag_power_use_gj": _round(value(model.horizon_wag_power_use_gj)),
        "flare_spill_gj": _round(value(model.horizon_flare_spill_gj)),
        "wag_co2_t": _round(sum(_sum_carrier_expr(model, "wag_co2_t", c) for c in WAG_CARRIERS)),
        "drp_ng_combustion_co2_t": _round(value(model.horizon_drp_ng_combustion_co2_t)),
        "drp_residual_process_co2_t": _round(value(model.horizon_drp_residual_process_co2_t)),
        "bf_bof_non_wag_residual_direct_co2_t": _round(value(model.horizon_bf_bof_non_wag_residual_direct_co2_t)),
        "reheating_ng_co2_t": _round(value(model.horizon_reheating_ng_co2_t)),
        "total_direct_co2_t": _round(value(model.horizon_s3_2_total_direct_co2_t)),
        "scope2_operational_co2_t": _round(value(model.scope2_operational_co2_t)),
        "grid_lifecycle_co2e_sensitivity_t": _round(value(model.grid_lifecycle_co2e_sensitivity_t)),
        "total_direct_plus_scope2_t": _round(value(model.total_location_based_direct_plus_scope2_t)),
        "complete_direct_emissions_ready": str(model.s3_2_assumptions.complete_direct_emissions_ready).lower(),
        "scope2_ets_costed": "false",
        "double_counting_warning": "",
        "material_cost_eur": _round(value(model.total_material_cost_eur)),
        "electricity_cost_eur": _round(value(model.electricity_cost_eur)),
        "natural_gas_cost_eur": _round(value(model.natural_gas_cost_eur)),
        "gross_direct_co2_cost_eur": _round(value(model.gross_direct_co2_cost_eur)),
        "total_static_operating_cost_eur": _round(value(model.total_static_operating_cost_eur)),
        "eur_per_t_final_product": _round(value(model.eur_per_t_final_product)),
        "monetary_values_ready": "true",
        "max_material_balance_residual_t": _round(max_material_balance_residual(model), 12),
        "max_wag_balance_residual_gj": _round(_max_wag_balance_residual(model), 12),
        "max_electricity_balance_residual_mwh": _round(_max_electricity_balance_residual(model), 12),
        "max_carbon_decomposition_residual_t": _round(_max_carbon_decomposition_residual(model), 12),
        "max_cost_sum_residual_eur": _round(_cost_sum_residual(model), 9),
        "shortfall_slack_present": "false",
        "infeasibility_class": "",
        "thesis_usability": "false",
        "limitations": "development-only S3.2 static economics; no DA bidding settlement stochastic CVaR mFRR product revenue CBAM or ETS free allocation",
        "notes": case.notes,
    }


def _infeasible_row(case: S32SmokeCase, model, result, runtime: float, solver_name: str) -> dict[str, Any]:
    stats = model.s3_2_model_stats
    termination = str(result.solver.termination_condition) if result is not None else "not_attempted"
    return {
        "result_id": f"S32_{case.smoke_case}",
        "smoke_case": case.smoke_case,
        "configuration_id": case.configuration_id,
        "horizon_hours": case.horizon_hours,
        "assumption_set_id": model.s3_2_assumptions.assumption_set_id,
        "sensitivity_case": model.s3_2_assumptions.sensitivity_case,
        "slab_capacity_case": case.slab_capacity_case,
        "slab_yard_capacity_t": _round(model.s2_13_assumptions.slab_yard_capacity_t),
        "initial_cold_slab_inventory_t": _round(model.s2_13_assumptions.initial_cold_slab_inventory_t),
        "route_mode": case.route_mode,
        "objective_type": model.s3_2_metadata["objective_type"],
        "static_cost_result": "true",
        "solver_name": solver_name,
        "solver_status": str(result.solver.status) if result is not None else "not_attempted",
        "termination_condition": termination,
        "objective_value": "",
        "runtime_seconds": round(runtime, 6),
        "mip_gap": _mip_gap(result) if result is not None else "not_attempted",
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": _round(model.s2_13_assumptions.final_product_target_t),
        "final_product_output_t": "",
        "liquid_steel_input_t": "",
        "bof_liquid_steel_t": "",
        "eaf_liquid_steel_t": "",
        "bf_bof_share": "",
        "drp_eaf_share": "",
        "wag_share_vs_c0": "",
        "dsp_output_t": "",
        "hsm_output_t": "",
        "hot_charge_t": "",
        "cold_slab_to_yard_t": "",
        "reheated_t": "",
        "max_cold_slab_inventory_t": "",
        "avg_cold_slab_inventory_t": "",
        "terminal_cold_slab_deviation_t": "",
        "terminal_hot_slab_t": "",
        "terminal_reheated_queue_t": "",
        "startup_count": "",
        "coking_coal_t": "",
        "purchased_coke_t": "",
        "iron_ore_sinter_feed_t": "",
        "bf_pellets_t": "",
        "dr_pellets_t": "",
        "scrap_t": "",
        "flux_t": "",
        "electrode_t": "",
        "gross_electricity_mwh": "",
        "wag_power_output_mwh": "",
        "grid_import_mwh": "",
        "natural_gas_import_gj": "",
        "drp_natural_gas_m3": "",
        "reheating_heat_gj": "",
        "bfg_generated_gj": "",
        "cog_generated_gj": "",
        "bofg_generated_gj": "",
        "total_wag_generated_gj": "",
        "wag_process_use_gj": "",
        "wag_steam_boiler_use_gj": "",
        "wag_reheating_use_gj": "",
        "wag_power_use_gj": "",
        "flare_spill_gj": "",
        "wag_co2_t": "",
        "drp_ng_combustion_co2_t": "",
        "drp_residual_process_co2_t": "",
        "bf_bof_non_wag_residual_direct_co2_t": "",
        "reheating_ng_co2_t": "",
        "total_direct_co2_t": "",
        "scope2_operational_co2_t": "",
        "grid_lifecycle_co2e_sensitivity_t": "",
        "total_direct_plus_scope2_t": "",
        "complete_direct_emissions_ready": str(model.s3_2_assumptions.complete_direct_emissions_ready).lower(),
        "scope2_ets_costed": "false",
        "double_counting_warning": "",
        "material_cost_eur": "",
        "electricity_cost_eur": "",
        "natural_gas_cost_eur": "",
        "gross_direct_co2_cost_eur": "",
        "total_static_operating_cost_eur": "",
        "eur_per_t_final_product": "",
        "monetary_values_ready": "true",
        "max_material_balance_residual_t": "",
        "max_wag_balance_residual_gj": "",
        "max_electricity_balance_residual_mwh": "",
        "max_carbon_decomposition_residual_t": "",
        "max_cost_sum_residual_eur": "",
        "shortfall_slack_present": "false",
        "infeasibility_class": (
            "hard_final_product_target_infeasible_accounting_layer_no_fake_feasibility"
            if "infeasible" in termination.lower()
            else f"non_optimal_termination_{termination}"
        ),
        "thesis_usability": "false",
        "limitations": "development-only S3.2 stress diagnostic; no hidden shortfall slack",
        "notes": case.notes,
    }


def solve_s3_2_case(
    case: S32SmokeCase,
    *,
    solver_name: str | None = None,
    solver=None,
) -> tuple[dict[str, Any], Any | None]:
    if solver is None:
        solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S3.2 static economic solves.")
    s3_2_assumptions = load_s3_2_static_economics_assumptions(
        sensitivity_case=case.s3_2_sensitivity_case
    )
    downstream_assumptions = _downstream_assumptions_for_case(case)
    model = build_site_static_economics_model(
        configuration_id=case.configuration_id,
        horizon_hours=case.horizon_hours,
        assumptions=s3_2_assumptions,
        downstream_assumptions=downstream_assumptions,
        case_options=S32CaseOptions(
            smoke_case_id=case.smoke_case,
            downstream_options=case.downstream_options,
            s3_2_sensitivity_case=case.s3_2_sensitivity_case,
            route_mode=case.route_mode,
        ),
    )
    start = time.perf_counter()
    result = _solve_model(model, solver)
    runtime = time.perf_counter() - start
    if _is_feasible(result) and case.horizon_hours <= 24:
        optimum_cost = float(value(model.total_static_operating_cost_eur))
        model.s3_2_cost_optimum_fixed = Constraint(
            expr=model.total_static_operating_cost_eur <= optimum_cost + 1e-4
        )
        model.s3_2_static_cost_objective.deactivate()
        model.s3_2_secondary_objective = Objective(
            expr=(
                model.horizon_reheated_tonnage
                + 0.01 * model.horizon_startup_count
                + 0.001
                * sum(
                    model.dsp_throughput_variation[t]
                    + model.reheater_throughput_variation[t]
                    + model.hsm_throughput_variation[t]
                    for t in model.TIME
                )
            )
        )
        secondary_start = time.perf_counter()
        result = _solve_model(model, solver)
        runtime += time.perf_counter() - secondary_start
    if _is_feasible(result):
        return _feasible_row(case, model, result, runtime, solver_name or "unknown"), model
    return _infeasible_row(case, model, result, runtime, solver_name or "unknown"), None


def _required_outcomes_met(rows: list[dict[str, Any]], cases: tuple[S32SmokeCase, ...]) -> bool:
    expected = {case.smoke_case: case.expected_outcome for case in cases}
    for row in rows:
        if row["smoke_case"] not in expected:
            continue
        termination = str(row["termination_condition"]).lower()
        if expected[row["smoke_case"]] == "optimal" and termination not in {"optimal", "feasible"}:
            return False
        if expected[row["smoke_case"]] == "infeasible" and "infeasible" not in termination:
            return False
    return True


def run_s3_2_smoke_suite(
    *,
    write_outputs: bool = True,
    include_168h: bool = True,
    include_sensitivities: bool = True,
) -> dict[str, Any]:
    solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S3.2 static economic solves.")
    mandatory_cases = required_s3_2_smoke_cases()
    cases = list(mandatory_cases)
    if include_168h:
        cases.extend(required_s3_2_168h_cases())
    if include_sensitivities:
        cases.extend(s3_2_sensitivity_cases())
    rows: list[dict[str, Any]] = []
    for case in cases:
        row, _ = solve_s3_2_case(case, solver_name=solver_name, solver=solver)
        rows.append(row)
    if write_outputs:
        pd.DataFrame(rows).to_csv(DEFAULT_RESULT_REGISTER, index=False)
    all_required = _required_outcomes_met(rows, mandatory_cases)
    all_168h = _required_outcomes_met(rows, required_s3_2_168h_cases()) if include_168h else False
    return {
        "solver_name": solver_name,
        "results": rows,
        "all_required_24h_outcomes_met": all_required,
        "all_required_168h_outcomes_met": all_168h,
        "s3_2_freeze_ready": bool(all_required and all_168h),
    }


def validate_inputs_only() -> dict[str, Any]:
    assumptions = load_s3_2_static_economics_assumptions()
    return {
        "assumption_set_id": assumptions.assumption_set_id,
        "static_cost_ready": assumptions.static_cost_ready,
        "route_cost_coverage_complete": assumptions.route_cost_coverage_complete,
        "complete_direct_emissions_ready": assumptions.complete_direct_emissions_ready,
        "thesis_usability": assumptions.thesis_usability,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S3.2 static material-energy-carbon economic smokes.")
    parser.add_argument("--validate-inputs-only", action="store_true")
    parser.add_argument("--suite", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--skip-168h", action="store_true")
    parser.add_argument("--skip-sensitivities", action="store_true")
    parser.add_argument("--output-path", type=Path, default=None)
    args = parser.parse_args()

    if args.validate_inputs_only:
        print(json.dumps(validate_inputs_only(), indent=2))
        return 0
    if args.suite:
        payload = run_s3_2_smoke_suite(
            write_outputs=not args.no_write,
            include_168h=not args.skip_168h,
            include_sensitivities=not args.skip_sensitivities,
        )
        if args.output_path is not None:
            args.output_path.parent.mkdir(parents=True, exist_ok=True)
            args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        else:
            print(json.dumps(payload, indent=2))
        return 0 if payload["all_required_24h_outcomes_met"] else 1
    print(json.dumps(validate_inputs_only(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
