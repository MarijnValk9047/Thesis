from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_PATH.parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hydrogen.benchmarks import run_price_insensitive_heuristic  # noqa: E402
from hydrogen.optimisation_model import solve_stochastic_dispatch  # noqa: E402
from hydrogen.plant_parameters import (  # noqa: E402
    ProductionTargetEntry,
    ProductionTargetsSettings,
    load_hydrogen_config,
)


LOCAL_TZ = "Europe/Amsterdam"


def _build_one_day_frame(local_day: str, *, scenario_price_eur_per_mwh: float = 300.0) -> pd.DataFrame:
    local_start = pd.Timestamp(f"{local_day} 00:00:00", tz=LOCAL_TZ)
    timestamps = pd.date_range(local_start, periods=24, freq="h").tz_convert("UTC")
    return pd.DataFrame(
        {
            "scenario_id": "deterministic",
            "scenario_probability": 1.0,
            "scenario_price_eur_per_mwh": float(scenario_price_eur_per_mwh),
            "delivery_start_utc": timestamps,
            "actual_price_eur_per_mwh": float(scenario_price_eur_per_mwh),
            "point_forecast_eur_per_mwh": float(scenario_price_eur_per_mwh),
        }
    )


def _rolling_targets(*targets: ProductionTargetEntry, initial_inventory_kg: float = 0.0) -> ProductionTargetsSettings:
    return ProductionTargetsSettings(
        mode="rolling_deadline_envelope",
        initial_inventory_kg=float(initial_inventory_kg),
        max_inventory_kg=None,
        terminal_inventory_value_mode="disabled",
        targets=tuple(targets),
    )


def _summarise_case(name: str, result: Any) -> dict[str, Any]:
    dispatch = result.dispatch.copy()
    debug_info = result.debug_info or {}
    plan = debug_info.get("rolling_target_plan") or {}
    return {
        "case": name,
        "total_production_kg": float(dispatch["H_comp_kg"].sum()) if not dispatch.empty else 0.0,
        "shortfall_kg": float(dispatch["shortfall_kg"].iloc[0]) if not dispatch.empty else 0.0,
        "solver_status": str(result.solver.status),
        "objective_value_eur": float(result.solver.objective_value) if result.solver.objective_value is not None else None,
        "terminal_inventory_value_disabled": bool(plan.get("effective_apply_terminal_value") is False),
        "rolling_constraints": plan.get("rolling_constraints", []),
        "terminal_guards": plan.get("terminal_guards", []),
    }


def main() -> int:
    config = load_hydrogen_config(REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml")
    reserve_only_inventory = float(config.hydrogen_system.reserve_kg)
    local_day = "2025-07-11"
    frame = _build_one_day_frame(local_day)

    cases: list[dict[str, Any]] = []

    due_inside_result = solve_stochastic_dispatch(
        day_scenarios=frame,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=reserve_only_inventory,
        reserve_kg=config.hydrogen_system.reserve_kg,
        daily_target_kg=config.economics.daily_target_kg,
        gamma=0.0,
        alpha=config.risk.alpha,
        production_target_mode="current_soft_target",
        production_targets=_rolling_targets(
            ProductionTargetEntry(
                delivery_id="due_inside",
                due_date=local_day,
                required_quantity_kg=10000.0,
            )
        ),
        apply_terminal_value=True,
        terminal_reference_start_kg=reserve_only_inventory,
        terminal_value_per_kg=config.terminal_inventory_value_per_kg,
    )
    due_inside_summary = _summarise_case("due_inside_horizon", due_inside_result)
    due_inside_summary["due_targets_satisfied"] = bool(due_inside_summary["total_production_kg"] + 1e-6 >= 10000.0)
    cases.append(due_inside_summary)

    guard_active_result = solve_stochastic_dispatch(
        day_scenarios=frame,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=reserve_only_inventory,
        reserve_kg=config.hydrogen_system.reserve_kg,
        daily_target_kg=config.economics.daily_target_kg,
        gamma=0.0,
        alpha=config.risk.alpha,
        production_target_mode="current_soft_target",
        production_targets=_rolling_targets(
            ProductionTargetEntry(
                delivery_id="future_tight",
                due_date="2025-07-12",
                required_quantity_kg=40000.0,
            )
        ),
        apply_terminal_value=True,
        terminal_reference_start_kg=reserve_only_inventory,
        terminal_value_per_kg=config.terminal_inventory_value_per_kg,
    )
    guard_active_summary = _summarise_case("future_guard_active", guard_active_result)
    guard_active_summary["due_targets_satisfied"] = True
    cases.append(guard_active_summary)

    guard_inactive_result = solve_stochastic_dispatch(
        day_scenarios=frame,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=reserve_only_inventory,
        reserve_kg=config.hydrogen_system.reserve_kg,
        daily_target_kg=config.economics.daily_target_kg,
        gamma=0.0,
        alpha=config.risk.alpha,
        production_target_mode="current_soft_target",
        production_targets=_rolling_targets(
            ProductionTargetEntry(
                delivery_id="future_loose",
                due_date="2025-07-12",
                required_quantity_kg=20000.0,
            )
        ),
        apply_terminal_value=True,
        terminal_reference_start_kg=reserve_only_inventory,
        terminal_value_per_kg=config.terminal_inventory_value_per_kg,
    )
    guard_inactive_summary = _summarise_case("future_guard_inactive", guard_inactive_result)
    guard_inactive_summary["due_targets_satisfied"] = True
    cases.append(guard_inactive_summary)

    rolling_config = replace(config, production_targets=_rolling_targets(
        ProductionTargetEntry(
            delivery_id="benchmark_check",
            due_date=local_day,
            required_quantity_kg=1000.0,
        )
    ))
    try:
        run_price_insensitive_heuristic(
            day_frame=frame,
            config=rolling_config,
            inventory_start_kg=reserve_only_inventory,
            reserve_kg=config.hydrogen_system.reserve_kg,
            apply_terminal_value=True,
            terminal_reference_start_kg=reserve_only_inventory,
        )
    except Exception as exc:
        benchmark_payload = {
            "case": "heuristic_benchmark_support",
            "status": "failed_clearly",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        benchmark_payload = {
            "case": "heuristic_benchmark_support",
            "status": "unexpected_success",
        }

    print(json.dumps({"cases": cases, "benchmark_check": benchmark_payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
