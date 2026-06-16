from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.contrib.solver.common.util import NoFeasibleSolutionError
from pyomo.environ import Constraint, Objective, SolverFactory, SolverStatus, TerminationCondition, minimize, value

from .liquid_steel_smoke_builder import (
    ALLOWED_CONFIGURATION_IDS,
    ALLOWED_OBJECTIVE_TYPES,
    DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    DEFAULT_REVIEW_ROOT,
    LiquidSteelSmokeBuilderError,
    PreparedSmokeInputs,
    _infer_output_carrier,
    build_liquid_steel_smoke_model,
    configure_liquid_steel_smoke_objective,
    validate_liquid_steel_smoke_inputs,
)
from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STEEL_SMOKE_RUN_ROOT = (
    REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "runs" / "steel_s2_liquid_smoke"
)
DEFAULT_BUFFER_INVENTORY_SUMMARY_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "s2_candidate_review"
    / "s2_buffer_inventory_smoke_summary.csv"
)
DEFAULT_BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "s2_candidate_review"
    / "s2_buffer_sensitivity_result_summary.csv"
)
DEFAULT_ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "s2_candidate_review"
    / "s2_one_week_buffer_smoke_summary.csv"
)
DEFAULT_SOLVER_PREFERENCE = ("gurobi", "appsi_highs", "highs", "cbc", "glpk")
SCOPE_ID = "restricted_liquid_steel_smoke"
MAX_SENSITIVITY_CAPACITY_MULTIPLIER = 4.0
DEFAULT_OBJECTIVE_TYPE = "minimise_overproduction_dev_only"
ZERO_HIT_ATTRIBUTION_REGISTER_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "s2_candidate_review"
    / "s2_zero_hit_attribution_register.csv"
)


def _normalise_run_slug(
    configuration_id: str,
    horizon_hours: int,
    target_variant: str,
    inventory_mode: str,
    sensitivity_id: str,
    timestamp: datetime,
) -> str:
    configuration_short = configuration_id.split("_", 1)[0]
    if sensitivity_id and sensitivity_id != "base":
        case_token = f"{configuration_short}_{sensitivity_id}"
    else:
        case_token = f"{configuration_short}_{target_variant}_{inventory_mode}"
    return f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{case_token}"


def _normalise_capacity_multiplier_overrides(capacity_multiplier_overrides: dict[str, float] | None) -> dict[str, float]:
    if not capacity_multiplier_overrides:
        return {}
    return {str(store_id).strip(): float(multiplier) for store_id, multiplier in capacity_multiplier_overrides.items()}


def _format_store_float_map(values: dict[str, float]) -> str:
    if not values:
        return "none"
    return ";".join(f"{store_id}={round(float(values[store_id]), 6)}" for store_id in sorted(values))


def _format_active_store_ids(active_store_ids: list[str]) -> str:
    return ";".join(sorted(active_store_ids)) if active_store_ids else "none"


def _refused_rows_payload(prepared: PreparedSmokeInputs) -> dict[str, Any]:
    rows = [
        {"table_name": row.table_name, "row_id": row.row_id, "reason": row.reason}
        for row in prepared.validation_report.refused_rows
    ]
    by_reason: dict[str, int] = {}
    by_table: dict[str, int] = {}
    for row in rows:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
        by_table[row["table_name"]] = by_table.get(row["table_name"], 0) + 1
    return {
        "rows": rows,
        "count": len(rows),
        "by_reason": by_reason,
        "by_table": by_table,
    }


def _objective_summary(model) -> dict[str, Any]:
    objective = next(model.component_data_objects(Objective, active=True, descend_into=True))
    objective_type = str(model.s2_metadata.get("objective_type", DEFAULT_OBJECTIVE_TYPE))
    return {
        "objective_name": objective.name,
        "objective_sense": "minimize" if objective.sense == minimize else "maximize",
        "objective_type": objective_type,
    }


def _active_bound_summary(prepared: PreparedSmokeInputs) -> dict[str, Any]:
    summary: dict[str, dict[str, float]] = {}
    for (process_unit_id, parameter_name), bound_value in sorted(prepared.process_bounds.items()):
        bucket = summary.setdefault(process_unit_id, {})
        bucket[parameter_name] = float(bound_value)
    return summary


def _process_output_coefficient(prepared: PreparedSmokeInputs, process_unit_id: str, carrier_id: str) -> float:
    matching = prepared.conversion_rows.loc[
        (prepared.conversion_rows["topology_process_unit_id"].eq(process_unit_id))
        & (prepared.conversion_rows["carrier_id"].eq(carrier_id))
        & (prepared.conversion_rows["coefficient_role"].eq("output_production"))
    ]
    if matching.empty:
        return 1.0
    return float(matching.iloc[0]["value"])


def _capacity_diagnostic(prepared: PreparedSmokeInputs) -> dict[str, Any]:
    max_bounds = {
        process_unit_id: value
        for (process_unit_id, parameter_name), value in prepared.process_bounds.items()
        if parameter_name in {"max_continuous_rate", "maximum_continuous_rate", "maximum_batch_equivalent_rate"}
    }
    min_bounds = {
        process_unit_id: value
        for (process_unit_id, parameter_name), value in prepared.process_bounds.items()
        if parameter_name in {"min_continuous_rate", "minimum_continuous_rate"}
    }

    route_limits: dict[str, dict[str, Any]] = {}
    for liquid_process_id in prepared.liquid_steel_process_ids:
        direct_max = float(max_bounds[liquid_process_id])
        limiting_value = direct_max
        limiting_notes = [f"direct_process_max={direct_max:.3f} t/h"]

        input_rows = prepared.conversion_rows.loc[
            (prepared.conversion_rows["topology_process_unit_id"].eq(liquid_process_id))
            & (prepared.conversion_rows["coefficient_role"].eq("input_consumption"))
            & (prepared.conversion_rows["carrier_id"].isin(prepared.internal_balance_carriers))
        ]
        for row in input_rows.to_dict(orient="records"):
            carrier_id = row["carrier_id"]
            input_per_output = float(row["value"])
            upstream_supply_tph = 0.0
            upstream_processes: list[str] = []
            for upstream_process_id in sorted(prepared.topology_process_ids):
                if upstream_process_id == liquid_process_id:
                    continue
                if upstream_process_id not in max_bounds:
                    continue
                matching_output = prepared.conversion_rows.loc[
                    (prepared.conversion_rows["topology_process_unit_id"].eq(upstream_process_id))
                    & (prepared.conversion_rows["carrier_id"].eq(carrier_id))
                    & (prepared.conversion_rows["coefficient_role"].eq("output_production"))
                ]
                if matching_output.empty:
                    inferred_output_carrier = _infer_output_carrier(
                        prepared.topology,
                        prepared.validation_report.configuration_id,
                        upstream_process_id,
                    )
                    if inferred_output_carrier != carrier_id:
                        continue
                coeff = _process_output_coefficient(prepared, upstream_process_id, carrier_id)
                upstream_supply_tph += float(max_bounds[upstream_process_id]) * coeff
                upstream_processes.append(upstream_process_id)
            if upstream_supply_tph > 0.0:
                translated_limit = upstream_supply_tph / input_per_output
                limiting_value = min(limiting_value, translated_limit)
                limiting_notes.append(
                    f"upstream_{carrier_id}_limit={translated_limit:.3f} t/h via {','.join(upstream_processes)}"
                )

        route_limits[liquid_process_id] = {
            "max_liquid_steel_tph": round(limiting_value, 6),
            "notes": limiting_notes,
        }

    aggregate_max_tph = sum(route["max_liquid_steel_tph"] for route in route_limits.values())
    horizon_hours = prepared.validation_report.horizon_hours
    aggregate_max_horizon = aggregate_max_tph * horizon_hours
    target_value = prepared.production_target_value

    return {
        "target_liquid_steel_tonnes": round(target_value, 6),
        "target_average_tph": round(target_value / horizon_hours, 6),
        "aggregate_max_liquid_steel_tph": round(aggregate_max_tph, 6),
        "aggregate_max_liquid_steel_tonnes": round(aggregate_max_horizon, 6),
        "target_minus_max_tonnes": round(target_value - aggregate_max_horizon, 6),
        "minimum_process_pressure_tph": {key: round(value, 6) for key, value in sorted(min_bounds.items())},
        "liquid_steel_route_limits": route_limits,
        "hard_target_without_slack": True,
        "likely_infeasible_due_capacity_gap": bool(aggregate_max_horizon + 1e-6 < target_value),
    }


def _build_input_validation_payload(prepared: PreparedSmokeInputs) -> dict[str, Any]:
    report = prepared.validation_report
    return {
        "configuration_id": report.configuration_id,
        "horizon_hours": report.horizon_hours,
        "inventory_mode": report.inventory_mode,
        "available_configurations": list(report.available_configurations),
        "selected_configurations": list(report.selected_configurations),
        "selected_target_variant": report.selected_target_variant,
        "consumed_process_bound_rows": list(report.consumed_process_bound_rows),
        "consumed_conversion_rows": list(report.consumed_conversion_rows),
        "consumed_production_target_rows": list(report.consumed_production_target_rows),
        "consumed_store_capacity_rows": list(report.consumed_store_capacity_rows),
        "consumed_initial_inventory_rows": list(report.consumed_initial_inventory_rows),
        "consumed_terminal_inventory_rows": list(report.consumed_terminal_inventory_rows),
        "consumed_inventory_policy_rows": list(report.consumed_inventory_policy_rows),
        "active_store_ids": list(report.active_store_ids),
        "sensitivity_id": prepared.sensitivity_id,
        "initial_inventory_fraction_by_store": {
            store.store_id: round(store.initial_inventory_fraction, 6) for store in prepared.active_inventory_stores
        },
        "capacity_multiplier_by_store": {
            store.store_id: round(store.capacity_multiplier, 6) for store in prepared.active_inventory_stores
        },
        "refused_rows": _refused_rows_payload(prepared),
        "encountered_non_executable_row": report.encountered_non_executable_row,
        "thesis_usability": report.thesis_usability,
        "notes": list(report.notes),
        "capacity_diagnostic": _capacity_diagnostic(prepared),
    }


def _build_model_stats_payload(model, prepared: PreparedSmokeInputs) -> dict[str, Any]:
    stats = model.s2_model_stats
    return {
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "active_process_units": list(prepared.topology_process_ids),
        "active_internal_carriers": list(prepared.internal_balance_carriers),
        "liquid_steel_producing_process_units": list(prepared.liquid_steel_process_ids),
        "target_value": prepared.production_target_value,
        "target_variant": prepared.validation_report.selected_target_variant,
        "inventory_mode": prepared.inventory_mode,
        "sensitivity_id": prepared.sensitivity_id,
        "active_store_count": len(prepared.active_inventory_stores),
        "active_store_ids": [store.store_id for store in prepared.active_inventory_stores],
        "store_capacities_t": {store.store_id: round(store.capacity_tonnes, 6) for store in prepared.active_inventory_stores},
        "base_store_capacities_t": {
            store.store_id: round(store.base_capacity_tonnes, 6) for store in prepared.active_inventory_stores
        },
        "initial_inventory_t": {store.store_id: round(store.initial_inventory_tonnes, 6) for store in prepared.active_inventory_stores},
        "base_initial_inventory_t": {
            store.store_id: round(store.base_initial_inventory_tonnes, 6) for store in prepared.active_inventory_stores
        },
        "initial_inventory_fraction_by_store": {
            store.store_id: round(store.initial_inventory_fraction, 6) for store in prepared.active_inventory_stores
        },
        "capacity_multiplier_by_store": {
            store.store_id: round(store.capacity_multiplier, 6) for store in prepared.active_inventory_stores
        },
        "terminal_inventory_target_t": {
            store.store_id: round(store.initial_inventory_tonnes * store.terminal_inventory_ratio, 6)
            for store in prepared.active_inventory_stores
        },
        "bound_summary": _active_bound_summary(prepared),
        **_objective_summary(model),
        "shortfall_slack_active": False,
        "inventory_active": prepared.inventory_mode == "first_buffers",
        "downstream_active": False,
        "thesis_usability": False,
    }


def _inventory_summary(model, prepared: PreparedSmokeInputs, *, solved: bool) -> dict[str, Any]:
    if prepared.inventory_mode != "first_buffers":
        return {
            "inventory_mode": prepared.inventory_mode,
            "inventory_active": False,
            "active_store_count": 0,
            "active_store_ids": [],
            "sensitivity_id": prepared.sensitivity_id,
            "store_capacities_t": {},
            "initial_inventory_t": {},
            "initial_inventory_fraction_by_store": {},
            "capacity_multiplier_by_store": {},
            "terminal_inventory_target_t": {},
            "minimum_inventory_reached_t": {},
            "maximum_inventory_reached_t": {},
            "terminal_inventory_achieved_t": {},
            "hit_zero_by_store": {},
            "hit_capacity_by_store": {},
            "cyc50_satisfied": None if not solved else True,
        }

    summary = {
        "inventory_mode": prepared.inventory_mode,
        "inventory_active": True,
        "active_store_count": len(prepared.active_inventory_stores),
        "active_store_ids": [store.store_id for store in prepared.active_inventory_stores],
        "sensitivity_id": prepared.sensitivity_id,
        "store_capacities_t": {store.store_id: round(store.capacity_tonnes, 6) for store in prepared.active_inventory_stores},
        "initial_inventory_t": {store.store_id: round(store.initial_inventory_tonnes, 6) for store in prepared.active_inventory_stores},
        "initial_inventory_fraction_by_store": {
            store.store_id: round(store.initial_inventory_fraction, 6) for store in prepared.active_inventory_stores
        },
        "capacity_multiplier_by_store": {
            store.store_id: round(store.capacity_multiplier, 6) for store in prepared.active_inventory_stores
        },
        "terminal_inventory_target_t": {
            store.store_id: round(store.initial_inventory_tonnes * store.terminal_inventory_ratio, 6)
            for store in prepared.active_inventory_stores
        },
    }
    if not solved:
        summary.update(
            {
                "minimum_inventory_reached_t": {},
                "maximum_inventory_reached_t": {},
                "terminal_inventory_achieved_t": {},
                "hit_zero_by_store": {},
                "hit_capacity_by_store": {},
                "cyc50_satisfied": None,
            }
        )
        return summary

    min_inventory = {}
    max_inventory = {}
    terminal_inventory = {}
    hit_zero = {}
    hit_capacity = {}
    cyc50_satisfied = True
    for store in prepared.active_inventory_stores:
        values = [float(value(model.store_inventory[store.store_id, t])) for t in model.TIME]
        min_inventory[store.store_id] = round(min(values), 6)
        max_inventory[store.store_id] = round(max(values), 6)
        terminal_inventory[store.store_id] = round(values[-1], 6)
        hit_zero[store.store_id] = bool(min(values) <= 1e-6)
        hit_capacity[store.store_id] = bool(max(values) >= store.capacity_tonnes - 1e-6)
        if abs(values[-1] - store.initial_inventory_tonnes * store.terminal_inventory_ratio) > 1e-6:
            cyc50_satisfied = False
    summary.update(
        {
            "minimum_inventory_reached_t": min_inventory,
            "maximum_inventory_reached_t": max_inventory,
            "terminal_inventory_achieved_t": terminal_inventory,
            "hit_zero_by_store": hit_zero,
            "hit_capacity_by_store": hit_capacity,
            "cyc50_satisfied": cyc50_satisfied,
        }
    )
    return summary


def _available_solver(preferred_solvers: tuple[str, ...] = DEFAULT_SOLVER_PREFERENCE):
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
    except NoFeasibleSolutionError:
        return solver.solve(model, tee=False, load_solutions=False)


def _carrier_balance_residual(model) -> float:
    residuals = [
        abs(value(constraint.body))
        for constraint in model.component_data_objects(Constraint, active=True, descend_into=True)
        if constraint.parent_component().name == "internal_material_balance"
    ]
    return 0.0 if not residuals else max(float(item) for item in residuals)


def _process_activity_summary(model) -> dict[str, float]:
    return {
        process_unit_id: round(
            sum(float(value(model.process_activity[process_unit_id, time_index])) for time_index in model.TIME),
            6,
        )
        for process_unit_id in model.PROCESSES
    }


def _overproduction_hint(model, prepared: PreparedSmokeInputs, overproduction_value: float) -> str:
    if overproduction_value <= 1e-6:
        return "zero_overproduction"

    minimum_liquid_steel_tph = sum(
        float(bound_value)
        for (process_unit_id, parameter_name), bound_value in prepared.process_bounds.items()
        if process_unit_id in prepared.liquid_steel_process_ids
        and parameter_name in {"min_continuous_rate", "minimum_continuous_rate"}
    )
    minimum_liquid_steel_total = minimum_liquid_steel_tph * prepared.validation_report.horizon_hours
    if minimum_liquid_steel_total > prepared.production_target_value + 1e-6:
        return "likely_caused_by_process_lower_bounds"
    if prepared.validation_report.configuration_id == "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF":
        return "likely_caused_by_balance_or_conversion_structure"
    return "not_diagnosed"


def _build_solve_summary(
    *,
    model,
    prepared: PreparedSmokeInputs,
    solve_attempted: bool,
    solver_name: str | None,
    result=None,
    runtime_seconds: float | None = None,
) -> dict[str, Any]:
    inventory_summary = _inventory_summary(model, prepared, solved=False)
    base = {
        "solve_attempted": solve_attempted,
        "solver_name": solver_name,
        "thesis_usability": False,
        "hard_target_without_slack": True,
        "target_variant": prepared.validation_report.selected_target_variant,
        "sensitivity_id": prepared.sensitivity_id,
        "objective_type": str(model.s2_metadata.get("objective_type", DEFAULT_OBJECTIVE_TYPE)),
        "inventory_summary": inventory_summary,
    }
    if not solve_attempted:
        base.update(
            {
                "solve_status": "not_attempted_solver_unavailable",
                "termination_condition": None,
                "objective_value": None,
                "runtime_seconds": None,
                "production_target_achieved": None,
                "production_target_value": prepared.production_target_value,
                "production_target_residual": None,
                "overproduction": None,
                "overproduction_positive": None,
                "overproduction_diagnostic_hint": None,
                "minimum_inventory_margin": None,
                "carrier_balance_max_abs_residual": None,
                "process_activity_summary": None,
            }
        )
        return base

    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    success = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )
    infeasible = "infeasible" in termination_condition.lower()

    achieved_production = float(value(model.horizon_total_liquid_steel_output)) if success else None
    overproduction_value = float(value(model.overproduction)) if success else None
    production_residual = float(value(model.production_target_residual)) if success else None
    inventory_summary = _inventory_summary(model, prepared, solved=success)

    base.update(
        {
            "solve_status": solver_status,
            "termination_condition": termination_condition,
            "runtime_seconds": runtime_seconds,
            "objective_value": float(value(next(model.component_data_objects(Objective, active=True, descend_into=True)))) if success else None,
            "production_target_value": prepared.production_target_value,
            "production_target_achieved": achieved_production,
            "production_target_residual": production_residual,
            "overproduction": overproduction_value,
            "overproduction_positive": None if overproduction_value is None else bool(overproduction_value > 1e-6),
            "overproduction_diagnostic_hint": None if overproduction_value is None else _overproduction_hint(model, prepared, overproduction_value),
            "minimum_inventory_margin": (
                float(value(model.minimum_inventory_margin))
                if success and hasattr(model, "minimum_inventory_margin")
                else None
            ),
            "carrier_balance_max_abs_residual": _carrier_balance_residual(model) if success else None,
            "process_activity_summary": _process_activity_summary(model) if success else None,
            "inventory_summary": inventory_summary,
            "feasible": success,
            "infeasible": infeasible,
        }
    )
    if not success:
        base["capacity_diagnostic"] = _capacity_diagnostic(prepared)
    return base


def _warning_list(configuration_id: str, *, inventory_mode: str, active_store_ids: list[str], objective_type: str) -> list[str]:
    return [
        "All outputs in this run folder are provisional development diagnostics only.",
        "thesis_usability=false",
        "input_surface=s2_provisional_dev_input",
        f"objective_type={objective_type}",
        "consumed_rows_must_be_dev_executable_only",
        "approved_input_used=false",
        "shortfall_slack_active=false",
        f"inventory_mode={inventory_mode}",
        f"inventory_active={'true' if inventory_mode == 'first_buffers' else 'false'}",
        f"active_store_ids={','.join(active_store_ids)}",
        "downstream_active=false",
        "energy_cost_emissions_active=false",
        "market_logic_active=false",
        f"configuration_id={configuration_id}",
    ]


def _limitations_text(configuration_id: str, *, inventory_mode: str, active_store_ids: list[str], objective_type: str) -> str:
    return "\n".join(
        [
            "# Limitations",
            "",
            f"- configuration: `{configuration_id}`",
            "- scope: restricted liquid-steel smoke only",
            f"- inventory_mode: `{inventory_mode}`",
            f"- objective_type: `{objective_type}`",
            f"- active_store_ids: `{', '.join(active_store_ids) if active_store_ids else 'none'}`",
            "- no downstream slab or HSM scope",
            "- no hidden shortfall slack",
            "- no DA, stochastic, CVaR, or mFRR logic",
            "- any feasibility result remains non-thesis and provisional",
        ]
    ) + "\n"


def _write_run_folder(
    *,
    run_dir: Path,
    resolved_config: dict[str, Any],
    input_manifest: dict[str, Any],
    model_stats_payload: dict[str, Any],
    input_validation_payload: dict[str, Any],
    solve_summary: dict[str, Any],
    warnings: list[str],
    limitations_text: str,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "resolved_config.json", resolved_config)
    write_json(run_dir / "input_manifest.json", input_manifest)
    write_json(run_dir / "model_stats.json", model_stats_payload)
    write_json(run_dir / "input_validation_summary.json", input_validation_payload)
    write_json(run_dir / "solve_summary.json", solve_summary)
    write_json(run_dir / "warnings.json", {"warnings": warnings})
    (run_dir / "limitations.md").write_text(limitations_text, encoding="utf-8")


def _inventory_metric_string(summary: dict[str, Any], field_name: str) -> str:
    mapping = summary.get(field_name, {})
    if not mapping:
        return "none"
    return ";".join(f"{store_id}={mapping[store_id]}" for store_id in sorted(mapping))


def _summary_row_from_result(result: dict[str, Any]) -> dict[str, Any]:
    solve_summary = result["solve_summary"]
    model_stats = result["model_stats"]
    inventory_summary = solve_summary["inventory_summary"]
    horizon_hours = int(result["input_validation_summary"]["horizon_hours"])
    return {
        "case_id": f"{result['configuration_id']}_{solve_summary['target_variant']}_{inventory_summary['inventory_mode']}",
        "configuration_id": result["configuration_id"],
        "horizon_hours": horizon_hours,
        "target_variant": solve_summary["target_variant"],
        "inventory_mode": inventory_summary["inventory_mode"],
        "active_store_ids": ";".join(inventory_summary["active_store_ids"]) if inventory_summary["active_store_ids"] else "none",
        "solve_status": solve_summary["termination_condition"] or solve_summary["solve_status"],
        "target_t": round(float(solve_summary["production_target_value"]), 6),
        "achieved_liquid_steel_t": (
            "not_applicable_infeasible_case"
            if solve_summary["production_target_achieved"] is None
            else round(float(solve_summary["production_target_achieved"]), 6)
        ),
        "overproduction_t": (
            "not_applicable_infeasible_case"
            if solve_summary["overproduction"] is None
            else round(float(solve_summary["overproduction"]), 6)
        ),
        "variable_count": model_stats["variable_count"],
        "constraint_count": model_stats["constraint_count"],
        "binary_count": model_stats["binary_count"],
        "inventory_active": str(bool(inventory_summary["inventory_active"])).lower(),
        "active_store_count": inventory_summary["active_store_count"],
        "min_inventory_t": (
            _inventory_metric_string(inventory_summary, "minimum_inventory_reached_t")
            if solve_summary.get("feasible")
            else "not_applicable_infeasible_case"
        ),
        "max_inventory_t": (
            _inventory_metric_string(inventory_summary, "maximum_inventory_reached_t")
            if solve_summary.get("feasible")
            else "not_applicable_infeasible_case"
        ),
        "terminal_inventory_satisfied": (
            "not_applicable_infeasible_case"
            if inventory_summary["cyc50_satisfied"] is None
            else str(bool(inventory_summary["cyc50_satisfied"])).lower()
        ),
        "shortfall_slack_active": "false",
        "downstream_active": "false",
        "thesis_usability": "false",
        "interpretation": (
            "first_buffer_inventory_smoke_mechanics"
            if solve_summary.get("feasible")
            else "intentional_stress_infeasibility_with_guarded_inventory_mode"
        ),
        "next_action": (
            "use_for_guarded_buffer_diagnostics_only"
            if solve_summary.get("feasible")
            else "preserve_as_infeasibility_regression_case"
        ),
}


def _buffer_sensitivity_summary_row_from_result(result: dict[str, Any]) -> dict[str, Any]:
    solve_summary = result["solve_summary"]
    model_stats = result["model_stats"]
    inventory_summary = solve_summary["inventory_summary"]
    hit_zero_by_store = inventory_summary.get("hit_zero_by_store", {})
    hit_capacity_by_store = inventory_summary.get("hit_capacity_by_store", {})
    horizon_hours = int(result["input_validation_summary"]["horizon_hours"])
    return {
        "result_id": f"{result['configuration_id']}_{result['sensitivity_id']}",
        "sensitivity_id": result["sensitivity_id"],
        "configuration_id": result["configuration_id"],
        "horizon_hours": horizon_hours,
        "target_variant": solve_summary["target_variant"],
        "inventory_mode": inventory_summary["inventory_mode"],
        "solve_status": solve_summary["termination_condition"] or solve_summary["solve_status"],
        "target_t": round(float(solve_summary["production_target_value"]), 6),
        "achieved_liquid_steel_t": (
            "not_applicable_unsolved_or_infeasible"
            if solve_summary["production_target_achieved"] is None
            else round(float(solve_summary["production_target_achieved"]), 6)
        ),
        "overproduction_t": (
            "not_applicable_unsolved_or_infeasible"
            if solve_summary["overproduction"] is None
            else round(float(solve_summary["overproduction"]), 6)
        ),
        "active_store_ids": _format_active_store_ids(inventory_summary["active_store_ids"]),
        "capacity_multiplier_summary": _format_store_float_map(inventory_summary.get("capacity_multiplier_by_store", {})),
        "initial_inventory_fraction_summary": _format_store_float_map(
            inventory_summary.get("initial_inventory_fraction_by_store", {})
        ),
        "any_store_hit_zero": (
            "not_applicable_unsolved_or_infeasible"
            if not hit_zero_by_store
            else str(any(bool(item) for item in hit_zero_by_store.values())).lower()
        ),
        "any_store_hit_capacity": (
            "not_applicable_unsolved_or_infeasible"
            if not hit_capacity_by_store
            else str(any(bool(item) for item in hit_capacity_by_store.values())).lower()
        ),
        "all_terminal_inventory_satisfied": (
            "not_applicable_unsolved_or_infeasible"
            if inventory_summary["cyc50_satisfied"] is None
            else str(bool(inventory_summary["cyc50_satisfied"])).lower()
        ),
        "min_inventory_summary": (
            _format_store_float_map(inventory_summary["minimum_inventory_reached_t"])
            if solve_summary.get("feasible")
            else "not_applicable_unsolved_or_infeasible"
        ),
        "max_inventory_summary": (
            _format_store_float_map(inventory_summary["maximum_inventory_reached_t"])
            if solve_summary.get("feasible")
            else "not_applicable_unsolved_or_infeasible"
        ),
        "variable_count": model_stats["variable_count"],
        "constraint_count": model_stats["constraint_count"],
        "binary_count": model_stats["binary_count"],
        "shortfall_slack_active": "false",
        "thesis_usability": "false",
        "interpretation": result["interpretation"],
        "next_action": result["next_action"],
    }


def _zero_hit_reduced_vs_default(default_summary: dict[str, Any], diagnostic_summary: dict[str, Any]) -> bool | None:
    default_inventory = default_summary.get("inventory_summary", {})
    diagnostic_inventory = diagnostic_summary.get("inventory_summary", {})
    default_hits = default_inventory.get("hit_zero_by_store", {})
    diagnostic_hits = diagnostic_inventory.get("hit_zero_by_store", {})
    if not default_hits or not diagnostic_hits:
        return None
    return sum(bool(item) for item in diagnostic_hits.values()) < sum(bool(item) for item in default_hits.values())


def _diagnostic_zero_hit_explanation(
    *,
    default_summary: dict[str, Any],
    diagnostic_summary: dict[str, Any],
) -> str:
    if not diagnostic_summary.get("feasible"):
        return "diagnostic_objective_not_feasible_or_not_solved"
    reduced = _zero_hit_reduced_vs_default(default_summary, diagnostic_summary)
    if reduced:
        return "zero_hits_reduce_under_inventory_preservation_so_default_zero_hits_are_likely_objective_degeneracy"
    diagnostic_inventory = diagnostic_summary.get("inventory_summary", {})
    if diagnostic_inventory.get("hit_zero_by_store") and any(bool(item) for item in diagnostic_inventory["hit_zero_by_store"].values()):
        return "zero_hits_persist_under_inventory_preservation_so_buffer_depletion_is_structurally_forced_or_ambiguous"
    return "not_diagnosed"


def write_buffer_inventory_smoke_summary(results: list[dict[str, Any]], output_path: str | Path) -> Path:
    summary_path = Path(output_path).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_summary_row_from_result(result) for result in results]
    frame = pd.DataFrame(
        rows,
        columns=[
            "case_id",
            "configuration_id",
            "horizon_hours",
            "target_variant",
            "inventory_mode",
            "active_store_ids",
            "solve_status",
            "target_t",
            "achieved_liquid_steel_t",
            "overproduction_t",
            "variable_count",
            "constraint_count",
            "binary_count",
            "inventory_active",
            "active_store_count",
            "min_inventory_t",
            "max_inventory_t",
            "terminal_inventory_satisfied",
            "shortfall_slack_active",
            "downstream_active",
            "thesis_usability",
            "interpretation",
            "next_action",
        ],
    )
    frame.to_csv(summary_path, index=False)
    return summary_path


def write_buffer_sensitivity_result_summary(results: list[dict[str, Any]], output_path: str | Path) -> Path:
    summary_path = Path(output_path).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_buffer_sensitivity_summary_row_from_result(result) for result in results]
    frame = pd.DataFrame(
        rows,
        columns=[
            "result_id",
            "sensitivity_id",
            "configuration_id",
            "horizon_hours",
            "target_variant",
            "inventory_mode",
            "solve_status",
            "target_t",
            "achieved_liquid_steel_t",
            "overproduction_t",
            "active_store_ids",
            "capacity_multiplier_summary",
            "initial_inventory_fraction_summary",
            "any_store_hit_zero",
            "any_store_hit_capacity",
            "all_terminal_inventory_satisfied",
            "min_inventory_summary",
            "max_inventory_summary",
            "variable_count",
            "constraint_count",
            "binary_count",
            "shortfall_slack_active",
            "thesis_usability",
            "interpretation",
            "next_action",
        ],
    )
    frame.to_csv(summary_path, index=False)
    return summary_path


def write_zero_hit_attribution_register(rows: list[dict[str, Any]], output_path: str | Path) -> Path:
    summary_path = Path(output_path).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        rows,
        columns=[
            "attribution_id",
            "configuration_id",
            "horizon_hours",
            "target_variant",
            "inventory_mode",
            "objective_type",
            "solve_status",
            "active_store_ids",
            "any_store_hit_zero",
            "zero_hit_reduced_vs_default",
            "all_terminal_inventory_satisfied",
            "stress_case_preserved_if_applicable",
            "likely_explanation",
            "benign_gate_result",
            "one_week_allowed",
            "thesis_usability",
            "notes",
        ],
    )
    frame.to_csv(summary_path, index=False)
    return summary_path


def _one_week_summary_row_from_result(result: dict[str, Any]) -> dict[str, Any]:
    solve_summary = result["solve_summary"]
    model_stats = result["model_stats"]
    inventory_summary = solve_summary["inventory_summary"]
    hit_zero_by_store = inventory_summary.get("hit_zero_by_store", {})
    hit_capacity_by_store = inventory_summary.get("hit_capacity_by_store", {})
    horizon_hours = int(result["input_validation_summary"]["horizon_hours"])
    return {
        "case_id": f"{result['configuration_id']}_{solve_summary['target_variant']}_{solve_summary['objective_type']}",
        "configuration_id": result["configuration_id"],
        "horizon_hours": horizon_hours,
        "target_variant": solve_summary["target_variant"],
        "inventory_mode": inventory_summary["inventory_mode"],
        "objective_type": solve_summary["objective_type"],
        "solve_status": solve_summary["termination_condition"] or solve_summary["solve_status"],
        "target_t": round(float(solve_summary["production_target_value"]), 6),
        "achieved_liquid_steel_t": (
            "not_applicable_unsolved_or_infeasible"
            if solve_summary["production_target_achieved"] is None
            else round(float(solve_summary["production_target_achieved"]), 6)
        ),
        "overproduction_t": (
            "not_applicable_unsolved_or_infeasible"
            if solve_summary["overproduction"] is None
            else round(float(solve_summary["overproduction"]), 6)
        ),
        "variable_count": model_stats["variable_count"],
        "constraint_count": model_stats["constraint_count"],
        "binary_count": model_stats["binary_count"],
        "active_store_count": inventory_summary["active_store_count"],
        "active_store_ids": _format_active_store_ids(inventory_summary["active_store_ids"]),
        "any_store_hit_zero": (
            "not_applicable_unsolved_or_infeasible"
            if not hit_zero_by_store
            else str(any(bool(item) for item in hit_zero_by_store.values())).lower()
        ),
        "any_store_hit_capacity": (
            "not_applicable_unsolved_or_infeasible"
            if not hit_capacity_by_store
            else str(any(bool(item) for item in hit_capacity_by_store.values())).lower()
        ),
        "all_terminal_inventory_satisfied": (
            "not_applicable_unsolved_or_infeasible"
            if inventory_summary["cyc50_satisfied"] is None
            else str(bool(inventory_summary["cyc50_satisfied"])).lower()
        ),
        "shortfall_slack_active": "false",
        "downstream_active": "false",
        "thesis_usability": "false",
        "interpretation": (
            "one_week_buffer_smoke_opened_after_benign_zero_hit_gate"
            if solve_summary.get("feasible")
            else "one_week_buffer_smoke_failed_or_unsolved"
        ),
        "next_action": (
            "keep_scope_non_thesis_and_do_not_open_downstream_or_s3"
            if solve_summary.get("feasible")
            else "review_weekly_failure_before_any_scope_increase"
        ),
    }


def write_one_week_buffer_smoke_summary(results: list[dict[str, Any]], output_path: str | Path) -> Path:
    summary_path = Path(output_path).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_one_week_summary_row_from_result(result) for result in results]
    frame = pd.DataFrame(
        rows,
        columns=[
            "case_id",
            "configuration_id",
            "horizon_hours",
            "target_variant",
            "inventory_mode",
            "objective_type",
            "solve_status",
            "target_t",
            "achieved_liquid_steel_t",
            "overproduction_t",
            "variable_count",
            "constraint_count",
            "binary_count",
            "active_store_count",
            "active_store_ids",
            "any_store_hit_zero",
            "any_store_hit_capacity",
            "all_terminal_inventory_satisfied",
            "shortfall_slack_active",
            "downstream_active",
            "thesis_usability",
            "interpretation",
            "next_action",
        ],
    )
    frame.to_csv(summary_path, index=False)
    return summary_path


def run_zero_hit_attribution_gate(
    *,
    output_root: str | Path = DEFAULT_STEEL_SMOKE_RUN_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    solve_if_available: bool = True,
    summary_output_path: str | Path = ZERO_HIT_ATTRIBUTION_REGISTER_PATH,
) -> dict[str, Any]:
    configuration_ids = (
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    )
    rows: list[dict[str, Any]] = []
    run_results: dict[str, dict[str, Any]] = {}
    overall_benign = True
    stop_reasons: list[str] = []

    for configuration_id in configuration_ids:
        config_short = configuration_id.split("_", 1)[0]
        default_payload = run_liquid_steel_smoke_cases(
            configuration_ids=(configuration_id,),
            horizon_hours=24,
            target_variant="feasible_smoke",
            inventory_mode="first_buffers",
            objective_type=DEFAULT_OBJECTIVE_TYPE,
            solve_if_available=solve_if_available,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            output_root=output_root,
            sensitivity_id=f"{config_short}_ZERO_HIT_DEFAULT",
        )
        default_result = default_payload["results"][0]
        default_summary = default_result["solve_summary"]

        diagnostic_cap = (
            float(default_summary["overproduction"])
            if default_summary.get("feasible") and default_summary.get("overproduction") is not None
            else None
        )
        diagnostic_payload = run_liquid_steel_smoke_cases(
            configuration_ids=(configuration_id,),
            horizon_hours=24,
            target_variant="feasible_smoke",
            inventory_mode="first_buffers",
            objective_type="diagnostic_maximise_min_inventory_margin",
            solve_if_available=solve_if_available,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            output_root=output_root,
            sensitivity_id=f"{config_short}_ZERO_HIT_DIAGNOSTIC",
            diagnostic_overproduction_cap=diagnostic_cap,
        )
        diagnostic_result = diagnostic_payload["results"][0]
        diagnostic_summary = diagnostic_result["solve_summary"]

        stress_payload = run_liquid_steel_smoke_cases(
            configuration_ids=(configuration_id,),
            horizon_hours=24,
            target_variant="stress_infeasible_original",
            inventory_mode="first_buffers",
            objective_type=DEFAULT_OBJECTIVE_TYPE,
            solve_if_available=solve_if_available,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            output_root=output_root,
            sensitivity_id=f"{config_short}_ZERO_HIT_STRESS",
        )
        stress_result = stress_payload["results"][0]
        stress_summary = stress_result["solve_summary"]

        default_zero_hits = default_summary.get("inventory_summary", {}).get("hit_zero_by_store", {})
        diagnostic_zero_hits = diagnostic_summary.get("inventory_summary", {}).get("hit_zero_by_store", {})
        any_default_zero = bool(default_zero_hits) and any(bool(item) for item in default_zero_hits.values())
        any_diagnostic_zero = bool(diagnostic_zero_hits) and any(bool(item) for item in diagnostic_zero_hits.values())
        zero_hit_reduced = _zero_hit_reduced_vs_default(default_summary, diagnostic_summary)
        stress_preserved = bool(stress_summary.get("infeasible"))
        terminal_satisfied = diagnostic_summary.get("inventory_summary", {}).get("cyc50_satisfied")

        config_benign = bool(
            default_summary.get("feasible")
            and diagnostic_summary.get("feasible")
            and stress_preserved
            and terminal_satisfied is True
            and (zero_hit_reduced is True or any_diagnostic_zero is False)
        )
        if not config_benign:
            overall_benign = False
            if not default_summary.get("feasible"):
                stop_reasons.append(f"{configuration_id}: default_feasible_smoke_not_optimal")
            elif not diagnostic_summary.get("feasible"):
                stop_reasons.append(f"{configuration_id}: diagnostic_objective_not_feasible")
            elif not stress_preserved:
                stop_reasons.append(f"{configuration_id}: stress_infeasibility_not_preserved")
            elif terminal_satisfied is not True:
                stop_reasons.append(f"{configuration_id}: cyc50_terminal_equality_not_satisfied")
            elif any_diagnostic_zero:
                stop_reasons.append(f"{configuration_id}: zero_hits_persist_under_inventory_preservation")
            else:
                stop_reasons.append(f"{configuration_id}: benign_gate_not_proven")

        likely_explanation = _diagnostic_zero_hit_explanation(
            default_summary=default_summary,
            diagnostic_summary=diagnostic_summary,
        )
        active_store_ids = diagnostic_summary.get("inventory_summary", {}).get("active_store_ids", [])
        active_store_ids_text = _format_active_store_ids(active_store_ids)
        benign_gate_result = "passed" if config_benign else "failed_non_benign_or_ambiguous"

        rows.extend(
            [
                {
                    "attribution_id": f"{config_short}_DEFAULT",
                    "configuration_id": configuration_id,
                    "horizon_hours": 24,
                    "target_variant": "feasible_smoke",
                    "inventory_mode": "first_buffers",
                    "objective_type": DEFAULT_OBJECTIVE_TYPE,
                    "solve_status": default_summary.get("termination_condition") or default_summary.get("solve_status"),
                    "active_store_ids": active_store_ids_text,
                    "any_store_hit_zero": str(any_default_zero).lower(),
                    "zero_hit_reduced_vs_default": "not_applicable",
                    "all_terminal_inventory_satisfied": str(bool(default_summary.get("inventory_summary", {}).get("cyc50_satisfied"))).lower()
                    if default_summary.get("inventory_summary", {}).get("cyc50_satisfied") is not None
                    else "not_applicable",
                    "stress_case_preserved_if_applicable": "not_applicable",
                    "likely_explanation": "default_objective_boundary_touching_reference_case",
                    "benign_gate_result": benign_gate_result,
                    "one_week_allowed": str(config_benign).lower(),
                    "thesis_usability": "false",
                    "notes": "Reference feasible case under default objective.",
                },
                {
                    "attribution_id": f"{config_short}_DIAGNOSTIC",
                    "configuration_id": configuration_id,
                    "horizon_hours": 24,
                    "target_variant": "feasible_smoke",
                    "inventory_mode": "first_buffers",
                    "objective_type": "diagnostic_maximise_min_inventory_margin",
                    "solve_status": diagnostic_summary.get("termination_condition") or diagnostic_summary.get("solve_status"),
                    "active_store_ids": active_store_ids_text,
                    "any_store_hit_zero": str(any_diagnostic_zero).lower() if diagnostic_zero_hits else "not_applicable",
                    "zero_hit_reduced_vs_default": (
                        "not_applicable" if zero_hit_reduced is None else str(bool(zero_hit_reduced)).lower()
                    ),
                    "all_terminal_inventory_satisfied": str(bool(terminal_satisfied)).lower()
                    if terminal_satisfied is not None
                    else "not_applicable",
                    "stress_case_preserved_if_applicable": "not_applicable",
                    "likely_explanation": likely_explanation,
                    "benign_gate_result": benign_gate_result,
                    "one_week_allowed": str(config_benign).lower(),
                    "thesis_usability": "false",
                    "notes": f"Diagnostic run with overproduction cap {diagnostic_cap}.",
                },
                {
                    "attribution_id": f"{config_short}_STRESS",
                    "configuration_id": configuration_id,
                    "horizon_hours": 24,
                    "target_variant": "stress_infeasible_original",
                    "inventory_mode": "first_buffers",
                    "objective_type": DEFAULT_OBJECTIVE_TYPE,
                    "solve_status": stress_summary.get("termination_condition") or stress_summary.get("solve_status"),
                    "active_store_ids": active_store_ids_text,
                    "any_store_hit_zero": "not_applicable",
                    "zero_hit_reduced_vs_default": "not_applicable",
                    "all_terminal_inventory_satisfied": "not_applicable",
                    "stress_case_preserved_if_applicable": str(stress_preserved).lower(),
                    "likely_explanation": (
                        "stress_infeasibility_preserved_under_first_buffer_inventory_mode"
                        if stress_preserved
                        else "stress_case_became_feasible_red_flag"
                    ),
                    "benign_gate_result": benign_gate_result,
                    "one_week_allowed": str(config_benign).lower(),
                    "thesis_usability": "false",
                    "notes": "Stress safeguard regression row.",
                },
            ]
        )

        run_results[configuration_id] = {
            "default": default_result,
            "diagnostic": diagnostic_result,
            "stress": stress_result,
            "config_benign": config_benign,
            "likely_explanation": likely_explanation,
        }

    summary_path = write_zero_hit_attribution_register(rows, summary_output_path)
    return {
        "scope": SCOPE_ID,
        "solver_name": _available_solver()[0],
        "solve_if_available": solve_if_available,
        "thesis_usability": False,
        "zero_hit_attribution_path": str(summary_path),
        "rows": rows,
        "run_results": run_results,
        "overall_benign": overall_benign,
        "one_week_opened": False,
        "stop_reason": "; ".join(stop_reasons) if stop_reasons else "benign_gate_passed",
    }


def run_liquid_steel_smoke_cases(
    *,
    configuration_ids: tuple[str, ...] = (
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    ),
    horizon_hours: int = 24,
    target_variant: str = "feasible_smoke",
    inventory_mode: str = "inactive",
    objective_type: str = DEFAULT_OBJECTIVE_TYPE,
    solve_if_available: bool = True,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    output_root: str | Path = DEFAULT_STEEL_SMOKE_RUN_ROOT,
    summary_output_path: str | Path | None = None,
    sensitivity_id: str = "base",
    initial_inventory_fraction: float | None = None,
    capacity_multiplier_overrides: dict[str, float] | None = None,
    diagnostic_overproduction_cap: float | None = None,
) -> dict[str, Any]:
    if horizon_hours not in {24, 168}:
        raise LiquidSteelSmokeBuilderError("Restricted steel smoke runs currently support only 24h or 168h horizons.")
    resolved_objective_type = str(objective_type).strip()
    if resolved_objective_type not in ALLOWED_OBJECTIVE_TYPES:
        raise LiquidSteelSmokeBuilderError(
            f"Unsupported objective_type={objective_type!r}. Allowed values: {sorted(ALLOWED_OBJECTIVE_TYPES)}."
        )

    output_root_path = Path(output_root).resolve()
    output_root_path.mkdir(parents=True, exist_ok=True)
    resolved_capacity_overrides = _normalise_capacity_multiplier_overrides(capacity_multiplier_overrides)

    solver_name, solver = _available_solver()
    results: list[dict[str, Any]] = []

    for configuration_id in configuration_ids:
        if configuration_id not in ALLOWED_CONFIGURATION_IDS:
            raise LiquidSteelSmokeBuilderError(f"Unsupported configuration_id={configuration_id!r} for S2.9b.")

        prepared = validate_liquid_steel_smoke_inputs(
            configuration_id=configuration_id,
            horizon_hours=horizon_hours,
            target_variant=target_variant,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            inventory_mode=inventory_mode,
            sensitivity_id=sensitivity_id,
            initial_inventory_fraction=initial_inventory_fraction,
            capacity_multiplier_overrides=resolved_capacity_overrides,
        )
        model = build_liquid_steel_smoke_model(
            configuration_id=configuration_id,
            horizon_hours=horizon_hours,
            target_variant=target_variant,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            inventory_mode=inventory_mode,
            sensitivity_id=sensitivity_id,
            initial_inventory_fraction=initial_inventory_fraction,
            capacity_multiplier_overrides=resolved_capacity_overrides,
            objective_type=resolved_objective_type,
            allow_target_shortfall=False,
        )
        if resolved_objective_type != DEFAULT_OBJECTIVE_TYPE and diagnostic_overproduction_cap is not None:
            configure_liquid_steel_smoke_objective(
                model,
                objective_type=resolved_objective_type,
                overproduction_cap=diagnostic_overproduction_cap,
            )

        timestamp = now_utc()
        run_dir = output_root_path / _normalise_run_slug(
            configuration_id,
            horizon_hours,
            prepared.validation_report.selected_target_variant,
            prepared.inventory_mode,
            prepared.sensitivity_id,
            timestamp,
        )
        input_validation_payload = _build_input_validation_payload(prepared)
        model_stats_payload = _build_model_stats_payload(model, prepared)
        warnings = _warning_list(
            configuration_id,
            inventory_mode=prepared.inventory_mode,
            active_store_ids=list(prepared.validation_report.active_store_ids),
            objective_type=str(model.s2_metadata.get("objective_type", resolved_objective_type)),
        )

        runtime_seconds = None
        result = None
        solve_attempted = bool(solve_if_available and solver is not None)
        if solve_attempted:
            wall_start = time.perf_counter()
            result = _solve_model(model, solver)
            runtime_seconds = time.perf_counter() - wall_start
        solve_summary = _build_solve_summary(
            model=model,
            prepared=prepared,
            solve_attempted=solve_attempted,
            solver_name=solver_name,
            result=result,
            runtime_seconds=runtime_seconds,
        )

        resolved_config = {
            "run_timestamp_utc": iso_utc(timestamp),
            "configuration_id": configuration_id,
            "horizon_hours": horizon_hours,
            "scope": SCOPE_ID,
            "target_variant": prepared.validation_report.selected_target_variant,
            "inventory_mode": prepared.inventory_mode,
            "sensitivity_id": prepared.sensitivity_id,
            "objective_type": str(model.s2_metadata.get("objective_type", resolved_objective_type)),
            "initial_inventory_fraction_summary": {
                store.store_id: round(store.initial_inventory_fraction, 6) for store in prepared.active_inventory_stores
            },
            "capacity_multiplier_summary": {
                store.store_id: round(store.capacity_multiplier, 6) for store in prepared.active_inventory_stores
            },
            "input_surface": "s2_provisional_dev_input",
            "refused_input_surface": "s2_approved_model_input",
            "approved_input_used": False,
            "shortfall_slack_active": False,
            "inventory_active": prepared.inventory_mode == "first_buffers",
            "active_store_count": len(prepared.active_inventory_stores),
            "active_store_ids": [store.store_id for store in prepared.active_inventory_stores],
            "downstream_active": False,
            "energy_cost_emissions_active": False,
            "market_logic_active": False,
            "thesis_usability": False,
            "solve_if_available": solve_if_available,
            "solver_name_selected": solver_name,
            "diagnostic_overproduction_cap": diagnostic_overproduction_cap,
            "code_version": {
                "git_commit": resolve_git_commit(REPO_ROOT),
            },
        }
        input_manifest = {
            "provisional_dev_input_root": repo_rel(Path(provisional_dev_input_root).resolve(), REPO_ROOT),
            "review_root": repo_rel(Path(review_root).resolve(), REPO_ROOT),
            "consumed_process_bound_rows": list(prepared.validation_report.consumed_process_bound_rows),
            "consumed_conversion_rows": list(prepared.validation_report.consumed_conversion_rows),
            "consumed_production_target_rows": list(prepared.validation_report.consumed_production_target_rows),
            "consumed_store_capacity_rows": list(prepared.validation_report.consumed_store_capacity_rows),
            "consumed_initial_inventory_rows": list(prepared.validation_report.consumed_initial_inventory_rows),
            "consumed_terminal_inventory_rows": list(prepared.validation_report.consumed_terminal_inventory_rows),
            "consumed_inventory_policy_rows": list(prepared.validation_report.consumed_inventory_policy_rows),
            "selected_target_variant": prepared.validation_report.selected_target_variant,
            "inventory_mode": prepared.inventory_mode,
            "sensitivity_id": prepared.sensitivity_id,
            "objective_type": str(model.s2_metadata.get("objective_type", resolved_objective_type)),
            "initial_inventory_fraction_summary": {
                store.store_id: round(store.initial_inventory_fraction, 6) for store in prepared.active_inventory_stores
            },
            "capacity_multiplier_summary": {
                store.store_id: round(store.capacity_multiplier, 6) for store in prepared.active_inventory_stores
            },
            "active_store_ids": list(prepared.validation_report.active_store_ids),
            "refused_row_count": len(prepared.validation_report.refused_rows),
            "thesis_usability": False,
            "approved_input_used": False,
            "input_surface": "s2_provisional_dev_input",
            "diagnostic_overproduction_cap": diagnostic_overproduction_cap,
        }
        _write_run_folder(
            run_dir=run_dir,
            resolved_config=resolved_config,
            input_manifest=input_manifest,
            model_stats_payload=model_stats_payload,
            input_validation_payload=input_validation_payload,
            solve_summary=solve_summary,
            warnings=warnings,
            limitations_text=_limitations_text(
                configuration_id,
                inventory_mode=prepared.inventory_mode,
                active_store_ids=list(prepared.validation_report.active_store_ids),
                objective_type=str(model.s2_metadata.get("objective_type", resolved_objective_type)),
            ),
        )

        results.append(
            {
                "configuration_id": configuration_id,
                "target_variant": prepared.validation_report.selected_target_variant,
                "sensitivity_id": prepared.sensitivity_id,
                "run_dir": str(run_dir),
                "solve_summary": solve_summary,
                "model_stats": model_stats_payload,
                "input_validation_summary": input_validation_payload,
                "interpretation": (
                    "feasible_under_guarded_buffer_sensitivity"
                    if solve_summary.get("feasible")
                    else (
                        "stress_infeasibility_preserved_under_guarded_buffer_sensitivity"
                        if "infeasible" in str(solve_summary.get("termination_condition", "")).lower()
                        else "build_only_guarded_buffer_sensitivity"
                    )
                ),
                "next_action": (
                    "use_for_24h_buffer_sensitivity_interpretation_only"
                    if solve_summary.get("feasible")
                    else "preserve_as_non_thesis_sensitivity_diagnostic"
                ),
            }
        )

    payload = {
        "scope": SCOPE_ID,
        "horizon_hours": horizon_hours,
        "solver_name": solver_name,
        "solver_available": solver is not None,
        "target_variant": target_variant,
        "inventory_mode": inventory_mode,
        "objective_type": resolved_objective_type,
        "sensitivity_id": sensitivity_id,
        "initial_inventory_fraction": initial_inventory_fraction,
        "capacity_multiplier_overrides": resolved_capacity_overrides,
        "diagnostic_overproduction_cap": diagnostic_overproduction_cap,
        "thesis_usability": False,
        "results": results,
    }
    if summary_output_path is not None:
        write_buffer_inventory_smoke_summary(results, summary_output_path)
    return payload


def run_buffer_sensitivity_suite(
    *,
    cases: list[dict[str, Any]],
    output_root: str | Path = DEFAULT_STEEL_SMOKE_RUN_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    solve_if_available: bool = True,
    summary_output_path: str | Path = DEFAULT_BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        payload = run_liquid_steel_smoke_cases(
            configuration_ids=(case["configuration_id"],),
            horizon_hours=24,
            target_variant=case.get("target_variant", "feasible_smoke"),
            inventory_mode=case.get("inventory_mode", "first_buffers"),
            solve_if_available=solve_if_available,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            output_root=output_root,
            sensitivity_id=case["sensitivity_id"],
            initial_inventory_fraction=case.get("initial_inventory_fraction"),
            capacity_multiplier_overrides=case.get("capacity_multiplier_overrides"),
        )
        results.append(payload["results"][0])
    summary_path = write_buffer_sensitivity_result_summary(results, summary_output_path)
    return {
        "scope": SCOPE_ID,
        "solver_name": _available_solver()[0],
        "solve_if_available": solve_if_available,
        "thesis_usability": False,
        "result_count": len(results),
        "summary_output_path": str(summary_path),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run guarded 24h steel S2 liquid-steel smoke diagnostics.")
    parser.add_argument(
        "--configuration-id",
        dest="configuration_ids",
        action="append",
        choices=sorted(ALLOWED_CONFIGURATION_IDS),
        help="Configuration ID to run. May be repeated. Defaults to C0 and C1.",
    )
    parser.add_argument("--build-only", action="store_true", help="Build diagnostics only; do not attempt a solve.")
    parser.add_argument(
        "--target-variant",
        default="feasible_smoke",
        choices=("feasible_smoke", "stress_infeasible_original"),
        help="Target variant to use for 24h smoke cases.",
    )
    parser.add_argument(
        "--inventory-mode",
        default="inactive",
        choices=("inactive", "first_buffers"),
        help="Inventory activation mode for the restricted smoke cases.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_STEEL_SMOKE_RUN_ROOT)
    parser.add_argument("--summary-output-path", type=Path, default=None)
    args = parser.parse_args()

    configuration_ids = tuple(args.configuration_ids) if args.configuration_ids else (
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    )
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=configuration_ids,
        horizon_hours=24,
        target_variant=args.target_variant,
        inventory_mode=args.inventory_mode,
        solve_if_available=not args.build_only,
        output_root=args.output_root,
        summary_output_path=args.summary_output_path,
    )
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
