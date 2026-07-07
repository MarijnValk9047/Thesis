"""S4.4c1 24h static physical regression over the S4.4b5 input package."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5_c0_c1_assumption_completion import COMPLETED_INPUT_DIR, S44B5_DIR
from .s4_4c_unified_physical_modelbuilder import (
    S44CModelBuilderError,
    run_s44c_unified_physical_regression,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S44C1_DIR = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c1_unified_static_physical_regression"
)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    columns = list(fieldnames or [])
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _folder_stats(path: Path) -> tuple[int, int]:
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    return len(files), sum(candidate.stat().st_size for candidate in files)


def _b5_gate() -> str:
    gate_path = S44B5_DIR / "s4_4b5_stage_gate.json"
    if not gate_path.exists():
        return "missing"
    return json.loads(gate_path.read_text(encoding="utf-8")).get("decision", "missing")


def _c1_decision(audits: list[dict[str, Any]]) -> str:
    statuses = {row["configuration_id"]: row["build_status"] for row in audits}
    c0 = statuses.get("C0_current_BF_BOF_reference")
    c1 = statuses.get("C1_phase1_BF_BOF_plus_DRP_EAF")
    if c0 == "solved" and c1 == "solved":
        return "pass_24h_static_physical_both_configs"
    if c0 != "solved" and c1 == "solved":
        return "pass_24h_static_physical_c1_only_c0_blocked"
    if c0 in {"solver_failed"} or c1 in {"solver_failed"}:
        return "blocked_solver_failure"
    return "blocked_24h_static_physical_both_configs"


def _report_rows(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for audit in audits:
        rows.append(
            {
                "configuration_id": audit["configuration_id"],
                "build_status": audit["build_status"],
                "solver_name": audit.get("solver_name", ""),
                "solver_status": audit.get("solver_status", ""),
                "termination_condition": audit.get("termination_condition", ""),
                "objective_value": audit.get("objective_value", ""),
                "final_product_target_t": audit.get("final_product_target_t", ""),
                "final_product_fulfilled_t": audit.get("final_product_fulfilled_t", ""),
                "final_product_residual_t": audit.get("final_product_residual_t", ""),
                "variable_count": audit.get("variable_count", ""),
                "binary_count": audit.get("binary_count", ""),
                "constraint_count": audit.get("constraint_count", ""),
                "caveat": audit.get("caveat", ""),
            }
        )
    return rows


def _run_metric_rows(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = []
    for audit in audits:
        metrics.append(
            {
                "configuration_id": audit["configuration_id"],
                "build_status": audit["build_status"],
                "final_product_target_t": audit.get("final_product_target_t", ""),
                "final_product_fulfilled_t": audit.get("final_product_fulfilled_t", ""),
                "final_product_residual_t": audit.get("final_product_residual_t", ""),
                "electricity_mwh": audit.get("electricity_mwh", ""),
                "natural_gas_nm3": audit.get("natural_gas_nm3", ""),
                "oxygen_t": audit.get("oxygen_t", ""),
                "WAG_generated": audit.get("WAG_generated", ""),
                "WAG_used": audit.get("WAG_used", ""),
                "WAG_flared": audit.get("WAG_flared", ""),
                "dri_terminal_residual_t": audit.get("dri_terminal_residual_t", ""),
                "hot_iron_terminal_residual_t": audit.get("hot_iron_terminal_residual_t", ""),
                "cold_slab_terminal_residual_t": audit.get("cold_slab_terminal_residual_t", ""),
                "caveat": audit.get("caveat", ""),
            }
        )
    return metrics


def _analytics_rows(
    audits: list[dict[str, Any]],
    *,
    input_validation_time: float,
    total_runtime: float,
    output_file_count: int,
    output_folder_size_bytes: int,
) -> list[dict[str, Any]]:
    rows = []
    for audit in audits:
        variable_count = int(audit.get("variable_count") or 0)
        binary_count = int(audit.get("binary_count") or 0)
        rows.append(
            {
                "configuration_id": audit["configuration_id"],
                "input_validation_time_seconds": round(input_validation_time, 6),
                "model_build_time_seconds": audit.get("build_runtime_seconds", ""),
                "solve_time_seconds": audit.get("runtime_seconds", ""),
                "reporting_output_time_seconds": "",
                "total_runtime_seconds": round(total_runtime, 6),
                "solver_name": audit.get("solver_name", ""),
                "solver_status": audit.get("solver_status", ""),
                "termination_condition": audit.get("termination_condition", ""),
                "objective_value": audit.get("objective_value", ""),
                "variable_count": variable_count,
                "binary_count": binary_count,
                "continuous_variable_count": variable_count - binary_count,
                "constraint_count": audit.get("constraint_count", ""),
                "nonzero_count": "",
                "mip_gap": audit.get("mip_gap", ""),
                "node_count": "",
                "iteration_count": "",
                "peak_memory_mb": "",
                "output_folder_size_bytes": output_folder_size_bytes,
                "output_file_count": output_file_count,
                "caveat": "Computational analytics are captured for the static 24h development regression; unavailable solver internals are left blank.",
            }
        )
    return rows


def _infeasibility_rows(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration_id": audit["configuration_id"],
            "build_status": audit["build_status"],
            "solver_status": audit.get("solver_status", ""),
            "termination_condition": audit.get("termination_condition", ""),
            "caveat": audit.get("caveat", ""),
        }
        for audit in audits
        if audit.get("build_status") != "solved"
    ]


def run_s4_4c1_static_physical_regression() -> dict[str, Any]:
    total_start = time.perf_counter()
    S44C1_DIR.mkdir(parents=True, exist_ok=True)
    b5_gate = _b5_gate()
    if b5_gate != "pass_to_s4_4c1_static_physical_regression":
        stage_gate = {
            "stage": "S4.4c1",
            "decision": "blocked_modelbuilder_input_contract_mismatch",
            "b5_gate": b5_gate,
            "caveat": "S4.4c1 did not execute because S4.4b5 did not pass its gate.",
        }
        _write_json(S44C1_DIR / "s4_4c1_stage_gate.json", stage_gate)
        _write_csv(S44C1_DIR / "s4_4c1_stage_gate.csv", [stage_gate])
        return stage_gate

    validation_start = time.perf_counter()
    validation_result = validate_unified_dev_inputs(COMPLETED_INPUT_DIR.resolve())
    input_validation_time = time.perf_counter() - validation_start
    if validation_result["failure_count"] != 0:
        stage_gate = {
            "stage": "S4.4c1",
            "decision": "blocked_modelbuilder_input_contract_mismatch",
            "b5_gate": b5_gate,
            "validator_failure_count": validation_result["failure_count"],
            "caveat": "Completed inputs failed validation before modelbuilder execution.",
        }
        _write_json(S44C1_DIR / "s4_4c1_stage_gate.json", stage_gate)
        _write_csv(S44C1_DIR / "s4_4c1_stage_gate.csv", [stage_gate])
        return stage_gate

    try:
        report = run_s44c_unified_physical_regression(
            input_dir=COMPLETED_INPUT_DIR.resolve(),
            run_id="s4_4c1_24h_static_physical",
            write_report=False,
        )
    except S44CModelBuilderError as exc:
        stage_gate = {
            "stage": "S4.4c1",
            "decision": "blocked_solver_failure",
            "b5_gate": b5_gate,
            "caveat": str(exc),
        }
        _write_json(S44C1_DIR / "s4_4c1_stage_gate.json", stage_gate)
        _write_csv(S44C1_DIR / "s4_4c1_stage_gate.csv", [stage_gate])
        return stage_gate

    audits = report["configuration_build_audit"]
    hourly_rows = report["hourly_rows"]
    decision = _c1_decision(audits)
    total_runtime = time.perf_counter() - total_start
    stage_gate = {
        "stage": "S4.4c1",
        "decision": decision,
        "b5_gate": b5_gate,
        "may_proceed_to_168h": "false",
        "hourly_da_price_taking_active": "false",
        "product_revenue_active": "false",
        "export_revenue_active": "false",
        "grid_tariff_objective_active": "false",
        "direct_wag_market_valuation_active": "false",
        "co2_ets_objective_active": "false",
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": "S4.4c1 is a 24h static physical development regression only.",
    }
    full_report = {
        **report,
        "stage": "S4.4c1",
        "s4_4c1_stage_gate": stage_gate,
        "input_validation_time_seconds": round(input_validation_time, 6),
        "total_runtime_seconds": round(total_runtime, 6),
    }

    _write_json(S44C1_DIR / "s4_4c1_static_physical_report.json", full_report)
    _write_csv(S44C1_DIR / "s4_4c1_static_physical_report.csv", _report_rows(audits))
    _write_csv(S44C1_DIR / "s4_4c1_run_metrics.csv", _run_metric_rows(audits))
    c0_rows = [row for row in hourly_rows if row["configuration_id"] == "C0_current_BF_BOF_reference"]
    c1_rows = [row for row in hourly_rows if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"]
    if any(row.get("build_status") == "solved" for row in c0_rows):
        _write_csv(S44C1_DIR / "s4_4c1_hourly_dispatch_c0.csv", c0_rows)
    if any(row.get("build_status") == "solved" for row in c1_rows):
        _write_csv(S44C1_DIR / "s4_4c1_hourly_dispatch_c1.csv", c1_rows)
    infeasibility = _infeasibility_rows(audits)
    if infeasibility:
        _write_csv(S44C1_DIR / "s4_4c1_infeasibility_diagnostics.csv", infeasibility)
    _write_json(S44C1_DIR / "s4_4c1_stage_gate.json", stage_gate)
    _write_csv(S44C1_DIR / "s4_4c1_stage_gate.csv", [stage_gate])

    analytics = _analytics_rows(
        audits,
        input_validation_time=input_validation_time,
        total_runtime=total_runtime,
        output_file_count=0,
        output_folder_size_bytes=0,
    )
    output_start = time.perf_counter()
    _write_csv(S44C1_DIR / "s4_4c1_computational_analytics.csv", analytics)
    output_runtime = time.perf_counter() - output_start
    file_count, folder_size = _folder_stats(S44C1_DIR)
    for row in analytics:
        row["reporting_output_time_seconds"] = round(output_runtime, 6)
        row["output_file_count"] = file_count
        row["output_folder_size_bytes"] = folder_size
    _write_csv(S44C1_DIR / "s4_4c1_computational_analytics.csv", analytics)
    return full_report


def main() -> None:
    report = run_s4_4c1_static_physical_regression()
    print(json.dumps({
        "decision": report.get("s4_4c1_stage_gate", report).get("decision"),
        "b5_gate": report.get("s4_4c1_stage_gate", report).get("b5_gate"),
        "configuration_statuses": {
            row["configuration_id"]: row["build_status"]
            for row in report.get("configuration_build_audit", [])
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
