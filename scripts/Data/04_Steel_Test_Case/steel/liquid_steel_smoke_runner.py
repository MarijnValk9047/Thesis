from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pyomo.contrib.solver.common.util import NoFeasibleSolutionError
from pyomo.environ import Constraint, Objective, SolverFactory, SolverStatus, TerminationCondition, minimize, value

from .liquid_steel_smoke_builder import (
    ALLOWED_CONFIGURATION_IDS,
    DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    DEFAULT_REVIEW_ROOT,
    LiquidSteelSmokeBuilderError,
    PreparedSmokeInputs,
    _infer_output_carrier,
    build_liquid_steel_smoke_model,
    validate_liquid_steel_smoke_inputs,
)
from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STEEL_SMOKE_RUN_ROOT = (
    REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "runs" / "steel_s2_liquid_smoke"
)
DEFAULT_SOLVER_PREFERENCE = ("gurobi", "appsi_highs", "highs", "cbc", "glpk")
SCOPE_ID = "restricted_liquid_steel_smoke"


def _normalise_run_slug(configuration_id: str, horizon_hours: int, target_variant: str, timestamp: datetime) -> str:
    return f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{configuration_id}_{horizon_hours}h_{target_variant}"


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
    return {
        "objective_name": objective.name,
        "objective_sense": "minimize" if objective.sense == minimize else "maximize",
        "objective_type": "minimise_overproduction_dev_only",
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
        "available_configurations": list(report.available_configurations),
        "selected_configurations": list(report.selected_configurations),
        "selected_target_variant": report.selected_target_variant,
        "consumed_process_bound_rows": list(report.consumed_process_bound_rows),
        "consumed_conversion_rows": list(report.consumed_conversion_rows),
        "consumed_production_target_rows": list(report.consumed_production_target_rows),
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
        "bound_summary": _active_bound_summary(prepared),
        **_objective_summary(model),
        "shortfall_slack_active": False,
        "inventory_active": False,
        "downstream_active": False,
        "thesis_usability": False,
    }


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
    base = {
        "solve_attempted": solve_attempted,
        "solver_name": solver_name,
        "thesis_usability": False,
        "hard_target_without_slack": True,
        "target_variant": prepared.validation_report.selected_target_variant,
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
            "carrier_balance_max_abs_residual": _carrier_balance_residual(model) if success else None,
            "process_activity_summary": _process_activity_summary(model) if success else None,
            "feasible": success,
            "infeasible": infeasible,
        }
    )
    if not success:
        base["capacity_diagnostic"] = _capacity_diagnostic(prepared)
    return base


def _warning_list(configuration_id: str) -> list[str]:
    return [
        "All outputs in this run folder are provisional development diagnostics only.",
        "thesis_usability=false",
        "input_surface=s2_provisional_dev_input",
        "objective_type=minimise_overproduction_dev_only",
        "consumed_rows_must_be_dev_executable_only",
        "approved_input_used=false",
        "shortfall_slack_active=false",
        "inventory_active=false",
        "downstream_active=false",
        "energy_cost_emissions_active=false",
        "market_logic_active=false",
        f"configuration_id={configuration_id}",
    ]


def _limitations_text(configuration_id: str) -> str:
    return "\n".join(
        [
            "# Limitations",
            "",
            f"- configuration: `{configuration_id}`",
            "- scope: restricted liquid-steel smoke only",
            "- no inventory activation",
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


def run_liquid_steel_smoke_cases(
    *,
    configuration_ids: tuple[str, ...] = (
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    ),
    horizon_hours: int = 24,
    target_variant: str = "feasible_smoke",
    solve_if_available: bool = True,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    output_root: str | Path = DEFAULT_STEEL_SMOKE_RUN_ROOT,
) -> dict[str, Any]:
    if horizon_hours != 24:
        raise LiquidSteelSmokeBuilderError("S2.9b is limited to 24h smoke cases only.")

    output_root_path = Path(output_root).resolve()
    output_root_path.mkdir(parents=True, exist_ok=True)

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
            enable_inventory_rows=False,
        )
        model = build_liquid_steel_smoke_model(
            configuration_id=configuration_id,
            horizon_hours=horizon_hours,
            target_variant=target_variant,
            provisional_dev_input_root=provisional_dev_input_root,
            review_root=review_root,
            enable_inventory_rows=False,
            allow_target_shortfall=False,
        )

        timestamp = now_utc()
        run_dir = output_root_path / _normalise_run_slug(
            configuration_id,
            horizon_hours,
            prepared.validation_report.selected_target_variant,
            timestamp,
        )
        input_validation_payload = _build_input_validation_payload(prepared)
        model_stats_payload = _build_model_stats_payload(model, prepared)
        warnings = _warning_list(configuration_id)

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
            "input_surface": "s2_provisional_dev_input",
            "refused_input_surface": "s2_approved_model_input",
            "approved_input_used": False,
            "objective_type": "minimise_overproduction_dev_only",
            "shortfall_slack_active": False,
            "inventory_active": False,
            "downstream_active": False,
            "energy_cost_emissions_active": False,
            "market_logic_active": False,
            "thesis_usability": False,
            "solve_if_available": solve_if_available,
            "solver_name_selected": solver_name,
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
            "selected_target_variant": prepared.validation_report.selected_target_variant,
            "refused_row_count": len(prepared.validation_report.refused_rows),
            "thesis_usability": False,
            "approved_input_used": False,
            "input_surface": "s2_provisional_dev_input",
        }
        _write_run_folder(
            run_dir=run_dir,
            resolved_config=resolved_config,
            input_manifest=input_manifest,
            model_stats_payload=model_stats_payload,
            input_validation_payload=input_validation_payload,
            solve_summary=solve_summary,
            warnings=warnings,
            limitations_text=_limitations_text(configuration_id),
        )

        results.append(
            {
                "configuration_id": configuration_id,
                "target_variant": prepared.validation_report.selected_target_variant,
                "run_dir": str(run_dir),
                "solve_summary": solve_summary,
                "model_stats": model_stats_payload,
                "input_validation_summary": input_validation_payload,
            }
        )

    return {
        "scope": SCOPE_ID,
        "horizon_hours": horizon_hours,
        "solver_name": solver_name,
        "solver_available": solver is not None,
        "target_variant": target_variant,
        "objective_type": "minimise_overproduction_dev_only",
        "thesis_usability": False,
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
    parser.add_argument("--output-root", type=Path, default=DEFAULT_STEEL_SMOKE_RUN_ROOT)
    args = parser.parse_args()

    configuration_ids = tuple(args.configuration_ids) if args.configuration_ids else (
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    )
    payload = run_liquid_steel_smoke_cases(
        configuration_ids=configuration_ids,
        horizon_hours=24,
        target_variant=args.target_variant,
        solve_if_available=not args.build_only,
        output_root=args.output_root,
    )
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
