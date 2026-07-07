from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Objective, SolverFactory, SolverStatus, TerminationCondition, value

from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json
from .s3_4_guardrails import build_s34_guardrail_smoke_model, summarise_s34_guardrails


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_S40B_REPORT_JSON_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s4_0b_guardrail_regression_report.json"
)
DEFAULT_S40B_REPORT_CSV_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s4_0b_guardrail_regression_report.csv"
)
DEFAULT_SOLVER_PREFERENCE = ("gurobi", "appsi_highs", "highs", "cbc", "glpk")
S40B_MODE_ID = "s4_0b_static_zero_price_guardrail_regression"
S40B_TOLERANCE = 1e-6
FORBIDDEN_MARKET_FIELDS = {
    "da_price",
    "da_prices",
    "price_series",
    "market_settlement",
    "realised_price",
    "submitted_bids",
    "bid_clearing",
    "product_revenue",
    "cvar",
    "mfrr",
}


def _available_solver(preferred_solvers: tuple[str, ...] = DEFAULT_SOLVER_PREFERENCE):
    for solver_name in preferred_solvers:
        try:
            solver = SolverFactory(solver_name)
        except Exception:
            continue
        if solver is not None and solver.available(exception_flag=False):
            return solver_name, solver
    return None, None


def _mip_gap(result) -> float | None:
    solver_payload = getattr(result, "solver", None)
    if solver_payload is None:
        return None
    for attr_name in ("mip_gap", "MIPGap", "gap"):
        gap_value = getattr(solver_payload, attr_name, None)
        if gap_value is not None:
            try:
                return float(gap_value)
            except (TypeError, ValueError):
                return None
    statistics = getattr(solver_payload, "statistics", None)
    branch_and_bound = getattr(statistics, "branch_and_bound", None) if statistics is not None else None
    gap_value = getattr(branch_and_bound, "gap", None) if branch_and_bound is not None else None
    if gap_value is None:
        return None
    try:
        return float(gap_value)
    except (TypeError, ValueError):
        return None


def _active_objective_value(model) -> float | None:
    active = list(model.component_data_objects(Objective, active=True, descend_into=True))
    if not active:
        return None
    return float(value(active[0]))


def _required_report_fields() -> tuple[str, ...]:
    return (
        "run_id",
        "mode",
        "timestamp_utc",
        "solver_name",
        "solver_status",
        "termination_condition",
        "objective_value",
        "runtime_seconds",
        "mip_gap",
        "variable_count",
        "binary_count",
        "constraint_count",
        "production_target_residual",
        "dri_terminal_residual",
        "dri_buffer_min",
        "dri_buffer_max",
        "eaf_on_hours",
        "eaf_off_hours",
        "eaf_min_bound_hits",
        "eaf_max_bound_hits",
        "eaf_electricity_mwh",
        "eaf_dri_input_total",
        "eaf_liquid_steel_output_total",
        "drp_pellet_input_total",
        "drp_dri_output_total",
        "drp_max_ramp_usage",
        "drp_min_bound_hits",
        "drp_max_bound_hits",
        "drp_electricity_mwh",
        "drp_ng_nm3",
        "drp_o2_t",
        "gate_passed",
        "caveats_limitations",
    )


def _guardrail_totals(model) -> dict[str, float]:
    return {
        "eaf_dri_input_total": round(sum(float(value(model.s34_eaf_dri_input[t])) for t in model.TIME), 6),
        "eaf_liquid_steel_output_total": round(
            sum(float(value(model.process_activity["c1_eaf", t])) for t in model.TIME),
            6,
        ),
        "drp_pellet_input_total": round(sum(float(value(model.s34_drp_pellet_input[t])) for t in model.TIME), 6),
        "drp_dri_output_total": round(sum(float(value(model.s34_drp_dri_output[t])) for t in model.TIME), 6),
        "drp_electricity_mwh": round(sum(float(value(model.s34_drp_electricity_mwh[t])) for t in model.TIME), 6),
        "drp_ng_nm3": round(sum(float(value(model.s34_drp_ng_nm3[t])) for t in model.TIME), 6),
        "drp_o2_t": round(sum(float(value(model.s34_drp_oxygen_input_t[t])) for t in model.TIME), 6),
    }


def _check_report(report: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    tolerance = S40B_TOLERANCE
    checks = [
        {
            "check_name": "solver_optimal_or_feasible",
            "passed": report["solver_status"] in {"ok", "warning"}
            and report["termination_condition"] in {"optimal", "feasible"},
            "actual_value": f"{report['solver_status']}:{report['termination_condition']}",
            "expected_value": "ok_or_warning:optimal_or_feasible",
        },
        {
            "check_name": "production_target_residual_zero",
            "passed": abs(float(report["production_target_residual"])) <= tolerance,
            "actual_value": report["production_target_residual"],
            "expected_value": 0.0,
        },
        {
            "check_name": "dri_terminal_residual_zero",
            "passed": abs(float(report["dri_terminal_residual"])) <= tolerance,
            "actual_value": report["dri_terminal_residual"],
            "expected_value": 0.0,
        },
        {
            "check_name": "eaf_on_off_count_closes",
            "passed": int(report["eaf_on_hours"]) + int(report["eaf_off_hours"]) == int(report["horizon_hours"]),
            "actual_value": int(report["eaf_on_hours"]) + int(report["eaf_off_hours"]),
            "expected_value": int(report["horizon_hours"]),
        },
        {
            "check_name": "eaf_binary_positive",
            "passed": int(report["binary_count"]) > 0,
            "actual_value": int(report["binary_count"]),
            "expected_value": ">0",
        },
        {
            "check_name": "drp_ramp_within_limit",
            "passed": float(report["drp_max_ramp_usage"]) <= float(report["drp_ramp_limit"]) + tolerance,
            "actual_value": report["drp_max_ramp_usage"],
            "expected_value": report["drp_ramp_limit"],
        },
        {
            "check_name": "dri_buffer_nonnegative",
            "passed": float(report["dri_buffer_min"]) >= -tolerance,
            "actual_value": report["dri_buffer_min"],
            "expected_value": ">=0",
        },
        {
            "check_name": "dri_buffer_within_capacity",
            "passed": float(report["dri_buffer_max"]) <= float(report["dri_buffer_capacity"]) + tolerance,
            "actual_value": report["dri_buffer_max"],
            "expected_value": report["dri_buffer_capacity"],
        },
    ]
    missing = [field for field in _required_report_fields() if field not in report]
    checks.append(
        {
            "check_name": "required_diagnostics_present",
            "passed": not missing,
            "actual_value": ";".join(missing),
            "expected_value": "all_required_report_fields",
        }
    )
    forbidden = [field for field in FORBIDDEN_MARKET_FIELDS if field in report]
    checks.append(
        {
            "check_name": "no_market_fields_active",
            "passed": not forbidden,
            "actual_value": ";".join(forbidden),
            "expected_value": "no_DA_or_market_settlement_fields",
        }
    )
    return all(bool(check["passed"]) for check in checks), checks


def _write_report_artifacts(report: dict[str, Any], *, json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(json_path, report)
    flat_report = {key: value for key, value in report.items() if not isinstance(value, (dict, list))}
    pd.DataFrame([flat_report]).to_csv(csv_path, index=False)


def run_s40b_guardrail_regression(
    *,
    horizon_hours: int = 24,
    target_variant: str = "feasible_smoke",
    run_id: str | None = None,
    solver_name: str | None = None,
    report_json_path: str | Path | None = DEFAULT_S40B_REPORT_JSON_PATH,
    report_csv_path: str | Path | None = DEFAULT_S40B_REPORT_CSV_PATH,
    write_report: bool = True,
    strict: bool = True,
) -> dict[str, Any]:
    timestamp = now_utc()
    resolved_run_id = run_id or f"{S40B_MODE_ID}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    resolved_solver_name, solver = _available_solver((solver_name,) if solver_name else DEFAULT_SOLVER_PREFERENCE)
    if solver is None or resolved_solver_name is None:
        raise RuntimeError("No configured MILP solver is available for S4.0b guardrail regression.")

    model = build_s34_guardrail_smoke_model(
        horizon_hours=horizon_hours,
        target_variant=target_variant,
    )
    start = time.perf_counter()
    result = solver.solve(model, tee=False)
    runtime_seconds = time.perf_counter() - start
    solved = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )
    summary = summarise_s34_guardrails(model, solved=solved)
    totals = _guardrail_totals(model) if solved else {}

    caveats = (
        "C1/future-route only; C0 remains S3.3j baseline. "
        "Development-only S3.4/S4.0a input surface, not thesis-approved or Tata-measured. "
        "Static/zero-price regression only; no DA prices, bidding, settlement, stochasticity, CVaR, mFRR, QH, product revenue, or heat sequencing. "
        "Electricity, NG and O2 quantities are diagnostics, not full utility balances. "
        "DRI buffer initial inventory is zero for smoke testing."
    )
    report: dict[str, Any] = {
        "run_id": resolved_run_id,
        "mode": S40B_MODE_ID,
        "timestamp_utc": iso_utc(timestamp),
        "git_commit": resolve_git_commit(REPO_ROOT),
        "configuration_id": model.s2_metadata["configuration_id"],
        "horizon_hours": horizon_hours,
        "target_variant": target_variant,
        "solver_name": resolved_solver_name,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value": round(_active_objective_value(model) or 0.0, 6) if solved else None,
        "runtime_seconds": round(runtime_seconds, 6),
        "mip_gap": _mip_gap(result),
        "variable_count": summary["variable_count"],
        "binary_count": summary["binary_count"],
        "constraint_count": summary["constraint_count"],
        "production_target_residual": summary.get("production_target_residual_t"),
        "dri_terminal_residual": summary.get("dri_buffer_terminal_residual_t"),
        "dri_buffer_min": summary.get("dri_buffer_min_t"),
        "dri_buffer_max": summary.get("dri_buffer_max_t"),
        "dri_buffer_capacity": summary["dri_buffer_capacity_t"],
        "eaf_on_hours": summary.get("eaf_on_count"),
        "eaf_off_hours": summary.get("eaf_off_count"),
        "eaf_min_bound_hits": summary.get("eaf_min_bound_hits"),
        "eaf_max_bound_hits": summary.get("eaf_max_bound_hits"),
        "eaf_electricity_mwh": summary.get("eaf_electricity_mwh"),
        "eaf_dri_input_total": totals.get("eaf_dri_input_total"),
        "eaf_liquid_steel_output_total": totals.get("eaf_liquid_steel_output_total"),
        "drp_pellet_input_total": totals.get("drp_pellet_input_total"),
        "drp_dri_output_total": totals.get("drp_dri_output_total"),
        "drp_max_ramp_usage": summary.get("drp_max_ramp_usage_tph"),
        "drp_ramp_limit": summary.get("drp_ramp_limit_tph"),
        "drp_min_bound_hits": summary.get("drp_min_bound_hits"),
        "drp_max_bound_hits": summary.get("drp_max_bound_hits"),
        "drp_electricity_mwh": totals.get("drp_electricity_mwh"),
        "drp_ng_nm3": totals.get("drp_ng_nm3"),
        "drp_o2_t": totals.get("drp_o2_t"),
        "caveats_limitations": caveats,
        "report_json_path": repo_rel(Path(report_json_path), REPO_ROOT) if report_json_path else "",
        "report_csv_path": repo_rel(Path(report_csv_path), REPO_ROOT) if report_csv_path else "",
        "gate_passed": False,
    }
    gate_passed, checks = _check_report(report)
    report["gate_passed"] = gate_passed
    report["checks"] = checks

    if write_report:
        if report_json_path is None or report_csv_path is None:
            raise ValueError("report_json_path and report_csv_path are required when write_report=True.")
        _write_report_artifacts(report, json_path=Path(report_json_path), csv_path=Path(report_csv_path))
    if strict and not gate_passed:
        failed = [check["check_name"] for check in checks if not check["passed"]]
        raise RuntimeError(f"S4.0b guardrail regression failed checks: {failed}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run S4.0b static/zero-price DRP/EAF guardrail regression.")
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--target-variant", type=str, default="feasible_smoke")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--solver", type=str, default=None)
    parser.add_argument("--report-json-path", type=Path, default=DEFAULT_S40B_REPORT_JSON_PATH)
    parser.add_argument("--report-csv-path", type=Path, default=DEFAULT_S40B_REPORT_CSV_PATH)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--non-strict", action="store_true")
    args = parser.parse_args(argv)

    report = run_s40b_guardrail_regression(
        horizon_hours=args.horizon_hours,
        target_variant=args.target_variant,
        run_id=args.run_id,
        solver_name=args.solver,
        report_json_path=args.report_json_path,
        report_csv_path=args.report_csv_path,
        write_report=not args.no_write,
        strict=not args.non_strict,
    )
    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "mode": report["mode"],
                "solver_name": report["solver_name"],
                "solver_status": report["solver_status"],
                "termination_condition": report["termination_condition"],
                "objective_value": report["objective_value"],
                "runtime_seconds": report["runtime_seconds"],
                "variable_count": report["variable_count"],
                "binary_count": report["binary_count"],
                "constraint_count": report["constraint_count"],
                "gate_passed": report["gate_passed"],
                "report_json_path": report["report_json_path"],
                "report_csv_path": report["report_csv_path"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
