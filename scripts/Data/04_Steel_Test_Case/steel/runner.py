from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path

from pyomo.environ import SolverStatus, TerminationCondition, value
from pyomo.contrib.solver.common.util import NoFeasibleSolutionError

from .config import load_config
from .diagnostics import classify_infeasibility
from .model import build_model, choose_solver, collect_model_stats
from .reporting import (
    build_code_version,
    build_feasible_validation_frame,
    build_infeasible_validation_frame,
    build_run_summary,
    extract_solution_frames,
    fingerprint_file,
    iso_utc,
    now_utc,
    repo_rel,
    write_json,
    write_yaml,
)


def _write_solver_log_placeholder(path: Path, solver_name: str, note: str) -> None:
    path.write_text(
        f"solver={solver_name}\n{note}\n",
        encoding="utf-8",
    )


def _solve_model(model, solver, solver_name: str, solver_log_path: Path):
    try:
        return solver.solve(model, tee=False, logfile=str(solver_log_path))
    except (TypeError, NotImplementedError):
        _write_solver_log_placeholder(
            solver_log_path,
            solver_name,
            "Solver plugin did not accept logfile argument; see JSON summaries for compact run metadata.",
        )
        try:
            return solver.solve(model, tee=False)
        except NoFeasibleSolutionError:
            return solver.solve(model, tee=False, load_solutions=False)
    except NoFeasibleSolutionError:
        return solver.solve(model, tee=False, load_solutions=False)


def _build_model_stats_payload(model_stats) -> dict[str, int]:
    return {
        "variable_count": model_stats.variables,
        "binary_count": model_stats.binaries,
        "constraint_count": model_stats.constraints,
    }


def _build_solver_summary_payload(
    *,
    solver_name: str,
    solver_status: str,
    termination_condition: str,
    objective_value: float | None,
    runtime_seconds: float,
    result,
) -> dict[str, object]:
    mip_gap = getattr(result.solver, "gap", None)
    return {
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": objective_value,
        "runtime_seconds": runtime_seconds,
        "mip_gap": mip_gap,
    }


def _build_warnings(config) -> list[str]:
    governance = config.input_governance
    return [
        "All numerical values are toy scaffold values only and are not approved Tata Steel IJmuiden inputs.",
        "Governed toy input tables are scaffold inputs only, not approved model inputs and not Tata-specific quantitative evidence.",
        "S2 uses simple indexed hourly periods rather than market-timestamped UTC delivery times; this is intentional for the first smoke scaffold.",
        "This run excludes S3 internal energy, emissions costs, network tariffs, DA prices, DA bidding, stochasticity, mFRR, quarter-hour granularity, D+4 horizon, CVaR, and product revenue by design.",
        "The run is structural smoke evidence only and is not thesis-grade quantitative evidence.",
        f"Declared input_mode={governance.input_mode}.",
        governance.thesis_usability_reason,
        config.model.note,
    ]


def run_from_config(config_path: str | Path, *, output_root_override: str | Path | None = None, run_id_override: str | None = None) -> dict[str, object]:
    config = load_config(config_path)
    repo_root = Path(__file__).resolve().parents[4]
    runner_path = Path(__file__).resolve()
    started = now_utc()
    run_id = run_id_override or f"{started.strftime('%Y%m%d_%H%M%S')}_{config.run.run_slug}"
    output_root_base = Path(output_root_override) if output_root_override is not None else repo_root / config.run.output_root
    run_dir = (output_root_base / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)

    model = build_model(config)
    model_stats = collect_model_stats(model)
    solver_name, solver = choose_solver(config)

    solver_log_path = run_dir / "solver_log.txt"
    wall_start = time.perf_counter()
    result = _solve_model(model, solver, solver_name, solver_log_path)
    runtime_seconds = time.perf_counter() - wall_start

    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    success = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )

    objective_value = float(value(model.total_cost)) if success else None
    warnings = _build_warnings(config)
    thesis_usable = "yes" if config.input_governance.thesis_usable else "no"
    code_version = build_code_version(repo_root, runner_path)

    resolved_config = dict(config.raw)
    resolved_config["resolved_run_id"] = run_id
    resolved_config["resolved_output_root"] = repo_rel(run_dir, repo_root)
    resolved_config["resolved_solver"] = solver_name
    resolved_config["resolved_timestamp_utc"] = iso_utc(started)
    resolved_config["resolved_case_label"] = config.diagnostics.case_label
    resolved_config["resolved_input_mode"] = config.input_governance.input_mode
    write_yaml(run_dir / "resolved_config.yaml", resolved_config)

    input_manifest = {
        "config_file": fingerprint_file(config.config_path, repo_root),
        "approved_asset_inputs_used": bool(config.input_governance.all_required_inputs_approved),
        "toy_scaffold_only": bool(config.input_governance.contains_toy_values and config.input_governance.input_mode == "toy_scaffold"),
        "input_mode": config.input_governance.input_mode,
        "contains_toy_values": config.input_governance.contains_toy_values,
        "contains_candidate_not_approved_values": config.input_governance.contains_candidate_not_approved_values,
        "contains_validation_only_values": config.input_governance.contains_validation_only_values,
        "all_required_inputs_approved": config.input_governance.all_required_inputs_approved,
        "thesis_usable": thesis_usable,
        "thesis_usability_reason": config.input_governance.thesis_usability_reason,
        "input_paths": [
            {
                "path": repo_rel(config.config_path, repo_root),
                "role": f"{config.input_governance.input_mode}_config",
            }
        ]
        + [
            {
                "path": repo_rel(path, repo_root),
                "role": f"governed_input_table::{table_name}",
            }
            for table_name, path in config.input_table_paths.items()
        ],
        "governed_input_table_row_counts": config.input_table_row_counts,
    }
    write_json(run_dir / "input_manifest.json", input_manifest)

    write_json(run_dir / "code_version.json", code_version)
    write_json(run_dir / "model_stats.json", _build_model_stats_payload(model_stats))
    write_json(
        run_dir / "solver_summary.json",
        _build_solver_summary_payload(
            solver_name=solver_name,
            solver_status=solver_status,
            termination_condition=termination_condition,
            objective_value=objective_value,
            runtime_seconds=runtime_seconds,
            result=result,
        ),
    )

    validation_summary = None
    infeasibility_class = None
    if success:
        flows, inventories, production_summary = extract_solution_frames(model, config)
        validation_summary = build_feasible_validation_frame(model, config, solver_status)
        flows.to_csv(run_dir / "flows.csv", index=False)
        inventories.to_csv(run_dir / "inventories.csv", index=False)
        production_summary.to_csv(run_dir / "production_summary.csv", index=False)
        validation_summary.to_csv(run_dir / "validation_summary.csv", index=False)
        stage_note = (
            "# S2.3 Stage Note\n\n"
            "This run is the governed-input S2 deterministic hourly metallic material-flow LP scaffold with the S2.3 input-governance guard.\n\n"
            "- Purpose: prove the governed toy input-table bridge, input-mode guard, and run-output infrastructure.\n"
            "- Time indexing: simple hourly indices `0..23` for a one-day toy smoke horizon.\n"
            f"- Input mode: `{config.input_governance.input_mode}`.\n"
            "- Numerical status: all values are scaffold/toy/not approved.\n"
            f"- Thesis status: {thesis_usable}; {config.input_governance.thesis_usability_reason}\n"
        )
    else:
        infeasibility_payload = classify_infeasibility(config, solver)
        infeasibility_class = str(infeasibility_payload["infeasibility_class"])
        validation_summary = build_infeasible_validation_frame(
            config,
            solver_status=solver_status,
            termination_condition=termination_condition,
            infeasibility_class=infeasibility_class,
            expected_infeasibility_class=config.diagnostics.expected_infeasibility_class,
        )
        validation_summary.to_csv(run_dir / "validation_summary.csv", index=False)
        write_json(
            run_dir / "infeasibility_summary.json",
            {
                **infeasibility_payload,
                "expected_infeasibility_class": config.diagnostics.expected_infeasibility_class,
                "expected_class_match": config.diagnostics.expected_infeasibility_class in {None, infeasibility_class},
            },
        )
        stage_note = (
            "# S2.3 Stage Note\n\n"
            "This run is an explicit S2 infeasibility-classification smoke case under the S2.3 input-governance guard.\n\n"
            "- Purpose: prove that structural infeasibility is reported without slacks.\n"
            f"- Input mode: `{config.input_governance.input_mode}`.\n"
            "- Numerical status: all values are scaffold/toy/not approved.\n"
            f"- Thesis status: {thesis_usable}; {config.input_governance.thesis_usability_reason}\n"
        )

    warnings_path = run_dir / "warnings_and_limitations.md"
    warnings_path.write_text("\n".join(f"- {warning}" for warning in warnings) + "\n", encoding="utf-8")
    (run_dir / "stage_note.md").write_text(stage_note, encoding="utf-8")

    run_summary = build_run_summary(
        run_id=run_id,
        started=started,
        solver_name=solver_name,
        solver_status=solver_status,
        termination_condition=termination_condition,
        objective_value=objective_value,
        runtime_seconds=runtime_seconds,
        model_stats=model_stats,
        input_governance=config.input_governance,
    )
    run_summary["infeasibility_class"] = infeasibility_class
    write_json(run_dir / "run_summary.json", run_summary)

    files = [
        "resolved_config.yaml",
        "input_manifest.json",
        "code_version.json",
        "model_stats.json",
        "solver_summary.json",
        "run_summary.json",
        "validation_summary.csv",
        "warnings_and_limitations.md",
        "stage_note.md",
        "solver_log.txt",
        "registry_entry.json",
    ]
    if success:
        files[6:6] = ["flows.csv", "inventories.csv", "production_summary.csv"]
    else:
        files.insert(6, "infeasibility_summary.json")
    write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "domain": "optimisation",
            "pipeline_stage": "steel_s2_smoke",
            "output_policy": config.run.output_policy,
            "run_class": config.run.run_class,
            "lineage_role": config.run.lineage_role,
            "thesis_usable": thesis_usable,
            "thesis_usability_reason": config.input_governance.thesis_usability_reason,
            "input_mode": config.input_governance.input_mode,
            "output_root": repo_rel(run_dir, repo_root),
            "files": files,
        },
    )

    registry_entry = {
        "run_id": run_id,
        "timestamp": iso_utc(started),
        "domain": "optimisation",
        "market": "none",
        "pipeline_stage": "steel_s2_smoke",
        "granularity": "hourly",
        "horizon": "D_only_one_day_toy",
        "model_family": "steel_material_flow_lp",
        "feature_set": "none",
        "scenario_source": "none",
        "input_artifacts": [{"artifact_id": "steel_s2_toy_config", "path": repo_rel(config.config_path, repo_root)}],
        "output_root": repo_rel(run_dir, repo_root),
        "output_policy": config.run.output_policy,
        "run_class": config.run.run_class,
        "lineage_role": config.run.lineage_role,
        "status": "completed" if success else "failed",
        "thesis_usable": thesis_usable,
        "input_mode": config.input_governance.input_mode,
        "key_result": (
            f"S2 toy smoke run solved with solver_status={solver_status} and termination={termination_condition}."
            if success
            else f"S2 infeasibility smoke run classified as {infeasibility_class}."
        ),
        "limitations": "; ".join(warnings),
        "archive_location": None,
        "delete_after": None,
        "git_commit": code_version["git_commit"],
    }
    write_json(run_dir / "registry_entry.json", registry_entry)

    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": objective_value,
        "runtime_seconds": runtime_seconds,
        "model_stats": asdict(model_stats),
        "input_mode": config.input_governance.input_mode,
        "thesis_usable": thesis_usable,
        "thesis_usability_reason": config.input_governance.thesis_usability_reason,
        "validation_summary": validation_summary.to_dict(orient="records"),
        "infeasibility_class": infeasibility_class,
    }
