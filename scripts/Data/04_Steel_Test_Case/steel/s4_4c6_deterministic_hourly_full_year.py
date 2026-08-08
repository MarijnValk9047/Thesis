"""Governed hourly C0/C1 deterministic full-year launcher.

The launcher uses one shared realised-price ledger for price-insensitive
settlement, perfect-foresight optimisation and later Strict LEAR D-only
scenario evaluation. It runs no bidding, stochastic or reserve layer.
"""

from __future__ import annotations

import json
import math
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml
from pyomo.environ import Constraint, Var, value
from pyomo.core.expr.visitor import identify_variables

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from .s4_4c6_deterministic_behaviour_anchor_validation import (
    _activate_c1_calibration_bundle,
    load_validation_config,
)
from .s4_4c6_deterministic_c0_temporal_validation import (
    _annualised_rows,
    initial_c0_state,
    load_c0_validation_config,
)
from .s4_4c6_deterministic_hourly_temporal_validation import (
    C0_ANNUAL_HOURLY_CONTRACT_VERSION,
    C0_ANNUAL_QH_CONTRACT_VERSION,
    C1_ANNUAL_HOURLY_CONTRACT_VERSION,
    C1_ANNUAL_QH_CONTRACT_VERSION,
    C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T,
    DEFAULT_RATE_RANGES_T_H,
    HourlyTemporalValidationError,
    YEAR_END_FULL_HORIZON_HOURS,
    _advance_state,
    _annual_initial_inventory_targets,
    _audit,
    _build_model,
    _calibrate_c0_inventory_continuation,
    _calibrate_continuation,
    _component_value,
    _cost_rows,
    _dispatch_rows,
    _hourly_context,
    _qh_context,
    _normalized_capacity_rows,
    _response_rows,
    _sha256_file,
    _solve,
    _write_csv,
    _write_json,
    build_hourly_annual_calendar,
    c0_annual_operational_reconciliation,
)
from .s4_4c6_deterministic_qh_full_year import (
    OUTPUT_ROOT as QH_OUTPUT_ROOT,
    load_qh_annual_calendar_and_prices,
)
from .s4_4c6_shared_annual_recoverability import (
    ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T,
)
from .s4_4c6_deterministic_temporal_repair import (
    CALENDAR_CONTRACT_VERSION,
    HOURS_PER_YEAR,
    _annual_heat_schedule,
    cumulative_eaf_target_taps,
    dynamic_daily_heat_bounds,
    initial_temporal_state,
    load_temporal_repair_config,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelRollingState,
    _represented_cost_expression,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c6_deterministic_hourly_full_year.yaml"
)
OUTPUT_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/runs/"
    "steel_c6_deterministic_hourly_full_year_v1_20260806"
)

EAF_HEAT_SIZE_T = 325.0
EAF_SECONDARY_ELECTRICITY_MWH_PER_T_LIQUID_STEEL = 0.031
SIFA_SINTER_T_PER_T_REPRESENTED_ORE = 1.23
BF_HOT_METAL_T_PER_T_REPRESENTED_ACTIVITY = 2.1041667
DRY_COAL_T_PER_T_COKE = 1.285


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HourlyTemporalValidationError("Hourly full-year config must be a mapping.")
    if payload.get("mode") != "deterministic_hourly_c0_c1_pi_pf_full_year":
        raise HourlyTemporalValidationError("Unexpected hourly full-year run mode.")
    if payload.get("scope", {}).get("full_four_week_matrix_authorized") is not False:
        raise HourlyTemporalValidationError("Four-week matrix must remain unauthorized.")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    temporary.replace(path)


def materialize_lear_strict_realised_price_ledger(
    calendar: pd.DataFrame,
    *,
    source_path: Path,
    timestamp_column: str = "timestamp_utc",
    price_column: str = "price_eur_per_mwh",
    region_column: str | None = "region",
    region: str | None = "NL",
) -> pd.DataFrame:
    """Apply the Strict-LEAR daily price repair on the native DST calendar."""

    path = Path(source_path)
    source = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    required = {timestamp_column, price_column}
    if not required.issubset(source.columns):
        raise HourlyTemporalValidationError(
            f"Realised-price source lacks columns {sorted(required - set(source.columns))}."
        )
    if region_column and region_column in source and region is not None:
        source = source[source[region_column].astype(str) == str(region)].copy()
    source = source[[timestamp_column, price_column]].copy()
    source[timestamp_column] = pd.to_datetime(source[timestamp_column], utc=True, errors="coerce")
    source[price_column] = pd.to_numeric(source[price_column], errors="coerce")
    source = source.dropna(subset=[timestamp_column]).copy()
    if source[timestamp_column].duplicated().any():
        raise HourlyTemporalValidationError("Realised-price source has duplicate UTC timestamps.")
    source = source.rename(
        columns={timestamp_column: "timestamp_utc", price_column: "observed_price_eur_per_mwh"}
    )
    ledger = calendar[
        [
            "calendar_day_index",
            "local_date",
            "local_day_length_hours",
            "annual_hour_index",
            "timestamp_utc",
        ]
    ].merge(source, on="timestamp_utc", how="left", validate="one_to_one")
    ledger["price_eur_per_mwh"] = ledger["observed_price_eur_per_mwh"]
    ledger["is_imputed"] = ledger["price_eur_per_mwh"].isna()
    repaired: list[pd.DataFrame] = []
    for local_date, day in ledger.groupby("local_date", sort=False):
        work = day.copy()
        values = pd.to_numeric(work["price_eur_per_mwh"], errors="coerce")
        if not values.notna().any():
            raise HourlyTemporalValidationError(
                f"Strict-LEAR realised-price repair cannot recover empty day {local_date}."
            )
        values = values.interpolate(method="linear", limit_direction="both")
        if values.isna().any():
            values = values.fillna(float(values.dropna().median()))
        work["price_eur_per_mwh"] = values.astype(float)
        repaired.append(work)
    result = pd.concat(repaired, ignore_index=True).sort_values("annual_hour_index")
    if len(result) != int(HOURS_PER_YEAR) or result["price_eur_per_mwh"].isna().any():
        raise HourlyTemporalValidationError(
            "Strict-LEAR realised-price ledger must close all 8,760 hours."
        )
    result["price_repair_method"] = result["is_imputed"].map(
        {
            False: "observed_cleaned_hourly_price",
            True: "lear_strict_day_local_linear_interpolation_then_daily_median_fallback",
        }
    )
    result["price_contract_version"] = "lear_strict_donly_realised_price_repair_v1"
    result["dst_policy"] = "native_23_25_hour_delivery_days"
    return result.reset_index(drop=True)


def prepare_lear_strict_hourly_year_inputs(
    *,
    run_id: str,
    config_path: Path = CONFIG_PATH,
    output_root: Path = OUTPUT_ROOT,
    allow_existing: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, Path]:
    config = _load_config(config_path)
    output = Path(output_root) / run_id
    if output.exists() and any(output.iterdir()) and not allow_existing:
        raise HourlyTemporalValidationError(f"Refusing to overwrite {output}.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "solver_logs").mkdir(parents=True, exist_ok=True)
    (output / "checkpoints").mkdir(parents=True, exist_ok=True)
    period = config["period"]
    c0_config = load_c0_validation_config()
    c1_config = load_temporal_repair_config(REPO_ROOT / c0_config["base_temporal_config"])
    calendar = build_hourly_annual_calendar(
        c1_config,
        start_local_date=period["start_local_date"],
        end_exclusive_local_date=period["end_exclusive_local_date"],
        timezone_name=period["timezone"],
    )
    source_contract = config["realised_price_source"]
    source_path = REPO_ROOT / str(source_contract["path"])
    ledger = materialize_lear_strict_realised_price_ledger(
        calendar,
        source_path=source_path,
        timestamp_column=str(source_contract["timestamp_column"]),
        price_column=str(source_contract["price_column"]),
        region_column=str(source_contract.get("region_column", "region")),
        region=str(source_contract.get("region", "NL")),
    )
    calendar.to_csv(output / "annual_hourly_calendar.csv", index=False)
    ledger.to_csv(output / "annual_realised_price_ledger.csv", index=False)
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
    input_summary = {
        "status": "lear_strict_hourly_year_inputs_ready",
        "calendar_hours": int(config["period"]["expected_hours"]),
        "calendar_intervals": int(len(calendar)),
        "calendar_days": int(day_contract.shape[0]),
        "day_length_counts": {
            str(key): int(number)
            for key, number in day_contract["day_length_hours"].value_counts().items()
        },
        "observed_price_hours": int((~ledger["is_imputed"]).sum()),
        "imputed_price_hours": int(ledger["is_imputed"].sum()),
        "price_min_eur_per_mwh": float(ledger["price_eur_per_mwh"].min()),
        "price_max_eur_per_mwh": float(ledger["price_eur_per_mwh"].max()),
        "calendar_contract_version": config["calendar_contract_version"],
        "price_contract_version": config["price_contract_version"],
        "realised_price_source": str(source_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "realised_price_source_sha256": _sha256_file(source_path),
        "full_year_solve_started": False,
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "input_contract_summary.json", input_summary)
    return config, calendar, ledger, output


def _initial_state(
    configuration: str,
    *,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    first_quota_target: int,
    strategy: str,
    temporal_contract_version: str | None = None,
    time_step_hours: float = 1.0,
) -> SteelRollingState:
    if configuration == C0_CONFIGURATION:
        return replace(
            initial_c0_state(c0_config, episode_id=f"annual_C0_{strategy}"),
            temporal_contract_version=(
                temporal_contract_version or C0_ANNUAL_HOURLY_CONTRACT_VERSION
            ),
        )
    return replace(
        initial_temporal_state(c1_config),
        episode_id=f"annual_C1_{strategy}",
        temporal_contract_version=(
            temporal_contract_version or C1_ANNUAL_HOURLY_CONTRACT_VERSION
        ),
        # This state field is an interval quantity.  Preserve the hourly
        # convention for H runs and convert the same source rate to one QH
        # quantity for the native-QH annual model.
        drp_last_pellet_input_t=(
            DEFAULT_RATE_RANGES_T_H["drp_pellet_input"][0]
            * float(time_step_hours)
        ),
        eaf_quota_period_id="annual_quota_000",
        eaf_quota_target_taps=int(first_quota_target),
        eaf_quota_completed_taps=0,
        sifa_trend_cooldown_intervals=0,
    )


def _checkpoint_paths(output: Path, case_id: str) -> list[Path]:
    root = output / "checkpoints" / case_id
    if not root.exists():
        return []
    return sorted(root.glob("day_*.json"))


def _load_completed_case(
    output: Path,
    case_id: str,
    *,
    contract_version: str,
) -> tuple[int, SteelRollingState | None, float, float]:
    paths = _checkpoint_paths(output, case_id)
    if not paths:
        return 0, None, 0.0, 0.0
    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    state = SteelRollingState.from_snapshot(
        payload["state_after"],
        required_temporal_contract_version=contract_version,
        required_calendar_contract_version=CALENDAR_CONTRACT_VERSION,
    )
    return (
        int(payload["calendar_day_index"]),
        state,
        float(payload["cumulative_realised_procurement_cost_eur"]),
        float(payload["cumulative_optimisation_procurement_cost_eur"]),
    )


def _materialize_compatible_c0_calibration_seed(
    destination: Path,
    *,
    seed_run_id: str,
    current_state: SteelRollingState,
    seed_root: Path = OUTPUT_ROOT,
) -> bool:
    """Reuse a one-day C0 calibration only across identical initial physics."""

    source = seed_root / seed_run_id / "c0_inventory_continuation_calibration.json"
    if not source.exists():
        return False
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("method") != "strict_flat_price_finite_difference_at_governed_terminal_target":
        raise HourlyTemporalValidationError("C0 calibration seed uses an incompatible method.")
    if abs(float(payload.get("price_eur_per_mwh", math.nan)) - 80.0) > 1e-9:
        raise HourlyTemporalValidationError("C0 calibration seed uses an incompatible price.")
    source_state = dict(payload.get("state", {}))
    current_snapshot = current_state.snapshot()
    source_state.pop("temporal_contract_version", None)
    current_snapshot.pop("temporal_contract_version", None)
    if source_state != current_snapshot:
        raise HourlyTemporalValidationError(
            "C0 calibration seed initial physics differs from the current calibration state."
        )
    values = payload.get("values_eur_per_t", {})
    expected = {
        "coke_inventory_t",
        "cold_slab_inventory_t",
        "hot_iron_inventory_t",
        "sinter_inventory_t",
    }
    if set(values) != expected or any(
        not math.isfinite(float(value_)) or float(value_) < 0.0
        for value_ in values.values()
    ):
        raise HourlyTemporalValidationError("C0 calibration seed values are invalid.")
    payload["state"]["temporal_contract_version"] = current_state.temporal_contract_version
    payload["reuse_provenance"] = {
        "source_run_id": seed_run_id,
        "reuse_contract": "identical_initial_physics_except_annual_contract_label",
        "current_temporal_contract_version": current_state.temporal_contract_version,
    }
    _write_json(destination, payload)
    return True


def _apply_shifted_physical_tail_warm_start(
    previous_model: Any,
    model: Any,
    *,
    execution_hours: int,
) -> dict[str, Any]:
    """Shift the previous price-blind physical witness into the next replan."""

    assigned = 0
    for component in model.component_objects(Var, active=True, descend_into=True):
        previous_component = previous_model.find_component(component.name)
        if previous_component is None:
            continue
        subsets = list(component.index_set().subsets())
        for index, variable in component.items():
            if index is None:
                previous_index = None
            else:
                parts = list(index if isinstance(index, tuple) else (index,))
                if len(parts) != len(subsets):
                    continue
                for position, subset in enumerate(subsets):
                    subset_name = str(subset.name).upper()
                    if subset_name.endswith("EAF_SUBTIME"):
                        parts[position] = int(parts[position]) + 4 * execution_hours
                    elif subset_name.endswith("TIME"):
                        parts[position] = int(parts[position]) + execution_hours
                    elif "COMMITMENT_DAY" in subset_name:
                        parts[position] = int(parts[position]) + 1
                previous_index = tuple(parts) if isinstance(index, tuple) else parts[0]
            try:
                previous_variable = previous_component[previous_index]
            except (KeyError, TypeError):
                continue
            if previous_variable.value is None:
                continue
            variable.set_value(float(value(previous_variable)), skip_validation=True)
            assigned += 1
    # A shifted tail is deliberately partial: the newly appended physical-tail
    # intervals have no counterpart in the previous model.  Audit only
    # constraints whose variables all received a value.  The complete
    # incumbent audit after solving remains strict and uses
    # ``_maximum_incumbent_violation``.
    violation = 0.0
    violation_component = ""
    skipped_constraints = 0
    evaluated_constraints = 0
    for constraint in model.component_data_objects(Constraint, active=True):
        if any(variable.value is None for variable in identify_variables(constraint.body)):
            skipped_constraints += 1
            continue
        body = float(value(constraint.body))
        observed = 0.0
        if constraint.has_lb():
            observed = max(observed, float(value(constraint.lower)) - body)
        if constraint.has_ub():
            observed = max(observed, body - float(value(constraint.upper)))
        evaluated_constraints += 1
        if observed > violation:
            violation = observed
            violation_component = constraint.name
    return {
        "assigned_variable_count": assigned,
        "maximum_constraint_violation": float(violation),
        "maximum_violation_component": str(violation_component),
        "evaluated_constraint_count": evaluated_constraints,
        "skipped_uninitialized_constraint_count": skipped_constraints,
    }


def _progress_payload(
    *,
    run_id: str,
    completed_day_solves: int,
    total_day_solves: int,
    case_id: str,
    day_index: int,
    started: float,
    status: str,
    session_start_completed: int = 0,
) -> dict[str, Any]:
    elapsed = max(0.0, time.perf_counter() - started)
    session_completed = max(0, completed_day_solves - int(session_start_completed))
    rate = elapsed / session_completed if session_completed else math.nan
    remaining = max(0, total_day_solves - completed_day_solves)
    eta_seconds = rate * remaining if math.isfinite(rate) else math.nan
    return {
        "run_id": run_id,
        "status": status,
        "current_case": case_id,
        "current_calendar_day_index": int(day_index),
        "completed_day_solves": int(completed_day_solves),
        "completed_day_solves_this_session": int(session_completed),
        "total_day_solves": int(total_day_solves),
        "progress_fraction": completed_day_solves / total_day_solves,
        "elapsed_seconds": elapsed,
        "mean_seconds_per_day_solve": rate,
        "eta_seconds": eta_seconds,
        "estimated_completion_utc": (
            datetime.fromtimestamp(time.time() + eta_seconds, tz=timezone.utc).isoformat()
            if math.isfinite(eta_seconds)
            else None
        ),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "full_four_week_matrix_authorized": False,
    }


def _print_progress(payload: Mapping[str, Any]) -> None:
    eta = payload.get("eta_seconds")
    eta_text = "unknown" if eta is None or not math.isfinite(float(eta)) else f"{float(eta) / 60.0:.1f} min"
    print(
        "[hourly-year] "
        f"{payload['completed_day_solves']}/{payload['total_day_solves']} "
        f"({100.0 * float(payload['progress_fraction']):.1f}%) | "
        f"{payload['current_case']} day {payload['current_calendar_day_index']} | "
        f"ETA {eta_text}",
        flush=True,
    )


def _annual_physical_horizon_hours(
    *,
    configuration: str,
    execution_hours: int,
    remaining_calendar_hours: int,
    final_day: bool,
) -> int:
    """Return the execution day plus exactly 48 future physical hours."""

    if final_day:
        return int(execution_hours)
    if int(remaining_calendar_hours) <= YEAR_END_FULL_HORIZON_HOURS:
        return int(remaining_calendar_hours)
    return min(int(execution_hours) + 48, int(remaining_calendar_hours))


def _physical_tail_heat_days(
    calendar_days: Sequence[Mapping[str, Any]],
    heat_schedule: Sequence[Mapping[str, Any]],
    *,
    zero_index: int,
    execution_hours: int,
    physical_horizon_hours: int,
    current_quota_period_index: int,
    remaining_quota_taps: int,
) -> list[dict[str, Any]]:
    """Map complete future calendar days into the price-blind physical tail."""

    rows: list[dict[str, Any]] = []
    cursor = int(execution_hours)
    quota_start_hours: dict[int, int] = {int(current_quota_period_index): 0}
    for future_index in range(int(zero_index) + 1, len(calendar_days)):
        day_hours = int(calendar_days[future_index]["day_length_hours"])
        end = cursor + day_hours
        if end > int(physical_horizon_hours):
            break
        scheduled = heat_schedule[future_index]
        same_quota = (
            int(scheduled["quota_period_index"]) == int(current_quota_period_index)
        )
        quota_period_index = int(scheduled["quota_period_index"])
        quota_start_hours.setdefault(quota_period_index, cursor)
        closes_quota = bool(scheduled["quota_period_boundary"])
        quota_remaining_taps = (
            int(remaining_quota_taps)
            if same_quota
            else int(scheduled["quota_period_target"])
        )
        rows.append(
            {
                "calendar_day_index": future_index + 1,
                "start_hour": cursor,
                "end_hour": end,
                "lower_taps": int(scheduled["lower"]),
                "upper_taps": int(scheduled["upper"]),
                "quota_period_index": quota_period_index,
                "closes_current_quota": bool(
                    same_quota and scheduled["quota_period_boundary"]
                ),
                "closes_quota": closes_quota,
                "quota_start_hour": quota_start_hours[quota_period_index],
                "quota_remaining_taps": quota_remaining_taps,
                "remaining_quota_taps": int(remaining_quota_taps),
            }
        )
        cursor = end
    return rows


def _physical_commitment_day_lengths(
    calendar_days: Sequence[Mapping[str, Any]],
    *,
    zero_index: int,
    physical_horizon_hours: int,
) -> list[int]:
    """Partition an exact-hour horizon on local-calendar-day boundaries."""

    remaining = int(physical_horizon_hours)
    lengths: list[int] = []
    for day in calendar_days[int(zero_index) :]:
        if remaining <= 0:
            break
        segment = min(int(day["day_length_hours"]), remaining)
        lengths.append(segment)
        remaining -= segment
    if remaining != 0:
        raise HourlyTemporalValidationError(
            "Physical horizon extends beyond the governed calendar support."
        )
    return lengths


def _consolidate_checkpoints(output: Path, execution_order: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    dispatch: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    final_cases: dict[str, Any] = {}
    for case_id in execution_order:
        paths = _checkpoint_paths(output, case_id)
        if not paths:
            continue
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            dispatch.extend(payload["dispatch"])
            costs.extend(payload["cost_rows"])
            attempts.append(payload["solver_attempt"])
            audits.extend(payload["physical_audit"])
        final_cases[case_id] = json.loads(paths[-1].read_text(encoding="utf-8"))
    return (
        pd.DataFrame(dispatch),
        pd.DataFrame(costs),
        pd.DataFrame(attempts),
        pd.DataFrame(audits),
        final_cases,
    )


def _economic_rows(
    dispatch: pd.DataFrame,
    costs: pd.DataFrame,
    final_cases: Mapping[str, Any],
    *,
    c0_config: Mapping[str, Any],
    period_label: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, final in final_cases.items():
        configuration, strategy = case_id.split("__", maxsplit=1)
        case_dispatch = dispatch[
            (dispatch["configuration"] == configuration)
            & (dispatch["strategy"] == strategy)
        ]
        case_costs = costs[
            (costs["configuration"] == configuration)
            & (costs["strategy"] == strategy)
        ]
        physical_steel = float(final["state_after"]["cumulative_production_t"])
        reporting_factor = (
            float(c0_config["c0_material_contract"]["reporting_normalization_factor"])
            if configuration == "C0"
            else 1.0
        )
        reported_steel = physical_steel * reporting_factor
        realised_cost = float(case_costs["cost_eur"].sum())
        electricity = case_costs[case_costs["price_id"] == "grid_electricity_flat_nl"]
        grid_mwh = float(electricity["quantity"].sum())
        electricity_cost = float(electricity["cost_eur"].sum())

        def cost_for(price_ids: set[str]) -> float:
            return float(case_costs[case_costs["price_id"].isin(price_ids)]["cost_eur"].sum())

        rows.append(
            {
                "configuration": configuration,
                "granularity": "H",
                "strategy": strategy,
                "strategy_label": "Price insensitive" if strategy == "price_insensitive" else "Perfect foresight",
                "period": period_label,
                "represented_hours": int(case_dispatch.shape[0]),
                "market_scope": "deterministic_no_bidding_no_mfrr",
                "realised_procurement_cost_eur": realised_cost,
                "optimisation_procurement_cost_eur": float(
                    final["cumulative_optimisation_procurement_cost_eur"]
                ),
                "physical_steel_produced_t": physical_steel,
                "steel_produced_t": reported_steel,
                "cost_eur_per_t": realised_cost / reported_steel,
                "site_electricity_consumed_mwh": float(case_dispatch["site_electricity_mwh"].sum()),
                "grid_electricity_purchased_mwh": grid_mwh,
                "average_electricity_price_paid_eur_per_mwh": electricity_cost / grid_mwh if grid_mwh > 0.0 else math.nan,
                "total_electricity_cost_eur": electricity_cost,
                "total_ng_cost_eur": cost_for({"natural_gas_ttf_proxy"}),
                "total_coal_cost_eur": cost_for({"coking_coal_hcc_proxy", "pci_coal_proxy"}),
                "total_imported_pellets_cost_eur": cost_for({"imported_bf_pellets_proxy", "imported_dr_pellets_proxy"}),
                "direct_emissions_tco2": float(case_dispatch["direct_co2_t"].sum()),
                "mfrr_revenue_eur": "",
                "mfrr_revenue_status": "not_applicable_no_mfrr_layer",
                "full_four_week_matrix_authorized": False,
            }
        )
    return rows


def _production_comparability_rows(
    economics_frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Gate C0/C1 reported steel on the common 6.75-Mt denominator."""

    rows: list[dict[str, Any]] = []
    for strategy in ("price_insensitive", "perfect_foresight_D"):
        c0_steel = float(
            economics_frame[
                (economics_frame["configuration"] == "C0")
                & (economics_frame["strategy"] == strategy)
            ].iloc[0]["steel_produced_t"]
        )
        c1_steel = float(
            economics_frame[
                (economics_frame["configuration"] == "C1")
                & (economics_frame["strategy"] == strategy)
            ].iloc[0]["steel_produced_t"]
        )
        difference_t = abs(c1_steel - c0_steel)
        c0_target_delta_t = abs(
            c0_steel - ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T
        )
        c1_target_delta_t = abs(
            c1_steel - ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T
        )
        rows.append(
            {
                "strategy": strategy,
                "c0_reported_steel_t": c0_steel,
                "c1_reported_steel_t": c1_steel,
                "absolute_difference_t": difference_t,
                "common_target_t": ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T,
                "c0_absolute_target_delta_t": c0_target_delta_t,
                "c1_absolute_target_delta_t": c1_target_delta_t,
                "tolerance_t": C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T,
                "passed": bool(
                    difference_t
                    <= C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T + 0.001
                    and c0_target_delta_t
                    <= C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T + 0.001
                    and c1_target_delta_t
                    <= C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T + 0.001
                ),
                "denominator_policy": (
                    "common_6_75_mt_reported_product_with_6_746_6_754_hard_band"
                ),
            }
        )
    return rows


def _annual_anchor_rows(
    dispatch: pd.DataFrame,
    costs: pd.DataFrame,
    final_cases: Mapping[str, Any],
    economics: Sequence[Mapping[str, Any]],
    *,
    c0_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Apply the existing Phase-5E-style anchor evaluator to the full year.

    The full-year checkpoint format is intentionally compact. Quantities not
    retained in it (notably WAG production and generator-fuel input by carrier)
    remain explicitly not comparable instead of being reconstructed as plugs.
    """

    aggregate_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    for case_id, final in final_cases.items():
        configuration, strategy = case_id.split("__", maxsplit=1)
        data = dispatch[
            (dispatch["configuration"] == configuration)
            & (dispatch["strategy"] == strategy)
        ]
        case_costs = costs[
            (costs["configuration"] == configuration)
            & (costs["strategy"] == strategy)
        ]
        state = final["state_after"]
        route = state["cumulative_route_progress_t"]

        def route_value(name: str) -> float:
            return float(route.get(name, 0.0))

        def flow_quantity(flow_id: str) -> float:
            return float(case_costs.loc[case_costs["flow_id"] == flow_id, "quantity"].sum())

        reporting_factor = (
            float(c0_config["c0_material_contract"]["reporting_normalization_factor"])
            if configuration == "C0"
            else 1.0
        )
        external_bof = float(state["cumulative_external_scrap_to_bof_t"])
        internal_bof = float(state["cumulative_internal_scrap_to_bof_t"])
        external_eaf = float(state["cumulative_external_scrap_to_eaf_t"])
        internal_eaf = float(state["cumulative_internal_scrap_to_eaf_t"])
        if configuration == "C0":
            bof = route_value("C0_BOF_crude_steel_output_t")
            hsm = route_value("C0_HSM_final_product_t") * reporting_factor
            dsp = route_value("C0_DSP_final_product_t") * reporting_factor
            eaf = 0.0
            imported_bf = flow_quantity("C0_MAT_IMPORTED_BF_PELLETS")
            imported_dr = 0.0
        else:
            bof = route_value("C1_BOF_liquid_steel_output_t_h")
            hsm = route_value("C1_HSM_final_product_output_t")
            dsp = route_value("C1_DSP_final_product_output_t")
            eaf = route_value("C1_EAF_liquid_steel_output_t_h")
            imported_bf = 0.0
            imported_dr = flow_quantity("C1_MAT_DRP_PELLETS")
        aggregate_rows.append(
            {
                "configuration": configuration,
                "strategy_id": strategy,
                "final_product_t": float(state["cumulative_production_t"]) * reporting_factor,
                "net_grid_import_mwh": float(data["grid_import_mwh"].sum()),
                "internal_generation_mwh": float(data["generation_mwh"].sum()),
                "external_scrap_to_bof_t": external_bof,
                "internal_scrap_to_bof_t": internal_bof,
                "external_scrap_to_eaf_t": external_eaf,
                "internal_scrap_to_eaf_t": internal_eaf,
                "total_flare_mwh_lhv": 0.0,
                "sinter_output_t": float(data["sifa_t_h"].sum())
                * SIFA_SINTER_T_PER_T_REPRESENTED_ORE,
                "pefa_output_t": float(data["pefa_t_h"].sum()),
                "external_bf_pellets_to_bf_t": imported_bf,
                "external_dr_pellets_to_drp_t": imported_dr,
                "coke_output_t": float(
                    data["kgf1_t_h"].sum() + data["kgf2_t_h"].fillna(0.0).sum()
                )
                / DRY_COAL_T_PER_T_COKE,
                "hot_metal_output_t": float(
                    data["bf6_t_h"].sum() + data["bf7_t_h"].fillna(0.0).sum()
                )
                * BF_HOT_METAL_T_PER_T_REPRESENTED_ACTIVITY,
                "bof_liquid_steel_t": bof,
                "drp_dri_output_t": float(data["drp_dri_output_t"].fillna(0.0).sum()),
                "eaf_liquid_steel_t": eaf,
                "hsm_final_output_t": hsm,
                "dsp_final_output_t": dsp,
                "total_named_ng_procurement_mwh": float(data["named_ng_mwh"].sum()),
                "direct_co2_reporting_t": float(data["direct_co2_t"].sum()),
                "bfg_generated_mwh": 0.0,
                "cog_generated_mwh": 0.0,
                "bofg_generated_mwh": 0.0,
                "generator_total_fuel_mwh": 0.0,
            }
        )
        economic = next(
            row
            for row in economics
            if row["configuration"] == configuration and row["strategy"] == strategy
        )
        result_rows.append(
            {
                "configuration": configuration,
                "strategy_id": strategy,
                "objective_eur": float(economic["realised_procurement_cost_eur"]),
            }
        )

    rows = _annualised_rows(
        pd.DataFrame(aggregate_rows),
        result_rows,
        c0_config,
        represented_hours=8760,
    )
    unavailable_metrics = {
        "flare",
        "c0_wag_total",
        "c1_wag_total",
        "c0_generator_fuel_total",
        "c1_generator_fuel_total",
    }
    for row in rows:
        row["period_classification"] = "full_calendar_year_observed"
        row["represented_hours"] = 8760
        if "denominator" in row:
            row["denominator"] = "8760_hour_causal_calendar_year"
        if "boundary_denominator" in row and row.get("metric") == "final_product":
            row["boundary_denominator"] = "6.75_Mt_common_reporting_denominator"
        if row.get("metric") in unavailable_metrics:
            row["model_annual_equivalent"] = ""
            row["absolute_deviation"] = ""
            row["relative_deviation"] = ""
            row["comparability"] = "not_comparable"
            row["model_coverage"] = "not_retained_in_compact_annual_checkpoint"
            row["caveat"] = "No residual or reporting plug was introduced."

    coal_anchor = {"C0": (120.8, 4_400_000.0), "C1": (58.0, 2_200_000.0)}
    for case_id in final_cases:
        configuration, strategy = case_id.split("__", maxsplit=1)
        case_costs = costs[
            (costs["configuration"] == configuration)
            & (costs["strategy"] == strategy)
        ]
        coal_t = float(
            case_costs.loc[
                case_costs["price_id"].isin(
                    {"coking_coal_hcc_proxy", "pci_coal_proxy"}
                ),
                "quantity",
            ].sum()
        )
        source_pj, source_mass_t = coal_anchor[configuration]
        model_pj = coal_t * source_pj / source_mass_t
        metric = f"{configuration.lower()}_coal_energy"
        coal_row = next(
            row
            for row in rows
            if row.get("configuration") == configuration
            and row.get("strategy_id") == strategy
            and row.get("metric") == metric
        )
        coal_row.update(
            {
                "model_annual_equivalent": model_pj,
                "absolute_deviation": model_pj - source_pj,
                "relative_deviation": (model_pj - source_pj) / source_pj,
                "model_coverage": "represented_purchased_coal_mass",
                "boundary_denominator": "MER_joint_energy_per_reported_coal_mass",
                "comparability": "partially_comparable",
                "caveat": "Administrative mass-to-energy comparison; not a carrier LHV balance.",
            }
        )
    return rows


def _hourly_eaf_load_decomposition(
    dispatch: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Expose the EAF electricity components available in an hourly run.

    Annual checkpoints intentionally retain hourly settlement aggregates, not
    the internal 15-minute binary solution. This adapter therefore reports an
    honest hourly decomposition and never fabricates sub-hourly phases.
    """

    c1 = dispatch[dispatch["configuration"] == "C1"].copy()
    rows: list[dict[str, Any]] = []
    for row in c1.to_dict(orient="records"):
        taps = float(row["eaf_taps"])
        cold = float(row["eaf_cold_dri_reheat_electricity_mwh"])
        total = float(row["eaf_electricity_mwh"])
        secondary = (
            taps
            * EAF_HEAT_SIZE_T
            * EAF_SECONDARY_ELECTRICITY_MWH_PER_T_LIQUID_STEEL
        )
        arc = total - cold - secondary
        if arc < -1e-6:
            raise HourlyTemporalValidationError(
                "Hourly EAF component decomposition exceeds the reported total."
            )
        rows.append(
            {
                "configuration": "C1",
                "strategy": row["strategy"],
                "day": int(row["day"]),
                "hour": int(row["hour"]),
                "subslot": "",
                "timestamp_utc": row["timestamp_utc"],
                "price_eur_per_mwh": float(row["price_eur_per_mwh"]),
                "phase": "hourly_aggregate",
                "temporal_resolution": "H_settlement_aggregate",
                "arc_power_mw": max(0.0, arc),
                "cold_dri_reheat_power_mw": cold,
                "secondary_metallurgy_power_mw": secondary,
                "total_eaf_related_power_mw": total,
            }
        )
    return rows


def _build_example_week_figure_package(
    output: Path,
    *,
    dispatch: pd.DataFrame,
    costs: pd.DataFrame,
    c0_config: Mapping[str, Any],
    c1_config: Mapping[str, Any],
    week_start_local_date: str,
) -> dict[str, Any]:
    from .s4_4c6_deterministic_figure_package import generate_deterministic_figure_package

    start_local = pd.Timestamp(week_start_local_date, tz="Europe/Amsterdam")
    end_local = start_local + pd.Timedelta(days=7)
    timestamps = pd.to_datetime(dispatch["timestamp_utc"], utc=True).dt.tz_convert("Europe/Amsterdam")
    selected = dispatch[(timestamps >= start_local) & (timestamps < end_local)].copy()
    if selected.shape[0] == 4 * 168 * 4:
        selected["timestamp_utc"] = pd.to_datetime(
            selected["timestamp_utc"], utc=True
        ).dt.floor("h")
        keys = ["configuration", "strategy", "day", "timestamp_utc"]
        aggregations: dict[str, str] = {}
        for column in selected.columns:
            if column in keys or column == "hour":
                continue
            if column.endswith("_mwh") or column in {
                "eaf_starts",
                "eaf_taps",
                "final_product_t",
                "direct_co2_t",
                "bfg_combustion_co2_t",
                "bofg_combustion_co2_t",
                "cog_combustion_co2_t",
                "named_ng_combustion_co2_t",
                "unmodelled_direct_co2_t",
                "drp_dri_output_t",
                "eaf_dri_input_t",
                "hdri_direct_to_eaf_t",
                "hdri_to_cdri_storage_t",
                "cdri_from_storage_to_eaf_t",
            }:
                aggregations[column] = "sum"
            elif "inventory" in column or "capacity" in column:
                aggregations[column] = "last"
            else:
                aggregations[column] = "mean"
        selected = selected.groupby(keys, as_index=False, sort=False).agg(aggregations)
        selected["hour"] = selected.groupby(
            ["configuration", "strategy", "day"], sort=False
        ).cumcount()
    if selected.shape[0] != 4 * 168:
        raise HourlyTemporalValidationError(
            "The configured figure week must contain 168 hours for all four cases."
        )
    selected_days = set(int(day) for day in selected["day"].unique())
    selected_costs = costs[costs["day"].astype(int).isin(selected_days)].copy()
    # The standard figure package consumes an hourly comparison table.  QH
    # source ledgers retain identical weekly totals after aggregation, but the
    # reporting key must match that hourly view.
    selected_costs["granularity"] = "H"
    figure_root = output / "standard_figure_package"
    figure_root.mkdir(parents=True, exist_ok=True)
    selected.to_csv(figure_root / "hourly_dispatch.csv", index=False)
    selected_costs.to_csv(figure_root / "represented_cost_ledger.csv", index=False)
    _write_csv(
        figure_root / "eaf_subhourly_load.csv",
        _hourly_eaf_load_decomposition(selected),
    )
    week_final: dict[str, Any] = {}
    for (configuration, strategy), group in selected.groupby(["configuration", "strategy"]):
        week_costs = selected_costs[
            (selected_costs["configuration"] == configuration)
            & (selected_costs["strategy"] == strategy)
        ]
        physical_steel = float(group["final_product_t"].sum())
        reporting_factor = (
            float(c0_config["c0_material_contract"]["reporting_normalization_factor"])
            if configuration == "C0"
            else 1.0
        )
        week_final[f"{configuration}__{strategy}"] = {
            "state_after": {"cumulative_production_t": physical_steel},
            "cumulative_optimisation_procurement_cost_eur": float(week_costs["cost_eur"].sum()),
            "reporting_factor": reporting_factor,
        }
    week_economics = _economic_rows(
        selected,
        selected_costs,
        week_final,
        c0_config=c0_config,
        period_label=f"example_week_{week_start_local_date}",
    )
    pd.DataFrame(week_economics).to_csv(figure_root / "weekly_economics.csv", index=False)
    _write_csv(
        figure_root / "resolved_plant_capacity_contract.csv",
        _normalized_capacity_rows(c0_config, c1_config),
    )
    _write_json(
        figure_root / "run_manifest.json",
        {
            "run_mode": "full_year_selected_example_week_figure_source",
            "period": f"{week_start_local_date}/7d",
            "granularity": "H",
            "full_four_week_matrix_authorized": False,
        },
    )
    return generate_deterministic_figure_package(
        figure_root, regime="high_volatility"
    )


def run_hourly_full_year(
    *,
    run_id: str,
    resume: bool = False,
    dry_run: bool = False,
    feasibility_shakedown: bool = False,
    stop_after_total_day_solves: int | None = None,
    stop_after_day_per_case: int | None = None,
    config_path: Path = CONFIG_PATH,
    selected_configurations: Sequence[str] | None = None,
    granularity: str = "H",
) -> dict[str, Any]:
    """Run C0/C1 annual trajectories through the shared H/QH annual engine."""

    is_qh = str(granularity).upper() == "QH"
    if is_qh:
        config, price_ledger = load_qh_annual_calendar_and_prices(config_path)
        calendar = price_ledger.copy()
        output = QH_OUTPUT_ROOT / run_id
        if output.exists() and not resume:
            raise HourlyTemporalValidationError(
                f"QH annual run folder already exists: {output}"
            )
        (output / "checkpoints").mkdir(parents=True, exist_ok=True)
        (output / "solver_logs").mkdir(parents=True, exist_ok=True)
        calendar.to_parquet(output / "annual_qh_calendar.parquet", index=False)
        price_ledger.to_parquet(output / "annual_qh_price_ledger.parquet", index=False)
    elif str(granularity).upper() == "H":
        config, calendar, price_ledger, output = prepare_lear_strict_hourly_year_inputs(
            run_id=run_id,
            config_path=config_path,
            allow_existing=resume,
        )
    else:
        raise HourlyTemporalValidationError("Annual granularity must be H or QH.")
    reporting = dict(config["reporting"])
    if feasibility_shakedown:
        reporting.update(
            {
                "output_policy": "minimal",
                "lineage_role": (
                    "diagnostic_shared_annual_recoverability_feasibility_smoke"
                ),
                "expected_artifact_count_upper_bound": 80,
                "estimated_output_size_mb_upper_bound": 10,
            }
        )
    execution_order = (
        ["C0__flat_price_shakedown", "C1__flat_price_shakedown"]
        if feasibility_shakedown
        else [str(item) for item in config["execution_order"]]
    )
    if selected_configurations is not None:
        selected = {str(item).upper() for item in selected_configurations}
        if not selected or not selected.issubset({"C0", "C1"}):
            raise HourlyTemporalValidationError(
                "Selected annual configurations must be C0 and/or C1."
            )
        execution_order = [
            case_id
            for case_id in execution_order
            if case_id.split("__", maxsplit=1)[0].upper() in selected
        ]
        if not execution_order:
            raise HourlyTemporalValidationError(
                "No annual execution cases remain after configuration filtering."
            )
    expected_days = int(config["period"]["expected_days"])
    if stop_after_day_per_case is not None and not 1 <= int(stop_after_day_per_case) <= expected_days:
        raise HourlyTemporalValidationError(
            "stop_after_day_per_case must lie inside the governed annual calendar."
        )
    planned_days_per_case = (
        min(expected_days, int(stop_after_day_per_case))
        if stop_after_day_per_case is not None
        else expected_days
    )
    total_day_solves = len(execution_order) * planned_days_per_case
    if feasibility_shakedown:
        # Each accepted day writes an atomic checkpoint and compact progress /
        # solver evidence.  Scale the pre-solve declaration with the requested
        # prefix instead of advertising the old fixed one-week estimate.
        reporting["expected_artifact_count_upper_bound"] = (
            20 + 3 * total_day_solves
        )
        reporting["estimated_output_size_mb_upper_bound"] = max(
            10, int(math.ceil(0.15 * total_day_solves))
        )
    selected_configuration_ids = sorted(
        {case_id.split("__", maxsplit=1)[0] for case_id in execution_order}
    )
    manifest = {
        "run_id": run_id,
        "run_family_id": config["run_family_id"],
        "period_start_local_date": config["period"]["start_local_date"],
        "period_end_exclusive_local_date": config["period"]["end_exclusive_local_date"],
        "calendar_hours": int(config["period"]["expected_hours"]),
        "calendar_intervals": int(len(calendar)),
        "calendar_days": int(calendar["calendar_day_index"].nunique()),
        "configurations": selected_configuration_ids,
        "strategies": (
            ["flat_price_shakedown"]
            if feasibility_shakedown
            else list(config["strategies"])
        ),
        "granularity": "QH" if is_qh else "H",
        "execution_mode": (
            "flat_price_causal_feasibility_shakedown"
            if feasibility_shakedown
            else "price_insensitive_and_perfect_foresight"
        ),
        "temporal_contract_versions": {
            "C0": (
                C0_ANNUAL_QH_CONTRACT_VERSION
                if is_qh else C0_ANNUAL_HOURLY_CONTRACT_VERSION
            ),
            "C1": (
                C1_ANNUAL_QH_CONTRACT_VERSION
                if is_qh else C1_ANNUAL_HOURLY_CONTRACT_VERSION
            ),
        },
        "planned_day_solves": total_day_solves,
        "planned_days_per_case": planned_days_per_case,
        "planned_calibration_solves_upper_bound": 12,
        "planned_model_build_count_upper_bound": total_day_solves + 12,
        "planned_solve_attempt_count_upper_bound": 2 * total_day_solves + 12,
        "expected_artifact_count_upper_bound": reporting["expected_artifact_count_upper_bound"],
        "estimated_output_size_mb_upper_bound": reporting["estimated_output_size_mb_upper_bound"],
        "output_policy": reporting["output_policy"],
        "run_class": reporting["run_class"],
        "lineage_role": reporting["lineage_role"],
        "retention_status": reporting["retention_status"],
        "git_eligible": reporting["git_eligible"],
        "full_four_week_matrix_authorized": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output / "run_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=True), encoding="utf-8"
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    _write_json(output / "code_version.json", {"git_head": head, "dirty_worktree": True})
    input_manifest = {
        "config": str(config_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "config_sha256": _sha256_file(config_path),
    }
    if is_qh:
        bundle_path = REPO_ROOT / str(config["qh_price_bundle"]["path"])
        input_manifest.update(
            {
                "qh_price_bundle_sha256": _sha256_file(bundle_path),
                "qh_price_contract_version": config["price_contract_version"],
            }
        )
    else:
        input_manifest.update(
            {
                "realised_price_source_sha256": _sha256_file(
                    REPO_ROOT / str(config["realised_price_source"]["path"])
                ),
                "realised_price_ledger_sha256": _sha256_file(
                    output / "annual_realised_price_ledger.csv"
                ),
            }
        )
    _write_json(output / "input_manifest.json", input_manifest)
    print(
        json.dumps(
            {
                "before_first_solve": True,
                "output_root": str(output),
                "planned_day_solves": total_day_solves,
                "planned_solve_attempts_upper_bound": manifest["planned_solve_attempt_count_upper_bound"],
                "estimated_output_size_mb_upper_bound": manifest["estimated_output_size_mb_upper_bound"],
                "dry_run": bool(dry_run),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if dry_run:
        summary = {
            **manifest,
            "decision": (
                "qh_full_year_inputs_ready_no_solve_started"
                if is_qh else "hourly_full_year_inputs_ready_no_solve_started"
            ),
            "full_year_solve_started": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(output / "gate_decision.json", summary)
        return summary

    c0_config = load_c0_validation_config()
    c1_config = load_temporal_repair_config(REPO_ROOT / c0_config["base_temporal_config"])
    c0_annual_contract = (
        C0_ANNUAL_QH_CONTRACT_VERSION
        if is_qh else C0_ANNUAL_HOURLY_CONTRACT_VERSION
    )
    c1_annual_contract = (
        C1_ANNUAL_QH_CONTRACT_VERSION
        if is_qh else C1_ANNUAL_HOURLY_CONTRACT_VERSION
    )
    behaviour = load_validation_config(REPO_ROOT / c0_config["behaviour_validation_config"])
    _activate_c1_calibration_bundle(c1_config, behaviour)
    contexts = {
        C0_CONFIGURATION: {
            hours: (
                _qh_context(
                    c1_config, C0_ANNUAL_QH_CONTRACT_VERSION,
                    execution_hours=hours, physical_horizon_hours=hours + 48,
                )
                if is_qh else _hourly_context(
                    c1_config, C0_ANNUAL_HOURLY_CONTRACT_VERSION,
                    execution_hours=hours,
                )
            )
            for hours in (23, 24, 25)
        },
        C1_CONFIGURATION: {
            hours: (
                _qh_context(
                    c1_config, C1_ANNUAL_QH_CONTRACT_VERSION,
                    execution_hours=hours, physical_horizon_hours=hours + 48,
                )
                if is_qh else _hourly_context(
                    c1_config, C1_ANNUAL_HOURLY_CONTRACT_VERSION,
                    execution_hours=hours,
                )
            )
            for hours in (23, 24, 25)
        },
    }
    calendar_days = []
    for _, group in calendar.groupby("calendar_day_index", sort=True):
        calendar_days.append(
            {
                "date": pd.Timestamp(group["local_date"].iloc[0]).date(),
                "day_length_hours": int(group["local_day_length_hours"].iloc[0]),
                "execution_steps": int(group.shape[0]) if is_qh else int(group.shape[0]) * 4,
                "start_utc": pd.Timestamp(group["timestamp_utc"].iloc[0]),
            }
        )
    annual_target_taps = cumulative_eaf_target_taps(int(HOURS_PER_YEAR))
    heat_schedule = _annual_heat_schedule(
        calendar_days,
        annual_target_taps=annual_target_taps,
        daily_tolerance=int(
            c1_config["deterministic_temporal_repair"]["causal_flat_year"]["heat_target_daily_tolerance"]
        ),
        quota_period_days=7,
        quota_neutral_upper_cap=int(
            c1_config["deterministic_temporal_repair"]["causal_flat_year"]["routine_quota_normal_day_upper_taps"]
        ),
    )
    annual_inventory_targets = {
        configuration: _annual_initial_inventory_targets(
            c0_config, c1_config, configuration=configuration
        )
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION)
    }
    c0_reconciliation = c0_annual_operational_reconciliation(c0_config)
    _write_json(output / "annual_operational_reconciliation.json", c0_reconciliation)
    if not bool(c0_reconciliation["passed"]):
        raise HourlyTemporalValidationError(
            "C0 annual aggregate material reconciliation is infeasible."
        )
    calibration_attempts: list[dict[str, Any]] = []
    heat_calibration_path = output / (
        "qh_continuation_calibration.json" if is_qh else "hourly_continuation_calibration.json"
    )
    if heat_calibration_path.exists():
        kappa = float(json.loads(heat_calibration_path.read_text(encoding="utf-8"))["kappa_eur_per_heat"])
    else:
        calibration_state = _initial_state(
            C1_CONFIGURATION,
            c0_config=c0_config,
            c1_config=c1_config,
            first_quota_target=int(heat_schedule[0]["quota_period_target"]),
            strategy="calibration",
            temporal_contract_version=c1_annual_contract,
            time_step_hours=0.25 if is_qh else 1.0,
        )
        kappa = _calibrate_continuation(
            contexts[C1_CONFIGURATION][24],
            calibration_state,
            c0_config,
            c1_config,
            output,
            calibration_attempts,
            artifact_name=heat_calibration_path.name,
        )
    c0_selected = any(case_id.startswith("C0__") for case_id in execution_order)
    c0_inventory_values: dict[str, float] = {}
    if c0_selected:
        c0_calibration_path = output / (
            "qh_c0_inventory_continuation_calibration.json"
            if is_qh else "c0_inventory_continuation_calibration.json"
        )
        c0_calibration_state = _initial_state(
            C0_CONFIGURATION,
            c0_config=c0_config,
            c1_config=c1_config,
            first_quota_target=int(heat_schedule[0]["quota_period_target"]),
            strategy="calibration",
            temporal_contract_version=c0_annual_contract,
            time_step_hours=0.25 if is_qh else 1.0,
        )
        if not c0_calibration_path.exists():
            seed_run_id = str(
                config.get("calibration", {}).get("c0_inventory_seed_run_id", "")
            )
            if seed_run_id and not is_qh:
                _materialize_compatible_c0_calibration_seed(
                    c0_calibration_path,
                    seed_run_id=seed_run_id,
                    current_state=c0_calibration_state,
                )
        if c0_calibration_path.exists():
            c0_inventory_values = {
                str(key): float(item)
                for key, item in json.loads(c0_calibration_path.read_text(encoding="utf-8"))["values_eur_per_t"].items()
            }
        else:
            c0_inventory_values = _calibrate_c0_inventory_continuation(
                contexts[C0_CONFIGURATION][24],
                c0_calibration_state,
                c0_config,
                c1_config,
                output,
                calibration_attempts,
                artifact_name=c0_calibration_path.name,
            )
    _write_csv(output / "calibration_solver_attempts.csv", calibration_attempts)

    started = time.perf_counter()
    completed_day_solves = sum(len(_checkpoint_paths(output, case_id)) for case_id in execution_order)
    session_start_completed = completed_day_solves
    stopped_early = False
    for case_id in execution_order:
        configuration_label, strategy = case_id.split("__", maxsplit=1)
        configuration = C0_CONFIGURATION if configuration_label == "C0" else C1_CONFIGURATION
        contract_version = (
            (C0_ANNUAL_QH_CONTRACT_VERSION if is_qh else C0_ANNUAL_HOURLY_CONTRACT_VERSION)
            if configuration == C0_CONFIGURATION
            else (C1_ANNUAL_QH_CONTRACT_VERSION if is_qh else C1_ANNUAL_HOURLY_CONTRACT_VERSION)
        )
        completed_days, resumed_state, realised_cost, optimisation_cost = _load_completed_case(
            output, case_id, contract_version=contract_version
        )
        state = resumed_state or _initial_state(
            configuration,
            c0_config=c0_config,
            c1_config=c1_config,
            first_quota_target=int(heat_schedule[0]["quota_period_target"]),
            strategy=strategy,
            temporal_contract_version=contract_version,
            time_step_hours=0.25 if is_qh else 1.0,
        )
        previous_physical_model = None
        for zero_index in range(completed_days, len(calendar_days)):
            if (
                stop_after_day_per_case is not None
                and zero_index >= int(stop_after_day_per_case)
            ):
                break
            if stop_after_total_day_solves is not None and completed_day_solves >= int(stop_after_total_day_solves):
                stopped_early = True
                break
            day_number = zero_index + 1
            day_calendar = calendar[calendar["calendar_day_index"] == day_number].copy()
            day_prices = price_ledger[price_ledger["calendar_day_index"] == day_number].copy()
            realised = tuple(float(item) for item in day_prices["price_eur_per_mwh"])
            planning = (
                realised
                if strategy == "perfect_foresight_D"
                else (float(config["price_insensitive_eur_per_mwh"]),) * len(realised)
            )
            execution_hours = int(day_calendar["local_day_length_hours"].iloc[0])
            context = contexts[configuration][execution_hours]
            scheduled = heat_schedule[zero_index]
            if configuration == C1_CONFIGURATION:
                remaining = int(state.eaf_quota_target_taps or 0) - int(state.eaf_quota_completed_taps)
                period_index = int(scheduled["quota_period_index"])
                future = [
                    item
                    for item in heat_schedule[zero_index + 1 :]
                    if int(item["quota_period_index"]) == period_index
                ]
                lower, upper = dynamic_daily_heat_bounds(
                    remaining_taps=remaining,
                    today_lower=int(scheduled["lower"]),
                    today_upper=int(scheduled["upper"]),
                    future_lower_bounds=[int(item["lower"]) for item in future],
                    future_upper_bounds=[int(item["upper"]) for item in future],
                )
            else:
                remaining, lower, upper = 0, 0, 0
            final_day = day_number == len(calendar_days)
            remaining_calendar_hours = sum(
                int(item["day_length_hours"])
                for item in calendar_days[zero_index:]
            )
            year_endpoint_visible = (
                remaining_calendar_hours <= YEAR_END_FULL_HORIZON_HOURS
            )
            physical_horizon_hours = _annual_physical_horizon_hours(
                configuration=configuration,
                execution_hours=execution_hours,
                remaining_calendar_hours=remaining_calendar_hours,
                final_day=final_day,
            )
            recovery_index = (
                context.time_grid.hours_to_steps(physical_horizon_hours) - 1
                if year_endpoint_visible and not final_day
                else None
            )
            completed_eaf_taps = float(
                state.cumulative_route_progress_t.get(
                    "C1_EAF_liquid_steel_output_t_h", 0.0
                )
            ) / 325.0
            if configuration == C1_CONFIGURATION and not math.isclose(
                completed_eaf_taps,
                round(completed_eaf_taps),
                rel_tol=0.0,
                abs_tol=1e-7,
            ):
                raise HourlyTemporalValidationError(
                    "C1 cumulative EAF output no longer maps to whole 325-t taps."
                )
            year_terminal_remaining_taps = (
                int(annual_target_taps - round(completed_eaf_taps))
                if configuration == C1_CONFIGURATION
                and recovery_index is not None
                else None
            )
            physical_tail_heat_days = (
                _physical_tail_heat_days(
                    calendar_days,
                    heat_schedule,
                    zero_index=zero_index,
                    execution_hours=execution_hours,
                    physical_horizon_hours=physical_horizon_hours,
                    current_quota_period_index=int(scheduled["quota_period_index"]),
                    remaining_quota_taps=remaining,
                )
                if configuration == C1_CONFIGURATION and not final_day
                else None
            )
            commitment_day_lengths_hours = _physical_commitment_day_lengths(
                calendar_days,
                zero_index=zero_index,
                physical_horizon_hours=physical_horizon_hours,
            )
            annual_future_heat_calendar = (
                [
                    {
                        **dict(heat_schedule[future_index]),
                        "calendar_day_index": future_index + 1,
                        "day_length_hours": int(
                            calendar_days[future_index]["day_length_hours"]
                        ),
                    }
                    for future_index in range(zero_index + 1, len(calendar_days))
                ]
                if configuration == C1_CONFIGURATION and not final_day
                else None
            )
            model, procurement, band = _build_model(
                context,
                state,
                c0_config,
                c1_config,
                planning,
                configuration=configuration,
                lower_taps=lower,
                upper_taps=upper,
                week_boundary=bool(scheduled["quota_period_boundary"]),
                continuation_eur_per_heat=kappa,
                remaining_taps=remaining,
                year_terminal_remaining_taps=year_terminal_remaining_taps,
                day_index=((zero_index % 7) + 1),
                c0_inventory_values_eur_per_t=c0_inventory_values,
                annual_readiness=True,
                final_year_day=final_day,
                year_terminal_recovery_index=recovery_index,
                annual_initial_inventory_targets_t=annual_inventory_targets[configuration],
                physical_horizon_hours=physical_horizon_hours,
                physical_tail_heat_days=physical_tail_heat_days,
                commitment_day_lengths_hours=commitment_day_lengths_hours,
                annual_future_heat_calendar=annual_future_heat_calendar,
                annual_current_quota_period_index=(
                    int(scheduled["quota_period_index"])
                    if configuration == C1_CONFIGURATION
                    else None
                ),
            )
            if (
                configuration == C1_CONFIGURATION
                and not final_day
                and not bool(model.c1_annual_future_heat_calendar_complete)
            ):
                raise HourlyTemporalValidationError(
                    "Operational C1 annual solves require the complete price-blind "
                    "future heat calendar."
                )
            warm_start_audit = (
                _apply_shifted_physical_tail_warm_start(
                    previous_physical_model,
                    model,
                    execution_hours=int(context.time_grid.execution_steps),
                )
                if previous_physical_model is not None
                else {
                    "assigned_variable_count": 0,
                    "maximum_constraint_violation": math.nan,
                    "maximum_violation_component": "not_available_after_resume_or_first_day",
                }
            )
            if warm_start_audit["assigned_variable_count"]:
                _atomic_json(
                    output / "shifted_physical_tail_warm_start_current.json",
                    {
                        "case_id": case_id,
                        "calendar_day_index": day_number,
                        **warm_start_audit,
                    },
                )
            attempt = _solve(
                model,
                model.hourly_scalar_objective.expr,
                case_id=f"{case_id}_day_{day_number:03d}",
                output=output,
                diagnose_infeasible=True,
                warmstart=bool(warm_start_audit["assigned_variable_count"]),
            )
            optimisation_cost += float(value(procurement))
            realised_expression = _represented_cost_expression(
                context,
                model,
                configuration,
                tuple(realised) + (0.0,) * (
                    context.time_grid.hours_to_steps(physical_horizon_hours) - len(realised)
                ),
                objective_hours=range(len(realised)),
            )
            realised_cost += float(value(realised_expression))
            audit = _audit(model, band, configuration)
            if not all(bool(row["passed"]) for row in audit):
                failed = next(row for row in audit if not bool(row["passed"]))
                raise HourlyTemporalValidationError(
                    f"Annual physical audit failed for {case_id}/day {day_number}: {failed}."
                )
            dispatch_rows = _dispatch_rows(
                model,
                realised,
                configuration=configuration,
                strategy=strategy,
                day=day_number,
                week_start=pd.Timestamp(day_calendar["timestamp_utc"].iloc[0]).to_pydatetime(),
                timestamps_utc=tuple(day_calendar["timestamp_utc"]),
            )
            cost_rows = _cost_rows(
                context,
                model,
                realised,
                configuration=configuration,
                strategy=strategy,
                day=day_number,
            )
            before = state
            advanced = _advance_state(
                context,
                model,
                state,
                configuration=configuration,
                contract_version=contract_version,
                timestamp=pd.Timestamp(day_calendar["timestamp_utc"].iloc[-1]).isoformat(),
            )
            if configuration == C1_CONFIGURATION and bool(scheduled["quota_period_boundary"]):
                remaining_after = int(advanced.eaf_quota_target_taps or 0) - int(advanced.eaf_quota_completed_taps)
                if remaining_after != 0 or advanced.eaf_start_lag1 + advanced.eaf_start_lag2 != 0:
                    raise HourlyTemporalValidationError(
                        f"Annual EAF quota period did not close for {case_id}/day {day_number}."
                    )
                if zero_index + 1 < len(heat_schedule):
                    following = heat_schedule[zero_index + 1]
                    state = replace(
                        advanced,
                        eaf_quota_period_id=f"annual_quota_{int(following['quota_period_index']):03d}",
                        eaf_quota_target_taps=int(following["quota_period_target"]),
                        eaf_quota_completed_taps=0,
                    )
                else:
                    state = advanced
            else:
                state = advanced
            checkpoint = {
                "case_id": case_id,
                "configuration": configuration_label,
                "strategy": strategy,
                "calendar_day_index": day_number,
                "local_date": str(day_calendar["local_date"].iloc[0]),
                "day_length_hours": execution_hours,
                "state_before": before.snapshot(),
                "state_after": state.snapshot(),
                "solver_attempt": attempt,
                "shifted_physical_tail_warm_start_audit": warm_start_audit,
                "physical_audit": [
                    {"configuration": configuration_label, "strategy": strategy, "day": day_number, **row}
                    for row in audit
                ],
                "dispatch": dispatch_rows,
                "cost_rows": cost_rows,
                "year_endpoint_physical_witness": (
                    [
                        {
                            "hour": int(t),
                            "pefa_output_t_h": _component_value(
                                model, "pefa_pellet_output_t", t
                            ),
                            "pellet_inventory_t": _component_value(
                                model, "pellet_inventory", t
                            ),
                            "final_product_t": _component_value(
                                model, "final_product_output", t
                            ),
                            "hsm_t_h": _component_value(
                                model, "hot_strip_mill", t
                            ),
                            "dsp_final_product_t": _component_value(
                                model,
                                (
                                    "c0_dsp_final_product_output"
                                    if configuration == C0_CONFIGURATION
                                    else "dsp_final_product_output"
                                ),
                                t,
                            ),
                            "eaf_taps": _component_value(model, "eaf_tap", t),
                        }
                        for t in range(
                            int(context.time_grid.execution_steps), int(recovery_index) + 1
                        )
                    ]
                    if recovery_index is not None
                    else []
                ),
                "cumulative_realised_procurement_cost_eur": realised_cost,
                "cumulative_optimisation_procurement_cost_eur": optimisation_cost,
                "full_four_week_matrix_authorized": False,
            }
            _atomic_json(
                output / "checkpoints" / case_id / f"day_{day_number:03d}.json",
                checkpoint,
            )
            previous_physical_model = model
            completed_day_solves += 1
            progress = _progress_payload(
                run_id=run_id,
                completed_day_solves=completed_day_solves,
                total_day_solves=total_day_solves,
                case_id=case_id,
                day_index=day_number,
                started=started,
                status="running",
                session_start_completed=session_start_completed,
            )
            _atomic_json(output / "progress_current.json", progress)
            if completed_day_solves % int(reporting["progress_update_every_days"]) == 0:
                _print_progress(progress)
        if stopped_early:
            break

    if stopped_early:
        summary = {
            **manifest,
            "decision": "interrupted_by_requested_stop_after_checkpoint",
            "completed_day_solves": completed_day_solves,
            "full_year_complete": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(output / "gate_decision.json", summary)
        return summary

    if stop_after_day_per_case is not None and int(stop_after_day_per_case) < len(calendar_days):
        dispatch, costs, attempts, audits, final_cases = _consolidate_checkpoints(
            output, execution_order
        )
        dispatch_name = "qh_dispatch_partial.parquet" if is_qh else "hourly_dispatch_partial.parquet"
        dispatch.to_parquet(output / dispatch_name, index=False)
        costs.to_csv(output / "represented_cost_ledger_partial.csv", index=False)
        attempts.to_csv(output / "solver_attempts_partial.csv", index=False)
        audits.to_csv(output / "physical_audit_partial.csv", index=False)
        passed = bool(not audits.empty and audits["passed"].astype(bool).all())
        complete_cases = all(
            int(row["calendar_day_index"]) == int(stop_after_day_per_case)
            for row in final_cases.values()
        ) and len(final_cases) == len(execution_order)
        summary = {
            **manifest,
            "decision": (
                ("qh_bounded_causal_prefix_pass" if is_qh else "hourly_bounded_causal_prefix_pass")
                if passed and complete_cases
                else "needs_bounded_fix"
            ),
            "completed_day_solves": completed_day_solves,
            "completed_days_per_case": int(stop_after_day_per_case),
            "all_configured_cases_at_prefix": complete_cases,
            "physical_audit_pass": passed,
            "full_year_complete": False,
            "figure_package_generated": False,
            "full_four_week_matrix_authorized": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(output / "gate_decision.json", summary)
        return summary

    dispatch, costs, attempts, audits, final_cases = _consolidate_checkpoints(
        output, execution_order
    )
    dispatch_name = "qh_dispatch.parquet" if is_qh else "hourly_dispatch.parquet"
    dispatch.to_parquet(output / dispatch_name, index=False)
    costs.to_csv(output / "represented_cost_ledger.csv", index=False)
    attempts.to_csv(output / "solver_attempts.csv", index=False)
    audits.to_csv(output / "physical_audit.csv", index=False)
    response = pd.DataFrame(_response_rows(dispatch))
    response.to_csv(output / "plant_response_metrics.csv", index=False)
    if feasibility_shakedown:
        passed = bool(audits["passed"].astype(bool).all())
        summary = {
            **manifest,
            "decision": (
                (
                    "qh_c0_c1_physical_feasibility_shakedown_pass"
                    if is_qh
                    else "hourly_c0_c1_physical_feasibility_shakedown_pass"
                )
                if passed
                else "needs_bounded_fix"
            ),
            "full_year_complete": True,
            "completed_day_solves": total_day_solves,
            "physical_audit_pass": passed,
            "economic_results_generated": False,
            "figure_package_generated": False,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "full_four_week_matrix_authorized": False,
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(output / "gate_decision.json", summary)
        _print_progress(
            _progress_payload(
                run_id=run_id,
                completed_day_solves=total_day_solves,
                total_day_solves=total_day_solves,
                case_id="complete",
                day_index=365,
                started=started,
                status="complete",
                session_start_completed=session_start_completed,
            )
        )
        return summary
    economics = _economic_rows(
        dispatch,
        costs,
        final_cases,
        c0_config=c0_config,
        period_label="2024-10-01_to_2025-09-30_full_calendar_year",
    )
    pd.DataFrame(economics).to_csv(output / "annual_economics.csv", index=False)
    anchor_rows = _annual_anchor_rows(
        dispatch,
        costs,
        final_cases,
        economics,
        c0_config=c0_config,
    )
    _write_csv(output / "annual_operational_anchor_results.csv", anchor_rows)
    _write_csv(
        output / "annual_anchor_delta_vs_last_accepted.csv",
        [
            {
                **row,
                "last_accepted_baseline_value": "",
                "delta_vs_last_accepted": "",
                "baseline_status": (
                    "no_prior_accepted_full_year_qh_baseline"
                    if is_qh
                    else "no_prior_accepted_full_year_hourly_baseline"
                ),
            }
            for row in anchor_rows
            if row.get("anchor_family")
        ],
    )
    _write_json(
        output / "annual_operational_anchor_gate.json",
        {
            "status": "full_calendar_year_anchor_evaluation_complete_coverage_partial",
            "represented_hours": 8760,
            "calendar_coverage": "2024-10-01_to_2025-09-30",
            "full_year_certified": True,
            "constraints_or_objective_use_anchors": False,
            "last_accepted_full_year_baseline_granularity": "QH" if is_qh else "H",
            "last_accepted_full_year_baseline_available": False,
            "not_comparable_metrics": sorted(
                {
                    str(row["metric"])
                    for row in anchor_rows
                    if row.get("comparability") == "not_comparable"
                }
            ),
            "full_four_week_matrix_authorized": False,
        },
    )
    figure_manifest = _build_example_week_figure_package(
        output,
        dispatch=dispatch,
        costs=costs,
        c0_config=c0_config,
        c1_config=c1_config,
        week_start_local_date=str(reporting["figure_example_week_start_local_date"]),
    )
    pf_gate = []
    economics_frame = pd.DataFrame(economics)
    for configuration in ("C0", "C1"):
        pi = economics_frame[
            (economics_frame["configuration"] == configuration)
            & (economics_frame["strategy"] == "price_insensitive")
        ].iloc[0]
        pf = economics_frame[
            (economics_frame["configuration"] == configuration)
            & (economics_frame["strategy"] == "perfect_foresight_D")
        ].iloc[0]
        pf_gate.append(
            {
                "configuration": configuration,
                "check": "perfect_foresight_realised_cost_not_above_price_insensitive",
                "delta_eur": float(pf["realised_procurement_cost_eur"])
                - float(pi["realised_procurement_cost_eur"]),
                "passed": bool(
                    float(pf["realised_procurement_cost_eur"])
                    <= float(pi["realised_procurement_cost_eur"]) + 0.001
                ),
            }
        )
    _write_csv(output / "perfect_foresight_validation_gate.csv", pf_gate)
    production_gate = _production_comparability_rows(economics_frame)
    _write_csv(output / "annual_production_comparability_gate.csv", production_gate)
    passed = (
        all(bool(row["passed"]) for row in pf_gate)
        and all(bool(row["passed"]) for row in production_gate)
        and bool(
        audits["passed"].astype(bool).all()
        )
    )
    summary = {
        **manifest,
        "decision": (
            ("qh_c0_c1_pi_pf_full_year_pass" if is_qh else "hourly_c0_c1_pi_pf_full_year_pass")
            if passed
            else "needs_bounded_fix"
        ),
        "full_year_complete": True,
        "completed_day_solves": total_day_solves,
        "figure_count": int(figure_manifest["figure_count"]),
        "annual_anchor_evaluation_status": (
            "full_calendar_year_anchor_evaluation_complete_coverage_partial"
        ),
        "perfect_foresight_gate_pass": all(bool(row["passed"]) for row in pf_gate),
        "annual_production_comparability_gate_pass": all(
            bool(row["passed"]) for row in production_gate
        ),
        "annual_production_comparability_tolerance_mt": (
            C1_ANNUAL_PRODUCT_COMPARABILITY_TOLERANCE_T / 1_000_000.0
        ),
        "physical_audit_pass": bool(audits["passed"].astype(bool).all()),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(output / "gate_decision.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            key: summary[key]
            for key in (
                "run_id",
                "output_policy",
                "run_class",
                "lineage_role",
                "retention_status",
                "git_eligible",
                "decision",
                "full_four_week_matrix_authorized",
            )
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Perfect foresight is an oracle benchmark, not an implementable strategy.\n"
        "- The realised price ledger uses the disclosed Strict-LEAR daily repair for missing hours.\n"
        "- DST delivery days are represented natively as 23 and 25 hours.\n"
        "- Annual anchors remain validation-only and do not enter constraints or objectives.\n"
        "- No DAM bidding, mFRR, stochasticity, S10 or four-week matrix is represented.\n"
        "- `full_four_week_matrix_authorized=false`.\n",
        encoding="utf-8",
    )
    _print_progress(
        _progress_payload(
            run_id=run_id,
            completed_day_solves=total_day_solves,
            total_day_solves=total_day_solves,
            case_id="complete",
            day_index=365,
            started=started,
            status="complete",
            session_start_completed=session_start_completed,
        )
    )
    return summary


__all__ = [
    "CONFIG_PATH",
    "OUTPUT_ROOT",
    "materialize_lear_strict_realised_price_ledger",
    "prepare_lear_strict_hourly_year_inputs",
    "run_hourly_full_year",
]
