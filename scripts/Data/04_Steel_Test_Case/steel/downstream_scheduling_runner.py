from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Constraint, Objective, SolverFactory, TerminationCondition, value

from .downstream_scheduling_builder import DownstreamCaseOptions, build_downstream_scheduling_model
from .downstream_scheduling_inputs import DownstreamAssumptions, load_downstream_assumptions


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RESULT_REGISTER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S2"
    / "s2_candidate_review"
    / "s2_13_downstream_smoke_result_register.csv"
)
DEFAULT_FIXED_PROFILE_ROOT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "fixed_profiles"
)
DEFAULT_SOLVER_PREFERENCE = ("gurobi", "appsi_highs", "highs", "cbc", "glpk")
OPTIMAL_TERMINATIONS = {TerminationCondition.optimal, TerminationCondition.feasible}


@dataclass(frozen=True)
class SmokeCaseDefinition:
    smoke_case: str
    configuration_id: str
    options: DownstreamCaseOptions
    expected_outcome: str
    write_profile: bool = False


def required_smoke_cases() -> tuple[SmokeCaseDefinition, ...]:
    return (
        SmokeCaseDefinition(
            smoke_case="c0_base_downstream",
            configuration_id="C0_current_BF_BOF_reference",
            options=DownstreamCaseOptions(smoke_case_id="c0_base_downstream"),
            expected_outcome="optimal",
            write_profile=True,
        ),
        SmokeCaseDefinition(
            smoke_case="c1_central_downstream",
            configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            options=DownstreamCaseOptions(smoke_case_id="c1_central_downstream"),
            expected_outcome="optimal",
            write_profile=True,
        ),
        SmokeCaseDefinition(
            smoke_case="recoverable_hsm_outage",
            configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            options=DownstreamCaseOptions(
                smoke_case_id="recoverable_hsm_outage",
                hsm_unavailable_hours=(8, 9, 10, 11),
                hsm_capacity_multiplier=1.15,
            ),
            expected_outcome="optimal",
        ),
        SmokeCaseDefinition(
            smoke_case="cold_slab_anti_free_battery",
            configuration_id="C0_current_BF_BOF_reference",
            options=DownstreamCaseOptions(
                smoke_case_id="cold_slab_anti_free_battery",
                hsm_unavailable_hours=(8, 9, 10, 11),
                reheater_enabled=False,
                require_cold_slab_creation=True,
            ),
            expected_outcome="infeasible",
        ),
        SmokeCaseDefinition(
            smoke_case="hard_target_stress_infeasible",
            configuration_id="C0_current_BF_BOF_reference",
            options=DownstreamCaseOptions(
                smoke_case_id="hard_target_stress_infeasible",
                hsm_unavailable_hours=(6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
                hsm_capacity_multiplier=0.5,
            ),
            expected_outcome="infeasible",
        ),
    )


def available_solver(preferred_solvers: tuple[str, ...] = DEFAULT_SOLVER_PREFERENCE):
    for solver_name in preferred_solvers:
        try:
            solver = SolverFactory(solver_name)
        except Exception:
            solver = None
        if solver is not None and solver.available(exception_flag=False):
            return solver_name, solver
    return None, None


def _solve_model(model, solver):
    try:
        return solver.solve(model, tee=False)
    except RuntimeError as exc:
        if "no solution can be loaded" not in str(exc).lower():
            raise
        return solver.solve(model, tee=False, load_solutions=False)


def _objective_value(model) -> float | None:
    active = list(model.component_data_objects(Objective, active=True, descend_into=True))
    if not active:
        return None
    return float(value(active[0]))


def _mip_gap(result) -> str:
    for attr in ("mip_gap", "gap"):
        candidate = getattr(result.solver, attr, None)
        if candidate is not None:
            return str(candidate)
    return "not_reported_by_solver"


def _is_feasible_result(result) -> bool:
    return result is not None and result.solver.termination_condition in OPTIMAL_TERMINATIONS


def _constraint_residual(constraint) -> float:
    body_value = float(value(constraint.body))
    if constraint.equality:
        return abs(body_value - float(value(constraint.lower)))
    return 0.0


def max_material_balance_residual(model) -> float:
    balance_component_names = {
        "liquid_steel_to_secondary_metallurgy",
        "secondary_metallurgy_delay",
        "caster_input_link",
        "casting_delay",
        "hot_slab_age_inventory_balance",
        "hot_slab_expiry_to_cold_yard",
        "cold_slab_inventory_balance",
        "reheating_delay",
        "reheated_slab_queue_balance",
        "hsm_total_slab_input_link",
        "dsp_output_yield",
        "hsm_output_yield",
        "final_product_balance",
    }
    residuals = []
    for constraint in model.component_data_objects(Constraint, active=True, descend_into=True):
        if constraint.parent_component().name in balance_component_names:
            residuals.append(_constraint_residual(constraint))
    return 0.0 if not residuals else max(residuals)


def _safe_value(expr) -> float | None:
    try:
        return float(value(expr))
    except Exception:
        return None


def _sum_binary(var, time_set) -> float | None:
    try:
        return float(sum(value(var[t]) for t in time_set))
    except Exception:
        return None


def _terminal_hot_total(model) -> float | None:
    try:
        last = max(model.TIME)
        return float(sum(value(model.hot_slab_inventory[age, last]) for age in model.HOT_AGES))
    except Exception:
        return None


def solve_downstream_case(
    case: SmokeCaseDefinition,
    *,
    solver_name: str | None = None,
    solver=None,
    horizon_hours: int = 24,
) -> tuple[dict[str, Any], Any | None]:
    if solver is None:
        solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S2.13 downstream smoke solves.")

    assumptions = load_downstream_assumptions(
        configuration_id=case.configuration_id,
        horizon_hours=horizon_hours,
    )
    model = build_downstream_scheduling_model(
        configuration_id=case.configuration_id,
        horizon_hours=horizon_hours,
        assumptions=assumptions,
        case_options=case.options,
    )
    wall_start = time.perf_counter()
    primary_result = _solve_model(model, solver)
    runtime = time.perf_counter() - wall_start
    final_result = primary_result
    primary_feasible = _is_feasible_result(primary_result)

    if primary_feasible:
        optimum_overproduction = float(value(model.final_product_overproduction))
        model.primary_optimum_fixed = Constraint(expr=model.final_product_overproduction <= optimum_overproduction + 1e-7)
        model.primary_objective.deactivate()
        model.secondary_objective.activate()
        secondary_start = time.perf_counter()
        final_result = _solve_model(model, solver)
        runtime += time.perf_counter() - secondary_start

    feasible = _is_feasible_result(final_result)
    stats = model.s2_13_model_stats
    terminal_cold_deviation = None
    if feasible:
        terminal_cold_deviation = abs(
            float(value(model.cold_slab_inventory[max(model.TIME)]))
            - assumptions.initial_cold_slab_inventory_t * assumptions.terminal_cold_inventory_ratio
        )
    row = {
        "result_id": f"S213_{case.smoke_case}",
        "smoke_case": case.smoke_case,
        "configuration_id": case.configuration_id,
        "horizon_hours": horizon_hours,
        "assumption_set_id": assumptions.assumption_set_id,
        "solver_name": solver_name,
        "solver_status": str(final_result.solver.status) if final_result is not None else "not_attempted",
        "termination_condition": str(final_result.solver.termination_condition) if final_result is not None else "not_attempted",
        "objective_value": _objective_value(model) if feasible else "",
        "runtime_seconds": round(runtime, 6),
        "mip_gap": _mip_gap(final_result) if final_result is not None else "not_attempted",
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": assumptions.final_product_target_t,
        "final_product_output_t": _safe_value(model.horizon_final_product_output) if feasible else "",
        "liquid_steel_input_t": _safe_value(model.horizon_liquid_steel_input) if feasible else "",
        "dsp_output_t": _safe_value(model.horizon_dsp_output) if feasible else "",
        "hsm_output_t": _safe_value(model.horizon_hsm_output) if feasible else "",
        "hot_charge_t": _safe_value(model.horizon_hot_charge_tonnage) if feasible else "",
        "reheated_t": _safe_value(model.horizon_reheated_tonnage) if feasible else "",
        "max_cold_slab_inventory_t": (
            max(float(value(model.cold_slab_inventory[t])) for t in model.TIME) if feasible else ""
        ),
        "terminal_cold_slab_deviation_t": terminal_cold_deviation if feasible else "",
        "terminal_hot_slab_t": _terminal_hot_total(model) if feasible else "",
        "terminal_reheated_queue_t": (
            float(value(model.reheated_slab_queue[max(model.TIME)])) if feasible else ""
        ),
        "max_material_balance_residual_t": max_material_balance_residual(model) if feasible else "",
        "startup_count": _safe_value(model.horizon_startup_count) if feasible else "",
        "shortfall_slack_present": "false",
        "infeasibility_class": "" if feasible else _classify_infeasibility(case, final_result),
        "thesis_usability": "false",
        "limitations": "development-only S2.13 smoke; Tier-D mechanics; not Tata-exact; no market logic",
        "notes": _case_notes(case, feasible),
    }
    return row, model if feasible else None


def _classify_infeasibility(case: SmokeCaseDefinition, result) -> str:
    termination = "" if result is None else str(result.solver.termination_condition).lower()
    if "infeasible" in termination and case.smoke_case == "cold_slab_anti_free_battery":
        return "cold_slab_reheating_disabled_bypass_blocked"
    if "infeasible" in termination:
        return "hard_final_product_target_infeasible_under_selected_capacity_or_outage"
    return f"non_optimal_termination_{termination}"


def _case_notes(case: SmokeCaseDefinition, feasible: bool) -> str:
    if case.smoke_case == "recoverable_hsm_outage":
        return "HSM unavailable for four contiguous hours; should recover through slab yard and reheating."
    if case.smoke_case == "cold_slab_anti_free_battery":
        return "Reheating disabled while cold-slab creation is required; infeasibility confirms no cold bypass."
    if case.smoke_case == "hard_target_stress_infeasible":
        return "HSM outage and capacity reduction intentionally make the hard final target infeasible."
    return "Base downstream smoke solved with hard final-product target." if feasible else "Base smoke did not solve."


def _profile_rows_from_model(model, *, profile_package_id: str) -> list[dict[str, Any]]:
    assumptions: DownstreamAssumptions = model.s2_13_assumptions
    metadata = model.s2_13_metadata
    rows = []
    for t in model.TIME:
        hot_inventory = ";".join(
            f"age_{age}={round(float(value(model.hot_slab_inventory[age, t])), 9)}"
            for age in model.HOT_AGES
        )
        rows.append(
            {
                "profile_package_id": profile_package_id,
                "configuration_id": metadata["configuration_id"],
                "time_index": int(t),
                "timestamp_utc": _timestamp_for_index(assumptions.profile_start_utc, int(t)),
                "timestep_hours": 1.0,
                "source_model_stage": "S2.13_downstream_scheduling_extension",
                "source_config_id": metadata["configuration_id"],
                "profile_content_hash": "",
                "profile_extraction_method": "direct_from_S2_13_downstream_model_solution",
                "s2_13_assumption_set_id": assumptions.assumption_set_id,
                "route_share_policy": f"bf_bof={assumptions.bf_bof_share};drp_eaf={assumptions.drp_eaf_share}",
                "liquid_steel_production_t": round(float(value(model.secondary_metallurgy_input[t])), 9),
                "secondary_metallurgy_throughput_t": round(float(value(model.secondary_metallurgy_output[t])), 9),
                "caster_throughput_t": round(float(value(model.caster_input[t])), 9),
                "cast_slab_output_t": round(float(value(model.cast_slab_output[t])), 9),
                "hot_slab_age_bucket_inventories_t": hot_inventory,
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 9),
                "dsp_hot_slab_input_t": round(float(value(model.dsp_hot_slab_input[t])), 9),
                "dsp_output_t": round(float(value(model.dsp_product_output[t])), 9),
                "reheat_throughput_t": round(float(value(model.reheat_cold_slab_input[t])), 9),
                "reheated_slab_output_t": round(float(value(model.reheated_slab_output[t])), 9),
                "hsm_hot_slab_input_t": round(float(value(model.hsm_hot_slab_input[t])), 9),
                "hsm_reheated_slab_input_t": round(float(value(model.hsm_reheated_slab_input[t])), 9),
                "hsm_output_t": round(float(value(model.hsm_product_output[t])), 9),
                "final_product_output_t": round(float(value(model.final_product_output[t])), 9),
                "dsp_on": int(round(float(value(model.dsp_on[t])))),
                "reheater_on": int(round(float(value(model.reheater_on[t])))),
                "hsm_on": int(round(float(value(model.hsm_on[t])))),
                "dsp_startup": int(round(float(value(model.dsp_startup[t])))),
                "reheater_startup": int(round(float(value(model.reheater_startup[t])))),
                "hsm_startup": int(round(float(value(model.hsm_startup[t])))),
                "dsp_shutdown": int(round(float(value(model.dsp_shutdown[t])))),
                "reheater_shutdown": int(round(float(value(model.reheater_shutdown[t])))),
                "hsm_shutdown": int(round(float(value(model.hsm_shutdown[t])))),
                "continuous_casting_electricity_driver_t": round(float(value(model.caster_input[t])), 9),
                "dsp_electricity_driver_t": round(float(value(model.dsp_hot_slab_input[t])), 9),
                "slab_handling_electricity_driver_t": round(float(value(model.hot_slab_to_cold[t])), 9),
                "reheating_fuel_heat_driver_t": round(float(value(model.reheat_cold_slab_input[t])), 9),
                "hsm_electricity_driver_t": round(float(value(model.hsm_total_slab_input[t])), 9),
                "hot_charge_tonnage_t": round(float(value(model.dsp_hot_slab_input[t] + model.hsm_hot_slab_input[t])), 9),
                "cold_charge_reheated_tonnage_t": round(float(value(model.hsm_reheated_slab_input[t])), 9),
                "cold_slab_dwell_indicator_t": round(float(value(model.cold_slab_inventory[t])), 9),
                "direct_emissions_driver_hook_t": round(float(value(model.reheat_cold_slab_input[t])), 9),
                "wag_compatible_reheating_fuel_demand_hook_t": round(float(value(model.reheat_cold_slab_input[t])), 9),
                "thesis_usability": "false",
                "limitations": "development-only governed S2.13 profile; no prices, revenue, DA, stochastic, CVaR, mFRR, tariff, or ETS logic",
            }
        )
    digest = hashlib.sha256(
        json.dumps(
            [{k: str(v) for k, v in row.items() if k != "profile_content_hash"} for row in rows],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    for row in rows:
        row["profile_content_hash"] = digest
    return rows


def _timestamp_for_index(start_utc: str, time_index: int) -> str:
    start = pd.Timestamp(start_utc)
    return (start + pd.Timedelta(hours=time_index)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_profile_snapshot(model, *, output_root: Path = DEFAULT_FIXED_PROFILE_ROOT) -> Path:
    config_id = model.s2_13_metadata["configuration_id"]
    if config_id == "C0_current_BF_BOF_reference":
        filename = "c0_s2_13_downstream_profile_24h_dev.csv"
        package_id = "S213_C0_DOWNSTREAM_PROFILE_24H_DEV"
    elif config_id == "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF":
        filename = "c1_central_s2_13_downstream_profile_24h_dev.csv"
        package_id = "S213_C1_CENTRAL_DOWNSTREAM_PROFILE_24H_DEV"
    else:
        raise ValueError(f"Unsupported S2.13 profile configuration {config_id!r}.")
    output_root.mkdir(parents=True, exist_ok=True)
    rows = _profile_rows_from_model(model, profile_package_id=package_id)
    path = output_root / filename
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def run_required_smoke_suite(*, write_outputs: bool = True) -> dict[str, Any]:
    solver_name, solver = available_solver()
    if solver is None:
        raise RuntimeError("No configured MILP solver is available for S2.13 downstream smoke solves.")
    rows: list[dict[str, Any]] = []
    profile_paths: list[str] = []
    for case in required_smoke_cases():
        row, model = solve_downstream_case(case, solver_name=solver_name, solver=solver)
        rows.append(row)
        if write_outputs and case.write_profile and model is not None:
            profile_paths.append(str(write_profile_snapshot(model)))
    if write_outputs:
        pd.DataFrame(rows).to_csv(DEFAULT_RESULT_REGISTER, index=False)
    return {
        "solver_name": solver_name,
        "results": rows,
        "profile_paths": profile_paths,
        "all_required_outcomes_met": _required_outcomes_met(rows),
        "optional_168h_status": "skipped_not_run_to_keep_task_within_24h_gate_and_avoid_extra_tracked_snapshots",
    }


def _required_outcomes_met(rows: list[dict[str, Any]]) -> bool:
    expected = {case.smoke_case: case.expected_outcome for case in required_smoke_cases()}
    for row in rows:
        termination = str(row["termination_condition"]).lower()
        is_optimal = termination in {"optimal", "feasible"}
        is_infeasible = "infeasible" in termination
        if expected[row["smoke_case"]] == "optimal" and not is_optimal:
            return False
        if expected[row["smoke_case"]] == "infeasible" and not is_infeasible:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run governed S2.13 downstream scheduling smoke solves.")
    parser.add_argument("--no-write", action="store_true", help="Solve in memory without writing governed registers/profiles.")
    args = parser.parse_args()
    payload = run_required_smoke_suite(write_outputs=not args.no_write)
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_required_outcomes_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
