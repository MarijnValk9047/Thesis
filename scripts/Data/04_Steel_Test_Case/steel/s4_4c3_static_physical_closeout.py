"""S4.4c3 static physical closeout and plausibility diagnostics."""

from __future__ import annotations

import csv
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from pyomo.environ import Constraint, NonNegativeReals, Objective, RangeSet, Var, minimize, value

from .model import collect_model_stats
from .s4_0b_guardrail_regression_runner import _mip_gap
from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .s4_4c_unified_physical_modelbuilder import (
    _build_c0_inputs,
    _build_c0_model,
    _load_tables,
    _select_solver,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C1A_DIR = S4_ROOT / "s4_4c1a_asymmetric_24h_static_physical_regression"
C2_DIR = S4_ROOT / "s4_4c2_asymmetric_168h_static_physical_regression"
C3_DIR = S4_ROOT / "s4_4c3_static_physical_closeout"
C0 = "C0_current_BF_BOF_reference"

DAILY_ENVELOPE_LOW = 0.80
DAILY_ENVELOPE_HIGH = 1.20
FREE_C0_TIME_LIMIT_SECONDS = 60.0
FREE_C0_HORIZON_HOURS = 24


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


def _safe_float(value_in: Any, default: float = 0.0) -> float:
    try:
        if value_in in {"", None}:
            return default
        return float(value_in)
    except (TypeError, ValueError):
        return default


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _apply_solver_time_limit(solver: Any, seconds: float) -> list[str]:
    applied: list[str] = []
    try:
        if hasattr(solver, "config") and hasattr(solver.config, "time_limit"):
            solver.config.time_limit = seconds
            applied.append("solver.config.time_limit")
    except Exception:
        pass
    try:
        if hasattr(solver, "options"):
            solver.options["time_limit"] = seconds
            applied.append("solver.options.time_limit")
    except Exception:
        pass
    return applied


def _fixed_schedule_asset_rows(horizon_hours: int = 168) -> list[dict[str, Any]]:
    process_names = [
        "coking_plant_1",
        "sintering_plant",
        "blast_furnace_6",
        "basic_oxygen_furnace",
        "hot_strip_mill",
        "coking_plant_2",
        "blast_furnace_7",
    ]
    eight_hour_block = {
        "coking_plant_1",
        "blast_furnace_6",
        "blast_furnace_7",
        "basic_oxygen_furnace",
        "hot_strip_mill",
    }
    rows: list[dict[str, Any]] = []
    for process_name in process_names:
        fixed_on = 0
        for hour in range(horizon_hours):
            hour_of_day = hour % 24
            active = process_name in eight_hour_block and hour_of_day < 8
            if process_name == "sintering_plant":
                active = hour_of_day < 9
            fixed_on += int(active)
        rows.append(
            {
                "asset_or_binary": f"{process_name}_on",
                "fixed_hours": horizon_hours,
                "fixed_on_hours": fixed_on,
                "fixed_off_hours": horizon_hours - fixed_on,
                "slot_rule": "hour_of_day<8" if process_name in eight_hour_block else (
                    "hour_of_day<9" if process_name == "sintering_plant" else "always_off"
                ),
                "source": "S4.4c1a/S4.4c2 asymmetric regression fallback",
                "caveat": "Deterministic slot rule; not copied from an optimized free-C0 solution.",
            }
        )
    return rows


def _audit_fixed_schedule() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _fixed_schedule_asset_rows(168)
    total_fixed_hours = sum(int(row["fixed_hours"]) for row in rows)
    total_on_hours = sum(int(row["fixed_on_hours"]) for row in rows)
    payload = {
        "stage": "S4.4c3",
        "classification": "heuristic_not_benchmark_ready",
        "why_introduced": "The free C0 binary solve exceeded the interactive 5-minute timeout during S4.4c1a work; the fixed rule kept static physical feasibility diagnostics bounded.",
        "fixed_binary_variables": [row["asset_or_binary"] for row in rows],
        "fixed_binary_variable_count": len(rows),
        "horizon_hours_audited": 168,
        "fixed_binary_hour_count": total_fixed_hours,
        "fixed_on_hour_count": total_on_hours,
        "fixed_off_hour_count": total_fixed_hours - total_on_hours,
        "schedule_source_type": "deterministic_slot_rule",
        "copied_from_solved_pattern": False,
        "warm_start_only": False,
        "production_inventory_wag_depend_materially_on_schedule": True,
        "hidden_production_batching": True,
        "cp2_effectively_fixed_off": True,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "The schedule is a labelled feasibility fallback only. It fixes all C0 process on/off binaries and creates daily production batching.",
    }
    return rows, payload


def _c0_weekly_rows() -> list[dict[str, str]]:
    rows = _read_csv(C2_DIR / "s4_4c2_hourly_dispatch_c0.csv")
    return [row for row in rows if row.get("configuration_id") == C0]


def _production_plausibility(hourly_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    production = [_safe_float(row.get("final_product_output_t")) for row in hourly_rows]
    weekly_target = sum(production)
    average_daily = weekly_target / 7.0
    daily_totals = [sum(production[day * 24 : (day + 1) * 24]) for day in range(7)]
    daily_deviations = [value - average_daily for value in daily_totals]
    largest_deviation = max(abs(value) for value in daily_deviations)
    largest_deviation_pct = largest_deviation / average_daily if average_daily else 0.0
    average_hourly = weekly_target / len(production)
    low_threshold = 0.50 * average_hourly
    zero_hours = sum(1 for value in production if abs(value) <= 1e-6)
    low_hours = sum(1 for value in production if value < low_threshold)
    capacity_hours = sum(1 for value in production if value >= 800.0 - 1e-6)
    final_day_compression = daily_totals[-1] < DAILY_ENVELOPE_LOW * average_daily
    excessive_daily_variability = largest_deviation_pct > 0.20

    rows: list[dict[str, Any]] = [
        {
            "metric": "hourly_production",
            "min_t_h": round(min(production), 6),
            "max_t_h": round(max(production), 6),
            "mean_t_h": round(statistics.fmean(production), 6),
            "std_t_h": round(statistics.pstdev(production), 6),
            "zero_production_hours": zero_hours,
            "low_production_hours": low_hours,
            "capacity_bound_hours": capacity_hours,
            "final_day_compression": str(final_day_compression).lower(),
            "excessive_daily_variability": str(excessive_daily_variability).lower(),
            "front_or_back_loading_flag": str(final_day_compression or excessive_daily_variability).lower(),
            "caveat": "C0 production shape is from the fixed binary fallback schedule.",
        }
    ]
    for day, total in enumerate(daily_totals):
        rows.append(
            {
                "metric": "daily_production",
                "day_index": day,
                "daily_production_t": round(total, 6),
                "weekly_average_daily_target_t": round(average_daily, 6),
                "daily_deviation_t": round(total - average_daily, 6),
                "daily_deviation_pct": round((total - average_daily) / average_daily, 6),
                "below_80pct_average": str(total < DAILY_ENVELOPE_LOW * average_daily).lower(),
                "above_120pct_average": str(total > DAILY_ENVELOPE_HIGH * average_daily).lower(),
            }
        )

    process_map = {
        "coking_total": ("C0_coking_input_t_h", 180.0),
        "sintering": ("C0_sintering_input_t_h", 320.0),
        "bf_sinter_input": ("C0_BF_sinter_input_t_h", 431.53846154),
        "bof_hot_iron_input": ("C0_BOF_hot_iron_input_t_h", 830.0),
        "hsm_input": ("C0_HSM_input_t_h", 800.0),
    }
    for process_name, (field, capacity) in process_map.items():
        values = [_safe_float(row.get(field)) for row in hourly_rows]
        rows.append(
            {
                "metric": "process_utilisation",
                "asset_or_process": process_name,
                "total_activity": round(sum(values), 6),
                "active_hours": sum(1 for value in values if value > 1e-6),
                "capacity_bound_hours": sum(1 for value in values if value >= capacity - 1e-6),
                "utilisation_fraction_of_full_week_capacity": round(sum(values) / (capacity * len(values)), 6),
                "max_rate_observed": round(max(values), 6),
            }
        )

    flags = {
        "final_day_compression": final_day_compression,
        "excessive_daily_variability": excessive_daily_variability,
        "largest_daily_deviation_t": round(largest_deviation, 6),
        "largest_daily_deviation_pct": round(largest_deviation_pct, 6),
        "zero_production_hours": zero_hours,
        "low_production_hours": low_hours,
        "capacity_bound_hours": capacity_hours,
        "weekly_target_gamed_through_front_loading": final_day_compression and all(
            total >= average_daily for total in daily_totals[:6]
        ),
    }
    return rows, flags


def _inventory_plausibility(hourly_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inventory_specs = {
        "coke_inventory_t": 720.0,
        "sinter_inventory_t": 640.0,
        "hot_iron_inventory_t": 500.0,
        "cold_slab_inventory_t": 25000.0,
        "oxygen_inventory_t": math.nan,
    }
    rows: list[dict[str, Any]] = []
    zero_dependency = False
    capacity_dependency = False
    terminal_residual_nonzero = False
    for field, capacity in inventory_specs.items():
        if field not in hourly_rows[0]:
            rows.append(
                {
                    "inventory": field,
                    "available_in_hourly_dispatch": "false",
                    "caveat": "Not reported by current static C0 runner.",
                }
            )
            continue
        values = [_safe_float(row.get(field)) for row in hourly_rows]
        hit_zero = sum(1 for value in values if abs(value) <= 1e-6)
        hit_capacity = 0 if math.isnan(capacity) else sum(1 for value in values if abs(value - capacity) <= 1e-6)
        terminal_residual = ""
        if field == "coke_inventory_t":
            terminal_residual = values[-1] - 360.0
        elif field == "sinter_inventory_t":
            terminal_residual = values[-1] - 320.0
        elif field == "hot_iron_inventory_t":
            terminal_residual = values[-1] - 250.0
        elif field == "cold_slab_inventory_t":
            terminal_residual = values[-1] - 12500.0
        if terminal_residual != "" and abs(float(terminal_residual)) > 1e-6:
            terminal_residual_nonzero = True
        zero_dependency = zero_dependency or hit_zero > 0
        capacity_dependency = capacity_dependency or hit_capacity > 0
        rows.append(
            {
                "inventory": field,
                "available_in_hourly_dispatch": "true",
                "min_t": round(min(values), 6),
                "max_t": round(max(values), 6),
                "final_t": round(values[-1], 6),
                "capacity_t": "" if math.isnan(capacity) else capacity,
                "hours_at_zero": hit_zero,
                "hours_at_capacity": hit_capacity,
                "terminal_residual_t": "" if terminal_residual == "" else round(float(terminal_residual), 9),
                "zero_inventory_dependency": str(hit_zero > 0).lower(),
                "capacity_inventory_dependency": str(hit_capacity > 0).lower(),
            }
        )
    flags = {
        "zero_inventory_dependency": zero_dependency,
        "capacity_inventory_dependency": capacity_dependency,
        "free_buffer_battery_risk": terminal_residual_nonzero,
        "terminal_residual_nonzero": terminal_residual_nonzero,
    }
    return rows, flags


def _wag_plausibility(hourly_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    generated = sum(_safe_float(row.get("WAG_generated")) for row in hourly_rows)
    used = sum(_safe_float(row.get("WAG_used")) for row in hourly_rows)
    flared = sum(_safe_float(row.get("WAG_flared")) for row in hourly_rows)
    flare_fraction = flared / generated if generated else 0.0
    row = {
        "configuration_id": C0,
        "WAG_generated": round(generated, 6),
        "WAG_used": round(used, 6),
        "WAG_flared": round(flared, 6),
        "flare_fraction": round(flare_fraction, 6),
        "BFG_COG_BOFG_separate": "true",
        "direct_WAG_market_valuation_active": "false",
        "fixed_schedule_dependency": "true",
        "caveat": "Current static C0 runner reports aggregate WAG generation/flaring; utility sinks are not yet modelled.",
    }
    return [row], {"full_wag_flare": generated > 0 and abs(used) <= 1e-6}


def _guardrail_options() -> list[dict[str, Any]]:
    return [
        {
            "option_id": "daily_production_envelope",
            "mathematical_form": "0.8 * weekly_target / 7 <= sum_t_in_day final_product_t <= 1.2 * weekly_target / 7",
            "affected_variables": "final_product_output_t by day",
            "expected_impact": "Prevents six-day front-loading plus final-day compression while preserving weekly target.",
            "risk_of_over_constraining": "medium; real plant may legitimately schedule maintenance or campaign variation.",
            "changes_methodology": "yes",
            "thesis_base_or_sensitivity": "recommended_static_base_after_review",
            "recommended_default": "yes",
        },
        {
            "option_id": "rolling_24h_minimum_production",
            "mathematical_form": "sum_t_in_each_24h_window final_product_t >= 0.8 * weekly_target / 7",
            "affected_variables": "final_product_output_t in rolling windows",
            "expected_impact": "Controls production droughts even when day boundaries are arbitrary.",
            "risk_of_over_constraining": "medium_high; may conflict with legitimate long outages or transition outages.",
            "changes_methodology": "yes",
            "thesis_base_or_sensitivity": "sensitivity_or_robustness_check",
            "recommended_default": "no",
        },
        {
            "option_id": "process_continuity_max_off_hours",
            "mathematical_form": "for key C0 assets, rolling sum(on_t) >= minimum_on_hours or consecutive_off_hours <= cap",
            "affected_variables": "C0 process on/off binaries for BF, BOF, HSM, coking and sintering",
            "expected_impact": "Reduces hidden batch scheduling and more closely reflects continuous process operation.",
            "risk_of_over_constraining": "high; needs source-backed outage and campaign assumptions.",
            "changes_methodology": "yes",
            "thesis_base_or_sensitivity": "later_sensitivity_after_source_review",
            "recommended_default": "no",
        },
    ]


def _extract_c0_hourly(model: Any, inputs: Any, *, caveat: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in model.TIME:
        hour = int(t)
        wag_generated = float(value(model.wag_generated[t]))
        rows.append(
            {
                "hour_index": hour,
                "configuration_id": C0,
                "build_status": "solved",
                "C0_BF_BOF_STATIC_BLOCK_activity": round(float(value(model.hot_strip_mill[t])), 6),
                "C0_coking_input_t_h": round(float(value(model.coking_plant_1[t] + model.coking_plant_2[t])), 6),
                "C0_sintering_input_t_h": round(float(value(model.sintering_plant[t])), 6),
                "C0_BF_sinter_input_t_h": round(float(value(model.bf_sinter_input[t])), 6),
                "C0_BOF_hot_iron_input_t_h": round(float(value(model.basic_oxygen_furnace[t])), 6),
                "C0_HSM_input_t_h": round(float(value(model.hot_strip_mill[t])), 6),
                "final_product_output_t": round(float(value(model.final_product_output[t])), 6),
                "coke_inventory_t": round(float(value(model.coke_inventory[t])), 6),
                "sinter_inventory_t": round(float(value(model.sinter_inventory[t])), 6),
                "hot_iron_inventory_t": round(float(value(model.hot_iron_inventory[t])), 6),
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 6),
                "electricity_mwh": 0.0,
                "natural_gas_nm3": 0.0,
                "WAG_generated": round(wag_generated, 6),
                "WAG_used": 0.0,
                "WAG_flared": round(wag_generated, 6),
                "oxygen_t": 0.0,
                "caveat": caveat,
            }
        )
    return rows


def _run_daily_envelope_diagnostic() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    tables = _load_tables(CORRECTED_INPUT_DIR.resolve())
    inputs = _build_c0_inputs(tables, horizon_hours_override=168, target_multiplier=7.0)
    model = _build_c0_model(inputs, fix_binary_schedule=True)
    days = inputs.horizon_hours // 24
    daily_average = inputs.final_product_target_t / days
    lower = DAILY_ENVELOPE_LOW * daily_average
    upper = DAILY_ENVELOPE_HIGH * daily_average
    model.DAYS = RangeSet(0, days - 1)
    model.daily_under_slack = Var(model.DAYS, domain=NonNegativeReals)
    model.daily_over_slack = Var(model.DAYS, domain=NonNegativeReals)

    def _daily_product(m: Any, d: int) -> Any:
        return sum(m.final_product_output[t] for t in range(int(d) * 24, (int(d) + 1) * 24))

    model.daily_lower_envelope = Constraint(
        model.DAYS,
        rule=lambda m, d: _daily_product(m, d) + m.daily_under_slack[d] >= lower,
    )
    model.daily_upper_envelope = Constraint(
        model.DAYS,
        rule=lambda m, d: _daily_product(m, d) - m.daily_over_slack[d] <= upper,
    )
    base_objective = model.static_price_naive_objective.expr
    model.del_component("static_price_naive_objective")
    model.daily_envelope_objective = Objective(
        expr=1_000_000.0 * sum(model.daily_under_slack[d] + model.daily_over_slack[d] for d in model.DAYS)
        + base_objective,
        sense=minimize,
    )
    solver_name, solver = _select_solver()
    if solver is None:
        raise RuntimeError("No solver available for S4.4c3 daily-envelope diagnostic.")
    applied_limit = _apply_solver_time_limit(solver, 300.0)
    start = time.perf_counter()
    result = solver.solve(model)
    runtime = time.perf_counter() - start
    stats = collect_model_stats(model)
    termination = str(result.solver.termination_condition)
    status = str(result.solver.status)
    solved = termination.lower() in {"optimal", "feasible"}
    hourly_rows = _extract_c0_hourly(
        model,
        inputs,
        caveat="S4.4c3 diagnostic-only fixed-schedule C0 run with soft daily production envelope.",
    ) if solved else []
    slack_rows: list[dict[str, Any]] = []
    total_under = 0.0
    total_over = 0.0
    for day in range(days):
        production = sum(_safe_float(row.get("final_product_output_t")) for row in hourly_rows[day * 24 : (day + 1) * 24])
        under = float(value(model.daily_under_slack[day])) if solved else ""
        over = float(value(model.daily_over_slack[day])) if solved else ""
        if solved:
            total_under += under
            total_over += over
        slack_rows.append(
            {
                "day_index": day,
                "daily_production_t": round(production, 6) if solved else "",
                "lower_bound_t": round(lower, 6),
                "upper_bound_t": round(upper, 6),
                "under_slack_t": "" if under == "" else round(under, 9),
                "over_slack_t": "" if over == "" else round(over, 9),
            }
        )
    fulfilled = sum(_safe_float(row.get("final_product_output_t")) for row in hourly_rows) if solved else ""
    report = {
        "stage": "S4.4c3_daily_envelope_diagnostic",
        "diagnostic_only": True,
        "methodological_change": True,
        "not_thesis_base_yet": True,
        "solver_name": solver_name,
        "solver_status": status,
        "termination_condition": termination,
        "time_limit_seconds": 300.0,
        "time_limit_applied_via": ";".join(applied_limit),
        "runtime_seconds": round(runtime, 6),
        "target_t": round(inputs.final_product_target_t, 6),
        "fulfilled_t": "" if fulfilled == "" else round(float(fulfilled), 6),
        "production_residual_t": "" if fulfilled == "" else round(float(fulfilled) - inputs.final_product_target_t, 9),
        "daily_average_target_t": round(daily_average, 6),
        "daily_lower_bound_t": round(lower, 6),
        "daily_upper_bound_t": round(upper, 6),
        "total_under_slack_t": round(total_under, 9),
        "total_over_slack_t": round(total_over, 9),
        "slack_used": total_under > 1e-6 or total_over > 1e-6,
        "objective_value": "" if not solved else round(float(value(model.daily_envelope_objective)), 6),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "mip_gap": _mip_gap(result),
        "caveat": "Diagnostic guardrail variant only; it should not replace the C0 baseline without human acceptance.",
    }
    return report, hourly_rows, slack_rows


def _run_free_c0_diagnostic() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    tables = _load_tables(CORRECTED_INPUT_DIR.resolve())
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=FREE_C0_HORIZON_HOURS,
        target_multiplier=FREE_C0_HORIZON_HOURS / 24.0,
    )
    model = _build_c0_model(inputs, fix_binary_schedule=False)
    solver_name, solver = _select_solver()
    if solver is None:
        return (
            {
                "stage": "S4.4c3_free_c0_solve_diagnostic",
                "attempt_id": "free_c0_24h_time_limited",
                "solver_name": "",
                "solver_status": "no_solver",
                "termination_condition": "not_run",
                "runtime_seconds": 0.0,
                "caveat": "No solver available.",
            },
            [],
            [],
        )
    applied_limit = _apply_solver_time_limit(solver, FREE_C0_TIME_LIMIT_SECONDS)
    stats = collect_model_stats(model)
    start = time.perf_counter()
    result = None
    exc_text = ""
    try:
        result = solver.solve(model)
    except Exception as exc:  # pragma: no cover - defensive solver boundary
        exc_text = str(exc)
    runtime = time.perf_counter() - start
    if result is None:
        report = {
            "stage": "S4.4c3_free_c0_solve_diagnostic",
            "attempt_id": "free_c0_24h_time_limited",
            "free_168h_attempted": False,
            "free_168h_skip_reason": "Not attempted because the prior free 24h run exceeded the 5-minute interactive timeout; bounded 24h diagnostic is the scaling probe.",
            "warm_start_supported": False,
            "solver_name": solver_name,
            "solver_status": "exception",
            "termination_condition": "exception",
            "runtime_seconds": round(runtime, 6),
            "time_limit_seconds": FREE_C0_TIME_LIMIT_SECONDS,
            "time_limit_applied_via": ";".join(applied_limit),
            "objective_value": "",
            "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "",
            "final_product_residual_t": "",
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "mip_gap": "",
            "caveat": exc_text,
        }
        return report, [], [{"diagnostic": "solver_exception", "detail": exc_text}]
    termination = str(result.solver.termination_condition)
    status = str(result.solver.status)
    solved = termination.lower() in {"optimal", "feasible"}
    incumbent_available = False
    incumbent_objective: float | str = ""
    incumbent_fulfilled: float | str = ""
    incumbent_residual: float | str = ""
    try:
        incumbent_objective = float(value(model.static_price_naive_objective))
        incumbent_fulfilled = sum(float(value(model.final_product_output[t])) for t in model.TIME)
        incumbent_residual = incumbent_fulfilled - inputs.final_product_target_t
        incumbent_available = True
    except Exception:
        incumbent_available = False
    hourly_rows = _extract_c0_hourly(
        model,
        inputs,
        caveat="S4.4c3 free-C0 bounded diagnostic solve.",
    ) if solved else []
    fulfilled = sum(_safe_float(row.get("final_product_output_t")) for row in hourly_rows) if solved else ""
    report = {
        "stage": "S4.4c3_free_c0_solve_diagnostic",
        "attempt_id": "free_c0_24h_time_limited",
        "free_168h_attempted": False,
        "free_168h_skip_reason": "Not attempted because the prior free 24h run exceeded the 5-minute interactive timeout; bounded 24h diagnostic is the scaling probe.",
        "warm_start_supported": False,
        "incumbent_available": incumbent_available,
        "solver_name": solver_name,
        "solver_status": status,
        "termination_condition": termination,
        "runtime_seconds": round(runtime, 6),
        "time_limit_seconds": FREE_C0_TIME_LIMIT_SECONDS,
        "time_limit_applied_via": ";".join(applied_limit),
        "objective_value": "" if not incumbent_available else round(float(incumbent_objective), 6),
        "final_product_target_t": round(inputs.final_product_target_t, 6),
        "final_product_fulfilled_t": "" if not incumbent_available else round(float(incumbent_fulfilled), 6),
        "final_product_residual_t": "" if not incumbent_available else round(float(incumbent_residual), 9),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "mip_gap": _mip_gap(result),
        "caveat": "Bounded diagnostic only. Current solver interface has no validated MIP-start path for the fixed-schedule incumbent.",
    }
    diagnostics = []
    if not solved:
        diagnostics.append(
            {
                "diagnostic": "free_c0_not_solved",
                "solver_status": status,
                "termination_condition": termination,
                "time_limit_seconds": FREE_C0_TIME_LIMIT_SECONDS,
                "caveat": "Fixed schedule remains necessary as a labelled fallback for bounded static runs.",
            }
        )
    return report, hourly_rows, diagnostics


def _variant_summary(name: str, metrics: dict[str, Any], daily_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    daily_values = []
    if daily_rows:
        daily_values = [_safe_float(row.get("daily_production_t", row.get("production_t"))) for row in daily_rows]

    def _first_present(*keys: str) -> Any:
        for key in keys:
            if key in metrics and metrics[key] not in {"", None}:
                return metrics[key]
        return ""

    return {
        "variant_id": name,
        "target_t": _first_present("target_t", "final_product_target_t"),
        "fulfilled_t": _first_present("fulfilled_t", "final_product_fulfilled_t"),
        "production_residual_t": _first_present("production_residual_t", "final_product_residual_t"),
        "objective_value": metrics.get("objective_value", ""),
        "solve_time_seconds": metrics.get("runtime_seconds", ""),
        "mip_gap": metrics.get("mip_gap", ""),
        "variable_count": metrics.get("variable_count", ""),
        "binary_count": metrics.get("binary_count", ""),
        "constraint_count": metrics.get("constraint_count", ""),
        "daily_min_t": "" if not daily_values else round(min(daily_values), 6),
        "daily_max_t": "" if not daily_values else round(max(daily_values), 6),
        "daily_std_t": "" if len(daily_values) < 2 else round(statistics.pstdev(daily_values), 6),
        "fixed_schedule_materially_changes_behavior": str(name == "fixed_c2_baseline").lower(),
        "caveat": metrics.get("caveat", ""),
    }


def run_s4_4c3_static_physical_closeout() -> dict[str, Any]:
    C3_DIR.mkdir(parents=True, exist_ok=True)
    fixed_rows, fixed_payload = _audit_fixed_schedule()
    hourly_rows = _c0_weekly_rows()
    production_rows, production_flags = _production_plausibility(hourly_rows)
    inventory_rows, inventory_flags = _inventory_plausibility(hourly_rows)
    wag_rows, wag_flags = _wag_plausibility(hourly_rows)
    guardrail_rows = _guardrail_options()
    daily_report, daily_hourly, daily_slack = _run_daily_envelope_diagnostic()
    free_report, free_hourly, free_diagnostics = _run_free_c0_diagnostic()

    baseline_metrics = _read_csv(C2_DIR / "s4_4c2_run_metrics.csv")[0]
    baseline_analytics = _read_csv(C2_DIR / "s4_4c2_computational_analytics.csv")[0]
    fixed_daily = _read_csv(C2_DIR / "s4_4c2_daily_summary.csv")
    fixed_c0_daily = [row for row in fixed_daily if row.get("configuration_id") == C0]
    comparison_rows = [
        _variant_summary(
            "fixed_c2_baseline",
            {
                "final_product_target_t": baseline_metrics.get("final_product_target_t"),
                "final_product_fulfilled_t": baseline_metrics.get("final_product_fulfilled_t"),
                "final_product_residual_t": baseline_metrics.get("final_product_residual_t"),
                "objective_value": baseline_analytics.get("objective_value"),
                "runtime_seconds": baseline_analytics.get("solve_time_seconds"),
                "mip_gap": baseline_analytics.get("mip_gap"),
                "variable_count": baseline_analytics.get("variable_count"),
                "binary_count": baseline_analytics.get("binary_count"),
                "constraint_count": baseline_analytics.get("constraint_count"),
                "caveat": "Fixed C0 binary schedule baseline from S4.4c2.",
            },
            fixed_c0_daily,
        )
    ]
    daily_rows_for_summary = []
    if daily_hourly:
        for day in range(7):
            chunk = daily_hourly[day * 24 : (day + 1) * 24]
            daily_rows_for_summary.append(
                {
                    "day_index": day,
                    "daily_production_t": round(sum(_safe_float(row.get("final_product_output_t")) for row in chunk), 6),
                }
            )
    comparison_rows.append(_variant_summary("daily_envelope_diagnostic", daily_report, daily_rows_for_summary))
    comparison_rows.append(_variant_summary("free_c0_24h_time_limited", free_report, None))

    fake_flexibility_risk = (
        production_flags["final_day_compression"]
        or production_flags["excessive_daily_variability"]
        or inventory_flags["zero_inventory_dependency"]
        or inventory_flags["capacity_inventory_dependency"]
    )
    severe_fake_flexibility = inventory_flags["free_buffer_battery_risk"]
    free_c0_solved = free_report.get("termination_condition", "").lower() in {"optimal", "feasible"}
    if severe_fake_flexibility:
        decision = "blocked_static_physical_closeout_fake_flexibility"
    elif free_c0_solved and free_report.get("final_product_residual_t") == 0:
        decision = "pass_static_physical_closeout_free_c0_solve_available"
    elif production_flags["final_day_compression"] or production_flags["excessive_daily_variability"]:
        decision = "pass_static_physical_closeout_but_daily_guardrail_required"
    else:
        decision = "pass_static_physical_closeout_fixed_schedule_accepted_as_development_baseline"

    gate = {
        "stage": "S4.4c3",
        "decision": decision,
        "fixed_schedule_classification": fixed_payload["classification"],
        "final_day_compression": str(production_flags["final_day_compression"]).lower(),
        "excessive_daily_variability": str(production_flags["excessive_daily_variability"]).lower(),
        "zero_inventory_dependency": str(inventory_flags["zero_inventory_dependency"]).lower(),
        "capacity_inventory_dependency": str(inventory_flags["capacity_inventory_dependency"]).lower(),
        "fixed_schedule_dependency": "true",
        "free_buffer_battery_risk": str(inventory_flags["free_buffer_battery_risk"]).lower(),
        "fake_flexibility_risk": str(fake_flexibility_risk).lower(),
        "daily_envelope_diagnostic_run": "true",
        "daily_envelope_slack_used": str(daily_report["slack_used"]).lower(),
        "free_c0_diagnostic_solved": str(free_c0_solved).lower(),
        "ready_for_hot_cold_slab_and_wag_utility_equation_work": "true_with_guardrail_caveat",
        "ready_for_benchmark_weekly_operation": "false",
        "hourly_da_price_taking_active": "false",
        "product_revenue_active": "false",
        "export_revenue_active": "false",
        "direct_wag_market_valuation_active": "false",
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": "Static physical closeout only. Weekly C0 production shape needs a daily or rolling guardrail before benchmark use.",
    }
    report = {
        "stage": "S4.4c3",
        "fixed_schedule_audit": fixed_payload,
        "production_flags": production_flags,
        "inventory_flags": inventory_flags,
        "wag_flags": wag_flags,
        "daily_envelope_diagnostic": daily_report,
        "free_c0_diagnostic": free_report,
        "stage_gate": gate,
    }

    _write_csv(C3_DIR / "s4_4c3_fixed_c0_binary_schedule_audit.csv", fixed_rows)
    _write_json(C3_DIR / "s4_4c3_fixed_c0_binary_schedule_audit.json", fixed_payload)
    _write_csv(C3_DIR / "s4_4c3_c0_weekly_production_plausibility.csv", production_rows)
    _write_csv(C3_DIR / "s4_4c3_c0_inventory_plausibility.csv", inventory_rows)
    _write_csv(C3_DIR / "s4_4c3_c0_wag_plausibility.csv", wag_rows)
    _write_csv(C3_DIR / "s4_4c3_production_stability_guardrail_options.csv", guardrail_rows)
    _write_json(C3_DIR / "s4_4c3_c0_daily_envelope_diagnostic_report.json", daily_report)
    _write_csv(C3_DIR / "s4_4c3_c0_daily_envelope_diagnostic_report.csv", [daily_report])
    if daily_hourly:
        _write_csv(C3_DIR / "s4_4c3_c0_daily_envelope_hourly_dispatch.csv", daily_hourly)
    _write_csv(C3_DIR / "s4_4c3_c0_daily_envelope_slack.csv", daily_slack)
    _write_json(C3_DIR / "s4_4c3_free_c0_solve_diagnostic_report.json", free_report)
    _write_csv(C3_DIR / "s4_4c3_free_c0_solve_diagnostic_report.csv", [free_report])
    _write_csv(
        C3_DIR / "s4_4c3_free_c0_solver_log_summary.csv",
        [
            {
                "solver_log_available": "false",
                "solver_name": free_report.get("solver_name", ""),
                "summary": "No solver text log was emitted by the current appsi_highs interface.",
            }
        ],
    )
    if free_diagnostics:
        _write_csv(C3_DIR / "s4_4c3_free_c0_infeasibility_or_timeout_diagnostics.csv", free_diagnostics)
    _write_csv(C3_DIR / "s4_4c3_fixed_vs_free_or_guarded_comparison.csv", comparison_rows)
    _write_json(C3_DIR / "s4_4c3_stage_gate.json", gate)
    _write_csv(C3_DIR / "s4_4c3_stage_gate.csv", [gate])
    _write_json(C3_DIR / "s4_4c3_static_physical_closeout_report.json", report)
    _write_csv(
        C3_DIR / "s4_4c3_static_physical_closeout_report.csv",
        [
            {
                "stage": "S4.4c3",
                "decision": decision,
                "fixed_schedule_classification": fixed_payload["classification"],
                "largest_daily_deviation_pct": production_flags["largest_daily_deviation_pct"],
                "daily_envelope_slack_used": daily_report["slack_used"],
                "free_c0_termination_condition": free_report.get("termination_condition", ""),
                "ready_for_hot_cold_slab_and_wag_utility_equation_work": gate[
                    "ready_for_hot_cold_slab_and_wag_utility_equation_work"
                ],
            }
        ],
    )
    return report


def main() -> int:
    report = run_s4_4c3_static_physical_closeout()
    print(
        json.dumps(
            {
                "decision": report["stage_gate"]["decision"],
                "fixed_schedule_classification": report["stage_gate"]["fixed_schedule_classification"],
                "daily_envelope_slack_used": report["stage_gate"]["daily_envelope_slack_used"],
                "free_c0_diagnostic_solved": report["stage_gate"]["free_c0_diagnostic_solved"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
