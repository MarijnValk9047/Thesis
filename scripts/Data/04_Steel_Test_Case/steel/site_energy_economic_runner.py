from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Constraint, Objective, SolverFactory, TerminationCondition, value

from .downstream_scheduling_builder import DownstreamCaseOptions
from .downstream_scheduling_runner import (
    _mip_gap,
    _solve_model,
    available_solver,
    max_material_balance_residual,
)
from .site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID, IntegratedCaseOptions, build_site_energy_economic_model
from .site_energy_economic_inputs import DEFAULT_S3_1_ENERGY_INPUT_PATH, DEFAULT_S3_1_PRICE_INPUT_PATH, WAG_CARRIERS, load_site_energy_economic_assumptions


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
    / "s3_1_smoke_result_register.csv"
)
OPTIMAL_TERMINATIONS = {TerminationCondition.optimal, TerminationCondition.feasible}


@dataclass(frozen=True)
class IntegratedSmokeCase:
    smoke_case: str
    configuration_id: str
    options: IntegratedCaseOptions
    expected_outcome: str
    notes: str


def required_integrated_smoke_cases() -> tuple[IntegratedSmokeCase, ...]:
    return (
        IntegratedSmokeCase(
            smoke_case="c0_integrated_central",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="c0_integrated_central",
                downstream_options=DownstreamCaseOptions(smoke_case_id="c0_integrated_central"),
            ),
            expected_outcome="optimal",
            notes="C0 integrated deterministic energy/emissions diagnostic.",
        ),
        IntegratedSmokeCase(
            smoke_case="c1_central_integrated",
            configuration_id=C1_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="c1_central_integrated",
                downstream_options=DownstreamCaseOptions(smoke_case_id="c1_central_integrated"),
            ),
            expected_outcome="optimal",
            notes="C1 central route-share integrated deterministic energy/emissions diagnostic.",
        ),
        IntegratedSmokeCase(
            smoke_case="recoverable_hsm_outage_integrated",
            configuration_id=C1_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="recoverable_hsm_outage_integrated",
                downstream_options=DownstreamCaseOptions(
                    smoke_case_id="recoverable_hsm_outage_integrated",
                    hsm_unavailable_hours=(8, 9, 10, 11),
                    hsm_capacity_multiplier=1.15,
                ),
            ),
            expected_outcome="optimal",
            notes="Recoverable four-hour HSM outage with slab buffering and reheating.",
        ),
        IntegratedSmokeCase(
            smoke_case="all_hot_reference",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="all_hot_reference",
                downstream_options=DownstreamCaseOptions(smoke_case_id="all_hot_reference"),
            ),
            expected_outcome="optimal",
            notes="All-hot feasible reference for the same fixed production target.",
        ),
        IntegratedSmokeCase(
            smoke_case="cold_heavy_diagnostic",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="cold_heavy_diagnostic",
                downstream_options=DownstreamCaseOptions(
                    smoke_case_id="cold_heavy_diagnostic",
                    hsm_capacity_multiplier=1.15,
                    require_cold_slab_creation=True,
                ),
            ),
            expected_outcome="optimal",
            notes="Controlled cold-heavy diagnostic requiring cold-slab creation and reheating.",
        ),
        IntegratedSmokeCase(
            smoke_case="hard_target_stress_infeasible_integrated",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="hard_target_stress_infeasible_integrated",
                downstream_options=DownstreamCaseOptions(
                    smoke_case_id="hard_target_stress_infeasible_integrated",
                    hsm_unavailable_hours=(6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
                    hsm_capacity_multiplier=0.5,
                ),
            ),
            expected_outcome="infeasible",
            notes="Hard final-product target stress case; accounting layer must not restore fake feasibility.",
        ),
    )


def sensitivity_cases() -> tuple[IntegratedSmokeCase, ...]:
    return (
        IntegratedSmokeCase(
            smoke_case="sensitivity_low_energy_coefficients",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="sensitivity_low_energy_coefficients",
                downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_low_energy_coefficients"),
                sensitivity_case="low",
            ),
            expected_outcome="optimal",
            notes="Grouped low sensitivity for selected S3.1 energy coefficients.",
        ),
        IntegratedSmokeCase(
            smoke_case="sensitivity_high_energy_coefficients",
            configuration_id=C0_CONFIGURATION_ID,
            options=IntegratedCaseOptions(
                smoke_case_id="sensitivity_high_energy_coefficients",
                downstream_options=DownstreamCaseOptions(smoke_case_id="sensitivity_high_energy_coefficients"),
                sensitivity_case="high",
            ),
            expected_outcome="optimal",
            notes="Grouped high sensitivity for selected S3.1 energy coefficients.",
        ),
    )


def _is_feasible(result) -> bool:
    return result is not None and result.solver.termination_condition in OPTIMAL_TERMINATIONS


def _objective_value(model) -> float | None:
    active = list(model.component_data_objects(Objective, active=True, descend_into=True))
    if not active:
        return None
    return float(value(active[0]))


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


def _max_cold_inventory(model) -> float:
    return float(max(value(model.cold_slab_inventory[t]) for t in model.TIME))


def _terminal_cold_deviation(model) -> float:
    assumptions = model.s2_13_assumptions
    return abs(
        float(value(model.cold_slab_inventory[max(model.TIME)]))
        - assumptions.initial_cold_slab_inventory_t * assumptions.terminal_cold_inventory_ratio
    )


def _terminal_hot_total(model) -> float:
    last = max(model.TIME)
    return float(sum(value(model.hot_slab_inventory[age, last]) for age in model.HOT_AGES))


def _max_wag_balance_residual(model) -> float:
    residuals = []
    for constraint in model.wag_carrier_balance.values():
        residuals.append(abs(float(value(constraint.body)) - float(value(constraint.lower))))
    return 0.0 if not residuals else max(residuals)


def _max_electricity_balance_residual(model) -> float:
    residuals = []
    for constraint in model.grid_import_balance.values():
        residuals.append(abs(float(value(constraint.body)) - float(value(constraint.lower))))
    return 0.0 if not residuals else max(residuals)


def _max_reheating_balance_residual(model) -> float:
    residuals = []
    for constraint in model.reheating_heat_balance.values():
        residuals.append(abs(float(value(constraint.body)) - float(value(constraint.lower))))
    return 0.0 if not residuals else max(residuals)


def _round(value_obj: float | str, digits: int = 6) -> float | str:
    if value_obj == "":
        return ""
    return round(float(value_obj), digits)


def _classify_infeasibility(case: IntegratedSmokeCase, result) -> str:
    termination = "" if result is None else str(result.solver.termination_condition).lower()
    if "infeasible" in termination and "stress" in case.smoke_case:
        return "hard_final_product_target_infeasible_accounting_layer_no_fake_feasibility"
    return f"non_optimal_termination_{termination}"


def _feasible_row(case: IntegratedSmokeCase, model, result, runtime: float, solver_name: str) -> dict[str, Any]:
    stats = model.s3_1_model_stats
    assumptions = model.s3_1_assumptions
    wag_co2_by_carrier = {
        carrier: _sum_carrier_expr(model, "wag_co2_t", carrier)
        for carrier in WAG_CARRIERS
    }
    total_wag_co2 = sum(wag_co2_by_carrier.values())
    costs_ready = assumptions.monetary_values_ready
    return {
        "result_id": f"S31_{case.smoke_case}",
        "smoke_case": case.smoke_case,
        "configuration_id": case.configuration_id,
        "horizon_hours": len(model.TIME),
        "assumption_set_id": assumptions.assumption_set_id,
        "sensitivity_case": assumptions.sensitivity_case,
        "objective_mode": model.s3_1_metadata["objective_mode"],
        "objective_type": "energy_emissions_diagnostic",
        "static_cost_result": "false",
        "wag_driver_basis_status": model.s3_1_metadata["wag_driver_basis_status"],
        "solver_name": solver_name,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value": _round(_objective_value(model)),
        "runtime_seconds": round(runtime, 6),
        "mip_gap": _mip_gap(result),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": _round(model.s2_13_assumptions.final_product_target_t),
        "final_product_output_t": _round(value(model.horizon_final_product_output)),
        "liquid_steel_input_t": _round(value(model.horizon_liquid_steel_input)),
        "bof_liquid_steel_t": _round(value(model.bof_route_total)),
        "bf_hot_metal_driver_t": _round(_sum_expr(model, "bf_hot_metal_driver_t")),
        "cog_dry_coal_driver_t": _round(_sum_expr(model, "cog_dry_coal_driver_t")),
        "eaf_liquid_steel_t": _round(value(model.eaf_route_total)),
        "bf_bof_share": _round(value(model.bof_route_total) / value(model.route_total_liquid_steel_source)),
        "drp_eaf_share": _round(value(model.eaf_route_total) / value(model.route_total_liquid_steel_source)),
        "dsp_output_t": _round(value(model.horizon_dsp_output)),
        "hsm_output_t": _round(value(model.horizon_hsm_output)),
        "hot_charge_t": _round(value(model.horizon_hot_charge_tonnage)),
        "cold_slab_to_yard_t": _round(value(model.horizon_hot_slab_to_cold)),
        "reheated_t": _round(value(model.horizon_reheated_tonnage)),
        "max_cold_slab_inventory_t": _round(_max_cold_inventory(model)),
        "terminal_cold_slab_deviation_t": _round(_terminal_cold_deviation(model), 9),
        "terminal_hot_slab_t": _round(_terminal_hot_total(model), 9),
        "terminal_reheated_queue_t": _round(value(model.reheated_slab_queue[max(model.TIME)]), 9),
        "startup_count": _round(value(model.horizon_startup_count)),
        "secondary_metallurgy_electricity_mwh": _round(_sum_expr(model, "secondary_metallurgy_electricity_mwh")),
        "casting_electricity_mwh": _round(_sum_expr(model, "casting_electricity_mwh")),
        "slab_handling_electricity_mwh": _round(_sum_expr(model, "slab_handling_electricity_mwh")),
        "dsp_electricity_mwh": _round(_sum_expr(model, "dsp_electricity_mwh")),
        "reheating_electricity_mwh": _round(_sum_expr(model, "reheating_electricity_mwh")),
        "hsm_electricity_mwh": _round(_sum_expr(model, "hsm_electricity_mwh")),
        "asu_electricity_mwh": _round(_sum_expr(model, "asu_electricity_mwh")),
        "residual_auxiliary_electricity_mwh": _round(_sum_expr(model, "residual_auxiliary_electricity_mwh")),
        "drp_electricity_mwh": _round(_sum_expr(model, "drp_electricity_mwh")),
        "eaf_electricity_mwh": _round(_sum_expr(model, "eaf_electricity_mwh")),
        "gross_electricity_mwh": _round(value(model.horizon_gross_electricity_mwh)),
        "wag_power_output_mwh": _round(value(model.horizon_wag_power_output_mwh)),
        "potential_wag_power_output_mwh": _round(value(model.horizon_potential_wag_power_output_mwh)),
        "grid_import_mwh": _round(value(model.horizon_grid_import_mwh)),
        "drp_natural_gas_m3": _round(value(model.horizon_drp_natural_gas_m3)),
        "natural_gas_import_gj": _round(value(model.horizon_natural_gas_import_gj)),
        "reheating_heat_gj": _round(value(model.horizon_reheating_heat_gj)),
        "bfg_generated_gj": _round(_sum_expr(model, "bfg_generated_gj")),
        "cog_generated_gj": _round(_sum_expr(model, "cog_generated_gj")),
        "bofg_generated_gj": _round(_sum_expr(model, "bofg_generated_gj")),
        "total_wag_generated_gj": _round(value(model.horizon_total_wag_generated_gj)),
        "wag_process_use_gj": _round(sum(_sum_carrier_expr(model, "wag_process_use_gj", carrier) for carrier in WAG_CARRIERS)),
        "wag_steam_boiler_use_gj": _round(sum(_sum_carrier_expr(model, "wag_steam_boiler_use_gj", carrier) for carrier in WAG_CARRIERS)),
        "wag_reheating_use_gj": _round(sum(_sum_carrier_expr(model, "wag_reheating_use_gj", carrier) for carrier in WAG_CARRIERS)),
        "flare_spill_gj": _round(value(model.horizon_flare_spill_gj)),
        "wag_co2_t": _round(total_wag_co2),
        "drp_direct_co2_proxy_t": _round(value(model.horizon_drp_direct_co2_proxy_t)),
        "drp_ng_combustion_co2_t": "",
        "reheating_co2_t": _round(value(model.horizon_reheating_co2_t)),
        "total_direct_co2_t": _round(value(model.horizon_total_direct_co2_t)),
        "complete_direct_emissions_ready": str(assumptions.complete_direct_emissions_ready).lower(),
        "scope2_electricity_counted": str(assumptions.scope2_electricity_counted).lower(),
        "ets_ready": str(assumptions.ets_ready).lower(),
        "double_counting_warning": "",
        "electricity_cost_eur": "" if not costs_ready else "",
        "natural_gas_cost_eur": "" if not costs_ready else "",
        "gross_co2_cost_eur": "" if not costs_ready else "",
        "flare_cost_eur": "" if not costs_ready else "",
        "startup_cost_eur": "" if not costs_ready else "",
        "tariff_cost_eur": "" if not costs_ready else "",
        "total_static_operating_cost_eur": "" if not costs_ready else "",
        "eur_per_t_final_product": "" if not costs_ready else "",
        "monetary_values_ready": str(costs_ready).lower(),
        "missing_price_inputs": ";".join(assumptions.missing_price_inputs),
        "max_material_balance_residual_t": _round(max_material_balance_residual(model), 12),
        "max_wag_balance_residual_gj": _round(_max_wag_balance_residual(model), 12),
        "max_electricity_balance_residual_mwh": _round(_max_electricity_balance_residual(model), 12),
        "max_reheating_balance_residual_gj": _round(_max_reheating_balance_residual(model), 12),
        "shortfall_slack_present": "false",
        "infeasibility_class": "",
        "thesis_usability": "false",
        "limitations": "development-only S3.1 energy/emissions diagnostic; prices missing; no DA settlement product revenue ETS free allocation stochastic CVaR or mFRR logic",
        "notes": case.notes,
    }


def _infeasible_row(case: IntegratedSmokeCase, model, result, runtime: float, solver_name: str) -> dict[str, Any]:
    stats = model.s3_1_model_stats
    return {
        "result_id": f"S31_{case.smoke_case}",
        "smoke_case": case.smoke_case,
        "configuration_id": case.configuration_id,
        "horizon_hours": len(model.TIME),
        "assumption_set_id": model.s3_1_assumptions.assumption_set_id,
        "sensitivity_case": model.s3_1_assumptions.sensitivity_case,
        "objective_mode": model.s3_1_metadata["objective_mode"],
        "objective_type": "energy_emissions_diagnostic",
        "static_cost_result": "false",
        "wag_driver_basis_status": model.s3_1_metadata["wag_driver_basis_status"],
        "solver_name": solver_name,
        "solver_status": str(result.solver.status) if result is not None else "not_attempted",
        "termination_condition": str(result.solver.termination_condition) if result is not None else "not_attempted",
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
        "bf_hot_metal_driver_t": "",
        "cog_dry_coal_driver_t": "",
        "eaf_liquid_steel_t": "",
        "bf_bof_share": "",
        "drp_eaf_share": "",
        "dsp_output_t": "",
        "hsm_output_t": "",
        "hot_charge_t": "",
        "cold_slab_to_yard_t": "",
        "reheated_t": "",
        "max_cold_slab_inventory_t": "",
        "terminal_cold_slab_deviation_t": "",
        "terminal_hot_slab_t": "",
        "terminal_reheated_queue_t": "",
        "startup_count": "",
        "secondary_metallurgy_electricity_mwh": "",
        "casting_electricity_mwh": "",
        "slab_handling_electricity_mwh": "",
        "dsp_electricity_mwh": "",
        "reheating_electricity_mwh": "",
        "hsm_electricity_mwh": "",
        "asu_electricity_mwh": "",
        "residual_auxiliary_electricity_mwh": "",
        "drp_electricity_mwh": "",
        "eaf_electricity_mwh": "",
        "gross_electricity_mwh": "",
        "wag_power_output_mwh": "",
        "potential_wag_power_output_mwh": "",
        "grid_import_mwh": "",
        "drp_natural_gas_m3": "",
        "natural_gas_import_gj": "",
        "reheating_heat_gj": "",
        "bfg_generated_gj": "",
        "cog_generated_gj": "",
        "bofg_generated_gj": "",
        "total_wag_generated_gj": "",
        "wag_process_use_gj": "",
        "wag_steam_boiler_use_gj": "",
        "wag_reheating_use_gj": "",
        "flare_spill_gj": "",
        "wag_co2_t": "",
        "drp_direct_co2_proxy_t": "",
        "drp_ng_combustion_co2_t": "",
        "reheating_co2_t": "",
        "total_direct_co2_t": "",
        "complete_direct_emissions_ready": "false",
        "scope2_electricity_counted": "false",
        "ets_ready": "false",
        "double_counting_warning": "",
        "electricity_cost_eur": "",
        "natural_gas_cost_eur": "",
        "gross_co2_cost_eur": "",
        "flare_cost_eur": "",
        "startup_cost_eur": "",
        "tariff_cost_eur": "",
        "total_static_operating_cost_eur": "",
        "eur_per_t_final_product": "",
        "monetary_values_ready": "false",
        "missing_price_inputs": ";".join(model.s3_1_assumptions.missing_price_inputs),
        "max_material_balance_residual_t": "",
        "max_wag_balance_residual_gj": "",
        "max_electricity_balance_residual_mwh": "",
        "max_reheating_balance_residual_gj": "",
        "shortfall_slack_present": "false",
        "infeasibility_class": _classify_infeasibility(case, result),
        "thesis_usability": "false",
        "limitations": "development-only S3.1 stress diagnostic; infeasible hard target expected; no hidden shortfall slack",
        "notes": case.notes,
    }


def solve_integrated_case(
    case: IntegratedSmokeCase,
    *,
    solver_name: str | None = None,
    solver=None,
    horizon_hours: int = 24,
) -> tuple[dict[str, Any], Any | None]:
    if solver is None:
        solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S3.1 integrated smoke solves.")
    assumptions = load_site_energy_economic_assumptions(sensitivity_case=case.options.sensitivity_case)
    model = build_site_energy_economic_model(
        configuration_id=case.configuration_id,
        horizon_hours=horizon_hours,
        assumptions=assumptions,
        case_options=case.options,
    )
    start = time.perf_counter()
    result = _solve_model(model, solver)
    runtime = time.perf_counter() - start
    if _is_feasible(result):
        return _feasible_row(case, model, result, runtime, solver_name or "unknown"), model
    return _infeasible_row(case, model, result, runtime, solver_name or "unknown"), None


def _required_outcomes_met(rows: list[dict[str, Any]], cases: tuple[IntegratedSmokeCase, ...]) -> bool:
    expected = {case.smoke_case: case.expected_outcome for case in cases}
    for row in rows:
        if row["smoke_case"] not in expected:
            continue
        termination = str(row["termination_condition"]).lower()
        is_optimal = termination in {"optimal", "feasible"}
        is_infeasible = "infeasible" in termination
        if expected[row["smoke_case"]] == "optimal" and not is_optimal:
            return False
        if expected[row["smoke_case"]] == "infeasible" and not is_infeasible:
            return False
    return True


def run_integrated_smoke_suite(*, write_outputs: bool = True, include_sensitivities: bool = True) -> dict[str, Any]:
    solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S3.1 integrated smoke solves.")
    cases = required_integrated_smoke_cases()
    rows: list[dict[str, Any]] = []
    for case in cases:
        row, _ = solve_integrated_case(case, solver_name=solver_name, solver=solver)
        rows.append(row)
    if include_sensitivities:
        for case in sensitivity_cases():
            row, _ = solve_integrated_case(case, solver_name=solver_name, solver=solver)
            rows.append(row)
    if write_outputs:
        pd.DataFrame(rows).to_csv(DEFAULT_RESULT_REGISTER, index=False)
    return {
        "solver_name": solver_name,
        "results": rows,
        "all_required_outcomes_met": _required_outcomes_met(rows, cases),
        "optional_168h_status": "skipped_not_run_because_24h_mandatory_and_limited_sensitivity_cases_are_the_current_gate",
    }


def validate_inputs_only() -> dict[str, Any]:
    assumptions = load_site_energy_economic_assumptions()
    return {
        "energy_input_path": str(DEFAULT_S3_1_ENERGY_INPUT_PATH),
        "price_input_path": str(DEFAULT_S3_1_PRICE_INPUT_PATH),
        "assumption_set_id": assumptions.assumption_set_id,
        "monetary_values_ready": assumptions.monetary_values_ready,
        "missing_price_inputs": list(assumptions.missing_price_inputs),
        "complete_direct_emissions_ready": assumptions.complete_direct_emissions_ready,
        "scope2_electricity_counted": assumptions.scope2_electricity_counted,
        "ets_ready": assumptions.ets_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run S3.1 downstream-aware integrated energy/emissions diagnostics.")
    parser.add_argument("--validate-inputs-only", action="store_true")
    parser.add_argument("--configuration", default=C0_CONFIGURATION_ID)
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--static-accounting", action="store_true")
    parser.add_argument("--physical-diagnostic", action="store_true")
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--solver", default=None)
    parser.add_argument("--mip-gap", type=float, default=None)
    parser.add_argument("--time-limit", type=float, default=None)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--suite", action="store_true")
    args = parser.parse_args()

    if args.validate_inputs_only:
        print(json.dumps(validate_inputs_only(), indent=2))
        return 0

    assumptions = load_site_energy_economic_assumptions()
    if args.static_accounting and not assumptions.monetary_values_ready:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "static_cost_solve_requested_but_price_inputs_missing",
                    "missing_price_inputs": list(assumptions.missing_price_inputs),
                },
                indent=2,
            )
        )
        return 2

    if args.suite:
        payload = run_integrated_smoke_suite(write_outputs=not args.no_write)
    else:
        solver_name, solver = (args.solver, SolverFactory(args.solver)) if args.solver else available_solver()
        case = IntegratedSmokeCase(
            smoke_case="single_integrated_case",
            configuration_id=args.configuration,
            options=IntegratedCaseOptions(
                smoke_case_id="single_integrated_case",
                downstream_options=DownstreamCaseOptions(smoke_case_id="single_integrated_case"),
            ),
            expected_outcome="optimal",
            notes="Single requested integrated diagnostic case.",
        )
        row, _ = solve_integrated_case(case, solver_name=solver_name, solver=solver, horizon_hours=args.horizon_hours)
        payload = {"solver_name": solver_name, "results": [row], "all_required_outcomes_met": True}

    if args.output_path is not None:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("all_required_outcomes_met", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
