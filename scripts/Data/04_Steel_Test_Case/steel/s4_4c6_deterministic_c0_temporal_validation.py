"""Governed deterministic C0 temporal validation and one-week comparison.

This runner contains no bids, scenarios, settlement, stochasticity or ETS
objective. It extends the shared physical builder with a configuration-specific
C0 rolling contract and reuses the accepted C1 day solver for common-support
behaviour reporting.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import pandas as pd
import yaml
from pyomo.environ import Objective, minimize, value
from pyomo.opt import SolverFactory

from visual_style import COLORS, apply_visual_style, save_figure

from .model import collect_model_stats
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
)
from .s4_4c6_deterministic_behaviour_anchor_validation import (
    _activate_c1_calibration_bundle,
    _calibrate_continuation,
    _solve_day,
    load_representative_week_prices,
    load_validation_config,
)
from .s4_4c6_deterministic_temporal_repair import (
    CALENDAR_CONTRACT_VERSION,
    PHYSICAL_TOLERANCE,
    _canonical_json_sha256,
    initial_temporal_state,
    load_temporal_repair_config,
    prepare_temporal_context,
    quota_period_target_taps,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelRollingState,
    _build_physical_model,
    _component_value,
    _inventory_overrides,
    _represented_cost_expression,
    _route_progress_values,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c6_deterministic_c0_temporal_validation.yaml"
)
C0_TEMPORAL_CONTRACT_VERSION = (
    "c0_deterministic_scalar_temporal_v6_hsm_block_campaign_scrap_cap_1p41Mt"
)
HOURS_PER_YEAR = 8_760
DT = 0.25
EXECUTION_STEPS = 96
PHYSICAL_HORIZON_HOURS = 48
C0_CONTINUOUS_ASSETS = (
    "coking_plant_1",
    "coking_plant_2",
    "sintering_plant",
    "blast_furnace_6",
    "blast_furnace_7",
)


class C0TemporalValidationError(RuntimeError):
    """Fail-closed C0 temporal-validation error."""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_c0_validation_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload["temporal_contract_version"] != C0_TEMPORAL_CONTRACT_VERSION:
        raise C0TemporalValidationError("Unexpected C0 temporal contract version.")
    if payload["calendar_contract_version"] != CALENDAR_CONTRACT_VERSION:
        raise C0TemporalValidationError("C0 calendar contract must exclude maintenance.")
    if payload["objective_mode"] != "scalar_procurement_only":
        raise C0TemporalValidationError("C0 operation must use procurement-only scalar cost.")
    if payload["forbidden_scope"]["full_four_week_matrix_authorized"] is not False:
        raise C0TemporalValidationError("Four-week authorization must remain false.")
    return payload


def prepare_c0_context(
    config: Mapping[str, Any], base_temporal_config: Mapping[str, Any]
) -> Any:
    context = prepare_temporal_context(base_temporal_config)
    return replace(
        context,
        temporal_contract_version=C0_TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        economic_horizon_hours=24,
        physical_feasibility_tail_active=True,
    )


def initial_c0_state(config: Mapping[str, Any], *, episode_id: str) -> SteelRollingState:
    dynamics = config["plant_dynamics"]
    return SteelRollingState(
        episode_id=episode_id,
        configuration_id=C0_CONFIGURATION,
        temporal_contract_version=C0_TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        last_continuous_rate_t_h={
            key: float(value)
            for key, value in dynamics["normal_reference_rates_t_h"].items()
        },
        pefa_last_output_t_h=float(dynamics["pefa"]["initial_output_t_h"]),
        pellet_inventory_t=float(dynamics["pefa"]["initial_inventory_t"]),
        hsm_last_input_t_h=float(
            dynamics["downstream_temporal_contract"]["hsm_initial_rate_t_h"]
        ),
    )


def validate_c0_state(state: SteelRollingState, config: Mapping[str, Any]) -> None:
    if state.configuration_id != C0_CONFIGURATION:
        raise C0TemporalValidationError("C0 state has a different configuration.")
    if state.temporal_contract_version != C0_TEMPORAL_CONTRACT_VERSION:
        raise C0TemporalValidationError("Old or C1 temporal states are forbidden for C0.")
    if state.calendar_contract_version != CALENDAR_CONTRACT_VERSION:
        raise C0TemporalValidationError("Maintenance-calendar states are forbidden.")
    if set(state.last_continuous_rate_t_h) != set(C0_CONTINUOUS_ASSETS):
        raise C0TemporalValidationError("C0 state lacks a canonical continuous rate.")
    if state.pefa_last_output_t_h is None or state.pellet_inventory_t is None:
        raise C0TemporalValidationError("C0 state lacks its PeFa/pellet handoff.")
    if state.hsm_last_input_t_h is None or not 0.0 <= float(
        state.hsm_last_input_t_h
    ) <= 800.0:
        raise C0TemporalValidationError("C0 state lacks its HSM campaign handoff.")
    pefa = config["plant_dynamics"]["pefa"]
    if not (
        float(pefa["minimum_output_t_h"]) - PHYSICAL_TOLERANCE
        <= float(state.pefa_last_output_t_h)
        <= float(pefa["maximum_output_t_h"]) + PHYSICAL_TOLERANCE
    ):
        raise C0TemporalValidationError("C0 PeFa state is outside its development band.")
    if not 0.0 <= float(state.pellet_inventory_t) <= float(
        pefa["inventory_capacity_t"]
    ):
        raise C0TemporalValidationError("C0 pellet inventory is outside capacity.")


def _execution_band(context: Any, state: SteelRollingState) -> tuple[float, float]:
    annual = float(context.config["annual_reference_target_mt_y"]) * 1_000_000.0
    endpoint = int(state.executed_hours) + 24
    central = annual * endpoint / HOURS_PER_YEAR
    return (
        max(0.0, central * 0.995 - float(state.cumulative_production_t)),
        max(0.0, central * 1.005 - float(state.cumulative_production_t)),
    )


def build_c0_temporal_model(
    context: Any,
    state: SteelRollingState,
    config: Mapping[str, Any],
    prices: Sequence[float],
) -> tuple[Any, Any, tuple[float, float]]:
    validate_c0_state(state, config)
    if len(prices) != EXECUTION_STEPS:
        raise C0TemporalValidationError("C0 execution price vector must contain 96 QH.")
    lower, upper = _execution_band(context, state)
    material = config["c0_material_contract"]
    scrap_contract = {
        "annual_site_scrap_cap_t_y": float(material["annual_site_scrap_cap_t_y"]),
        "annual_bof_scrap_cap_t_y": float(material["annual_bof_scrap_cap_t_y"]),
        "annual_eaf_scrap_cap_t_y": 0.0,
        "annual_external_scrap_cap_t_y": float(
            material["annual_external_scrap_cap_t_y"]
        ),
        "annual_internal_scrap_cap_t_y": float(
            material["annual_internal_scrap_cap_t_y"]
        ),
        "quota_period_hours": HOURS_PER_YEAR,
    }
    model = _build_physical_model(
        context,
        C0_CONFIGURATION,
        state,
        terminal_day=False,
        planning_horizon_hours=PHYSICAL_HORIZON_HOURS,
        temporal_repair_contract={
            "configuration_id": C0_CONFIGURATION,
            "temporal_contract_version": C0_TEMPORAL_CONTRACT_VERSION,
            "inventory_terminal_policy": "recoverable_physical_tail",
            "recursive_recovery_horizon_hours": PHYSICAL_HORIZON_HOURS,
            "scrap_execution_checkpoint_hours": 24,
            "final_product_execution_lower_t": lower,
            "final_product_execution_upper_t": upper,
            "route_reference_policy": "annual_recoverable_calendar",
            "scrap_origin_contract": scrap_contract,
            "c0_bf_material_interface": {
                "sinter_t_per_t_hot_metal": float(
                    material["sinter_t_per_t_hot_metal"]
                ),
                "pellets_t_per_t_hot_metal": float(
                    material["pellets_t_per_t_hot_metal"]
                ),
            },
            "c0_coke_chain_reconciliation": dict(
                material["c0_coke_chain_reconciliation"]
            ),
            "plant_dynamics": dict(config["plant_dynamics"]),
        },
    )
    physical_prices = tuple(float(item) for item in prices) + (
        float(prices[-1]),
    ) * EXECUTION_STEPS
    procurement = _represented_cost_expression(
        context,
        model,
        C0_CONFIGURATION,
        physical_prices,
        objective_hours=range(EXECUTION_STEPS),
    )
    model.c0_scalar_procurement_objective = Objective(
        expr=procurement, sense=minimize
    )
    model.c0_represented_procurement_cost_D = procurement
    model.c0_objective_mode = "scalar_procurement_only"
    return model, procurement, (lower, upper)


def _solver_bound(result: Any) -> float | None:
    for owner, key in ((result.problem, "lower_bound"), (result.solver, "best_bound")):
        try:
            candidate = owner.get(key)
            if candidate is not None and math.isfinite(float(candidate)):
                return float(candidate)
        except Exception:
            continue
    return None


def audit_c0_incumbent(
    model: Any, execution_band: tuple[float, float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(check: str, residual: float, tolerance: float = 1e-5) -> None:
        rows.append(
            {
                "check": check,
                "residual": float(residual),
                "tolerance": float(tolerance),
                "passed": abs(float(residual)) <= float(tolerance),
            }
        )

    for q in range(EXECUTION_STEPS):
        add(
            "bof_material_identity",
            _component_value(model, "c0_bof_material_balance_residual", q),
        )
        add(
            "scrap_origin_identity",
            _component_value(model, "external_scrap_to_bof_t", q)
            + _component_value(model, "internal_scrap_to_bof_t", q)
            - _component_value(model, "c0_bof_scrap_input", q),
        )
        for asset in C0_CONTINUOUS_ASSETS:
            add(
                f"{asset}_must_run",
                max(0.0, 1.0 - _component_value(model, f"{asset}_on", q)),
                1e-6,
            )
        add(
            "electricity_identity",
            _component_value(model, "total_generator_electricity_mwh", q)
            + _component_value(model, "gross_grid_import_mwh", q)
            - _component_value(model, "gross_total_electricity_mwh", q),
        )
        for carrier in ("bfg", "cog", "bofg"):
            constraint = getattr(model, f"{carrier}_balance")[q]
            add(f"{carrier}_balance", float(value(constraint.body)))
    produced = sum(
        _component_value(model, "final_product_output", q)
        for q in range(EXECUTION_STEPS)
    )
    lower, upper = execution_band
    add("final_product_execution_lower", max(0.0, lower - produced))
    add("final_product_execution_upper", max(0.0, produced - upper))
    forbidden = ("drp_pellet_input", "eaf_heat_start", "vn25_electricity_mwh")
    for name in forbidden:
        rows.append(
            {
                "check": f"forbidden_C0_component_{name}",
                "residual": 1.0 if hasattr(model, name) else 0.0,
                "tolerance": 0.0,
                "passed": not hasattr(model, name),
            }
        )
    return rows


def solve_c0_day(
    context: Any,
    state: SteelRollingState,
    config: Mapping[str, Any],
    prices: Sequence[float],
    *,
    case_id: str,
    output: Path,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    model, procurement, band = build_c0_temporal_model(
        context, state, config, prices
    )
    solver_config = config["solver"]
    attempts: list[dict[str, Any]] = []
    accepted = False
    for attempt, limit in (
        ("primary_6s", float(solver_config["time_limit_seconds"])),
        ("fallback_60s", float(solver_config["fallback_time_limit_seconds"])),
    ):
        log_path = output / "solver_logs" / f"{case_id}__{attempt}.log"
        solver = SolverFactory("gurobi")
        solver.options["TimeLimit"] = limit
        solver.options["MIPGap"] = float(solver_config["mip_gap"])
        solver.options["Threads"] = int(solver_config["threads"])
        solver.options["Seed"] = int(solver_config["seed"])
        solver.options["LogFile"] = str(log_path)
        started = time.perf_counter()
        # A time limit without an incumbent is an expected operational outcome.
        # Inspect the result before loading it so Pyomo cannot reject the empty
        # SolverResults object before the governed fallback is attempted.
        result = solver.solve(model, tee=False, load_solutions=False)
        runtime = time.perf_counter() - started
        termination = str(result.solver.termination_condition).lower()
        has_incumbent = len(result.solution) > 0
        feasible = has_incumbent and termination in {
            "optimal",
            "feasible",
            "maxtimelimit",
            "max time limit",
        }
        if feasible:
            model.solutions.load_from(result)
        objective = float(value(procurement)) if feasible else None
        bound = _solver_bound(result)
        relative_gap = (
            None
            if objective is None or bound is None or abs(objective) < 1e-9
            else abs(objective - bound) / abs(objective)
        )
        attempt_row = {
            "case_id": case_id,
            "attempt": attempt,
            "solver_status": str(result.solver.status),
            "termination_condition": str(result.solver.termination_condition),
            "feasible_incumbent": feasible,
            "incumbent_objective_eur": objective,
            "best_bound_eur": bound,
            "relative_gap": relative_gap,
            "runtime_seconds": runtime,
            "time_limit_seconds": limit,
            "solver_log": str(log_path.relative_to(REPO_ROOT)),
        }
        attempts.append(attempt_row)
        if feasible:
            accepted = True
            break
    if not accepted:
        raise C0TemporalValidationError(
            f"C0 day {case_id} has no incumbent after the single fallback."
        )
    audit = audit_c0_incumbent(model, band)
    if not all(bool(row["passed"]) for row in audit):
        raise C0TemporalValidationError(f"C0 incumbent audit failed for {case_id}.")
    attempts[-1]["audit_status"] = "pass"
    stats = collect_model_stats(model)
    attempts[-1].update(
        {
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
        }
    )
    return model, attempts[-1], audit


def advance_c0_state(
    context: Any,
    model: Any,
    state: SteelRollingState,
    *,
    last_timestamp_utc: str,
) -> SteelRollingState:
    last = EXECUTION_STEPS - 1
    produced = sum(
        _component_value(model, "final_product_output", q)
        for q in range(EXECUTION_STEPS)
    )
    route_increment: dict[str, float] = {}
    for q in range(EXECUTION_STEPS):
        for key, amount in _route_progress_values(
            context, model, C0_CONFIGURATION, q
        ).items():
            route_increment[key] = route_increment.get(key, 0.0) + float(amount)
    next_state = SteelRollingState(
        episode_id=state.episode_id,
        configuration_id=C0_CONFIGURATION,
        inventory_overrides=_inventory_overrides(model, C0_CONFIGURATION, last),
        cumulative_production_t=float(state.cumulative_production_t) + produced,
        executed_hours=int(state.executed_hours) + 24,
        executed_intervals=int(state.executed_intervals) + EXECUTION_STEPS,
        last_executed_timestamp_utc=str(last_timestamp_utc),
        cumulative_route_progress_t={
            key: float(state.cumulative_route_progress_t.get(key, 0.0))
            + float(route_increment.get(key, 0.0))
            for key in set(state.cumulative_route_progress_t) | set(route_increment)
        },
        temporal_contract_version=C0_TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        last_continuous_rate_t_h={
            asset: _component_value(model, asset, last) / DT
            for asset in C0_CONTINUOUS_ASSETS
        },
        cumulative_external_scrap_to_bof_t=(
            float(state.cumulative_external_scrap_to_bof_t)
            + sum(
                _component_value(model, "external_scrap_to_bof_t", q)
                for q in range(EXECUTION_STEPS)
            )
        ),
        cumulative_internal_scrap_to_bof_t=(
            float(state.cumulative_internal_scrap_to_bof_t)
            + sum(
                _component_value(model, "internal_scrap_to_bof_t", q)
                for q in range(EXECUTION_STEPS)
            )
        ),
        pefa_last_output_t_h=(
            _component_value(model, "pefa_pellet_output_t", last) / DT
        ),
        pellet_inventory_t=_component_value(model, "pellet_inventory", last),
        hsm_last_input_t_h=_component_value(model, "hot_strip_mill", last) / DT,
    )
    return next_state


def c0_dispatch_rows(
    model: Any,
    state: SteelRollingState,
    *,
    strategy_id: str,
    day_index: int,
    prices: Sequence[float],
    optimisation_prices: Sequence[float],
    start_utc: datetime,
    week_id: str = "high_volatility",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    capacity = {
        name: float(value(getattr(model, name)[0].upper))
        for name in (
            "coke_capacity",
            "sinter_capacity",
            "hot_iron_capacity",
            "cold_slab_capacity",
            "pellet_capacity",
        )
    }
    for q in range(EXECUTION_STEPS):
        rows.append(
            {
                "configuration": "C0",
                "strategy_id": strategy_id,
                "week_id": week_id,
                "day_index": day_index,
                "interval": q,
                "timestamp_utc": (start_utc + timedelta(minutes=15 * q)).isoformat(),
                "electricity_price_eur_per_mwh": float(prices[q]),
                "optimisation_electricity_price_eur_per_mwh": float(
                    optimisation_prices[q]
                ),
                "coking_plant_1_t_h": _component_value(model, "coking_plant_1", q) / DT,
                "coking_plant_2_t_h": _component_value(model, "coking_plant_2", q) / DT,
                "sintering_plant_t_h": _component_value(model, "sintering_plant", q) / DT,
                "blast_furnace_6_t_h": _component_value(model, "blast_furnace_6", q) / DT,
                "blast_furnace_7_t_h": _component_value(model, "blast_furnace_7", q) / DT,
                "pefa_pellet_output_t_h": _component_value(model, "pefa_pellet_output_t", q) / DT,
                "bof_liquid_steel_t_h": _component_value(model, "bof_crude_steel_output", q) / DT,
                "hsm_input_t_h": _component_value(model, "hot_strip_mill", q) / DT,
                "dsp_output_t_h": _component_value(model, "c0_dsp_final_product_output", q) / DT,
                "kgf_electricity_mw": _component_value(model, "kgf_electricity_mwh", q) / DT,
                "bf_electricity_mw": _component_value(model, "bf_electricity_mwh", q) / DT,
                "sinter_electricity_mw": _component_value(model, "sinter_electricity_mwh", q) / DT,
                "pefa_electricity_mw": _component_value(model, "pefa_electricity_mwh", q) / DT,
                "bof_electricity_mw": _component_value(model, "bof_electricity_mwh", q) / DT,
                "hsm_electricity_mw": _component_value(model, "hsm_rolling_electricity_mwh", q) / DT,
                "dsp_electricity_mw": _component_value(model, "dsp_electricity_mwh", q) / DT,
                "linde_electricity_mw": _component_value(model, "linde_total_electricity_mwh", q) / DT,
                "net_grid_import_mwh": _component_value(model, "net_grid_import_mwh", q),
                "internal_generation_mwh": _component_value(model, "total_generator_electricity_mwh", q),
                "aggregate_generator_output_mw": _component_value(model, "total_generator_electricity_mwh", q) / DT,
                "generator_named_ng_mwh": _component_value(model, "generator_named_ng_mwh", q),
                "total_named_ng_procurement_mwh": _component_value(model, "total_named_ng_procurement_mwh", q),
                "generator_total_fuel_mwh": _component_value(model, "generator_total_fuel_mwh", q),
                "bfg_generated_mwh": _component_value(model, "bfg_generated", q),
                "cog_generated_mwh": _component_value(model, "cog_generated", q),
                "bofg_generated_mwh": _component_value(model, "bofg_generated", q),
                "total_flare_mwh_lhv": sum(
                    _component_value(model, name, q)
                    for name in ("bfg_flared", "cog_flared", "bofg_flared")
                ),
                "coke_inventory_t": _component_value(model, "coke_inventory", q),
                "coke_capacity_t": capacity["coke_capacity"],
                "sinter_inventory_t": _component_value(model, "sinter_inventory", q),
                "sinter_capacity_t": capacity["sinter_capacity"],
                "hot_iron_inventory_t": _component_value(model, "hot_iron_inventory", q),
                "hot_iron_capacity_t": capacity["hot_iron_capacity"],
                        "cold_slab_inventory_t": _component_value(model, "cold_slab_inventory", q),
                        "eaf_slab_inventory_t": _component_value(model, "eaf_slab_inventory", q),
                        "shared_slab_inventory_t": _component_value(model, "cold_slab_inventory", q)
                        + _component_value(model, "eaf_slab_inventory", q),
                "cold_slab_capacity_t": capacity["cold_slab_capacity"],
                "pellet_inventory_t": _component_value(model, "pellet_inventory", q),
                "pellet_capacity_t": capacity["pellet_capacity"],
                "final_product_t": _component_value(model, "final_product_output", q),
                "coke_output_t": _component_value(model, "coke_output", q),
                "sinter_output_t": _component_value(model, "sinter_output", q),
                "hot_metal_output_t": _component_value(model, "bf_hot_iron_output", q),
                "pefa_output_t": _component_value(model, "pefa_pellet_output_t", q),
                "imported_pellets_t": _component_value(model, "imported_pellet_supply_t", q),
                "internal_pefa_pellets_to_bf_t": _component_value(
                    model, "internal_pefa_pellets_to_bf_t", q
                ),
                "internal_pefa_pellets_to_drp_t": _component_value(
                    model, "internal_pefa_pellets_to_drp_t", q
                ),
                "external_bf_pellets_to_bf_t": _component_value(
                    model, "external_bf_pellets_to_bf_t", q
                ),
                "external_dr_pellets_to_drp_t": _component_value(
                    model, "external_dr_pellets_to_drp_t", q
                ),
                "bof_liquid_steel_t": _component_value(model, "bof_crude_steel_output", q),
                "hsm_final_output_t": _component_value(model, "c0_hsm_final_product_output", q),
                "dsp_final_output_t": _component_value(model, "c0_dsp_final_product_output", q),
                "coking_coal_input_t": _component_value(model, "coking_plant_1", q)
                + _component_value(model, "coking_plant_2", q),
                "pci_input_t": _component_value(model, "bf_pci_input_t", q),
                "pefa_iron_ore_input_t": _component_value(model, "pefa_iron_ore_input_t", q),
                "drp_pellet_input_t": 0.0,
                "direct_co2_reporting_t": _component_value(model, "total_direct_co2_reporting_t", q),
                "external_scrap_to_bof_t": _component_value(model, "external_scrap_to_bof_t", q),
                "internal_scrap_to_bof_t": _component_value(model, "internal_scrap_to_bof_t", q),
                "state_before_sha256": _canonical_json_sha256(state.snapshot()),
            }
        )
    return rows


def _annualised_rows(
    frame: pd.DataFrame,
    result_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    represented_hours: int = 168,
) -> list[dict[str, Any]]:
    factor = HOURS_PER_YEAR / float(represented_hours)
    presentation = config["presentation_contract"]
    normalized_downstream = presentation["downstream_normalization"]
    rows: list[dict[str, Any]] = []
    for (configuration, strategy), data in frame.groupby(
        ["configuration", "strategy_id"]
    ):
        def total(column: str) -> float:
            return float(data[column].sum()) if column in data else 0.0

        metrics = {
            "final_product": (total("final_product_t") * factor, "t/y"),
            "net_grid_import": (total("net_grid_import_mwh") * factor, "MWh/y"),
            "internal_generation": (total("internal_generation_mwh") * factor, "MWh/y"),
            "external_scrap_to_BOF": (total("external_scrap_to_bof_t") * factor, "t/y"),
            "internal_scrap_to_BOF": (total("internal_scrap_to_bof_t") * factor, "t/y"),
            "flare": (total("total_flare_mwh_lhv") * factor, "MWh_LHV/y"),
        }
        for metric, (amount, unit) in metrics.items():
            rows.append(
                {
                    "configuration": configuration,
                    "strategy_id": strategy,
                    "metric": metric,
                    "week_value": amount / factor,
                    "annual_equivalent": amount,
                    "unit": unit,
                    "period_classification": "representative_period_annualised",
                    "represented_hours": represented_hours,
                    "denominator": "one_selected_high_volatility_week",
                    "comparable": "partially_comparable",
                }
            )
    for result in result_rows:
        rows.append(
            {
                "configuration": result["configuration"],
                "strategy_id": result["strategy_id"],
                "metric": "represented_procurement_cost",
                "week_value": float(result["objective_eur"]),
                "annual_equivalent": float(result["objective_eur"]) * factor,
                "unit": "EUR/y",
                "period_classification": "representative_period_annualised",
                "represented_hours": represented_hours,
                "denominator": "one_selected_high_volatility_week",
                "comparable": "comparable_between_tested_strategies_only",
            }
        )
    production_anchors = {
        "C0": {
            "final_product": (
                "final_product_t",
                normalized_downstream["C0"]["raw_saleable_output_t_y"],
                presentation["canonical_final_product_t_y"],
            ),
            "sinter_output": ("sinter_output_t", 3_700_000.0, 3_468_750.0),
            "pefa_output": ("pefa_output_t", 4_600_000.0, 4_312_500.0),
            "pellet_import": (
                "external_bf_pellets_to_bf_t",
                1_500_000.0,
                1_406_250.0,
            ),
            "coke_output": ("coke_output_t", 1_800_000.0, 1_687_500.0),
            "hot_metal_output": ("hot_metal_output_t", 6_300_000.0, 5_906_250.0),
            "bof_liquid_steel": ("bof_liquid_steel_t", 7_200_000.0, 6_750_000.0),
            "hsm_final_output": (
                "hsm_final_output_t",
                5_400_000.0,
                normalized_downstream["C0"]["hsm_final_output_t_y"],
            ),
            "dsp_final_output": (
                "dsp_final_output_t",
                1_500_000.0,
                normalized_downstream["C0"]["dsp_final_output_t_y"],
            ),
            "site_scrap": ("site_scrap_t", 1_500_000.0, 1_406_250.0),
        },
        "C1": {
            "final_product": (
                "final_product_t",
                normalized_downstream["C1"]["raw_saleable_output_t_y"],
                presentation["canonical_final_product_t_y"],
            ),
            "sinter_output": ("sinter_output_t", 2_800_000.0, 2_800_000.0),
            "pefa_output": ("pefa_output_t", 5_000_000.0, 5_000_000.0),
            "pellet_import": (
                "external_dr_pellets_to_drp_t",
                200_000.0,
                200_000.0,
            ),
            "coke_output": ("coke_output_t", 1_000_000.0, 1_000_000.0),
            "hot_metal_output": ("hot_metal_output_t", 2_800_000.0, 2_800_000.0),
            "bof_liquid_steel": ("bof_liquid_steel_t", 3_400_000.0, 3_400_000.0),
            "drp_dri_output": ("drp_dri_output_t", 2_800_000.0, 2_800_000.0),
            "eaf_liquid_steel": ("eaf_liquid_steel_t", 3_300_000.0, 3_232_012.260),
            "hsm_final_output": (
                "hsm_final_output_t",
                5_500_000.0,
                normalized_downstream["C1"]["hsm_final_output_t_y"],
            ),
            "dsp_final_output": (
                "dsp_final_output_t",
                1_500_000.0,
                normalized_downstream["C1"]["dsp_final_output_t_y"],
            ),
            "site_scrap": ("site_scrap_t", 1_900_000.0, 1_900_000.0),
        },
    }
    service_contract = {
        row["record_id"]: row
        for row in csv.DictReader(
            (
                REPO_ROOT
                / "data/03_Optimisation/inputs/assets/steel/S4/"
                "c5_phase5e_source_backed_anchor_contract/"
                "source_backed_annual_service_contract.csv"
            ).open(encoding="utf-8")
        )
    }
    service_ids = {
        "C0": (
            "c0_ng_total",
            "c0_electricity_total",
            "c0_electricity_operating_total",
            "c0_scope1_total",
            "c0_wag_total",
            "c0_generator_fuel_total",
            "c0_generator_output",
            "c0_coal_energy",
        ),
        "C1": (
            "c1_ng_total",
            "c1_electricity_total",
            "c1_electricity_operating_total",
            "c1_scope1_total",
            "c1_wag_total",
            "c1_generator_fuel_total",
            "c1_generator_output",
            "c1_coal_energy",
        ),
    }
    for (configuration, strategy), data in frame.groupby(
        ["configuration", "strategy_id"]
    ):
        data = data.copy()
        def series(column: str) -> pd.Series:
            if column in data:
                return data[column].fillna(0.0)
            return pd.Series(0.0, index=data.index)

        data["site_scrap_t"] = (
            series("external_scrap_to_bof_t")
            + series("internal_scrap_to_bof_t")
            + series("external_scrap_to_eaf_t")
            + series("internal_scrap_to_eaf_t")
        )
        for metric, (column, raw_source, comparison_source) in production_anchors[
            configuration
        ].items():
            model_value = float(data[column].fillna(0.0).sum()) * factor
            delta = model_value - comparison_source
            rows.append(
                {
                    "configuration": configuration,
                    "strategy_id": strategy,
                    "metric": metric,
                    "anchor_family": "production_material",
                    "source_value_raw": raw_source,
                    "source_value_comparison": comparison_source,
                    "model_annual_equivalent": model_value,
                    "absolute_deviation": delta,
                    "relative_deviation": delta / comparison_source,
                    "unit": "t/y",
                    "model_coverage": "represented_route",
                    "boundary_denominator": (
                        presentation["headline_denominator"]
                        if metric in {"final_product", "hsm_final_output", "dsp_final_output"}
                        else (
                            "scaled_6.75Mt_C0_route_contract"
                            if configuration == "C0"
                            else "active_C1_route_contract"
                        )
                    ),
                    "comparability": "comparable",
                    "period_classification": "representative_period_annualised",
                    "represented_hours": represented_hours,
                }
            )
        energy_model = {
            "natural_gas": float(data["total_named_ng_procurement_mwh"].fillna(0.0).sum()) * factor * 3.6e-6,
            "electricity": float((data["net_grid_import_mwh"].fillna(0.0) + data["internal_generation_mwh"].fillna(0.0)).sum()) * factor * 3.6e-6,
            "scope1_co2": float(data["direct_co2_reporting_t"].fillna(0.0).sum()) * factor / 1_000_000.0,
            "wag_production": float((data["bfg_generated_mwh"].fillna(0.0) + data["cog_generated_mwh"].fillna(0.0) + data["bofg_generated_mwh"].fillna(0.0)).sum()) * factor * 3.6e-6,
            "generator_fuel": float(data["generator_total_fuel_mwh"].fillna(0.0).sum()) * factor * 3.6e-6,
            "generator_electricity": float(data["internal_generation_mwh"].fillna(0.0).sum()) * factor * 3.6e-6,
        }
        for record_id in service_ids[configuration]:
            source = service_contract[record_id]
            family = source["family"]
            model_value = energy_model.get(family)
            source_value = float(source["value"])
            comparable = model_value is not None and family not in {"scope1_co2"}
            rows.append(
                {
                    "configuration": configuration,
                    "strategy_id": strategy,
                    "metric": record_id,
                    "anchor_family": family,
                    "source_value_raw": source_value,
                    "source_value_comparison": source_value,
                    "model_annual_equivalent": model_value if model_value is not None else "",
                    "absolute_deviation": (
                        model_value - source_value if comparable else ""
                    ),
                    "relative_deviation": (
                        (model_value - source_value) / source_value
                        if comparable
                        else ""
                    ),
                    "unit": source["unit"],
                    "model_coverage": (
                        "represented_partial_boundary"
                        if family in {"scope1_co2", "coal_energy"}
                        else "represented_operational_boundary"
                    ),
                    "boundary_denominator": source["component"],
                    "comparability": (
                        "partially_comparable" if model_value is not None else "not_comparable"
                    ),
                    "period_classification": "representative_period_annualised",
                    "represented_hours": represented_hours,
                }
            )
    return rows


def _plant_response_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    assets = {
        "C0": {
            "KGF1": "coking_plant_1_t_h",
            "KGF2": "coking_plant_2_t_h",
            "SiFa": "sintering_plant_t_h",
            "BF6": "blast_furnace_6_t_h",
            "BF7": "blast_furnace_7_t_h",
            "PeFa": "pefa_pellet_output_t_h",
            "BOF": "bof_electricity_mw",
            "HSM": "hsm_electricity_mw",
            "DSP": "dsp_electricity_mw",
            "Linde": "linde_electricity_mw",
            "aggregate_generator": "aggregate_generator_output_mw",
        },
        "C1": {
            "KGF1": "coking_plant_1_t_h",
            "KGF2": None,
            "SiFa": "sintering_plant_t_h",
            "BF6": "blast_furnace_6_t_h",
            "BF7": None,
            "PeFa": "pefa_pellet_output_t_h",
            "BOF": "bof_electricity_mw",
            "HSM": "hsm_electricity_mw",
            "DSP": "dsp_electricity_mw",
            "Linde": "linde_electricity_mw",
            "EAF": "eaf_electricity_mw",
            "DRP": "drp_pellet_input_t_h",
            "VN25": "vn25_output_mw",
        },
    }
    rows: list[dict[str, Any]] = []
    for configuration, mapping in assets.items():
        pf = frame[
            (frame["configuration"] == configuration)
            & (frame["strategy_id"] == "perfect_foresight_D")
        ].reset_index(drop=True)
        pi = frame[
            (frame["configuration"] == configuration)
            & (frame["strategy_id"] == "price_insensitive")
        ].reset_index(drop=True)
        price = pf["electricity_price_eur_per_mwh"].astype(float)
        for asset, column in mapping.items():
            if column is None or column not in pf or pf[column].isna().all():
                rows.append(
                    {
                        "configuration": configuration,
                        "asset": asset,
                        "status": "not_present",
                    }
                )
                continue
            pf_values = pf[column].astype(float)
            pi_values = pi[column].astype(float)
            delta = pf_values - pi_values
            cheap = price <= price.quantile(0.25)
            expensive = price >= price.quantile(0.75)
            status = "represented"
            if float(delta.std()) <= 1e-12:
                status = "constant_no_paired_variance"
            rows.append(
                {
                    "configuration": configuration,
                    "asset": asset,
                    "status": status,
                    "pf_min": float(pf_values.min()),
                    "pf_max": float(pf_values.max()),
                    "pi_min": float(pi_values.min()),
                    "pi_max": float(pi_values.max()),
                    "correlation_price_pf_minus_pi_qh": (
                        float(delta.corr(price)) if status == "represented" else ""
                    ),
                    "cheap_q25_minus_expensive_q25_pf_minus_pi": float(
                        delta[cheap].mean() - delta[expensive].mean()
                    ),
                    "mean_absolute_pf_minus_pi": float(delta.abs().mean()),
                }
            )
    return rows


def _plot_package(
    output: Path,
    frame: pd.DataFrame,
    *,
    save_pdf: bool = False,
) -> list[str]:
    apply_visual_style()
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    paths: list[str] = []

    def save(fig: Any, name: str) -> None:
        path = figures / name
        save_figure(fig, path, save_pdf=save_pdf)
        plt.close(fig)
        paths.append(str(path.with_suffix(".png").relative_to(REPO_ROOT)))

    for (configuration, strategy), data in frame.groupby(
        ["configuration", "strategy_id"], sort=True
    ):
        data = data.sort_values("timestamp_utc").iloc[:288]
        x = range(len(data))
        fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(x, data["electricity_price_eur_per_mwh"], color=COLORS["actual"])
        axes[0].set_ylabel("EUR/MWh")
        grid = data["net_grid_import_mwh"] / DT
        generation = data["internal_generation_mwh"] / DT
        axes[1].stackplot(
            x,
            generation,
            grid,
            labels=(f"generation (avg {generation.mean():.1f} MW)", f"net import (avg {grid.mean():.1f} MW)"),
            colors=(COLORS["third_model"], COLORS["grid"]),
            alpha=0.75,
        )
        axes[1].set_ylabel("MW")
        axes[1].legend(ncol=2)
        hsm_final = data["hsm_final_output_t"] / DT
        dsp_final = data["dsp_final_output_t"] / DT
        axes[2].plot(x, hsm_final, label="HSM final", color=COLORS["main_model"])
        axes[2].plot(x, dsp_final, label="DSP final", color=COLORS["third_model"])
        axes[2].set_ylabel("t/h final product")
        axes[2].legend(ncol=2)
        axes[2].set_xlabel("quarter-hour, first three days")
        fig.suptitle(f"{configuration} {strategy} - high-volatility week")
        save(fig, f"week-dashboard-{configuration.lower()}-{strategy}")

    plant_columns = {
        "KGF1": "coking_plant_1_t_h",
        "KGF2": "coking_plant_2_t_h",
        "SiFa": "sintering_plant_t_h",
        "BF6": "blast_furnace_6_t_h",
        "BF7": "blast_furnace_7_t_h",
        "PeFa": "pefa_pellet_output_t_h",
    }
    c0 = frame[(frame["configuration"] == "C0") & (frame["strategy_id"] == "perfect_foresight_D")]
    plant_bounds = {
        "KGF1": (120.0, 140.0),
        "KGF2": (120.0, 140.0),
        "SiFa": (160.0, 320.0),
        "BF6": (120.0, 170.0),
        "BF7": (184.61538462, 261.53846154),
        "PeFa": (465.75, 513.1875),
    }
    fig, axes = plt.subplots(6, 1, figsize=(12, 14), sharex=True)
    for axis, (label, column) in zip(axes, plant_columns.items()):
        axis.plot(c0[column].to_numpy(), label=label)
        lower, upper = plant_bounds[label]
        axis.axhline(lower, color=COLORS["benchmark"], linewidth=0.7, linestyle="--")
        axis.axhline(upper, color=COLORS["benchmark"], linewidth=0.7, linestyle="--")
        axis.set_ylim(lower - 0.05 * (upper - lower), upper + 0.05 * (upper - lower))
        axis.set_ylabel("t/h")
        axis.legend(title=f"range {lower:.1f}-{upper:.1f}", loc="upper right")
    axes[-1].set_xlabel("quarter-hour")
    fig.suptitle("C0 continuous plant capacities - perfect foresight D")
    save(fig, "c0-continuous-plant-capacities")

    response_rows = {
        "C0": {
            "KGF1": "coking_plant_1_t_h",
            "KGF2": "coking_plant_2_t_h",
            "SiFa": "sintering_plant_t_h",
            "BF6": "blast_furnace_6_t_h",
            "BF7": "blast_furnace_7_t_h",
            "PeFa": "pefa_pellet_output_t_h",
            "BOF": "bof_electricity_mw",
            "HSM": "hsm_electricity_mw",
            "DSP": "dsp_electricity_mw",
            "Linde": "linde_electricity_mw",
            "Aggregate generator": "aggregate_generator_output_mw",
        },
        "C1": {
            "KGF1": "coking_plant_1_t_h",
            "KGF2": None,
            "SiFa": "sintering_plant_t_h",
            "BF6": "blast_furnace_6_t_h",
            "BF7": None,
            "PeFa": "pefa_pellet_output_t_h",
            "BOF": "bof_electricity_mw",
            "HSM": "hsm_electricity_mw",
            "DSP": "dsp_electricity_mw",
            "Linde": "linde_electricity_mw",
            "EAF": "eaf_electricity_mw",
            "DRP": "drp_pellet_input_t_h",
            "VN25": "vn25_output_mw",
        },
    }
    for configuration, assets in response_rows.items():
        pf = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")].reset_index(drop=True)
        pi = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "price_insensitive")].reset_index(drop=True)
        labels = list(assets)
        correlations: list[list[float]] = []
        quartile_shift: list[list[float]] = []
        statuses: list[str] = []
        price = pf["electricity_price_eur_per_mwh"]
        for label in labels:
            column = assets[label]
            if column is None or column not in pf or column not in pi:
                correlations.append([math.nan, math.nan])
                quartile_shift.append([math.nan, math.nan])
                statuses.append("not present")
                continue
            delta = pf[column].astype(float) - pi[column].astype(float)
            hourly_delta = delta.groupby(delta.index // 4).mean()
            hourly_price = price.groupby(price.index // 4).mean()
            if delta.std() <= 1e-12:
                correlations.append([math.nan, math.nan])
                quartile_shift.append([0.0, 0.0])
                statuses.append("constant/no variance")
                continue
            statuses.append("represented")
            correlation_values: list[float] = []
            shift_values: list[float] = []
            for local_delta, local_price in (
                (delta, price),
                (hourly_delta, hourly_price),
            ):
                cheap = local_price <= local_price.quantile(0.25)
                expensive = local_price >= local_price.quantile(0.75)
                correlation_values.append(float(local_delta.corr(local_price)))
                shift_values.append(
                    float(local_delta[cheap].mean() - local_delta[expensive].mean())
                )
            correlations.append(correlation_values)
            quartile_shift.append(shift_values)
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        for axis, values, title in (
            (axes[0], correlations, "corr(price, PF-PI)"),
            (axes[1], quartile_shift, "PF-PI cheap Q25 minus expensive Q25"),
        ):
            image = axis.imshow(values, aspect="auto", vmin=-1 if axis is axes[0] else None, vmax=1 if axis is axes[0] else None)
            axis.set_yticks(range(len(labels)), labels)
            axis.set_xticks([0, 1], ["QH", "H"])
            axis.set_title(title)
            fig.colorbar(image, ax=axis, shrink=0.7)
            for index, pair in enumerate(values):
                for column_index, number in enumerate(pair):
                    text = (
                        statuses[index]
                        if math.isnan(number)
                        else f"{number:.2f}"
                    )
                    axis.text(column_index, index, text, ha="center", va="center")
        fig.suptitle(f"{configuration} paired price response - high volatility")
        save(fig, f"paired-price-response-{configuration.lower()}-high-volatility")

    for configuration in ("C0", "C1"):
        data = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")]
        inventory_pairs = [
            ("coke_inventory_t", "coke_capacity_t", "coke"),
            ("sinter_inventory_t", "sinter_capacity_t", "sinter"),
            ("hot_iron_inventory_t", "hot_iron_capacity_t", "hot iron"),
            ("cold_slab_inventory_t", "cold_slab_capacity_t", "cold slab"),
            ("eaf_slab_inventory_t", "cold_slab_capacity_t", "EAF-origin slab"),
            ("pellet_inventory_t", "pellet_capacity_t", "pellets"),
            ("dri_inventory_t", "dri_capacity_t", "DRI"),
        ]
        fig, ax = plt.subplots(figsize=(12, 5))
        for inventory, capacity, label in inventory_pairs:
            if inventory in data and capacity in data and data[capacity].notna().any():
                ax.plot(100.0 * data[inventory] / data[capacity], label=label)
        ax.set_ylabel("state of charge (%)")
        ax.set_xlabel("quarter-hour")
        ax.legend(ncol=3)
        ax.set_title(f"{configuration} storage utilisation - high volatility")
        save(fig, f"storage-utilisation-{configuration.lower()}")

    for configuration in ("C0", "C1"):
        data = frame[
            (frame["configuration"] == configuration)
            & (frame["strategy_id"] == "perfect_foresight_D")
        ].reset_index(drop=True)
        generation = data["internal_generation_mwh"].astype(float) / DT
        grid = data["net_grid_import_mwh"].astype(float) / DT
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.stackplot(
            range(len(data)),
            generation,
            grid,
            labels=(
                f"internal generation (avg {generation.mean():.1f} MW)",
                f"net import (avg {grid.mean():.1f} MW)",
            ),
            colors=(COLORS["third_model"], COLORS["grid"]),
            alpha=0.75,
        )
        ax.set_ylabel("site electricity supply (MW)")
        ax.set_xlabel("quarter-hour")
        ax.legend(ncol=2)
        ax.set_title(f"{configuration} site load supplied by generation and net import")
        save(fig, f"stacked-site-load-{configuration.lower()}")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for axis, configuration in zip(axes, ("C0", "C1")):
        pf = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")].reset_index(drop=True).iloc[:288]
        pi = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "price_insensitive")].reset_index(drop=True).iloc[:288]
        axis.plot(pf["hsm_electricity_mw"] - pi["hsm_electricity_mw"], label=f"{configuration} PF-PI HSM")
        axis.axhline(0.0, color=COLORS["benchmark"], linewidth=0.8)
        axis.set_ylabel("delta MW")
        axis.legend(loc="upper right")
    axes[-1].set_xlabel("quarter-hour, first three days")
    fig.suptitle("HSM electricity difference versus price-insensitive operation")
    save(fig, "hsm-delta-vs-price-insensitive-high-volatility")

    c1_pf = frame[(frame["configuration"] == "C1") & (frame["strategy_id"] == "perfect_foresight_D")].reset_index(drop=True).iloc[:288]
    c1_pi = frame[(frame["configuration"] == "C1") & (frame["strategy_id"] == "price_insensitive")].reset_index(drop=True).iloc[:288]
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(c1_pf["eaf_electricity_mw"] - c1_pi["eaf_electricity_mw"], color=COLORS["main_model"])
    axes[0].axhline(0.0, color=COLORS["benchmark"], linewidth=0.8)
    axes[0].set_ylabel("EAF delta MW")
    axes[1].plot(c1_pf["electricity_price_eur_per_mwh"], color=COLORS["actual"])
    axes[1].set_ylabel("EUR/MWh")
    axes[1].set_xlabel("quarter-hour, first three days")
    fig.suptitle("C1 EAF electricity difference versus price-insensitive operation")
    save(fig, "eaf-delta-vs-price-insensitive-high-volatility")

    materials = []
    for configuration in ("C0", "C1"):
        data = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")]
        external_eaf = (
            data["external_scrap_to_eaf_t"].fillna(0.0)
            if "external_scrap_to_eaf_t" in data
            else pd.Series(0.0, index=data.index)
        )
        internal_eaf = (
            data["internal_scrap_to_eaf_t"].fillna(0.0)
            if "internal_scrap_to_eaf_t" in data
            else pd.Series(0.0, index=data.index)
        )
        materials.append(
            {
                "configuration": configuration,
                "external_scrap": float(data["external_scrap_to_bof_t"].fillna(0.0).sum() + external_eaf.sum()),
                "internal_scrap": float(data["internal_scrap_to_bof_t"].fillna(0.0).sum() + internal_eaf.sum()),
                "pellet_import": float(data["imported_pellets_t"].fillna(0.0).sum()),
            }
        )
    material_frame = pd.DataFrame(materials).set_index("configuration") / 1_000.0
    fig, ax = plt.subplots(figsize=(9, 4))
    material_frame.plot.bar(ax=ax)
    ax.set_ylabel("kt in selected week")
    ax.set_title("Material origins on common weekly support")
    save(fig, "c0-c1-material-origin-summary")

    economic_rows = []
    for (configuration, strategy), data in frame.groupby(["configuration", "strategy_id"]):
        economic_rows.append(
            {
                "configuration": configuration,
                "strategy": strategy,
                "grid_MWh": float(data["net_grid_import_mwh"].sum()),
                "generation_MWh": float(data["internal_generation_mwh"].sum()),
            }
        )
    economic_frame = pd.DataFrame(economic_rows)
    fig, ax = plt.subplots(figsize=(10, 4))
    economic_frame.pivot(index="configuration", columns="strategy", values="grid_MWh").plot.bar(ax=ax)
    ax.set_ylabel("net grid import (MWh/week)")
    ax.set_title("PF and price-insensitive electricity comparison")
    save(fig, "economic-energy-comparison")

    anchor_specs = {
        "C0": {"final_product_t": 6_750_000.0, "sinter_output_t": 3_468_750.0, "pefa_output_t": 4_312_500.0, "coke_output_t": 1_687_500.0},
        "C1": {"final_product_t": 6_750_000.0, "sinter_output_t": 2_800_000.0, "pefa_output_t": 5_000_000.0, "coke_output_t": 1_000_000.0},
    }
    fig, ax = plt.subplots(figsize=(10, 4))
    width = 0.35
    labels = ["final", "sinter", "PeFa", "coke"]
    for offset, configuration in ((-width / 2, "C0"), (width / 2, "C1")):
        data = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")]
        ratios = [
            float(data[column].fillna(0.0).sum()) * HOURS_PER_YEAR / 168.0 / anchor
            for column, anchor in anchor_specs[configuration].items()
        ]
        ax.bar([index + offset for index in range(len(labels))], ratios, width=width, label=configuration)
    ax.axhline(1.0, color=COLORS["benchmark"], linewidth=0.8)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_ylabel("annualised model / comparison anchor")
    ax.legend()
    ax.set_title("Production-anchor ratios - representative week only")
    save(fig, "annualised-production-anchor-ratios")

    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for axis, configuration in zip(axes, ("C0", "C1")):
        pf = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "perfect_foresight_D")].reset_index(drop=True).iloc[:96]
        pi = frame[(frame["configuration"] == configuration) & (frame["strategy_id"] == "price_insensitive")].reset_index(drop=True).iloc[:96]
        pf_load = (pf["net_grid_import_mwh"] + pf["internal_generation_mwh"]) / DT
        pi_load = (pi["net_grid_import_mwh"] + pi["internal_generation_mwh"]) / DT
        axis.plot(pf_load, label=f"{configuration} ideal PF load")
        axis.plot(pi_load, label=f"{configuration} price-insensitive load", alpha=0.65)
        price_axis = axis.twinx()
        price_axis.plot(pf["electricity_price_eur_per_mwh"], color=COLORS["actual"], linewidth=0.8, alpha=0.55)
        axis.set_ylabel("MW")
        price_axis.set_ylabel("EUR/MWh")
        axis.legend(loc="upper left")
    axes[-1].set_xlabel("quarter-hour of example day")
    fig.suptitle("Example-day ideal demand and day-ahead price - no bidding curve")
    save(fig, "example-day-ideal-demand-and-da-price")

    package = {
        "package_version": "deterministic_plant_behaviour_figures_v4",
        "selection_policy": "default_complete_selection_unless_explicit_subset_requested",
        "figure_count": len(paths),
        "figures": paths,
        "support": {
            "period": "one selected high-volatility week",
            "strategies": ["perfect_foresight_D", "price_insensitive"],
            "granularity": "QH solved; H aggregated only for reporting",
            "common_support": True,
            "counterfactual_prices_are_observed_truth": False,
        },
    }
    _write_json(output / "figure_package" / "figure_package_manifest.json", package)
    return paths


def run_c0_temporal_validation(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "c0_high_volatility_week_v1",
    week_regime: str | None = None,
) -> dict[str, Any]:
    config = load_c0_validation_config(config_path)
    base_config = load_temporal_repair_config(REPO_ROOT / config["base_temporal_config"])
    behaviour_config = load_validation_config(REPO_ROOT / config["behaviour_validation_config"])
    _activate_c1_calibration_bundle(base_config, behaviour_config)
    output = REPO_ROOT / config["output_root"] / run_id
    if output.exists() and any(output.iterdir()):
        raise C0TemporalValidationError(f"Refusing to overwrite {output}.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "solver_logs").mkdir(exist_ok=True)
    manifest = {
        "run_id": run_id,
        "run_family_id": config["run_family_id"],
        "output_root": str(output.relative_to(REPO_ROOT)),
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "retention_status": config["retention_status"],
        "git_eligible": False,
        "temporal_contracts": {
            "C0": C0_TEMPORAL_CONTRACT_VERSION,
            "C1": base_config["temporal_contract_version"],
        },
        "calendar_contract_version": CALENDAR_CONTRACT_VERSION,
        "maintenance_hours_represented": 0,
        "annual_availability_comparable": False,
        "major_outage_certified": False,
        "expected_file_count": "90-130",
        "expected_size_mb_upper_bound": 60,
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "run_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=True), encoding="utf-8"
    )
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _write_json(
        output / "code_version.json",
        {"git_head": git_head, "git_dirty_at_run": True, "branch": "feature/steel-next-layer"},
    )

    c0_context = prepare_c0_context(config, base_config)
    c1_context = prepare_temporal_context(base_config)
    attempts: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    dispatch: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    bounded_fixes: list[dict[str, Any]] = []

    flat_state = initial_c0_state(config, episode_id="c0_flat_reference")
    flat_model, flat_result, flat_audit = solve_c0_day(
        c0_context,
        flat_state,
        config,
        (80.0,) * EXECUTION_STEPS,
        case_id="c0_flat_reference",
        output=output,
    )
    attempts.append(flat_result)
    audits.extend({"case_id": "c0_flat_reference", **row} for row in flat_audit)
    c0_reference_state = advance_c0_state(
        c0_context,
        flat_model,
        flat_state,
        last_timestamp_utc="2026-01-01T23:45:00+00:00",
    )
    validate_c0_state(c0_reference_state, config)
    flat_dispatch = c0_dispatch_rows(
        flat_model,
        flat_state,
        strategy_id="flat_reference",
        day_index=0,
        prices=(80.0,) * EXECUTION_STEPS,
        optimisation_prices=(80.0,) * EXECUTION_STEPS,
        start_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    flat_annualised = _annualised_rows(
        pd.DataFrame(flat_dispatch),
        [
            {
                "configuration": "C0",
                "strategy_id": "flat_reference",
                "objective_eur": float(flat_result["incumbent_objective_eur"]),
            }
        ],
        config,
        represented_hours=24,
    )
    for row in flat_annualised:
        row["period_classification"] = "provisional_day_annualised_diagnostic"
        row["represented_hours"] = 24
        row["denominator"] = "one_flat_reference_day_not_representative_year"
    _write_csv(output / "d1_annual_operational_anchor_results.csv", flat_annualised)
    _write_json(
        output / "d1_annual_operational_anchor_gate.json",
        {
            "status": "provisional_day_diagnostic_only",
            "represented_hours": 24,
            "representative_year_claim": False,
            "physical_audit_passed": True,
        },
    )

    week_manifest, week_prices = load_representative_week_prices(behaviour_config)
    requested_regime = str(
        week_regime or config["representative_week"]["regime"]
    )
    selected = next(
        (
            row
            for row in week_manifest
            if requested_regime
            in {str(row["regime_role"]), str(row["case_id"])}
        ),
        None,
    )
    if selected is None:
        raise C0TemporalValidationError(
            f"Representative-week regime is unavailable: {requested_regime}."
        )
    week_label = str(selected["regime_role"])
    prices = week_prices[selected["case_id"]]
    week_start = datetime.fromisoformat(selected["start_date"]).replace(tzinfo=timezone.utc)
    for strategy_id in ("perfect_foresight_D", "price_insensitive"):
        state = replace(
            c0_reference_state,
            episode_id=f"c0_{week_label}__{strategy_id}",
        )
        objective_total = 0.0
        optimisation_objective_total = 0.0
        for day_index in range(1, 8):
            realised = prices[(day_index - 1) * 96 : day_index * 96]
            planning = realised if strategy_id == "perfect_foresight_D" else (80.0,) * 96
            before = state
            model, result, audit = solve_c0_day(
                c0_context,
                state,
                config,
                planning,
                case_id=f"c0_{strategy_id}_day_{day_index}",
                output=output,
            )
            attempts.append(result)
            optimisation_objective_total += float(result["incumbent_objective_eur"])
            realised_cost = float(
                value(
                    _represented_cost_expression(
                        c0_context,
                        model,
                        C0_CONFIGURATION,
                        tuple(float(item) for item in realised)
                        + tuple(0.0 for _ in range(EXECUTION_STEPS)),
                        objective_hours=range(EXECUTION_STEPS),
                    )
                )
            )
            objective_total += realised_cost
            audits.extend(
                {
                    "case_id": f"c0_{strategy_id}_day_{day_index}",
                    **row,
                }
                for row in audit
            )
            dispatch.extend(
                c0_dispatch_rows(
                    model,
                    before,
                    strategy_id=strategy_id,
                    day_index=day_index,
                    prices=realised,
                    optimisation_prices=planning,
                    start_utc=week_start + timedelta(days=day_index - 1),
                    week_id=week_label,
                )
            )
            state = advance_c0_state(
                c0_context,
                model,
                state,
                last_timestamp_utc=(
                    week_start + timedelta(days=day_index, minutes=-15)
                ).isoformat(),
            )
            validate_c0_state(state, config)
            state_rows.append(
                {
                    "configuration": "C0",
                    "strategy_id": strategy_id,
                    "day_index": day_index,
                    "state_before_sha256": _canonical_json_sha256(before.snapshot()),
                    "state_after_sha256": _canonical_json_sha256(state.snapshot()),
                    "cumulative_production_t": state.cumulative_production_t,
                    "cumulative_external_scrap_to_bof_t": state.cumulative_external_scrap_to_bof_t,
                    "cumulative_internal_scrap_to_bof_t": state.cumulative_internal_scrap_to_bof_t,
                }
            )
        result_rows.append(
            {
                "configuration": "C0",
                "strategy_id": strategy_id,
                "objective_eur": objective_total,
                "optimisation_objective_eur": optimisation_objective_total,
            }
        )

    c1_attempts: list[dict[str, Any]] = []
    c1_initial = replace(
        initial_temporal_state(base_config),
        episode_id=f"c1_{week_label}_reference",
        eaf_quota_period_id=f"c1_{week_label}_week",
        eaf_quota_target_taps=quota_period_target_taps(0),
        eaf_quota_completed_taps=0,
    )
    continuation = _calibrate_continuation(
        c1_context, c1_initial, base_config, output / "c1_calibration", c1_attempts
    )
    attempts.extend(c1_attempts)
    for strategy_id in ("perfect_foresight_D", "price_insensitive"):
        state = replace(
            c1_initial,
            episode_id=f"c1_{week_label}__{strategy_id}",
            eaf_quota_period_id=f"c1_{week_label}__{strategy_id}",
        )
        warm_model = None
        objective_total = 0.0
        optimisation_objective_total = 0.0
        for day_index in range(1, 8):
            realised = prices[(day_index - 1) * 96 : day_index * 96]
            planning = realised if strategy_id == "perfect_foresight_D" else (80.0,) * 96
            model, result, _, day_dispatch, _, checks = _solve_day(
                c1_context,
                state,
                base_config,
                behaviour_config,
                output,
                case_id=f"c1_{strategy_id}_day_{day_index}",
                experiment_type="representative_week_counterfactual",
                day_index=day_index,
                prices=planning,
                evaluation_prices=realised,
                continuation=continuation,
                remaining_days=8 - day_index,
                warm_source=warm_model,
                start_utc=week_start + timedelta(days=day_index - 1),
                attempt_rows=attempts,
                strategy_id=strategy_id,
            )
            warm_model = model
            objective_total += float(result["realised_procurement_eur"])
            optimisation_objective_total += float(
                result["optimisation_procurement_eur"]
            )
            for q, row in enumerate(day_dispatch):
                row["week_id"] = week_label
                row.update(
                    {
                        "coking_plant_2_t_h": math.nan,
                        "blast_furnace_7_t_h": math.nan,
                        "pefa_pellet_output_t_h": _component_value(model, "pefa_pellet_output_t", q) / DT,
                        "pellet_inventory_t": _component_value(model, "pellet_inventory", q),
                        # C1 has no governed physical pellet-storage capacity.
                        # Do not turn its initial inventory reference into a cap.
                        "pellet_capacity_t": math.nan,
                        "aggregate_generator_output_mw": math.nan,
                        "generator_total_fuel_mwh": _component_value(model, "generator_total_fuel_mwh", q),
                        "total_named_ng_procurement_mwh": _component_value(model, "total_named_ng_procurement_mwh", q),
                        "bfg_generated_mwh": _component_value(model, "bfg_generated", q),
                        "cog_generated_mwh": _component_value(model, "cog_generated", q),
                        "bofg_generated_mwh": _component_value(model, "bofg_generated", q),
                        "coke_output_t": _component_value(model, "coke_output", q),
                        "sinter_output_t": _component_value(model, "sinter_output", q),
                        "hot_metal_output_t": _component_value(model, "bf_hot_iron_output", q),
                        "pefa_output_t": _component_value(model, "pefa_pellet_output_t", q),
                        "imported_pellets_t": _component_value(model, "imported_pellet_supply_t", q),
                        "internal_pefa_pellets_to_bf_t": _component_value(
                            model, "internal_pefa_pellets_to_bf_t", q
                        ),
                        "internal_pefa_pellets_to_drp_t": _component_value(
                            model, "internal_pefa_pellets_to_drp_t", q
                        ),
                        "external_bf_pellets_to_bf_t": _component_value(
                            model, "external_bf_pellets_to_bf_t", q
                        ),
                        "external_dr_pellets_to_drp_t": _component_value(
                            model, "external_dr_pellets_to_drp_t", q
                        ),
                        "bof_liquid_steel_t": _component_value(model, "bof_crude_steel_output", q),
                        "hsm_final_output_t": (
                            _component_value(model, "final_product_output", q)
                            - _component_value(model, "dsp_final_product_output", q)
                        ),
                        "dsp_final_output_t": _component_value(model, "dsp_final_product_output", q),
                        "drp_dri_output_t": _component_value(model, "drp_dri_output", q),
                        "eaf_liquid_steel_t": _component_value(model, "eaf_liquid_steel_output", q),
                        "coking_coal_input_t": _component_value(
                            model,
                            (
                                "c1_adjusted_coking_coal_input_t"
                                if hasattr(model, "c1_adjusted_coking_coal_input_t")
                                else "coking_plant_1"
                            ),
                            q,
                        ),
                        "pci_input_t": _component_value(
                            model,
                            (
                                "c1_adjusted_pci_input_t"
                                if hasattr(model, "c1_adjusted_pci_input_t")
                                else "bf_pci_input_t"
                            ),
                            q,
                        ),
                        "pefa_iron_ore_input_t": _component_value(model, "pefa_iron_ore_input_t", q),
                        "drp_pellet_input_t": _component_value(model, "drp_pellet_input", q),
                        "direct_co2_reporting_t": _component_value(model, "total_direct_co2_reporting_t", q),
                        "external_scrap_to_bof_t": _component_value(model, "external_scrap_to_bof_t", q),
                        "internal_scrap_to_bof_t": _component_value(model, "internal_scrap_to_bof_t", q),
                        "external_scrap_to_eaf_t": _component_value(model, "external_scrap_to_eaf_t", q),
                        "internal_scrap_to_eaf_t": _component_value(model, "internal_scrap_to_eaf_t", q),
                    }
                )
            dispatch.extend(day_dispatch)
            audits.extend(
                {"case_id": f"c1_{strategy_id}_day_{day_index}", **row}
                for row in checks
            )
            from .s4_4c6_deterministic_temporal_repair import advance_temporal_state

            state = advance_temporal_state(
                c1_context,
                model,
                state,
                last_timestamp_utc=(
                    week_start + timedelta(days=day_index, minutes=-15)
                ).isoformat(),
            )
        result_rows.append(
            {
                "configuration": "C1",
                "strategy_id": strategy_id,
                "objective_eur": objective_total,
                "optimisation_objective_eur": optimisation_objective_total,
            }
        )

    dispatch_frame = pd.DataFrame(dispatch)
    _write_csv(output / "interval_dispatch.csv", dispatch)
    _write_csv(output / "solver_attempts.csv", attempts)
    _write_json(output / "solver_attempts.json", attempts)
    _write_csv(output / "physical_audit.csv", audits)
    _write_csv(output / "state_handoff_audit.csv", state_rows)
    if not bounded_fixes:
        bounded_fixes.append(
            {
                "iteration": 0,
                "trigger": "none",
                "old_value": "",
                "new_value": "",
                "affected_kpi": "none",
                "source_status": "no_bounded_repair_required",
                "before_result": "",
                "after_result": "",
            }
        )
    _write_csv(output / "c0_bounded_fix_ledger.csv", bounded_fixes)
    response_metrics = _plant_response_metrics(dispatch_frame)
    _write_csv(output / "plant_response_metrics.csv", response_metrics)
    _write_csv(output / "temporal_kpis.csv", response_metrics)
    annualised = _annualised_rows(dispatch_frame, result_rows, config)
    _write_csv(output / "annual_operational_anchor_results.csv", annualised)
    delta_rows = [
        {
            **row,
            "last_accepted_baseline_value": "",
            "delta_vs_last_accepted": "",
            "baseline_status": "not_available_for_new_C0_temporal_contract",
        }
        for row in annualised
        if row.get("anchor_family")
    ]
    _write_csv(output / "annual_anchor_delta_vs_last_accepted.csv", delta_rows)
    _write_json(
        output / "annual_operational_anchor_gate.json",
        {
            "status": "representative_period_annualised_anchor_coverage_partial",
            "represented_hours": 168,
            "calendar_coverage": f"one_selected_{week_label}_week",
            "full_year_certified": False,
            "constraints_or_objective_use_anchors": False,
            "last_accepted_C0_temporal_baseline_available": False,
        },
    )
    _write_csv(output / "economic_comparison.csv", result_rows)
    figure_formats = tuple(config["presentation_contract"]["figure_formats"])
    figure_paths = _plot_package(
        output,
        dispatch_frame,
        save_pdf="pdf" in figure_formats,
    )
    hard_failure = any(
        row.get("passed") is False or row.get("status") == "fail" for row in audits
    )
    decision = (
        "needs_bounded_fix"
        if hard_failure
        else "c0_example_week_behaviour_pass_anchor_coverage_partial"
    )
    gate = {
        "decision": decision,
        "flat_reference_passed": True,
        "week_solve_count": 28,
        "bounded_repair_iterations_used": 0,
        "annual_anchor_status": "representative_period_annualised_not_full_year",
        "figure_count": len(figure_paths),
        "figure_formats": list(figure_formats),
        "presentation_denominator": config["presentation_contract"][
            "headline_denominator"
        ],
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "gate_decision.json", gate)
    _write_json(
        output / "run_summary.json",
        {**gate, "output_root": str(output.relative_to(REPO_ROOT))},
    )
    _write_json(
        output / "warnings_and_limitations.json",
        {
            "kgf2_bf7": "controlled symmetry assumption",
            "c0_bf_burden": "annual reconciliation, not full technology recipe",
            "coke_anchor": "anchor-derived C0 development reconciliation; technical minimum remains unverified",
            "presentation_denominator": config["presentation_contract"][
                "headline_denominator"
            ],
            "annualisation": "one high-volatility week is not a representative year",
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- KGF2 and BF7 dynamics use the governed symmetry assumption.\n"
        "- The C0 BF burden is an annual reconciliation, not a full burden recipe.\n"
        "- KGF1 and KGF2 use an anchor-derived 120-140 t/h development envelope, not a sourced technical capacity range; both remain at the lower envelope in this week.\n"
        "- Annual values are annualised from one selected high-volatility week and do not certify a representative year.\n"
        "- The ideal-demand figure is not a bidding curve.\n"
        "- No DAM, mFRR, stochastic, S10, ETS-objective or four-week solve was run.\n",
        encoding="utf-8",
    )
    _write_json(
        output / "input_manifest.json",
        {
            "C0_config": str(Path(config_path).resolve()),
            "C1_config": str((REPO_ROOT / config["base_temporal_config"]).resolve()),
            "behaviour_config": str((REPO_ROOT / config["behaviour_validation_config"]).resolve()),
            "selected_price_case": selected,
            "selected_regime": week_label,
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": run_id,
            "decision": decision,
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "git_eligible": False,
        },
    )
    _write_csv(
        output / "metrics_summary.csv",
        [
            {"metric": "solve_attempts", "value": len(attempts), "unit": "count"},
            {"metric": "solver_runtime", "value": sum(float(row.get("runtime_seconds", 0.0)) for row in attempts), "unit": "s"},
            {"metric": "figure_count", "value": len(figure_paths), "unit": "count"},
            {"metric": "bounded_repairs", "value": 0, "unit": "count"},
        ],
    )
    return gate


__all__ = [
    "C0_TEMPORAL_CONTRACT_VERSION",
    "C0TemporalValidationError",
    "audit_c0_incumbent",
    "build_c0_temporal_model",
    "initial_c0_state",
    "load_c0_validation_config",
    "prepare_c0_context",
    "run_c0_temporal_validation",
    "validate_c0_state",
]
