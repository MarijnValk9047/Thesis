"""Deterministic hourly C0/C1 temporal validation on one representative week.

The global model grid is hourly.  C1 retains four internal EAF batch subslots
per hour solely to preserve the accepted 45-minute heat cycle; prices,
continuous plants, inventories, utilities and the objective remain hourly.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import time
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from pyomo.contrib.iis import write_iis
from pyomo.environ import (
    Constraint,
    ConstraintList,
    NonNegativeIntegers,
    NonNegativeReals,
    Objective,
    Var,
    minimize,
    value,
)
from pyomo.opt import SolverFactory

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from .s4_4c6_deterministic_behaviour_anchor_validation import (
    _activate_c1_calibration_bundle,
    load_representative_week_prices,
    load_validation_config,
)
from .s4_4c6_deterministic_c0_temporal_validation import (
    C0_CONTINUOUS_ASSETS,
    initial_c0_state,
    load_c0_validation_config,
)
from .s4_4c6_deterministic_temporal_repair import (
    ANNUAL_EAF_ROUTE_T,
    CALENDAR_CONTRACT_VERSION,
    CONTINUOUS_ASSETS,
    DEFAULT_RATE_RANGES_T_H,
    HOURS_PER_YEAR,
    _component_value,
    _annual_calendar_contract,
    _maximum_incumbent_violation,
    initial_temporal_state,
    load_temporal_repair_config,
    prepare_temporal_context,
    cumulative_eaf_target_taps,
    quota_period_target_taps,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelRollingState,
    _applicable_cost_flows,
    _build_physical_model,
    _inventory_overrides,
    _represented_cost_expression,
    _route_progress_values,
)
from .s4_4c6_shared_annual_recoverability import (
    ANNUAL_REPORTED_FINAL_PRODUCT_TOLERANCE_T,
    SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION,
    annual_final_product_band,
    future_quota_requirements,
    validate_future_heat_calendar,
)
from .s4_4c_unified_physical_modelbuilder import (
    ModelTimeGrid,
    REPO_ROOT,
    _build_c0_inputs,
    _build_retained_bf_bof_inputs,
    _load_tables,
)


C0_HOURLY_CONTRACT_VERSION = (
    "c0_deterministic_hourly_temporal_v7_24h_exec_48h_feasibility_tail"
)
C1_HOURLY_CONTRACT_VERSION = (
    "c1_deterministic_hourly_temporal_v6_24h_exec_48h_feasibility_tail"
)
C0_ANNUAL_HOURLY_CONTRACT_VERSION = (
    "c0_deterministic_hourly_annual_v60_terminal_inventory_band"
)
C1_ANNUAL_HOURLY_CONTRACT_VERSION = (
    "c1_deterministic_hourly_annual_v60_terminal_inventory_band"
)
C0_ANNUAL_QH_CONTRACT_VERSION = (
    "c0_deterministic_qh_annual_v1_mean_preserving_shape"
)
C1_ANNUAL_QH_CONTRACT_VERSION = (
    "c1_deterministic_qh_annual_v1_mean_preserving_shape"
)
EXECUTION_HOURS = 24
PHYSICAL_HORIZON_HOURS = 72
YEAR_END_FULL_HORIZON_DAYS = 14
YEAR_END_FULL_HORIZON_HOURS = 24 * YEAR_END_FULL_HORIZON_DAYS
DT = 1.0
EAF_SUBSLOTS_PER_HOUR = 4
STATE_FEASIBILITY_TOLERANCE = 1e-8
ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T = 1e-4
# Do not tighten the source contract by accumulating a positive numerical
# reserve at every remaining replan.  Solver feasibility tolerances are
# handled by ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T instead.
ANNUAL_RECOVERABILITY_HANDOFF_RESERVE_T_PER_FUTURE_REPLAN = 0.0
C1_KGF_ANNUAL_RECONCILIATION_TOLERANCE_T = 1.0
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/runs/"
    "steel_c6_deterministic_hourly_temporal_validation_v1_20260806"
)
YEAR_READINESS_OUTPUT_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/runs/"
    "steel_c6_deterministic_hourly_year_readiness_v1_20260806"
)
ANNUAL_HOURLY_PRICE_CONTRACT_VERSION = "hourly_annual_price_interface_v1"
ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION = 0.10
ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION = 0.50
ANNUAL_TERMINAL_BULK_PELLET_BAND_FRACTION = 0.10
C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T = (
    ANNUAL_REPORTED_FINAL_PRODUCT_TOLERANCE_T
)
ANNUAL_PROGRESS_PHYSICAL_MAX_FACTOR = 1.20
C1_KGF1_DRY_COAL_PROGRESS_KEY = "C1_KGF1_dry_coal_input_t"


class HourlyTemporalValidationError(RuntimeError):
    """Fail-closed hourly temporal validation error."""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    if not materialized:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in materialized for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_governed_run_metadata(
    output: Path,
    *,
    run_id: str,
    regime: str,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    behaviour_config: Mapping[str, Any],
    annual_readiness: bool = False,
) -> None:
    lineage_role = (
        "diagnostic_hourly_year_contract_readiness"
        if annual_readiness
        else (
            "diagnostic_c0_stateful_route_inventory_behaviour_and_"
            "reproducible_figure_evidence"
        )
    )
    resolved = {
        "run_id": run_id,
        "regime": regime,
        "output_policy": "thesis_report",
        "run_class": "diagnostic_validation",
        "lineage_role": lineage_role,
        "run_mode": (
            "causal_annual_prefix_smoke" if annual_readiness else "representative_week"
        ),
        "c0": dict(c0_config),
        "c1": dict(c1_config),
        "behaviour": dict(behaviour_config),
    }
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(resolved, sort_keys=True), encoding="utf-8"
    )
    config_paths = [
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/configs/"
        "steel_c6_deterministic_c0_temporal_validation.yaml",
        REPO_ROOT / str(c0_config["base_temporal_config"]),
        REPO_ROOT / str(c0_config["behaviour_validation_config"]),
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/configs/"
        "steel_deterministic_figure_package_v8.yaml",
    ]
    _write_json(
        output / "input_manifest.json",
        {
            "inputs": [
                {
                    "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "sha256": _sha256_file(path),
                }
                for path in config_paths
            ]
        },
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _write_json(output / "code_version.json", {"branch": branch, "head": head})
    terminal_warning = (
        "- Annual-prefix semantics are active: no weekly inventory or C0 route reset.\n"
        if annual_readiness
        else "- Representative-week terminal contracts are active.\n"
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Seven-day hourly run; not an annual operating certificate.\n"
        + terminal_warning
        + "- Capacity envelopes and ramps are development policy, not Tata nameplate truth.\n"
        "- Price-insensitive and perfect-foresight deterministic benchmarks only.\n"
        "- No DAM, mFRR, stochastic, S10 or four-week solve is represented.\n"
        "- `full_four_week_matrix_authorized=false`.\n",
        encoding="utf-8",
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": run_id,
            "output_policy": "thesis_report",
            "run_class": "diagnostic_validation",
            "lineage_role": lineage_role,
            "retention": "local_governed_ignored",
            "git_eligible": False,
            "full_four_week_matrix_authorized": False,
        },
    )


def _hourly_context(
    base_config: Mapping[str, Any],
    contract_version: str,
    *,
    execution_hours: int = EXECUTION_HOURS,
) -> Any:
    if int(execution_hours) not in {23, 24, 25}:
        raise HourlyTemporalValidationError(
            "Hourly execution days must contain 23, 24 or 25 hours."
        )
    qh_context = prepare_temporal_context(base_config)
    return replace(
        qh_context,
        time_grid=ModelTimeGrid(
            horizon_hours=PHYSICAL_HORIZON_HOURS,
            execution_hours=int(execution_hours),
            time_step_hours=DT,
        ),
        temporal_contract_version=contract_version,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        economic_horizon_hours=int(execution_hours),
        physical_feasibility_tail_active=True,
        model_id="steel_deterministic_hourly_temporal_v1",
        granularity="hourly",
        grid_id="H_v1",
    )


def _execution_hours(context: Any) -> int:
    return int(context.time_grid.execution_hours)


def _execution_steps(context: Any) -> int:
    """Return executable Pyomo intervals, never physical hours."""

    return int(context.time_grid.execution_steps)


def _steps_for_hours(context: Any, hours: int) -> int:
    """Map a governed physical-hour boundary to a model-index boundary."""

    return int(context.time_grid.hours_to_steps(int(hours)))


def _hours_for_steps(context: Any, steps: int) -> int:
    value_in_hours = int(steps) * float(context.time_grid.time_step_hours)
    if not math.isclose(value_in_hours, round(value_in_hours), abs_tol=1e-9):
        raise HourlyTemporalValidationError("Annual calendar boundaries must resolve to whole physical hours.")
    return int(round(value_in_hours))


def _qh_context(
    base_config: Mapping[str, Any],
    contract_version: str,
    *,
    execution_hours: int,
    physical_horizon_hours: int,
) -> Any:
    """Native-QH annual context with physical hours separated from indices."""

    if int(execution_hours) not in {23, 24, 25}:
        raise HourlyTemporalValidationError(
            "QH execution days must contain 23, 24 or 25 physical hours."
        )
    if int(physical_horizon_hours) < int(execution_hours):
        raise HourlyTemporalValidationError("QH physical horizon cannot precede execution.")
    qh_context = prepare_temporal_context(base_config)
    return replace(
        qh_context,
        time_grid=ModelTimeGrid(
            horizon_hours=int(physical_horizon_hours),
            execution_hours=int(execution_hours),
            time_step_hours=0.25,
        ),
        temporal_contract_version=contract_version,
        calendar_contract_version="lear_strict_donly_native_dst_qh_calendar_v1",
        economic_horizon_hours=int(execution_hours),
        physical_feasibility_tail_active=True,
        model_id="steel_deterministic_qh_annual_v1",
        granularity="quarterhour",
        grid_id="QH_v1",
    )


def build_hourly_annual_calendar(
    base_config: Mapping[str, Any],
    *,
    start_local_date: date | str | None = None,
    end_exclusive_local_date: date | str | None = None,
    timezone_name: str | None = None,
) -> pd.DataFrame:
    """Return the governed maintenance-free local-day calendar at hourly support."""

    if start_local_date is None and end_exclusive_local_date is None:
        days, _ = _annual_calendar_contract(base_config)
    else:
        if start_local_date is None or end_exclusive_local_date is None:
            raise HourlyTemporalValidationError(
                "Annual calendar start and exclusive end must be supplied together."
            )
        start = pd.Timestamp(start_local_date).date()
        end = pd.Timestamp(end_exclusive_local_date).date()
        if end <= start:
            raise HourlyTemporalValidationError("Annual calendar end must follow its start.")
        zone_name = timezone_name or "Europe/Amsterdam"
        if zone_name != "Europe/Amsterdam":
            raise HourlyTemporalValidationError(
                "The annual steel calendar must remain Europe/Amsterdam."
            )
        zone = ZoneInfo(zone_name)
        days = []
        current = start
        while current < end:
            start_local = datetime.combine(current, wall_time.min, tzinfo=zone)
            next_local = datetime.combine(
                current + timedelta(days=1), wall_time.min, tzinfo=zone
            )
            start_utc = start_local.astimezone(timezone.utc)
            end_utc = next_local.astimezone(timezone.utc)
            days.append(
                {
                    "date": current,
                    "day_length_hours": int(
                        round((end_utc - start_utc).total_seconds() / 3600.0)
                    ),
                    "start_utc": start_utc,
                }
            )
            current += timedelta(days=1)
    rows: list[dict[str, Any]] = []
    absolute_hour = 0
    for day_index, item in enumerate(days, start=1):
        start_utc = pd.Timestamp(item["start_utc"])
        day_hours = int(item["day_length_hours"])
        for local_hour in range(day_hours):
            rows.append(
                {
                    "calendar_day_index": day_index,
                    "local_date": item["date"].isoformat(),
                    "local_day_length_hours": day_hours,
                    "local_hour_index": local_hour,
                    "annual_hour_index": absolute_hour,
                    "timestamp_utc": start_utc + pd.Timedelta(hours=local_hour),
                    "maintenance_active": False,
                }
            )
            absolute_hour += 1
    frame = pd.DataFrame(rows)
    timestamps = pd.DatetimeIndex(frame["timestamp_utc"])
    if len(frame) != int(HOURS_PER_YEAR) or not timestamps.is_unique:
        raise HourlyTemporalValidationError(
            "Annual hourly calendar must contain 8,760 unique UTC timestamps."
        )
    expected = pd.date_range(timestamps[0], periods=int(HOURS_PER_YEAR), freq="h")
    if not timestamps.equals(expected):
        raise HourlyTemporalValidationError(
            "Annual hourly calendar must be contiguous in UTC."
        )
    return frame


def load_hourly_annual_prices(
    calendar: pd.DataFrame,
    *,
    strategy: str,
    source_path: Path | None = None,
    flat_price_eur_per_mwh: float = 80.0,
    timestamp_column: str = "timestamp_utc",
    price_column: str = "price_eur_per_mwh",
    source_is_realised_oracle: bool = False,
) -> pd.DataFrame:
    """Resolve an exact annual hourly price vector without filling missing support."""

    if strategy == "price_insensitive":
        result = calendar[["annual_hour_index", "timestamp_utc"]].copy()
        result["price_eur_per_mwh"] = float(flat_price_eur_per_mwh)
        result["price_information"] = "price_insensitive_constant"
        result["source_path"] = "generated_by_contract"
    elif strategy == "perfect_foresight_oracle":
        if source_path is None or not source_is_realised_oracle:
            raise HourlyTemporalValidationError(
                "Perfect foresight requires an explicit realised-oracle source."
            )
        path = Path(source_path)
        frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        if timestamp_column not in frame or price_column not in frame:
            raise HourlyTemporalValidationError("Annual price source columns are missing.")
        source = frame[[timestamp_column, price_column]].copy()
        source[timestamp_column] = pd.to_datetime(source[timestamp_column], utc=True)
        source[price_column] = pd.to_numeric(source[price_column], errors="raise")
        source = source.rename(
            columns={timestamp_column: "timestamp_utc", price_column: "price_eur_per_mwh"}
        )
        if source["timestamp_utc"].duplicated().any():
            raise HourlyTemporalValidationError("Annual price source contains duplicate timestamps.")
        result = calendar[["annual_hour_index", "timestamp_utc"]].merge(
            source, on="timestamp_utc", how="left", validate="one_to_one"
        )
        if result["price_eur_per_mwh"].isna().any() or len(source) != len(calendar):
            raise HourlyTemporalValidationError(
                "Perfect-foresight annual price source must match all 8,760 calendar hours exactly."
            )
        result["price_information"] = "separately_labelled_perfect_foresight_oracle"
        result["source_path"] = str(path)
    else:
        raise HourlyTemporalValidationError(f"Unsupported annual price strategy: {strategy}.")
    result["price_contract_version"] = ANNUAL_HOURLY_PRICE_CONTRACT_VERSION
    return result


def _hourly_prices(qh_prices: Sequence[float]) -> tuple[float, ...]:
    if len(qh_prices) != 7 * 24 * 4:
        raise HourlyTemporalValidationError("Representative week must contain 672 QH prices.")
    return tuple(
        sum(float(qh_prices[index + offset]) for offset in range(4)) / 4.0
        for index in range(0, len(qh_prices), 4)
    )


def _annual_recoverable_progress_bounds(
    *,
    annual_target_t: float,
    band_fraction: float,
    completed_t: float,
    endpoint_hours: int,
    corridor_hours: int = PHYSICAL_HORIZON_HOURS,
) -> tuple[float, float]:
    """Preserve the annual terminal band without imposing its daily average.

    The one-physical-horizon corridor prevents indefinite deferral.  The
    future-capacity term is a conservative reachability certificate based on
    the existing governed 120% route-envelope factor; it is not a new plant
    throughput bound.
    """

    annual = float(annual_target_t)
    fraction = float(band_fraction)
    completed = float(completed_t)
    endpoint = int(endpoint_hours)
    corridor = int(corridor_hours)
    if (
        annual <= 0.0
        or not 0.0 <= fraction < 1.0
        or completed < 0.0
        or not 0 < endpoint <= HOURS_PER_YEAR
        or corridor <= 0
    ):
        raise HourlyTemporalValidationError(
            "Annual recoverable-progress inputs are invalid."
        )
    reference_rate = annual / HOURS_PER_YEAR
    reachable_rate = reference_rate * ANNUAL_PROGRESS_PHYSICAL_MAX_FACTOR
    future_hours = HOURS_PER_YEAR - endpoint
    terminal_lower = annual * (1.0 - fraction)
    terminal_upper = annual * (1.0 + fraction)
    planned_cumulative = annual * endpoint / HOURS_PER_YEAR
    physical_corridor = reachable_rate * corridor
    recoverable_lower = max(
        0.0,
        terminal_lower - completed - reachable_rate * future_hours,
    )
    progress_lower = max(0.0, planned_cumulative - physical_corridor - completed)
    recoverable_upper = terminal_upper - completed
    progress_upper = planned_cumulative + physical_corridor - completed
    if endpoint == HOURS_PER_YEAR:
        lower = recoverable_lower
        upper = recoverable_upper
    else:
        lower = max(recoverable_lower, progress_lower)
        upper = min(recoverable_upper, max(0.0, progress_upper))
    if lower > upper + 1e-6:
        raise HourlyTemporalValidationError(
            "Accepted rolling state cannot recover the annual progress band."
        )
    return lower, max(0.0, upper)


def _annual_exact_terminal_recoverable_bounds(
    *,
    annual_target_t: float,
    completed_t: float,
    endpoint_hours: int,
    mandatory_future_rate_t_h: float = 0.0,
    future_reachable_rate_t_h: float | None = None,
) -> tuple[float, float]:
    """Preserve an exact annual endpoint without a prescriptive daily path."""

    annual = float(annual_target_t)
    completed = float(completed_t)
    endpoint = int(endpoint_hours)
    mandatory_rate = float(mandatory_future_rate_t_h)
    reachable_rate = (
        annual / HOURS_PER_YEAR * ANNUAL_PROGRESS_PHYSICAL_MAX_FACTOR
        if future_reachable_rate_t_h is None
        else float(future_reachable_rate_t_h)
    )
    if (
        annual <= 0.0
        or completed < 0.0
        or not 0 < endpoint <= HOURS_PER_YEAR
        or mandatory_rate < 0.0
        or reachable_rate <= 0.0
    ):
        raise HourlyTemporalValidationError(
            "Exact annual terminal-recoverability inputs are invalid."
        )
    future_hours = HOURS_PER_YEAR - endpoint
    lower = max(
        0.0,
        annual
        - completed
        - reachable_rate * future_hours
        - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T,
    )
    upper = (
        annual
        - completed
        - mandatory_rate * future_hours
        + ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
    )
    if upper < -1e-6 or lower > upper + 1e-6:
        raise HourlyTemporalValidationError(
            "Accepted rolling state cannot recover the exact annual endpoint."
        )
    return lower, max(0.0, upper)


def _annual_banded_terminal_recoverable_bounds(
    *,
    annual_target_t: float,
    tolerance_t: float,
    completed_t: float,
    endpoint_hours: int,
    mandatory_future_rate_t_h: float,
    future_reachable_rate_t_h: float,
) -> tuple[float, float]:
    """Recover an explicit absolute annual band without changing hourly bounds."""

    tolerance = float(tolerance_t)
    if tolerance < 0.0 or float(annual_target_t) <= tolerance:
        raise HourlyTemporalValidationError("Invalid annual reconciliation band.")
    lower, _ = _annual_exact_terminal_recoverable_bounds(
        annual_target_t=float(annual_target_t) - tolerance,
        completed_t=completed_t,
        endpoint_hours=endpoint_hours,
        mandatory_future_rate_t_h=mandatory_future_rate_t_h,
        future_reachable_rate_t_h=future_reachable_rate_t_h,
    )
    _, upper = _annual_exact_terminal_recoverable_bounds(
        annual_target_t=float(annual_target_t) + tolerance,
        completed_t=completed_t,
        endpoint_hours=endpoint_hours,
        mandatory_future_rate_t_h=mandatory_future_rate_t_h,
        future_reachable_rate_t_h=future_reachable_rate_t_h,
    )
    return lower, upper


def c0_annual_operational_reconciliation(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the annual C0 material chain before any rolling optimisation.

    The active C0 recipes fix the relevant annual flows, so their aggregate
    feasibility can be certified algebraically without inventing a scheduling
    profile.  Cyclic inventory restoration is explicit: initial stock cannot
    be counted as annual supply.
    """

    material = config["c0_material_contract"]
    rolling = config["c0_hourly_rolling_contract"]
    conversion = rolling["active_conversion_reuse"]
    ranges = config["plant_dynamics"]["active_operating_ranges_t_h"]
    normalized = config["plant_dynamics"]["normalized_capacity_contract"]["assets"]
    bof = float(material["physical_bof_liquid_steel_t_y"])
    hot_metal = bof * float(material["bof_hot_metal_t_per_t_liquid_steel"])
    demands = {
        "coke_t": hot_metal * float(conversion["coke_t_per_t_hot_metal"]),
        "sinter_t": hot_metal * float(material["sinter_t_per_t_hot_metal"]),
        "pellets_t": hot_metal * float(material["pellets_t_per_t_hot_metal"]),
        "bof_scrap_t": bof * float(material["bof_scrap_t_per_t_liquid_steel"]),
        "hot_metal_t": hot_metal,
    }
    supplies = {
        "coke_t": sum(float(ranges[name][1]) for name in ("coking_plant_1", "coking_plant_2"))
        * float(conversion["coke_t_per_t_activity"])
        * HOURS_PER_YEAR,
        "sinter_t": float(ranges["sintering_plant"][1])
        * float(conversion["sinter_t_per_t_sifa_activity"])
        * HOURS_PER_YEAR,
        "pellets_t": float(normalized["pefa_pellet_output_t"]["resolved_maximum_t_h"])
        * HOURS_PER_YEAR
        + float(material["imported_pellets_t_y"]),
        "bof_scrap_t": float(material["annual_bof_scrap_cap_t_y"]),
        "hot_metal_t": sum(float(ranges[name][1]) for name in ("blast_furnace_6", "blast_furnace_7"))
        * float(conversion["bf_hot_metal_t_per_t_activity"])
        * HOURS_PER_YEAR,
    }
    rows = []
    for flow_id, demand in demands.items():
        supply = supplies[flow_id]
        rows.append(
            {
                "flow_id": flow_id,
                "annual_demand_t": demand,
                "annual_reachable_supply_t": supply,
                "headroom_t": supply - demand,
                "headroom_fraction_of_demand": (supply - demand) / demand,
                "passed": supply + 1e-6 >= demand,
            }
        )
    return {
        "contract": "c0_annual_joint_material_reconciliation_v1",
        "cyclic_inventory_net_supply_t": 0.0,
        "rows": rows,
        "passed": all(bool(row["passed"]) for row in rows),
    }


def _execution_product_band(
    context: Any,
    state: SteelRollingState,
    *,
    configuration: str,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any] | None = None,
    execution_hours: int | None = None,
) -> tuple[float, float]:
    shared_band = annual_final_product_band(
        configuration=configuration,
        c0_material_contract=c0_config["c0_material_contract"],
    )
    annual = shared_band.physical_target_t
    endpoint = int(state.executed_hours) + int(
        _execution_hours(context) if execution_hours is None else execution_hours
    )
    if configuration == C0_CONFIGURATION:
        material = c0_config["c0_material_contract"]
        bof_from_scrap_cap_t_y = float(
            material["annual_bof_scrap_cap_t_y"]
        ) / float(material["bof_scrap_t_per_t_liquid_steel"])
        final_per_bof = float(material["physical_final_product_t_y"]) / float(
            material["physical_bof_liquid_steel_t_y"]
        )
        return _annual_banded_terminal_recoverable_bounds(
            annual_target_t=annual,
            tolerance_t=shared_band.physical_tolerance_t,
            completed_t=float(state.cumulative_production_t),
            endpoint_hours=endpoint,
            mandatory_future_rate_t_h=0.0,
            future_reachable_rate_t_h=(
                bof_from_scrap_cap_t_y * final_per_bof / HOURS_PER_YEAR
            ),
        )
    # C1 already carries an integer heat calendar, a shiftable daily
    # route/slab witness and a one-step physical-tail viability constraint.
    # A second daily lower derived from independent nameplate maxima is not a
    # valid viability certificate: it ignores the jointly reachable heat/BF/
    # downstream mix and can demand more output today than that mix permits.
    # Keep only the annual endpoint band here; the stateful witness determines
    # how much must be produced before the final day.
    return _c1_annual_progress_corridor_bounds(
        annual_target_t=annual,
        completed_t=float(state.cumulative_production_t),
        endpoint_hours=endpoint,
    )


def _c1_annual_progress_corridor_bounds(
    *,
    annual_target_t: float,
    completed_t: float,
    endpoint_hours: int,
) -> tuple[float, float]:
    """Close only the common endpoint band; no linear daily path is imposed."""

    annual = float(annual_target_t)
    completed = float(completed_t)
    endpoint = min(int(endpoint_hours), HOURS_PER_YEAR)
    if annual <= 0.0 or completed < 0.0 or endpoint <= 0:
        raise HourlyTemporalValidationError("Invalid C1 annual progress state.")
    if endpoint == HOURS_PER_YEAR:
        return (
            max(
                0.0,
                annual
                - C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T
                - completed
                - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T,
            ),
            max(
                0.0,
                annual
                + C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T
                - completed,
            ),
        )
    return 0.0, max(
        0.0,
        annual + C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T - completed,
    )


def _c0_contract(
    config: Mapping[str, Any],
    band: tuple[float, float],
    *,
    contract_version: str = C0_HOURLY_CONTRACT_VERSION,
    execution_hours: int = EXECUTION_HOURS,
    physical_horizon_hours: int = PHYSICAL_HORIZON_HOURS,
) -> dict[str, Any]:
    material = config["c0_material_contract"]
    plant_dynamics = deepcopy(config["plant_dynamics"])
    plant_dynamics["sifa"]["ramp_t_h_per_hour"] = float(
        plant_dynamics["sifa"]["ramp_t_h_per_qh"]
    )
    plant_dynamics["sifa"]["minimum_direction_hours"] = 2.0
    return {
        "configuration_id": C0_CONFIGURATION,
        "temporal_contract_version": contract_version,
        "inventory_terminal_policy": "recoverable_physical_tail",
        "recursive_recovery_horizon_hours": int(physical_horizon_hours),
        "scrap_execution_checkpoint_hours": (
            int(execution_hours)
            if int(physical_horizon_hours) > int(execution_hours)
            else None
        ),
        "final_product_execution_lower_t": float(band[0]),
        "final_product_execution_upper_t": float(band[1]),
        "route_reference_policy": "annual_recoverable_calendar",
        "scrap_origin_contract": {
            "annual_site_scrap_cap_t_y": float(material["annual_site_scrap_cap_t_y"]),
            "annual_bof_scrap_cap_t_y": float(material["annual_bof_scrap_cap_t_y"]),
            "annual_eaf_scrap_cap_t_y": 0.0,
            "annual_external_scrap_cap_t_y": float(material["annual_external_scrap_cap_t_y"]),
            "annual_internal_scrap_cap_t_y": float(material["annual_internal_scrap_cap_t_y"]),
            "quota_period_hours": HOURS_PER_YEAR,
        },
        "c0_bf_material_interface": {
            "sinter_t_per_t_hot_metal": float(material["sinter_t_per_t_hot_metal"]),
            "pellets_t_per_t_hot_metal": float(material["pellets_t_per_t_hot_metal"]),
        },
        "c0_coke_chain_reconciliation": dict(material["c0_coke_chain_reconciliation"]),
        "plant_dynamics": plant_dynamics,
    }


def _c1_contract(
    config: Mapping[str, Any],
    band: tuple[float, float],
    *,
    contract_version: str = C1_HOURLY_CONTRACT_VERSION,
    annual_readiness: bool = False,
    physical_horizon_hours: int = PHYSICAL_HORIZON_HOURS,
) -> dict[str, Any]:
    repair = config["deterministic_temporal_repair"]
    plant_dynamics = deepcopy(repair["plant_dynamics"])
    plant_dynamics["sifa"]["ramp_t_h_per_hour"] = float(
        plant_dynamics["sifa"]["ramp_t_h_per_qh"]
    )
    plant_dynamics["sifa"]["minimum_direction_hours"] = 2.0
    return {
        "configuration_id": C1_CONFIGURATION,
        "temporal_contract_version": contract_version,
        "inventory_terminal_policy": "recoverable_physical_tail",
        "recursive_recovery_horizon_hours": int(physical_horizon_hours),
        "final_product_execution_lower_t": float(band[0]),
        "final_product_execution_upper_t": float(band[1]),
        "eaf_annual_route_basis_t_y": ANNUAL_EAF_ROUTE_T,
        "route_reference_policy": (
            "annual_recoverable_calendar"
            if (
                annual_readiness
                or str(contract_version) == C1_ANNUAL_QH_CONTRACT_VERSION
            )
            else "maintenance_free_daily_reference"
        ),
        "c1_bf_material_interface": deepcopy(repair["c1_bf_material_interface"]),
        "scrap_origin_contract": deepcopy(repair["scrap_origin_contract"]),
        "kgf1_route_scale_reconciliation": deepcopy(
            repair["kgf1_route_scale_reconciliation"]
        ),
        "c1_metallics_sensitivity": {
            **deepcopy(repair["c1_metallics_sensitivity"]),
            "hbi_horizon_cap_t": 0.0,
        },
        "plant_dynamics": plant_dynamics,
        "experimental_self_use_calibration": deepcopy(
            repair.get("experimental_self_use_calibration", {})
        ),
        "experimental_process_electricity_overlay": deepcopy(
            repair.get("experimental_process_electricity_overlay", {})
        ),
        "experimental_ng_service_calibration": deepcopy(
            repair.get("experimental_ng_service_calibration", {})
        ),
        "experimental_coal_wag_calibration": deepcopy(
            repair.get("experimental_coal_wag_calibration", {})
        ),
    }


def _add_c1_daily_contract(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    *,
    lower_taps: int,
    upper_taps: int,
    fixed_taps: int | None,
    week_boundary: bool,
    state: SteelRollingState,
    annual_readiness: bool,
    physical_horizon_hours: int,
    physical_tail_heat_days: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    execution_hours = _execution_hours(context)
    execution_steps = _execution_steps(context)
    executed_taps = sum(model.eaf_tap[t] for t in range(execution_steps))
    model.executed_eaf_taps = executed_taps
    if fixed_taps is None:
        model.eaf_daily_heat_lower = Constraint(expr=executed_taps >= int(lower_taps))
        model.eaf_daily_heat_upper = Constraint(expr=executed_taps <= int(upper_taps))
    else:
        model.eaf_daily_heat_fixed = Constraint(expr=executed_taps == int(fixed_taps))
    # The builder owns a four-subslot heat automaton per model interval; QH
    # affects the interval duration, not this internal state representation.
    execution_subslots = execution_steps * EAF_SUBSLOTS_PER_HOUR
    if week_boundary:
        model.eaf_week_boundary_idle = Constraint(
            expr=model.eaf_heat_start_subslot[execution_subslots - 2]
            + model.eaf_heat_start_subslot[execution_subslots - 1]
            == 0
        )
    tail_days = tuple(physical_tail_heat_days or ())
    model.eaf_physical_tail_calendar_constraints = ConstraintList()
    model.eaf_physical_tail_calendar_audit = []
    for row in tail_days:
        start_hour = int(row["start_hour"])
        end_hour = int(row["end_hour"])
        if not execution_hours <= start_hour < end_hour <= int(physical_horizon_hours):
            raise HourlyTemporalValidationError(
                "EAF physical-tail calendar day lies outside the physical horizon."
            )
        start_step = _steps_for_hours(context, start_hour)
        end_step = _steps_for_hours(context, end_hour)
        taps = sum(model.eaf_tap[t] for t in range(start_step, end_step))
        model.eaf_physical_tail_calendar_constraints.add(
            taps >= int(row["lower_taps"])
        )
        model.eaf_physical_tail_calendar_constraints.add(
            taps <= int(row["upper_taps"])
        )
        closes_quota = bool(
            row.get("closes_quota", row.get("closes_current_quota", False))
        )
        if closes_quota:
            quota_start_hour = int(row.get("quota_start_hour", 0))
            quota_start_step = _steps_for_hours(context, quota_start_hour)
            quota_target = int(
                row.get("quota_remaining_taps", row["remaining_quota_taps"])
            )
            model.eaf_physical_tail_calendar_constraints.add(
                sum(
                    model.eaf_tap[t]
                    for t in range(quota_start_step, end_step)
                )
                == quota_target
            )
            boundary_subslot = end_step * EAF_SUBSLOTS_PER_HOUR
            model.eaf_physical_tail_calendar_constraints.add(
                model.eaf_heat_start_subslot[boundary_subslot - 2]
                + model.eaf_heat_start_subslot[boundary_subslot - 1]
                == 0
            )
        model.eaf_physical_tail_calendar_audit.append(dict(row))
    model.eaf_physical_tail_calendar_policy = (
        "calendar_day_bounds_and_current_quota_boundary_inside_price_blind_tail"
    )
    annual_target = float(
        config["deterministic_temporal_repair"]
        ["kgf1_route_scale_reconciliation"]["annual_dry_coal_target_t_y"]
    )
    completed = float(
        state.cumulative_route_progress_t.get(C1_KGF1_DRY_COAL_PROGRESS_KEY, 0.0)
    )
    model.kgf1_anchor_constraints_active = False
    model.kgf1_anchor_role = (
        "validation_only_mer_annual_reference_physical_coke_balance_drives_output"
    )
    model.kgf1_annual_recoverability_audit = {
        "annual_reference_t": annual_target,
        "rounding_tolerance_t": C1_KGF_ANNUAL_RECONCILIATION_TOLERANCE_T,
        "completed_before_t": completed,
        "annual_readiness": bool(annual_readiness),
        "constraint_active": False,
        "physical_driver": "exact_coke_balance_with_kgf1_capacity_and_dynamics",
    }
    diagnostic = config["deterministic_temporal_repair"].get(
        "experimental_wag_self_use_diagnostic", {}
    )
    if diagnostic.get("active"):
        model.experimental_wag_self_use_caps = ConstraintList()
        for carrier, annual_cap_pj in diagnostic["vn25_carrier_caps_pj_y"].items():
            component = getattr(model, f"{carrier.lower()}_to_vn25")
            cap_mwh = (
                float(annual_cap_pj)
                * 1_000_000.0
                / 3.6
                * execution_hours
                / HOURS_PER_YEAR
            )
            model.experimental_wag_self_use_caps.add(
                sum(component[t] for t in range(execution_steps)) <= cap_mwh
            )


def _c0_route_expressions(
    model: Any, steps: int = EXECUTION_HOURS
) -> dict[str, Any]:
    return _c0_route_expressions_over_hours(model, int(steps))


def _c0_route_expressions_over_hours(model: Any, hours: int) -> dict[str, Any]:
    return {
        "C0_BOF_crude_steel_output_t": sum(
            model.bof_crude_steel_output[t] for t in range(int(hours))
        ),
        "C0_HSM_final_product_t": sum(
            model.c0_hsm_final_product_output[t] for t in range(int(hours))
        ),
        "C0_DSP_final_product_t": sum(
            model.c0_dsp_final_product_output[t] for t in range(int(hours))
        ),
    }


def _annual_initial_inventory_targets(
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    *,
    configuration: str,
) -> dict[str, float]:
    """Resolve cold-start inventories from the active physical input tables."""

    tables = _load_tables()
    if configuration == C0_CONFIGURATION:
        inputs = _build_c0_inputs(tables, horizon_hours_override=PHYSICAL_HORIZON_HOURS)
        pellet_initial = float(c0_config["plant_dynamics"]["pefa"]["initial_inventory_t"])
        return {
            "coke_inventory": float(inputs.coke_store_initial_t),
            "sinter_inventory": float(inputs.sinter_store_initial_t),
            "hot_iron_inventory": float(inputs.hot_iron_store_initial_t),
            "cold_slab_inventory": float(inputs.cold_slab_store_initial_t),
            "pellet_inventory": pellet_initial,
        }
    if configuration == C1_CONFIGURATION:
        retained = _build_retained_bf_bof_inputs(
            tables,
            configuration_id=C1_CONFIGURATION,
        )
        pellet_initial = float(
            c1_config["deterministic_temporal_repair"]["plant_dynamics"]["pefa"]
            ["initial_inventory_t"]
        )
        return {
            "dri_inventory": 0.0,
            "coke_inventory": float(retained.coke_store_initial_t),
            "sinter_inventory": float(retained.sinter_store_initial_t),
            "hot_iron_inventory": float(retained.hot_iron_store_initial_t),
            "cold_slab_inventory": float(retained.cold_slab_store_initial_t),
            "eaf_slab_inventory": 0.0,
            "pellet_inventory": pellet_initial,
        }
    raise HourlyTemporalValidationError(f"Unsupported annual configuration {configuration}.")


def _c0_week_terminal_inventory_bands(
    context: Any,
    c0_config: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    """Use the governed C0 fixed-initial/fixed-terminal inventory quantities."""

    targets = _annual_initial_inventory_targets(
        c0_config,
        {},
        configuration=C0_CONFIGURATION,
    )
    fraction = float(c0_config["c0_hourly_rolling_contract"]["route_band_fraction"])
    bands: dict[str, dict[str, float]] = {}
    for inventory_id, component_name in c0_config["c0_hourly_rolling_contract"][
        "inventory_components"
    ].items():
        source_band = context.terminal_inventory_band[C0_CONFIGURATION][inventory_id]
        target = float(targets[str(component_name)])
        component_fraction = (
            ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION
            if str(component_name)
            in {"hot_iron_inventory", "cold_slab_inventory", "eaf_slab_inventory"}
            else fraction
        )
        bands[str(inventory_id)] = {
            "capacity_t": float(source_band["capacity_t"]),
            "target_t": target,
            "lower_t": max(
                0.0,
                target
                - component_fraction * float(source_band["capacity_t"]),
            ),
            "upper_t": min(
                float(source_band["capacity_t"]),
                target
                + component_fraction * float(source_band["capacity_t"]),
            ),
        }
    return bands


def _add_execution_year_terminal(
    model: Any,
    targets_t: Mapping[str, float],
    *,
    final_year_day: bool,
    execution_hours: int = EXECUTION_HOURS,
    physical_horizon_hours: int = PHYSICAL_HORIZON_HOURS,
    recovery_terminal_index: int | None = None,
) -> None:
    """Apply true year closure or prove it in the preceding physical tail."""

    model.hourly_annual_inventory_terminal_active = bool(final_year_day)
    model.hourly_annual_inventory_recovery_active = recovery_terminal_index is not None
    model.hourly_annual_inventory_terminal_targets_t = {
        str(component): float(target) for component, target in targets_t.items()
    }
    model.hourly_annual_inventory_terminal_band_fraction = (
        ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION
    )
    model.hourly_annual_inventory_terminal_band_fraction_by_component = {
        str(component): (
            ANNUAL_TERMINAL_BULK_PELLET_BAND_FRACTION
            if str(component) == "pellet_inventory"
            else ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION
            if str(component)
            in {"hot_iron_inventory", "cold_slab_inventory", "eaf_slab_inventory"}
            else ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION
        )
        for component in targets_t
    }
    if not final_year_day and recovery_terminal_index is None:
        return
    terminal_index = (
        int(execution_hours) - 1
        if final_year_day
        else int(recovery_terminal_index)
    )
    if not 0 <= terminal_index < int(physical_horizon_hours):
        raise HourlyTemporalValidationError(
            "Annual inventory recovery index is outside the physical tail."
        )
    model.hourly_annual_inventory_terminal = ConstraintList()
    model.hourly_annual_inventory_terminal_bands_t = {}
    capacity_attributes = {
        "dri_inventory": "c1_dri_buffer_active_capacity_t",
        "coke_inventory": "coke_capacity",
        "sinter_inventory": "sinter_capacity",
        "hot_iron_inventory": "hot_iron_capacity",
        "cold_slab_inventory": "cold_slab_capacity",
        "eaf_slab_inventory": "shared_cold_slab_capacity",
        "pellet_inventory": "pellet_capacity",
    }
    for component_name, target in targets_t.items():
        component = getattr(model, str(component_name))
        capacity_component = getattr(
            model, capacity_attributes[str(component_name)], None
        )
        if capacity_component is None:
            capacity = max(float(target), 1.0)
            band_scale_basis = "terminal_target_no_finite_modelled_capacity"
        elif isinstance(capacity_component, (float, int)):
            capacity = float(capacity_component)
            band_scale_basis = "modelled_inventory_capacity"
        else:
            capacity = float(value(capacity_component[terminal_index].upper))
            band_scale_basis = "modelled_inventory_capacity"
        band_fraction = (
            ANNUAL_TERMINAL_BULK_PELLET_BAND_FRACTION
            if str(component_name) == "pellet_inventory"
            else ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION
            if str(component_name)
            in {"hot_iron_inventory", "cold_slab_inventory", "eaf_slab_inventory"}
            else ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION
        )
        half_width = band_fraction * capacity
        lower = max(0.0, float(target) - half_width)
        upper = min(capacity, float(target) + half_width)
        model.hourly_annual_inventory_terminal_bands_t[str(component_name)] = {
            "target_t": float(target),
            "capacity_t": capacity,
            "lower_t": lower,
            "upper_t": upper,
            "band_fraction": band_fraction,
            "band_scale_basis": band_scale_basis,
        }
        model.hourly_annual_inventory_terminal.add(
            component[terminal_index] >= lower
        )
        model.hourly_annual_inventory_terminal.add(
            component[terminal_index] <= upper
        )
    model.hourly_annual_inventory_terminal_index = terminal_index


def _add_year_end_recovery_execution_contract(
    model: Any,
    context: Any,
    state: SteelRollingState,
    c0_config: Mapping[str, Any],
    *,
    configuration: str,
    remaining_taps: int,
    recovery_terminal_index: int,
) -> None:
    """Make an endpoint-visible physical tail close the remaining year."""

    execution_hours = _execution_hours(context)
    horizon_steps = int(recovery_terminal_index) + 1
    horizon_hours = _hours_for_steps(context, horizon_steps)
    if horizon_steps > len(model.TIME):
        raise HourlyTemporalValidationError(
            "Year-end recovery terminal lies outside the physical model horizon."
        )
    if execution_hours != 24 or not execution_hours < horizon_hours <= YEAR_END_FULL_HORIZON_HOURS:
        raise HourlyTemporalValidationError(
            "Year-end recovery certification requires a 24-hour execution day "
            "and an endpoint-visible physical horizon inside the configured window."
        )
    shared_product_band = annual_final_product_band(
        configuration=configuration,
        c0_material_contract=c0_config["c0_material_contract"],
    )
    if configuration == C0_CONFIGURATION:
        fraction = float(
            c0_config["c0_hourly_rolling_contract"]["route_band_fraction"]
        )
    annual_product_lower = shared_product_band.physical_lower_t
    annual_product_upper = shared_product_band.physical_upper_t
    full_horizon_product = sum(model.final_product_output[t] for t in range(horizon_steps))
    future_replan_handoffs = max(
        0, math.ceil((horizon_hours - execution_hours) / execution_hours)
    )
    numerical_handoff_reserve_t = (
        ANNUAL_RECOVERABILITY_HANDOFF_RESERVE_T_PER_FUTURE_REPLAN
        * future_replan_handoffs
    )
    model.hourly_year_end_future_replan_handoffs = future_replan_handoffs
    model.hourly_year_end_numerical_handoff_reserve_t = numerical_handoff_reserve_t
    model.hourly_year_end_product_recovery = ConstraintList()
    model.hourly_year_end_product_recovery.add(
        float(state.cumulative_production_t) + full_horizon_product
        >= annual_product_lower
        - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
        + numerical_handoff_reserve_t
    )
    model.hourly_year_end_product_recovery.add(
        float(state.cumulative_production_t) + full_horizon_product
        <= annual_product_upper
    )
    if configuration == C0_CONFIGURATION:
        model.hourly_year_end_route_recovery = ConstraintList()
        full_routes = _c0_route_expressions_over_hours(model, horizon_steps)
        for route_id, annual_target in c0_config["c0_hourly_rolling_contract"][
            "route_annual_targets_t_y"
        ].items():
            completed = float(state.cumulative_route_progress_t.get(route_id, 0.0))
            model.hourly_year_end_route_recovery.add(
                completed + full_routes[str(route_id)]
                >= float(annual_target) * (1.0 - fraction)
                - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
                + numerical_handoff_reserve_t
            )
            model.hourly_year_end_route_recovery.add(
                completed + full_routes[str(route_id)]
                <= float(annual_target) * (1.0 + fraction)
            )
    else:
        model.hourly_year_end_eaf_tap_recovery = Constraint(
            expr=sum(model.eaf_tap[t] for t in range(horizon_steps))
            == int(remaining_taps)
        )
        final_subslot = horizon_steps * EAF_SUBSLOTS_PER_HOUR
        model.hourly_year_end_eaf_idle = Constraint(
            expr=model.eaf_heat_start_subslot[final_subslot - 2]
            + model.eaf_heat_start_subslot[final_subslot - 1]
            == 0
        )


def _add_c0_annual_progress_contract(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    state: SteelRollingState,
) -> None:
    """Use recoverable annual route progress without an exact daily quota."""

    if hasattr(model, "normalized_capacity_aggregate_recoverability"):
        model.normalized_capacity_aggregate_recoverability.deactivate()
    model.c0_fixed_bf_aggregate_floor_active = False
    model.c0_stateful_recoverability_contract = (
        "annual_terminal_recoverability_with_48h_progress_corridor_v2"
    )
    rolling = config["c0_hourly_rolling_contract"]
    execution_hours = _execution_hours(context)
    execution_steps = _execution_steps(context)
    endpoint_hours = int(state.executed_hours) + execution_hours
    route_expressions = _c0_route_expressions(model, execution_steps)
    conversions = rolling["active_conversion_reuse"]
    bf_ranges = config["plant_dynamics"]["active_operating_ranges_t_h"]
    mandatory_bof_rate = (
        float(bf_ranges["blast_furnace_6"][0])
        + float(bf_ranges["blast_furnace_7"][0])
    ) * float(conversions["bf_hot_metal_t_per_t_activity"]) / float(
        conversions["bof_hot_metal_t_per_t_liquid_steel"]
    )
    material = config["c0_material_contract"]
    kgf_max_total = sum(
        float(bf_ranges[asset][1])
        for asset in ("coking_plant_1", "coking_plant_2")
    )
    bof_from_coke_rate = (
        kgf_max_total
        * float(conversions["coke_t_per_t_activity"])
        / float(conversions["coke_t_per_t_hot_metal"])
        / float(conversions["bof_hot_metal_t_per_t_liquid_steel"])
    )
    sifa_max = float(bf_ranges["sintering_plant"][1])
    bof_from_sinter_rate = (
        sifa_max
        * float(conversions["sinter_t_per_t_sifa_activity"])
        / float(material["sinter_t_per_t_hot_metal"])
        / float(conversions["bof_hot_metal_t_per_t_liquid_steel"])
    )
    bof_from_scrap_rate = (
        float(material["annual_bof_scrap_cap_t_y"])
        / float(material["bof_scrap_t_per_t_liquid_steel"])
        / HOURS_PER_YEAR
    )
    bof_reachable_rate = min(
        bof_from_coke_rate,
        bof_from_sinter_rate,
        bof_from_scrap_rate,
    )
    dsp_reachable_rate = float(
        config["plant_dynamics"]["downstream_temporal_contract"][
            "dsp_final_product_max_t_h"
        ]
    )
    model.c0_annual_route_progress = ConstraintList()
    model.c0_annual_route_audit = {}
    for route_id, annual_target in rolling["route_annual_targets_t_y"].items():
        completed = float(state.cumulative_route_progress_t.get(route_id, 0.0))
        current = route_expressions[str(route_id)]
        mandatory_rate = (
            mandatory_bof_rate
            if str(route_id) == "C0_BOF_crude_steel_output_t"
            else 0.0
        )
        reachable_rate = (
            dsp_reachable_rate
            if str(route_id) == "C0_DSP_final_product_t"
            else (
                bof_reachable_rate
                if str(route_id) == "C0_BOF_crude_steel_output_t"
                else None
            )
        )
        lower_today, upper_today = _annual_exact_terminal_recoverable_bounds(
            annual_target_t=float(annual_target),
            completed_t=completed,
            endpoint_hours=endpoint_hours,
            mandatory_future_rate_t_h=mandatory_rate,
            future_reachable_rate_t_h=reachable_rate,
        )
        model.c0_annual_route_progress.add(current >= lower_today)
        model.c0_annual_route_progress.add(current <= upper_today)
        model.c0_annual_route_audit[str(route_id)] = {
            "endpoint_hours": endpoint_hours,
            "annual_target_t": float(annual_target),
            "terminal_lower_t": float(annual_target),
            "terminal_upper_t": float(annual_target),
            "completed_before_t": completed,
            "lower_today_t": lower_today,
            "upper_today_t": upper_today,
            "corridor_hours": PHYSICAL_HORIZON_HOURS,
            "physical_max_factor": ANNUAL_PROGRESS_PHYSICAL_MAX_FACTOR,
            "mandatory_future_rate_t_h": mandatory_rate,
            "future_reachable_rate_t_h": reachable_rate,
        }

    # One coupled residual certificate replaces independent route-rate
    # optimism.  It reserves the cyclic terminal inventories before material
    # is credited to the remaining BOF obligation and prevents the same
    # future hot metal from being supported independently by coke, sinter,
    # pellets and BF capacity.
    future_hours = HOURS_PER_YEAR - endpoint_hours
    if future_hours > 0:
        inventory_bands = context.terminal_inventory_band[C0_CONFIGURATION]
        last = execution_hours - 1
        pefa_max = float(
            config["plant_dynamics"]["normalized_capacity_contract"]["assets"]
            ["pefa_pellet_output_t"]["resolved_maximum_t_h"]
        )
        bf_max_total = sum(
            float(bf_ranges[asset][1])
            for asset in ("blast_furnace_6", "blast_furnace_7")
        )
        remaining_bof = (
            float(rolling["route_annual_targets_t_y"]["C0_BOF_crude_steel_output_t"])
            - float(
                state.cumulative_route_progress_t.get(
                    "C0_BOF_crude_steel_output_t", 0.0
                )
            )
            - route_expressions["C0_BOF_crude_steel_output_t"]
        )
        model.c0_annual_coupled_residual_hot_metal_t = Var(
            domain=NonNegativeReals
        )
        model.c0_annual_coupled_residual_limits = ConstraintList()
        available_hot_metal = (
            bf_max_total
            * float(conversions["bf_hot_metal_t_per_t_activity"])
            * future_hours
        )
        available_from_coke = (
            model.coke_inventory[last]
            + kgf_max_total
            * float(conversions["coke_t_per_t_activity"])
            * future_hours
            - float(inventory_bands["coke_inventory_t"]["lower_t"])
        ) / float(conversions["coke_t_per_t_hot_metal"])
        available_from_sinter = (
            model.sinter_inventory[last]
            + sifa_max
            * float(conversions["sinter_t_per_t_sifa_activity"])
            * future_hours
            - float(inventory_bands["sinter_inventory_t"]["lower_t"])
        ) / float(material["sinter_t_per_t_hot_metal"])
        available_from_pellets = (
            model.pellet_inventory[last]
            + pefa_max * future_hours
            + float(material["imported_pellets_t_y"])
            * future_hours
            / HOURS_PER_YEAR
            - float(
                inventory_bands.get(
                    "pellet_inventory_t",
                    {
                        "lower_t": max(
                            0.0,
                            float(config["plant_dynamics"]["pefa"]["initial_inventory_t"])
                            - ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION
                            * float(config["plant_dynamics"]["pefa"]["inventory_capacity_t"]),
                        )
                    },
                )["lower_t"]
            )
        ) / float(material["pellets_t_per_t_hot_metal"])
        for available in (
            available_hot_metal,
            available_from_coke,
            available_from_sinter,
            available_from_pellets,
        ):
            model.c0_annual_coupled_residual_limits.add(
                model.c0_annual_coupled_residual_hot_metal_t <= available
            )
        model.c0_annual_coupled_residual_balance = Constraint(
            expr=(
                model.hot_iron_inventory[last]
                + model.c0_annual_coupled_residual_hot_metal_t
                >= float(conversions["bof_hot_metal_t_per_t_liquid_steel"])
                * remaining_bof
                + float(inventory_bands["hot_iron_inventory_t"]["lower_t"])
            )
        )
        executed_scrap = sum(
            model.external_scrap_to_bof_t[t] + model.internal_scrap_to_bof_t[t]
            for t in range(execution_hours)
        )
        model.c0_annual_coupled_residual_scrap = Constraint(
            expr=(
                float(material["bof_scrap_t_per_t_liquid_steel"])
                * remaining_bof
                <= float(material["annual_bof_scrap_cap_t_y"])
                - float(state.cumulative_external_scrap_to_bof_t)
                - float(state.cumulative_internal_scrap_to_bof_t)
                - executed_scrap
            )
        )
        model.c0_annual_coupled_residual_policy = (
            "joint_net_of_terminal_inventory_material_certificate_v1"
        )


def _add_c1_annual_residual_product_certificate(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    state: SteelRollingState,
    annual_inventory_targets_t: Mapping[str, float],
    future_heat_calendar: Sequence[Mapping[str, Any]] | None = None,
    current_quota_period_index: int | None = None,
) -> None:
    """Prove the remaining annual product from non-duplicated route resources."""

    physical_horizon_hours = int(context.time_grid.horizon_hours)
    physical_horizon_steps = len(model.TIME)
    execution_hours = _execution_hours(context)
    execution_steps = _execution_steps(context)
    endpoint_hours = int(state.executed_hours) + execution_hours
    future_hours = max(0, HOURS_PER_YEAR - endpoint_hours)
    routing = context.c1_reference_routing
    reference_hours = float(context.plan.planning_horizon_hours)
    bands = routing["reference_validation_bands"]
    bof_annual_upper = (
        float(bands["bof_liquid_steel"]["upper_t"])
        / reference_hours
        * HOURS_PER_YEAR
    )
    eaf_annual_upper = (
        float(bands["eaf_liquid_steel"]["upper_t"])
        / reference_hours
        * HOURS_PER_YEAR
    )
    imported_annual_cap = (
        float(context.config["imported_slab_annual_cap_mt_y"]) * 1_000_000.0
    )
    dsp_annual_cap = (
        float(routing["dsp_final_product_horizon_cap_t"])
        / reference_hours
        * HOURS_PER_YEAR
    )
    hsm_yield = float(routing["hsm_final_t_per_t_slab"])
    dsp_input_per_final = float(
        routing["dsp_liquid_steel_input_t_per_t_coil"]
    )
    dsp_yield = 1.0 / dsp_input_per_final
    annual_target = (
        float(context.config["annual_reference_target_mt_y"]) * 1_000_000.0
    )
    annual_product_lower = (
        annual_target - C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T
    )
    bof_completed = float(
        state.cumulative_route_progress_t.get(
            "C1_BOF_liquid_steel_output_t_h", 0.0
        )
    )
    eaf_completed = float(
        state.cumulative_route_progress_t.get(
            "C1_EAF_liquid_steel_output_t_h", 0.0
        )
    )
    imported_completed = float(
        state.cumulative_route_progress_t.get(
            "C1_imported_slab_to_HSM_t_h", 0.0
        )
    )
    dsp_completed = float(
        state.cumulative_route_progress_t.get(
            "C1_DSP_final_product_output_t", 0.0
        )
    )
    executed_period = range(execution_steps)
    current_product = sum(model.final_product_output[t] for t in executed_period)
    current_bof = sum(model.bof_crude_steel_output[t] for t in executed_period)
    current_eaf = sum(model.eaf_liquid_steel_output[t] for t in executed_period)
    current_imported = sum(model.imported_slab_to_hsm[t] for t in executed_period)
    current_dsp = sum(model.dsp_final_product_output[t] for t in executed_period)

    model.c1_future_bof_liquid_t = Var(domain=NonNegativeReals)
    model.c1_future_eaf_liquid_t = Var(domain=NonNegativeReals)
    model.c1_future_imported_slab_t = Var(domain=NonNegativeReals)
    model.c1_future_dsp_input_t = Var(domain=NonNegativeReals)
    model.c1_annual_residual_capacity_limits = ConstraintList()
    limits = model.c1_annual_residual_capacity_limits
    limits.add(
        model.c1_future_bof_liquid_t
        <= bof_annual_upper - bof_completed - current_bof
    )
    limits.add(
        model.c1_future_eaf_liquid_t
        <= eaf_annual_upper - eaf_completed - current_eaf
    )
    limits.add(
        model.c1_future_imported_slab_t
        <= imported_annual_cap - imported_completed - current_imported
    )
    limits.add(
        model.c1_future_dsp_input_t
        <= dsp_input_per_final * (dsp_annual_cap - dsp_completed - current_dsp)
    )
    future_heat_rows = validate_future_heat_calendar(future_heat_calendar or ())
    model.c1_annual_future_heat_calendar_rows = future_heat_rows
    model.c1_annual_future_heat_calendar_contract_version = (
        SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION
    )
    model.c1_annual_future_heat_calendar_complete = bool(future_heat_rows)
    if future_heat_rows:
        day_indices = range(len(future_heat_rows))
        model.c1_future_eaf_taps_by_calendar_day = Var(
            day_indices, domain=NonNegativeIntegers
        )
        model.c1_annual_future_heat_calendar_constraints = ConstraintList()
        heat_constraints = model.c1_annual_future_heat_calendar_constraints
        physical_cursor = execution_steps
        physical_row_end_hours: list[int] = []
        for day_offset, row in enumerate(future_heat_rows):
            taps = model.c1_future_eaf_taps_by_calendar_day[day_offset]
            heat_constraints.add(taps >= int(row["lower_taps"]))
            heat_constraints.add(taps <= int(row["upper_taps"]))
            day_end = physical_cursor + _steps_for_hours(
                context, int(row["day_length_hours"])
            )
            physical_row_end_hours.append(day_end)
            if day_end <= physical_horizon_steps:
                heat_constraints.add(
                    taps
                    == sum(
                        model.eaf_tap[t]
                        for t in range(physical_cursor, day_end)
                    )
                )
            physical_cursor = day_end

        current_period = (
            int(future_heat_rows[0]["quota_period_index"])
            if current_quota_period_index is None
            else int(current_quota_period_index)
        )
        current_remaining = int(state.eaf_quota_target_taps or 0) - int(
            state.eaf_quota_completed_taps
        )
        quota_requirements = future_quota_requirements(
            future_heat_rows,
            current_period_index=current_period,
            current_remaining_taps=current_remaining,
        )
        current_future_indices = quota_requirements["current_future_indices"]
        if current_future_indices:
            heat_constraints.add(
                model.executed_eaf_taps
                + sum(
                    model.c1_future_eaf_taps_by_calendar_day[index]
                    for index in current_future_indices
                )
                == current_remaining
            )
        else:
            # On the quota boundary the future calendar starts in the next
            # period; today's executed taps alone must close the old period.
            heat_constraints.add(model.executed_eaf_taps == current_remaining)
        for period, requirement in quota_requirements["later_periods"].items():
            heat_constraints.add(
                sum(
                    model.c1_future_eaf_taps_by_calendar_day[index]
                    for index in requirement["indices"]
                )
                == int(requirement["target_taps"])
            )
        model.c1_annual_future_quota_requirements = quota_requirements
        heat_constraints.add(
            model.c1_future_eaf_liquid_t
            == 325.0
            * sum(
                model.c1_future_eaf_taps_by_calendar_day[index]
                for index in day_indices
            )
        )
        model.c1_annual_future_heat_calendar_physical_row_end_hours = tuple(
            physical_row_end_hours
        )
        model.c1_annual_future_heat_calendar_policy = (
            "price_blind_calendar_day_integer_taps_with_quota_equalities_and_physical_tail_link"
        )
    else:
        model.c1_annual_future_heat_calendar_policy = (
            "missing_calendar_rows_static_builder_only_not_operationally_accepted"
        )
    repair = config["deterministic_temporal_repair"]
    downstream = repair["plant_dynamics"]["downstream_temporal_contract"]
    # The first future days are already linked to the detailed physical tail
    # by the shiftable daily witness.  Subtracting another full execution day
    # here double-counted the boundary and discarded valid import/downstream
    # capacity at every replan.
    downstream_boundary_block_hours = 0
    downstream_future_hours = future_hours
    bf_max_liquid_rate = (
        float(
            repair["continuous_must_run_assets"]["blast_furnace_6"]
            ["maximum_rate_t_h"]
        )
        * float(
            repair["c1_bf_material_interface"]
            ["hot_metal_t_per_t_represented_bf_activity"]
        )
        / float(context.config["bof_material_balance"]["hot_metal_t_per_t_liquid_steel"])
    )
    limits.add(model.c1_future_bof_liquid_t <= bf_max_liquid_rate * future_hours)
    limits.add(
        model.c1_future_eaf_liquid_t
        <= (32.0 * 325.0 / 24.0) * future_hours
    )
    limits.add(
        model.c1_future_imported_slab_t
        <= float(routing["imported_slab_max_t_h"]) * downstream_future_hours
    )
    model.c1_annual_import_recoverability_hours = downstream_future_hours
    domestic_future = model.c1_future_bof_liquid_t + model.c1_future_eaf_liquid_t
    limits.add(model.c1_future_dsp_input_t <= domestic_future)
    annual_target_taps = cumulative_eaf_target_taps(HOURS_PER_YEAR)
    limits.add(
        model.c1_future_eaf_liquid_t + current_eaf
        == float(annual_target_taps * 325) - eaf_completed
    )
    cold_slab_capacity = float(
        value(model.cold_slab_capacity[execution_hours - 1].upper)
    )
    cold_slab_terminal_lower = max(
        0.0,
        float(annual_inventory_targets_t["cold_slab_inventory"])
        - ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION * cold_slab_capacity,
    )
    eaf_slab_terminal_lower = max(
        0.0,
        float(annual_inventory_targets_t.get("eaf_slab_inventory", 0.0))
        - ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION * cold_slab_capacity,
    )
    cold_slab_net = (
        model.cold_slab_inventory[execution_hours - 1]
        - cold_slab_terminal_lower
    )
    eaf_slab_net = (
        model.eaf_slab_inventory[execution_hours - 1]
        - eaf_slab_terminal_lower
    )

    last = execution_hours - 1

    model.c1_future_continuous_reachability = ConstraintList()

    def future_reachable_upper_sum(
        name: str,
        component: Any,
        *,
        minimum_rate: float,
        maximum_rate: float,
        maximum_step: float,
        block_hours: int,
        available_hours: int | None = None,
        anchor_index: int | None = None,
        namespace: str = "future",
    ) -> Any:
        reachability_hours = (
            future_hours if available_hours is None else int(available_hours)
        )
        if reachability_hours <= 0:
            return 0.0
        ramp_hours = min(
            reachability_hours,
            int(math.ceil((maximum_rate - minimum_rate) / maximum_step))
            * int(block_hours),
        )
        rates = Var(range(ramp_hours), domain=NonNegativeReals)
        setattr(model, f"c1_{namespace}_reachable_{name}_rate_t_h", rates)
        reachability_anchor = last if anchor_index is None else int(anchor_index)
        for future_hour in range(ramp_hours):
            reachable = rates[future_hour]
            blocks = math.ceil((future_hour + 1) / int(block_hours))
            model.c1_future_continuous_reachability.add(
                reachable >= float(minimum_rate)
            )
            model.c1_future_continuous_reachability.add(
                reachable <= float(maximum_rate)
            )
            model.c1_future_continuous_reachability.add(
                reachable
                <= component[reachability_anchor] + float(maximum_step) * blocks
            )
        return sum(rates[hour] for hour in range(ramp_hours)) + float(
            maximum_rate
        ) * (reachability_hours - ramp_hours)

    dynamics = repair["plant_dynamics"]
    assets = repair["continuous_must_run_assets"]
    future_kgf_upper = future_reachable_upper_sum(
        "kgf1",
        model.coking_plant_1,
        minimum_rate=float(assets["coking_plant_1"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["coking_plant_1"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["kgf1"]["maximum_step_t_h"]),
        block_hours=int(dynamics["kgf1"]["setpoint_block_hours"]),
    )
    future_sifa_upper = future_reachable_upper_sum(
        "sifa",
        model.sintering_plant,
        minimum_rate=float(assets["sintering_plant"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["sintering_plant"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["sifa"]["ramp_t_h_per_hour"]),
        block_hours=1,
    )
    future_bf_upper = future_reachable_upper_sum(
        "bf6",
        model.blast_furnace_6,
        minimum_rate=float(assets["blast_furnace_6"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["blast_furnace_6"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["bf6"]["maximum_step_t_h"]),
        block_hours=int(dynamics["bf6"]["setpoint_block_hours"]),
    )
    future_drp_upper = future_reachable_upper_sum(
        "drp",
        model.drp_pellet_input,
        minimum_rate=float(assets["drp_pellet_input"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["drp_pellet_input"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["drp"]["maximum_step_t_h"]),
        block_hours=int(dynamics["drp"]["setpoint_block_hours"]),
    )
    future_pefa_upper = future_reachable_upper_sum(
        "pefa",
        model.pefa_pellet_output_t,
        minimum_rate=float(dynamics["pefa"]["minimum_output_t_h"]),
        maximum_rate=float(dynamics["pefa"]["maximum_output_t_h"]),
        maximum_step=float(dynamics["pefa"]["maximum_step_t_h"]),
        block_hours=int(dynamics["pefa"]["setpoint_block_hours"]),
    )
    downstream = dynamics["downstream_temporal_contract"]
    process_limits = getattr(model, "temporal_process_limits_t_per_interval", {})
    hsm_limits = process_limits.get("hot_strip_mill")
    if not hsm_limits or len(hsm_limits) != 2:
        raise HourlyTemporalValidationError(
            "The annual residual certificate requires an explicit HSM capacity."
        )
    future_hsm_upper = future_reachable_upper_sum(
        "hsm",
        model.hot_strip_mill,
        minimum_rate=0.0,
        maximum_rate=float(hsm_limits[1]),
        maximum_step=float(downstream["hsm_maximum_step_t_h"]),
        block_hours=int(downstream["hsm_setpoint_block_hours"]),
        available_hours=downstream_future_hours,
    )

    def terminal_lower(component_name: str, capacity: float) -> float:
        band_fraction = (
            ANNUAL_TERMINAL_WIP_INVENTORY_BAND_FRACTION
            if component_name == "hot_iron_inventory"
            else ANNUAL_TERMINAL_INVENTORY_BAND_FRACTION
        )
        return max(
            0.0,
            float(annual_inventory_targets_t[component_name])
            - band_fraction * float(capacity),
        )

    coke_capacity = float(value(model.coke_capacity[last].upper))
    sinter_capacity = float(value(model.sinter_capacity[last].upper))
    hot_iron_capacity = float(value(model.hot_iron_capacity[last].upper))
    pellet_capacity_component = getattr(model, "pellet_capacity", None)
    pellet_capacity = (
        float(value(pellet_capacity_component[last].upper))
        if pellet_capacity_component is not None
        else max(float(annual_inventory_targets_t["pellet_inventory"]), 1.0)
    )
    dri_capacity = float(model.c1_dri_buffer_active_capacity_t)
    coke_lower = terminal_lower("coke_inventory", coke_capacity)
    sinter_lower = terminal_lower("sinter_inventory", sinter_capacity)
    hot_iron_lower = terminal_lower("hot_iron_inventory", hot_iron_capacity)
    pellet_lower = max(
        0.0,
        float(annual_inventory_targets_t["pellet_inventory"])
        - ANNUAL_TERMINAL_BULK_PELLET_BAND_FRACTION * pellet_capacity,
    )
    dri_lower = terminal_lower("dri_inventory", dri_capacity)

    hot_metal_per_liquid = float(
        context.config["bof_material_balance"]["hot_metal_t_per_t_liquid_steel"]
    )
    coke_per_hot_metal = float(
        context.source_coke_chain["bf_coke_t_per_t_hot_metal"]
    )
    dry_coal_per_coke = float(
        context.source_coke_chain["dry_coal_t_per_t_coke"]
    )
    # The rounded MER KGF1 annual quantity is a validation anchor, not a
    # physical supply cap. Future coke availability follows the reachable KGF1
    # capacity; the exact coke balance determines actual production.
    future_coke_t = future_kgf_upper / dry_coal_per_coke
    limits.add(
        hot_metal_per_liquid * coke_per_hot_metal * model.c1_future_bof_liquid_t
        <= model.coke_inventory[last] + future_coke_t - coke_lower
    )

    sinter_per_ore = float(
        repair["sifa_operating_metadata"]["sinter_t_per_t_represented_ore"]
    )
    sinter_per_hot_metal = float(
        repair["c1_bf_material_interface"]["sinter_t_per_t_hot_metal"]
    )
    limits.add(
        hot_metal_per_liquid
        * sinter_per_hot_metal
        * model.c1_future_bof_liquid_t
        <= model.sinter_inventory[last]
        + future_sifa_upper * sinter_per_ore
        - sinter_lower
    )
    hot_metal_per_activity = float(
        repair["c1_bf_material_interface"]
        ["hot_metal_t_per_t_represented_bf_activity"]
    )
    limits.add(
        hot_metal_per_liquid * model.c1_future_bof_liquid_t
        <= model.hot_iron_inventory[last]
        + future_bf_upper * hot_metal_per_activity
        - hot_iron_lower
    )

    metallics = repair["c1_metallics_sensitivity"]
    hdri_per_eaf_liquid = float(
        metallics["eaf_hdri_t_per_t_liquid_steel"]
    )
    eaf_scrap_per_liquid = float(
        metallics["eaf_scrap_t_per_t_liquid_steel"]
    )
    drp_yield = float(model.drp_yield_t_dri_per_t_pellets)
    bf_pellets_per_hot_metal = float(
        repair["plant_dynamics"]["pefa"]["bf_pellets_t_per_t_hot_metal"]
    )
    imported_pellets_rate = float(
        repair["plant_dynamics"]["pefa"]["imported_pellets_t_y"]
    ) / HOURS_PER_YEAR
    dri_net = model.dri_inventory[last] - dri_lower
    future_internal_and_external_pellets = (
        model.pellet_inventory[last]
        + future_pefa_upper
        + imported_pellets_rate * future_hours
        - pellet_lower
    )
    limits.add(
        hot_metal_per_liquid
        * bf_pellets_per_hot_metal
        * model.c1_future_bof_liquid_t
        <= model.pellet_inventory[last]
        + future_pefa_upper
        - pellet_lower
    )
    limits.add(
        hot_metal_per_liquid
        * bf_pellets_per_hot_metal
        * model.c1_future_bof_liquid_t
        + hdri_per_eaf_liquid / drp_yield * model.c1_future_eaf_liquid_t
        <= future_internal_and_external_pellets + dri_net / drp_yield
    )
    limits.add(
        hdri_per_eaf_liquid * model.c1_future_eaf_liquid_t
        <= model.dri_inventory[last]
        + drp_yield * future_drp_upper
        - dri_lower
    )

    scrap = repair["scrap_origin_contract"]
    bof_scrap_per_liquid = float(
        context.config["bof_material_balance"]["scrap_t_per_t_liquid_steel"]
    )
    bof_scrap_used = (
        float(state.cumulative_external_scrap_to_bof_t)
        + float(state.cumulative_internal_scrap_to_bof_t)
        + sum(model.bof_scrap_supply_t[t] for t in executed_period)
    )
    eaf_scrap_used = (
        float(state.cumulative_external_scrap_to_eaf_t)
        + float(state.cumulative_internal_scrap_to_eaf_t)
        + sum(model.eaf_scrap_supply_t[t] for t in executed_period)
    )
    future_bof_scrap = bof_scrap_per_liquid * model.c1_future_bof_liquid_t
    future_eaf_scrap = eaf_scrap_per_liquid * model.c1_future_eaf_liquid_t
    limits.add(
        bof_scrap_used + future_bof_scrap
        <= float(scrap["annual_bof_scrap_cap_t_y"])
    )
    limits.add(
        eaf_scrap_used + future_eaf_scrap
        <= float(scrap["annual_eaf_scrap_cap_t_y"])
    )
    limits.add(
        bof_scrap_used + eaf_scrap_used + future_bof_scrap + future_eaf_scrap
        <= float(scrap["annual_site_scrap_cap_t_y"])
    )
    future_slab_supply = (
        domestic_future
        - model.c1_future_dsp_input_t
        + model.c1_future_imported_slab_t
        + cold_slab_net
        + eaf_slab_net
    )
    model.c1_future_hsm_input_t = Var(domain=NonNegativeReals)
    limits.add(model.c1_future_hsm_input_t <= future_slab_supply)
    limits.add(model.c1_future_hsm_input_t <= future_hsm_upper)
    limits.add(
        model.c1_future_dsp_input_t
        <= float(downstream["dsp_final_product_max_t_h"])
        * dsp_input_per_final
        * downstream_future_hours
    )

    # A scalar annual remainder can certify a total that cannot be shifted to
    # the next rolling day: it has no chronology for slabs or downstream
    # capacity.  Keep one price-blind daily witness over the remaining local
    # calendar instead.  The first complete days are tied to the detailed
    # physical tail, so tomorrow's model can reuse the same witness after one
    # left shift.  This is a feasibility construct only; none of its variables
    # enter represented procurement cost.
    if future_heat_rows:
        future_day_indices = range(len(future_heat_rows))
        calendar_future_hours = sum(
            int(row["day_length_hours"]) for row in future_heat_rows
        )
        model.c1_annual_future_daily_route_calendar_complete = (
            calendar_future_hours == future_hours
        )
        model.c1_future_bof_liquid_by_calendar_day_t = Var(
            future_day_indices, domain=NonNegativeReals
        )
        model.c1_future_imported_slab_by_calendar_day_t = Var(
            future_day_indices, domain=NonNegativeReals
        )
        model.c1_future_dsp_input_by_calendar_day_t = Var(
            future_day_indices, domain=NonNegativeReals
        )
        model.c1_future_hsm_input_by_calendar_day_t = Var(
            future_day_indices, domain=NonNegativeReals
        )
        model.c1_future_slab_inventory_by_calendar_day_t = Var(
            future_day_indices,
            domain=NonNegativeReals,
            bounds=(0.0, cold_slab_capacity),
        )
        model.c1_annual_future_daily_route_constraints = ConstraintList()
        daily = model.c1_annual_future_daily_route_constraints
        daily.add(
            sum(
                model.c1_future_bof_liquid_by_calendar_day_t[index]
                for index in future_day_indices
            )
            == model.c1_future_bof_liquid_t
        )
        daily.add(
            sum(
                model.c1_future_imported_slab_by_calendar_day_t[index]
                for index in future_day_indices
            )
            == model.c1_future_imported_slab_t
        )
        daily.add(
            sum(
                model.c1_future_dsp_input_by_calendar_day_t[index]
                for index in future_day_indices
            )
            == model.c1_future_dsp_input_t
        )
        daily.add(
            sum(
                model.c1_future_hsm_input_by_calendar_day_t[index]
                for index in future_day_indices
            )
            == model.c1_future_hsm_input_t
        )
        physical_cursor = execution_steps
        for index, row in enumerate(future_heat_rows):
            hours = int(row["day_length_hours"])
            bof_day = model.c1_future_bof_liquid_by_calendar_day_t[index]
            eaf_day = 325.0 * model.c1_future_eaf_taps_by_calendar_day[index]
            imported_day = (
                model.c1_future_imported_slab_by_calendar_day_t[index]
            )
            dsp_day = model.c1_future_dsp_input_by_calendar_day_t[index]
            hsm_day = model.c1_future_hsm_input_by_calendar_day_t[index]
            slab_end = model.c1_future_slab_inventory_by_calendar_day_t[index]
            slab_start = (
                model.cold_slab_inventory[last] + model.eaf_slab_inventory[last]
                if index == 0
                else model.c1_future_slab_inventory_by_calendar_day_t[index - 1]
            )
            daily.add(bof_day <= bf_max_liquid_rate * hours)
            daily.add(
                imported_day
                <= float(routing["imported_slab_max_t_h"]) * hours
            )
            daily.add(
                dsp_day
                <= float(downstream["dsp_final_product_max_t_h"])
                * dsp_input_per_final
                * hours
            )
            daily.add(hsm_day <= float(hsm_limits[1]) * hours)
            daily.add(dsp_day <= bof_day + eaf_day)
            daily.add(
                slab_end
                == slab_start
                + bof_day
                + eaf_day
                + imported_day
                - dsp_day
                - hsm_day
            )
            day_end = physical_cursor + _steps_for_hours(context, hours)
            if day_end <= physical_horizon_steps:
                detailed = range(physical_cursor, day_end)
                daily.add(
                    bof_day
                    == sum(model.bof_crude_steel_output[t] for t in detailed)
                )
                daily.add(
                    imported_day
                    == sum(model.imported_slab_to_hsm[t] for t in detailed)
                )
                daily.add(
                    dsp_day
                    == sum(
                        model.bof_to_dsp_liquid_steel[t]
                        + model.eaf_to_dsp_liquid_steel[t]
                        for t in detailed
                    )
                )
                daily.add(
                    hsm_day == sum(model.hot_strip_mill[t] for t in detailed)
                )
                daily.add(
                    slab_end
                    == model.cold_slab_inventory[day_end - 1]
                    + model.eaf_slab_inventory[day_end - 1]
                )
            physical_cursor = day_end
        daily.add(
            model.c1_future_slab_inventory_by_calendar_day_t[
                len(future_heat_rows) - 1
            ]
            >= cold_slab_terminal_lower + eaf_slab_terminal_lower
        )
        daily_future_final = sum(
            dsp_yield * model.c1_future_dsp_input_by_calendar_day_t[index]
            + hsm_yield * model.c1_future_hsm_input_by_calendar_day_t[index]
            for index in future_day_indices
        )
        annual_product_target = (
            float(context.config["annual_reference_target_mt_y"])
            * 1_000_000.0
        )
        annual_product_upper = (
            annual_product_target
            + C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T
        )
        daily.add(
            float(state.cumulative_production_t)
            + current_product
            + daily_future_final
            >= annual_product_lower - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
        )
        daily.add(
            float(state.cumulative_production_t)
            + current_product
            + daily_future_final
            <= annual_product_upper + ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
        )
        model.c1_annual_future_daily_route_policy = (
            "price_blind_shiftable_daily_origin_downstream_inventory_witness_v1"
        )
    else:
        model.c1_annual_future_daily_route_policy = (
            "missing_calendar_rows_static_builder_only_not_operationally_accepted"
        )
    future_final_max = (
        dsp_yield * model.c1_future_dsp_input_t
        + hsm_yield * model.c1_future_hsm_input_t
    )
    annual_eaf_liquid = float(annual_target_taps * 325)
    initial_coke = float(annual_inventory_targets_t["coke_inventory"])
    kgf_annual_physical_upper = (
        float(assets["coking_plant_1"]["maximum_rate_t_h"])
        * HOURS_PER_YEAR
    )
    bof_from_annual_coke = (
        initial_coke
        + kgf_annual_physical_upper / dry_coal_per_coke
        - coke_lower
    ) / (hot_metal_per_liquid * coke_per_hot_metal)
    bof_from_annual_hot_metal = (
        float(annual_inventory_targets_t["hot_iron_inventory"])
        + float(assets["blast_furnace_6"]["maximum_rate_t_h"])
        * hot_metal_per_activity
        * HOURS_PER_YEAR
        - hot_iron_lower
    ) / hot_metal_per_liquid
    bof_from_annual_scrap = (
        float(scrap["annual_bof_scrap_cap_t_y"]) / bof_scrap_per_liquid
    )
    annual_bof_resource_upper = min(
        bof_annual_upper,
        bof_from_annual_coke,
        bof_from_annual_hot_metal,
        bof_from_annual_scrap,
    )
    maximum_dsp_final = min(dsp_annual_cap, annual_product_lower)
    minimum_annual_origin_input = (
        dsp_input_per_final * maximum_dsp_final
        + max(0.0, annual_product_lower - maximum_dsp_final) / hsm_yield
    )
    annual_initial_slab_net = (
        float(annual_inventory_targets_t["cold_slab_inventory"])
        - cold_slab_terminal_lower
        + float(annual_inventory_targets_t.get("eaf_slab_inventory", 0.0))
        - eaf_slab_terminal_lower
    )
    minimum_annual_imported_slab = max(
        0.0,
        minimum_annual_origin_input
        - annual_bof_resource_upper
        - annual_eaf_liquid
        - annual_initial_slab_net,
    )
    imported_rate = float(routing["imported_slab_max_t_h"])
    model.c1_annual_executed_import_deadline = Constraint(
        expr=imported_completed
        + current_imported
        + imported_rate * future_hours
        >= minimum_annual_imported_slab
    )
    future_after_physical_horizon = max(
        0,
        HOURS_PER_YEAR - int(state.executed_hours) - physical_horizon_hours,
    )
    model.c1_annual_physical_tail_import_viability = Constraint(
        expr=imported_completed
        + sum(
            model.imported_slab_to_hsm[t]
            for t in range(physical_horizon_hours)
        )
        + imported_rate * future_after_physical_horizon
        >= minimum_annual_imported_slab
    )

    # Prove one-step recursive feasibility with the first explicitly modelled
    # tail day.  A witness only at the end of the complete 48-hour tail can
    # pass through a state that is no longer viable at the next daily replan.
    commitment_days = tuple(
        int(round(hours)) for hours in model.commitment_day_lengths_hours
    )
    if len(commitment_days) < 2:
        raise HourlyTemporalValidationError(
            "C1 annual recursive viability requires one complete tail day."
        )
    tail_horizon_hours = commitment_days[0] + commitment_days[1]
    tail_horizon_steps = _steps_for_hours(context, tail_horizon_hours)
    if not execution_hours < tail_horizon_hours <= physical_horizon_hours:
        raise HourlyTemporalValidationError(
            "C1 annual recursive viability handoff lies outside the physical tail."
        )
    tail_last = tail_horizon_steps - 1
    tail_future_hours = max(
        0,
        HOURS_PER_YEAR - int(state.executed_hours) - tail_horizon_hours,
    )
    physical_period = range(tail_horizon_steps)
    tail_bof_completed = bof_completed + sum(
        model.bof_crude_steel_output[t] for t in physical_period
    )
    tail_eaf_completed = eaf_completed + sum(
        model.eaf_liquid_steel_output[t] for t in physical_period
    )
    tail_imported_completed = imported_completed + sum(
        model.imported_slab_to_hsm[t] for t in physical_period
    )
    tail_dsp_completed = dsp_completed + sum(
        model.dsp_final_product_output[t] for t in physical_period
    )
    model.c1_tail_future_bof_liquid_t = Var(domain=NonNegativeReals)
    model.c1_tail_future_eaf_liquid_t = Var(domain=NonNegativeReals)
    model.c1_tail_future_imported_slab_t = Var(domain=NonNegativeReals)
    model.c1_tail_future_dsp_input_t = Var(domain=NonNegativeReals)
    model.c1_tail_future_hsm_input_t = Var(domain=NonNegativeReals)
    model.c1_annual_physical_tail_residual_limits = ConstraintList()
    tail_limits = model.c1_annual_physical_tail_residual_limits
    if future_heat_rows:
        residual_day_indices = [
            index
            for index, end_hour in enumerate(
                model.c1_annual_future_heat_calendar_physical_row_end_hours
            )
            if int(end_hour) > tail_horizon_steps
        ]
        tail_limits.add(
            model.c1_tail_future_eaf_liquid_t
            == 325.0
            * sum(
                model.c1_future_eaf_taps_by_calendar_day[index]
                for index in residual_day_indices
            )
        )
    tail_limits.add(
        model.c1_tail_future_bof_liquid_t
        <= bof_annual_upper - tail_bof_completed
    )
    tail_limits.add(
        model.c1_tail_future_eaf_liquid_t
        <= eaf_annual_upper - tail_eaf_completed
    )
    tail_limits.add(
        model.c1_tail_future_imported_slab_t
        <= imported_annual_cap - tail_imported_completed
    )
    tail_limits.add(
        model.c1_tail_future_dsp_input_t
        <= dsp_input_per_final * (dsp_annual_cap - tail_dsp_completed)
    )
    tail_limits.add(
        model.c1_tail_future_eaf_liquid_t
        == annual_eaf_liquid - tail_eaf_completed
    )
    tail_limits.add(
        model.c1_tail_future_bof_liquid_t
        <= bf_max_liquid_rate * tail_future_hours
    )
    tail_limits.add(
        model.c1_tail_future_eaf_liquid_t
        <= (32.0 * 325.0 / 24.0) * tail_future_hours
    )
    tail_limits.add(
        model.c1_tail_future_imported_slab_t
        <= imported_rate
        * max(0, tail_future_hours - downstream_boundary_block_hours)
    )
    model.c1_annual_tail_import_recoverability_hours = max(
        0, tail_future_hours - downstream_boundary_block_hours
    )

    tail_kgf_upper = future_reachable_upper_sum(
        "kgf1",
        model.coking_plant_1,
        minimum_rate=float(assets["coking_plant_1"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["coking_plant_1"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["kgf1"]["maximum_step_t_h"]),
        block_hours=int(dynamics["kgf1"]["setpoint_block_hours"]),
        available_hours=tail_future_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_sifa_upper = future_reachable_upper_sum(
        "sifa",
        model.sintering_plant,
        minimum_rate=float(assets["sintering_plant"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["sintering_plant"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["sifa"]["ramp_t_h_per_hour"]),
        block_hours=1,
        available_hours=tail_future_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_bf_upper = future_reachable_upper_sum(
        "bf6",
        model.blast_furnace_6,
        minimum_rate=float(assets["blast_furnace_6"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["blast_furnace_6"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["bf6"]["maximum_step_t_h"]),
        block_hours=int(dynamics["bf6"]["setpoint_block_hours"]),
        available_hours=tail_future_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_drp_upper = future_reachable_upper_sum(
        "drp",
        model.drp_pellet_input,
        minimum_rate=float(assets["drp_pellet_input"]["minimum_rate_t_h"]),
        maximum_rate=float(assets["drp_pellet_input"]["maximum_rate_t_h"]),
        maximum_step=float(dynamics["drp"]["maximum_step_t_h"]),
        block_hours=int(dynamics["drp"]["setpoint_block_hours"]),
        available_hours=tail_future_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_pefa_upper = future_reachable_upper_sum(
        "pefa",
        model.pefa_pellet_output_t,
        minimum_rate=float(dynamics["pefa"]["minimum_output_t_h"]),
        maximum_rate=float(dynamics["pefa"]["maximum_output_t_h"]),
        maximum_step=float(dynamics["pefa"]["maximum_step_t_h"]),
        block_hours=int(dynamics["pefa"]["setpoint_block_hours"]),
        available_hours=tail_future_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_downstream_hours = tail_future_hours
    tail_hsm_upper = future_reachable_upper_sum(
        "hsm",
        model.hot_strip_mill,
        minimum_rate=0.0,
        maximum_rate=float(hsm_limits[1]),
        maximum_step=float(downstream["hsm_maximum_step_t_h"]),
        block_hours=int(downstream["hsm_setpoint_block_hours"]),
        available_hours=tail_downstream_hours,
        anchor_index=tail_last,
        namespace="tail_future",
    )
    tail_future_coke = tail_kgf_upper / dry_coal_per_coke
    tail_limits.add(
        hot_metal_per_liquid
        * coke_per_hot_metal
        * model.c1_tail_future_bof_liquid_t
        <= model.coke_inventory[tail_last] + tail_future_coke - coke_lower
    )
    tail_limits.add(
        hot_metal_per_liquid
        * sinter_per_hot_metal
        * model.c1_tail_future_bof_liquid_t
        <= model.sinter_inventory[tail_last]
        + tail_sifa_upper * sinter_per_ore
        - sinter_lower
    )
    tail_limits.add(
        hot_metal_per_liquid * model.c1_tail_future_bof_liquid_t
        <= model.hot_iron_inventory[tail_last]
        + tail_bf_upper * hot_metal_per_activity
        - hot_iron_lower
    )
    tail_limits.add(
        hot_metal_per_liquid
        * bf_pellets_per_hot_metal
        * model.c1_tail_future_bof_liquid_t
        + hdri_per_eaf_liquid / drp_yield * model.c1_tail_future_eaf_liquid_t
        <= model.pellet_inventory[tail_last]
        + tail_pefa_upper
        + imported_pellets_rate * tail_future_hours
        - pellet_lower
        + (model.dri_inventory[tail_last] - dri_lower) / drp_yield
    )
    tail_limits.add(
        hdri_per_eaf_liquid * model.c1_tail_future_eaf_liquid_t
        <= model.dri_inventory[tail_last]
        + drp_yield * tail_drp_upper
        - dri_lower
    )
    tail_bof_scrap_used = (
        float(state.cumulative_external_scrap_to_bof_t)
        + float(state.cumulative_internal_scrap_to_bof_t)
        + sum(model.bof_scrap_supply_t[t] for t in physical_period)
    )
    tail_eaf_scrap_used = (
        float(state.cumulative_external_scrap_to_eaf_t)
        + float(state.cumulative_internal_scrap_to_eaf_t)
        + sum(model.eaf_scrap_supply_t[t] for t in physical_period)
    )
    tail_future_bof_scrap = (
        bof_scrap_per_liquid * model.c1_tail_future_bof_liquid_t
    )
    tail_future_eaf_scrap = (
        eaf_scrap_per_liquid * model.c1_tail_future_eaf_liquid_t
    )
    tail_limits.add(
        tail_bof_scrap_used + tail_future_bof_scrap
        <= float(scrap["annual_bof_scrap_cap_t_y"])
    )
    tail_limits.add(
        tail_eaf_scrap_used + tail_future_eaf_scrap
        <= float(scrap["annual_eaf_scrap_cap_t_y"])
    )
    tail_limits.add(
        tail_bof_scrap_used
        + tail_eaf_scrap_used
        + tail_future_bof_scrap
        + tail_future_eaf_scrap
        <= float(scrap["annual_site_scrap_cap_t_y"])
    )
    tail_domestic_future = (
        model.c1_tail_future_bof_liquid_t
        + model.c1_tail_future_eaf_liquid_t
    )
    tail_limits.add(model.c1_tail_future_dsp_input_t <= tail_domestic_future)
    tail_slab_supply = (
        tail_domestic_future
        - model.c1_tail_future_dsp_input_t
        + model.c1_tail_future_imported_slab_t
        + model.cold_slab_inventory[tail_last]
        - cold_slab_terminal_lower
        + model.eaf_slab_inventory[tail_last]
        - eaf_slab_terminal_lower
    )
    tail_limits.add(model.c1_tail_future_hsm_input_t <= tail_slab_supply)
    tail_limits.add(model.c1_tail_future_hsm_input_t <= tail_hsm_upper)
    tail_limits.add(
        model.c1_tail_future_dsp_input_t
        <= float(downstream["dsp_final_product_max_t_h"])
        * dsp_input_per_final
        * tail_downstream_hours
    )
    model.c1_annual_physical_tail_recursive_product_certificate = Constraint(
        expr=float(state.cumulative_production_t)
        + sum(model.final_product_output[t] for t in physical_period)
        + dsp_yield * model.c1_tail_future_dsp_input_t
        + hsm_yield * model.c1_tail_future_hsm_input_t
        >= annual_product_lower - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
    )
    model.c1_annual_joint_residual_product_certificate = Constraint(
        expr=float(state.cumulative_production_t)
        + current_product
        + future_final_max
        >= annual_product_lower - ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
    )
    model.c1_annual_joint_residual_policy = (
        "shared_calendar_integer_heat_and_shiftable_daily_route_continuation_v13"
    )
    model.c1_annual_joint_residual_target_taps = annual_target_taps
    model.c1_annual_joint_residual_product_lower_t = annual_product_lower
    model.c1_annual_recoverability_numerical_tolerance_t = (
        ANNUAL_RECOVERABILITY_NUMERICAL_TOLERANCE_T
    )
    model.c1_annual_joint_residual_certified_horizon_hours = execution_hours
    model.c1_annual_joint_residual_physical_horizon_hours = physical_horizon_hours
    model.c1_annual_joint_residual_future_hours = future_hours
    model.c1_annual_joint_residual_downstream_future_hours = (
        downstream_future_hours
    )
    model.c1_annual_joint_residual_downstream_boundary_reserve_hours = (
        downstream_boundary_block_hours
    )
    model.c1_annual_minimum_imported_slab_t = minimum_annual_imported_slab
    model.c1_annual_import_deadline_policy = (
        "source_to_equation_minimum_import_with_executed_and_physical_tail_viability"
    )
    model.c1_annual_recursive_tail_future_hours = tail_future_hours
    model.c1_annual_recursive_handoff_horizon_hours = tail_horizon_hours
    model.c1_annual_recursive_tail_policy = (
        "first_price_blind_tail_day_ends_inside_annual_recoverable_set"
    )


def _add_annual_physical_tail_handoff_viability(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    c1_config: Mapping[str, Any] | None,
    state: SteelRollingState,
    *,
    configuration: str,
    physical_horizon_hours: int,
) -> None:
    """Certify a reachable next handoff inside the existing physical tail."""

    execution_hours = _execution_hours(context)
    horizon = int(physical_horizon_hours)
    horizon_steps = _steps_for_hours(context, horizon)
    if horizon <= execution_hours:
        return
    model.hourly_physical_tail_inventory_policy = (
        "balance_capacity_and_executed_state_only_until_true_year_terminal"
    )
    product_lower, product_upper = _execution_product_band(
        context,
        state,
        configuration=configuration,
        c0_config=config,
        c1_config=c1_config,
        execution_hours=horizon,
    )
    full_product = sum(model.final_product_output[t] for t in range(horizon_steps))
    model.hourly_physical_tail_product_handoff = ConstraintList()
    if configuration == C0_CONFIGURATION:
        model.hourly_physical_tail_product_handoff.add(full_product >= product_lower)
    else:
        model.c1_physical_horizon_progress_audit = {
            "endpoint_hours": min(
                HOURS_PER_YEAR,
                int(state.executed_hours) + horizon,
            ),
            "required_over_horizon_lower_t": 0.0,
            "completed_before_t": float(state.cumulative_production_t),
            "physical_horizon_hours": horizon,
            "policy": (
                "no_linear_progress_corridor_shared_calendar_continuation_proves_terminal"
            ),
        }
    model.hourly_physical_tail_product_handoff.add(full_product <= product_upper)
    model.hourly_physical_tail_handoff_policy = (
        "c0_route_recoverability_or_c1_shared_calendar_continuation"
    )
    if configuration != C0_CONFIGURATION:
        return
    rolling = config["c0_hourly_rolling_contract"]
    conversions = rolling["active_conversion_reuse"]
    bf_ranges = config["plant_dynamics"]["active_operating_ranges_t_h"]
    mandatory_bof_rate = (
        float(bf_ranges["blast_furnace_6"][0])
        + float(bf_ranges["blast_furnace_7"][0])
    ) * float(conversions["bf_hot_metal_t_per_t_activity"]) / float(
        conversions["bof_hot_metal_t_per_t_liquid_steel"]
    )
    material = config["c0_material_contract"]
    kgf_max_total = sum(
        float(bf_ranges[asset][1])
        for asset in ("coking_plant_1", "coking_plant_2")
    )
    bof_from_coke_rate = (
        kgf_max_total
        * float(conversions["coke_t_per_t_activity"])
        / float(conversions["coke_t_per_t_hot_metal"])
        / float(conversions["bof_hot_metal_t_per_t_liquid_steel"])
    )
    sifa_max = float(bf_ranges["sintering_plant"][1])
    bof_from_sinter_rate = (
        sifa_max
        * float(conversions["sinter_t_per_t_sifa_activity"])
        / float(material["sinter_t_per_t_hot_metal"])
        / float(conversions["bof_hot_metal_t_per_t_liquid_steel"])
    )
    bof_from_scrap_rate = (
        float(material["annual_bof_scrap_cap_t_y"])
        / float(material["bof_scrap_t_per_t_liquid_steel"])
        / HOURS_PER_YEAR
    )
    bof_reachable_rate = min(
        bof_from_coke_rate,
        bof_from_sinter_rate,
        bof_from_scrap_rate,
    )
    dsp_reachable_rate = float(
        config["plant_dynamics"]["downstream_temporal_contract"][
            "dsp_final_product_max_t_h"
        ]
    )
    full_routes = _c0_route_expressions_over_hours(model, horizon)
    model.c0_physical_tail_route_handoff = ConstraintList()
    model.c0_physical_tail_route_handoff_audit = {}
    endpoint_hours = int(state.executed_hours) + horizon
    for route_id, annual_target in rolling["route_annual_targets_t_y"].items():
        completed = float(state.cumulative_route_progress_t.get(route_id, 0.0))
        mandatory_rate = (
            mandatory_bof_rate
            if str(route_id) == "C0_BOF_crude_steel_output_t"
            else 0.0
        )
        reachable_rate = (
            dsp_reachable_rate
            if str(route_id) == "C0_DSP_final_product_t"
            else (
                bof_reachable_rate
                if str(route_id) == "C0_BOF_crude_steel_output_t"
                else None
            )
        )
        lower, upper = _annual_exact_terminal_recoverable_bounds(
            annual_target_t=float(annual_target),
            completed_t=completed,
            endpoint_hours=endpoint_hours,
            mandatory_future_rate_t_h=mandatory_rate,
            future_reachable_rate_t_h=reachable_rate,
        )
        expression = full_routes[str(route_id)]
        model.c0_physical_tail_route_handoff.add(expression >= lower)
        model.c0_physical_tail_route_handoff.add(expression <= upper)
        model.c0_physical_tail_route_handoff_audit[str(route_id)] = {
            "endpoint_hours": endpoint_hours,
            "lower_over_physical_horizon_t": lower,
            "upper_over_physical_horizon_t": upper,
        }


def _add_c0_executed_inventory_continuation(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    inventory_values_eur_per_t: Mapping[str, float] | None,
) -> Any:
    """Value only the executed handoff state; never value the physical tail."""

    inventory_map = dict(config["c0_hourly_rolling_contract"]["inventory_components"])
    values = {
        key: float(value_)
        for key, value_ in (inventory_values_eur_per_t or {}).items()
    }
    model.c0_inventory_shortfall_t = Var(tuple(inventory_map), domain=NonNegativeReals)
    model.c0_inventory_continuation_constraints = ConstraintList()
    continuation = 0.0
    for inventory_id, component_name in inventory_map.items():
        target = float(
            context.terminal_inventory_band[C0_CONFIGURATION][inventory_id]["target_t"]
        )
        handoff = getattr(model, str(component_name))[_execution_hours(context) - 1]
        model.c0_inventory_continuation_constraints.add(
            model.c0_inventory_shortfall_t[inventory_id] >= target - handoff
        )
        continuation += values.get(inventory_id, 0.0) * model.c0_inventory_shortfall_t[
            inventory_id
        ]
    model.c0_inventory_values_eur_per_t = values
    return continuation


def _add_c0_week_contract(
    model: Any,
    context: Any,
    config: Mapping[str, Any],
    state: SteelRollingState,
    *,
    day_index: int,
    week_boundary: bool,
    inventory_values_eur_per_t: Mapping[str, float] | None,
) -> Any:
    """Replace the former fixed BF floor with stateful week recoverability."""

    if not 1 <= int(day_index) <= 7:
        raise HourlyTemporalValidationError("C0 week day must be in [1, 7].")
    rolling = config["c0_hourly_rolling_contract"]
    if rolling["contract_version"] != (
        "c0_stateful_week_route_and_inventory_recoverability_v1"
    ):
        raise HourlyTemporalValidationError("Unexpected C0 rolling contract.")
    if hasattr(model, "normalized_capacity_aggregate_recoverability"):
        model.normalized_capacity_aggregate_recoverability.deactivate()
    model.c0_fixed_bf_aggregate_floor_active = False
    model.c0_stateful_recoverability_contract = str(rolling["contract_version"])

    fraction = float(rolling["route_band_fraction"])
    quota_hours = int(rolling["quota_period_hours"])
    future_days = 7 - int(day_index)
    route_expressions = _c0_route_expressions(model)
    model.c0_week_route_recoverability = ConstraintList()
    route_audit: dict[str, dict[str, float]] = {}
    for route_id, annual_target in rolling["route_annual_targets_t_y"].items():
        target = float(annual_target) * quota_hours / HOURS_PER_YEAR
        lower = target * (1.0 - fraction)
        upper = target * (1.0 + fraction)
        completed = float(state.cumulative_route_progress_t.get(route_id, 0.0))
        current = route_expressions[str(route_id)]
        # The 120% ceiling is the already-governed C0 daily production
        # guardrail, reused here only to prove remaining-week recoverability.
        maximum_future_day = target / 7.0 * 1.20
        if str(route_id) == "C0_BOF_crude_steel_output_t":
            scrap_per_t_liquid_steel = float(
                config["c0_material_contract"]["bof_scrap_t_per_t_liquid_steel"]
            )
            scrap_cap_t_h = float(
                value(model.c0_bof_hourly_scrap_cap[model.TIME.first()].upper)
            )
            maximum_future_day = min(
                maximum_future_day,
                scrap_cap_t_h / scrap_per_t_liquid_steel * EXECUTION_HOURS,
            )
        elif str(route_id) == "C0_DSP_final_product_t":
            maximum_future_day = min(
                maximum_future_day,
                float(
                    config["plant_dynamics"]["downstream_temporal_contract"]
                    ["dsp_final_product_max_t_h"]
                )
                * EXECUTION_HOURS,
            )
        lower_today = max(0.0, lower - completed - future_days * maximum_future_day)
        upper_today = min(maximum_future_day, max(0.0, upper - completed))
        model.c0_week_route_recoverability.add(current >= lower_today)
        model.c0_week_route_recoverability.add(current <= upper_today)
        route_audit[str(route_id)] = {
            "week_target_t": target,
            "week_lower_t": lower,
            "week_upper_t": upper,
            "completed_before_t": completed,
            "lower_today_t": lower_today,
            "upper_today_t": upper_today,
            "maximum_future_day_t": maximum_future_day,
        }
    model.c0_week_route_audit = route_audit

    remaining_period_hours = (future_days + 1) * EXECUTION_HOURS
    if future_days > 0 and remaining_period_hours > PHYSICAL_HORIZON_HOURS:
        bf_assets = ("blast_furnace_6", "blast_furnace_7")
        future_hours = future_days * EXECUTION_HOURS
        model.c0_future_reachable_bf_rate_t_h = Var(
            bf_assets, range(future_hours), domain=NonNegativeReals
        )
        model.c0_future_reachable_bf_constraints = ConstraintList()
        dynamics = config["plant_dynamics"]
        normalized_assets = dynamics["normalized_capacity_contract"]["assets"]
        for asset in bf_assets:
            short_name = "bf6" if asset.endswith("6") else "bf7"
            maximum_rate = float(normalized_assets[asset]["resolved_maximum_t_h"])
            maximum_step = float(dynamics[short_name]["maximum_step_t_h"])
            for future_hour in range(future_hours):
                reachable = model.c0_future_reachable_bf_rate_t_h[
                    asset, future_hour
                ]
                model.c0_future_reachable_bf_constraints.add(
                    reachable <= maximum_rate
                )
                model.c0_future_reachable_bf_constraints.add(
                    reachable
                    <= getattr(model, asset)[EXECUTION_HOURS - 1]
                    + maximum_step * (future_hour + 1)
                )
        conversion = rolling["active_conversion_reuse"]
        future_hot_metal_from_bf = float(
            conversion["bf_hot_metal_t_per_t_activity"]
        ) * sum(
            model.c0_future_reachable_bf_rate_t_h[asset, future_hour]
            for asset in bf_assets
            for future_hour in range(future_hours)
        )
        supply_assets = ("coking_plant_1", "coking_plant_2", "sintering_plant")
        model.c0_future_reachable_supply_rate_t_h = Var(
            supply_assets, range(future_hours), domain=NonNegativeReals
        )
        model.c0_future_reachable_supply_constraints = ConstraintList()
        for asset in supply_assets:
            maximum_rate = float(normalized_assets[asset]["resolved_maximum_t_h"])
            if asset == "sintering_plant":
                maximum_step = float(dynamics["sifa"]["ramp_t_h_per_hour"])
                block_hours = 1
            else:
                maximum_step = float(
                    dynamics["kgf1" if asset.endswith("1") else "kgf2"][
                        "maximum_step_t_h"
                    ]
                )
                block_hours = int(
                    dynamics["kgf1" if asset.endswith("1") else "kgf2"][
                        "setpoint_block_hours"
                    ]
                )
            for future_hour in range(future_hours):
                reachable = model.c0_future_reachable_supply_rate_t_h[
                    asset, future_hour
                ]
                model.c0_future_reachable_supply_constraints.add(
                    reachable <= maximum_rate
                )
                model.c0_future_reachable_supply_constraints.add(
                    reachable
                    <= getattr(model, asset)[EXECUTION_HOURS - 1]
                    + maximum_step * math.ceil((future_hour + 1) / block_hours)
                )
        inventory_bands = context.terminal_inventory_band[C0_CONFIGURATION]
        future_hot_metal_from_sinter = (
            model.sinter_inventory[EXECUTION_HOURS - 1]
            + float(conversion["sinter_t_per_t_sifa_activity"])
            * sum(
                model.c0_future_reachable_supply_rate_t_h[
                    "sintering_plant", future_hour
                ]
                for future_hour in range(future_hours)
            )
            - float(inventory_bands["sinter_inventory_t"]["lower_t"])
        ) / float(conversion["sinter_t_per_t_hot_metal"])
        future_hot_metal_from_coke = (
            model.coke_inventory[EXECUTION_HOURS - 1]
            + float(conversion["coke_t_per_t_activity"])
            * sum(
                model.c0_future_reachable_supply_rate_t_h[asset, future_hour]
                for asset in ("coking_plant_1", "coking_plant_2")
                for future_hour in range(future_hours)
            )
            - float(inventory_bands["coke_inventory_t"]["lower_t"])
        ) / float(conversion["coke_t_per_t_hot_metal"])
        model.c0_future_hot_metal_recoverable_t = Var(domain=NonNegativeReals)
        model.c0_future_hot_metal_recoverability_limits = ConstraintList()
        for available in (
            future_hot_metal_from_bf,
            future_hot_metal_from_sinter,
            future_hot_metal_from_coke,
        ):
            model.c0_future_hot_metal_recoverability_limits.add(
                model.c0_future_hot_metal_recoverable_t <= available
            )
        bof_route = route_expressions["C0_BOF_crude_steel_output_t"]
        bof_lower = route_audit["C0_BOF_crude_steel_output_t"]["week_lower_t"]
        bof_completed = route_audit["C0_BOF_crude_steel_output_t"][
            "completed_before_t"
        ]
        hot_iron_lower = float(
            _c0_week_terminal_inventory_bands(context, config)[
                "hot_iron_inventory_t"
            ]["lower_t"]
        )
        model.c0_hot_iron_calendar_recoverability = Constraint(
            expr=model.hot_iron_inventory[EXECUTION_HOURS - 1]
            + model.c0_future_hot_metal_recoverable_t
            >= float(conversion["bof_hot_metal_t_per_t_liquid_steel"])
            * (bof_lower - bof_completed - bof_route)
            + hot_iron_lower
        )

    if remaining_period_hours <= PHYSICAL_HORIZON_HOURS:
        model.c0_physical_tail_week_closure = ConstraintList()
        tail_routes = _c0_route_expressions_over_hours(model, remaining_period_hours)
        for route_id, annual_target in rolling["route_annual_targets_t_y"].items():
            target = float(annual_target) * quota_hours / HOURS_PER_YEAR
            completed = float(state.cumulative_route_progress_t.get(route_id, 0.0))
            model.c0_physical_tail_week_closure.add(
                completed + tail_routes[str(route_id)] >= target * (1.0 - fraction)
            )
            model.c0_physical_tail_week_closure.add(
                completed + tail_routes[str(route_id)] <= target * (1.0 + fraction)
            )

    inventory_map = dict(rolling["inventory_components"])
    week_inventory_bands = _c0_week_terminal_inventory_bands(context, config)
    model.c0_week_terminal_inventory_bands_t = week_inventory_bands
    model.c0_week_terminal_inventory_basis = (
        "governed_fixed_initial_terminal_quantity_with_one_percent_band"
    )
    values = {key: float(value_) for key, value_ in (inventory_values_eur_per_t or {}).items()}
    model.c0_inventory_shortfall_t = Var(tuple(inventory_map), domain=NonNegativeReals)
    model.c0_inventory_continuation_constraints = ConstraintList()
    continuation = 0.0
    for inventory_id, component_name in inventory_map.items():
        band = week_inventory_bands[inventory_id]
        handoff = getattr(model, str(component_name))[EXECUTION_HOURS - 1]
        model.c0_inventory_continuation_constraints.add(
            model.c0_inventory_shortfall_t[inventory_id]
            >= float(band["target_t"]) - handoff
        )
        continuation += values.get(inventory_id, 0.0) * model.c0_inventory_shortfall_t[
            inventory_id
        ]
        if remaining_period_hours <= PHYSICAL_HORIZON_HOURS:
            terminal_index = remaining_period_hours - 1
            terminal_inventory = getattr(model, str(component_name))[terminal_index]
            model.c0_inventory_continuation_constraints.add(
                terminal_inventory >= float(band["lower_t"])
            )
            model.c0_inventory_continuation_constraints.add(
                terminal_inventory <= float(band["upper_t"])
            )
    model.c0_inventory_values_eur_per_t = values
    return continuation


def _build_model(
    context: Any,
    state: SteelRollingState,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    prices: Sequence[float],
    *,
    configuration: str,
    lower_taps: int = 0,
    upper_taps: int = 0,
    fixed_taps: int | None = None,
    week_boundary: bool = False,
    continuation_eur_per_heat: float = 0.0,
    remaining_taps: int = 0,
    year_terminal_remaining_taps: int | None = None,
    day_index: int = 1,
    c0_inventory_values_eur_per_t: Mapping[str, float] | None = None,
    annual_readiness: bool = False,
    final_year_day: bool = False,
    year_terminal_recovery_index: int | None = None,
    annual_initial_inventory_targets_t: Mapping[str, float] | None = None,
    physical_horizon_hours: int = PHYSICAL_HORIZON_HOURS,
    physical_tail_heat_days: Sequence[Mapping[str, Any]] | None = None,
    commitment_day_lengths_hours: Sequence[int] | None = None,
    annual_future_heat_calendar: Sequence[Mapping[str, Any]] | None = None,
    annual_current_quota_period_index: int | None = None,
) -> tuple[Any, Any, tuple[float, float]]:
    execution_hours = _execution_hours(context)
    execution_steps = _execution_steps(context)
    physical_horizon_steps = _steps_for_hours(context, int(physical_horizon_hours))
    if not execution_hours <= int(physical_horizon_hours) <= YEAR_END_FULL_HORIZON_HOURS:
        raise HourlyTemporalValidationError("Invalid hourly physical horizon length.")
    if len(prices) != execution_steps:
        raise HourlyTemporalValidationError(
            "Execution price vector must contain one value per model interval."
        )
    band = _execution_product_band(
        context,
        state,
        configuration=configuration,
        c0_config=c0_config,
        c1_config=c1_config,
    )
    contract = (
        _c0_contract(
            c0_config,
            band,
            contract_version=str(context.temporal_contract_version),
            execution_hours=execution_hours,
            physical_horizon_hours=int(physical_horizon_hours),
        )
        if configuration == C0_CONFIGURATION
        else _c1_contract(
            c1_config,
            band,
            contract_version=str(context.temporal_contract_version),
            annual_readiness=annual_readiness,
            physical_horizon_hours=int(physical_horizon_hours),
        )
    )
    hard_year_terminal = bool(
        annual_readiness
        and final_year_day
        and int(physical_horizon_hours) == execution_hours
    )
    if hard_year_terminal:
        contract["inventory_terminal_policy"] = "hard_terminal"
    if commitment_day_lengths_hours is not None:
        if sum(int(value) for value in commitment_day_lengths_hours) != int(
            physical_horizon_hours
        ):
            raise HourlyTemporalValidationError(
                "Commitment-day segments must cover the physical horizon exactly."
            )
        contract["commitment_day_lengths_hours"] = [
            int(value) for value in commitment_day_lengths_hours
        ]
    model = _build_physical_model(
        context,
        configuration,
        state,
        terminal_day=False,
        planning_horizon_hours=int(physical_horizon_hours),
        temporal_repair_contract=contract,
    )
    if annual_readiness:
        shared_product_band = annual_final_product_band(
            configuration=configuration,
            c0_material_contract=c0_config["c0_material_contract"],
        )
        model.shared_annual_recoverability_contract_version = (
            SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION
        )
        model.shared_annual_final_product_band = shared_product_band.audit()
    if hard_year_terminal:
        for name in (
            "coke_terminal",
            "sinter_terminal",
            "hot_iron_terminal",
            "cold_slab_terminal",
            "pellet_terminal",
            "dri_terminal_equality",
            "eaf_slab_terminal",
        ):
            component = getattr(model, name, None)
            if component is not None and component.active:
                component.deactivate()
        model.hourly_hard_year_terminal_replaces_native_cyclic_closure = True
    elif float(context.time_grid.time_step_hours) == 0.25:
        # The native QH heat model exposes unavoidable DRI production in the
        # final physical-tail interval.  A cyclic equality inside that
        # non-executed tail conflicts with the next-replan carry semantics;
        # annual recoverability and executed-state export remain the governing
        # closure contracts.  The actual year-end still uses hard bands above.
        native_dri_terminal = getattr(model, "dri_terminal_equality", None)
        if native_dri_terminal is not None and native_dri_terminal.active:
            native_dri_terminal.deactivate()
        model.qh_physical_tail_replaces_native_dri_cyclic_closure = True
    if configuration == C1_CONFIGURATION and (
        annual_readiness
        or str(context.temporal_contract_version) == C1_ANNUAL_QH_CONTRACT_VERSION
    ):
        # The 48 h fixed-recovery checkpoint belongs to the representative
        # finite-tail diagnostic.  An annual rolling state instead exports the
        # executed inventory and proves a bounded physical continuation, so a
        # reset of DRI or slabs within that continuation would contradict the
        # annual recoverability contract.
        replaced = []
        for name in (
            "temporal_fixed_recovery_dri_terminal",
            "temporal_fixed_recovery_cold_slab_terminal",
        ):
            component = getattr(model, name, None)
            if component is not None and component.active:
                component.deactivate()
                replaced.append(name)
        model.annual_recoverability_replaces_fixed_recovery_checkpoint = tuple(replaced)
    if configuration == C1_CONFIGURATION:
        _add_c1_daily_contract(
            model,
            context,
            c1_config,
            lower_taps=lower_taps,
            upper_taps=upper_taps,
            fixed_taps=fixed_taps,
            week_boundary=week_boundary,
            state=state,
            annual_readiness=annual_readiness,
            physical_horizon_hours=int(physical_horizon_hours),
            physical_tail_heat_days=physical_tail_heat_days,
        )
        c0_continuation = 0.0
    elif annual_readiness:
        _add_c0_annual_progress_contract(model, context, c0_config, state)
        c0_continuation = _add_c0_executed_inventory_continuation(
            model,
            context,
            c0_config,
            c0_inventory_values_eur_per_t,
        )
    else:
        c0_continuation = _add_c0_week_contract(
            model,
            context,
            c0_config,
            state,
            day_index=day_index,
            week_boundary=week_boundary,
            inventory_values_eur_per_t=c0_inventory_values_eur_per_t,
        )
    if annual_readiness:
        if annual_initial_inventory_targets_t is None:
            raise HourlyTemporalValidationError(
                "Annual readiness requires explicit cold-start inventory targets."
            )
        if configuration == C1_CONFIGURATION and not final_year_day:
            _add_c1_annual_residual_product_certificate(
                model,
                context,
                c1_config,
                state,
                annual_initial_inventory_targets_t,
                annual_future_heat_calendar,
                annual_current_quota_period_index,
            )
            if year_terminal_recovery_index is not None:
                for component_name in (
                    "c1_annual_residual_capacity_limits",
                    "c1_future_continuous_reachability",
                    "c1_annual_executed_import_deadline",
                    "c1_annual_physical_tail_import_viability",
                    "c1_annual_joint_residual_product_certificate",
                    "c1_annual_physical_tail_residual_limits",
                    "c1_annual_physical_tail_recursive_product_certificate",
                ):
                    getattr(model, component_name).deactivate()
                model.c1_annual_visible_endpoint_certificate_policy = (
                    "exact_physical_endpoint_replaces_all_abstract_future_residuals"
                )
        _add_annual_physical_tail_handoff_viability(
            model,
            context,
            c0_config,
            c1_config,
            state,
            configuration=configuration,
            physical_horizon_hours=int(physical_horizon_hours),
        )
        _add_execution_year_terminal(
            model,
            annual_initial_inventory_targets_t,
            final_year_day=final_year_day,
            execution_hours=execution_hours,
            physical_horizon_hours=int(physical_horizon_hours),
            recovery_terminal_index=year_terminal_recovery_index,
        )
        if year_terminal_recovery_index is not None:
            _add_year_end_recovery_execution_contract(
                model,
                context,
                state,
                c0_config,
                configuration=configuration,
                remaining_taps=(
                    int(year_terminal_remaining_taps)
                    if year_terminal_remaining_taps is not None
                    else int(remaining_taps)
                ),
                recovery_terminal_index=int(year_terminal_recovery_index),
            )
    physical_prices = tuple(float(item) for item in prices) + (
        (float(prices[-1]),) * (physical_horizon_steps - execution_steps)
    )
    procurement = _represented_cost_expression(
        context,
        model,
        configuration,
        physical_prices,
        objective_hours=range(execution_steps),
    )
    continuation = (
        float(continuation_eur_per_heat)
        * (int(remaining_taps) - model.executed_eaf_taps)
        if configuration == C1_CONFIGURATION and fixed_taps is None
        else 0.0
    )
    model.hourly_scalar_objective = Objective(
        expr=procurement + continuation + c0_continuation,
        sense=minimize,
    )
    model.hourly_represented_procurement_cost_D = procurement
    model.hourly_continuation_value = continuation + c0_continuation
    model.hourly_objective_mode = (
        "scalar_procurement_plus_calibrated_inventory_continuation"
        if configuration == C0_CONFIGURATION
        else "scalar_procurement_plus_linear_heat_continuation"
    )
    model.hourly_annual_readiness_mode = bool(annual_readiness)
    model.annual_execution_hours = execution_hours
    model.annual_execution_steps = execution_steps
    model.annual_physical_horizon_hours = int(physical_horizon_hours)
    model.annual_physical_horizon_steps = physical_horizon_steps
    model.annual_physical_feasibility_lookahead_hours = (
        int(physical_horizon_hours) - execution_hours
    )
    model.annual_physical_tail_price_information_active = False
    model.annual_physical_tail_cost_active = False
    # Retain the accepted H attribute names for downstream reporting/tests;
    # QH callers use the neutral annual attributes above.
    if float(context.time_grid.time_step_hours) == 1.0:
        model.hourly_execution_hours = execution_hours
        model.hourly_physical_horizon_hours = int(physical_horizon_hours)
        model.hourly_physical_feasibility_lookahead_hours = (
            int(physical_horizon_hours) - execution_hours
        )
        model.hourly_physical_tail_price_information_active = False
        model.hourly_physical_tail_cost_active = False
    return model, procurement, band


def _requires_infeasibility_confirmation(
    termination: str,
    *,
    attempt_index: int,
    attempt_count: int,
    confirmation_already_active: bool,
) -> bool:
    return (
        termination == "infeasible"
        and not confirmation_already_active
        and attempt_index < attempt_count
    )


def _solve(
    model: Any,
    objective_expression: Any,
    *,
    case_id: str,
    output: Path,
    strict: bool = False,
    diagnose_infeasible: bool = False,
    warmstart: bool = False,
) -> dict[str, Any]:
    # The first strict calibration solve may return ``infeasible_or_unbounded``
    # with dual reductions enabled.  A same-limit direct confirmation is not a
    # second optimisation policy; it is the required status disambiguation.
    limits = (60.0, 60.0) if strict else (6.0, 60.0)
    ambiguous_status_seen = False
    for attempt_index, limit in enumerate(limits, start=1):
        digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:10]
        log_path = output / "solver_logs" / f"{digest}_a{attempt_index}.log"
        solver = SolverFactory("gurobi")
        solver.options["TimeLimit"] = limit
        solver.options["MIPGap"] = 0.0 if strict else 0.002
        solver.options["Threads"] = 1
        solver.options["Seed"] = 0
        solver.options["FeasibilityTol"] = STATE_FEASIBILITY_TOLERANCE
        solver.options["IntFeasTol"] = STATE_FEASIBILITY_TOLERANCE
        if ambiguous_status_seen:
            solver.options["DualReductions"] = 0
            if diagnose_infeasible:
                solver.options["ResultFile"] = str(
                    output / "solver_logs" / f"{digest}_confirmed_iis.ilp"
                )
        solver.options["LogFile"] = str(log_path)
        started = time.perf_counter()
        result = solver.solve(
            model,
            tee=False,
            load_solutions=False,
            symbolic_solver_labels=ambiguous_status_seen,
            warmstart=warmstart,
        )
        runtime = time.perf_counter() - started
        termination = str(result.solver.termination_condition).lower()
        has_incumbent = len(result.solution) > 0
        if has_incumbent:
            model.solutions.load_from(result)
            incumbent = float(value(objective_expression))
            try:
                bound = float(result.problem.lower_bound)
            except (TypeError, ValueError, AttributeError):
                bound = math.nan
            return {
                "case_id": case_id,
                "attempt": attempt_index,
                "termination_condition": str(result.solver.termination_condition),
                "solver_status": str(result.solver.status),
                "incumbent": True,
                "incumbent_objective_eur": incumbent,
                "best_bound_eur": bound,
                "relative_gap": (
                    abs(incumbent - bound) / max(abs(incumbent), 1.0)
                    if math.isfinite(bound)
                    else math.nan
                ),
                "runtime_seconds": runtime,
                "time_limit_seconds": limit,
                "feasibility_tolerance": STATE_FEASIBILITY_TOLERANCE,
                "integer_feasibility_tolerance": STATE_FEASIBILITY_TOLERANCE,
                "warmstart": bool(warmstart),
                "solver_log": str(log_path.relative_to(REPO_ROOT)),
            }
        if termination == "infeasible":
            # A first solve with Gurobi's dual reductions enabled can report
            # infeasible even though a fresh direct model solve is feasible.
            # Certify the status once with DualReductions=0 before treating it
            # as physical infeasibility or requesting an IIS.
            if _requires_infeasibility_confirmation(
                termination,
                attempt_index=attempt_index,
                attempt_count=len(limits),
                confirmation_already_active=ambiguous_status_seen,
            ):
                ambiguous_status_seen = True
                continue
            if diagnose_infeasible:
                iis_path = (
                    output / "solver_logs" / f"{digest}_confirmed_iis.ilp"
                )
                if not iis_path.exists():
                    write_iis(model, str(iis_path), solver="gurobi")
            raise HourlyTemporalValidationError(f"{case_id} is solver-proven infeasible.")
        if termination in {"infeasibleorunbounded", "infeasible_or_unbounded"}:
            ambiguous_status_seen = True
    raise HourlyTemporalValidationError(
        f"{case_id} is unknown_under_time_limit_or_ambiguous_status "
        "after the governed fallback."
    )


def _advance_state(
    context: Any,
    model: Any,
    state: SteelRollingState,
    *,
    configuration: str,
    contract_version: str,
    timestamp: str,
) -> SteelRollingState:
    execution_hours = _execution_hours(context)
    execution_steps = _execution_steps(context)
    last = execution_steps - 1
    produced = sum(
        _component_value(model, "final_product_output", t)
        for t in range(execution_steps)
    )
    route_increment: dict[str, float] = {}
    for t in range(execution_steps):
        for key, amount in _route_progress_values(context, model, configuration, t).items():
            route_increment[key] = route_increment.get(key, 0.0) + float(amount)
    if configuration == C1_CONFIGURATION:
        route_increment[C1_KGF1_DRY_COAL_PROGRESS_KEY] = sum(
            _component_value(model, "coking_plant_1", t)
            for t in range(execution_steps)
        )
    common = dict(
        episode_id=state.episode_id,
        configuration_id=configuration,
        inventory_overrides=_inventory_overrides(model, configuration, last),
        cumulative_production_t=float(state.cumulative_production_t) + produced,
        executed_hours=int(state.executed_hours) + execution_hours,
        executed_intervals=int(state.executed_intervals) + execution_steps,
        last_executed_timestamp_utc=timestamp,
        cumulative_route_progress_t={
            key: float(state.cumulative_route_progress_t.get(key, 0.0))
            + float(route_increment.get(key, 0.0))
            for key in set(state.cumulative_route_progress_t) | set(route_increment)
        },
        temporal_contract_version=contract_version,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        cumulative_external_scrap_to_bof_t=float(state.cumulative_external_scrap_to_bof_t)
        + sum(
            _component_value(model, "external_scrap_to_bof_t", t)
            for t in range(execution_steps)
        ),
        cumulative_internal_scrap_to_bof_t=float(state.cumulative_internal_scrap_to_bof_t)
        + sum(
            _component_value(model, "internal_scrap_to_bof_t", t)
            for t in range(execution_steps)
        ),
        pefa_last_output_t_h=_component_value(model, "pefa_pellet_output_t", last),
        pellet_inventory_t=_component_value(model, "pellet_inventory", last),
        hsm_last_input_t_h=_component_value(model, "hot_strip_mill", last),
    )
    if configuration == C0_CONFIGURATION:
        return SteelRollingState(
            **common,
            last_continuous_rate_t_h={
                asset: _component_value(model, asset, last)
                for asset in C0_CONTINUOUS_ASSETS
            },
        )
    boundary = execution_steps * EAF_SUBSLOTS_PER_HOUR
    taps = int(
        round(
            sum(
                _component_value(model, "eaf_tap", t)
                for t in range(execution_steps)
            )
        )
    )
    sifa_direction = state.sifa_trend_direction
    last_movement: tuple[int, str] | None = None
    for t in range(execution_steps):
        if _component_value(model, "sifa_up_direction", t) > 0.5:
            last_movement = (t, "up")
        elif _component_value(model, "sifa_down_direction", t) > 0.5:
            last_movement = (t, "down")
    window = int(getattr(model, "sifa_minimum_direction_intervals", 1))
    cooldown = 0
    if last_movement is not None:
        movement, sifa_direction = last_movement
        cooldown = max(0, window - (execution_steps - movement))
    return SteelRollingState(
        **common,
        eaf_start_lag1=int(round(value(model.eaf_heat_start_subslot[boundary - 1]))),
        eaf_start_lag2=int(round(value(model.eaf_heat_start_subslot[boundary - 2]))),
        drp_last_pellet_input_t=_component_value(model, "drp_pellet_input", last),
        last_continuous_rate_t_h={
            asset: _component_value(model, asset, last)
            for asset in CONTINUOUS_ASSETS
        },
        last_vn25_output_mw=_component_value(model, "vn25_electricity_mwh", last),
        eaf_quota_period_id=state.eaf_quota_period_id,
        eaf_quota_target_taps=state.eaf_quota_target_taps,
        eaf_quota_completed_taps=int(state.eaf_quota_completed_taps) + taps,
        cumulative_external_scrap_to_eaf_t=float(state.cumulative_external_scrap_to_eaf_t)
        + sum(
            _component_value(model, "external_scrap_to_eaf_t", t)
            for t in range(execution_steps)
        ),
        cumulative_internal_scrap_to_eaf_t=float(state.cumulative_internal_scrap_to_eaf_t)
        + sum(
            _component_value(model, "internal_scrap_to_eaf_t", t)
            for t in range(execution_steps)
        ),
        sifa_trend_direction=sifa_direction,
        sifa_trend_cooldown_intervals=cooldown,
    )


def _audit(model: Any, band: tuple[float, float], configuration: str) -> list[dict[str, Any]]:
    execution_steps = int(getattr(model, "annual_execution_steps", EXECUTION_HOURS))
    maximum_violation, component = _maximum_incumbent_violation(model)
    produced = sum(
        _component_value(model, "final_product_output", t)
        for t in range(execution_steps)
    )
    rows = [
        {
            "check": "maximum_active_constraint_violation",
            "residual": maximum_violation,
            "tolerance": 1e-5,
            "passed": maximum_violation <= 1e-5,
            "component": component,
        },
        {
            "check": "final_product_execution_band",
            "residual": max(0.0, band[0] - produced, produced - band[1]),
            "tolerance": 1e-5,
            "passed": band[0] - 1e-5 <= produced <= band[1] + 1e-5,
            "component": "final_product_output",
        },
    ]
    for t in range(execution_steps):
        electricity = (
            _component_value(model, "total_generator_electricity_mwh", t)
            + _component_value(model, "gross_grid_import_mwh", t)
            - _component_value(model, "gross_total_electricity_mwh", t)
        )
        rows.append(
            {
                "check": "electricity_identity",
                "residual": electricity,
                "tolerance": 1e-5,
                "passed": abs(electricity) <= 1e-5,
                "component": f"hour_{t}",
            }
        )
    return rows


def _dispatch_rows(
    model: Any,
    prices: Sequence[float],
    *,
    configuration: str,
    strategy: str,
    day: int,
    week_start: datetime,
    timestamps_utc: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    def capacity(name: str, t: int) -> float:
        component = getattr(model, name, None)
        if component is None:
            return math.nan
        try:
            upper = component[t].upper
            return math.nan if upper is None else float(value(upper))
        except (KeyError, TypeError, ValueError):
            return math.nan

    rows: list[dict[str, Any]] = []
    if timestamps_utc is not None and len(timestamps_utc) != len(prices):
        raise HourlyTemporalValidationError(
            "Dispatch timestamps must match the executed price vector."
        )
    for t in range(len(prices)):
        timestamp = (
            pd.Timestamp(timestamps_utc[t]).isoformat()
            if timestamps_utc is not None
            else (week_start + timedelta(days=day - 1, hours=t)).isoformat()
        )
        row = {
            "configuration": "C0" if configuration == C0_CONFIGURATION else "C1",
            "strategy": strategy,
            "day": day,
            "hour": t,
            "timestamp_utc": timestamp,
            "price_eur_per_mwh": float(prices[t]),
            "final_product_t": _component_value(model, "final_product_output", t),
            "grid_import_mwh": _component_value(model, "gross_grid_import_mwh", t),
            "generation_mwh": _component_value(model, "total_generator_electricity_mwh", t),
            "site_electricity_mwh": _component_value(model, "gross_total_electricity_mwh", t),
            "named_ng_mwh": _component_value(model, "total_named_ng_procurement_mwh", t),
            "kgf1_t_h": _component_value(model, "coking_plant_1", t),
            "sifa_t_h": _component_value(model, "sintering_plant", t),
            "bf6_t_h": _component_value(model, "blast_furnace_6", t),
            "hsm_t_h": _component_value(model, "hot_strip_mill", t),
            "bof_electricity_mwh": _component_value(model, "bof_electricity_mwh", t),
            "hsm_electricity_mwh": _component_value(
                model, "hsm_rolling_electricity_mwh", t
            ),
            "dsp_electricity_mwh": _component_value(model, "dsp_electricity_mwh", t),
            "linde_electricity_mwh": _component_value(
                model, "linde_total_electricity_mwh", t
            ),
            "dsp_t_h": _component_value(
                model,
                (
                    "c0_dsp_final_product_output"
                    if configuration == C0_CONFIGURATION
                    else "dsp_final_product_output"
                ),
                t,
            ),
            "pefa_t_h": _component_value(model, "pefa_pellet_output_t", t),
            "coke_inventory_t": _component_value(model, "coke_inventory", t),
            "sinter_inventory_t": _component_value(model, "sinter_inventory", t),
            "hot_iron_inventory_t": _component_value(model, "hot_iron_inventory", t),
            "cold_slab_inventory_t": _component_value(model, "cold_slab_inventory", t),
            "pellet_inventory_t": _component_value(model, "pellet_inventory", t),
            "coke_capacity_t": capacity("coke_capacity", t),
            "sinter_capacity_t": capacity("sinter_capacity", t),
            "hot_iron_capacity_t": capacity("hot_iron_capacity", t),
            "cold_slab_capacity_t": capacity("cold_slab_capacity", t),
            "pellet_capacity_t": capacity("pellet_capacity", t),
            "direct_co2_t": _component_value(model, "total_direct_co2_reporting_t", t),
            "bfg_combustion_co2_t": _component_value(
                model, "bfg_explicit_combustion_co2_t", t
            ),
            "cog_combustion_co2_t": _component_value(
                model, "cog_explicit_combustion_co2_t", t
            ),
            "bofg_combustion_co2_t": _component_value(
                model, "bofg_explicit_combustion_co2_t", t
            ),
            "named_ng_combustion_co2_t": _component_value(
                model, "explicit_ng_combustion_co2_t", t
            ),
            "unmodelled_direct_co2_t": _component_value(
                model, "residual_unmodelled_direct_co2_t", t
            ),
        }
        if configuration == C0_CONFIGURATION:
            row.update(
                {
                    "kgf2_t_h": _component_value(model, "coking_plant_2", t),
                    "bf7_t_h": _component_value(model, "blast_furnace_7", t),
                    "drp_t_h": math.nan,
                    "eaf_starts": math.nan,
                    "eaf_taps": math.nan,
                    "eaf_occupancy_fraction": math.nan,
                    "dri_inventory_t": math.nan,
                    "dri_capacity_t": math.nan,
                    "drp_dri_output_t": math.nan,
                    "eaf_dri_input_t": math.nan,
                    "hdri_direct_to_eaf_t": math.nan,
                    "hdri_to_cdri_storage_t": math.nan,
                    "cdri_from_storage_to_eaf_t": math.nan,
                    "cdri_share_of_eaf_dri": math.nan,
                    "eaf_cold_dri_reheat_electricity_mwh": math.nan,
                    "drp_electricity_mwh": math.nan,
                    "eaf_electricity_mwh": math.nan,
                    "vn25_mw": math.nan,
                }
            )
        else:
            row.update(
                {
                    "kgf2_t_h": math.nan,
                    "bf7_t_h": math.nan,
                    "drp_t_h": _component_value(model, "drp_pellet_input", t),
                    "eaf_starts": _component_value(model, "eaf_heat_start", t),
                    "eaf_taps": _component_value(model, "eaf_tap", t),
                    "eaf_occupancy_fraction": _component_value(model, "eaf_on", t),
                    "dri_inventory_t": _component_value(model, "dri_inventory", t),
                    "dri_capacity_t": float(
                        getattr(model, "c1_dri_buffer_active_capacity_t", math.nan)
                    ),
                    "drp_dri_output_t": _component_value(
                        model, "drp_dri_output", t
                    ),
                    "eaf_dri_input_t": _component_value(
                        model, "eaf_dri_input", t
                    ),
                    "hdri_direct_to_eaf_t": _component_value(
                        model, "hdri_direct_to_eaf_t", t
                    ),
                    "hdri_to_cdri_storage_t": _component_value(
                        model, "hdri_to_cdri_storage_t", t
                    ),
                    "cdri_from_storage_to_eaf_t": _component_value(
                        model, "cdri_from_storage_to_eaf_t", t
                    ),
                    "cdri_share_of_eaf_dri": (
                        _component_value(model, "cdri_from_storage_to_eaf_t", t)
                        / _component_value(model, "eaf_dri_input", t)
                        if _component_value(model, "eaf_dri_input", t) > 1e-9
                        else 0.0
                    ),
                    "eaf_cold_dri_reheat_electricity_mwh": _component_value(
                        model, "eaf_cold_dri_reheat_electricity_mwh", t
                    ),
                    "drp_electricity_mwh": _component_value(
                        model, "drp_electricity_mwh", t
                    ),
                    "eaf_electricity_mwh": _component_value(
                        model, "eaf_total_electricity_mwh", t
                    ),
                    "vn25_mw": _component_value(model, "vn25_electricity_mwh", t),
                }
            )
        rows.append(row)
    return rows


def _eaf_subhourly_load_rows(
    model: Any,
    prices: Sequence[float],
    *,
    strategy: str,
    day: int,
    week_start: datetime,
) -> list[dict[str, Any]]:
    """Expose the internal EAF heat states without changing hourly settlement.

    Arc power is a hard physical subslot expression. Cold-DRI premium energy is
    allocated uniformly over the active melting subslots of its settlement
    hour. Secondary metallurgy remains the existing post-tap hourly accounting
    block and is shown separately from furnace arc power.
    """

    if not hasattr(model, "EAF_SUBTIME"):
        return []
    rows: list[dict[str, Any]] = []
    for hour in range(EXECUTION_HOURS):
        melting = [
            _component_value(model, "eaf_melt_subslot", 4 * hour + offset)
            for offset in range(EAF_SUBSLOTS_PER_HOUR)
        ]
        melt_count = sum(melting)
        cold_energy_mwh = _component_value(
            model, "eaf_cold_dri_reheat_electricity_mwh", hour
        )
        cold_power_when_melting_mw = (
            cold_energy_mwh / (DT / EAF_SUBSLOTS_PER_HOUR) / melt_count
            if melt_count > 1e-9
            else 0.0
        )
        secondary_power_mw = _component_value(
            model, "eaf_secondary_electricity_mwh", hour
        )
        for offset in range(EAF_SUBSLOTS_PER_HOUR):
            subslot = 4 * hour + offset
            melt = melting[offset]
            tap = _component_value(model, "eaf_tap_subslot", subslot)
            arc_power_mw = _component_value(
                model, "eaf_arc_power_mw_subslot", subslot
            )
            cold_power_mw = cold_power_when_melting_mw * melt
            phase = (
                "melting_power_on"
                if melt > 0.5
                else "tapping_turnaround"
                if tap > 0.5
                else "idle"
            )
            rows.append(
                {
                    "configuration": "C1",
                    "strategy": strategy,
                    "day": day,
                    "hour": hour,
                    "subslot": offset,
                    "timestamp_utc": (
                        week_start
                        + timedelta(days=day - 1, hours=hour, minutes=15 * offset)
                    ).isoformat(),
                    "price_eur_per_mwh": float(prices[hour]),
                    "phase": phase,
                    "arc_power_mw": arc_power_mw,
                    "cold_dri_reheat_power_mw": cold_power_mw,
                    "secondary_metallurgy_power_mw": secondary_power_mw,
                    "total_eaf_related_power_mw": (
                        arc_power_mw + cold_power_mw + secondary_power_mw
                    ),
                }
            )
    return rows


def _resolved_cost_attribute(model: Any, attribute: str) -> str:
    """Mirror the governed temporal cost mapping used by the scalar objective."""

    resolved = {
        "c0_bof_scrap_input": "external_scrap_to_bof_t",
        "bof_scrap_supply_t": "external_scrap_to_bof_t",
        "eaf_scrap_supply_t": "external_scrap_to_eaf_t",
    }.get(attribute, attribute)
    if getattr(model, "experimental_coal_wag_policy", "inactive") != "inactive":
        resolved = {
            "coking_plant_1": "c1_adjusted_coking_coal_input_t",
            "bf_pci_input_t": "c1_adjusted_pci_input_t",
        }.get(resolved, resolved)
    return resolved


def _normalized_capacity_rows(
    c0_config: Mapping[str, Any], c1_config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    contracts = {
        "C0": c0_config["plant_dynamics"]["normalized_capacity_contract"],
        "C1": c1_config["deterministic_temporal_repair"]["plant_dynamics"][
            "normalized_capacity_contract"
        ],
    }
    for configuration, contract in contracts.items():
        for component, payload in contract["assets"].items():
            rows.append(
                {
                    "configuration": configuration,
                    "component": component,
                    "display_name": payload["display_name"],
                    "asset_family": payload["family"],
                    "reference_rate_t_h": float(payload["reference_rate_t_h"]),
                    "relative_half_width": float(payload["relative_half_width"]),
                    "resolved_minimum": float(payload["resolved_minimum_t_h"]),
                    "resolved_maximum": float(payload["resolved_maximum_t_h"]),
                    "unit": "t/h",
                    "ramp_fraction_of_reference_per_setpoint": float(
                        payload["ramp_fraction_of_reference_per_setpoint"]
                    ),
                    "calibration_evidence_run": contract[
                        "calibration_evidence_run"
                    ],
                    "calibration_price_information": "flat_price_only",
                    "methodological_status": (
                        "normalized_development_envelope_not_technical_capacity"
                    ),
                }
            )
    repair = c1_config["deterministic_temporal_repair"]
    drp = repair["continuous_must_run_assets"]["drp_pellet_input"]
    rows.append(
        {
            "configuration": "C1",
            "component": "drp_pellet_input",
            "display_name": "DRP",
            "asset_family": "drp_unpaired",
            "reference_rate_t_h": float(
                repair["plant_dynamics"]["normal_reference_rates_t_h"][
                    "drp_pellet_input"
                ]
            ),
            "relative_half_width": "",
            "resolved_minimum": float(drp["minimum_rate_t_h"]),
            "resolved_maximum": float(drp["maximum_rate_t_h"]),
            "unit": "t/h",
            "ramp_fraction_of_reference_per_setpoint": "",
            "calibration_evidence_run": "not_applicable_unpaired_asset",
            "calibration_price_information": "not_applicable",
            "methodological_status": "existing_configuration_specific_contract",
        }
    )
    generator = repair["generator_mode"]
    rows.append(
        {
            "configuration": "C1",
            "component": "vn25_electricity_mwh",
            "display_name": "VN25",
            "asset_family": "generator_unpaired",
            "reference_rate_t_h": "",
            "relative_half_width": "",
            "resolved_minimum": float(generator["vn25_minimum_output_mw"]),
            "resolved_maximum": float(generator["vn25_maximum_output_mw"]),
            "unit": "MW",
            "ramp_fraction_of_reference_per_setpoint": "",
            "calibration_evidence_run": "not_applicable_unpaired_asset",
            "calibration_price_information": "not_applicable",
            "methodological_status": "existing_generator_development_contract",
        }
    )
    return rows


def _cost_category(price_id: str) -> str:
    return {
        "grid_electricity_flat_nl": "Grid electricity",
        "natural_gas_ttf_proxy": "Natural gas",
        "coking_coal_hcc_proxy": "Coking coal",
        "pci_coal_proxy": "PCI coal",
        "iron_ore_62fe_proxy": "Iron ore",
        "imported_bf_pellets_proxy": "Imported BF pellets",
        "imported_dr_pellets_proxy": "Imported DR pellets",
        "purchased_scrap_proxy": "External scrap",
        "imported_slab_proxy": "Imported slabs",
        "hbi_import_proxy": "Imported HBI",
    }.get(price_id, price_id.replace("_", " ").title())


def _cost_rows(
    context: Any,
    model: Any,
    realised_prices: Sequence[float],
    *,
    configuration: str,
    strategy: str,
    day: int,
) -> list[dict[str, Any]]:
    """Reconstruct represented executed-day procurement cost by governed flow."""

    rows: list[dict[str, Any]] = []
    label = "C0" if configuration == C0_CONFIGURATION else "C1"
    for flow in _applicable_cost_flows(context, configuration):
        price_id = str(flow["price_id"])
        is_grid = price_id == "grid_electricity_flat_nl"
        quantity = 0.0
        cost = 0.0
        resolved_attributes: list[str] = []
        for raw_attribute in str(flow["model_component_attribute"]).split(";"):
            attribute = _resolved_cost_attribute(model, raw_attribute)
            resolved_attributes.append(attribute)
            if not hasattr(model, attribute):
                raise HourlyTemporalValidationError(
                    f"Cost-ledger component is missing: {attribute}."
                )
            component = getattr(model, attribute)
            for t in range(len(realised_prices)):
                amount = float(value(component[t]))
                unit_price = (
                    float(realised_prices[t])
                    if is_grid
                    else float(flow["constant_price_eur"])
                )
                quantity += amount
                cost += amount * unit_price
        rows.append(
            {
                "configuration": label,
                "granularity": (
                    "QH"
                    if str(getattr(context, "granularity", "hourly")) == "quarterhour"
                    else "H"
                ),
                "strategy": strategy,
                "day": day,
                "market_scope": "deterministic_no_bidding_no_mfrr",
                "flow_id": str(flow["flow_id"]),
                "cost_category": _cost_category(price_id),
                "component": str(flow.get("component", "")),
                "cost_route": str(flow.get("cost_route", "")),
                "resolved_model_components": ";".join(resolved_attributes),
                "price_id": price_id,
                "quantity": quantity,
                "quantity_unit": str(flow.get("physical_unit", "")),
                "average_unit_price_eur": cost / quantity if quantity > 0.0 else math.nan,
                "cost_eur": cost,
                "cost_boundary": "represented_external_procurement_only",
            }
        )
    return rows


def _response_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    assets = ("kgf1_t_h", "sifa_t_h", "bf6_t_h", "drp_t_h", "hsm_t_h", "dsp_t_h", "pefa_t_h", "vn25_mw")
    rows: list[dict[str, Any]] = []
    for (configuration, strategy), group in frame.groupby(["configuration", "strategy"]):
        for asset in assets:
            values = pd.to_numeric(group[asset], errors="coerce").dropna()
            if values.empty:
                continue
            aligned_prices = pd.to_numeric(group.loc[values.index, "price_eur_per_mwh"])
            rows.append(
                {
                    "configuration": configuration,
                    "strategy": strategy,
                    "asset": asset,
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                    "mean": float(values.mean()),
                    "total_variation": float(values.diff().abs().sum()),
                    "price_correlation": (
                        float(values.corr(aligned_prices))
                        if values.nunique() > 1 and aligned_prices.nunique() > 1
                        else math.nan
                    ),
                }
            )
    return rows


def _calibrate_continuation(
    context: Any,
    state: SteelRollingState,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    output: Path,
    attempts: list[dict[str, Any]],
    artifact_name: str = "hourly_continuation_calibration.json",
) -> float:
    costs: dict[int, float] = {}
    execution_steps = _execution_steps(context)
    for count in (26, 28):
        model, procurement, _ = _build_model(
            context,
            state,
            c0_config,
            c1_config,
            (80.0,) * execution_steps,
            configuration=C1_CONFIGURATION,
            lower_taps=count,
            upper_taps=count,
            fixed_taps=count,
        )
        attempt = _solve(
            model,
            procurement,
            case_id=f"continuation_fixed_{count}",
            output=output,
            strict=True,
        )
        attempts.append(attempt)
        costs[count] = float(attempt["incumbent_objective_eur"])
    kappa = (costs[28] - costs[26]) / 2.0
    if not math.isfinite(kappa) or kappa < 0.0:
        raise HourlyTemporalValidationError("Hourly heat continuation marginal is invalid.")
    _write_json(
        output / artifact_name,
        {"fixed_26_cost_eur": costs[26], "fixed_28_cost_eur": costs[28], "kappa_eur_per_heat": kappa},
    )
    return kappa


def _calibrate_c0_inventory_continuation(
    context: Any,
    state: SteelRollingState,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    output: Path,
    attempts: list[dict[str, Any]],
) -> dict[str, float]:
    rolling = c0_config["c0_hourly_rolling_contract"]
    calibration = rolling["inventory_value_calibration"]
    flat_price = float(calibration["price_eur_per_mwh"])
    perturbation_fraction = float(calibration["perturbation_fraction_of_capacity"])
    execution_steps = _execution_steps(context)
    values: dict[str, float] = {}
    evidence: dict[str, Any] = {
        "method": str(calibration["method"]),
        "price_eur_per_mwh": flat_price,
        "state": state.snapshot(),
        "endpoints": {},
    }
    for inventory_id, component_name in rolling["inventory_components"].items():
        band = _c0_week_terminal_inventory_bands(context, c0_config)[inventory_id]
        reference_level = float(band["target_t"])
        delta = float(band["capacity_t"]) * perturbation_fraction
        reference_model, reference_procurement, _ = _build_model(
            context,
            state,
            c0_config,
            c1_config,
            (flat_price,) * execution_steps,
            configuration=C0_CONFIGURATION,
            day_index=1,
        )
        reference_model.c0_inventory_calibration_reference = Constraint(
            expr=getattr(reference_model, str(component_name))[execution_steps - 1]
            == reference_level
        )
        reference_basis = "governed_terminal_target"
        try:
            reference_attempt = _solve(
                reference_model,
                reference_procurement,
                case_id=f"c0_inventory_value_{inventory_id}_reference",
                output=output,
                strict=True,
            )
        except HourlyTemporalValidationError as exc:
            if "solver-proven infeasible" not in str(exc):
                raise
            reference_basis = "reachable_flat_price_handoff"
            reference_model, reference_procurement, _ = _build_model(
                context,
                state,
                c0_config,
                c1_config,
                (flat_price,) * execution_steps,
                configuration=C0_CONFIGURATION,
                day_index=1,
            )
            reference_attempt = _solve(
                reference_model,
                reference_procurement,
                case_id=f"c0_inventory_value_{inventory_id}_reachable_reference",
                output=output,
                strict=True,
            )
            reference_level = _component_value(
                reference_model, str(component_name), execution_steps - 1
            )
        attempts.append(reference_attempt)
        reference_cost = float(reference_attempt["incumbent_objective_eur"])
        reference_levels = {
            str(other_inventory_id): _component_value(
                reference_model, str(other_component_name), execution_steps - 1
            )
            for other_inventory_id, other_component_name in rolling[
                "inventory_components"
            ].items()
        }
        reference_routes = {
            route_id: float(value(expression))
            for route_id, expression in _c0_route_expressions(
                reference_model, execution_steps
            ).items()
        }
        if reference_basis == "reachable_flat_price_handoff" and not math.isclose(
            reference_level, float(band["target_t"]), abs_tol=1e-6
        ):
            direction = 1.0 if float(band["target_t"]) > reference_level else -1.0
            endpoint_level = reference_level + direction * min(
                delta, abs(float(band["target_t"]) - reference_level)
            )
        else:
            endpoint_level = min(float(band["capacity_t"]), reference_level + delta)
        if endpoint_level - reference_level <= 1e-6:
            endpoint_level = max(0.0, reference_level - delta)
        requested_endpoint_level = float(endpoint_level)
        attempt = None
        endpoint_scale = math.nan
        for candidate_scale in (1.0, 0.5, 0.25, 0.10, 0.05):
            endpoint_level = reference_level + candidate_scale * (
                requested_endpoint_level - reference_level
            )
            model, procurement, _ = _build_model(
                context,
                state,
                c0_config,
                c1_config,
                (flat_price,) * execution_steps,
                configuration=C0_CONFIGURATION,
                day_index=1,
            )
            model.c0_inventory_calibration_endpoints = ConstraintList()
            for fixed_inventory_id, fixed_component_name in rolling[
                "inventory_components"
            ].items():
                fixed_target = float(reference_levels[str(fixed_inventory_id)])
                if fixed_inventory_id == inventory_id:
                    fixed_target = float(endpoint_level)
                model.c0_inventory_calibration_endpoints.add(
                    getattr(model, str(fixed_component_name))[execution_steps - 1]
                    == fixed_target
                )
            if inventory_id == "cold_slab_inventory_t":
                model.c0_inventory_calibration_endpoints.add(
                    sum(model.final_product_output[t] for t in range(execution_steps))
                    == float(
                        reference_routes["C0_HSM_final_product_t"]
                        + reference_routes["C0_DSP_final_product_t"]
                    )
                )
            else:
                for route_id, route_expression in _c0_route_expressions(
                    model, execution_steps
                ).items():
                    model.c0_inventory_calibration_endpoints.add(
                        route_expression == float(reference_routes[route_id])
                    )
            try:
                attempt = _solve(
                    model,
                    procurement,
                    case_id=(
                        f"c0_inventory_value_{inventory_id}_perturbed_"
                        f"scale_{candidate_scale:g}"
                    ),
                    output=output,
                    strict=True,
                )
            except HourlyTemporalValidationError as exc:
                if "solver-proven infeasible" not in str(exc):
                    raise
                continue
            endpoint_scale = candidate_scale
            break
        if attempt is None:
            values[str(inventory_id)] = 0.0
            evidence["endpoints"][str(inventory_id)] = {
                "governed_terminal_target_t": float(band["target_t"]),
                "reference_basis": reference_basis,
                "reference_handoff_t": reference_levels,
                "reference_routes_t": reference_routes,
                "requested_endpoint_t": requested_endpoint_level,
                "accepted_endpoint_scale": None,
                "status": "not_applicable_unreachable_coupled_endpoint",
                "marginal_value_eur_per_t": 0.0,
            }
            continue
        attempts.append(attempt)
        endpoint_cost = float(attempt["incumbent_objective_eur"])
        _write_csv(output / "solver_attempts_partial.csv", attempts)
        marginal = (endpoint_cost - reference_cost) / abs(
            endpoint_level - reference_level
        )
        if not math.isfinite(marginal) or marginal < -1e-6:
            raise HourlyTemporalValidationError(
                f"Invalid C0 inventory marginal for {inventory_id}: {marginal}."
            )
        values[str(inventory_id)] = max(0.0, marginal)
        evidence["endpoints"][str(inventory_id)] = {
            "governed_terminal_target_t": float(band["target_t"]),
            "reference_basis": reference_basis,
            "reference_handoff_t": reference_levels,
            "reference_routes_t": reference_routes,
            "endpoint_t": endpoint_level,
            "requested_endpoint_t": requested_endpoint_level,
            "accepted_endpoint_scale": endpoint_scale,
            "baseline_cost_eur": reference_cost,
            "endpoint_cost_eur": endpoint_cost,
            "marginal_value_eur_per_t": values[str(inventory_id)],
        }
    evidence["values_eur_per_t"] = values
    _write_json(output / "c0_inventory_continuation_calibration.json", evidence)
    return values


def run_hourly_example_week(
    *,
    run_id: str = "high_volatility_hourly_week_01",
    regime: str = "high_volatility",
    annual_readiness: bool = False,
) -> dict[str, Any]:
    c0_config = load_c0_validation_config()
    c1_config = load_temporal_repair_config(REPO_ROOT / c0_config["base_temporal_config"])
    behaviour = load_validation_config(REPO_ROOT / c0_config["behaviour_validation_config"])
    _activate_c1_calibration_bundle(c1_config, behaviour)
    output = (
        YEAR_READINESS_OUTPUT_ROOT if annual_readiness else DEFAULT_OUTPUT_ROOT
    ) / run_id
    if output.exists() and any(output.iterdir()):
        raise HourlyTemporalValidationError(f"Refusing to overwrite {output}.")
    (output / "solver_logs").mkdir(parents=True, exist_ok=True)

    c0_contract_version = (
        C0_ANNUAL_HOURLY_CONTRACT_VERSION
        if annual_readiness
        else C0_HOURLY_CONTRACT_VERSION
    )
    c1_contract_version = (
        C1_ANNUAL_HOURLY_CONTRACT_VERSION
        if annual_readiness
        else C1_HOURLY_CONTRACT_VERSION
    )
    c0_context = _hourly_context(c1_config, c0_contract_version)
    c1_context = _hourly_context(c1_config, c1_contract_version)
    manifest, qh_week_prices = load_representative_week_prices(behaviour)
    selected = next(
        row for row in manifest if regime in {str(row["regime_role"]), str(row["case_id"])}
    )
    _write_governed_run_metadata(
        output,
        run_id=run_id,
        regime=regime,
        c0_config=c0_config,
        c1_config=c1_config,
        behaviour_config=behaviour,
        annual_readiness=annual_readiness,
    )
    prices = _hourly_prices(qh_week_prices[str(selected["case_id"])])
    week_start = datetime.fromisoformat(str(selected["start_date"])).replace(tzinfo=timezone.utc)

    attempts: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    dispatch: list[dict[str, Any]] = []
    eaf_subhourly_loads: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    economics: list[dict[str, Any]] = []
    cost_ledger: list[dict[str, Any]] = []

    c1_state = replace(
        initial_temporal_state(c1_config),
        episode_id="hourly_c1_reference",
        temporal_contract_version=c1_contract_version,
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="hourly_reference_week",
        eaf_quota_target_taps=quota_period_target_taps(0),
        eaf_quota_completed_taps=0,
        sifa_trend_cooldown_intervals=0,
    )
    kappa = _calibrate_continuation(
        c1_context, c1_state, c0_config, c1_config, output, attempts
    )

    initial_states = {
        C0_CONFIGURATION: replace(
            initial_c0_state(c0_config, episode_id="hourly_c0_reference"),
            temporal_contract_version=c0_contract_version,
        ),
        C1_CONFIGURATION: c1_state,
    }
    c0_inventory_values = _calibrate_c0_inventory_continuation(
        c0_context,
        initial_states[C0_CONFIGURATION],
        c0_config,
        c1_config,
        output,
        attempts,
    )
    annual_inventory_targets = {
        configuration: _annual_initial_inventory_targets(
            c0_config,
            c1_config,
            configuration=configuration,
        )
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION)
    }
    for configuration in (C0_CONFIGURATION, C1_CONFIGURATION):
        for strategy in ("price_insensitive", "perfect_foresight_D"):
            state = replace(
                initial_states[configuration],
                episode_id=f"hourly_{configuration}_{strategy}",
                eaf_quota_period_id=(
                    f"hourly_{strategy}_week" if configuration == C1_CONFIGURATION else None
                ),
            )
            realised_cost = 0.0
            optimisation_cost = 0.0
            for day in range(1, 8):
                realised = prices[(day - 1) * 24 : day * 24]
                planning = realised if strategy == "perfect_foresight_D" else (80.0,) * 24
                if configuration == C1_CONFIGURATION:
                    remaining = int(state.eaf_quota_target_taps) - int(state.eaf_quota_completed_taps)
                    future_days = 7 - day
                    lower = max(26, remaining - 28 * future_days)
                    upper = min(28, remaining - 26 * future_days)
                else:
                    remaining, lower, upper = 0, 0, 0
                model, procurement, band = _build_model(
                    c0_context if configuration == C0_CONFIGURATION else c1_context,
                    state,
                    c0_config,
                    c1_config,
                    planning,
                    configuration=configuration,
                    lower_taps=lower,
                    upper_taps=upper,
                    week_boundary=day == 7,
                    continuation_eur_per_heat=kappa,
                    remaining_taps=remaining,
                    day_index=day,
                    c0_inventory_values_eur_per_t=c0_inventory_values,
                    annual_readiness=annual_readiness,
                    final_year_day=False,
                    annual_initial_inventory_targets_t=annual_inventory_targets[
                        configuration
                    ],
                )
                attempt = _solve(
                    model,
                    model.hourly_scalar_objective.expr,
                    case_id=f"{configuration}_{strategy}_day_{day}",
                    output=output,
                    diagnose_infeasible=True,
                )
                attempts.append(attempt)
                _write_csv(output / "solver_attempts_partial.csv", attempts)
                optimisation_cost += float(value(procurement))
                realised_expression = _represented_cost_expression(
                    c0_context if configuration == C0_CONFIGURATION else c1_context,
                    model,
                    configuration,
                    tuple(realised) + (0.0,) * 24,
                    objective_hours=range(24),
                )
                realised_cost += float(value(realised_expression))
                cost_ledger.extend(
                    _cost_rows(
                        c0_context if configuration == C0_CONFIGURATION else c1_context,
                        model,
                        realised,
                        configuration=configuration,
                        strategy=strategy,
                        day=day,
                    )
                )
                case_audit = _audit(model, band, configuration)
                if not all(bool(row["passed"]) for row in case_audit):
                    failure = next(row for row in case_audit if not bool(row["passed"]))
                    raise HourlyTemporalValidationError(
                        f"Physical audit failed for {configuration}/{strategy}/day {day}: {failure}."
                    )
                audits.extend(
                    {"configuration": configuration, "strategy": strategy, "day": day, **row}
                    for row in case_audit
                )
                dispatch.extend(
                    _dispatch_rows(
                        model,
                        realised,
                        configuration=configuration,
                        strategy=strategy,
                        day=day,
                        week_start=week_start,
                    )
                )
                if configuration == C1_CONFIGURATION:
                    eaf_subhourly_loads.extend(
                        _eaf_subhourly_load_rows(
                            model,
                            realised,
                            strategy=strategy,
                            day=day,
                            week_start=week_start,
                        )
                    )
                before_production = state.cumulative_production_t
                state = _advance_state(
                    c0_context if configuration == C0_CONFIGURATION else c1_context,
                    model,
                    state,
                    configuration=configuration,
                    contract_version=(
                        c0_contract_version
                        if configuration == C0_CONFIGURATION
                        else c1_contract_version
                    ),
                    timestamp=(week_start + timedelta(days=day)).isoformat(),
                )
                state_rows.append(
                    {
                        "configuration": configuration,
                        "strategy": strategy,
                        "day": day,
                        "executed_hours": state.executed_hours,
                        "daily_production_t": state.cumulative_production_t - before_production,
                        "cumulative_production_t": state.cumulative_production_t,
                        "completed_eaf_taps": state.eaf_quota_completed_taps,
                        "eaf_carry_lag1": state.eaf_start_lag1,
                        "eaf_carry_lag2": state.eaf_start_lag2,
                        "coke_inventory_t": state.inventory_overrides.get("coke_store_initial_t", ""),
                        "sinter_inventory_t": state.inventory_overrides.get("sinter_store_initial_t", ""),
                        "hot_iron_inventory_t": state.inventory_overrides.get("hot_iron_store_initial_t", ""),
                        "cold_slab_inventory_t": state.inventory_overrides.get("cold_slab_store_initial_t", ""),
                        "pellet_inventory_t": state.pellet_inventory_t,
                        "dri_inventory_t": state.inventory_overrides.get(
                            "dri_buffer_initial_t", ""
                        ),
                        "cumulative_bof_liquid_steel_t": state.cumulative_route_progress_t.get(
                            "C0_BOF_crude_steel_output_t", ""
                        ),
                        "cumulative_hsm_final_t": state.cumulative_route_progress_t.get(
                            "C0_HSM_final_product_t", ""
                        ),
                        "cumulative_dsp_final_t": state.cumulative_route_progress_t.get(
                            "C0_DSP_final_product_t", ""
                        ),
                    }
                )
                checkpoint_id = f"{configuration}_{strategy}_day_{day}"
                _write_json(
                    output / "checkpoints" / f"{checkpoint_id}.json",
                    state.snapshot(),
                )
                _write_csv(output / "hourly_dispatch_partial.csv", dispatch)
                _write_csv(
                    output / "eaf_subhourly_load_partial.csv", eaf_subhourly_loads
                )
                _write_csv(output / "state_handoff_audit_partial.csv", state_rows)
                _write_csv(output / "physical_audit_partial.csv", audits)
            if configuration == C1_CONFIGURATION and (
                int(state.eaf_quota_completed_taps) != int(state.eaf_quota_target_taps)
                or state.eaf_start_lag1 + state.eaf_start_lag2 != 0
            ):
                raise HourlyTemporalValidationError("Hourly C1 week quota or heat carry did not close.")
            if configuration == C0_CONFIGURATION and not annual_readiness:
                rolling = c0_config["c0_hourly_rolling_contract"]
                fraction = float(rolling["route_band_fraction"])
                quota_hours = int(rolling["quota_period_hours"])
                for route_id, annual_target in rolling["route_annual_targets_t_y"].items():
                    target = float(annual_target) * quota_hours / HOURS_PER_YEAR
                    actual = float(state.cumulative_route_progress_t.get(route_id, 0.0))
                    if not target * (1.0 - fraction) - 1e-4 <= actual <= target * (
                        1.0 + fraction
                    ) + 1e-4:
                        raise HourlyTemporalValidationError(
                            f"Hourly C0 week route did not close: {route_id}={actual}."
                        )
                for inventory_id, band_row in _c0_week_terminal_inventory_bands(
                    c0_context, c0_config
                ).items():
                    state_key = {
                        "coke_inventory_t": "coke_store_initial_t",
                        "sinter_inventory_t": "sinter_store_initial_t",
                        "hot_iron_inventory_t": "hot_iron_store_initial_t",
                        "cold_slab_inventory_t": "cold_slab_store_initial_t",
                    }[inventory_id]
                    actual = float(state.inventory_overrides[state_key])
                    if not float(band_row["lower_t"]) - 1e-4 <= actual <= float(
                        band_row["upper_t"]
                    ) + 1e-4:
                        raise HourlyTemporalValidationError(
                            "Hourly C0 week inventory did not close: "
                            f"{inventory_id}={actual}."
                        )
            label = "C0" if configuration == C0_CONFIGURATION else "C1"
            case_costs = [
                row
                for row in cost_ledger
                if row["configuration"] == label and row["strategy"] == strategy
            ]
            electricity_cost = sum(
                float(row["cost_eur"])
                for row in case_costs
                if row["price_id"] == "grid_electricity_flat_nl"
            )
            grid_mwh = sum(
                float(row["quantity"])
                for row in case_costs
                if row["price_id"] == "grid_electricity_flat_nl"
            )
            ng_cost = sum(
                float(row["cost_eur"])
                for row in case_costs
                if row["price_id"] == "natural_gas_ttf_proxy"
            )
            coal_cost = sum(
                float(row["cost_eur"])
                for row in case_costs
                if row["price_id"] in {"coking_coal_hcc_proxy", "pci_coal_proxy"}
            )
            pellet_cost = sum(
                float(row["cost_eur"])
                for row in case_costs
                if row["price_id"]
                in {"imported_bf_pellets_proxy", "imported_dr_pellets_proxy"}
            )
            case_dispatch = [
                row
                for row in dispatch
                if row["configuration"] == label and row["strategy"] == strategy
            ]
            economics.append(
                {
                    "configuration": label,
                    "granularity": "H",
                    "strategy": strategy,
                    "strategy_label": (
                        "Price insensitive"
                        if strategy == "price_insensitive"
                        else "Perfect foresight"
                    ),
                    "market_scope": "deterministic_no_bidding_no_mfrr",
                    "realised_procurement_cost_eur": realised_cost,
                    "optimisation_procurement_cost_eur": optimisation_cost,
                    "steel_produced_t": state.cumulative_production_t,
                    "cost_eur_per_t": realised_cost / state.cumulative_production_t,
                    "site_electricity_consumed_mwh": sum(
                        float(row["site_electricity_mwh"]) for row in case_dispatch
                    ),
                    "grid_electricity_purchased_mwh": grid_mwh,
                    "average_electricity_price_paid_eur_per_mwh": (
                        electricity_cost / grid_mwh if grid_mwh > 0.0 else math.nan
                    ),
                    "total_electricity_cost_eur": electricity_cost,
                    "total_ng_cost_eur": ng_cost,
                    "total_coal_cost_eur": coal_cost,
                    "total_imported_pellets_cost_eur": pellet_cost,
                    "direct_emissions_tco2": sum(
                        float(row["direct_co2_t"]) for row in case_dispatch
                    ),
                    "mfrr_revenue_eur": "",
                    "mfrr_revenue_status": "not_applicable_no_mfrr_layer",
                    "eaf_taps": state.eaf_quota_completed_taps if configuration == C1_CONFIGURATION else "",
                }
            )

    frame = pd.DataFrame(dispatch)
    responses = _response_rows(frame)
    credibility: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        pi = next(row for row in economics if row["configuration"] == configuration and row["strategy"] == "price_insensitive")
        pf = next(row for row in economics if row["configuration"] == configuration and row["strategy"] == "perfect_foresight_D")
        if not annual_readiness:
            credibility.append(
                {
                    "configuration": configuration,
                    "check": "perfect_foresight_not_more_expensive_than_price_insensitive",
                    "observed": float(pf["realised_procurement_cost_eur"]) - float(pi["realised_procurement_cost_eur"]),
                    "passed": float(pf["realised_procurement_cost_eur"]) <= float(pi["realised_procurement_cost_eur"]) + 1e-4,
                }
            )
            credibility.append(
                {
                    "configuration": configuration,
                    "check": "same_week_production_across_strategies",
                    "observed": float(pf["steel_produced_t"]) - float(pi["steel_produced_t"]),
                    "passed": abs(float(pf["steel_produced_t"]) - float(pi["steel_produced_t"])) <= 1e-3,
                }
            )
        for economic in (pi, pf):
            reconstructed = sum(
                float(row["cost_eur"])
                for row in cost_ledger
                if row["configuration"] == configuration
                and row["strategy"] == economic["strategy"]
            )
            residual = reconstructed - float(economic["realised_procurement_cost_eur"])
            credibility.append(
                {
                    "configuration": configuration,
                    "check": f"represented_cost_ledger_identity__{economic['strategy']}",
                    "observed": residual,
                    "passed": abs(residual) <= 1e-4,
                }
            )
    c1_frame = frame[frame["configuration"] == "C1"]
    dri_thermal_summary: list[dict[str, Any]] = []
    for strategy, thermal in c1_frame.groupby("strategy"):
        total_eaf_dri = float(thermal["eaf_dri_input_t"].sum())
        direct_hdri = float(thermal["hdri_direct_to_eaf_t"].sum())
        cold_dri = float(thermal["cdri_from_storage_to_eaf_t"].sum())
        capacity = float(thermal["dri_capacity_t"].dropna().iloc[0])
        dri_thermal_summary.append(
            {
                "configuration": "C1",
                "strategy": strategy,
                "thermal_state_contract": "600C_HDRI_direct_50C_CDRI_buffer",
                "hdri_direct_to_eaf_t": direct_hdri,
                "hdri_cooled_to_storage_t": float(
                    thermal["hdri_to_cdri_storage_t"].sum()
                ),
                "cdri_from_storage_to_eaf_t": cold_dri,
                "total_eaf_dri_input_t": total_eaf_dri,
                "aggregate_cdri_share": (
                    cold_dri / total_eaf_dri if total_eaf_dri > 0.0 else 0.0
                ),
                "maximum_interval_cdri_share": float(
                    thermal["cdri_share_of_eaf_dri"].max()
                ),
                "maximum_buffer_utilisation_fraction": float(
                    (thermal["dri_inventory_t"] / capacity).max()
                ),
                "cold_dri_electricity_premium_mwh": float(
                    thermal["eaf_cold_dri_reheat_electricity_mwh"].sum()
                ),
                "drp_allocation_balance_residual_t": float(
                    (
                        thermal["drp_dri_output_t"]
                        - thermal["hdri_direct_to_eaf_t"]
                        - thermal["hdri_to_cdri_storage_t"]
                    ).abs().max()
                ),
                "eaf_thermal_input_balance_residual_t": float(
                    (
                        thermal["eaf_dri_input_t"]
                        - thermal["hdri_direct_to_eaf_t"]
                        - thermal["cdri_from_storage_to_eaf_t"]
                    ).abs().max()
                ),
            }
        )
    credibility.extend(
        [
            {
                "configuration": "C1",
                "check": "hourly_sifa_step_within_normalized_contract",
                "observed": float(
                    c1_frame.groupby("strategy")["sifa_t_h"]
                    .apply(lambda series: series.diff().abs().max())
                    .max()
                ),
                "passed": bool(
                    c1_frame.groupby("strategy")["sifa_t_h"]
                    .apply(lambda series: series.diff().abs().max())
                    .max()
                    <= float(
                        c1_config["deterministic_temporal_repair"]["plant_dynamics"]
                        ["sifa"]["ramp_t_h_per_qh"]
                    )
                    + 1e-6
                ),
            },
            {
                "configuration": "C1",
                "check": "eaf_hourly_occupancy_fraction_not_above_one",
                "observed": float(c1_frame["eaf_occupancy_fraction"].max()),
                "passed": bool(c1_frame["eaf_occupancy_fraction"].max() <= 1.0 + 1e-6),
            },
            {
                "configuration": "C1",
                "check": "cold_dri_share_not_above_30_percent",
                "observed": float(c1_frame["cdri_share_of_eaf_dri"].max()),
                "passed": bool(
                    c1_frame["cdri_share_of_eaf_dri"].max() <= 0.30 + 1e-6
                ),
            },
            {
                "configuration": "C1",
                "check": "hdri_cdri_mass_allocations_close",
                "observed": max(
                    max(row["drp_allocation_balance_residual_t"] for row in dri_thermal_summary),
                    max(row["eaf_thermal_input_balance_residual_t"] for row in dri_thermal_summary),
                ),
                "passed": bool(
                    max(
                        max(row["drp_allocation_balance_residual_t"] for row in dri_thermal_summary),
                        max(row["eaf_thermal_input_balance_residual_t"] for row in dri_thermal_summary),
                    )
                    <= 1e-6
                ),
            },
        ]
    )
    _write_csv(output / "hourly_credibility_gate_partial.csv", credibility)
    if not all(bool(row["passed"]) for row in credibility):
        raise HourlyTemporalValidationError("Hourly week credibility gate failed.")

    _write_csv(output / "hourly_dispatch.csv", dispatch)
    _write_csv(output / "eaf_subhourly_load.csv", eaf_subhourly_loads)
    _write_csv(output / "solver_attempts.csv", attempts)
    _write_csv(output / "physical_audit.csv", audits)
    _write_csv(output / "state_handoff_audit.csv", state_rows)
    _write_csv(output / "plant_response_metrics.csv", responses)
    _write_csv(output / "weekly_economics.csv", economics)
    _write_csv(output / "represented_cost_ledger.csv", cost_ledger)
    _write_csv(output / "dri_thermal_summary.csv", dri_thermal_summary)
    _write_csv(
        output / "resolved_plant_capacity_contract.csv",
        _normalized_capacity_rows(c0_config, c1_config),
    )
    _write_csv(output / "credibility_gate.csv", credibility)
    _write_csv(
        output / "annual_objective_contract.csv",
        [
            {
                "configuration": "C0",
                "run_mode": (
                    "causal_annual_prefix_smoke"
                    if annual_readiness
                    else "representative_week"
                ),
                "procurement_active": True,
                "heat_continuation_active": False,
                "inventory_continuation_active": True,
                "future_prices_active": False,
                "physical_tail_cost_active": False,
                "objective_mode": "scalar_procurement_plus_calibrated_inventory_continuation",
            },
            {
                "configuration": "C1",
                "run_mode": (
                    "causal_annual_prefix_smoke"
                    if annual_readiness
                    else "representative_week"
                ),
                "procurement_active": True,
                "heat_continuation_active": True,
                "inventory_continuation_active": False,
                "future_prices_active": False,
                "physical_tail_cost_active": False,
                "objective_mode": "scalar_procurement_plus_linear_heat_continuation",
            },
        ],
    )
    inventory_contract_rows = []
    for configuration, targets in annual_inventory_targets.items():
        for component, target in targets.items():
            inventory_contract_rows.append(
                {
                    "configuration": (
                        "C0" if configuration == C0_CONFIGURATION else "C1"
                    ),
                    "inventory_component": component,
                    "cold_start_t": target,
                    "daily_reset": False,
                    "weekly_terminal": bool(
                        not annual_readiness and configuration == C0_CONFIGURATION
                    ),
                    "annual_terminal": True,
                    "annual_terminal_target_t": target,
                    "annual_terminal_applied_in_seven_day_smoke": False,
                }
            )
    _write_csv(output / "annual_inventory_contract.csv", inventory_contract_rows)
    _write_csv(
        output / "bounded_repair_ledger.csv",
        [
            {
                "iteration": 1,
                "trigger": "fixed BF floor suppressed C0 PF response and ignored the rolling inventory state",
                "old_value": "combined BF6+BF7 activity floor 304.61538462 t/h",
                "new_value": "stateful weekly BOF/HSM/DSP recoverability plus calibrated inventory continuation and hard week closure",
                "affected_kpi": "C0 BF movement, route closure, and coke/sinter/hot-iron/slab handoff",
                "before_result": "PF approximately identical to PI and week-end inventories depleted",
                "after_result": "see credibility gate and state_handoff_audit.csv",
                "classification": "causal_stateful_repair_superseding_constant_floor",
            },
            {
                "iteration": 2,
                "trigger": "rounded MER C0 route anchors conflict with the source-backed SiFa maximum at a 0.5% weekly band",
                "old_value": "weekly C0 route tolerance +/-0.5%",
                "new_value": "weekly C0 route tolerance +/-1.0%",
                "affected_kpi": "C0 BOF/HSM/DSP weekly route feasibility",
                "before_result": "solver-proven infeasible because the sinter-supported BOF ceiling remained below the 0.5% BOF lower bound",
                "after_result": "see physical_audit.csv and state_handoff_audit.csv",
                "classification": "user_authorized_tolerance_for_rounded_source_anchors",
                "derived_constraint_alignment": "C0 aggregate final-product corridor uses the same 1.0% band because it is exactly HSM final plus DSP final",
            }
        ],
    )
    from .s4_4c6_deterministic_figure_package import (
        generate_deterministic_figure_package,
    )

    figure_package = generate_deterministic_figure_package(output, regime=regime)
    _write_json(
        output / "run_manifest.json",
        {
            "run_id": run_id,
            "global_time_step_hours": 1.0,
            "eaf_internal_batch_subslots_minutes": 15,
            "represented_hours": 168,
            "run_mode": (
                "causal_annual_prefix_smoke"
                if annual_readiness
                else "representative_week"
            ),
            "c0_temporal_contract_version": c0_contract_version,
            "c1_temporal_contract_version": c1_contract_version,
            "price_resolution": "hourly_mean_of_source_QH_prices",
            "calendar_contract_version": CALENDAR_CONTRACT_VERSION,
            "maintenance_hours_represented": 0,
            "market_scope": "none",
            "figure_package_version": figure_package["package_version"],
            "full_four_week_matrix_authorized": False,
        },
    )
    gate = {
        "decision": (
            "hourly_year_readiness_smoke_pass_pre_year_actions_remain"
            if annual_readiness
            else "hourly_example_week_physical_and_behaviour_pass"
        ),
        "representative_week": regime,
        "solve_count": len(attempts),
        "bounded_repair_iterations_used": 2,
        "global_time_step_hours": 1.0,
        "eaf_batch_contract": "internal_15_minute_subslots_hourly_energy_aggregation",
        "full_year_certified": False,
        "ready_for_full_year_run": False,
        "pre_full_year_actions": (
            [
                "connect_hourly_8760_calendar_and_price_series_to_this_runner",
                "certify_late_year_inventory_terminal_recoverability",
            ]
            if annual_readiness
            else []
        ),
        "annual_inventory_terminal_tested_statically": bool(annual_readiness),
        "annual_inventory_terminal_executed": False,
        "figure_count": figure_package["figure_count"],
        "full_four_week_matrix_authorized": False,
        "output_root": str(output.relative_to(REPO_ROOT)),
    }
    _write_json(output / "gate_decision.json", gate)
    _write_json(output / "run_summary.json", gate)
    return gate


def run_hourly_year_readiness_smoke(
    *,
    run_id: str = "hourly_year_readiness_smoke_01",
    regime: str = "high_volatility",
) -> dict[str, Any]:
    """Run seven days with annual-prefix semantics; never start the full year."""

    return run_hourly_example_week(
        run_id=run_id,
        regime=regime,
        annual_readiness=True,
    )


def prepare_hourly_annual_run_inputs(
    *,
    run_id: str,
    price_strategy: str = "price_insensitive",
    price_source: Path | None = None,
    source_is_realised_oracle: bool = False,
) -> dict[str, Any]:
    """Materialise the governed 8,760-hour calendar/price interface without solving."""

    c0_config = load_c0_validation_config()
    c1_config = load_temporal_repair_config(REPO_ROOT / c0_config["base_temporal_config"])
    output = YEAR_READINESS_OUTPUT_ROOT.parent / (
        "steel_c6_deterministic_hourly_year_readiness_v2_20260806"
    ) / run_id
    output.mkdir(parents=True, exist_ok=False)
    calendar = build_hourly_annual_calendar(c1_config)
    prices = load_hourly_annual_prices(
        calendar,
        strategy=price_strategy,
        source_path=price_source,
        source_is_realised_oracle=source_is_realised_oracle,
    )
    calendar.to_csv(output / "annual_hourly_calendar.csv", index=False)
    prices.to_csv(output / "annual_hourly_prices.csv", index=False)
    day_contract = (
        calendar.groupby(["calendar_day_index", "local_date"], as_index=False)
        .agg(
            day_length_hours=("local_day_length_hours", "first"),
            start_utc=("timestamp_utc", "min"),
            end_utc=("timestamp_utc", "max"),
            maintenance_hours=("maintenance_active", "sum"),
        )
    )
    day_contract.to_csv(output / "annual_day_contract.csv", index=False)
    summary = {
        "run_id": run_id,
        "status": "annual_inputs_ready_no_solve_started",
        "calendar_hours": len(calendar),
        "calendar_days": int(day_contract.shape[0]),
        "day_length_counts": {
            str(key): int(value_)
            for key, value_ in day_contract["day_length_hours"].value_counts().sort_index().items()
        },
        "maintenance_hours_represented": int(day_contract["maintenance_hours"].sum()),
        "price_strategy": price_strategy,
        "price_contract_version": ANNUAL_HOURLY_PRICE_CONTRACT_VERSION,
        "full_year_solve_started": False,
        "output_policy": "diagnostics",
        "run_class": "diagnostic_validation",
        "lineage_role": "diagnostic_hourly_calendar_and_terminal_recovery_readiness",
        "retention": "local_governed_ignored",
        "git_eligible": False,
        "full_four_week_matrix_authorized": False,
        "output_root": str(output.relative_to(REPO_ROOT)).replace("\\", "/"),
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(output / "gate_decision.json", summary)
    _write_json(
        output / "registry_entry.json",
        {key: summary[key] for key in (
            "run_id", "output_policy", "run_class", "lineage_role", "retention",
            "git_eligible", "full_four_week_matrix_authorized",
        )},
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This prepares the 8,760-hour input contract; it does not solve the year.\n"
        "- Perfect foresight is accepted only as a separately labelled realised-price oracle.\n"
        "- The governed D+4 forecast currently has partial-year support and is not padded.\n"
        "- No DAM, mFRR, stochasticity, S10 or four-week matrix is represented.\n"
        "- `full_four_week_matrix_authorized=false`.\n",
        encoding="utf-8",
    )
    return summary


def _synthetic_late_year_state(
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    *,
    configuration: str,
) -> SteelRollingState:
    """Create a denominator-consistent day-364 reference state for terminal proof."""

    completed_hours = int(HOURS_PER_YEAR) - 48
    fraction = completed_hours / HOURS_PER_YEAR
    targets = _annual_initial_inventory_targets(
        c0_config, c1_config, configuration=configuration
    )
    inventory_overrides = {
        "coke_store_initial_t": targets["coke_inventory"],
        "sinter_store_initial_t": targets["sinter_inventory"],
        "hot_iron_store_initial_t": targets["hot_iron_inventory"],
        "cold_slab_store_initial_t": targets["cold_slab_inventory"],
    }
    if configuration == C0_CONFIGURATION:
        material = c0_config["c0_material_contract"]
        rolling = c0_config["c0_hourly_rolling_contract"]
        return replace(
            initial_c0_state(c0_config, episode_id="c0_late_year_terminal_reference"),
            temporal_contract_version=C0_ANNUAL_HOURLY_CONTRACT_VERSION,
            executed_hours=completed_hours,
            executed_intervals=completed_hours,
            cumulative_production_t=float(material["physical_final_product_t_y"]) * fraction,
            cumulative_route_progress_t={
                str(key): float(amount) * fraction
                for key, amount in rolling["route_annual_targets_t_y"].items()
            },
            cumulative_external_scrap_to_bof_t=float(
                material["annual_external_scrap_cap_t_y"]
            )
            * fraction,
            cumulative_internal_scrap_to_bof_t=float(
                material["annual_internal_scrap_cap_t_y"]
            )
            * fraction,
            inventory_overrides=inventory_overrides,
            pellet_inventory_t=float(targets["pellet_inventory"]),
        )
    annual_taps = int(round(ANNUAL_EAF_ROUTE_T / 325.0))
    inventory_overrides["dri_buffer_initial_t"] = targets["dri_inventory"]
    return replace(
        initial_temporal_state(c1_config),
        episode_id="c1_late_year_terminal_reference",
        temporal_contract_version=C1_ANNUAL_HOURLY_CONTRACT_VERSION,
        executed_hours=completed_hours,
        executed_intervals=completed_hours,
        cumulative_production_t=float(
            prepare_temporal_context(c1_config).config[
                "annual_reference_target_mt_y"
            ]
        )
        * 1_000_000.0
        * fraction,
        cumulative_route_progress_t={
            "C1_BOF_liquid_steel_output_t_h": 3_400_000.0 * fraction,
            "C1_EAF_liquid_steel_output_t_h": ANNUAL_EAF_ROUTE_T * fraction,
            "C1_HSM_final_product_output_t": 5_250_000.0 * fraction,
            "C1_DSP_final_product_output_t": 1_500_000.0 * fraction,
            "C1_imported_slab_to_HSM_t_h": 600_000.0 * fraction,
            C1_KGF1_DRY_COAL_PROGRESS_KEY: float(
                c1_config["deterministic_temporal_repair"]
                ["kgf1_route_scale_reconciliation"]["annual_dry_coal_target_t_y"]
            )
            * fraction,
        },
        cumulative_external_scrap_to_bof_t=700_000.0 * fraction,
        cumulative_external_scrap_to_eaf_t=600_000.0 * fraction,
        cumulative_internal_scrap_to_bof_t=300_000.0 * fraction,
        cumulative_internal_scrap_to_eaf_t=300_000.0 * fraction,
        inventory_overrides=inventory_overrides,
        pellet_inventory_t=float(targets["pellet_inventory"]),
        drp_last_pellet_input_t=DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0],
        eaf_quota_period_id="annual_terminal_48h",
        eaf_quota_target_taps=annual_taps,
        eaf_quota_completed_taps=annual_taps - 54,
    )


def run_hourly_year_terminal_recovery_smoke(
    *,
    run_id: str = "hourly_year_terminal_recovery_01",
) -> dict[str, Any]:
    """Solve day 364/365 from a denominator-consistent late-year state."""

    c0_config = load_c0_validation_config()
    c1_config = load_temporal_repair_config(REPO_ROOT / c0_config["base_temporal_config"])
    behaviour = load_validation_config(REPO_ROOT / c0_config["behaviour_validation_config"])
    _activate_c1_calibration_bundle(c1_config, behaviour)
    output = YEAR_READINESS_OUTPUT_ROOT.parent / (
        "steel_c6_deterministic_hourly_year_readiness_v2_20260806"
    ) / run_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "solver_logs").mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for configuration, contract_version in (
        (C0_CONFIGURATION, C0_ANNUAL_HOURLY_CONTRACT_VERSION),
        (C1_CONFIGURATION, C1_ANNUAL_HOURLY_CONTRACT_VERSION),
    ):
        context = _hourly_context(c1_config, contract_version)
        state = _synthetic_late_year_state(
            c0_config, c1_config, configuration=configuration
        )
        targets = _annual_initial_inventory_targets(
            c0_config, c1_config, configuration=configuration
        )
        for day_number in (364, 365):
            remaining_taps = (
                int(state.eaf_quota_target_taps or 0)
                - int(state.eaf_quota_completed_taps)
            )
            model, _, band = _build_model(
                context,
                state,
                c0_config,
                c1_config,
                (80.0,) * 24,
                configuration=configuration,
                lower_taps=(remaining_taps if day_number == 365 else 27),
                upper_taps=(remaining_taps if day_number == 365 else 27),
                fixed_taps=(
                    remaining_taps
                    if configuration == C1_CONFIGURATION and day_number == 365
                    else (27 if configuration == C1_CONFIGURATION else None)
                ),
                week_boundary=configuration == C1_CONFIGURATION and day_number == 365,
                remaining_taps=remaining_taps,
                annual_readiness=True,
                final_year_day=day_number == 365,
                year_terminal_recovery_index=47 if day_number == 364 else None,
                annual_initial_inventory_targets_t=targets,
                c0_inventory_values_eur_per_t={},
                physical_horizon_hours=48 if day_number == 364 else 24,
            )
            model.hourly_scalar_objective.deactivate()
            model.hourly_terminal_feasibility_objective = Objective(expr=0.0, sense=minimize)
            case_id = f"{'c0' if configuration == C0_CONFIGURATION else 'c1'}_day_{day_number}"
            attempt = _solve(
                model,
                model.hourly_terminal_feasibility_objective.expr,
                case_id=case_id,
                output=output,
                strict=False,
                diagnose_infeasible=True,
            )
            attempts.append({"case_id": case_id, **attempt})
            for component, target in targets.items():
                index = 47 if day_number == 364 else 23
                actual = _component_value(model, component, index)
                terminal_band = model.hourly_annual_inventory_terminal_bands_t[
                    component
                ]
                lower = float(terminal_band["lower_t"])
                upper = float(terminal_band["upper_t"])
                audit_rows.append(
                    {
                        "configuration": "C0" if configuration == C0_CONFIGURATION else "C1",
                        "day": day_number,
                        "terminal_index": index,
                        "inventory_component": component,
                        "target_t": float(target),
                        "lower_t": lower,
                        "upper_t": upper,
                        "actual_t": actual,
                        "residual_t": actual - float(target),
                        "passed": lower - 1e-5 <= actual <= upper + 1e-5,
                    }
                )
            state = _advance_state(
                context,
                model,
                state,
                configuration=configuration,
                contract_version=contract_version,
                timestamp=f"2025-12-{day_number - 334:02d}T23:00:00+00:00",
            )
    passed = all(bool(row["passed"]) for row in audit_rows)
    _write_csv(output / "solver_attempts.csv", attempts)
    _write_csv(output / "annual_inventory_terminal_recovery_audit.csv", audit_rows)
    decision = {
        "run_id": run_id,
        "decision": "hourly_late_year_inventory_recovery_pass" if passed else "needs_bounded_fix",
        "status": "pass" if passed else "fail",
        "day_364_physical_tail_recovery_certified": passed,
        "day_365_executed_terminal_certified": passed,
        "solve_attempts": len(attempts),
        "full_year_solve_started": False,
        "output_policy": "diagnostics",
        "run_class": "diagnostic_validation",
        "lineage_role": "diagnostic_hourly_calendar_and_terminal_recovery_readiness",
        "full_four_week_matrix_authorized": False,
        "output_root": str(output.relative_to(REPO_ROOT)).replace("\\", "/"),
    }
    _write_json(output / "gate_decision.json", decision)
    _write_json(output / "run_summary.json", decision)
    return decision


__all__ = [
    "C0_HOURLY_CONTRACT_VERSION",
    "C0_ANNUAL_HOURLY_CONTRACT_VERSION",
    "C1_HOURLY_CONTRACT_VERSION",
    "C1_ANNUAL_HOURLY_CONTRACT_VERSION",
    "HourlyTemporalValidationError",
    "ANNUAL_HOURLY_PRICE_CONTRACT_VERSION",
    "build_hourly_annual_calendar",
    "load_hourly_annual_prices",
    "prepare_hourly_annual_run_inputs",
    "run_hourly_year_terminal_recovery_smoke",
    "run_hourly_example_week",
    "run_hourly_year_readiness_smoke",
]
