"""Asymmetric S4.4c1a/S4.4c2 static physical regression runners."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5a_asymmetric_correction import B5A_DIR, CORRECTED_INPUT_DIR
from .s4_4c_unified_physical_modelbuilder import (
    S44CModelBuilderError,
    run_s44c_unified_physical_regression,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C1A_DIR = S4_ROOT / "s4_4c1a_asymmetric_24h_static_physical_regression"
C2_DIR = S4_ROOT / "s4_4c2_asymmetric_168h_static_physical_regression"
C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _folder_stats(path: Path) -> tuple[int, int]:
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    return len(files), sum(candidate.stat().st_size for candidate in files)


def _gate(path: Path, key: str = "decision") -> str:
    if not path.exists():
        return "missing"
    return json.loads(path.read_text(encoding="utf-8")).get(key, "missing")


def _status_map(audits: list[dict[str, Any]]) -> dict[str, str]:
    return {row["configuration_id"]: row["build_status"] for row in audits}


def _zero_residual(audit: dict[str, Any]) -> bool:
    try:
        return abs(float(audit.get("final_product_residual_t", 1))) <= 1e-6
    except (TypeError, ValueError):
        return False


def _phase3_gate(audits: list[dict[str, Any]]) -> str:
    statuses = _status_map(audits)
    by_config = {row["configuration_id"]: row for row in audits}
    c0_ok = statuses.get(C0) == "solved" and _zero_residual(by_config[C0])
    c1_ok = statuses.get(C1) == "solved" and _zero_residual(by_config[C1])
    if c0_ok and c1_ok:
        return "pass_to_phase4_week_run"
    if c1_ok and not c0_ok:
        return "pass_24h_c1_only_c0_blocked"
    if any(status == "solver_failed" for status in statuses.values()):
        return "blocked_solver_failure"
    return "blocked_24h_both_configs"


def _phase4_gate(audits: list[dict[str, Any]]) -> str:
    statuses = _status_map(audits)
    by_config = {row["configuration_id"]: row for row in audits}
    c0_ok = statuses.get(C0) == "solved" and _zero_residual(by_config[C0])
    c1_ok = statuses.get(C1) == "solved" and _zero_residual(by_config[C1])
    if c0_ok and c1_ok:
        return "pass_168h_static_physical_both_configs"
    if c1_ok and not c0_ok:
        return "pass_168h_c1_only_c0_blocked"
    if any(status == "solver_failed" for status in statuses.values()):
        return "blocked_168h_solver_failure"
    return "blocked_168h_both_configs"


def _report_rows(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration_id": row["configuration_id"],
            "build_status": row["build_status"],
            "solver_name": row.get("solver_name", ""),
            "solver_status": row.get("solver_status", ""),
            "termination_condition": row.get("termination_condition", ""),
            "objective_value": row.get("objective_value", ""),
            "final_product_target_t": row.get("final_product_target_t", ""),
            "final_product_fulfilled_t": row.get("final_product_fulfilled_t", ""),
            "final_product_residual_t": row.get("final_product_residual_t", ""),
            "variable_count": row.get("variable_count", ""),
            "binary_count": row.get("binary_count", ""),
            "constraint_count": row.get("constraint_count", ""),
            "caveat": row.get("caveat", ""),
        }
        for row in audits
    ]


def _run_metrics(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "configuration_id",
        "build_status",
        "final_product_target_t",
        "final_product_fulfilled_t",
        "final_product_residual_t",
        "electricity_mwh",
        "natural_gas_nm3",
        "oxygen_t",
        "WAG_generated",
        "WAG_used",
        "WAG_flared",
        "dri_terminal_residual_t",
        "coke_terminal_residual_t",
        "sinter_terminal_residual_t",
        "hot_iron_terminal_residual_t",
        "cold_slab_terminal_residual_t",
        "caveat",
    ]
    return [{field: row.get(field, "") for field in fields} for row in audits]


def _analytics(
    audits: list[dict[str, Any]],
    *,
    input_validation_time: float,
    total_runtime: float,
    output_file_count: int,
    output_folder_size_bytes: int,
    reporting_time: float,
    scaling: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for audit in audits:
        variable_count = int(audit.get("variable_count") or 0)
        binary_count = int(audit.get("binary_count") or 0)
        config_id = audit["configuration_id"]
        rows.append(
            {
                "configuration_id": config_id,
                "input_validation_time_seconds": round(input_validation_time, 6),
                "model_build_time_seconds": audit.get("build_runtime_seconds", ""),
                "solve_time_seconds": audit.get("runtime_seconds", ""),
                "reporting_output_time_seconds": round(reporting_time, 6),
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
                "runtime_scaling_ratio_vs_24h": "" if scaling is None else scaling.get(config_id, ""),
                "caveat": "Unavailable solver internals are left blank.",
            }
        )
    return rows


def _infeasibility(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration_id": row["configuration_id"],
            "build_status": row["build_status"],
            "solver_status": row.get("solver_status", ""),
            "termination_condition": row.get("termination_condition", ""),
            "caveat": row.get("caveat", ""),
        }
        for row in audits
        if row.get("build_status") != "solved"
    ]


def _daily_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for day in range(7):
            chunk = rows[day * 24 : (day + 1) * 24]
            if not chunk:
                continue
            production = [float(row.get("final_product_output_t") or 0.0) for row in chunk]
            out.append(
                {
                    "configuration_id": config_id,
                    "day_index": day,
                    "production_t": round(sum(production), 6),
                    "min_hourly_production_t": round(min(production), 6),
                    "max_hourly_production_t": round(max(production), 6),
                    "mean_hourly_production_t": round(sum(production) / len(production), 6),
                }
            )
    return out


def _inventory_summary(hourly_rows: list[dict[str, Any]], audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    inventory_fields = {
        C0: ["coke_inventory_t", "sinter_inventory_t", "hot_iron_inventory_t", "cold_slab_inventory_t"],
        C1: ["DRI_inventory_t"],
    }
    capacities = {
        "coke_inventory_t": 720.0,
        "sinter_inventory_t": 640.0,
        "hot_iron_inventory_t": 500.0,
        "cold_slab_inventory_t": 25000.0,
        "DRI_inventory_t": 17760.0,
    }
    for config_id, fields in inventory_fields.items():
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        audit = next((row for row in audits if row["configuration_id"] == config_id), {})
        for field in fields:
            values = [float(row.get(field) or 0.0) for row in config_rows if row.get(field) not in {"", None}]
            if not values:
                continue
            cap = capacities[field]
            rows.append(
                {
                    "configuration_id": config_id,
                    "inventory": field,
                    "min_t": round(min(values), 6),
                    "max_t": round(max(values), 6),
                    "terminal_t": round(values[-1], 6),
                    "hit_zero_hours": sum(1 for value in values if abs(value) <= 1e-6),
                    "hit_capacity_hours": sum(1 for value in values if abs(value - cap) <= 1e-6),
                    "terminal_residual_t": audit.get(field.replace("_inventory_t", "_terminal_residual_t"), ""),
                }
            )
    return rows


def _wag_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        generated = sum(float(row.get("WAG_generated") or 0.0) for row in rows)
        used = sum(float(row.get("WAG_used") or 0.0) for row in rows)
        flared = sum(float(row.get("WAG_flared") or 0.0) for row in rows)
        out.append(
            {
                "configuration_id": config_id,
                "WAG_generated": round(generated, 6),
                "WAG_used": round(used, 6),
                "WAG_flared": round(flared, 6),
                "BFG_COG_BOFG_separate": "true",
                "direct_WAG_market_valuation_active": "false",
                "caveat": "Carrier-level WAG split is governed in inputs; current C0 runner reports aggregate generated/flared proxy only.",
            }
        )
    return out


def _phase_run(
    *,
    output_dir: Path,
    prefix: str,
    report_prefix: str | None = None,
    run_id: str,
    phase_gate: str,
    required_gate_path: Path,
    required_gate_value: str,
    blocked_gate_decision: str,
    horizon_hours_override: int | None,
    target_multiplier: float,
    week_outputs: bool,
    scaling_reference_path: Path | None = None,
) -> dict[str, Any]:
    total_start = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_gate = _gate(required_gate_path)
    if prior_gate != required_gate_value:
        gate = {
            "stage": phase_gate,
            "decision": blocked_gate_decision,
            "prior_gate": prior_gate,
            "caveat": "Required prior gate did not pass; run not executed.",
        }
        _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
        _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])
        return gate

    validation_start = time.perf_counter()
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    input_validation_time = time.perf_counter() - validation_start
    if validation["failure_count"] != 0:
        gate = {
            "stage": phase_gate,
            "decision": "blocked_modelbuilder_input_contract_mismatch",
            "validator_failure_count": validation["failure_count"],
            "caveat": "Corrected inputs failed validator before regression.",
        }
        _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
        _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])
        return gate

    try:
        report = run_s44c_unified_physical_regression(
            input_dir=CORRECTED_INPUT_DIR.resolve(),
            run_id=run_id,
            write_report=False,
            horizon_hours_override=horizon_hours_override,
            target_multiplier=target_multiplier,
            fix_c0_binary_schedule=True,
        )
    except S44CModelBuilderError as exc:
        gate = {
            "stage": phase_gate,
            "decision": "blocked_solver_failure",
            "caveat": str(exc),
        }
        _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
        _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])
        return gate

    audits = report["configuration_build_audit"]
    hourly_rows = report["hourly_rows"]
    decision = _phase4_gate(audits) if week_outputs else _phase3_gate(audits)
    if week_outputs and decision == "pass_168h_static_physical_both_configs":
        # Conservative inventory-borrowing check: all terminal residuals reported by solved audits must be zero.
        for audit in audits:
            residuals = [
                value
                for key, value in audit.items()
                if key.endswith("_terminal_residual_t") and value not in {"", None}
            ]
            if any(abs(float(value)) > 1e-6 for value in residuals):
                decision = "blocked_168h_fake_flexibility_or_inventory_borrowing"
    total_runtime = time.perf_counter() - total_start
    gate = {
        "stage": phase_gate,
        "decision": decision,
        "horizon_hours": horizon_hours_override or 24,
        "target_multiplier": target_multiplier,
        "hourly_da_price_taking_active": "false",
        "product_revenue_active": "false",
        "export_revenue_active": "false",
        "grid_tariff_objective_active": "false",
        "direct_wag_market_valuation_active": "false",
        "co2_ets_objective_active": "false",
        "c0_fixed_binary_schedule_used": "true",
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": "Static physical development regression only; C0 binary on/off slots fixed to deterministic daily blocks without slack.",
    }
    full_report = {
        **report,
        "stage": phase_gate,
        "phase_stage_gate": gate,
        "input_validation_time_seconds": round(input_validation_time, 6),
        "total_runtime_seconds": round(total_runtime, 6),
    }
    report_stem = report_prefix or prefix
    _write_json(output_dir / f"{report_stem}_static_physical_report.json", full_report)
    _write_csv(output_dir / f"{report_stem}_static_physical_report.csv", _report_rows(audits))
    _write_csv(output_dir / f"{prefix}_run_metrics.csv", _run_metrics(audits))
    c0_rows = [row for row in hourly_rows if row["configuration_id"] == C0]
    c1_rows = [row for row in hourly_rows if row["configuration_id"] == C1]
    if any(row.get("build_status") == "solved" for row in c0_rows):
        _write_csv(output_dir / f"{prefix}_hourly_dispatch_c0.csv", c0_rows)
    if any(row.get("build_status") == "solved" for row in c1_rows):
        _write_csv(output_dir / f"{prefix}_hourly_dispatch_c1.csv", c1_rows)
    infeasibility = _infeasibility(audits)
    if infeasibility:
        _write_csv(output_dir / f"{prefix}_infeasibility_diagnostics.csv", infeasibility)
    if week_outputs:
        _write_csv(output_dir / f"{prefix}_daily_summary.csv", _daily_summary(hourly_rows))
        _write_csv(output_dir / f"{prefix}_inventory_summary.csv", _inventory_summary(hourly_rows, audits))
        _write_csv(output_dir / f"{prefix}_wag_summary.csv", _wag_summary(hourly_rows))
    _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
    _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])

    scaling: dict[str, float] | None = None
    if scaling_reference_path and scaling_reference_path.exists():
        ref_rows = _read_csv(scaling_reference_path)
        ref = {row["configuration_id"]: float(row["solve_time_seconds"]) for row in ref_rows if row.get("solve_time_seconds")}
        scaling = {}
        for audit in audits:
            solve_time = float(audit.get("runtime_seconds") or 0.0)
            base = ref.get(audit["configuration_id"], 0.0)
            scaling[audit["configuration_id"]] = round(solve_time / base, 6) if base else ""
    reporting_start = time.perf_counter()
    file_count, folder_size = _folder_stats(output_dir)
    analytics = _analytics(
        audits,
        input_validation_time=input_validation_time,
        total_runtime=total_runtime,
        output_file_count=file_count + 1,
        output_folder_size_bytes=folder_size,
        reporting_time=0.0,
        scaling=scaling,
    )
    _write_csv(output_dir / f"{prefix}_computational_analytics.csv", analytics)
    reporting_time = time.perf_counter() - reporting_start
    file_count, folder_size = _folder_stats(output_dir)
    analytics = _analytics(
        audits,
        input_validation_time=input_validation_time,
        total_runtime=total_runtime,
        output_file_count=file_count,
        output_folder_size_bytes=folder_size,
        reporting_time=reporting_time,
        scaling=scaling,
    )
    _write_csv(output_dir / f"{prefix}_computational_analytics.csv", analytics)
    return full_report


def run_c1a_24h() -> dict[str, Any]:
    return _phase_run(
        output_dir=C1A_DIR,
        prefix="s4_4c1a",
        report_prefix=None,
        run_id="s4_4c1a_asymmetric_24h_static",
        phase_gate="S4.4c1a",
        required_gate_path=B5A_DIR / "s4_4b5a_phase2_validation_gate.json",
        required_gate_value="pass_to_phase3_24h_rerun",
        blocked_gate_decision="blocked_modelbuilder_input_contract_mismatch",
        horizon_hours_override=None,
        target_multiplier=1.0,
        week_outputs=False,
    )


def run_c2_168h() -> dict[str, Any]:
    return _phase_run(
        output_dir=C2_DIR,
        prefix="s4_4c2",
        report_prefix="s4_4c2_168h",
        run_id="s4_4c2_asymmetric_168h_static",
        phase_gate="S4.4c2",
        required_gate_path=C1A_DIR / "s4_4c1a_stage_gate.json",
        required_gate_value="pass_to_phase4_week_run",
        blocked_gate_decision="blocked_168h_both_configs",
        horizon_hours_override=168,
        target_multiplier=7.0,
        week_outputs=True,
        scaling_reference_path=C1A_DIR / "s4_4c1a_computational_analytics.csv",
    )
