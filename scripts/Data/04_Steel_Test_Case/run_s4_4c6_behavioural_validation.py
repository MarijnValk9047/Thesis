"""CLI for the governed pre-matrix C6 behavioural validation gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_behavioural_validation import (  # noqa: E402
    BEHAVIOURAL_CONFIG,
    aggregate_path_feasibility_case_artifacts,
    preflight,
    prepare_behavioural_run,
    run_behavioural_gate,
    run_full_path_feasibility_behavioural_gate,
    run_non_final_rolling_week_gate,
    run_path_feasibility_blocker_gate,
    run_s0_c1_augmented_planning_performance_diagnostic,
    run_s0_c1_constraint_generation_gate,
    run_single_path_feasibility_case_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=BEHAVIOURAL_CONFIG)
    parser.add_argument(
        "--mode",
        choices=(
            "preflight",
            "select",
            "synthetic",
            "shadow",
            "all",
            "path-full",
            "path-profile",
            "path-blocker",
            "path-target-s0",
            "path-case",
            "path-aggregate",
            "path-rolling-week",
        ),
        default="preflight",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--phase-b-summary",
        type=Path,
        help="Required proven blocker-summary provenance for --mode path-full.",
    )
    parser.add_argument(
        "--path-source-shadow-id",
        action="append",
        default=[],
        help="Repeat for each non-final feasibility path used by --mode path-profile.",
    )
    parser.add_argument("--baseline-progress-optimum-t", type=float)
    parser.add_argument(
        "--case-id",
        help="One non-final manifest case for --mode path-case.",
    )
    parser.add_argument(
        "--case-run-root",
        action="append",
        default=[],
        help="Completed governed case root; repeat for --mode path-aggregate.",
    )
    parser.add_argument(
        "--aggregate-phase",
        choices=("synthetic", "shadow"),
        help="Non-final phase aggregated by --mode path-aggregate.",
    )
    parser.add_argument(
        "--path-pattern-scope",
        choices=(
            "governed_validation",
            "shadow_only_runtime_diagnostic",
            "shadow_plus_case_validation",
        ),
        default="governed_validation",
        help="Pattern scope for the non-final --mode path-target-s0 gate.",
    )
    parser.add_argument(
        "--gurobi-performance-option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Safe engine-validated override for --mode path-profile.",
    )
    parser.add_argument(
        "--final-path-gurobi-performance-option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Override used only for the final prefix in --mode path-profile.",
    )
    args = parser.parse_args()
    if args.mode == "preflight":
        result = preflight(args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if args.mode == "select":
        prepared = prepare_behavioural_run(
            args.config, run_id=run_id, resume=bool(args.resume)
        )
        result = {
            "status": "prepared_no_solver_runs",
            "output": str(prepared["output"]),
            "output_declaration": prepared["declaration"],
            "shadow_days": prepared["selection"][
                ["regime_role", "day", "day_id"]
            ].to_dict(orient="records"),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.mode == "path-full":
        if args.resume:
            parser.error("--mode path-full is intentionally non-resumable.")
        if args.phase_b_summary is None:
            parser.error("--mode path-full requires --phase-b-summary.")
        result = run_full_path_feasibility_behavioural_gate(
            args.config,
            run_id=run_id,
            phase_b_summary_path=args.phase_b_summary,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-blocker":
        if args.resume:
            parser.error("--mode path-blocker is intentionally non-resumable.")
        result = run_path_feasibility_blocker_gate(
            args.config,
            run_id=run_id,
        )
        print(
            json.dumps(
                {"output": result["output"], "summary": result["summary"]},
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-profile":
        if args.resume:
            parser.error("--mode path-profile is intentionally non-resumable.")
        if not args.path_source_shadow_id:
            parser.error("--mode path-profile requires --path-source-shadow-id.")
        if args.baseline_progress_optimum_t is None:
            parser.error(
                "--mode path-profile requires --baseline-progress-optimum-t."
            )
        integer_options = {"MIPFocus", "Cuts", "Symmetry"}
        def parse_options(raw_options: list[str]) -> dict[str, int | float]:
            parsed: dict[str, int | float] = {}
            for raw_option in raw_options:
                name, separator, raw_value = raw_option.partition("=")
                if not separator or not name or not raw_value:
                    parser.error("Gurobi performance options must use NAME=VALUE.")
                try:
                    parsed[name] = (
                        int(raw_value)
                        if name in integer_options
                        else float(raw_value)
                    )
                except ValueError:
                    parser.error(f"Invalid numeric Gurobi option: {raw_option}.")
            return parsed

        performance_options = parse_options(args.gurobi_performance_option)
        final_performance_options = parse_options(
            args.final_path_gurobi_performance_option
        )
        result = run_s0_c1_augmented_planning_performance_diagnostic(
            args.config,
            run_id=run_id,
            source_shadow_ids=args.path_source_shadow_id,
            baseline_progress_optimum_t=args.baseline_progress_optimum_t,
            gurobi_performance_options=performance_options,
            final_path_gurobi_performance_options=final_performance_options,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-target-s0":
        if args.resume:
            parser.error("--mode path-target-s0 is intentionally non-resumable.")
        result = run_s0_c1_constraint_generation_gate(
            args.config,
            run_id=run_id,
            pattern_scope=args.path_pattern_scope,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-case":
        if args.resume:
            parser.error("--mode path-case is intentionally non-resumable.")
        if not args.case_id:
            parser.error("--mode path-case requires --case-id.")
        result = run_single_path_feasibility_case_gate(
            args.config,
            run_id=run_id,
            case_id=args.case_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-aggregate":
        if args.resume:
            parser.error("--mode path-aggregate is intentionally non-resumable.")
        if not args.case_run_root or not args.aggregate_phase:
            parser.error(
                "--mode path-aggregate requires --aggregate-phase and "
                "--case-run-root."
            )
        result = aggregate_path_feasibility_case_artifacts(
            args.config,
            run_id=run_id,
            phase=args.aggregate_phase,
            case_run_roots=args.case_run_root,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    if args.mode == "path-rolling-week":
        result = run_non_final_rolling_week_gate(
            args.config,
            run_id=run_id,
            resume=bool(args.resume),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"].get("decision") == "PASS" else 1
    result = run_behavioural_gate(
        args.config,
        run_id=run_id,
        phase=args.mode,
        resume=bool(args.resume),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    decision = result["summary"].get("decision")
    if args.mode == "synthetic":
        return 0 if result["summary"].get("synthetic_gate_pass") else 1
    return 0 if decision in {"PASS", "PASS_WITH_LIMITATION"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
