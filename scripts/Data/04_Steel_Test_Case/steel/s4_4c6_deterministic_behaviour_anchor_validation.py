"""Deterministic C1 plant-behaviour and partial-year anchor validation.

This module orchestrates the active shared temporal builder.  It does not copy
or alter plant physics, and annual anchors remain reporting-only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import pandas as pd
import yaml
from pyomo.environ import Var, value

from visual_style import COLORS, apply_visual_style, save_figure

from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    C1_CONFIGURATION,
    _component_value,
    _represented_cost_expression,
)
from steel.s4_4c6_deterministic_temporal_repair import (
    ASSET_ON_COMPONENTS,
    CALENDAR_CONTRACT_VERSION,
    CONTINUOUS_ASSETS,
    INVENTORY_COMPONENTS,
    OBJECTIVE_MODE,
    PHYSICAL_TOLERANCE,
    TEMPORAL_CONTRACT_VERSION,
    TemporalPhysicalInfeasibility,
    TemporalRepairError,
    _canonical_json_sha256,
    _copy_adjacent_warm_start,
    _maximum_incumbent_violation,
    _last_accepted_annual_values,
    _solve_scalar_attempt,
    advance_temporal_state,
    annual_operational_anchor_rows,
    annual_anchor_delta_rows,
    build_scalar_objective_components,
    build_temporal_model,
    dynamic_daily_heat_bounds,
    energy_audit_rows,
    initial_temporal_state,
    load_temporal_repair_config,
    prepare_temporal_context,
    quota_period_target_taps,
    rate_ranges_from_config,
    round_half_up,
    run_causal_flat_year,
    scalar_reporting_kpis,
    solve_scalar_operational_model,
    state_handoff_row,
    unexpected_anchor_worsening,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c6_deterministic_behaviour_anchor_validation.yaml"
)
JUDGEMENTS = {
    "behaviour_validation_pass_anchor_coverage_partial",
    "needs_bounded_fix",
    "source_or_boundary_evidence_gap",
    "invalid_validation_run",
}

STANDARD_FIGURE_PACKAGE_VERSION = "deterministic_plant_behaviour_figures_v3"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    if not materialized:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def load_validation_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TemporalRepairError("Behaviour-validation config must be a mapping.")
    if payload.get("temporal_contract_version") != TEMPORAL_CONTRACT_VERSION:
        raise TemporalRepairError("Behaviour validation uses a stale temporal contract.")
    if payload.get("calendar_contract_version") != CALENDAR_CONTRACT_VERSION:
        raise TemporalRepairError("Behaviour validation uses a stale calendar contract.")
    if payload.get("objective_mode") != OBJECTIVE_MODE:
        raise TemporalRepairError("Behaviour validation uses a stale objective mode.")
    if payload["forbidden_scope"].get("full_four_week_matrix_authorized") is not False:
        raise TemporalRepairError("The full four-week matrix must remain unauthorized.")
    return payload


def _activate_c1_calibration_bundle(
    temporal_config: dict[str, Any], validation_config: Mapping[str, Any]
) -> None:
    bundle = validation_config.get("active_c1_calibration_bundle", {})
    repair = temporal_config["deterministic_temporal_repair"]
    if bundle.get("wag_self_use_diagnostic"):
        repair["experimental_wag_self_use_diagnostic"] = {
            "active": True,
            "classification": "non_promoted_anchor_diagnostic_no_new_process_sink",
            "vn25_carrier_caps_pj_y": {"COG": 0.0, "BOFG": 1.4},
        }
        repair["experimental_self_use_calibration"] = {
            "classification": "experimental_carrier_self_use_calibration_not_source_proven",
            "additional_cog_mwh_per_t_kgf_activity": 0.2396,
            "additional_cog_mwh_per_t_sinter": 0.2396,
            "additional_bofg_mwh_per_t_pellet": 0.00363,
        }
    if bundle.get("generator_efficiency_418"):
        repair["experimental_generator_efficiency"] = {
            "classification": "experimental_combined_generator_efficiency_not_vn25_source_truth",
            "efficiency": 0.418,
        }
    if bundle.get("process_electricity_overlay"):
        repair["experimental_process_electricity_overlay"] = {
            "classification": "experimental_proportional_process_electricity_not_source_proven",
            "mwh_per_t_activity": 0.04664,
        }
    if bundle.get("ng_service_anchor_overlay"):
        repair["experimental_ng_service_calibration"] = {
            "classification": "user_authorized_c1_origin_explicit_ng_service_calibration",
            "ironmaking_target_pj_y": 2.0,
            "ironmaking_basis_t_y": 2_800_000.0,
            "downstream_target_pj_y": 13.1,
            "downstream_basis_t_y": 6_750_000.0,
        }
    if bundle.get("coal_wag_carbon_overlay"):
        repair["experimental_coal_wag_calibration"] = {
            "classification": "user_authorized_c1_coal_completion_carrier_wag_calibration",
            "coal_procurement_multiplier": 1.28495216932074,
            "bfg_mwh_per_t_hot_metal": 1.46825396825397,
            "cog_mwh_per_t_kgf_activity": 1.78780575437936,
            "bofg_mwh_per_t_bof_steel": 0.179738562091503,
            "cog_self_use_scale": 0.942949340241867,
            "coal_anchor_t_y": 2_200_000.0,
            "coal_anchor_pj_y": 58.0,
        }


def expected_plant_response_contract(
    temporal_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    repair = temporal_config["deterministic_temporal_repair"]
    ranges = rate_ranges_from_config(temporal_config)
    dynamics = repair["plant_dynamics"]

    def row(
        asset: str,
        category: str,
        control: str,
        bounds: str,
        commitment: str,
        response: str,
        sign: str,
        scale: str,
        dynamics_rule: str,
        confounders: str,
        criterion: str,
        source: str,
    ) -> dict[str, Any]:
        return {
            "asset": asset,
            "asset_category": category,
            "control_variable": control,
            "hard_bounds": bounds,
            "commitment_or_must_run_status": commitment,
            "price_response_class": response,
            "expected_response_sign": sign,
            "expected_timescale_and_delay": scale,
            "ramps_or_setpoint_rules": dynamics_rule,
            "physical_confounders": confounders,
            "pass_fail_criteria": criterion,
            "source_or_model_contract": source,
            "fixed_before_results": True,
        }

    rows = [
        row(
            "sintering_plant",
            "continuous_thermal_process",
            "represented iron-ore feed",
            f"{ranges['sintering_plant'][0]:g}--{ranges['sintering_plant'][1]:g} t ore/h",
            "continuous must-run",
            "indirect",
            "no direct electricity-price tracking expected",
            "2 h minimum direction",
            f"<= {dynamics['sifa']['ramp_t_h_per_qh']:g} t/h per QH; no early reversal",
            "sinter inventory, BF demand, COG availability",
            "zero off intervals; bounds/ramp hold; <=12 direction reversals/day",
            "SINTER_Parameters.md; temporal plant_dynamics.sifa",
        ),
        row(
            "blast_furnace_6",
            "continuous_thermal_process",
            "represented BF activity proxy",
            f"{ranges['blast_furnace_6'][0]:g}--{ranges['blast_furnace_6'][1]:g} t activity/h",
            "continuous must-run",
            "indirect",
            "no direct electricity-price tracking expected",
            "hourly setpoint blocks",
            f"{dynamics['bf6']['setpoint_block_hours']:g} h holds; <= {dynamics['bf6']['maximum_step_t_h']:g} t/h step",
            "hot-iron inventory, BOF demand, sinter availability",
            "zero off intervals; hourly holds and step bound hold",
            "Blast_Furnace_Parameters.md; temporal plant_dynamics.bf6",
        ),
        row(
            "coking_plant_1",
            "continuous_thermal_process",
            "dry-coal feed",
            f"{ranges['coking_plant_1'][0]:.6f}--{ranges['coking_plant_1'][1]:g} t dry coal/h",
            "continuous must-run",
            "indirect",
            "no direct electricity-price tracking expected",
            "daily setpoint",
            f"{dynamics['kgf1']['setpoint_block_hours']:g} h block; <= {dynamics['kgf1']['maximum_step_t_h']:g} t/h/day",
            "coke inventory and BOF route",
            "zero off intervals; no executed-day QH cycling",
            "Coking_Plants_Parameters.md; temporal plant_dynamics.kgf1",
        ),
        row(
            "drp_pellet_input",
            "continuous_thermal_process",
            "pellet feed",
            f"{ranges['drp_pellet_input'][0]:g}--{ranges['drp_pellet_input'][1]:g} t pellets/h",
            "continuous must-run",
            "indirect",
            "may reduce load at high prices only within physical ramp/buffer limits",
            "slow continuous response",
            "active DRP ramp; no added setpoint penalty",
            "DRI inventory, EAF demand, annual pellet/scrap balance",
            "zero off intervals; not every-QH direction switching; <=12 reversals/day",
            "DRP_Parameters.md; active builder ramp",
        ),
        row(
            "basic_oxygen_furnace",
            "batch_process",
            "liquid-steel output",
            "active builder recipe/capacity",
            "batch-equivalent",
            "indirect",
            "no free QH price chasing",
            "batch/material timescale",
            "no invented ramp; physical recipe and route balance",
            "hot iron, scrap origins, downstream routes",
            "material balance exact; rate changes on <95% of QH transitions",
            "BOF_OSF_Parameters.md; unified builder",
        ),
        row(
            "hot_strip_mill",
            "batch_process",
            "slab input",
            "active builder capacity",
            "bounded downstream",
            "indirect",
            "no free QH price chasing",
            "material/batch timescale",
            "reporting-only until source-backed batch contract",
            "cold-slab inventory, imported slab, route mix",
            "route balance exact; rate changes on <95% of QH transitions",
            "HSM_Parameters.md; unified builder",
        ),
        row(
            "direct_sheet_plant",
            "batch_process",
            "final coil output",
            "active builder capacity",
            "bounded downstream",
            "indirect",
            "no free QH price chasing",
            "material/batch timescale",
            "reporting-only until source-backed batch contract",
            "BOF/EAF origins and annual DSP route",
            "origin/route balance exact; rate changes on <95% of QH transitions",
            "DSP_Parameters.md; unified builder",
        ),
        row(
            "eaf",
            "batch_process",
            "heat starts and taps",
            "dynamic calendar/carry/quota band",
            "single-furnace occupancy",
            "direct",
            "starts shift toward lower execution-day prices",
            "45-minute heat cycle with carry-in",
            "two melt QH plus one tap/turnaround QH",
            "quota, occupancy, DRI/scrap and week recoverability",
            "occupancy and dynamic bounds exact; week target closes",
            "EAF_Parameters.md; temporal EAF heat contract",
        ),
        row(
            "vn25",
            "generator_or_utility",
            "electricity output and fuel allocation",
            "175--350 MW",
            "continuous development availability",
            "direct via avoided grid procurement",
            "direction follows active marginal WAG/NG/grid cost",
            "quarter-hour ramped",
            "<=52.5 MW change per QH including handoff",
            "carrier-specific WAG, gas-volume cap and named NG",
            "bounds/ramp exact; no avoidable eligible-WAG flare plus named NG",
            "IJ01_VN25_GENERATORS_Parameters.md; user-authorized development policy",
        ),
        row(
            "ij01",
            "generator_or_utility",
            "electricity/fuel",
            "exactly zero",
            "forced off",
            "not_price_responsive",
            "none",
            "none",
            "all fuel/output variables fixed zero",
            "none",
            "output, WAG and named NG all zero",
            "normal_operation_vn25_available model contract",
        ),
        row(
            "material_buffers",
            "buffers_and_inventories",
            "inventory level",
            "existing capacities",
            "state variable",
            "indirect",
            "arbitrage only through physical charge/discharge",
            "rolling handoff",
            "no inventory objective or midpoint target",
            "plant balances and terminal/recoverability rules",
            "within bounds; handoff equals exported execution state",
            "BUFFERS_STORAGE_Parameters.md; temporal state contract",
        ),
        row(
            "external_materials",
            "external_material_flow",
            "purchased flow by origin",
            "annual and rolling caps",
            "continuous accounting flow",
            "not_price_responsive when price is time-invariant",
            "no electricity-price response required",
            "annual cumulative budget",
            "no arbitrary daily delivery profile",
            "recipes, inventories, route allocation",
            "origin conservation; no budget reuse; external purchases priced once",
            "metallics audit, route-boundary contract and source cards",
        ),
    ]
    return rows


def synthetic_price_profiles(config: Mapping[str, Any]) -> dict[str, tuple[float, ...]]:
    profiles: dict[str, tuple[float, ...]] = {}
    for case_id, spec in config["synthetic_cases"].items():
        if "first_12h" in spec:
            profiles[case_id] = tuple(
                [float(spec["first_12h"])] * 48
                + [float(spec["second_12h"])] * 48
            )
        else:
            values = [float(spec["base"])] * 96
            for q in range(int(spec["spike_start_qh"]), int(spec["spike_end_qh"])):
                values[q] = float(spec["spike"])
            profiles[case_id] = tuple(values)
    return profiles


def load_representative_week_prices(
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, tuple[float, ...]]]:
    source = config["representative_week_source"]
    root = REPO_ROOT / str(source["root"])
    selected = list(csv.DictReader((root / source["selected_weeks_file"]).open(encoding="utf-8")))
    frame = pd.read_parquet(root / source["quarterhour_overlay_file"])
    frame = frame[
        (frame["path_kind"] == source["deterministic_path_kind"])
        & (frame["scenario_id"] == source["deterministic_scenario_id"])
    ].copy()
    prices: dict[str, tuple[float, ...]] = {}
    manifest: list[dict[str, Any]] = []
    for row in selected:
        week_id = row["week_id"]
        week = frame[frame["week_id"] == week_id].sort_values("target_timestamp_utc")
        values = tuple(float(item) for item in week[source["price_field"]])
        if len(values) != 672:
            raise TemporalRepairError(f"{week_id} does not contain 672 QH prices.")
        prices[week_id] = values
        manifest.append(
            {
                "experiment_type": "representative_week_counterfactual",
                "case_id": week_id,
                "regime_role": row["regime_role"],
                "start_date": row["week_start"],
                "end_date": row["week_end"],
                "price_source": str(source["root"]),
                "price_path_kind": source["deterministic_path_kind"],
                "price_field": source["price_field"],
                "same_initial_state_within_week": False,
                "causal_state_handoff_between_days": True,
                "week_initial_state_policy": (
                    "contract_initial_state_then_seven_causal_handoffs"
                ),
                "stateful_days": 7,
                "counterfactual_not_observed_truth": True,
            }
        )
    return manifest, prices


def _directions(values: Sequence[float], epsilon: float) -> list[int]:
    output: list[int] = []
    for left, right in zip(values, values[1:]):
        delta = right - left
        output.append(1 if delta > epsilon else (-1 if delta < -epsilon else 0))
    return output


def _direction_reversals(values: Sequence[float], epsilon: float) -> int:
    nonzero = [item for item in _directions(values, epsilon) if item]
    return sum(left != right for left, right in zip(nonzero, nonzero[1:]))


def _best_price_lag(values: Sequence[float], prices: Sequence[float], max_lag: int) -> tuple[int, float]:
    best_lag, best_corr = 0, math.nan
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = values[-lag:], prices[:lag]
        elif lag > 0:
            x, y = values[:-lag], prices[lag:]
        else:
            x, y = values, prices
        if len(x) < 3 or max(x) - min(x) <= 1e-12 or max(y) - min(y) <= 1e-12:
            continue
        corr = float(pd.Series(x).corr(pd.Series(y)))
        if math.isnan(best_corr) or abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, corr
    return best_lag, best_corr


def interval_dispatch_rows(
    model: Any,
    state: Any,
    *,
    case_id: str,
    experiment_type: str,
    day_index: int,
    prices: Sequence[float],
    start_utc: datetime,
    evaluation_prices: Sequence[float] | None = None,
    strategy_id: str = "perfect_foresight_D",
) -> list[dict[str, Any]]:
    steps = len(prices)
    dt = float(model.time_step_hours)
    cumulative_route = 0.0
    realised_prices = prices if evaluation_prices is None else evaluation_prices
    rows: list[dict[str, Any]] = []
    for q in range(steps):
        cumulative_route += _component_value(model, "final_product_output", q)
        rows.append(
            {
                "experiment_type": experiment_type,
                "configuration": "C1",
                "strategy_id": strategy_id,
                "case_id": case_id,
                "day_index": day_index,
                "interval": q,
                "timestamp_utc": (start_utc + timedelta(minutes=15 * q)).isoformat(),
                "electricity_price_eur_per_mwh": float(realised_prices[q]),
                "optimisation_electricity_price_eur_per_mwh": float(prices[q]),
                "sintering_plant_t_h": _component_value(model, "sintering_plant", q) / dt,
                "blast_furnace_6_t_h": _component_value(model, "blast_furnace_6", q) / dt,
                "coking_plant_1_t_h": _component_value(model, "coking_plant_1", q) / dt,
                "drp_pellet_input_t_h": _component_value(model, "drp_pellet_input", q) / dt,
                "bof_liquid_steel_t_h": _component_value(model, "bof_crude_steel_output", q) / dt,
                "hsm_input_t_h": _component_value(model, "hot_strip_mill", q) / dt,
                "dsp_output_t_h": _component_value(model, "dsp_final_product_output", q) / dt,
                "eaf_start": _component_value(model, "eaf_heat_start", q),
                "eaf_tap": _component_value(model, "eaf_tap", q),
                "eaf_on": _component_value(model, "eaf_on", q),
                "eaf_electricity_mw": _component_value(model, "eaf_total_electricity_mwh", q) / dt,
                "hsm_electricity_mw": _component_value(model, "hsm_rolling_electricity_mwh", q) / dt,
                "bof_electricity_mw": _component_value(model, "bof_electricity_mwh", q) / dt,
                "bf_electricity_mw": _component_value(model, "bf_electricity_mwh", q) / dt,
                "kgf_electricity_mw": _component_value(model, "kgf_electricity_mwh", q) / dt,
                "dsp_electricity_mw": _component_value(model, "dsp_electricity_mwh", q) / dt,
                "linde_electricity_mw": _component_value(model, "linde_total_electricity_mwh", q) / dt,
                "sinter_electricity_mw": _component_value(model, "sinter_electricity_mwh", q) / dt,
                "pefa_electricity_mw": _component_value(model, "pefa_electricity_mwh", q) / dt,
                "dri_inventory_t": _component_value(model, "dri_inventory", q),
                "dri_capacity_t": float(value(model.dri_buffer_capacity[q].upper)),
                "coke_inventory_t": _component_value(model, "coke_inventory", q),
                "coke_capacity_t": float(value(model.coke_capacity[q].upper)),
                "sinter_inventory_t": _component_value(model, "sinter_inventory", q),
                "sinter_capacity_t": float(value(model.sinter_capacity[q].upper)),
                "hot_iron_inventory_t": _component_value(model, "hot_iron_inventory", q),
                "hot_iron_capacity_t": float(value(model.hot_iron_capacity[q].upper)),
                "cold_slab_inventory_t": _component_value(model, "cold_slab_inventory", q),
                "cold_slab_capacity_t": float(value(model.cold_slab_capacity[q].upper)),
                "vn25_output_mw": _component_value(model, "vn25_electricity_mwh", q) / dt,
                "vn25_wag_mwh_lhv": _component_value(model, "vn25_wag_fuel_mwh", q),
                "vn25_named_ng_mwh_lhv": _component_value(model, "ng_to_vn25_mwh", q),
                "total_flare_mwh_lhv": sum(
                    _component_value(model, name, q)
                    for name in ("bfg_flared", "cog_flared", "bofg_flared")
                ),
                "net_grid_import_mwh": _component_value(model, "net_grid_import_mwh", q),
                "gross_grid_import_mwh": _component_value(
                    model, "gross_grid_import_mwh", q
                ),
                "gross_grid_export_mwh": _component_value(
                    model, "gross_grid_export_mwh", q
                ),
                "internal_generation_mwh": _component_value(model, "total_generator_electricity_mwh", q),
                "final_product_t": _component_value(model, "final_product_output", q),
                "cumulative_final_product_day_t": cumulative_route,
                "state_before_sha256": _canonical_json_sha256(state.snapshot()),
            }
        )
    return rows


def plant_response_kpis(
    model: Any,
    state: Any,
    temporal_config: Mapping[str, Any],
    validation_config: Mapping[str, Any],
    *,
    case_id: str,
    experiment_type: str,
    day_index: int,
    prices: Sequence[float],
) -> list[dict[str, Any]]:
    steps = len(prices)
    dt = float(model.time_step_hours)
    epsilon = float(validation_config["behaviour_contract"]["movement_epsilon"])
    max_lag = int(validation_config["behaviour_contract"]["correlation_lag_qh"])
    ranges = rate_ranges_from_config(temporal_config)
    rows: list[dict[str, Any]] = []

    def add(asset: str, metric: str, observed: Any, unit: str, status: str = "observed") -> None:
        rows.append(
            {
                "experiment_type": experiment_type,
                "case_id": case_id,
                "day_index": day_index,
                "aggregation_level": "day",
                "asset": asset,
                "metric": metric,
                "value": observed,
                "unit": unit,
                "status": status,
            }
        )

    component_map = {
        "sintering_plant": "sintering_plant",
        "blast_furnace_6": "blast_furnace_6",
        "coking_plant_1": "coking_plant_1",
        "drp_pellet_input": "drp_pellet_input",
        "basic_oxygen_furnace": "bof_crude_steel_output",
        "hot_strip_mill": "hot_strip_mill",
        "direct_sheet_plant": "dsp_final_product_output",
    }
    for asset, component in component_map.items():
        values = [_component_value(model, component, q) / dt for q in range(steps)]
        previous = (
            float(state.last_continuous_rate_t_h[asset])
            if asset in CONTINUOUS_ASSETS
            else values[0]
        )
        jumps = [abs(values[0] - previous)] + [
            abs(values[q] - values[q - 1]) for q in range(1, steps)
        ]
        span = ranges[asset][1] - ranges[asset][0] if asset in ranges else max(values) - min(values)
        changes = sum(item > epsilon for item in jumps[1:])
        reversals = _direction_reversals(values, epsilon)
        weighted_price = (
            sum(load * price for load, price in zip(values, prices)) / sum(values)
            if sum(values) > epsilon
            else math.nan
        )
        lag, correlation = _best_price_lag(values, prices, max_lag)
        add(asset, "minimum_throughput", min(values), "t/h")
        add(asset, "maximum_throughput", max(values), "t/h")
        add(asset, "mean_throughput", sum(values) / len(values), "t/h")
        add(asset, "execution_total", sum(values) * dt, "t")
        add(asset, "largest_jump_including_handoff", max(jumps), "t/h")
        add(asset, "normalized_total_variation", sum(jumps) / max(span, epsilon), "range")
        add(asset, "setpoint_change_count", changes, "transition")
        add(asset, "direction_reversal_count", reversals, "count")
        add(asset, "load_weighted_electricity_price", weighted_price, "EUR/MWh")
        add(asset, "price_correlation", correlation, "correlation")
        add(asset, "strongest_price_lead_lag", lag, "QH")
        if asset in ranges:
            lower, upper = ranges[asset]
            add(asset, "lower_bound_hits", sum(abs(item - lower) <= 1e-5 for item in values), "interval")
            add(asset, "upper_bound_hits", sum(abs(item - upper) <= 1e-5 for item in values), "interval")
        if asset in ASSET_ON_COMPONENTS:
            on = [_component_value(model, ASSET_ON_COMPONENTS[asset], q) for q in range(steps)]
            add(asset, "off_interval_count", sum(item < 0.5 for item in on), "interval")
            add(asset, "starts", sum(on[q] >= 0.5 and on[q - 1] < 0.5 for q in range(1, steps)), "count")
            add(asset, "stops", sum(on[q] < 0.5 and on[q - 1] >= 0.5 for q in range(1, steps)), "count")

    starts = [_component_value(model, "eaf_heat_start", q) for q in range(steps)]
    taps = [_component_value(model, "eaf_tap", q) for q in range(steps)]
    add("eaf", "heat_starts", sum(starts), "count")
    add("eaf", "heat_taps", sum(taps), "count")
    add(
        "eaf",
        "heat_start_mean_qh",
        sum(q * starts[q] for q in range(steps)) / max(sum(starts), epsilon),
        "QH",
    )
    add(
        "eaf",
        "heat_start_weighted_electricity_price",
        sum(float(prices[q]) * starts[q] for q in range(steps))
        / max(sum(starts), epsilon),
        "EUR/MWh",
    )
    add("eaf", "carry_in_lag1", state.eaf_start_lag1, "binary")
    add("eaf", "carry_in_lag2", state.eaf_start_lag2, "binary")
    add("eaf", "quota_target_taps", state.eaf_quota_target_taps, "count")
    add(
        "eaf",
        "quota_completed_before_day",
        state.eaf_quota_completed_taps,
        "count",
    )
    add(
        "eaf",
        "quota_remaining_before_day",
        int(state.eaf_quota_target_taps) - int(state.eaf_quota_completed_taps),
        "count",
    )
    for inventory in INVENTORY_COMPONENTS:
        values = [_component_value(model, inventory, q) for q in range(steps)]
        add(inventory, "inventory_start", values[0], "t")
        add(inventory, "inventory_end", values[-1], "t")
        add(inventory, "inventory_minimum", min(values), "t")
        add(inventory, "inventory_maximum", max(values), "t")
    vn25 = [_component_value(model, "vn25_electricity_mwh", q) / dt for q in range(steps)]
    add("vn25", "minimum_output", min(vn25), "MW")
    add("vn25", "maximum_output", max(vn25), "MW")
    add("vn25", "largest_ramp", max(abs(vn25[q] - vn25[q - 1]) for q in range(1, steps)), "MW/QH")
    add(
        "vn25",
        "wag_fuel_total",
        sum(_component_value(model, "vn25_wag_fuel_mwh", q) for q in range(steps)),
        "MWh_LHV",
    )
    add(
        "vn25",
        "named_ng_total",
        sum(_component_value(model, "ng_to_vn25_mwh", q) for q in range(steps)),
        "MWh_LHV",
    )
    add(
        "vn25",
        "wag_flare_total",
        sum(
            _component_value(model, carrier, q)
            for carrier in ("bfg_flared", "cog_flared", "bofg_flared")
            for q in range(steps)
        ),
        "MWh_LHV",
    )
    for metric, component in (
        ("gross_grid_import", "gross_grid_import_mwh"),
        ("net_grid_import", "net_grid_import_mwh"),
        ("internal_generation", "total_generator_electricity_mwh"),
        ("grid_export", "gross_grid_export_mwh"),
    ):
        add(
            "electricity_system",
            metric,
            sum(_component_value(model, component, q) for q in range(steps)),
            "MWh",
        )
    add(
        "final_product_route",
        "execution_total",
        sum(_component_value(model, "final_product_output", q) for q in range(steps)),
        "t",
    )
    return rows


def paired_counterfactual_validation_rows(
    kpi_rows: Sequence[Mapping[str, Any]],
    result_rows: Sequence[Mapping[str, Any]],
    *,
    expected_state_sha256: str,
    negative_fixed_count_oracle_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Gate causal paired-price responses using identical pre-decision state."""

    synthetic_kpis = [
        row
        for row in kpi_rows
        if row["experiment_type"] == "synthetic_paired_counterfactual"
        and row.get("aggregation_level") == "day"
    ]
    values = {
        (str(row["case_id"]), str(row["asset"]), str(row["metric"])): float(
            row["value"]
        )
        for row in synthetic_kpis
        if row["value"] != ""
        and not (isinstance(row["value"], float) and math.isnan(row["value"]))
    }
    synthetic_results = [
        row
        for row in result_rows
        if row["experiment_type"] == "synthetic_paired_counterfactual"
    ]
    state_hashes = {str(row["state_before_sha256"]) for row in synthetic_results}
    hard_audit_pass = bool(synthetic_results) and all(
        str(row["solver_status"])
        in {"optimal", "feasible_time_limited", "feasible_fallback"}
        and float(row["hard_constraint_max_violation"]) <= 1e-5
        for row in synthetic_results
    )
    cheap_first = values[
        ("synthetic_cheap_to_expensive", "eaf", "heat_start_mean_qh")
    ]
    expensive_first = values[
        ("synthetic_expensive_to_cheap", "eaf", "heat_start_mean_qh")
    ]
    flat_taps = values[("synthetic_flat", "eaf", "heat_taps")]
    negative_taps = values[("synthetic_negative_price_block", "eaf", "heat_taps")]
    certified_oracle_rows = [
        row
        for row in negative_fixed_count_oracle_rows
        if row.get("status") == "optimal" and row.get("objective_eur") is not None
    ]
    certified_negative_count = (
        None
        if len(certified_oracle_rows) != 3
        else int(
            min(
                certified_oracle_rows,
                key=lambda row: float(row["objective_eur"]),
            )["fixed_taps"]
        )
    )
    flat_vn25 = values[("synthetic_flat", "vn25", "maximum_output")]
    spike_vn25 = values[
        ("synthetic_positive_price_spike", "vn25", "maximum_output")
    ]
    checks = (
        (
            "paired_state",
            "identical_initial_state",
            len(state_hashes),
            "unique state hashes",
            state_hashes == {expected_state_sha256},
            "all price regimes use the identical pre-decision state",
        ),
        (
            "paired_physics",
            "hard_audits_close",
            max(
                (float(row["hard_constraint_max_violation"]) for row in synthetic_results),
                default=math.inf,
            ),
            "maximum violation",
            hard_audit_pass,
            "all paired incumbents pass the same hard physical audit",
        ),
        (
            "eaf",
            "cheap_first_starts_earlier",
            cheap_first - expensive_first,
            "QH difference",
            cheap_first < expensive_first - 1e-6,
            "cheap-to-expensive mean start QH precedes expensive-to-cheap",
        ),
        (
            "eaf",
            "negative_price_count_matches_fixed_scalar_oracle",
            negative_taps - flat_taps,
            "tap difference",
            certified_negative_count is not None
            and round_half_up(negative_taps) == certified_negative_count,
            "negative-price free count equals the strict best fixed 26--28 scalar endpoint",
        ),
        (
            "vn25",
            "positive_spike_generation_response",
            spike_vn25 - flat_vn25,
            "MW maximum difference",
            spike_vn25 > flat_vn25 + 1e-6,
            "high grid-price spike increases VN25 output within its contract",
        ),
    )
    return [
        {
            "experiment_type": "paired_counterfactual_comparison",
            "case_id": "synthetic_paired_summary",
            "asset": asset,
            "check_id": check_id,
            "observed": observed,
            "unit": unit,
            "criterion": criterion,
            "status": "pass" if passed else "fail",
        }
        for asset, check_id, observed, unit, passed, criterion in checks
    ]


def representative_week_kpis(
    interval_rows: Sequence[Mapping[str, Any]],
    temporal_config: Mapping[str, Any],
    validation_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate the seven causal days without hiding day-level KPI rows."""

    frame = pd.DataFrame(interval_rows)
    frame = frame[
        frame["experiment_type"] == "representative_week_counterfactual"
    ].copy()
    if frame.empty:
        return []
    frame["week_group"] = frame["case_id"].str.replace(
        r"_day_\d+$", "", regex=True
    )
    ranges = rate_ranges_from_config(temporal_config)
    epsilon = float(validation_config["behaviour_contract"]["movement_epsilon"])
    max_lag = int(validation_config["behaviour_contract"]["correlation_lag_qh"])
    dt = float(
        temporal_config["deterministic_temporal_repair"]["time_step_hours"]
    )
    output: list[dict[str, Any]] = []

    def add(week_id: str, asset: str, metric: str, observed: Any, unit: str) -> None:
        output.append(
            {
                "experiment_type": "representative_week_counterfactual",
                "case_id": week_id,
                "day_index": "week",
                "aggregation_level": "week",
                "asset": asset,
                "metric": metric,
                "value": observed,
                "unit": unit,
                "status": "observed",
            }
        )

    process_columns = {
        "sintering_plant": "sintering_plant_t_h",
        "blast_furnace_6": "blast_furnace_6_t_h",
        "coking_plant_1": "coking_plant_1_t_h",
        "drp_pellet_input": "drp_pellet_input_t_h",
        "basic_oxygen_furnace": "bof_liquid_steel_t_h",
        "hot_strip_mill": "hsm_input_t_h",
        "direct_sheet_plant": "dsp_output_t_h",
    }
    for week_id, week in frame.groupby("week_group", sort=False):
        week = week.sort_values(["day_index", "interval"])
        prices = [float(item) for item in week["electricity_price_eur_per_mwh"]]
        for asset, column in process_columns.items():
            values = [float(item) for item in week[column]]
            jumps = [abs(right - left) for left, right in zip(values, values[1:])]
            span = (
                ranges[asset][1] - ranges[asset][0]
                if asset in ranges
                else max(values) - min(values)
            )
            lag, correlation = _best_price_lag(values, prices, max_lag)
            add(week_id, asset, "minimum_throughput", min(values), "t/h")
            add(week_id, asset, "maximum_throughput", max(values), "t/h")
            add(week_id, asset, "mean_throughput", sum(values) / len(values), "t/h")
            add(week_id, asset, "execution_total", sum(values) * dt, "t")
            add(week_id, asset, "largest_jump_including_day_boundary", max(jumps, default=0.0), "t/h")
            add(week_id, asset, "normalized_total_variation", sum(jumps) / max(span, epsilon), "range")
            add(week_id, asset, "setpoint_change_count", sum(item > epsilon for item in jumps), "transition")
            add(week_id, asset, "direction_reversal_count", _direction_reversals(values, epsilon), "count")
            weighted = (
                sum(load * price for load, price in zip(values, prices)) / sum(values)
                if sum(values) > epsilon
                else math.nan
            )
            add(week_id, asset, "load_weighted_electricity_price", weighted, "EUR/MWh")
            add(week_id, asset, "price_correlation", correlation, "correlation")
            add(week_id, asset, "strongest_price_lead_lag", lag, "QH")
            if asset in ranges:
                lower, upper = ranges[asset]
                add(week_id, asset, "lower_bound_hits", sum(abs(item - lower) <= 1e-5 for item in values), "interval")
                add(week_id, asset, "upper_bound_hits", sum(abs(item - upper) <= 1e-5 for item in values), "interval")
                active = [item > epsilon for item in values]
                add(week_id, asset, "off_interval_count", sum(not item for item in active), "interval")
                add(week_id, asset, "starts", sum(active[q] and not active[q - 1] for q in range(1, len(active))), "count")
                add(week_id, asset, "stops", sum(not active[q] and active[q - 1] for q in range(1, len(active))), "count")
        add(week_id, "eaf", "heat_starts", float(week["eaf_start"].sum()), "count")
        add(week_id, "eaf", "heat_taps", float(week["eaf_tap"].sum()), "count")
        for asset, column in (
            ("dri_inventory", "dri_inventory_t"),
            ("coke_inventory", "coke_inventory_t"),
            ("sinter_inventory", "sinter_inventory_t"),
            ("hot_iron_inventory", "hot_iron_inventory_t"),
            ("cold_slab_inventory", "cold_slab_inventory_t"),
        ):
            values = [float(item) for item in week[column]]
            add(week_id, asset, "inventory_start", values[0], "t")
            add(week_id, asset, "inventory_end", values[-1], "t")
            add(week_id, asset, "inventory_minimum", min(values), "t")
            add(week_id, asset, "inventory_maximum", max(values), "t")
        vn25 = [float(item) for item in week["vn25_output_mw"]]
        add(week_id, "vn25", "minimum_output", min(vn25), "MW")
        add(week_id, "vn25", "maximum_output", max(vn25), "MW")
        add(week_id, "vn25", "largest_ramp", max(abs(right - left) for left, right in zip(vn25, vn25[1:])), "MW/QH")
        for metric, column, unit in (
            ("wag_fuel_total", "vn25_wag_mwh_lhv", "MWh_LHV"),
            ("named_ng_total", "vn25_named_ng_mwh_lhv", "MWh_LHV"),
            ("wag_flare_total", "total_flare_mwh_lhv", "MWh_LHV"),
            ("gross_grid_import", "gross_grid_import_mwh", "MWh"),
            ("net_grid_import", "net_grid_import_mwh", "MWh"),
            ("internal_generation", "internal_generation_mwh", "MWh"),
            ("grid_export", "gross_grid_export_mwh", "MWh"),
            ("final_product", "final_product_t", "t"),
        ):
            asset = (
                "vn25"
                if metric in {"wag_fuel_total", "named_ng_total", "wag_flare_total"}
                else "final_product_route"
                if metric == "final_product"
                else "electricity_system"
            )
            add(week_id, asset, metric, float(week[column].sum()), unit)
    return output


def behaviour_validation_rows(
    kpis: Sequence[Mapping[str, Any]],
    energy_rows: Sequence[Mapping[str, Any]],
    temporal_config: Mapping[str, Any],
    validation_config: Mapping[str, Any],
    *,
    case_id: str,
    experiment_type: str,
) -> list[dict[str, Any]]:
    observed = {
        (str(row["asset"]), str(row["metric"])): float(row["value"])
        for row in kpis
        if row["value"] != "" and not (isinstance(row["value"], float) and math.isnan(row["value"]))
    }
    dynamics = temporal_config["deterministic_temporal_repair"]["plant_dynamics"]
    contract = validation_config["behaviour_contract"]
    kgf1_block_hours = float(dynamics["kgf1"]["setpoint_block_hours"])
    kgf1_maximum_daily_changes = int(math.ceil(24.0 / kgf1_block_hours))
    checks: list[tuple[str, str, float, str, bool, str]] = []
    for asset in CONTINUOUS_ASSETS:
        off = observed[(asset, "off_interval_count")]
        checks.append((asset, "must_run", off, "off intervals", off == 0, "continuous must-run"))
    checks.extend(
        [
            ("sintering_plant", "ramp", observed[("sintering_plant", "largest_jump_including_handoff")], "t/h", observed[("sintering_plant", "largest_jump_including_handoff")] <= float(dynamics["sifa"]["ramp_t_h_per_qh"]) + 1e-5, "SiFa QH ramp"),
            ("sintering_plant", "direction_reversals", observed[("sintering_plant", "direction_reversal_count")], "count", observed[("sintering_plant", "direction_reversal_count")] <= 12, "2-hour no-reversal contract"),
            ("blast_furnace_6", "setpoint_step", observed[("blast_furnace_6", "largest_jump_including_handoff")], "t/h", observed[("blast_furnace_6", "largest_jump_including_handoff")] <= float(dynamics["bf6"]["maximum_step_t_h"]) + 1e-5, "BF6 hourly step"),
            ("coking_plant_1", "bounded_setpoint_changes", observed[("coking_plant_1", "setpoint_change_count")], "count", observed[("coking_plant_1", "setpoint_change_count")] <= kgf1_maximum_daily_changes, f"KGF1 {kgf1_block_hours:g}-hour setpoint blocks"),
            ("drp_pellet_input", "direction_reversals", observed[("drp_pellet_input", "direction_reversal_count")], "count", observed[("drp_pellet_input", "direction_reversal_count")] <= int(contract["drp_maximum_direction_reversals_per_day"]), "slow continuous behaviour"),
        ]
    )
    maximum_free_changes = int(
        95 * float(contract["downstream_free_qh_change_fraction_failure"])
    )
    for asset in ("basic_oxygen_furnace", "hot_strip_mill", "direct_sheet_plant"):
        changes = observed[(asset, "setpoint_change_count")]
        checks.append((asset, "no_free_qh_oscillation", changes, "transition", changes <= maximum_free_changes, "batch/material response"))
    checks.extend(
        [
            ("vn25", "minimum_output", observed[("vn25", "minimum_output")], "MW", observed[("vn25", "minimum_output")] >= 175.0 - 1e-5, "development lower bound"),
            ("vn25", "maximum_output", observed[("vn25", "maximum_output")], "MW", observed[("vn25", "maximum_output")] <= 350.0 + 1e-5, "development upper bound"),
            ("vn25", "ramp", observed[("vn25", "largest_ramp")], "MW/QH", observed[("vn25", "largest_ramp")] <= 52.5 + 1e-5, "210 MW/h ramp"),
        ]
    )
    avoidable = sum(bool(row["avoidable_flare_plus_vn25_ng"]) for row in energy_rows)
    checks.append(("wag_ng", "avoidable_flare_plus_named_ng", avoidable, "interval", avoidable == 0, "eligible WAG precedence"))
    return [
        {
            "experiment_type": experiment_type,
            "case_id": case_id,
            "asset": asset,
            "check_id": check,
            "observed": observed_value,
            "unit": unit,
            "criterion": criterion,
            "status": "pass" if passed else "fail",
        }
        for asset, check, observed_value, unit, passed, criterion in checks
    ]


def _calibrate_continuation(
    context: Any,
    state: Any,
    temporal_config: Mapping[str, Any],
    output: Path,
    attempt_rows: list[dict[str, Any]],
) -> float:
    prices = (75.0,) * context.time_grid.execution_steps
    costs: dict[int, float] = {}
    for count in (26, 27, 28):
        model = build_temporal_model(
            context, state, temporal_config, lower_taps=26, upper_taps=28, fixed_taps=count
        )
        components = build_scalar_objective_components(
            context,
            model,
            electricity_prices=prices,
            remaining_taps=count,
            continuation_eur_per_heat=0.0,
        )
        result = _solve_scalar_attempt(
            model,
            components,
            temporal_config,
            run_case=f"behaviour_calibration_fixed_{count}",
            attempt="strict_cost_endpoint",
            time_limit_seconds=float(temporal_config["deterministic_temporal_repair"]["solver_time_limit_seconds"]),
            mip_gap=0.0,
            solver_log_path=output / "solver_logs" / f"calibration_fixed_{count}.log",
            fallback_used=False,
        )
        attempt_rows.append(result.record())
        _write_json(output / "solver_attempts.json", attempt_rows)
        if result.status != "optimal" or result.procurement_eur is None:
            raise TemporalRepairError(f"Continuation endpoint {count} is not optimal.")
        costs[count] = float(result.procurement_eur)
    continuation = (costs[28] - costs[26]) / 2.0
    if continuation < 0.0 or not math.isfinite(continuation):
        raise TemporalRepairError("Continuation calibration is invalid.")
    _write_json(
        output / "continuation_calibration.json",
        {
            "endpoint_costs_eur": costs,
            "continuation_eur_per_heat": continuation,
            "state_sha256": _canonical_json_sha256(state.snapshot()),
            "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
            "status": "strict_endpoints_recomputed_for_validation",
        },
    )
    return continuation


def _negative_price_fixed_count_oracle(
    context: Any,
    state: Any,
    temporal_config: Mapping[str, Any],
    validation_config: Mapping[str, Any],
    output: Path,
    *,
    prices: Sequence[float],
    continuation: float,
    attempt_rows: list[dict[str, Any]],
) -> tuple[Any, list[dict[str, Any]]]:
    """Return the exact best 26--28 fixed-count model as a diagnostic MIP start."""

    rows: list[dict[str, Any]] = []
    models: dict[int, Any] = {}
    limit = float(
        validation_config["behaviour_contract"][
            "diagnostic_extended_time_limit_seconds"
        ]
    )
    for count in (26, 27, 28):
        model = build_temporal_model(
            context,
            state,
            temporal_config,
            lower_taps=count,
            upper_taps=count,
            week_boundary=False,
        )
        components = build_scalar_objective_components(
            context,
            model,
            electricity_prices=prices,
            remaining_taps=(
                int(state.eaf_quota_target_taps)
                - int(state.eaf_quota_completed_taps)
            ),
            continuation_eur_per_heat=continuation,
        )
        result = _solve_scalar_attempt(
            model,
            components,
            temporal_config,
            run_case=f"negative_fixed_{count}",
            attempt="strict_fixed_count_oracle",
            time_limit_seconds=limit,
            mip_gap=0.0,
            solver_log_path=(
                output / "solver_logs" / f"negative_fixed_{count}_oracle.log"
            ),
            fallback_used=True,
            warm_start=False,
            dual_reductions=False,
        )
        attempt_rows.append(result.record())
        rows.append(
            {
                "case_id": "synthetic_negative_price_block",
                "fixed_taps": count,
                "status": result.status,
                "objective_eur": result.incumbent_objective_eur,
                "procurement_eur": result.procurement_eur,
                "continuation_eur": result.continuation_eur,
                "best_bound_eur": result.best_bound_eur,
                "relative_gap": result.relative_gap,
                "runtime_seconds": result.runtime_seconds,
            }
        )
        models[count] = model
    _write_csv(output / "negative_price_fixed_count_oracle.csv", rows)
    _write_json(output / "solver_attempts.json", attempt_rows)
    if any(row["status"] != "optimal" for row in rows):
        raise TemporalRepairError(
            "Negative-price fixed-count oracle did not prove all 26--28 endpoints."
        )
    best = min(rows, key=lambda row: float(row["objective_eur"]))
    return models[int(best["fixed_taps"])], rows


def _solve_day(
    context: Any,
    state: Any,
    temporal_config: Mapping[str, Any],
    validation_config: Mapping[str, Any],
    output: Path,
    *,
    case_id: str,
    experiment_type: str,
    day_index: int,
    prices: Sequence[float],
    continuation: float,
    remaining_days: int,
    warm_source: Any | None,
    start_utc: datetime,
    attempt_rows: list[dict[str, Any]],
    evaluation_prices: Sequence[float] | None = None,
    strategy_id: str = "perfect_foresight_D",
    extend_time_limited_diagnostic: bool = False,
) -> tuple[Any, Any, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    remaining = int(state.eaf_quota_target_taps) - int(state.eaf_quota_completed_taps)
    future_lower = [26] * (remaining_days - 1)
    future_upper = [28] * (remaining_days - 1)
    lower, upper = dynamic_daily_heat_bounds(
        remaining_taps=remaining,
        today_lower=26,
        today_upper=28,
        future_lower_bounds=future_lower,
        future_upper_bounds=future_upper,
    )
    model = build_temporal_model(
        context,
        state,
        temporal_config,
        lower_taps=lower,
        upper_taps=upper,
        week_boundary=remaining_days == 1,
    )
    warm_start_value_count = (
        0 if warm_source is None else _copy_adjacent_warm_start(warm_source, model)
    )
    components = build_scalar_objective_components(
        context,
        model,
        electricity_prices=prices,
        remaining_taps=remaining,
        continuation_eur_per_heat=continuation,
    )
    solver_case_id = (
        case_id
        if len(case_id) <= 32 and "__" not in case_id
        else f"week_{hashlib.sha256(case_id.encode('utf-8')).hexdigest()[:16]}"
    )
    result, attempts = solve_scalar_operational_model(
        model,
        components,
        temporal_config,
        run_case=solver_case_id,
        solver_log_root=output / "solver_logs",
        warm_start=warm_start_value_count > 0,
    )
    primary_was_time_limited = result.status == "feasible_time_limited"
    behaviour_contract = validation_config["behaviour_contract"]
    gate_oracle_required = (
        extend_time_limited_diagnostic
        and bool(behaviour_contract["extend_time_limited_gate_cases"])
        and primary_was_time_limited
    )
    if gate_oracle_required:
        extended = _solve_scalar_attempt(
            model,
            components,
            temporal_config,
            run_case=solver_case_id,
            attempt="gate_defining_strict_oracle_60s",
            time_limit_seconds=float(
                behaviour_contract["diagnostic_extended_time_limit_seconds"]
            ),
            mip_gap=float(
                temporal_config["deterministic_temporal_repair"]["runtime_mip_gap"]
            ),
            solver_log_path=(
                output / "solver_logs" / f"{solver_case_id}_strict_oracle_60s.log"
            ),
            fallback_used=True,
            warm_start=True,
            dual_reductions=False,
        )
        attempts.append(extended)
        if extended.feasible_incumbent:
            result = extended

    # A time-limited MIP incumbent can contain a needlessly expensive continuous
    # fuel allocation.  Fix its integer schedule and re-optimise the *same*
    # scalar objective; this is an incumbent polish, not a new objective tier.
    if primary_was_time_limited or (
        gate_oracle_required and result.status != "optimal"
    ):
        for variable in model.component_data_objects(Var, active=True):
            if not (variable.is_binary() or variable.is_integer()):
                continue
            if variable.value is None:
                raise TemporalRepairError(
                    f"{case_id} cannot polish an unset integer {variable.name}."
                )
            variable.fix(round(float(value(variable))))
        polished = _solve_scalar_attempt(
            model,
            components,
            temporal_config,
            run_case=solver_case_id,
            attempt="same_objective_continuous_polish",
            time_limit_seconds=float(
                behaviour_contract["continuous_incumbent_polish_time_limit_seconds"]
            ),
            mip_gap=0.0,
            solver_log_path=(
                output / "solver_logs" / f"{solver_case_id}_continuous_polish.log"
            ),
            fallback_used=True,
            warm_start=True,
            dual_reductions=False,
        )
        attempts.append(polished)
        if not polished.feasible_incumbent or polished.status != "optimal":
            raise TemporalRepairError(
                f"{case_id} same-objective continuous incumbent polish did not close."
            )
        result.incumbent_objective_eur = polished.incumbent_objective_eur
        result.procurement_eur = polished.procurement_eur
        result.continuation_eur = polished.continuation_eur
        result.absolute_gap_eur = (
            None
            if result.best_bound_eur is None or result.incumbent_objective_eur is None
            else max(
                0.0,
                float(result.incumbent_objective_eur) - float(result.best_bound_eur),
            )
        )
        result.relative_gap = (
            None
            if result.absolute_gap_eur is None or result.incumbent_objective_eur is None
            else result.absolute_gap_eur
            / max(1.0, abs(float(result.incumbent_objective_eur)))
        )
        result.runtime_seconds = sum(item.runtime_seconds for item in attempts)
        result.fallback_used = True
    attempt_rows.extend(item.record() for item in attempts)
    _write_json(output / "solver_attempts.json", attempt_rows)
    violation, location = _maximum_incumbent_violation(model)
    if violation > 1e-5:
        raise TemporalRepairError(f"{case_id} violates {location} by {violation:.9g}.")
    if abs(float(value(model.rolling_production_progress_deviation_t))) > PHYSICAL_TOLERANCE:
        raise TemporalRepairError(f"{case_id} has non-zero production progress deviation.")
    reporting = scalar_reporting_kpis(
        model,
        state,
        temporal_config,
        execution_steps=context.time_grid.execution_steps,
        remaining_taps=remaining,
        remaining_days=remaining_days,
    )
    interval_rows = interval_dispatch_rows(
        model,
        state,
        case_id=case_id,
        experiment_type=experiment_type,
        day_index=day_index,
        prices=prices,
        evaluation_prices=evaluation_prices,
        strategy_id=strategy_id,
        start_utc=start_utc,
    )
    kpis = plant_response_kpis(
        model,
        state,
        temporal_config,
        validation_config,
        case_id=case_id,
        experiment_type=experiment_type,
        day_index=day_index,
        prices=prices,
    )
    energy = energy_audit_rows(model, run_case=case_id)
    validations = behaviour_validation_rows(
        kpis,
        energy,
        temporal_config,
        validation_config,
        case_id=case_id,
        experiment_type=experiment_type,
    )
    result_row = {
        "experiment_type": experiment_type,
        "configuration": "C1",
        "strategy_id": strategy_id,
        "case_id": case_id,
        "day_index": day_index,
        "state_before_sha256": _canonical_json_sha256(state.snapshot()),
        "lower_taps": lower,
        "upper_taps": upper,
        "executed_taps": int(round(reporting["executed_taps"])),
        "solver_status": result.status,
        "incumbent_objective_eur": result.incumbent_objective_eur,
        "optimisation_procurement_eur": result.procurement_eur,
        "realised_procurement_eur": float(
            value(
                _represented_cost_expression(
                    context,
                    model,
                    C1_CONFIGURATION,
                    tuple(float(item) for item in (evaluation_prices or prices))
                    + tuple(0.0 for _ in range(len(model.TIME) - len(prices))),
                    objective_hours=tuple(range(len(prices))),
                )
            )
        ),
        "best_bound_eur": result.best_bound_eur,
        "relative_gap": result.relative_gap,
        "runtime_seconds": result.runtime_seconds,
        "fallback_used": result.fallback_used,
        "hard_constraint_max_violation": violation,
        "hard_constraint_max_violation_location": location,
        "status": "pass" if all(row["status"] == "pass" for row in validations) else "fail",
    }
    return model, result_row, reporting, interval_rows, kpis, validations


def partial_anchor_rows(
    annual_rows: Sequence[Mapping[str, Any]],
    executed_hours: int,
    baseline_delta_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    factor = float(executed_hours) / 8760.0
    baseline_by_metric = {
        str(row["metric_id"]): row for row in baseline_delta_rows
    }
    output: list[dict[str, Any]] = []
    for row in annual_rows:
        source = row.get("source_value", "")
        annualised = float(row["model_annual_equivalent"])
        cumulative = annualised * factor
        source_period = "" if source == "" else float(source) * factor
        baseline = baseline_by_metric.get(str(row["metric_id"]), {})
        output.append(
            {
                "metric_id": row["metric_id"],
                "metric": row["metric"],
                "family": row["family"],
                "source_value": source,
                "source_unit": row["source_unit"],
                "model_cumulative_8688h": cumulative,
                "comparable_period_source_value": source_period,
                "provisional_annualised_model_diagnostic": annualised,
                "absolute_deviation_annualised": row["absolute_deviation"],
                "relative_deviation_annualised": row["relative_deviation"],
                "coverage": row["model_coverage"],
                "boundary_denominator": row["boundary_denominator"],
                "comparability": row["comparability"],
                "period_classification": "partial_year_8688h",
                "annualisation_label": "provisional_annualised_diagnostic",
                "validation_status": "not_full_year_validated",
                "executed_hours": executed_hours,
                "source_locator": row["source_locator"],
                "caveat": row["caveat"],
                "last_accepted_baseline_id": baseline.get("baseline_id", ""),
                "last_accepted_model_annual_equivalent": baseline.get(
                    "last_accepted_value", ""
                ),
                "absolute_delta_vs_last_accepted": baseline.get(
                    "absolute_delta", ""
                ),
                "relative_delta_vs_last_accepted": baseline.get(
                    "relative_delta", ""
                ),
                "baseline_comparison_status": baseline.get(
                    "comparison_status", "not_available_no_comparable_baseline"
                ),
            }
        )
    return output


def supplemental_annual_operational_rows(
    totals: Mapping[str, float],
    *,
    executed_hours: int,
    hsm_final_t_per_t_slab: float,
) -> list[dict[str, Any]]:
    """Expose plant-level diagnostics omitted by the shared primary anchor gate."""

    factor = 8760.0 / float(executed_hours)

    def annual(field: str, multiplier: float = 1.0) -> float:
        return float(totals.get(field, 0.0)) * factor * multiplier

    definitions = (
        (
            "represented_sinter_ore_feed",
            "Represented SiFa iron-ore feed",
            "material",
            annual("sintering_plant"),
            "t/y",
            2_800_000.0 / 1.23,
            "t/y",
            "represented SiFa ore-feed boundary",
            "2.8 Mt/y sinter divided by 1.230 t sinter/t represented ore",
            "partially_comparable",
            "c5_route_boundary_contract.csv C1_SINTER",
            "Derived configuration-matched development anchor; not full sinter burden.",
        ),
        (
            "hsm_final_output",
            "HSM final output",
            "material",
            annual("hot_strip_mill", hsm_final_t_per_t_slab),
            "t/y",
            5_500_000.0,
            "t/y",
            "represented HSM final-product route",
            "HRC final output after the active HSM yield",
            "not_comparable",
            "c5_model_anchor_evidence_register.csv c1_hsm_wbw_raw_output_5_5",
            "The 5.5-Mt/y row helped define the model route and is not independent validation evidence.",
        ),
        (
            "dsp_final_output",
            "DSP final output",
            "material",
            annual("dsp_final_product_output"),
            "t/y",
            1_500_000.0,
            "t/y",
            "represented DSP final-product route",
            "DSP coil final output",
            "not_comparable",
            "c5_model_anchor_evidence_register.csv c1_dsp_raw_output_1_5",
            "The 1.5-Mt/y row helped define the model route and is not independent validation evidence.",
        ),
        (
            "steam_production",
            "Represented steam production",
            "steam",
            annual("steam_production_mwh"),
            "MWh/y",
            "",
            "",
            "mapped represented steam boundary",
            "explicit boiler steam-production accounting",
            "not_comparable",
            "active unified-builder steam accounting",
            "No full-site steam-production anchor is claimed.",
        ),
        (
            "steam_15bar_supply",
            "Represented 15-bar steam supply",
            "steam",
            annual("steam_15bar_supply_t"),
            "t/y",
            "",
            "",
            "mapped represented 15-bar steam boundary",
            "instantaneous steam-bus supply",
            "not_comparable",
            "active unified-builder steam accounting",
            "Mapped demand only; no full-site steam residual is filled.",
        ),
        (
            "steam_15bar_demand",
            "Represented 15-bar steam demand",
            "steam",
            annual("steam_15bar_demand_t"),
            "t/y",
            "",
            "",
            "mapped represented 15-bar steam boundary",
            "instantaneous steam-bus demand",
            "not_comparable",
            "active unified-builder steam accounting",
            "Mapped demand only; no full-site steam residual is filled.",
        ),
        (
            "steam_15bar_spill",
            "Represented 15-bar steam spill",
            "steam",
            annual("steam_15bar_spill_t"),
            "t/y",
            "",
            "",
            "mapped represented 15-bar steam boundary",
            "explicit steam-bus spill",
            "not_comparable",
            "active unified-builder steam accounting",
            "Zero spill is model output, not a full-site claim.",
        ),
    )
    rows: list[dict[str, Any]] = []
    for (
        metric_id,
        metric,
        family,
        model_value,
        model_unit,
        source_value,
        source_unit,
        coverage,
        boundary,
        comparability,
        source_locator,
        caveat,
    ) in definitions:
        absolute = (
            "" if source_value == "" else model_value - float(source_value)
        )
        relative = (
            ""
            if source_value == "" or abs(float(source_value)) <= PHYSICAL_TOLERANCE
            else float(absolute) / abs(float(source_value))
        )
        rows.append(
            {
                "evaluation_id": "normal_operation_maintenance_excluded_partial_8688h",
                "period_classification": "partial_year_8688h",
                "executed_hours": int(executed_hours),
                "calendar_coverage": "362 sequential causal days; 8,688 h; maintenance excluded",
                "annualisation_denominator_hours": int(executed_hours),
                "metric_id": metric_id,
                "metric": metric,
                "family": family,
                "source_value": source_value,
                "source_unit": source_unit,
                "model_annual_equivalent": model_value,
                "model_unit": model_unit,
                "absolute_deviation": absolute,
                "relative_deviation": relative,
                "model_coverage": coverage,
                "boundary_denominator": boundary,
                "comparability": comparability,
                "source_locator": source_locator,
                "caveat": caveat,
            }
        )
    return rows


def c1_external_materials_audit(
    totals: Mapping[str, float], *, executed_hours: int
) -> list[dict[str, Any]]:
    flows = {
        "external_scrap_to_BOF": ("external_scrap_to_bof_t", 1_300_000.0),
        "external_scrap_to_EAF": ("external_scrap_to_eaf_t", 1_300_000.0),
        "internal_scrap_to_BOF": ("internal_scrap_to_bof_t", 600_000.0),
        "internal_scrap_to_EAF": ("internal_scrap_to_eaf_t", 600_000.0),
        "pellet_import": ("drp_pellet_input", math.inf),
        "HBI": ("imported_hbi_to_eaf_t", 0.0),
        "imported_slab": ("imported_slab_to_hsm", 600_000.0),
        "dry_coking_coal": ("coking_plant_1", math.inf),
        "PCI": ("bf_pci_input_t", math.inf),
        "represented_sinter_ore": ("sintering_plant", math.inf),
    }
    rows: list[dict[str, Any]] = []
    state_fields = {
        "external_scrap_to_BOF": "cumulative_external_scrap_to_bof_t",
        "external_scrap_to_EAF": "cumulative_external_scrap_to_eaf_t",
        "internal_scrap_to_BOF": "cumulative_internal_scrap_to_bof_t",
        "internal_scrap_to_EAF": "cumulative_internal_scrap_to_eaf_t",
        "imported_slab": "cumulative_route_progress_t.C1_imported_slab_to_HSM_t_h",
    }
    for material, (field, cap) in flows.items():
        observed = float(totals.get(field, 0.0))
        period_cap = ""
        passed = material != "HBI" or abs(observed) <= 1e-6
        if not math.isinf(cap) and material != "HBI":
            passed = observed <= float(cap) + 1e-5
        rows.append(
            {
                "material_flow": material,
                "model_cumulative_t": observed,
                "annual_cap_t": "" if math.isinf(cap) else cap,
                "comparable_period_cap_t": period_cap,
                "origin_tagged": material in {
                    "external_scrap_to_BOF",
                    "external_scrap_to_EAF",
                    "internal_scrap_to_BOF",
                    "internal_scrap_to_EAF",
                },
                "procurement_cost_treatment": (
                    "external_purchase_priced_once"
                    if material.startswith("external_") or material in {"pellet_import", "HBI", "imported_slab", "dry_coking_coal", "PCI", "represented_sinter_ore"}
                    else "internal_reuse_not_purchased"
                ),
                "status": "pass" if passed else "fail",
                "period_classification": "partial_year_8688h",
                "executed_hours": executed_hours,
                "rolling_cumulative_state_field": state_fields.get(material, ""),
                "rolling_budget_carry_status": (
                    "validated_no_reuse_between_replans"
                    if material in state_fields
                    else "not_applicable_no_rolling_budget_cap"
                ),
            }
        )
    external = float(totals.get("external_scrap_to_bof_t", 0.0)) + float(totals.get("external_scrap_to_eaf_t", 0.0))
    internal = float(totals.get("internal_scrap_to_bof_t", 0.0)) + float(totals.get("internal_scrap_to_eaf_t", 0.0))
    total = external + internal
    for material, observed, cap in (
        ("external_scrap_total", external, 1_300_000.0),
        ("internal_scrap_total", internal, 600_000.0),
        ("site_scrap_total", total, 1_900_000.0),
    ):
        rows.append(
            {
                "material_flow": material,
                "model_cumulative_t": observed,
                "annual_cap_t": cap,
                "comparable_period_cap_t": "",
                "origin_tagged": True,
                "procurement_cost_treatment": "origin_conservation_summary",
                "status": "pass" if observed <= cap + 1e-5 else "fail",
                "period_classification": "partial_year_8688h",
                "executed_hours": executed_hours,
                "rolling_cumulative_state_field": (
                    "sum_of_origin_tagged_SteelRollingState_fields"
                ),
                "rolling_budget_carry_status": (
                    "validated_no_reuse_between_replans"
                ),
            }
        )
    return rows


def balance_identity_rows(totals: Mapping[str, float]) -> list[dict[str, Any]]:
    residuals = {
        "bfg_balance_residual": float(totals.get("bfg_balance_residual", 0.0)),
        "cog_balance_residual": float(totals.get("cog_balance_residual", 0.0)),
        "bofg_balance_residual": float(totals.get("bofg_balance_residual", 0.0)),
        "generator_fuel_identity_residual_mwh": float(
            totals.get("generator_fuel_identity_residual_mwh", 0.0)
        ),
        "gross_site_electricity_identity_residual_mwh": float(
            totals.get("gross_site_electricity_identity_residual_mwh", 0.0)
        ),
        "steam_15bar_balance_residual_t": (
            float(totals.get("steam_15bar_supply_t", 0.0))
            - float(totals.get("steam_15bar_demand_t", 0.0))
            - float(totals.get("steam_15bar_spill_t", 0.0))
        ),
        "bof_scrap_origin_balance_residual_t": (
            float(totals.get("bof_scrap_supply_t", 0.0))
            - float(totals.get("external_scrap_to_bof_t", 0.0))
            - float(totals.get("internal_scrap_to_bof_t", 0.0))
        ),
        "eaf_scrap_origin_balance_residual_t": (
            float(totals.get("eaf_scrap_supply_t", 0.0))
            - float(totals.get("external_scrap_to_eaf_t", 0.0))
            - float(totals.get("internal_scrap_to_eaf_t", 0.0))
        ),
        "co2_double_count_residual_t": (
            float(totals.get("explicit_direct_co2_t", 0.0))
            - float(totals.get("bfg_explicit_combustion_co2_t", 0.0))
            - float(totals.get("cog_explicit_combustion_co2_t", 0.0))
            - float(totals.get("bofg_explicit_combustion_co2_t", 0.0))
            - float(totals.get("explicit_ng_combustion_co2_t", 0.0))
        ),
    }
    return [
        {
            "identity": identity,
            "residual": residual,
            "unit": "MWh_or_t_as_named",
            "tolerance": 1e-6,
            "status": "pass" if abs(residual) <= 1e-6 else "fail",
        }
        for identity, residual in residuals.items()
    ]


def representative_week_economic_rows(
    result_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(result_rows)
    frame = frame[
        frame["experiment_type"] == "representative_week_counterfactual"
    ].copy()
    if frame.empty:
        return []
    frame["week_id"] = frame["case_id"].str.replace(
        r"__(perfect_foresight_D|price_insensitive)_day_\d+$", "", regex=True
    )
    grouped = (
        frame.groupby(["configuration", "week_id", "strategy_id"], as_index=False)
        .agg(
            realised_procurement_eur=("realised_procurement_eur", "sum"),
            optimisation_procurement_eur=("optimisation_procurement_eur", "sum"),
            solver_runtime_seconds=("runtime_seconds", "sum"),
            executed_taps=("executed_taps", "sum"),
            maximum_reported_gap=("relative_gap", "max"),
        )
    )
    baseline = {
        (row.configuration, row.week_id): float(row.realised_procurement_eur)
        for row in grouped.itertuples()
        if row.strategy_id == "price_insensitive"
    }
    rows: list[dict[str, Any]] = []
    for row in grouped.itertuples():
        base = baseline.get((row.configuration, row.week_id))
        realised = float(row.realised_procurement_eur)
        rows.append(
            {
                "configuration": row.configuration,
                "week_id": row.week_id,
                "strategy_id": row.strategy_id,
                "period_hours": 168,
                "realised_procurement_eur": realised,
                "provisional_annualised_procurement_eur": realised * 8760.0 / 168.0,
                "saving_vs_price_insensitive_eur": (
                    "" if base is None else base - realised
                ),
                "saving_vs_price_insensitive_fraction": (
                    "" if not base else (base - realised) / base
                ),
                "optimisation_procurement_eur": float(
                    row.optimisation_procurement_eur
                ),
                "solver_runtime_seconds": float(row.solver_runtime_seconds),
                "maximum_reported_gap": float(row.maximum_reported_gap),
                "executed_taps": int(row.executed_taps),
                "economic_boundary": "represented_external_procurement_only",
                "annualisation_status": "selected_week_diagnostic_not_representative_year",
            }
        )
    return rows


def hourly_aggregate_rows(
    interval_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(interval_rows)
    frame = frame[
        frame["experiment_type"] == "representative_week_counterfactual"
    ].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame["timestamp_hour_utc"] = frame["timestamp_utc"].dt.floor("h")
    id_columns = ["configuration", "strategy_id", "case_id", "timestamp_hour_utc"]
    numeric = [
        column
        for column in frame.select_dtypes(include="number").columns
        if column not in {"day_index", "interval"}
    ]
    grouped = frame.groupby(id_columns, as_index=False)[numeric].mean()
    grouped["granularity"] = "H_aggregated_from_four_QH_after_solve"
    return grouped.to_dict("records")


def anchor_level_rows(anchor_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    level_by_family = {
        "production": "site_and_route",
        "material": "plant_and_material",
        "WAG": "energy_carrier",
        "generator": "plant_and_energy",
        "natural_gas": "plant_and_site_energy",
        "electricity": "plant_and_site_energy",
        "steam": "plant_and_energy",
        "CO2": "emissions",
    }
    return [
        {
            "configuration": "C1",
            "reporting_level": level_by_family.get(str(row["family"]), "other"),
            **dict(row),
        }
        for row in anchor_rows
    ]


def current_anchor_level_rows(
    validation_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source = validation_config["current_annual_anchor_source"]
    path = REPO_ROOT / str(source["file"])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    selected = [row for row in rows if row["evaluation_id"] == source["evaluation_id"]]
    if not selected:
        raise TemporalRepairError("Current D3 annual-anchor source contains no selected rows.")
    level_by_family = {
        "production": "site_and_route",
        "material": "plant_and_material",
        "WAG": "energy_carrier",
        "generator": "plant_and_energy",
        "natural_gas": "plant_and_site_energy",
        "electricity": "plant_and_site_energy",
        "steam": "plant_and_energy",
        "CO2": "emissions",
    }
    return [
        {
            "configuration": "C1",
            "reporting_level": level_by_family.get(row["family"], "other"),
            "evidence_status": source["status"],
            **row,
        }
        for row in selected
    ]


def before_after_validation_delta(
    before_run_root: str | Path,
    *,
    behaviour_rows: Sequence[Mapping[str, Any]],
    material_rows: Sequence[Mapping[str, Any]],
    balance_rows: Sequence[Mapping[str, Any]],
    validation_gate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compare an identical pre-repair run with the current validation outputs."""

    before = Path(before_run_root)
    if not before.is_absolute():
        before = REPO_ROOT / before
    required = {
        "behaviour_validation_results.csv": (
            behaviour_rows,
            ("experiment_type", "case_id", "asset", "check_id"),
            ("observed",),
        ),
        "c1_external_materials_audit.csv": (
            material_rows,
            ("material_flow",),
            ("model_cumulative_t", "annual_cap_t"),
        ),
        "balance_identity_gate.csv": (
            balance_rows,
            ("identity",),
            ("residual",),
        ),
    }
    if not before.is_dir():
        raise TemporalRepairError(f"Before-run folder does not exist: {before}")

    def read_rows(path: Path) -> list[dict[str, str]]:
        if not path.is_file():
            raise TemporalRepairError(f"Before-run evidence is missing: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def numeric_delta(before_value: Any, after_value: Any) -> float | str:
        try:
            left = float(before_value)
            right = float(after_value)
        except (TypeError, ValueError):
            return ""
        if not (math.isfinite(left) and math.isfinite(right)):
            return ""
        return right - left

    rows: list[dict[str, Any]] = []
    for artifact, (after_rows, key_fields, metric_fields) in required.items():
        before_rows = read_rows(before / artifact)
        before_index = {
            tuple(str(row.get(field, "")) for field in key_fields): row
            for row in before_rows
        }
        after_index = {
            tuple(str(row.get(field, "")) for field in key_fields): dict(row)
            for row in after_rows
        }
        for key in sorted(set(before_index) | set(after_index)):
            before_row = before_index.get(key)
            after_row = after_index.get(key)
            for metric in metric_fields:
                before_value = "" if before_row is None else before_row.get(metric, "")
                after_value = "" if after_row is None else after_row.get(metric, "")
                delta = numeric_delta(before_value, after_value)
                before_status = "" if before_row is None else before_row.get("status", "")
                after_status = "" if after_row is None else after_row.get("status", "")
                if before_row is None:
                    classification = "added_after_repair"
                elif after_row is None:
                    classification = "missing_after_repair"
                elif before_status != after_status:
                    classification = "status_changed"
                elif delta != "" and abs(float(delta)) > 1e-12:
                    classification = "value_changed"
                else:
                    classification = "unchanged"
                rows.append(
                    {
                        "artifact": artifact,
                        "comparison_key": "|".join(key),
                        "metric": metric,
                        "before_value": before_value,
                        "after_value": after_value,
                        "delta_after_minus_before": delta,
                        "before_status": before_status,
                        "after_status": after_status,
                        "change_classification": classification,
                    }
                )

    gate_path = before / "validation_gate.json"
    if not gate_path.is_file():
        raise TemporalRepairError(f"Before-run evidence is missing: {gate_path}")
    before_gate = json.loads(gate_path.read_text(encoding="utf-8"))
    for metric in (
        "behaviour_failure_count",
        "balance_failure_count",
        "material_failure_count",
        "figure_count",
    ):
        before_value = before_gate.get(metric, "")
        after_value = validation_gate.get(metric, "")
        delta = numeric_delta(before_value, after_value)
        rows.append(
            {
                "artifact": "validation_gate.json",
                "comparison_key": "run_gate",
                "metric": metric,
                "before_value": before_value,
                "after_value": after_value,
                "delta_after_minus_before": delta,
                "before_status": before_gate.get("judgement", ""),
                "after_status": validation_gate.get("judgement", ""),
                "change_classification": (
                    "status_changed"
                    if before_gate.get("judgement") != validation_gate.get("judgement")
                    else "value_changed"
                    if delta != "" and abs(float(delta)) > 1e-12
                    else "unchanged"
                ),
            }
        )
    return rows


def _plot_outputs(
    output: Path,
    interval_rows: Sequence[Mapping[str, Any]],
    anchor_rows: Sequence[Mapping[str, Any]],
    materials_rows: Sequence[Mapping[str, Any]],
    temporal_config: Mapping[str, Any],
) -> list[str]:
    apply_visual_style()
    frame = pd.DataFrame(interval_rows)
    figure_paths: list[str] = []
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    week_frame = frame[
        frame["experiment_type"] == "representative_week_counterfactual"
    ].copy()
    week_frame["week_group"] = week_frame["case_id"].str.replace(
        r"_day_\d+$", "", regex=True
    )
    week_cases = list(dict.fromkeys(week_frame["week_group"]))
    process_bounds = rate_ranges_from_config(temporal_config)
    for case_id in week_cases:
        data = week_frame[week_frame["week_group"] == case_id].reset_index(drop=True)
        x = range(len(data))
        fig, axes = plt.subplots(7, 1, figsize=(12, 15), sharex=True)
        axes[0].plot(x, data["electricity_price_eur_per_mwh"], color=COLORS["actual"])
        axes[0].set_ylabel("EUR/MWh")
        axes[1].plot(x, data["net_grid_import_mwh"] * 4.0, label="net grid", color=COLORS["grid"])
        axes[1].plot(x, data["internal_generation_mwh"] * 4.0, label="generation", color=COLORS["third_model"])
        axes[1].set_ylabel("MW")
        axes[1].legend(ncol=2)
        for column, label, asset in (
            ("sintering_plant_t_h", "SiFa", "sintering_plant"),
            ("blast_furnace_6_t_h", "BF6", "blast_furnace_6"),
            ("coking_plant_1_t_h", "KGF1", "coking_plant_1"),
            ("drp_pellet_input_t_h", "DRP", "drp_pellet_input"),
        ):
            series = data[column]
            lower, upper = process_bounds[asset]
            axes[2].plot(x, (series - lower) / (upper - lower), label=label)
        axes[2].set_ylabel("normalised")
        axes[2].legend(ncol=4)
        axes[3].step(x, data["eaf_start"], where="post", label="starts")
        axes[3].step(x, data["eaf_tap"], where="post", label="taps")
        axes[3].set_ylabel("binary")
        axes[3].legend(ncol=2)
        axes[4].plot(x, data["dri_inventory_t"], label="DRI")
        axes[4].plot(x, data["hot_iron_inventory_t"], label="hot iron")
        axes[4].plot(x, data["cold_slab_inventory_t"], label="cold slab")
        axes[4].set_ylabel("t")
        axes[4].legend(ncol=3)
        axes[5].plot(x, data["vn25_output_mw"], label="VN25 MW")
        axes[5].plot(x, data["vn25_named_ng_mwh_lhv"] * 4.0, label="VN25 NG MW")
        axes[5].plot(x, data["total_flare_mwh_lhv"] * 4.0, label="flare MW")
        axes[5].set_ylabel("MW")
        axes[5].legend(ncol=3)
        cumulative_product = data.groupby("day_index")["final_product_t"].cumsum()
        day_offsets = data.groupby("day_index")["final_product_t"].sum().cumsum().shift(fill_value=0.0)
        cumulative_route = cumulative_product + data["day_index"].map(day_offsets)
        axes[6].plot(x, cumulative_route / 1_000.0, color=COLORS["third_model"])
        axes[6].set_ylabel("kt product")
        axes[6].set_xlabel("quarter-hour in causal week")
        fig.suptitle(
            f"Deterministic C1 behaviour — {case_id}\n"
            "counterfactual QH point path; 24 h execution / 48 h physical; maintenance excluded"
        )
        stem = figures / f"week-dashboard-{case_id}"
        save_figure(fig, stem, save_pdf=False)
        plt.close(fig)
        figure_paths.append(str(stem.with_suffix(".png").relative_to(REPO_ROOT)))
    synthetic = frame[frame["experiment_type"] == "synthetic_paired_counterfactual"]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    for case_id, data in synthetic.groupby("case_id", sort=False):
        axes[0].plot(data["interval"], data["electricity_price_eur_per_mwh"], label=case_id)
        axes[1].plot(data["interval"], data["drp_pellet_input_t_h"], label=case_id)
        axes[2].step(data["interval"], data["eaf_start"].cumsum(), where="post", label=case_id)
    axes[0].set_ylabel("EUR/MWh")
    axes[1].set_ylabel("DRP t/h")
    axes[2].set_ylabel("cum. starts")
    axes[2].set_xlabel("quarter-hour")
    axes[0].legend(ncol=3)
    stem = figures / "synthetic-price-regime-comparison"
    save_figure(fig, stem, save_pdf=False)
    plt.close(fig)
    figure_paths.append(str(stem.with_suffix(".png").relative_to(REPO_ROOT)))
    comparable = pd.DataFrame(anchor_rows)
    comparable = comparable[
        comparable["relative_deviation_annualised"].astype(str) != ""
    ].copy()
    comparable["relative_deviation_annualised"] = pd.to_numeric(
        comparable["relative_deviation_annualised"]
    )
    comparable = comparable.reindex(
        comparable["relative_deviation_annualised"].abs().sort_values().index
    ).tail(20)
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(comparable["metric"], 100 * comparable["relative_deviation_annualised"], color=COLORS["main_model"])
    ax.axvline(0.0, color=COLORS["benchmark"], linewidth=1)
    ax.set_xlabel("provisional annualised deviation (%)")
    stem = figures / "partial-year-anchor-deviations"
    save_figure(fig, stem, save_pdf=False)
    plt.close(fig)
    figure_paths.append(str(stem.with_suffix(".png").relative_to(REPO_ROOT)))
    materials = pd.DataFrame(materials_rows)
    materials = materials[~materials["material_flow"].str.endswith("_total")]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(materials["material_flow"], materials["model_cumulative_t"] / 1e6, color=COLORS["third_model"])
    ax.set_xlabel("cumulative material over 8,688 h (Mt)")
    stem = figures / "c1-import-and-origin-summary"
    save_figure(fig, stem, save_pdf=False)
    plt.close(fig)
    figure_paths.append(str(stem.with_suffix(".png").relative_to(REPO_ROOT)))
    if len(figure_paths) > 7:
        raise TemporalRepairError("Figure contract exceeded seven figures.")
    return figure_paths


def _plot_requested_week_outputs(
    output: Path,
    interval_rows: Sequence[Mapping[str, Any]],
    anchor_rows: Sequence[Mapping[str, Any]],
    materials_rows: Sequence[Mapping[str, Any]],
    temporal_config: Mapping[str, Any],
) -> list[str]:
    """Create the selected-week behaviour pack requested for current C1 evidence."""

    apply_visual_style()
    frame = pd.DataFrame(interval_rows)
    week = frame[frame["experiment_type"] == "representative_week_counterfactual"].copy()
    week["week_group"] = week["case_id"].str.replace(r"_day_\d+$", "", regex=True)
    week["week_id"] = week["week_group"].str.replace(
        r"__(perfect_foresight_D|price_insensitive)$", "", regex=True
    )
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    paths: list[str] = []
    bounds = rate_ranges_from_config(temporal_config)

    def save(fig: Any, name: str) -> None:
        candidate = (figures / name).with_suffix(".png")
        # Keep the generated artifact portable on Windows hosts that still
        # enforce the legacy MAX_PATH limit.  The hash keeps shortened names
        # deterministic and the package manifest retains the exact selection.
        if len(name) > 72 or len(str(candidate.resolve())) >= 240:
            name = f"{name[:48]}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]}"
        stem = figures / name
        save_figure(fig, stem, save_pdf=False)
        plt.close(fig)
        paths.append(str(stem.with_suffix(".png").relative_to(REPO_ROOT)))

    for case_id, full in week.groupby("week_group", sort=False):
        data = full.reset_index(drop=True).iloc[:288]
        x = range(len(data))
        fig, axes = plt.subplots(9, 1, figsize=(12, 18), sharex=True)
        axes[0].plot(x, data["electricity_price_eur_per_mwh"], color=COLORS["actual"])
        axes[0].set_ylabel("EUR/MWh")
        grid = data["net_grid_import_mwh"] * 4.0
        generation = data["internal_generation_mwh"] * 4.0
        axes[1].plot(x, grid, label=f"net grid (avg {grid.mean():.1f} MW)", color=COLORS["grid"])
        axes[1].plot(x, generation, label=f"generation (avg {generation.mean():.1f} MW)", color=COLORS["third_model"])
        axes[1].set_ylabel("MW")
        axes[1].legend(ncol=2)
        plant_specs = (
            ("sintering_plant_t_h", "SiFa", "sintering_plant", COLORS["main_model"]),
            ("blast_furnace_6_t_h", "BF6", "blast_furnace_6", COLORS["third_model"]),
            ("coking_plant_1_t_h", "KGF1", "coking_plant_1", COLORS["actual"]),
            ("drp_pellet_input_t_h", "DRP", "drp_pellet_input", COLORS["grid"]),
        )
        for axis, (column, label, asset, color) in zip(axes[2:6], plant_specs):
            lower, upper = bounds[asset]
            axis.plot(x, data[column], color=color, label=f"{label} ({lower:.1f}–{upper:.1f} t/h)")
            axis.axhline(lower, color=COLORS["benchmark"], linewidth=0.8)
            axis.axhline(upper, color=COLORS["benchmark"], linewidth=0.8)
            axis.set_ylabel("t/h")
            axis.legend(loc="upper right")
        axes[6].step(x, data["eaf_on"], where="post", color=COLORS["main_model"], label="EAF occupied")
        axes[6].set_ylim(-0.05, 1.05)
        axes[6].set_ylabel("on/off")
        axes[6].legend(loc="upper right")
        for column, capacity, label, color in (
            ("dri_inventory_t", "dri_capacity_t", "DRI", COLORS["main_model"]),
            ("hot_iron_inventory_t", "hot_iron_capacity_t", "hot iron", COLORS["third_model"]),
            ("cold_slab_inventory_t", "cold_slab_capacity_t", "cold slab", COLORS["actual"]),
        ):
            axes[7].plot(x, 100.0 * data[column] / data[capacity], label=label, color=color)
        axes[7].set_ylabel("SOC (%)")
        axes[7].legend(ncol=3)
        axes[8].plot(x, data["vn25_output_mw"], label="VN25 output", color=COLORS["main_model"])
        axes[8].plot(x, data["vn25_named_ng_mwh_lhv"] * 4.0, label="named NG input", color=COLORS["third_model"])
        axes[8].plot(x, data["vn25_wag_mwh_lhv"] * 4.0, label="WAG input", color=COLORS["actual"])
        axes[8].set_ylabel("MW")
        axes[8].set_xlabel("quarter-hour (first three days)")
        axes[8].legend(ncol=3)
        fig.suptitle(f"Deterministic C1 behaviour — {case_id}\nQH solve; first three days; maintenance excluded")
        save(fig, f"week-dashboard-{case_id}")

    response_assets = {
        "Basic Oxygen Plant": "bof_electricity_mw",
        "Blast Furnace 6": "bf_electricity_mw",
        "Coking Plant 2": None,
        "DRP": "drp_pellet_input_t_h",
        "DSP Plant": "dsp_electricity_mw",
        "EAF": "eaf_electricity_mw",
        "Hot Strip Mill": "hsm_electricity_mw",
        "Linde Plant": "linde_electricity_mw",
        "Pelletizing Plant": "pefa_electricity_mw",
        "Sintering Plant": "sinter_electricity_mw",
        "VN25 generator": "vn25_output_mw",
    }
    paired_response_rows: list[dict[str, Any]] = []
    for week_id, full in week.groupby("week_id", sort=False):
        pf_full = full[full["strategy_id"] == "perfect_foresight_D"].sort_values(
            "timestamp_utc"
        ).reset_index(drop=True)
        pi_full = full[full["strategy_id"] == "price_insensitive"].sort_values(
            "timestamp_utc"
        ).reset_index(drop=True)
        if len(pf_full) != len(pi_full) or not pf_full["timestamp_utc"].equals(
            pi_full["timestamp_utc"]
        ):
            raise TemporalRepairError(
                f"PF and price-insensitive support differ for {week_id}."
            )
        price = pf_full["electricity_price_eur_per_mwh"].astype(float)
        cheap_limit = float(price.quantile(0.25))
        expensive_limit = float(price.quantile(0.75))
        correlation_matrix: list[list[float]] = []
        quartile_matrix: list[list[float]] = []
        for asset, column in response_assets.items():
            correlation_row = [math.nan, math.nan]
            quartile_row = [math.nan, math.nan, math.nan]
            if column is not None:
                pf_values = pf_full[column].astype(float)
                pi_values = pi_full[column].astype(float)
                delta = pf_values - pi_values
                combined_span = float(
                    max(pf_values.max(), pi_values.max())
                    - min(pf_values.min(), pi_values.min())
                )
                if float(delta.std()) > 1e-6:
                    correlation_row[0] = float(delta.corr(price))
                    hourly = pd.DataFrame(
                        {
                            "delta": delta.to_numpy(),
                            "price": price.to_numpy(),
                        },
                        index=pd.to_datetime(pf_full["timestamp_utc"], utc=True),
                    ).resample("h").mean()
                    if float(hourly["delta"].std()) > 1e-6:
                        correlation_row[1] = float(
                            hourly["delta"].corr(hourly["price"])
                        )
                cheap_delta = float(delta[price <= cheap_limit].mean())
                expensive_delta = float(delta[price >= expensive_limit].mean())
                if combined_span > 1e-6:
                    quartile_row = [
                        100.0 * cheap_delta / combined_span,
                        100.0 * expensive_delta / combined_span,
                        100.0 * (cheap_delta - expensive_delta) / combined_span,
                    ]
                paired_response_rows.append(
                    {
                        "week_id": week_id,
                        "asset": asset,
                        "activity_column": column,
                        "correlation_price_pf_minus_pi_qh": correlation_row[0],
                        "correlation_price_pf_minus_pi_h": correlation_row[1],
                        "cheap_q25_price_limit_eur_per_mwh": cheap_limit,
                        "expensive_q75_price_limit_eur_per_mwh": expensive_limit,
                        "mean_pf_minus_pi_cheapest_q25": cheap_delta,
                        "mean_pf_minus_pi_expensive_q25": expensive_delta,
                        "combined_observed_range": combined_span,
                        "cheap_minus_expensive_pct_observed_range": quartile_row[2],
                    }
                )
            correlation_matrix.append(correlation_row)
            quartile_matrix.append(quartile_row)
        fig, axes = plt.subplots(
            1,
            2,
            figsize=(15, 7),
            gridspec_kw={"width_ratios": (2, 3)},
        )
        correlation_image = axes[0].imshow(
            correlation_matrix,
            vmin=-1,
            vmax=1,
            cmap="coolwarm",
            aspect="auto",
        )
        quartile_image = axes[1].imshow(
            quartile_matrix,
            vmin=-100,
            vmax=100,
            cmap="coolwarm",
            aspect="auto",
        )
        for axis in axes:
            axis.set_yticks(range(len(response_assets)), list(response_assets))
        axes[1].tick_params(labelleft=False)
        axes[0].set_xticks((0, 1), ("corr QH", "corr H"))
        axes[1].set_xticks(
            (0, 1, 2),
            (
                "PF-PI cheap Q25",
                "PF-PI expensive Q25",
                "cheap minus expensive",
            ),
            rotation=20,
            ha="right",
        )
        for axis, matrix, suffix in (
            (axes[0], correlation_matrix, ""),
            (axes[1], quartile_matrix, "%"),
        ):
            for y, row in enumerate(matrix):
                for x_index, item in enumerate(row):
                    axis.text(
                        x_index,
                        y,
                        "N/A" if math.isnan(item) else f"{item:.2f}{suffix}",
                        ha="center",
                        va="center",
                    )
        fig.colorbar(correlation_image, ax=axes[0], label="corr(price, PF-PI)")
        fig.colorbar(
            quartile_image,
            ax=axes[1],
            label="share of combined observed operating range",
        )
        axes[0].set_title("Paired response association")
        axes[1].set_title("Paired response by realised-price quartile")
        fig.suptitle(
            f"C1 perfect foresight minus price-insensitive response - {week_id}\n"
            "Consumers: negative correlation and positive cheap-minus-expensive are aligned; "
            "VN25 signs reverse"
        )
        save(fig, f"paired-price-response-{week_id}")

        if "high_volatility" not in week_id:
            continue
        pf = full[full["strategy_id"] == "perfect_foresight_D"].reset_index(drop=True).iloc[:288]
        pi = full[full["strategy_id"] == "price_insensitive"].reset_index(drop=True).iloc[:288]
        fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(pf["eaf_electricity_mw"] - pi["eaf_electricity_mw"], color=COLORS["main_model"])
        axes[0].axhline(0.0, color=COLORS["benchmark"], linewidth=0.8)
        axes[0].set_ylabel("EAF ΔMW")
        axes[1].plot(pf["hsm_electricity_mw"] - pi["hsm_electricity_mw"], color=COLORS["third_model"])
        axes[1].axhline(0.0, color=COLORS["benchmark"], linewidth=0.8)
        axes[1].set_ylabel("HSM ΔMW")
        axes[2].plot(pf["electricity_price_eur_per_mwh"].to_numpy(), color=COLORS["actual"])
        axes[2].set_ylabel("EUR/MWh")
        axes[2].set_xlabel("quarter-hour (first three days)")
        axes[0].set_title(f"Perfect foresight minus price-insensitive load — {week_id}")
        plt.close(fig)
        for plant, column, color in (
            ("EAF", "eaf_electricity_mw", COLORS["main_model"]),
            ("HSM", "hsm_electricity_mw", COLORS["third_model"]),
        ):
            fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
            axes[0].plot(
                pf[column] - pi[column],
                color=color,
                label=f"{plant} PF minus price-insensitive",
            )
            axes[0].axhline(0.0, color=COLORS["benchmark"], linewidth=0.8)
            axes[0].set_ylabel("delta load (MW)")
            axes[0].legend(loc="upper right")
            axes[1].plot(
                pf["electricity_price_eur_per_mwh"].to_numpy(),
                color=COLORS["actual"],
            )
            axes[1].set_ylabel("EUR/MWh")
            axes[1].set_xlabel("quarter-hour (first three days)")
            axes[0].set_title(
                f"{plant} perfect foresight minus price-insensitive load - {week_id}"
            )
            save(fig, f"{plant.lower()}-delta-vs-price-insensitive-{week_id}")

    volatile_pf = week[
        week["week_id"].str.contains("high_volatility")
        & (week["strategy_id"] == "perfect_foresight_D")
    ].reset_index(drop=True)
    if volatile_pf.empty:
        raise TemporalRepairError("High-volatility PF week missing for site-load plot.")
    generation = (volatile_pf["internal_generation_mwh"] * 4.0).clip(lower=0.0)
    net_import = (volatile_pf["net_grid_import_mwh"] * 4.0).clip(lower=0.0)
    site_load = generation + net_import
    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(volatile_pf))
    ax.stackplot(
        x,
        generation,
        net_import,
        labels=(
            f"VN25/internal generation (avg {generation.mean():.1f} MW)",
            f"net grid import (avg {net_import.mean():.1f} MW)",
        ),
        colors=(COLORS["third_model"], COLORS["grid"]),
        alpha=0.75,
    )
    ax.plot(
        x,
        site_load,
        color=COLORS["actual"],
        linewidth=1.1,
        label=f"represented site load (avg {site_load.mean():.1f} MW)",
    )
    ax.set_ylabel("MW")
    ax.set_xlabel("quarter-hour (full week)")
    ax.set_title("Represented site load supply - high-volatility perfect foresight week")
    ax.legend(ncol=1, loc="upper right")
    save(fig, "stacked-site-load-high-volatility-perfect-foresight")

    _write_csv(output / "paired_price_response_metrics.csv", paired_response_rows)
    storage_rows: list[tuple[str, float]] = []
    for (week_id, strategy), data in week.groupby(["week_id", "strategy_id"], sort=False):
        for label, column, capacity in (
            ("DRI", "dri_inventory_t", "dri_capacity_t"),
            ("hot iron", "hot_iron_inventory_t", "hot_iron_capacity_t"),
            ("cold slab", "cold_slab_inventory_t", "cold_slab_capacity_t"),
        ):
            soc = 100.0 * data[column] / data[capacity]
            correlation = float(soc.corr(data["electricity_price_eur_per_mwh"])) if soc.nunique() > 1 else math.nan
            storage_rows.append((f"{week_id} | {strategy} | {label}", correlation))
    fig, ax = plt.subplots(figsize=(12, 8))
    image = ax.imshow([[item[1]] for item in storage_rows], vmin=-1, vmax=1, cmap="coolwarm", aspect="auto")
    ax.set_yticks(range(len(storage_rows)), [item[0] for item in storage_rows])
    ax.set_xticks([0], ["corr(price, SOC)"])
    fig.colorbar(image, ax=ax)
    save(fig, "storage-price-correlations")

    example = week[week["strategy_id"] == "perfect_foresight_D"].copy()
    example = example[example["week_id"] == example["week_id"].iloc[0]].iloc[:96]
    demand = example["net_grid_import_mwh"] * 4.0
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(example["electricity_price_eur_per_mwh"].to_numpy(), color=COLORS["actual"])
    axes[0].set_ylabel("DA price (EUR/MWh)")
    axes[1].step(range(len(demand)), demand, where="post", color=COLORS["main_model"], label="PF ideal net demand")
    axes[1].set_ylabel("MW")
    axes[1].set_xlabel("quarter-hour")
    axes[1].legend()
    save(fig, "example-day-ideal-demand-and-da-price")
    fig, ax = plt.subplots(figsize=(9, 6))
    order = example["electricity_price_eur_per_mwh"].to_numpy().argsort()
    ax.plot(example["electricity_price_eur_per_mwh"].to_numpy()[order], demand.to_numpy()[order], marker="o", color=COLORS["main_model"])
    ax.set_xlabel("counterfactual DA price (EUR/MWh)")
    ax.set_ylabel("PF net demand (MW)")
    ax.set_title("Deterministic price–demand diagnostic (not a submitted bid curve)")
    save(fig, "example-day-price-demand-diagnostic")

    comparable = pd.DataFrame(anchor_rows)
    deviation_column = (
        "relative_deviation_annualised"
        if "relative_deviation_annualised" in comparable
        else "relative_deviation"
    )
    comparable = comparable[comparable[deviation_column].astype(str) != ""].copy()
    comparable[deviation_column] = pd.to_numeric(comparable[deviation_column])
    comparable = comparable.reindex(comparable[deviation_column].abs().sort_values().index).tail(20)
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(comparable["metric"], 100 * comparable[deviation_column], color=COLORS["main_model"])
    ax.axvline(0.0, color=COLORS["benchmark"], linewidth=1)
    ax.set_xlabel("provisional annualised deviation (%)")
    save(fig, "partial-year-anchor-deviations")
    materials = pd.DataFrame(materials_rows)
    materials = materials[~materials["material_flow"].str.endswith("_total")]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(materials["material_flow"], materials["model_cumulative_t"] / 1e6, color=COLORS["third_model"])
    ax.set_xlabel("cumulative material over 8,688 h (Mt)")
    save(fig, "c1-import-and-origin-summary")
    if len(paths) > 40:
        raise TemporalRepairError("Figure contract exceeded forty figures.")
    return paths


def build_standard_figure_package(
    output: Path,
    figure_paths: Sequence[str],
) -> dict[str, Any]:
    """Package the governed default figure selection for repeatable delivery.

    The plotting routine remains the single source of the figures.  This
    function adds a stable manifest and archive so future requests receive the
    complete established selection unless a different subset is requested.
    """

    expected_prefix_counts = {
        "week-dashboard-": 8,
        "paired-price-response-": 4,
        "eaf-delta-vs-price-insensitive-": 1,
        "hsm-delta-vs-price-insensitive-": 1,
        "stacked-site-load-": 1,
        "storage-price-correlations": 1,
        "example-day-ideal-demand-and-da-price": 1,
        "example-day-price-demand-diagnostic": 1,
        "partial-year-anchor-deviations": 1,
        "c1-import-and-origin-summary": 1,
    }
    resolved = [REPO_ROOT / Path(path) for path in figure_paths]
    missing = [str(path) for path in resolved if not path.is_file()]
    if missing:
        raise TemporalRepairError(
            f"Standard figure package is missing rendered figures: {missing}"
        )
    names = [path.stem for path in resolved]
    for prefix, expected in expected_prefix_counts.items():
        observed = sum(name.startswith(prefix) for name in names)
        if observed != expected:
            raise TemporalRepairError(
                "Standard figure package selection is incomplete for "
                f"{prefix}: expected {expected}, observed {observed}."
            )

    package_dir = output / "figure_package"
    package_dir.mkdir(exist_ok=True)
    entries = []
    for path in resolved:
        relative = path.relative_to(output)
        entries.append(
            {
                "filename": path.name,
                "run_relative_path": str(relative).replace("\\", "/"),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    manifest = {
        "package_version": STANDARD_FIGURE_PACKAGE_VERSION,
        "selection_policy": (
            "default_complete_selection_unless_explicit_subset_or_alternative_requested"
        ),
        "figure_count": len(entries),
        "expected_selection": expected_prefix_counts,
        "figures": entries,
    }
    manifest_path = package_dir / "figure_package_manifest.json"
    _write_json(manifest_path, manifest)
    readme_path = package_dir / "README.md"
    readme_path.write_text(
        "# Deterministic plant-behaviour figure package\n\n"
        f"Package contract: `{STANDARD_FIGURE_PACKAGE_VERSION}`.\n\n"
        "This is the default complete figure selection. It is generated for "
        "future figure requests unless a different selection is explicitly requested.\n",
        encoding="utf-8",
    )
    archive_path = output / f"{STANDARD_FIGURE_PACKAGE_VERSION}.zip"
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(manifest_path, "figure_package_manifest.json")
        archive.write(readme_path, "README.md")
        for path in resolved:
            archive.write(path, f"figures/{path.name}")
    return {
        "package_version": STANDARD_FIGURE_PACKAGE_VERSION,
        "figure_count": len(entries),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "archive": str(archive_path.relative_to(REPO_ROOT)),
        "archive_sha256": _sha256(archive_path),
    }


def run_behaviour_anchor_validation(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "behaviour_anchor_validation_v1",
    skip_partial_year_replay: bool = False,
    annual_totals_source: str | Path | None = None,
    before_run_root: str | Path | None = None,
) -> dict[str, Any]:
    validation_config = load_validation_config(config_path)
    temporal_config = load_temporal_repair_config(
        REPO_ROOT / str(validation_config["base_temporal_config"])
    )
    _activate_c1_calibration_bundle(temporal_config, validation_config)
    output = REPO_ROOT / str(validation_config["output_root"]) / run_id
    if output.exists() and any(output.iterdir()):
        raise TemporalRepairError(f"Refusing to overwrite non-empty run folder: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "solver_logs").mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)
    planned = validation_config["planned_run"]
    manifest = {
        "run_id": run_id,
        "run_family_id": validation_config["run_family_id"],
        "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
        "calendar_contract_version": CALENDAR_CONTRACT_VERSION,
        "objective_mode": OBJECTIVE_MODE,
        "output_root": str(output),
        "output_policy": validation_config["output_policy"],
        "run_class": validation_config["run_class"],
        "lineage_role": validation_config["lineage_role"],
        "retention_status": validation_config["retention_status"],
        "git_eligible": False,
        "planned_model_build_count_upper_bound": planned["maximum_model_builds"],
        "planned_solve_attempt_count_upper_bound": planned["maximum_solve_attempts"],
        "estimated_runtime_minutes": planned["estimated_runtime_minutes"],
        "estimated_output_size_mb_upper_bound": planned["estimated_output_size_mb_upper_bound"],
        "planned_artifact_count_upper_bound": planned["planned_artifact_count_upper_bound"],
        "maximum_figure_count": planned["maximum_figure_count"],
        "deterministic_only": True,
        "maintenance_hours_represented": 0,
        "annual_availability_comparable": False,
        "major_outage_certified": False,
        "full_four_week_matrix_authorized": False,
        "active_c1_calibration_bundle": validation_config.get(
            "active_c1_calibration_bundle", {}
        ),
        "annual_totals_source": (
            "replay_within_run"
            if annual_totals_source is None
            else str(annual_totals_source)
        ),
        "before_run_root": (
            "not_applicable_no_repair_comparison"
            if before_run_root is None
            else str(before_run_root)
        ),
        "started_at_utc": started.isoformat(),
    }
    _write_json(output / "run_manifest.json", manifest)
    contract_rows = expected_plant_response_contract(temporal_config)
    _write_csv(output / "expected_plant_response_contract.csv", contract_rows)
    print(
        json.dumps(
            {
                "before_first_solve": True,
                "output_root": str(output),
                "expected_file_count_upper_bound": planned["planned_artifact_count_upper_bound"],
                "expected_size_mb_upper_bound": planned["estimated_output_size_mb_upper_bound"],
                "output_policy": validation_config["output_policy"],
                "run_class": validation_config["run_class"],
                "lineage_role": validation_config["lineage_role"],
                "retention_status": validation_config["retention_status"],
                "git_eligible": False,
                "expected_model_builds_upper_bound": planned["maximum_model_builds"],
                "expected_solver_attempts_upper_bound": planned["maximum_solve_attempts"],
                "expected_runtime_minutes": planned["estimated_runtime_minutes"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    attempts: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    kpi_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    case_manifest: list[dict[str, Any]] = []
    model_builds = 0
    judgement = "invalid_validation_run"
    reason = ""
    try:
        context = prepare_temporal_context(temporal_config)
        initial = replace(
            initial_temporal_state(temporal_config),
            episode_id="deterministic_behaviour_validation",
            eaf_quota_period_id="behaviour_week_000",
            eaf_quota_target_taps=quota_period_target_taps(0),
            eaf_quota_completed_taps=0,
        )
        continuation = _calibrate_continuation(
            context, initial, temporal_config, output, attempts
        )
        model_builds += 3
        negative_fixed_count_oracle_rows: list[dict[str, Any]] = []
        for case_id, prices in synthetic_price_profiles(validation_config).items():
            diagnostic_warm_source = None
            if case_id == "negative_price_block":
                (
                    diagnostic_warm_source,
                    negative_fixed_count_oracle_rows,
                ) = _negative_price_fixed_count_oracle(
                    context,
                    initial,
                    temporal_config,
                    validation_config,
                    output,
                    prices=prices,
                    continuation=continuation,
                    attempt_rows=attempts,
                )
                model_builds += 3
            model, result, _, dispatch, kpis, checks = _solve_day(
                context,
                initial,
                temporal_config,
                validation_config,
                output,
                case_id=f"synthetic_{case_id}",
                experiment_type="synthetic_paired_counterfactual",
                day_index=1,
                prices=prices,
                continuation=continuation,
                remaining_days=7,
                warm_source=diagnostic_warm_source,
                start_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
                attempt_rows=attempts,
                extend_time_limited_diagnostic=True,
            )
            model_builds += 1
            interval_rows.extend(dispatch)
            kpi_rows.extend(kpis)
            validation_rows.extend(checks)
            result_rows.append(result)
            case_manifest.append(
                {
                    "experiment_type": "synthetic_paired_counterfactual",
                    "case_id": f"synthetic_{case_id}",
                    "same_initial_state": True,
                    "only_electricity_price_changed": True,
                    "execution_hours": 24,
                    "physical_horizon_hours": 48,
                    "future_price_in_objective": False,
                    "initial_state_sha256": result["state_before_sha256"],
                }
            )
        validation_rows.extend(
            paired_counterfactual_validation_rows(
                kpi_rows,
                result_rows,
                expected_state_sha256=_canonical_json_sha256(initial.snapshot()),
                negative_fixed_count_oracle_rows=negative_fixed_count_oracle_rows,
            )
        )
        week_manifest, week_prices = load_representative_week_prices(validation_config)
        case_manifest.extend(week_manifest)
        strategy_specs = validation_config["representative_week_strategies"]
        for week_number, manifest_row in enumerate(week_manifest, start=1):
            week_id = manifest_row["case_id"]
            week_start = datetime.fromisoformat(manifest_row["start_date"]).replace(tzinfo=timezone.utc)
            for strategy_number, strategy_spec in enumerate(strategy_specs, start=1):
                strategy_id = str(strategy_spec["strategy_id"])
                state = replace(
                    initial,
                    episode_id=f"{week_id}__{strategy_id}",
                    eaf_quota_period_id=(
                        f"behaviour_week_{week_number:03d}_{strategy_number:02d}"
                    ),
                    eaf_quota_target_taps=quota_period_target_taps(0),
                    eaf_quota_completed_taps=0,
                )
                warm_model = None
                for day_index in range(1, 8):
                    realised_prices = week_prices[week_id][
                        (day_index - 1) * 96 : day_index * 96
                    ]
                    if strategy_id == "price_insensitive":
                        planning_prices = (float(strategy_spec["flat_price_eur_per_mwh"]),) * 96
                    else:
                        planning_prices = realised_prices
                    before = state
                    model, result, _, dispatch, kpis, checks = _solve_day(
                        context,
                        state,
                        temporal_config,
                        validation_config,
                        output,
                        case_id=f"{week_id}__{strategy_id}_day_{day_index}",
                        experiment_type="representative_week_counterfactual",
                        day_index=day_index,
                        prices=planning_prices,
                        evaluation_prices=realised_prices,
                        strategy_id=strategy_id,
                        continuation=continuation,
                        remaining_days=8 - day_index,
                        warm_source=warm_model,
                        start_utc=week_start + timedelta(days=day_index - 1),
                        attempt_rows=attempts,
                    )
                    model_builds += 1
                    state = advance_temporal_state(
                        context,
                        model,
                        state,
                        last_timestamp_utc=(
                            week_start
                            + timedelta(days=day_index)
                            - timedelta(minutes=15)
                        ).isoformat(),
                    )
                    state_rows.append(
                        {
                            **state_handoff_row(
                                before, state, run_case=result["case_id"]
                            ),
                            "configuration": "C1",
                            "strategy_id": strategy_id,
                        }
                    )
                    interval_rows.extend(dispatch)
                    kpi_rows.extend(kpis)
                    validation_rows.extend(checks)
                    result_rows.append(result)
                    warm_model = model
                    _write_json(
                        output / "certification_progress.json",
                        {
                            "phase": result["case_id"],
                            "model_build_count": model_builds,
                            "solve_attempt_count": len(attempts),
                            "full_four_week_matrix_authorized": False,
                        },
                    )
                if int(state.eaf_quota_target_taps) - int(state.eaf_quota_completed_taps) != 0:
                    raise TemporalRepairError(
                        f"{week_id}/{strategy_id} did not close its causal EAF quota."
                    )
        kpi_rows.extend(
            representative_week_kpis(
                interval_rows,
                temporal_config,
                validation_config,
            )
        )
        _write_csv(output / "price_regime_case_manifest.csv", case_manifest)
        _write_csv(output / "interval_dispatch.csv", interval_rows)
        _write_csv(output / "plant_response_kpis.csv", kpi_rows)
        _write_csv(output / "behaviour_validation_results.csv", validation_rows)
        _write_csv(output / "solver_case_results.csv", result_rows)
        _write_csv(output / "state_handoff_audit.csv", state_rows)
        _write_csv(
            output / "representative_week_economics.csv",
            representative_week_economic_rows(result_rows),
        )
        _write_csv(
            output / "interval_dispatch_hourly_aggregated.csv",
            hourly_aggregate_rows(interval_rows),
        )
        _write_csv(
            output / "configuration_strategy_coverage.csv",
            [
                {
                    "configuration": configuration,
                    "strategy_id": strategy,
                    "week_count": 4 if configuration == "C1" else 0,
                    "status": (
                        "solved_current_scalar_temporal_contract"
                        if configuration == "C1"
                        else "not_available_pending_c0_scalar_temporal_contract"
                    ),
                    "claim_allowed": configuration == "C1",
                }
                for configuration in ("C0", "C1")
                for strategy in ("perfect_foresight_D", "price_insensitive")
            ],
        )

        annual_nested = output
        if annual_totals_source is not None:
            totals_path = Path(annual_totals_source)
            if not totals_path.is_absolute():
                totals_path = REPO_ROOT / totals_path
            if not totals_path.exists():
                raise TemporalRepairError(
                    f"Configured annual totals evidence is missing: {totals_path}"
                )
        elif skip_partial_year_replay:
            source = REPO_ROOT / str(validation_config["partial_year_source_run"])
            totals_path = source / "cumulative_execution_totals.json"
            if not totals_path.exists():
                raise TemporalRepairError(
                    "The existing 8,688-hour run lacks cumulative energy/material totals; "
                    "partial-year replay is required."
                )
        else:
            annual_decision = run_causal_flat_year(
                config_path=REPO_ROOT / str(validation_config["base_temporal_config"]),
                run_id="a8688",
                stop_after_contract_days=int(validation_config["partial_year_replay_days"]),
                output_root_override=annual_nested,
            )
            if annual_decision["status"] != "pass":
                raise TemporalRepairError(
                    f"Partial-year replay failed: {annual_decision}"
                )
            totals_path = annual_nested / "a8688" / "cumulative_execution_totals.json"
        cumulative = json.loads(totals_path.read_text(encoding="utf-8"))
        totals = {key: float(item) for key, item in cumulative["totals"].items()}
        executed_hours = int(cumulative["executed_hours"])
        if executed_hours != 8688:
            raise TemporalRepairError(f"Partial-year evidence covers {executed_hours}, not 8,688 hours.")
        annual_rows, annual_gate = annual_operational_anchor_rows(
            totals,
            evaluation_id="normal_operation_maintenance_excluded_partial_8688h",
            executed_hours=executed_hours,
            period_classification="partial_year_8688h",
            calendar_coverage="362 sequential causal days; 8,688 h; maintenance excluded",
        )
        annual_rows.extend(
            supplemental_annual_operational_rows(
                totals,
                executed_hours=executed_hours,
                hsm_final_t_per_t_slab=float(
                    context.c1_reference_routing["hsm_final_t_per_t_slab"]
                ),
            )
        )
        baseline_delta_rows = annual_anchor_delta_rows(
            annual_rows,
            baseline_id="steel_c5_phase5e_source_backed_anchor_closure_v1_20260727",
            baseline_values=_last_accepted_annual_values(),
        )
        anchor_worsening = unexpected_anchor_worsening(
            annual_rows,
            _last_accepted_annual_values(),
            relative_tolerance=float(
                temporal_config["deterministic_temporal_repair"]
                ["annual_anchor_worsening_tolerance_fraction"]
            ),
        )
        anchors = partial_anchor_rows(
            annual_rows,
            executed_hours,
            baseline_delta_rows,
        )
        materials = c1_external_materials_audit(totals, executed_hours=executed_hours)
        balances = balance_identity_rows(totals)
        _write_csv(output / "annual_anchor_results_partial_8688h.csv", anchors)
        current_anchors = current_anchor_level_rows(validation_config)
        _write_csv(
            output / "annual_anchor_results_by_level.csv",
            current_anchors,
        )
        _write_csv(
            output / "plant_level_anchor_results.csv",
            [row for row in anchors if row["family"] in {"material", "production", "WAG", "generator", "natural_gas", "electricity", "steam", "CO2"}],
        )
        _write_csv(output / "c1_external_materials_audit.csv", materials)
        _write_csv(output / "balance_identity_gate.csv", balances)
        figures = _plot_requested_week_outputs(
            output, interval_rows, current_anchors, materials, temporal_config
        )
        figure_package = build_standard_figure_package(output, figures)
        behaviour_failures = [row for row in validation_rows if row["status"] == "fail"]
        balance_failures = [row for row in balances if row["status"] == "fail"]
        material_failures = [row for row in materials if row["status"] == "fail"]
        if (
            behaviour_failures
            or balance_failures
            or material_failures
            or anchor_worsening
        ):
            judgement = "needs_bounded_fix"
            reason = (
                f"behaviour_failures={len(behaviour_failures)}, "
                f"balance_failures={len(balance_failures)}, "
                f"material_failures={len(material_failures)}"
                f", anchor_worsening={len(anchor_worsening)}"
            )
        else:
            judgement = "behaviour_validation_pass_anchor_coverage_partial"
            reason = "All predeclared behaviour and identity gates pass; anchors remain partial coverage."
        gate = {
            "judgement": judgement,
            "status": "pass" if judgement.startswith("behaviour_validation_pass") else "fail",
            "reason": reason,
            "behaviour_failure_count": len(behaviour_failures),
            "balance_failure_count": len(balance_failures),
            "material_failure_count": len(material_failures),
            "unexpected_anchor_worsening_count": len(anchor_worsening),
            "unexpected_anchor_worsening": anchor_worsening,
            "partial_year_anchor_identity_gate_pass": annual_gate["identity_gate_pass"],
            "annual_anchor_claim": "not_full_year_validated",
            "figure_count": len(figures),
            "figure_package": figure_package,
            "model_build_count": model_builds + (
                0
                if skip_partial_year_replay or annual_totals_source is not None
                else 365
            ),
            "solve_attempt_count_excluding_nested_annual": len(attempts),
            "full_four_week_matrix_authorized": False,
        }
        if before_run_root is None:
            before_after_rows = [
                {
                    "artifact": "not_applicable",
                    "comparison_key": "no_repair_baseline_supplied",
                    "metric": "comparison_status",
                    "before_value": "",
                    "after_value": "not_requested",
                    "delta_after_minus_before": "",
                    "before_status": "",
                    "after_status": "not_applicable",
                    "change_classification": "not_applicable",
                }
            ]
        else:
            before_after_rows = before_after_validation_delta(
                before_run_root,
                behaviour_rows=validation_rows,
                material_rows=materials,
                balance_rows=balances,
                validation_gate=gate,
            )
        _write_csv(output / "before_after_validation_delta.csv", before_after_rows)
        _write_json(output / "validation_gate.json", gate)
        _write_json(
            output / "run_summary.json",
            {**gate, "completed_at_utc": datetime.now(timezone.utc).isoformat()},
        )
        _write_json(
            output / "input_manifest.json",
            {
                "files": {
                    str(Path(config_path)): _sha256(Path(config_path)),
                    str(validation_config["base_temporal_config"]): _sha256(REPO_ROOT / str(validation_config["base_temporal_config"])),
                    str(validation_config["representative_week_source"]["root"]): "governed_directory_see_nested_manifest",
                    "annual_totals_source": _sha256(totals_path),
                },
                "git_head": _git_head(),
            },
        )
        _write_json(output / "code_version.json", {"git_head": _git_head(), "dirty_worktree": True})
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": run_id,
                "run_class": validation_config["run_class"],
                "lineage_role": validation_config["lineage_role"],
                "judgement": judgement,
                "git_eligible": False,
            },
        )
        (output / "resolved_config.yaml").write_text(
            yaml.safe_dump(validation_config, sort_keys=False), encoding="utf-8"
        )
        (output / "warnings_and_limitations.md").write_text(
            "# Warnings and limitations\n\n"
            "- The four governed price weeks are counterfactual QH overlays, not observed historical QH truth.\n"
            "- Perfect foresight is D-only: each executed day sees its realised within-day QH path, never future days.\n"
            "- Price-insensitive schedules use a fixed 80 EUR/MWh planning price and are revalued on the same realised QH path.\n"
            "- C0 is not solved because no current C0 scalar rolling-temporal contract exists; C0 cells are explicit N/A, not copied historical evidence.\n"
            "- The annual anchor table covers 8,688 hours and is only a provisional annualised diagnostic.\n"
            "- Maintenance and major outages are excluded, so annual availability is not comparable.\n"
            "- Anchors never enter constraints or objectives and no residual plug is added.\n"
            "- The day-363 infeasibility is not repaired by this validation.\n",
            encoding="utf-8",
        )
        reproduce_parts = [
            "python",
            "scripts/Data/04_Steel_Test_Case/run_s4_4c6_deterministic_behaviour_anchor_validation.py",
            "--run-id",
            run_id,
        ]
        if annual_totals_source is not None:
            reproduce_parts.extend(("--annual-totals-source", str(annual_totals_source)))
        if before_run_root is not None:
            reproduce_parts.extend(("--before-run-root", str(before_run_root)))
        reproduce_command = " ".join(reproduce_parts)
        (output / "README.md").write_text(
            "# Deterministic selected-week behaviour and partial-year anchor validation\n\n"
            f"Judgement: `{judgement}`.\n\n"
            "Reproduce with:\n\n"
            f"`{reproduce_command}`\n\n"
            "The four C1 week dashboards compare D-only perfect foresight with a fixed-price price-insensitive benchmark. "
            "C0 remains unavailable under the current scalar temporal contract. "
            "The 8,688-hour anchor outputs are not a full-year validation.\n",
            encoding="utf-8",
        )
    except TemporalPhysicalInfeasibility as exc:
        judgement = "invalid_validation_run"
        reason = f"solver-proven physical infeasibility: {exc}"
        _write_json(output / "validation_gate.json", {"judgement": judgement, "status": "fail", "reason": reason, "full_four_week_matrix_authorized": False})
    except Exception as exc:
        judgement = "invalid_validation_run"
        reason = f"{type(exc).__name__}: {exc}"
        _write_json(output / "validation_gate.json", {"judgement": judgement, "status": "fail", "reason": reason, "full_four_week_matrix_authorized": False})
    manifest.update(
        {
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "actual_model_build_count_excluding_nested_annual": model_builds,
            "actual_solve_attempt_count_excluding_nested_annual": len(attempts),
            "judgement": judgement,
            "full_four_week_matrix_authorized": False,
        }
    )
    _write_json(output / "run_manifest.json", manifest)
    if judgement not in JUDGEMENTS:
        raise TemporalRepairError(f"Unknown final judgement: {judgement}")
    return json.loads((output / "validation_gate.json").read_text(encoding="utf-8"))


__all__ = [
    "CONFIG_PATH",
    "balance_identity_rows",
    "before_after_validation_delta",
    "c1_external_materials_audit",
    "expected_plant_response_contract",
    "load_representative_week_prices",
    "load_validation_config",
    "partial_anchor_rows",
    "paired_counterfactual_validation_rows",
    "representative_week_kpis",
    "supplemental_annual_operational_rows",
    "run_behaviour_anchor_validation",
    "synthetic_price_profiles",
]
