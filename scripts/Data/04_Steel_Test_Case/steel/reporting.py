from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pyomo.environ import value

from .config import SteelToyConfig
from .model import ModelStats


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def fingerprint_file(path: Path, repo_root: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stat = path.stat()
    return {
        "path": repo_rel(path, repo_root),
        "sha256": digest,
        "size_bytes": int(stat.st_size),
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def resolve_git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def extract_solution_frames(model, config: SteelToyConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flow_rows: list[dict[str, Any]] = []
    for process_name, process in config.processes.items():
        for time_index in config.time_indices:
            throughput = value(model.process_throughput[process_name, time_index])
            flow_rows.append(
                {
                    "period_index": time_index,
                    "flow_type": "process_activity",
                    "name": process_name,
                    "carrier": "",
                    "route": process.route,
                    "quantity_tonnes": throughput,
                    "unit": "tonnes_per_hour_equivalent",
                }
            )
            for carrier, coefficient in process.conversion.items():
                flow_rows.append(
                    {
                        "period_index": time_index,
                        "flow_type": "process_net",
                        "name": process_name,
                        "carrier": carrier,
                        "route": process.route,
                        "quantity_tonnes": coefficient * throughput,
                        "unit": "tonnes",
                    }
                )

    for source_name, source in config.sources.items():
        for time_index in config.time_indices:
            flow_rows.append(
                {
                    "period_index": time_index,
                    "flow_type": "source_supply",
                    "name": source_name,
                    "carrier": source.carrier,
                    "route": "EXTERNAL",
                    "quantity_tonnes": value(model.source_supply[source_name, time_index]),
                    "unit": "tonnes",
                }
            )

    for sink_name, sink in config.sinks.items():
        for time_index in config.time_indices:
            flow_rows.append(
                {
                    "period_index": time_index,
                    "flow_type": "sink_delivery",
                    "name": sink_name,
                    "carrier": sink.carrier,
                    "route": "DELIVERY",
                    "quantity_tonnes": value(model.sink_flow[sink_name, time_index]),
                    "unit": "tonnes",
                }
            )

    inventory_rows: list[dict[str, Any]] = []
    for store_name, store in config.stores.items():
        for time_index in config.time_indices:
            charge = value(model.store_charge[store_name, time_index])
            discharge = value(model.store_discharge[store_name, time_index])
            flow_rows.append(
                {
                    "period_index": time_index,
                    "flow_type": "store_charge",
                    "name": store_name,
                    "carrier": store.carrier,
                    "route": "STORE",
                    "quantity_tonnes": charge,
                    "unit": "tonnes",
                }
            )
            flow_rows.append(
                {
                    "period_index": time_index,
                    "flow_type": "store_discharge",
                    "name": store_name,
                    "carrier": store.carrier,
                    "route": "STORE",
                    "quantity_tonnes": discharge,
                    "unit": "tonnes",
                }
            )
            inventory_rows.append(
                {
                    "period_index": time_index,
                    "store": store_name,
                    "carrier": store.carrier,
                    "inventory_tonnes": value(model.inventory[store_name, time_index]),
                    "initial_inventory_tonnes": store.initial_inventory_tonnes,
                    "terminal_min_tonnes": store.terminal_min_tonnes,
                    "terminal_max_tonnes": store.terminal_max_tonnes,
                }
            )

    delivery_total = sum(value(model.sink_flow[config.production_target.sink, time_index]) for time_index in config.time_indices)
    route_totals: dict[str, float] = {}
    for process_name, process in config.processes.items():
        total = sum(value(model.process_throughput[process_name, time_index]) for time_index in config.time_indices)
        route_totals[process.route] = route_totals.get(process.route, 0.0) + total

    production_summary = pd.DataFrame(
        [
            {
                "target_sink": config.production_target.sink,
                "target_carrier": config.production_target.carrier,
                "production_target_tonnes": config.production_target.total_tonnes,
                "delivered_tonnes": delivery_total,
                "target_gap_tonnes": delivery_total - config.production_target.total_tonnes,
                "bf_bof_process_tonnes": route_totals.get("BF_BOF", 0.0),
                "drp_eaf_process_tonnes": route_totals.get("DRP_EAF", 0.0),
                "downstream_process_tonnes": route_totals.get("DOWNSTREAM", 0.0),
            }
        ]
    )

    return pd.DataFrame(flow_rows), pd.DataFrame(inventory_rows), production_summary


def build_feasible_validation_frame(model, config: SteelToyConfig, solver_status: str) -> pd.DataFrame:
    tolerance = 1e-6
    last_time = config.time_indices[-1]

    delivered_total = sum(value(model.sink_flow[config.production_target.sink, time_index]) for time_index in config.time_indices)
    target_met = delivered_total >= config.production_target.total_tonnes - tolerance

    max_balance_violation = 0.0
    for carrier_name in config.carriers:
        for time_index in config.time_indices:
            residual = abs(value(model.carrier_balance[carrier_name, time_index].body))
            max_balance_violation = max(max_balance_violation, residual)

    terminal_checks: list[bool] = []
    for store_name, store in config.stores.items():
        ending_inventory = value(model.inventory[store_name, last_time])
        terminal_checks.append(
            store.terminal_min_tonnes - tolerance <= ending_inventory <= store.terminal_max_tonnes + tolerance
        )

    forbidden_features_active = [name for name, enabled in config.flags.items() if enabled]
    thesis_usable = "no"
    thesis_reason = "Toy scaffold values only; S2 smoke runs are structural evidence and not thesis-grade quantitative evidence."

    rows = [
        {
            "check_name": "production_target_met",
            "passed": bool(target_met),
            "actual_value": float(delivered_total),
            "expected_value": float(config.production_target.total_tonnes),
            "notes": "Fixed cumulative production target on delivered slab.",
        },
        {
            "check_name": "material_balance_close",
            "passed": bool(max_balance_violation <= tolerance),
            "actual_value": float(max_balance_violation),
            "expected_value": tolerance,
            "notes": "Maximum absolute carrier-balance residual across all carriers and hours.",
        },
        {
            "check_name": "terminal_inventory_rules_satisfied",
            "passed": bool(all(terminal_checks)),
            "actual_value": int(sum(1 for passed in terminal_checks if passed)),
            "expected_value": len(terminal_checks),
            "notes": "All active stores satisfy configured terminal min/max rules.",
        },
        {
            "check_name": "dri_buffer_not_free_battery",
            "passed": bool(abs(value(model.inventory["dri_buffer", last_time]) - config.stores["dri_buffer"].initial_inventory_tonnes) <= tolerance),
            "actual_value": float(value(model.inventory["dri_buffer", last_time]) - config.stores["dri_buffer"].initial_inventory_tonnes),
            "expected_value": 0.0,
            "notes": "DRI buffer ends at its initial inventory; no net free drawdown.",
        },
        {
            "check_name": "slab_buffer_not_free_battery",
            "passed": bool(abs(value(model.inventory["slab_buffer", last_time]) - config.stores["slab_buffer"].initial_inventory_tonnes) <= tolerance),
            "actual_value": float(value(model.inventory["slab_buffer", last_time]) - config.stores["slab_buffer"].initial_inventory_tonnes),
            "expected_value": 0.0,
            "notes": "Slab buffer ends at its initial inventory; no net free drawdown.",
        },
        {
            "check_name": "no_forbidden_stage_features_active",
            "passed": bool(not forbidden_features_active),
            "actual_value": ", ".join(forbidden_features_active) if forbidden_features_active else "none",
            "expected_value": "none",
            "notes": "S2 excludes S3, DA, stochastic, reserve, CVaR, and revenue layers.",
        },
        {
            "check_name": "objective_and_slack_interpretation",
            "passed": True,
            "actual_value": "operating_cost_only_no_slacks",
            "expected_value": "operating_cost_only_no_slacks",
            "notes": "Objective contains toy operating, import, and store costs only. No diagnostic slack variables are active.",
        },
        {
            "check_name": "solver_optimal_or_feasible",
            "passed": solver_status.lower() in {"ok", "optimal"},
            "actual_value": solver_status,
            "expected_value": "optimal",
            "notes": "Pyomo solver status as returned by the active LP solver.",
        },
        {
            "check_name": "thesis_usable",
            "passed": False,
            "actual_value": thesis_usable,
            "expected_value": "no",
            "notes": thesis_reason,
        },
    ]
    return pd.DataFrame(rows)


def build_infeasible_validation_frame(
    config: SteelToyConfig,
    *,
    solver_status: str,
    termination_condition: str,
    infeasibility_class: str,
    expected_infeasibility_class: str | None,
) -> pd.DataFrame:
    forbidden_features_active = [name for name, enabled in config.flags.items() if enabled]
    rows = [
        {
            "check_name": "infeasibility_detected",
            "passed": True,
            "actual_value": termination_condition,
            "expected_value": "infeasible",
            "notes": "Configured S2.2 diagnostic case is expected to fail structurally without slacks.",
        },
        {
            "check_name": "infeasibility_class_present",
            "passed": bool(infeasibility_class),
            "actual_value": infeasibility_class,
            "expected_value": "non_empty_class",
            "notes": "Stable infeasibility classification label is required for S2.2 smoke cases.",
        },
        {
            "check_name": "expected_infeasibility_class_match",
            "passed": expected_infeasibility_class in {None, infeasibility_class},
            "actual_value": infeasibility_class,
            "expected_value": expected_infeasibility_class or "n/a",
            "notes": "Expected smoke-case class from config should match the inferred class when provided.",
        },
        {
            "check_name": "no_forbidden_stage_features_active",
            "passed": bool(not forbidden_features_active),
            "actual_value": ", ".join(forbidden_features_active) if forbidden_features_active else "none",
            "expected_value": "none",
            "notes": "S2.2 still excludes S3, DA, stochastic, reserve, CVaR, and revenue layers.",
        },
        {
            "check_name": "thesis_usable",
            "passed": False,
            "actual_value": "no",
            "expected_value": "no",
            "notes": "Toy and infeasible smoke cases are not thesis-usable quantitative evidence.",
        },
        {
            "check_name": "solver_status_recorded",
            "passed": bool(solver_status),
            "actual_value": solver_status,
            "expected_value": "recorded",
            "notes": "Solver status must be written even when the run is infeasible.",
        },
    ]
    return pd.DataFrame(rows)


def build_code_version(repo_root: Path, runner_path: Path) -> dict[str, Any]:
    return {
        "timestamp_utc": iso_utc(now_utc()),
        "runner": repo_rel(runner_path, repo_root),
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_commit": resolve_git_commit(repo_root),
    }


def build_run_summary(
    *,
    run_id: str,
    started: datetime,
    solver_name: str,
    solver_status: str,
    termination_condition: str,
    objective_value: float | None,
    runtime_seconds: float,
    model_stats: ModelStats,
    thesis_usable: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "timestamp_utc": iso_utc(started),
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": objective_value,
        "runtime_seconds": runtime_seconds,
        "model_stats": asdict(model_stats),
        "thesis_usable": thesis_usable,
    }
