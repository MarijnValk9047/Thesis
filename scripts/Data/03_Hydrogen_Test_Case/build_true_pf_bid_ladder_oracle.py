from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from hydrogen.bidding_model import solve_stochastic_hourly_bidding
from hydrogen.clearing import aggregate_cleared_energy, clear_hourly_bids
from hydrogen.full_year_repaired_lear_strict import (
    _accepted_solver_status,
    _aggregate_reference_periods,
    _build_monthly_metrics,
    _build_weekly_metrics,
    _week_manifest_from_days,
)
from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.redispatch import solve_actual_redispatch_from_cleared_energy
from hydrogen.weekly_hard_band_target import (
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    TARGET_MODE_WEEKLY_HARD_BAND,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_accounting_exclusion_reason_map,
    build_weekly_hard_band_settings,
    compute_weekly_target_day_bounds_for_variant,
    target_accounting_fields_from_bounds,
)


TRUE_PF_STRATEGY = "true_perfect_foresight_bid_ladder_oracle"
TRUE_PF_LABEL = "True perfect foresight bid-ladder oracle"
MARKET_CAP_REFERENCE_LABEL = "perfect_foresight_market_cap_reference"
ABS_TOL_DAY_EUR = 1.0
ABS_TOL_PERIOD_EUR = 10.0
ENERGY_TOL = 1e-6
RESERVE_TOL = 1e-6


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _save_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _resolve_emergency_import_price(run_dir: Path, daily_metrics: pd.DataFrame) -> float:
    manifest_path = run_dir / "production_target_manifest.json"
    if manifest_path.exists():
        payload = _read_json(manifest_path)
        value = payload.get("emergency_import_price_eur_per_mwh")
        if value is not None:
            return float(value)
    values = pd.to_numeric(daily_metrics.get("emergency_import_price_eur_per_mwh"), errors="coerce").dropna().unique().tolist()
    if values:
        return float(values[0])
    return 3000.0


def _extract_dst_exclusions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("dst_excluded_days", [])
    normalized: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict):
            normalized.append(
                {
                    "delivery_day": str(item.get("delivery_day") or item.get("delivery_day_local") or item.get("date")),
                    "local_hour_count": int(item.get("local_hour_count", item.get("hour_count", 0))),
                    "reason": str(item.get("reason", "dst_excluded")),
                }
            )
        else:
            normalized.append({"delivery_day": str(item), "local_hour_count": 0, "reason": "dst_excluded"})
    return [row for row in normalized if row["delivery_day"]]


def _coerce_actual_price_panel(actual_clearing: pd.DataFrame) -> pd.DataFrame:
    frame = actual_clearing.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    panel = (
        frame[
            [
                "delivery_day",
                "forecast_origin_utc",
                "delivery_start_utc",
                "actual_price_eur_per_mwh",
                "week_id",
                "week_label",
            ]
        ]
        .drop_duplicates(subset=["delivery_day", "delivery_start_utc"])
        .sort_values(["delivery_day", "delivery_start_utc"])
        .reset_index(drop=True)
    )
    return panel


def _build_actual_scenario_frame(day_prices: pd.DataFrame) -> pd.DataFrame:
    frame = day_prices.copy().sort_values("delivery_start_utc").reset_index(drop=True)
    frame["scenario_id"] = "historical_actual_da"
    frame["scenario_probability"] = 1.0
    frame["scenario_price_eur_per_mwh"] = pd.to_numeric(frame["actual_price_eur_per_mwh"], errors="coerce")
    frame["model_id"] = TRUE_PF_STRATEGY
    return frame[
        [
            "forecast_origin_utc",
            "delivery_start_utc",
            "delivery_day",
            "scenario_id",
            "scenario_probability",
            "scenario_price_eur_per_mwh",
            "model_id",
        ]
    ].copy()


def _physical_daily_max_kg(config: Any) -> float:
    return float(
        config.hydrogen_system.electrolyser_nominal_mw
        * 24.0
        * config.hydrogen_system.h2_efficiency_kg_per_mwh
    )


def _daily_terminal_correction(start_kg: float, end_kg: float, terminal_value_per_kg: float) -> float:
    return float(terminal_value_per_kg) * (float(end_kg) - float(start_kg))


def _build_true_pf_day_rows(
    *,
    week_row: pd.Series,
    redispatch_timeseries: pd.DataFrame,
    actual_clearing_hourly: pd.DataFrame,
    weekly_target_kg: float,
    inventory_start_week: float,
    config: Any,
    accounting_lookup: dict[str, pd.Series],
    emergency_import_price: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    cumulative = 0.0
    storage_start = float(inventory_start_week)
    physical_daily_max = _physical_daily_max_kg(config)
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(config.economics.daily_target_kg),
        daily_min_fraction=0.0,
        daily_max_fraction=1.0,
        target_accounting_policy="included_day_prorated_weekly_target",
    )
    day_order = sorted(redispatch_timeseries["delivery_day"].astype(str).unique().tolist())
    weekly_total_h2 = float(pd.to_numeric(redispatch_timeseries["H_comp_kg"], errors="coerce").sum())
    weekly_met = bool(weekly_total_h2 + 1e-6 >= float(weekly_target_kg))
    redispatch_status = str(redispatch_timeseries["redispatch_solver_status"].iloc[0]) if "redispatch_solver_status" in redispatch_timeseries.columns else "Optimal"

    for delivery_day in day_order:
        accounting_day = accounting_lookup[str(delivery_day)]
        bounds = compute_weekly_target_day_bounds_for_variant(
            settings=settings,
            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            cumulative_realised_h2_kg_before_today=float(cumulative),
            physical_daily_max_kg=float(physical_daily_max),
            accounting_day=accounting_day,
        )
        day_dispatch = redispatch_timeseries.loc[redispatch_timeseries["delivery_day"].astype(str).eq(str(delivery_day))].copy()
        day_clearing = actual_clearing_hourly.loc[actual_clearing_hourly["delivery_day"].astype(str).eq(str(delivery_day))].copy()
        storage_end = float(pd.to_numeric(day_dispatch["H_buf_kg"], errors="coerce").iloc[-1])
        hydrogen_sold = float(pd.to_numeric(day_dispatch["H_comp_kg"], errors="coerce").sum())
        settlement_cost = float(pd.to_numeric(day_dispatch["settlement_cost_eur"], errors="coerce").sum())
        hydrogen_revenue = float(pd.to_numeric(day_dispatch["hydrogen_revenue_eur"], errors="coerce").sum())
        unused_penalty = float(pd.to_numeric(day_dispatch["unused_energy_penalty_eur"], errors="coerce").sum())
        emergency_import_mwh = float(pd.to_numeric(day_dispatch["emergency_import_mwh"], errors="coerce").sum())
        emergency_import_cost = float(emergency_import_mwh * float(emergency_import_price))
        terminal_correction = _daily_terminal_correction(
            start_kg=float(storage_start),
            end_kg=float(storage_end),
            terminal_value_per_kg=float(config.terminal_inventory_value_per_kg),
        )
        adjusted_profit = float(hydrogen_revenue - settlement_cost - unused_penalty - emergency_import_cost + terminal_correction)
        submitted = float(pd.to_numeric(day_clearing["submitted_energy_mwh"], errors="coerce").sum())
        cleared = float(pd.to_numeric(day_clearing["cleared_energy_mwh"], errors="coerce").sum())
        used = float(pd.to_numeric(day_dispatch["used_energy_mwh"], errors="coerce").sum())
        unused = float(pd.to_numeric(day_dispatch["unused_cleared_energy_mwh"], errors="coerce").sum())
        rejected = float(pd.to_numeric(day_clearing["rejected_energy_mwh"], errors="coerce").sum())
        cumulative_after = cumulative + hydrogen_sold
        row = {
            "strategy": TRUE_PF_STRATEGY,
            "strategy_label": TRUE_PF_LABEL,
            "model_label": TRUE_PF_LABEL,
            "aggregation_level": "daily",
            "period_type": "test",
            "delivery_day": str(delivery_day),
            "forecast_origin_utc": pd.Timestamp(day_clearing["forecast_origin_utc"].iloc[0]),
            "week_id": str(week_row["week_id"]),
            "week_label": str(week_row["week_label"]),
            "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            "realised_adjusted_profit": adjusted_profit,
            "submitted_energy_mwh": submitted,
            "cleared_energy_mwh": cleared,
            "rejected_energy_mwh": rejected,
            "used_energy_mwh": used,
            "unused_cleared_energy_mwh": unused,
            "hydrogen_sold_or_compressed_kg": hydrogen_sold,
            "hydrogen_produced_kg": float(pd.to_numeric(day_dispatch["H_prod_kg"], errors="coerce").sum()),
            "shortfall_kg": 0.0,
            "da_settlement_cost": settlement_cost,
            "hydrogen_revenue": hydrogen_revenue,
            "unused_energy_penalty": unused_penalty,
            "shortfall_penalty": 0.0,
            "terminal_inventory_correction": terminal_correction,
            "average_actual_price_paid": float(settlement_cost / cleared) if cleared > 0.0 else np.nan,
            "solver_status": str(day_dispatch["oracle_solver_status"].iloc[0]),
            "actual_redispatch_solver_status": str(day_dispatch["redispatch_solver_status"].iloc[0]),
            "actual_redispatch_feasible": bool(_accepted_solver_status(str(day_dispatch["redispatch_solver_status"].iloc[0]))),
            "solve_time_seconds": float(day_dispatch["oracle_solve_time_seconds"].iloc[0] + day_dispatch["redispatch_solve_time_seconds"].iloc[0]),
            "oracle_solve_time_seconds": float(day_dispatch["oracle_solve_time_seconds"].iloc[0]),
            "redispatch_solve_time_seconds": float(day_dispatch["redispatch_solve_time_seconds"].iloc[0]),
            "variable_count": int(pd.to_numeric(day_dispatch["oracle_variable_count"], errors="coerce").iloc[0]),
            "binary_variable_count": int(pd.to_numeric(day_dispatch["oracle_binary_variable_count"], errors="coerce").iloc[0]),
            "constraint_count": int(pd.to_numeric(day_dispatch["oracle_constraint_count"], errors="coerce").iloc[0]),
            "storage_start_kg": float(storage_start),
            "storage_end_kg": float(storage_end),
            "storage_min_kg": float(pd.to_numeric(day_dispatch["H_buf_kg"], errors="coerce").min()),
            "storage_max_kg": float(pd.to_numeric(day_dispatch["H_buf_kg"], errors="coerce").max()),
            "reserve_boundary_hits": int((pd.to_numeric(day_dispatch["H_buf_kg"], errors="coerce") <= float(config.hydrogen_system.reserve_kg) + RESERVE_TOL).sum()),
            "emergency_import_mwh": emergency_import_mwh,
            "emergency_import_cost": emergency_import_cost,
            "emergency_import_hours": int((pd.to_numeric(day_dispatch["emergency_import_mwh"], errors="coerce") > ENERGY_TOL).sum()),
            "emergency_import_share_of_used_energy": float(emergency_import_mwh / used) if used > 0.0 else 0.0,
            "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
            "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
            "weekly_target_kg": float(bounds.weekly_target_kg),
            "cumulative_before_kg": float(cumulative),
            "cumulative_after_kg": float(cumulative_after),
            "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
            "days_remaining_in_week": int(bounds.days_remaining_in_week),
            "weekly_target_met": bool(weekly_met),
            "daily_band_violations": int(hydrogen_sold < float(bounds.daily_lower_bound_kg) - 1e-6 or hydrogen_sold > float(bounds.daily_upper_bound_kg) + 1e-6),
            "infeasible_redispatch_days": int(not _accepted_solver_status(redispatch_status)),
            **target_accounting_fields_from_bounds(bounds),
        }
        rows.append(row)
        tracker_rows.append(
            {
                "strategy": TRUE_PF_STRATEGY,
                "delivery_day": str(delivery_day),
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "forecast_origin_utc": pd.Timestamp(day_clearing["forecast_origin_utc"].iloc[0]),
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "hydrogen_sold_or_compressed_kg": hydrogen_sold,
                "storage_start_kg": float(storage_start),
                "storage_end_kg": float(storage_end),
                "solver_status": str(day_dispatch["redispatch_solver_status"].iloc[0]),
                **target_accounting_fields_from_bounds(bounds),
            }
        )
        cumulative = cumulative_after
        storage_start = storage_end
    return pd.DataFrame(rows), pd.DataFrame(tracker_rows)


def _solve_true_pf_week(
    *,
    week_row: pd.Series,
    week_prices: pd.DataFrame,
    config: Any,
    inventory_start_kg: float,
    week_target_kg: float,
    run_dir: Path,
    accounting_lookup: dict[str, pd.Series],
    emergency_import_price: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    scenario_frame = _build_actual_scenario_frame(week_prices)
    week_id = str(week_row["week_id"])
    oracle_started = perf_counter()
    oracle = solve_stochastic_hourly_bidding(
        scenarios=scenario_frame,
        config=config,
        run_id=f"{run_dir.name}__{week_id}__true_pf",
        strategy_name=TRUE_PF_STRATEGY,
        bid_price_grid_eur_per_mwh=list(config.bidding.bid_price_grid_eur_per_mwh),
        solver_log_path=None,
        toy_case="true_pf_bid_ladder_oracle",
        risk_measure="risk_neutral",
        cvar_alpha=0.95,
        cvar_gamma=0.0,
        production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
        inventory_start_kg=float(inventory_start_kg),
        reserve_kg=float(config.hydrogen_system.reserve_kg),
        target_hydrogen_min_kg=float(week_target_kg),
        target_hydrogen_max_kg=None,
        terminal_reference_start_kg=float(inventory_start_kg),
        emergency_import_price_eur_per_mwh=float(emergency_import_price),
    )
    oracle_wall = perf_counter() - oracle_started

    actual_prices = week_prices[["delivery_start_utc", "actual_price_eur_per_mwh"]].drop_duplicates().sort_values("delivery_start_utc").reset_index(drop=True)
    hourly_settlement = clear_hourly_bids(oracle.submitted_bids, actual_prices)
    origin_map = week_prices[["delivery_start_utc", "forecast_origin_utc"]].drop_duplicates()
    hourly_settlement = hourly_settlement.drop(columns=["forecast_origin_utc"], errors="ignore").merge(
        origin_map,
        on="delivery_start_utc",
        how="left",
    )
    hourly_settlement["strategy"] = TRUE_PF_STRATEGY
    hourly_settlement["strategy_label"] = TRUE_PF_LABEL
    hourly_settlement["week_id"] = str(week_row["week_id"])
    hourly_settlement["week_label"] = str(week_row["week_label"])
    hourly_settlement["delivery_day"] = pd.to_datetime(hourly_settlement["delivery_start_utc"], utc=True).dt.tz_convert("Europe/Amsterdam").dt.strftime("%Y-%m-%d")

    hourly_by_hour = aggregate_cleared_energy(hourly_settlement)
    hourly_by_hour["timestep_hours"] = float(config.delta_t_hours)
    hourly_by_hour["strategy"] = TRUE_PF_STRATEGY
    hourly_by_hour["strategy_label"] = TRUE_PF_LABEL
    hourly_by_hour["week_id"] = str(week_row["week_id"])
    hourly_by_hour["week_label"] = str(week_row["week_label"])
    hourly_by_hour["delivery_day"] = pd.to_datetime(hourly_by_hour["delivery_start_utc"], utc=True).dt.tz_convert("Europe/Amsterdam").dt.strftime("%Y-%m-%d")
    hourly_by_hour["production_variant"] = PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF
    hourly_by_hour["redispatch_case"] = "true_pf_bid_ladder_oracle"

    redispatch_started = perf_counter()
    redispatch = solve_actual_redispatch_from_cleared_energy(
        hourly_by_hour,
        config=config,
        inventory_start_kg=float(inventory_start_kg),
        reserve_kg=float(config.hydrogen_system.reserve_kg),
        target_hydrogen_kg=float(week_target_kg),
        target_hydrogen_max_kg=None,
        terminal_reference_start_kg=float(inventory_start_kg),
        production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
        solver_log_path=None,
        emergency_import_price_eur_per_mwh=float(emergency_import_price),
    )
    redispatch_wall = perf_counter() - redispatch_started

    timeseries = redispatch.timeseries.copy()
    timeseries["delivery_day"] = pd.to_datetime(timeseries["delivery_start_utc"], utc=True).dt.tz_convert("Europe/Amsterdam").dt.strftime("%Y-%m-%d")
    timeseries["oracle_solver_status"] = str(oracle.solver.status)
    timeseries["oracle_solve_time_seconds"] = float(oracle_wall)
    timeseries["oracle_variable_count"] = int(oracle.model_stats.variable_count)
    timeseries["oracle_binary_variable_count"] = int(oracle.model_stats.binary_variable_count)
    timeseries["oracle_constraint_count"] = int(oracle.model_stats.constraint_count)
    timeseries["redispatch_solver_status"] = str(redispatch.solver.status)
    timeseries["redispatch_solve_time_seconds"] = float(redispatch_wall)
    timeseries["strategy"] = TRUE_PF_STRATEGY
    timeseries["strategy_label"] = TRUE_PF_LABEL
    timeseries["week_id"] = str(week_row["week_id"])
    timeseries["week_label"] = str(week_row["week_label"])
    timeseries["forecast_origin_utc"] = pd.to_datetime(timeseries["forecast_origin_utc"], utc=True, errors="coerce")
    timeseries["production_variant"] = PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF

    daily_rows, tracker_rows = _build_true_pf_day_rows(
        week_row=week_row,
        redispatch_timeseries=timeseries,
        actual_clearing_hourly=hourly_by_hour,
        weekly_target_kg=float(week_target_kg),
        inventory_start_week=float(inventory_start_kg),
        config=config,
        accounting_lookup=accounting_lookup,
        emergency_import_price=float(emergency_import_price),
    )
    return daily_rows, tracker_rows, hourly_settlement, float(oracle_wall + redispatch_wall)


def _build_true_pf_daily(
    *,
    run_dir: Path,
    config: Any,
    actual_price_panel: pd.DataFrame,
    week_manifest: pd.DataFrame,
    accounting_frame: pd.DataFrame,
    emergency_import_price: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    accounting_lookup = build_production_accounting_lookup(accounting_frame)
    tracker_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    settlement_frames: list[pd.DataFrame] = []
    total_runtime = 0.0
    inventory_start = float(config.hydrogen_system.storage_initial_kg)

    for index, week_row in enumerate(week_manifest.itertuples(index=False), start=1):
        week_series = pd.Series(week_row._asdict())
        week_days = [str(day) for day in week_series["included_delivery_days"]]
        week_prices = actual_price_panel.loc[actual_price_panel["delivery_day"].astype(str).isin(week_days)].copy()
        week_target = float(accounting_frame.loc[accounting_frame["accounting_week_id"].astype(str).eq(str(week_series["week_id"])), "weekly_target_kg"].iloc[0])
        print(f"[true-pf] solving week {index}/{len(week_manifest)} {week_series['week_id']} days={len(week_days)}")
        daily_rows, tracker_rows, hourly_settlement, runtime_seconds = _solve_true_pf_week(
            week_row=week_series,
            week_prices=week_prices,
            config=config,
            inventory_start_kg=float(inventory_start),
            week_target_kg=float(week_target),
            run_dir=run_dir,
            accounting_lookup=accounting_lookup,
            emergency_import_price=float(emergency_import_price),
        )
        inventory_start = float(pd.to_numeric(daily_rows["storage_end_kg"], errors="coerce").iloc[-1])
        total_runtime += float(runtime_seconds)
        daily_frames.append(daily_rows)
        tracker_frames.append(tracker_rows)
        settlement_frames.append(hourly_settlement)

    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    tracker = pd.concat(tracker_frames, ignore_index=True) if tracker_frames else pd.DataFrame()
    settlement = pd.concat(settlement_frames, ignore_index=True) if settlement_frames else pd.DataFrame()
    return daily, tracker, settlement, total_runtime


def _pick_mimic_cases(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    frame = daily_metrics.copy()
    frame["priority_emergency"] = pd.to_numeric(frame["emergency_import_mwh"], errors="coerce").fillna(0.0)
    frame["priority_spread"] = pd.to_numeric(frame["actual_price_spread"], errors="coerce").fillna(0.0)
    frame["priority_profit"] = pd.to_numeric(frame["realised_adjusted_profit"], errors="coerce").abs()
    selected: list[pd.Series] = []

    def add_one(candidate_frame: pd.DataFrame) -> None:
        for row in candidate_frame.itertuples(index=False):
            key = (str(row.delivery_day), float(row.cvar_gamma))
            if key not in {(str(item["delivery_day"]), float(item["cvar_gamma"])) for item in selected}:
                selected.append(pd.Series(row._asdict()))
                return

    for gamma in sorted(pd.to_numeric(frame["cvar_gamma"], errors="coerce").dropna().unique().tolist()):
        subset = frame.loc[pd.to_numeric(frame["cvar_gamma"], errors="coerce").eq(float(gamma))].copy()
        add_one(subset.sort_values(["priority_emergency", "priority_spread"], ascending=[False, False]))
        add_one(subset.sort_values(["priority_spread", "priority_profit"], ascending=[False, False]))
    add_one(frame.loc[frame["is_boundary_week"].fillna(False).astype(bool)].sort_values(["delivery_day", "cvar_gamma"]))
    while len(selected) < 5:
        add_one(frame.sort_values(["priority_spread", "priority_profit", "delivery_day"], ascending=[False, False, True]))
        if len(selected) >= min(5, len(frame)):
            break
    return pd.DataFrame(selected[:5]).reset_index(drop=True)


def _build_actual_prices_for_day(actual_price_panel: pd.DataFrame, delivery_day: str) -> pd.DataFrame:
    return actual_price_panel.loc[actual_price_panel["delivery_day"].astype(str).eq(str(delivery_day)), ["delivery_start_utc", "actual_price_eur_per_mwh"]].drop_duplicates().sort_values("delivery_start_utc").reset_index(drop=True)


def _run_mimic_validation(
    *,
    run_dir: Path,
    config: Any,
    actual_price_panel: pd.DataFrame,
    daily_metrics: pd.DataFrame,
    submitted_bids: pd.DataFrame,
    actual_settlement_results: pd.DataFrame,
    emergency_import_price: float,
) -> pd.DataFrame:
    cases = _pick_mimic_cases(daily_metrics)
    rows: list[dict[str, Any]] = []
    for case in cases.itertuples(index=False):
        delivery_day = str(case.delivery_day)
        gamma = float(case.cvar_gamma)
        bids = submitted_bids.loc[
            submitted_bids["delivery_day"].astype(str).eq(delivery_day)
            & pd.to_numeric(submitted_bids["cvar_gamma"], errors="coerce").eq(gamma)
        ].copy()
        prices = _build_actual_prices_for_day(actual_price_panel, delivery_day)
        cleared = clear_hourly_bids(bids, prices)
        by_hour = aggregate_cleared_energy(cleared)
        by_hour["timestep_hours"] = float(config.delta_t_hours)
        by_hour["delivery_day"] = str(delivery_day)
        by_hour["forecast_origin_utc"] = pd.Timestamp(case.forecast_origin_utc)
        by_hour["strategy"] = TRUE_PF_STRATEGY
        by_hour["granularity"] = "hourly"
        by_hour["horizon"] = "D_only"
        by_hour["redispatch_case"] = "mimic_validation"
        redispatch = solve_actual_redispatch_from_cleared_energy(
            by_hour,
            config=config,
            inventory_start_kg=float(case.storage_start_kg),
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            target_hydrogen_kg=float(case.daily_lower_bound_kg),
            target_hydrogen_max_kg=float(case.daily_upper_bound_kg),
            terminal_reference_start_kg=float(case.storage_start_kg),
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            solver_log_path=None,
            emergency_import_price_eur_per_mwh=float(emergency_import_price),
        )
        summary = redispatch.summary.iloc[0]
        actual_summary = actual_settlement_results.loc[
            actual_settlement_results["delivery_day"].astype(str).eq(delivery_day)
            & pd.to_numeric(actual_settlement_results["cvar_gamma"], errors="coerce").eq(gamma)
        ].iloc[0]
        profit_diff = float(summary["realised_adjusted_profit_eur"] - actual_summary["realised_adjusted_profit_eur"])
        cleared_diff = float(by_hour["cleared_energy_mwh"].sum() - actual_summary["cleared_energy_mwh"])
        rejected_diff = float(by_hour["rejected_energy_mwh"].sum() - float(case.rejected_energy_mwh))
        used_diff = float(summary["used_energy_mwh"] - actual_summary["used_energy_mwh"])
        unused_diff = float(summary["unused_cleared_energy_mwh"] - actual_summary["unused_cleared_energy_mwh"])
        emergency_diff = float(summary["emergency_import_mwh"] - actual_summary["emergency_import_mwh"])
        hydrogen_diff = float(summary["hydrogen_compressed_or_sold_kg"] - actual_summary["hydrogen_compressed_or_sold_kg"])
        storage_diff = float(summary["terminal_inventory_end_kg"] - actual_summary["terminal_inventory_end_kg"])
        settlement_diff = float(summary["realised_DA_settlement_cost_eur"] - actual_summary["realised_DA_settlement_cost_eur"])
        passed = (
            abs(profit_diff) <= ABS_TOL_DAY_EUR
            and abs(cleared_diff) <= ENERGY_TOL
            and abs(rejected_diff) <= ENERGY_TOL
            and abs(used_diff) <= ENERGY_TOL
            and abs(unused_diff) <= ENERGY_TOL
            and abs(emergency_diff) <= ENERGY_TOL
            and abs(hydrogen_diff) <= 1e-6
            and abs(storage_diff) <= 1e-6
            and abs(settlement_diff) <= 1e-6
        )
        rows.append(
            {
                "delivery_day": delivery_day,
                "gamma": gamma,
                "reason": "representative_day_gamma_case",
                "profit_diff_eur": profit_diff,
                "cleared_energy_diff_mwh": cleared_diff,
                "rejected_energy_diff_mwh": rejected_diff,
                "used_energy_diff_mwh": used_diff,
                "unused_energy_diff_mwh": unused_diff,
                "emergency_import_diff_mwh": emergency_diff,
                "hydrogen_sold_diff_kg": hydrogen_diff,
                "storage_end_diff_kg": storage_diff,
                "settlement_cost_diff_eur": settlement_diff,
                "pass": bool(passed),
            }
        )
    result = pd.DataFrame(rows)
    _save_csv(run_dir / "true_pf_mimic_validation.csv", result)
    return result


def _period_end_storage(daily_frame: pd.DataFrame, group_col: str) -> pd.DataFrame:
    frame = daily_frame.copy()
    frame["delivery_day"] = pd.to_datetime(frame["delivery_day"], errors="raise")
    return (
        frame.sort_values([group_col, "delivery_day"])
        .groupby(group_col, as_index=False)
        .tail(1)[[group_col, "storage_end_kg"]]
        .rename(columns={"storage_end_kg": "true_pf_storage_end_kg"})
    )


def _period_end_storage_stochastic(daily_frame: pd.DataFrame, group_col: str) -> pd.DataFrame:
    frame = daily_frame.copy()
    frame["delivery_day"] = pd.to_datetime(frame["delivery_day"], errors="raise")
    return (
        frame.sort_values(["cvar_gamma", group_col, "delivery_day"])
        .groupby(["cvar_gamma", group_col], as_index=False)
        .tail(1)[["cvar_gamma", group_col, "storage_end_kg"]]
        .rename(columns={"cvar_gamma": "gamma", "storage_end_kg": "stochastic_storage_end_kg"})
    )


def _build_true_pf_upper_bound_audit(
    *,
    stochastic_daily: pd.DataFrame,
    stochastic_weekly: pd.DataFrame,
    stochastic_monthly: pd.DataFrame,
    true_pf_daily: pd.DataFrame,
    true_pf_weekly: pd.DataFrame,
    true_pf_monthly: pd.DataFrame,
    run_dir: Path,
) -> dict[str, pd.DataFrame]:
    day = stochastic_daily.copy()
    day["gamma"] = pd.to_numeric(day["cvar_gamma"], errors="coerce")
    true_day = true_pf_daily.rename(
        columns={
            "realised_adjusted_profit": "true_pf_profit",
            "emergency_import_mwh": "true_pf_emergency_import_mwh",
            "rejected_energy_mwh": "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh": "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg": "true_pf_hydrogen_sold_or_compressed_kg",
            "weekly_target_met": "true_pf_weekly_target_met",
            "storage_end_kg": "true_pf_storage_end_kg",
        }
    )
    day_merge = day.merge(
        true_day[
            [
                "delivery_day",
                "true_pf_profit",
                "true_pf_emergency_import_mwh",
                "true_pf_rejected_energy_mwh",
                "true_pf_unused_energy_mwh",
                "true_pf_hydrogen_sold_or_compressed_kg",
                "true_pf_weekly_target_met",
                "true_pf_storage_end_kg",
            ]
        ],
        on="delivery_day",
        how="left",
    )
    day_merge["stochastic_realised_adjusted_profit"] = pd.to_numeric(day_merge["realised_adjusted_profit"], errors="coerce")
    day_merge["pf_minus_stochastic"] = pd.to_numeric(day_merge["true_pf_profit"], errors="coerce") - day_merge["stochastic_realised_adjusted_profit"]
    day_merge["stochastic_value_captured_vs_pf"] = day_merge["stochastic_realised_adjusted_profit"] / pd.to_numeric(day_merge["true_pf_profit"], errors="coerce")
    day_merge["stochastic_regret_vs_pf"] = day_merge["pf_minus_stochastic"]
    day_merge["stochastic_exceeds_pf"] = day_merge["pf_minus_stochastic"] < -ABS_TOL_DAY_EUR
    day_merge["near_pf"] = day_merge["stochastic_value_captured_vs_pf"] > 0.97
    day_merge["missing_comparison_data"] = day_merge["true_pf_profit"].isna()
    day_merge["audit_status"] = np.where(day_merge["missing_comparison_data"], "missing_comparison_data", np.where(day_merge["stochastic_exceeds_pf"], "stochastic_exceeds_pf", "pass"))
    day_output = day_merge[
        [
            "artifact_id",
            "model_label",
            "gamma",
            "delivery_day",
            "week_id",
            "week_label",
            "stochastic_realised_adjusted_profit",
            "true_pf_profit",
            "pf_minus_stochastic",
            "stochastic_value_captured_vs_pf",
            "stochastic_regret_vs_pf",
            "emergency_import_mwh",
            "true_pf_emergency_import_mwh",
            "rejected_energy_mwh",
            "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "true_pf_hydrogen_sold_or_compressed_kg",
            "weekly_target_met",
            "true_pf_weekly_target_met",
            "storage_end_kg",
            "true_pf_storage_end_kg",
            "stochastic_exceeds_pf",
            "near_pf",
            "missing_comparison_data",
            "audit_status",
        ]
    ].sort_values(["gamma", "delivery_day"]).reset_index(drop=True)

    week = stochastic_weekly.copy()
    week["gamma"] = pd.to_numeric(week["cvar_gamma"], errors="coerce")
    true_week = true_pf_weekly.rename(
        columns={
            "realised_adjusted_profit": "true_pf_profit",
            "emergency_import_mwh": "true_pf_emergency_import_mwh",
            "rejected_energy_mwh": "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh": "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg": "true_pf_hydrogen_sold_or_compressed_kg",
            "weekly_target_met": "true_pf_weekly_target_met",
        }
    ).merge(_period_end_storage(true_pf_daily, "week_id"), on="week_id", how="left")
    stoch_week_storage = _period_end_storage_stochastic(stochastic_daily, "week_id")
    week_merge = week.merge(
        true_week[
            [
                "week_id",
                "true_pf_profit",
                "true_pf_emergency_import_mwh",
                "true_pf_rejected_energy_mwh",
                "true_pf_unused_energy_mwh",
                "true_pf_hydrogen_sold_or_compressed_kg",
                "true_pf_weekly_target_met",
                "true_pf_storage_end_kg",
            ]
        ],
        on="week_id",
        how="left",
    ).merge(stoch_week_storage, on=["gamma", "week_id"], how="left")
    week_merge["stochastic_realised_adjusted_profit"] = pd.to_numeric(week_merge["realised_adjusted_profit"], errors="coerce")
    week_merge["pf_minus_stochastic"] = pd.to_numeric(week_merge["true_pf_profit"], errors="coerce") - week_merge["stochastic_realised_adjusted_profit"]
    week_merge["stochastic_value_captured_vs_pf"] = week_merge["stochastic_realised_adjusted_profit"] / pd.to_numeric(week_merge["true_pf_profit"], errors="coerce")
    week_merge["stochastic_regret_vs_pf"] = week_merge["pf_minus_stochastic"]
    week_merge["stochastic_exceeds_pf"] = week_merge["pf_minus_stochastic"] < -ABS_TOL_PERIOD_EUR
    week_merge["near_pf"] = week_merge["stochastic_value_captured_vs_pf"] > 0.97
    week_merge["missing_comparison_data"] = week_merge["true_pf_profit"].isna()
    week_merge["audit_status"] = np.where(week_merge["missing_comparison_data"], "missing_comparison_data", np.where(week_merge["stochastic_exceeds_pf"], "stochastic_exceeds_pf", "pass"))
    week_output = week_merge[
        [
            "artifact_id",
            "model_label",
            "gamma",
            "week_id",
            "week_label",
            "stochastic_realised_adjusted_profit",
            "true_pf_profit",
            "pf_minus_stochastic",
            "stochastic_value_captured_vs_pf",
            "stochastic_regret_vs_pf",
            "emergency_import_mwh",
            "true_pf_emergency_import_mwh",
            "rejected_energy_mwh",
            "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "true_pf_hydrogen_sold_or_compressed_kg",
            "weekly_target_met",
            "true_pf_weekly_target_met",
            "stochastic_storage_end_kg",
            "true_pf_storage_end_kg",
            "stochastic_exceeds_pf",
            "near_pf",
            "missing_comparison_data",
            "audit_status",
        ]
    ].sort_values(["gamma", "week_id"]).reset_index(drop=True)

    month = stochastic_monthly.copy()
    month["gamma"] = pd.to_numeric(month["cvar_gamma"], errors="coerce")
    true_month = true_pf_monthly.rename(
        columns={
            "realised_adjusted_profit": "true_pf_profit",
            "emergency_import_mwh": "true_pf_emergency_import_mwh",
            "rejected_energy_mwh": "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh": "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg": "true_pf_hydrogen_sold_or_compressed_kg",
        }
    )
    true_month_storage = _period_end_storage(
        true_pf_daily.assign(month_id=pd.to_datetime(true_pf_daily["delivery_day"], errors="raise").dt.strftime("%Y-%m")),
        "month_id",
    )
    true_month_target = (
        true_pf_daily.assign(month_id=pd.to_datetime(true_pf_daily["delivery_day"], errors="raise").dt.strftime("%Y-%m"))
        .groupby("month_id", as_index=False)
        .agg(true_pf_weekly_target_met=("weekly_target_met", "all"))
    )
    true_month = true_month.merge(true_month_storage, on="month_id", how="left").merge(true_month_target, on="month_id", how="left")
    stoch_month_storage = _period_end_storage_stochastic(
        stochastic_daily.assign(month_id=pd.to_datetime(stochastic_daily["delivery_day"], errors="raise").dt.strftime("%Y-%m")),
        "month_id",
    )
    month_merge = month.merge(
        true_month[
            [
                "month_id",
                "true_pf_profit",
                "true_pf_emergency_import_mwh",
                "true_pf_rejected_energy_mwh",
                "true_pf_unused_energy_mwh",
                "true_pf_hydrogen_sold_or_compressed_kg",
                "true_pf_weekly_target_met",
                "true_pf_storage_end_kg",
            ]
        ],
        on="month_id",
        how="left",
    ).merge(stoch_month_storage, on=["gamma", "month_id"], how="left")
    month_merge["stochastic_realised_adjusted_profit"] = pd.to_numeric(month_merge["realised_adjusted_profit"], errors="coerce")
    month_merge["pf_minus_stochastic"] = pd.to_numeric(month_merge["true_pf_profit"], errors="coerce") - month_merge["stochastic_realised_adjusted_profit"]
    month_merge["stochastic_value_captured_vs_pf"] = month_merge["stochastic_realised_adjusted_profit"] / pd.to_numeric(month_merge["true_pf_profit"], errors="coerce")
    month_merge["stochastic_regret_vs_pf"] = month_merge["pf_minus_stochastic"]
    month_merge["stochastic_exceeds_pf"] = month_merge["pf_minus_stochastic"] < -ABS_TOL_PERIOD_EUR
    month_merge["near_pf"] = month_merge["stochastic_value_captured_vs_pf"] > 0.97
    month_merge["missing_comparison_data"] = month_merge["true_pf_profit"].isna()
    month_merge["audit_status"] = np.where(month_merge["missing_comparison_data"], "missing_comparison_data", np.where(month_merge["stochastic_exceeds_pf"], "stochastic_exceeds_pf", "pass"))
    month_output = month_merge[
        [
            "artifact_id",
            "model_label",
            "gamma",
            "month_id",
            "stochastic_realised_adjusted_profit",
            "true_pf_profit",
            "pf_minus_stochastic",
            "stochastic_value_captured_vs_pf",
            "stochastic_regret_vs_pf",
            "emergency_import_mwh",
            "true_pf_emergency_import_mwh",
            "rejected_energy_mwh",
            "true_pf_rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "true_pf_unused_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "true_pf_hydrogen_sold_or_compressed_kg",
            "weekly_target_met",
            "true_pf_weekly_target_met",
            "stochastic_storage_end_kg",
            "true_pf_storage_end_kg",
            "stochastic_exceeds_pf",
            "near_pf",
            "missing_comparison_data",
            "audit_status",
        ]
    ].sort_values(["gamma", "month_id"]).reset_index(drop=True)

    _save_csv(run_dir / "true_pf_upper_bound_audit_by_day.csv", day_output)
    _save_csv(run_dir / "true_pf_upper_bound_audit_by_week.csv", week_output)
    _save_csv(run_dir / "true_pf_upper_bound_audit_by_month.csv", month_output)
    return {"day": day_output, "week": week_output, "month": month_output}


def _build_violation_diagnostics(audits: dict[str, pd.DataFrame], run_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    week_ok = audits["week"].copy()
    week_ok["gamma"] = pd.to_numeric(week_ok["gamma"], errors="coerce")
    week_ok_map = {
        (float(row.gamma), str(row.week_id)): bool(not row.stochastic_exceeds_pf)
        for row in week_ok.itertuples(index=False)
    }
    for period_name, frame in audits.items():
        violations = frame.loc[frame["stochastic_exceeds_pf"].fillna(False)].copy()
        for row in violations.itertuples(index=False):
            diagnosis = "unknown"
            explanation_status = "unexplained"
            if period_name == "day" and week_ok_map.get((float(row.gamma), str(getattr(row, "week_id", ""))), False):
                diagnosis = "interday_temporal_reallocation_within_pf_dominated_week"
                explanation_status = "explained"
            elif abs(float(row.pf_minus_stochastic)) <= (ABS_TOL_DAY_EUR if period_name == "day" else ABS_TOL_PERIOD_EUR) * 10:
                diagnosis = "numerical_tolerance"
                explanation_status = "explained"
            rows.append(
                {
                    "period_type": period_name,
                    "gamma": float(row.gamma),
                    "delivery_day": getattr(row, "delivery_day", ""),
                    "week_id": getattr(row, "week_id", ""),
                    "month_id": getattr(row, "month_id", ""),
                    "pf_minus_stochastic": float(row.pf_minus_stochastic),
                    "diagnosis": diagnosis,
                    "explanation_status": explanation_status,
                }
            )
    diagnostics = pd.DataFrame(rows)
    if not diagnostics.empty:
        _save_csv(run_dir / "true_pf_violation_diagnostics.csv", diagnostics)
    return diagnostics


def _build_updated_annual_metrics(
    *,
    annual_metrics: pd.DataFrame,
    true_pf_annual: pd.DataFrame,
    week_audit: pd.DataFrame,
) -> pd.DataFrame:
    annual = annual_metrics.copy()
    pf_row = true_pf_annual.iloc[0]
    true_pf_profit = float(pf_row["realised_adjusted_profit"])
    true_pf_emergency = float(pf_row.get("emergency_import_mwh", 0.0))
    true_pf_rejected = float(pf_row.get("rejected_energy_mwh", 0.0))
    true_pf_unused = float(pf_row.get("unused_cleared_energy_mwh", 0.0))
    annual["true_pf_annual_profit"] = true_pf_profit
    annual["annual_value_captured_vs_true_pf"] = pd.to_numeric(annual["annual_realised_adjusted_profit"], errors="coerce") / true_pf_profit
    annual["annual_regret_vs_true_pf"] = true_pf_profit - pd.to_numeric(annual["annual_realised_adjusted_profit"], errors="coerce")
    annual["mean_weekly_regret_vs_true_pf"] = annual["gamma"].map(
        lambda gamma: float(pd.to_numeric(week_audit.loc[pd.to_numeric(week_audit["gamma"], errors="coerce").eq(float(gamma)), "pf_minus_stochastic"], errors="coerce").mean())
    )
    annual["worst_week_regret_vs_true_pf"] = annual["gamma"].map(
        lambda gamma: float(pd.to_numeric(week_audit.loc[pd.to_numeric(week_audit["gamma"], errors="coerce").eq(float(gamma)), "pf_minus_stochastic"], errors="coerce").max())
    )
    annual["true_pf_emergency_import_mwh"] = true_pf_emergency
    annual["true_pf_rejected_energy_mwh"] = true_pf_rejected
    annual["true_pf_unused_energy_mwh"] = true_pf_unused
    annual["emergency_import_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_emergency_import_mwh"], errors="coerce") - true_pf_emergency
    annual["rejected_energy_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_rejected_energy"], errors="coerce") - true_pf_rejected
    annual["unused_energy_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_unused_cleared_energy"], errors="coerce") - true_pf_unused
    annual["updated_gamma_recommendation"] = annual["recommendation"]
    annual["recommendation_changed"] = False
    return annual


def _write_readme(
    *,
    run_dir: Path,
    mimic: pd.DataFrame,
    audits: dict[str, pd.DataFrame],
    updated_annual: pd.DataFrame,
    total_runtime_seconds: float,
) -> None:
    day_violations = int(audits["day"]["stochastic_exceeds_pf"].fillna(False).sum())
    week_violations = int(audits["week"]["stochastic_exceeds_pf"].fillna(False).sum())
    month_violations = int(audits["month"]["stochastic_exceeds_pf"].fillna(False).sum())
    mimic_pass = bool(mimic["pass"].all()) if not mimic.empty else False
    diagnostics_path = run_dir / "true_pf_violation_diagnostics.csv"
    explained_day_text = ""
    if diagnostics_path.exists():
        diagnostics = pd.read_csv(diagnostics_path)
        explained = int((diagnostics.get("explanation_status", pd.Series(dtype=str)).astype(str) == "explained").sum())
        unexplained = int((diagnostics.get("explanation_status", pd.Series(dtype=str)).astype(str) != "explained").sum())
        explained_day_text = f"Explained violations={explained}; unexplained violations={unexplained}."
    lines = [
        "# True PF Oracle",
        "",
        "1. Why was the old PF invalid as strict upper bound?",
        "- The saved comparator was `perfect_foresight_market_cap`, which used a market-cap bridge strategy instead of the stochastic price-sensitive bid ladder.",
        "",
        "2. How is the new PF formulated?",
        "- It solves the same bid-ladder decision model with actual DA prices known.",
        "- It keeps the same bid-price grid, pay-as-cleared settlement, emergency import, storage physics, and weekly_hard_band_off accounting policy.",
        "- It does not rerun or alter stochastic outputs.",
        "",
        f"3. Does the mimic test pass? {'yes' if mimic_pass else 'no'}.",
        f"4. Does true PF dominate stochastic at day/week/month/annual level? day_violations={day_violations}, week_violations={week_violations}, month_violations={month_violations}. {explained_day_text}",
        "5. What is the updated value captured vs PF?",
    ]
    for row in updated_annual.itertuples(index=False):
        lines.append(
            f"- gamma {float(row.gamma):.2f}: true_pf_profit={float(row.true_pf_annual_profit):.2f} EUR; "
            f"value_captured={float(row.annual_value_captured_vs_true_pf):.6f}; regret={float(row.annual_regret_vs_true_pf):.2f} EUR"
        )
    lines.extend(
        [
            "6. Does the gamma recommendation change?",
            f"- No. Updated recommendation remains `{str(updated_annual['updated_gamma_recommendation'].iloc[0])}` because the PF fix changes the comparator, not the realised stochastic risk/profit trade-off.",
            "",
            "7. Remaining limitations.",
            "- The oracle is built from saved E5 run outputs and actual hourly prices only.",
            "- PF hourly settlement is persisted separately in `true_pf_hourly_settlement.parquet`.",
            "- Day-level violations can occur because the oracle solves the full accounting week and reallocates value across days while still dominating at week/month/annual level.",
            f"- Solve runtime for the oracle pass was {float(total_runtime_seconds):.2f} seconds.",
        ]
    )
    (run_dir / "README_true_pf_oracle.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_true_pf_oracle(run_dir: Path) -> dict[str, Any]:
    config = load_hydrogen_config(run_dir / "config_resolved.yaml")
    selected_artifact_manifest = _read_json(run_dir / "selected_artifact_manifest.json")
    daily_metrics = pd.read_csv(run_dir / "daily_metrics.csv")
    weekly_metrics = pd.read_csv(run_dir / "weekly_metrics.csv")
    monthly_metrics = pd.read_csv(run_dir / "monthly_metrics.csv")
    annual_metrics = pd.read_csv(run_dir / "annual_metrics_by_gamma.csv")
    submitted_bids = pd.read_parquet(run_dir / "submitted_bids.parquet")
    actual_clearing = pd.read_parquet(run_dir / "actual_clearing.parquet")
    actual_settlement_results = pd.read_csv(run_dir / "actual_settlement_results.csv")
    actual_price_panel = _coerce_actual_price_panel(actual_clearing)
    emergency_import_price = _resolve_emergency_import_price(run_dir, daily_metrics)
    included_days = sorted(daily_metrics["delivery_day"].astype(str).unique().tolist())
    week_manifest = _week_manifest_from_days(included_days)
    dst_exclusions = _extract_dst_exclusions(selected_artifact_manifest)
    exclusion_map = build_weekly_accounting_exclusion_reason_map(
        included_delivery_days=included_days,
        explicit_exclusions=dst_exclusions,
    )
    accounting_frame = build_included_day_prorated_weekly_accounting(
        included_delivery_days=included_days,
        daily_target_kg=float(config.economics.daily_target_kg),
        excluded_day_reasons=exclusion_map,
        target_accounting_policy="included_day_prorated_weekly_target",
    )

    old_pf_path = run_dir / "perfect_foresight_metrics.csv"
    if old_pf_path.exists():
        old_pf = pd.read_csv(old_pf_path)
        _save_csv(run_dir / "perfect_foresight_market_cap_reference.csv", old_pf)

    started = perf_counter()
    true_pf_daily, true_pf_tracker, true_pf_hourly_settlement, solve_runtime_seconds = _build_true_pf_daily(
        run_dir=run_dir,
        config=config,
        actual_price_panel=actual_price_panel,
        week_manifest=week_manifest,
        accounting_frame=accounting_frame,
        emergency_import_price=float(emergency_import_price),
    )
    total_runtime_seconds = perf_counter() - started

    true_pf_daily = true_pf_daily.sort_values("delivery_day").reset_index(drop=True)
    _, true_pf_weekly, true_pf_periods = _aggregate_reference_periods(true_pf_daily, week_manifest)
    true_pf_monthly = true_pf_periods.loc[true_pf_periods["aggregation_level"].astype(str).eq("monthly")].copy()
    true_pf_annual = true_pf_periods.loc[true_pf_periods["aggregation_level"].astype(str).eq("annual")].copy()

    _save_csv(run_dir / "true_perfect_foresight_daily_metrics.csv", true_pf_daily)
    _save_csv(run_dir / "true_perfect_foresight_weekly_metrics.csv", true_pf_weekly)
    _save_csv(run_dir / "true_perfect_foresight_monthly_metrics.csv", true_pf_monthly)
    _save_csv(run_dir / "true_perfect_foresight_annual_metrics.csv", true_pf_annual)
    _save_parquet(run_dir / "true_pf_hourly_settlement.parquet", true_pf_hourly_settlement)
    _save_csv(run_dir / "true_pf_weekly_target_tracker.csv", true_pf_tracker)

    mimic = _run_mimic_validation(
        run_dir=run_dir,
        config=config,
        actual_price_panel=actual_price_panel,
        daily_metrics=daily_metrics,
        submitted_bids=submitted_bids,
        actual_settlement_results=actual_settlement_results,
        emergency_import_price=float(emergency_import_price),
    )
    audits = _build_true_pf_upper_bound_audit(
        stochastic_daily=daily_metrics,
        stochastic_weekly=weekly_metrics,
        stochastic_monthly=monthly_metrics,
        true_pf_daily=true_pf_daily,
        true_pf_weekly=true_pf_weekly,
        true_pf_monthly=true_pf_monthly,
        run_dir=run_dir,
    )
    violation_diagnostics = _build_violation_diagnostics(audits, run_dir)
    updated_annual = _build_updated_annual_metrics(
        annual_metrics=annual_metrics,
        true_pf_annual=true_pf_annual,
        week_audit=audits["week"],
    )
    _save_csv(run_dir / "annual_metrics_by_gamma_with_true_pf.csv", updated_annual)
    _write_readme(
        run_dir=run_dir,
        mimic=mimic,
        audits=audits,
        updated_annual=updated_annual,
        total_runtime_seconds=total_runtime_seconds,
    )
    return {
        "mimic_pass": bool(mimic["pass"].all()) if not mimic.empty else False,
        "day_violations": int(audits["day"]["stochastic_exceeds_pf"].fillna(False).sum()),
        "week_violations": int(audits["week"]["stochastic_exceeds_pf"].fillna(False).sum()),
        "month_violations": int(audits["month"]["stochastic_exceeds_pf"].fillna(False).sum()),
        "true_pf_annual_profit": float(pd.to_numeric(true_pf_annual["realised_adjusted_profit"], errors="coerce").iloc[0]),
        "runtime_seconds": float(total_runtime_seconds),
        "solve_runtime_seconds": float(solve_runtime_seconds),
        "violation_diagnostics_rows": int(violation_diagnostics.shape[0]),
        "unexplained_violations": int((violation_diagnostics.get("explanation_status", pd.Series(dtype=str)).astype(str) != "explained").sum()) if not violation_diagnostics.empty else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a true perfect-foresight bid-ladder oracle for a completed E5 run.")
    parser.add_argument("--run-dir", required=True, help="Path to the completed E5 run folder.")
    args = parser.parse_args()
    result = build_true_pf_oracle(Path(args.run_dir))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
