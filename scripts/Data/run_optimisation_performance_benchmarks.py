"""Governed legacy-versus-optimized performance fixtures for hydrogen and steel.

The fixtures use frozen inputs and short consecutive support. They are
diagnostic performance evidence, never model selection or thesis evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
HYDROGEN_ROOT = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case"
STEEL_ROOT = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case"
for path in (REPO_ROOT, HYDROGEN_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hydrogen.horizon_granularity_comparison import (  # noqa: E402
    load_comparison_config,
    resolved_hydrogen_config,
    run_rolling_policy,
    validate_support_contract,
)
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402
from run_strict_lear_horizon_granularity_comparison import _resolve_scenario_set  # noqa: E402
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (  # noqa: E402
    run_closed_loop_feasibility_anchor_reconciliation,
)


HYDROGEN_CASES = (
    ("H-D", 30),
    ("H-D4", 30),
    ("QH-D4", 30),
    ("QH-D4", 10),
)
PARITY_FIELDS = (
    "realised_adjusted_profit_ex_terminal_eur",
    "da_cost_eur",
    "hydrogen_produced_kg",
    "hydrogen_compressed_kg",
    "shortfall_kg",
    "emergency_import_mwh",
    "storage_end_kg",
    "electrolyser_power_end_mw",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hydrogen-config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/strict_lear_horizon_granularity_comparison.yaml",
    )
    parser.add_argument(
        "--steel-config",
        default="scripts/Data/04_Steel_Test_Case/configs/steel_hourly_da_dplus4_point_forecast_integration.yaml",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--hydrogen-days", type=int, default=3)
    parser.add_argument("--steel-replans", type=int, default=2)
    parser.add_argument("--skip-hydrogen", action="store_true")
    parser.add_argument("--skip-steel", action="store_true")
    return parser.parse_args()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_common(root: Path, *, run_id: str, inputs: list[Path], summary: dict[str, Any], warnings: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest = [
        {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": _hash(path)}
        for path in inputs if path.exists() and path.is_file()
    ]
    (root / "input_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n" + "\n".join(f"- {warning}" for warning in warnings) + "\n",
        encoding="utf-8",
    )
    (root / "registry_entry.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "output_policy": "audit",
                "run_class": "diagnostic_performance",
                "lineage_role": "non-canonical performance evidence",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _parity_rows(legacy: pd.DataFrame, optimized: pd.DataFrame, *, system: str, case: str) -> list[dict[str, Any]]:
    keys = (
        ["delivery_day"]
        if "delivery_day" in legacy.columns
        else [key for key in ("replan_index", "configuration_id") if key in legacy.columns]
    )
    merged = legacy.merge(optimized, on=keys, suffixes=("_legacy", "_optimized"), validate="one_to_one")
    rows: list[dict[str, Any]] = []
    candidate_fields = PARITY_FIELDS if system == "hydrogen" else (
        "executed_final_product_t", "cumulative_executed_final_product_t",
        "end_coke_inventory_t", "end_sinter_inventory_t", "end_hot_iron_inventory_t",
        "end_cold_slab_inventory_t", "end_dri_inventory_t", "gross_electricity_mwh",
        "net_grid_import_mwh", "represented_ng_nm3", "wag_generated_mwh",
        "wag_used_mwh", "wag_flared_mwh", "max_abs_material_balance_residual_t",
    )
    fields = [field for field in candidate_fields if f"{field}_legacy" in merged.columns]
    for record in merged.to_dict(orient="records"):
        for field in fields:
            left = float(record[f"{field}_legacy"])
            right = float(record[f"{field}_optimized"])
            tolerance = max(0.01 if "eur" in field or "cost" in field else 1e-5, 1e-6 * max(abs(left), abs(right)))
            rows.append(
                {
                    "system": system, "configuration": case,
                    **{key: record[key] for key in keys}, "field": field,
                    "legacy_value": left, "optimized_value": right,
                    "difference": right - left, "tolerance": tolerance,
                    "passed": abs(right - left) <= tolerance,
                }
            )
    return rows


def _solver_parity_rows(legacy: pd.DataFrame, optimized: pd.DataFrame, *, case: str) -> list[dict[str, Any]]:
    merged = legacy.merge(
        optimized, on=["delivery_day", "stage"], suffixes=("_legacy", "_optimized"),
        validate="one_to_one",
    )
    rows: list[dict[str, Any]] = []
    for record in merged.to_dict(orient="records"):
        left = float(record["objective_value_legacy"])
        right = float(record["objective_value_optimized"])
        tolerance = max(0.01, 1e-6 * max(abs(left), abs(right)))
        rows.append(
            {
                "system": "hydrogen", "configuration": case,
                "delivery_day": record["delivery_day"], "field": f"{record['stage']}_objective_value",
                "legacy_value": left, "optimized_value": right, "difference": right - left,
                "tolerance": tolerance,
                "passed": bool(
                    abs(right - left) <= tolerance
                    and str(record["solver_status_legacy"]) == str(record["solver_status_optimized"])
                    and str(record["termination_condition_legacy"]) == str(record["termination_condition_optimized"])
                ),
            }
        )
    return rows


def _runtime_summary(runtime: pd.DataFrame) -> pd.DataFrame:
    if runtime.empty:
        return pd.DataFrame()
    grouped = runtime.groupby(
        ["system", "configuration", "scenario_count", "stage", "performance_mode"],
        dropna=False,
    )["runtime_seconds"].agg(
        total_seconds="sum", median_seconds="median", p95_seconds=lambda values: float(np.quantile(values, 0.95)),
        origin_count="count",
    ).reset_index()
    pivot = grouped.pivot_table(
        index=["system", "configuration", "scenario_count", "stage"],
        columns="performance_mode", values="median_seconds", aggfunc="first",
    ).reset_index()
    if {"legacy_rebuild", "optimized_equivalent"}.issubset(pivot.columns):
        pivot["median_speedup"] = pivot["legacy_rebuild"] / pivot["optimized_equivalent"]
    return grouped.merge(
        pivot[["system", "configuration", "scenario_count", "stage", "median_speedup"]]
        if "median_speedup" in pivot else pivot.iloc[:, :4],
        on=["system", "configuration", "scenario_count", "stage"], how="left",
    )


def _speed_acceptance(summary: pd.DataFrame, *, system: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in summary.loc[summary["performance_mode"].eq("optimized_equivalent")].to_dict(orient="records"):
        if system == "hydrogen" and record["stage"] != "bidding":
            continue
        if system == "hydrogen":
            target = (
                2.0 if record["configuration"] == "QH-D4" and int(record["scenario_count"]) == 30
                else 1.5 if record["configuration"] == "QH-D4" and int(record["scenario_count"]) == 10
                else 1.0 / 1.10
            )
        else:
            target = 1.0 / 1.10
        speedup = float(record.get("median_speedup", np.nan))
        rows.append(
            {
                "system": system, "configuration": record["configuration"],
                "scenario_count": record["scenario_count"], "stage": record["stage"],
                "measured_median_speedup": speedup, "required_minimum_speedup": target,
                "passed": bool(np.isfinite(speedup) and speedup + 1e-12 >= target),
            }
        )
    return pd.DataFrame(rows)


def _run_hydrogen(run_id: str, config_path: Path, day_count: int) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    config, repo_root = load_comparison_config(config_path)
    forecast_root = (repo_root / config["forecast_run_root"]).resolve()
    _, support = validate_support_contract(forecast_root=forecast_root, comparison_config=config)
    days = list(support["episodes"]["primary"])[: int(day_count)]
    if len(days) != day_count:
        raise ValueError("Hydrogen performance fixture support is shorter than requested.")
    base = load_hydrogen_config((repo_root / config["base_hydrogen_config"]).resolve())
    output_root = repo_root / "data" / "03_Hydrogen_Test_Case" / "performance_benchmarks" / run_id
    output_root.mkdir(parents=True, exist_ok=False)
    cache_root = repo_root / "tmp" / "hydrogen_performance_cache"
    runtime_frames: list[pd.DataFrame] = []
    parity: list[dict[str, Any]] = []
    daily_by_case_mode: dict[tuple[str, int, str], pd.DataFrame] = {}
    solver_by_case_mode: dict[tuple[str, int, str], pd.DataFrame] = {}
    input_files = [config_path, forecast_root / "evaluation_actuals.parquet"]
    for configuration, scenario_count in HYDROGEN_CASES:
        spec = config["configurations"][configuration]
        granularity = str(spec["granularity"])
        horizon_mode = "D_only" if spec["horizon_lead_days"] == [0] else "D_to_Dplus4"
        hydrogen_config = resolved_hydrogen_config(
            base, granularity=granularity, horizon_mode=horizon_mode, comparison_config=config
        )
        scenario_30, actuals, _ = _resolve_scenario_set(
            hydrogen_config=hydrogen_config, artifact_id=spec["artifact_ids"][30],
            lead_days=spec["horizon_lead_days"], cache_root=cache_root,
        )
        scenario_10, _, _ = _resolve_scenario_set(
            hydrogen_config=hydrogen_config, artifact_id=spec["artifact_ids"][10],
            lead_days=spec["horizon_lead_days"], cache_root=cache_root,
        )
        input_files.extend(
            forecast_root / relative for relative in spec["scenario_files"].values()
        )
        policy = f"stochastic_{scenario_count}"
        for mode in ("legacy_rebuild", "optimized_equivalent"):
            fixture_config = {
                **config,
                "performance": {
                    **dict(config.get("performance", {})),
                    "performance_mode": mode,
                    "output_extraction": "full_audit" if mode == "legacy_rebuild" else "executed_day_only",
                },
            }
            daily, _, solver, _ = run_rolling_policy(
                config_id=configuration, policy=policy, episode_id="performance_fixture",
                episode_days=days, scenario_30=scenario_30, scenario_10=scenario_10,
                actuals=actuals, hydrogen_config=hydrogen_config,
                comparison_config=fixture_config, run_id=f"{run_id}_{configuration}_{scenario_count}_{mode}",
            )
            solver = solver.copy()
            solver["system"] = "hydrogen"
            solver["configuration"] = configuration
            solver["scenario_count"] = scenario_count
            runtime_frames.append(solver)
            daily_by_case_mode[(configuration, scenario_count, mode)] = daily
            solver_by_case_mode[(configuration, scenario_count, mode)] = solver
        parity.extend(
            _parity_rows(
                daily_by_case_mode[(configuration, scenario_count, "legacy_rebuild")],
                daily_by_case_mode[(configuration, scenario_count, "optimized_equivalent")],
                system="hydrogen", case=f"{configuration}_{scenario_count}",
            )
        )
        parity.extend(
            _solver_parity_rows(
                solver_by_case_mode[(configuration, scenario_count, "legacy_rebuild")],
                solver_by_case_mode[(configuration, scenario_count, "optimized_equivalent")],
                case=f"{configuration}_{scenario_count}",
            )
        )
    runtime = pd.concat(runtime_frames, ignore_index=True)
    parity_frame = pd.DataFrame(parity)
    summary = _runtime_summary(runtime)
    speed_acceptance = _speed_acceptance(summary, system="hydrogen")
    summary.to_csv(output_root / "performance_summary.csv", index=False)
    speed_acceptance.to_csv(output_root / "performance_acceptance.csv", index=False)
    runtime.to_parquet(output_root / "runtime_by_origin.parquet", index=False)
    runtime[[
        "configuration", "scenario_count", "delivery_day", "stage", "performance_mode",
        "variables", "binaries", "constraints", "horizon_steps",
    ]].to_csv(output_root / "model_size_by_origin.csv", index=False)
    runtime[[
        "configuration", "scenario_count", "delivery_day", "stage", "performance_mode",
        "cache_status", "model_reuse_status", "warm_start_status", "warm_start_values_applied",
    ]].to_csv(output_root / "cache_and_warm_start_checks.csv", index=False)
    parity_frame.to_csv(output_root / "legacy_optimized_parity.csv", index=False)
    runtime[[
        "configuration", "scenario_count", "delivery_day", "stage", "performance_mode",
        "input_resolution_seconds", "array_preparation_seconds", "build_time_seconds",
        "solver_time_seconds", "postprocess_time_seconds", "runtime_seconds",
    ]].to_csv(output_root / "bottleneck_breakdown.csv", index=False)
    all_parity = bool(parity_frame["passed"].all()) if not parity_frame.empty else False
    speed_targets_passed = bool(speed_acceptance["passed"].all())
    _write_common(
        output_root, run_id=run_id, inputs=list(dict.fromkeys(input_files)),
        summary={
            "run_id": run_id, "status": (
                "pass" if all_parity and speed_targets_passed
                else "pass_parity_speed_targets_not_met" if all_parity
                else "fail_parity"
            ),
            "output_policy": "audit", "run_class": "diagnostic_performance",
            "lineage_role": "non-canonical performance evidence", "fixture_days": days,
            "parity_passed": all_parity, "speed_targets_passed": speed_targets_passed,
            "speed_target_failure_count": int((~speed_acceptance["passed"]).sum()),
        },
        warnings=[
            "Short consecutive support is a runtime fixture, not a new forecast or economic evaluation.",
            "QH-D4 scenario undercoverage remains unchanged; no calibrated risk-coverage claim is made.",
            "The Pyomo model is still rebuilt; cache hits refer to immutable inputs and structural metadata.",
        ],
    )
    return output_root, runtime, parity_frame


def _run_steel(run_id: str, config_path: Path, replans: int) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    parent = REPO_ROOT / "data" / "03_Optimisation" / "performance_benchmarks" / run_id
    parent.mkdir(parents=True, exist_ok=False)
    frozen_forecast_root = (
        REPO_ROOT.parent
        / "Thesis"
        / "data"
        / "02_Forecasting"
        / "01_DA_prices"
        / "hourly_da"
        / "runs_lago_lear"
        / "20260706_024807_lago_lear_six_year_benchmark"
    ).resolve()
    if not frozen_forecast_root.is_dir():
        raise FileNotFoundError(
            "Frozen deterministic-steel forecast root is unavailable: "
            f"{frozen_forecast_root}"
        )
    results: dict[str, dict[str, Any]] = {}
    runtime_rows: list[dict[str, Any]] = []
    for mode in ("legacy_rebuild", "optimized_equivalent"):
        child_id = f"{run_id}_steel_{mode}"
        started = perf_counter()
        result = run_closed_loop_feasibility_anchor_reconciliation(
            config_path=config_path,
            output_root=parent,
            scenario_overrides={
                "run_id": child_id, "replan_count": int(replans),
                "performance_mode": mode, "output_policy": "audit",
                "run_class": "diagnostic_performance",
                "lineage_role": "non-canonical performance evidence",
                "forecast_run_root": str(frozen_forecast_root),
                "forecast_start_origin_utc": "2023-09-30T06:00:00+00:00",
            },
        )
        results[mode] = result
        metrics = pd.read_csv(Path(result["run_directory"]) / "rolling_model_metrics.csv")
        for record in metrics.to_dict(orient="records"):
            runtime_rows.append(
                {
                    "system": "steel", "configuration": record.get("configuration_id"),
                    "scenario_count": 1, "stage": "deterministic_rolling",
                    "performance_mode": mode, "origin": record.get("replan_index"),
                    "runtime_seconds": float(record.get("runtime_seconds", 0.0)),
                    "build_time_seconds": float(record.get("build_runtime_seconds", 0.0)),
                    "solver_time_seconds": float(record.get("runtime_seconds", 0.0)),
                    "postprocess_time_seconds": 0.0, "input_resolution_seconds": 0.0,
                    "array_preparation_seconds": 0.0, "wall_time_total_run": perf_counter() - started,
                    "variables": record.get("variable_count"), "binaries": record.get("binary_count"),
                    "constraints": record.get("constraint_count"), "horizon_steps": record.get("planning_horizon_hours"),
                    "cache_status": record.get("cache_status"),
                    "model_reuse_status": record.get("model_reuse_status"),
                    "warm_start_status": record.get("warm_start_status"),
                    "warm_start_values_applied": record.get("warm_start_values_applied", 0),
                }
            )
    runtime = pd.DataFrame(runtime_rows)
    legacy_exec = pd.DataFrame(results["legacy_rebuild"]["execution_rows"])
    optimized_exec = pd.DataFrame(results["optimized_equivalent"]["execution_rows"])
    parity = pd.DataFrame(_parity_rows(legacy_exec, optimized_exec, system="steel", case="active_deterministic"))
    performance_summary = _runtime_summary(runtime)
    speed_acceptance = _speed_acceptance(performance_summary, system="steel")
    performance_summary.to_csv(parent / "performance_summary.csv", index=False)
    speed_acceptance.to_csv(parent / "performance_acceptance.csv", index=False)
    runtime.to_parquet(parent / "runtime_by_origin.parquet", index=False)
    runtime.to_csv(parent / "model_size_by_origin.csv", index=False)
    runtime[[
        "configuration", "origin", "performance_mode", "cache_status", "model_reuse_status",
        "warm_start_status", "warm_start_values_applied",
    ]].to_csv(parent / "cache_and_warm_start_checks.csv", index=False)
    parity.to_csv(parent / "legacy_optimized_parity.csv", index=False)
    runtime.to_csv(parent / "bottleneck_breakdown.csv", index=False)
    all_parity = bool(parity["passed"].all()) if not parity.empty else False
    speed_targets_passed = bool(speed_acceptance["passed"].all())
    _write_common(
        parent, run_id=run_id, inputs=[config_path],
        summary={
            "run_id": run_id, "status": (
                "pass" if all_parity and speed_targets_passed
                else "pass_parity_speed_targets_not_met" if all_parity
                else "fail_parity"
            ),
            "output_policy": "audit", "run_class": "diagnostic_performance",
            "lineage_role": "non-canonical performance evidence", "fixture_replans": replans,
            "parity_passed": all_parity, "speed_targets_passed": speed_targets_passed,
            "speed_target_failure_count": int((~speed_acceptance["passed"]).sum()),
        },
        warnings=[
            "This is a short deterministic rolling performance fixture, not new canonical steel evidence.",
            "The physical boundary, stage gates and deterministic objective are unchanged.",
            "Cross-replan steel warm start remains a safe cold fallback pending a proven state mapper.",
        ],
    )
    return parent, runtime, parity


def main() -> int:
    args = _args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_optimized_equivalent_a01")
    payload: dict[str, Any] = {"run_id": run_id}
    if not args.skip_hydrogen:
        root, runtime, parity = _run_hydrogen(run_id, (REPO_ROOT / args.hydrogen_config).resolve(), args.hydrogen_days)
        payload["hydrogen"] = {"root": str(root), "runtime_rows": len(runtime), "parity_passed": bool(parity["passed"].all())}
    if not args.skip_steel:
        root, runtime, parity = _run_steel(run_id, (REPO_ROOT / args.steel_config).resolve(), args.steel_replans)
        payload["steel"] = {"root": str(root), "runtime_rows": len(runtime), "parity_passed": bool(parity["passed"].all())}
    print(json.dumps(payload, indent=2))
    return 0 if all(item.get("parity_passed", True) for key, item in payload.items() if isinstance(item, dict)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
