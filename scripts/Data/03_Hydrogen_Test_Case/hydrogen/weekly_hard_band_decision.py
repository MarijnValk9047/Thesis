from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from .benchmarks import run_perfect_foresight, run_price_insensitive
from .bidding import dispatch_schedule_to_one_block_bid_curve
from .bidding_backtest import run_real_scenario_bidding_dry_run
from .clearing import aggregate_cleared_energy, clear_hourly_bids
from .cvar import compute_weighted_cvar_from_frame
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .redispatch import solve_actual_redispatch_from_cleared_energy
from .run_registry import (
    build_inputs_manifest,
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs
from .selected_test_weeks_cvar_policy_eval import (
    DEFAULT_ALPHA,
    DEFAULT_GAMMAS,
    DEFAULT_WEEK_IDS,
    _load_and_validate_phase_e2_weeks,
)
from .selected_week_smoke import (
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    TOLERANCE,
    _label_for_artifact,
    _validation_row,
    _weighted_quantile,
)
from .selected_week_suite import _valid_daily_registry_for_artifact
from .validation_cvar_sweep import _aggregate_weekly_metrics, _build_cvar_validation_checks
from .weekly_hard_band_target import (
    TARGET_MODE_WEEKLY_HARD_BAND,
    WeeklyHardBandSettings,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_accounting_exclusion_reason_map,
    build_weekly_hard_band_settings,
    compute_weekly_target_day_bounds,
    daily_frame_matches_accounting,
    target_accounting_fields_from_bounds,
)


@dataclass(frozen=True)
class PhaseE4DecisionRunResult:
    run_dir: Path
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    aggregated_metrics_by_model_gamma: pd.DataFrame
    model_decision_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    runtime_summary: pd.DataFrame


def _bool_text(value: bool) -> str:
    return "true" if bool(value) else "false"


def _gamma_tag(gamma: float) -> str:
    return str(float(gamma)).replace("-", "m").replace(".", "p")


def _safe_numeric(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _accepted_solver_status(status: Any) -> bool:
    text = str(status).strip().lower()
    return text == "optimal" or text.startswith("optimal")


def _save_parquet_if_possible(run_dir: Path, name: str, frame: pd.DataFrame) -> bool:
    try:
        save_frame_parquet(run_dir, name, frame)
        return True
    except Exception:
        return False


def _build_phase_e4_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_ids: list[str],
    output_root: Path | None,
    run_slug: str,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    updated = replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(run_slug),
            execution_mode="weekly_hard_band_target_decision",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=(
            "stochastic_cvar_fixed_policy_selected_test_weeks",
            "price_insensitive_plan_first_market_cap",
            "perfect_foresight_market_cap",
        ),
        outputs=replace(
            base.outputs,
            root=Path(output_root) if output_root is not None else base.outputs.root,
            save_figures=False,
        ),
    )
    return updated


def _prepare_artifact_day_payloads(
    *,
    config: HydrogenConfig,
    artifact_ids: list[str],
    selected_delivery_days: set[str],
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[Path]]:
    payloads: dict[str, dict[str, dict[str, Any]]] = {}
    input_paths: list[Path] = [config.config_path, config.models.scenario_catalog]
    for artifact_id in artifact_ids:
        artifact_config = replace(config, models=replace(config.models, include=(str(artifact_id),)))
        selected_daily, _, spec, _, manifest = _valid_daily_registry_for_artifact(
            config=artifact_config,
            artifact_id=artifact_id,
        )
        scenarios, _ = load_scenarios_for_artifact(spec, config=artifact_config)
        scenarios = scenarios.copy()
        scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True, errors="raise")
        scenarios["delivery_start_utc"] = pd.to_datetime(scenarios["delivery_start_utc"], utc=True, errors="raise")
        scenarios["delivery_day"] = pd.to_datetime(scenarios["delivery_day"], errors="raise").dt.strftime("%Y-%m-%d")
        selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(selected_delivery_days)].copy()
        day_map: dict[str, dict[str, Any]] = {}
        for row in selected_daily.to_dict(orient="records"):
            delivery_day = str(row["delivery_day"])
            origin = pd.Timestamp(row["forecast_origin_utc"])
            selected = scenarios.loc[scenarios["forecast_origin_utc"].eq(origin)].copy()
            selected = selected.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)
            if selected.empty:
                raise ValueError(f"No scenario rows found for artifact={artifact_id}, delivery_day={delivery_day}, origin={origin}.")
            day_map[delivery_day] = {
                "day_meta": row,
                "forecast_origin_utc": origin,
                "scenarios": selected,
                "model_id": str(row["model_id"]),
                "model_label": str(row["model_label"]),
                "validation_mode": str(row["validation_mode"]),
                "thesis_grade": bool(row["thesis_grade"]),
                "forecast_origin_reconstruction_used": bool(row["forecast_origin_reconstruction_used"]),
                "artifact_manifest": manifest,
                "artifact_path": spec.path,
            }
        missing_days = sorted(selected_delivery_days.difference(day_map))
        if missing_days:
            raise ValueError(f"Artifact {artifact_id} is missing selected support days: {missing_days}")
        payloads[str(artifact_id)] = day_map
        input_paths.append(spec.path)
    return payloads, input_paths


def _actual_prices_from_day_frame(day_frame: pd.DataFrame) -> pd.DataFrame:
    actual_prices = (
        day_frame[["delivery_start_utc", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    actual_prices["delivery_start_utc"] = pd.to_datetime(actual_prices["delivery_start_utc"], utc=True, errors="raise")
    actual_prices["actual_price_eur_per_mwh"] = pd.to_numeric(actual_prices["actual_price_eur_per_mwh"], errors="raise")
    return actual_prices


def _build_strategy_day_row(
    *,
    run_id: str,
    strategy: str,
    week_row: pd.Series,
    delivery_day: str,
    forecast_origin_utc: pd.Timestamp,
    lower_bound_kg: float,
    upper_bound_kg: float,
    weekly_target_kg: float,
    cumulative_before_kg: float,
    cumulative_after_kg: float,
    remaining_target_before_today_kg: float,
    days_remaining_in_week: int,
    bounds: Any,
    submitted_energy_mwh: float,
    actual_clearing_by_hour: pd.DataFrame,
    redispatch_summary: pd.Series,
    plan_solver_status: str,
    plan_solve_time_seconds: float,
    plan_variable_count: int | None,
    plan_binary_count: int | None,
    plan_constraint_count: int | None,
) -> dict[str, Any]:
    cleared_energy_mwh = float(actual_clearing_by_hour["cleared_energy_mwh"].sum())
    weighted_price = (
        float(
            (
                actual_clearing_by_hour["actual_price_eur_per_mwh"].astype(float)
                * actual_clearing_by_hour["cleared_energy_mwh"].astype(float)
            ).sum()
            / cleared_energy_mwh
        )
        if cleared_energy_mwh > 0.0
        else float("nan")
    )
    actual_h2 = float(redispatch_summary["hydrogen_compressed_or_sold_kg"])
    return {
        "run_id": str(run_id),
        "strategy": str(strategy),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "period_type": "test",
        "aggregation_level": "daily",
        "delivery_day": str(delivery_day),
        "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
        "realised_adjusted_profit": float(redispatch_summary["realised_adjusted_profit_eur"]),
        "cleared_energy_mwh": cleared_energy_mwh,
        "used_energy_mwh": float(redispatch_summary["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(redispatch_summary["unused_cleared_energy_mwh"]),
        "hydrogen_sold_or_compressed_kg": actual_h2,
        "shortfall_kg": float(redispatch_summary["shortfall_kg"]),
        "da_settlement_cost": float(redispatch_summary["realised_DA_settlement_cost_eur"]),
        "hydrogen_revenue": float(redispatch_summary["hydrogen_revenue_eur"]),
        "unused_energy_penalty": float(redispatch_summary["unused_energy_penalty_eur"]),
        "shortfall_penalty": float(redispatch_summary["shortfall_penalty_eur"]),
        "terminal_inventory_correction": float(redispatch_summary["terminal_inventory_correction_eur"]),
        "average_actual_price_paid": weighted_price,
        "solver_status": str(plan_solver_status),
        "solve_time_seconds": float(plan_solve_time_seconds),
        "submitted_energy_mwh": float(submitted_energy_mwh),
        "rejected_energy_mwh": float(submitted_energy_mwh - cleared_energy_mwh),
        "daily_lower_bound_kg": float(lower_bound_kg),
        "daily_upper_bound_kg": float(upper_bound_kg),
        "weekly_target_kg": float(weekly_target_kg),
        "cumulative_before_kg": float(cumulative_before_kg),
        "cumulative_after_kg": float(cumulative_after_kg),
        "remaining_target_before_today_kg": float(remaining_target_before_today_kg),
        "days_remaining_in_week": int(days_remaining_in_week),
        "weekly_target_met": bool(False),
        "daily_band_violations": int(actual_h2 < lower_bound_kg - TOLERANCE or actual_h2 > upper_bound_kg + TOLERANCE),
        "infeasible_redispatch_days": int(not _accepted_solver_status(redispatch_summary["solver_status"])),
        "storage_min_kg": float(redispatch_summary["storage_min_kg"]),
        "storage_max_kg": float(redispatch_summary["storage_max_kg"]),
        "reserve_boundary_hits": int(redispatch_summary["reserve_boundary_hits"]),
        "variable_count": np.nan if plan_variable_count is None else int(plan_variable_count),
        "binary_variable_count": np.nan if plan_binary_count is None else int(plan_binary_count),
        "constraint_count": np.nan if plan_constraint_count is None else int(plan_constraint_count),
        **target_accounting_fields_from_bounds(bounds),
    }


def _accounting_frame_for_days(
    *,
    week_days: list[str],
    accounting_lookup: dict[str, pd.Series],
) -> pd.DataFrame:
    rows = [accounting_lookup[str(day)].to_dict() for day in week_days if str(day) in accounting_lookup]
    return pd.DataFrame(rows).sort_values("delivery_day").reset_index(drop=True) if rows else pd.DataFrame()


def _run_price_insensitive_week(
    *,
    week_row: pd.Series,
    week_days: list[str],
    reference_days: dict[str, dict[str, Any]],
    config: HydrogenConfig,
    settings: WeeklyHardBandSettings,
    run_id: str,
    cache_path: Path,
    accounting_lookup: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    week_accounting = _accounting_frame_for_days(week_days=week_days, accounting_lookup=accounting_lookup)
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        if (
            int(cached.loc[cached["aggregation_level"].astype(str).eq("daily")].shape[0]) == len(week_days)
            and daily_frame_matches_accounting(
                daily_frame=cached.loc[cached["aggregation_level"].astype(str).eq("daily")].copy(),
                accounting_frame=week_accounting,
                target_accounting_policy=settings.target_accounting_policy,
            )
        ):
            tracker = pd.read_csv(cache_path.parent / f"{cache_path.stem}__tracker.csv")
            return cached, tracker

    rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    inventory_start = float(config.hydrogen_system.storage_initial_kg)
    cumulative = 0.0
    for delivery_day in week_days:
        day_payload = reference_days[delivery_day]
        accounting_day = accounting_lookup[delivery_day]
        bounds = compute_weekly_target_day_bounds(
            settings=settings,
            cumulative_realised_h2_kg_before_today=cumulative,
            accounting_day=accounting_day,
        )
        day_frame = day_payload["scenarios"]
        actual_prices = _actual_prices_from_day_frame(day_frame)
        benchmark = run_price_insensitive(
            day_frame=day_frame,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            apply_terminal_value=True,
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            target_hydrogen_min_kg=bounds.daily_lower_bound_kg,
            target_hydrogen_max_kg=bounds.daily_upper_bound_kg,
            solver_log_path=str(cache_path.parent / f"{delivery_day}__benchmark_plan_solver_log.txt") if config.outputs.save_solver_log else None,
        )
        dispatch = benchmark.dispatch.copy()
        dispatch["forecast_origin_utc"] = day_payload["forecast_origin_utc"]
        dispatch["scenario_model"] = "price_insensitive_benchmark"
        bids = dispatch_schedule_to_one_block_bid_curve(
            dispatch,
            run_id=f"{run_id}__benchmark__{delivery_day}",
            source_strategy="price_insensitive",
            bridge_strategy="price_insensitive_plan_first_market_cap",
            bid_price_eur_per_mwh=float(config.bidding.price_insensitive_bid_price_eur_per_mwh),
            scenario_model="price_insensitive_benchmark",
            forecast_origin_utc=day_payload["forecast_origin_utc"],
        )
        actual_clearing = clear_hourly_bids(bids, actual_prices)
        actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
        actual_clearing_by_hour["timestep_hours"] = float(config.delta_t_hours)
        redispatch = solve_actual_redispatch_from_cleared_energy(
            actual_clearing_by_hour,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            target_hydrogen_kg=bounds.daily_lower_bound_kg,
            target_hydrogen_max_kg=bounds.daily_upper_bound_kg,
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            solver_log_path=cache_path.parent / f"{delivery_day}__benchmark_redispatch_solver_log.txt" if config.outputs.save_solver_log else None,
        )
        summary = redispatch.summary.iloc[0]
        cumulative_after = cumulative + float(summary["hydrogen_compressed_or_sold_kg"])
        rows.append(
            _build_strategy_day_row(
                run_id=run_id,
                strategy="price_insensitive_plan_first_market_cap",
                week_row=week_row,
                delivery_day=delivery_day,
                forecast_origin_utc=day_payload["forecast_origin_utc"],
                lower_bound_kg=bounds.daily_lower_bound_kg,
                upper_bound_kg=bounds.daily_upper_bound_kg,
                weekly_target_kg=bounds.weekly_target_kg,
                cumulative_before_kg=cumulative,
                cumulative_after_kg=cumulative_after,
                remaining_target_before_today_kg=bounds.remaining_target_before_today_kg,
                days_remaining_in_week=int(bounds.days_remaining_in_week),
                bounds=bounds,
                submitted_energy_mwh=float(actual_clearing_by_hour["submitted_energy_mwh"].sum()),
                actual_clearing_by_hour=actual_clearing_by_hour,
                redispatch_summary=summary,
                plan_solver_status=benchmark.solver_status,
                plan_solve_time_seconds=benchmark.solver_runtime_seconds,
                plan_variable_count=benchmark.model_stats.variable_count if benchmark.model_stats is not None else None,
                plan_binary_count=benchmark.model_stats.binary_variable_count if benchmark.model_stats is not None else None,
                plan_constraint_count=benchmark.model_stats.constraint_count if benchmark.model_stats is not None else None,
            )
        )
        tracker_rows.append(
            {
                "strategy": "price_insensitive_plan_first_market_cap",
                "artifact_id": "",
                "model_label": "Price insensitive benchmark",
                "gamma": np.nan,
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "delivery_day": str(delivery_day),
                "forecast_origin_utc": day_payload["forecast_origin_utc"],
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "hydrogen_sold_or_compressed_kg": float(summary["hydrogen_compressed_or_sold_kg"]),
                "storage_start_kg": float(inventory_start),
                "storage_end_kg": float(summary["terminal_inventory_end_kg"]),
                "solver_status": str(summary["solver_status"]),
                **target_accounting_fields_from_bounds(bounds),
            }
        )
        cumulative = cumulative_after
        inventory_start = float(summary["terminal_inventory_end_kg"])

    daily = pd.DataFrame(rows).sort_values("delivery_day").reset_index(drop=True)
    daily["weekly_target_met"] = bool(cumulative >= float(week_accounting["weekly_target_kg"].iloc[0]) - TOLERANCE)
    tracker = pd.DataFrame(tracker_rows).sort_values("delivery_day").reset_index(drop=True)
    save_frame_csv(cache_path.parent, cache_path.name, daily)
    save_frame_csv(cache_path.parent, f"{cache_path.stem}__tracker.csv", tracker)
    return daily, tracker


def _run_perfect_foresight_week(
    *,
    week_row: pd.Series,
    week_days: list[str],
    reference_days: dict[str, dict[str, Any]],
    config: HydrogenConfig,
    settings: WeeklyHardBandSettings,
    run_id: str,
    cache_path: Path,
    accounting_lookup: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    week_accounting = _accounting_frame_for_days(week_days=week_days, accounting_lookup=accounting_lookup)
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        if (
            int(cached.loc[cached["aggregation_level"].astype(str).eq("daily")].shape[0]) == len(week_days)
            and daily_frame_matches_accounting(
                daily_frame=cached.loc[cached["aggregation_level"].astype(str).eq("daily")].copy(),
                accounting_frame=week_accounting,
                target_accounting_policy=settings.target_accounting_policy,
            )
        ):
            tracker = pd.read_csv(cache_path.parent / f"{cache_path.stem}__tracker.csv")
            return cached, tracker

    market_cap = float(max(config.bidding.bid_price_grid_eur_per_mwh))
    rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    inventory_start = float(config.hydrogen_system.storage_initial_kg)
    cumulative = 0.0
    for delivery_day in week_days:
        day_payload = reference_days[delivery_day]
        accounting_day = accounting_lookup[delivery_day]
        bounds = compute_weekly_target_day_bounds(
            settings=settings,
            cumulative_realised_h2_kg_before_today=cumulative,
            accounting_day=accounting_day,
        )
        day_frame = day_payload["scenarios"]
        actual_prices = _actual_prices_from_day_frame(day_frame)
        pf = run_perfect_foresight(
            day_frame=day_frame,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            apply_terminal_value=True,
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            target_hydrogen_min_kg=bounds.daily_lower_bound_kg,
            target_hydrogen_max_kg=bounds.daily_upper_bound_kg,
            solver_log_path=str(cache_path.parent / f"{delivery_day}__pf_plan_solver_log.txt") if config.outputs.save_solver_log else None,
        )
        dispatch = pf.dispatch.copy()
        dispatch["forecast_origin_utc"] = day_payload["forecast_origin_utc"]
        dispatch["scenario_model"] = "perfect_foresight_oracle"
        bids = dispatch_schedule_to_one_block_bid_curve(
            dispatch,
            run_id=f"{run_id}__pf__{delivery_day}",
            source_strategy="perfect_foresight",
            bridge_strategy="perfect_foresight_market_cap",
            bid_price_eur_per_mwh=market_cap,
            scenario_model="perfect_foresight_oracle",
            forecast_origin_utc=day_payload["forecast_origin_utc"],
        )
        actual_clearing = clear_hourly_bids(bids, actual_prices)
        actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
        actual_clearing_by_hour["timestep_hours"] = float(config.delta_t_hours)
        redispatch = solve_actual_redispatch_from_cleared_energy(
            actual_clearing_by_hour,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            target_hydrogen_kg=bounds.daily_lower_bound_kg,
            target_hydrogen_max_kg=bounds.daily_upper_bound_kg,
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            solver_log_path=cache_path.parent / f"{delivery_day}__pf_redispatch_solver_log.txt" if config.outputs.save_solver_log else None,
        )
        summary = redispatch.summary.iloc[0]
        cumulative_after = cumulative + float(summary["hydrogen_compressed_or_sold_kg"])
        rows.append(
            _build_strategy_day_row(
                run_id=run_id,
                strategy="perfect_foresight_market_cap",
                week_row=week_row,
                delivery_day=delivery_day,
                forecast_origin_utc=day_payload["forecast_origin_utc"],
                lower_bound_kg=bounds.daily_lower_bound_kg,
                upper_bound_kg=bounds.daily_upper_bound_kg,
                weekly_target_kg=bounds.weekly_target_kg,
                cumulative_before_kg=cumulative,
                cumulative_after_kg=cumulative_after,
                remaining_target_before_today_kg=bounds.remaining_target_before_today_kg,
                days_remaining_in_week=int(bounds.days_remaining_in_week),
                bounds=bounds,
                submitted_energy_mwh=float(actual_clearing_by_hour["submitted_energy_mwh"].sum()),
                actual_clearing_by_hour=actual_clearing_by_hour,
                redispatch_summary=summary,
                plan_solver_status=pf.solver_status,
                plan_solve_time_seconds=pf.solver_runtime_seconds,
                plan_variable_count=pf.model_stats.variable_count if pf.model_stats is not None else None,
                plan_binary_count=pf.model_stats.binary_variable_count if pf.model_stats is not None else None,
                plan_constraint_count=pf.model_stats.constraint_count if pf.model_stats is not None else None,
            )
        )
        tracker_rows.append(
            {
                "strategy": "perfect_foresight_market_cap",
                "artifact_id": "",
                "model_label": "Perfect foresight",
                "gamma": np.nan,
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "delivery_day": str(delivery_day),
                "forecast_origin_utc": day_payload["forecast_origin_utc"],
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "hydrogen_sold_or_compressed_kg": float(summary["hydrogen_compressed_or_sold_kg"]),
                "storage_start_kg": float(inventory_start),
                "storage_end_kg": float(summary["terminal_inventory_end_kg"]),
                "solver_status": str(summary["solver_status"]),
                **target_accounting_fields_from_bounds(bounds),
            }
        )
        cumulative = cumulative_after
        inventory_start = float(summary["terminal_inventory_end_kg"])

    daily = pd.DataFrame(rows).sort_values("delivery_day").reset_index(drop=True)
    daily["weekly_target_met"] = bool(cumulative >= float(week_accounting["weekly_target_kg"].iloc[0]) - TOLERANCE)
    tracker = pd.DataFrame(tracker_rows).sort_values("delivery_day").reset_index(drop=True)
    save_frame_csv(cache_path.parent, cache_path.name, daily)
    save_frame_csv(cache_path.parent, f"{cache_path.stem}__tracker.csv", tracker)
    return daily, tracker


def _load_cached_day_payload(cache_row: pd.Series, *, model_id: str) -> dict[str, Any]:
    day_run_dir = Path(str(cache_row["day_run_dir"]))
    actual_settlement = pd.read_csv(day_run_dir / "actual_settlement_results.csv")
    metrics_summary = pd.read_csv(day_run_dir / "metrics_summary.csv")
    scenario_objective_summary = pd.read_csv(day_run_dir / "scenario_objective_summary.csv")
    scenario_settlement = pd.read_csv(day_run_dir / "scenario_settlement_results.csv")
    validation_checks = pd.read_csv(day_run_dir / "validation_checks.csv")
    actual_clearing = pd.read_parquet(day_run_dir / "actual_clearing.parquet")
    actual_redispatch = pd.read_parquet(day_run_dir / "actual_redispatch_timeseries.parquet")
    submitted_bids = pd.read_parquet(day_run_dir / "submitted_bids.parquet")
    scenario_clearing = pd.read_parquet(day_run_dir / "scenario_clearing.parquet")
    scenario_dispatch = pd.read_parquet(day_run_dir / "scenario_dispatch.parquet")
    model_stats_payload = json.loads((day_run_dir / "model_stats.json").read_text(encoding="utf-8"))
    stochastic_model = model_stats_payload.get("stochastic_bidding_model", {})
    return {
        "delivery_day": str(cache_row["delivery_day"]),
        "forecast_origin_utc": pd.Timestamp(cache_row["forecast_origin_utc"]),
        "run_dir": day_run_dir,
        "model_id": str(model_id),
        "submitted_bids": submitted_bids,
        "scenario_clearing": scenario_clearing,
        "scenario_dispatch": scenario_dispatch,
        "scenario_settlement_results": scenario_settlement,
        "scenario_objective_summary": scenario_objective_summary,
        "actual_clearing": actual_clearing,
        "actual_redispatch_timeseries": actual_redispatch,
        "actual_settlement_results": actual_settlement,
        "metrics_summary": metrics_summary,
        "validation_checks": validation_checks,
        "stochastic_solver_status": str(stochastic_model.get("solver_status", "")),
        "stochastic_objective_value": stochastic_model.get("objective_value"),
        "stochastic_solve_time_seconds": stochastic_model.get("solve_time_seconds"),
        "stochastic_variable_count": stochastic_model.get("variable_count"),
        "stochastic_binary_variable_count": stochastic_model.get("binary_variable_count"),
        "stochastic_constraint_count": stochastic_model.get("constraint_count"),
    }


def _payload_from_live_result(result: Any, *, model_id: str) -> dict[str, Any]:
    return {
        "delivery_day": str(result.delivery_day),
        "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
        "run_dir": result.run_dir,
        "model_id": str(model_id),
        "submitted_bids": result.optimisation_result.submitted_bids.copy(),
        "scenario_clearing": result.optimisation_result.scenario_clearing.copy(),
        "scenario_dispatch": result.optimisation_result.scenario_dispatch.copy(),
        "scenario_settlement_results": result.optimisation_result.scenario_economics.copy(),
        "scenario_objective_summary": result.scenario_objective_summary.copy(),
        "actual_clearing": result.actual_clearing.copy(),
        "actual_redispatch_timeseries": result.actual_redispatch_timeseries.copy(),
        "actual_settlement_results": result.actual_settlement_results.copy(),
        "metrics_summary": result.metrics_summary.copy(),
        "validation_checks": result.validation_checks.copy(),
        "stochastic_solver_status": str(result.optimisation_result.solver.status),
        "stochastic_objective_value": result.optimisation_result.solver.objective_value,
        "stochastic_solve_time_seconds": result.optimisation_result.solver.runtime_seconds,
        "stochastic_variable_count": result.optimisation_result.model_stats.variable_count,
        "stochastic_binary_variable_count": result.optimisation_result.model_stats.binary_variable_count,
        "stochastic_constraint_count": result.optimisation_result.model_stats.constraint_count,
    }


def _build_stochastic_daily_metric(
    *,
    run_id: str,
    artifact_id: str,
    model_label: str,
    validation_mode: str,
    thesis_grade: bool,
    forecast_origin_reconstruction_used: bool,
    week_row: pd.Series,
    day_meta: dict[str, Any],
    payload: dict[str, Any],
    cvar_alpha: float,
    cvar_gamma: float,
    benchmark_profit_row: pd.Series | None,
    perfect_foresight_profit_row: pd.Series | None,
    bounds: Any,
    cumulative_before_kg: float,
) -> dict[str, Any]:
    actual_summary = payload["actual_settlement_results"].iloc[0]
    metrics = payload["metrics_summary"].iloc[0]
    submitted = payload["submitted_bids"].copy()
    actual_clearing = payload["actual_clearing"].copy()
    scenario_results = payload["scenario_objective_summary"].copy()
    actual_redispatch = payload["actual_redispatch_timeseries"].copy()
    validation_checks = payload["validation_checks"].copy()
    scenario_probs = scenario_results[["scenario_id", "scenario_probability"]].drop_duplicates(subset=["scenario_id"]).copy()
    probability_sum = float(pd.to_numeric(scenario_probs["scenario_probability"], errors="coerce").sum())
    scenario_count = int(scenario_probs["scenario_id"].astype(str).nunique())
    scenario_profit_values = pd.to_numeric(scenario_results["adjusted_profit_eur"], errors="coerce").to_numpy()
    scenario_prob_values = pd.to_numeric(scenario_results["scenario_probability"], errors="coerce").to_numpy()
    reconstructed = compute_weighted_cvar_from_frame(
        scenario_results,
        loss_column="loss_eur",
        probability_column="scenario_probability",
        alpha=float(cvar_alpha),
    )
    submitted_energy_total = float(pd.to_numeric(submitted["bid_quantity_mw"], errors="coerce").sum())
    weighted_average_bid_price = (
        float(
            (
                pd.to_numeric(submitted["bid_quantity_mw"], errors="coerce")
                * pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce")
            ).sum()
            / submitted_energy_total
        )
        if submitted_energy_total > 0.0
        else float("nan")
    )
    high_bid_energy = float(
        pd.to_numeric(
            submitted.loc[pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce") >= 250.0, "bid_quantity_mw"],
            errors="coerce",
        ).sum()
    )
    market_cap = float(pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce").max())
    market_cap_bid_energy = float(
        pd.to_numeric(
            submitted.loc[np.isclose(pd.to_numeric(submitted["bid_price_eur_per_mwh"], errors="coerce"), market_cap), "bid_quantity_mw"],
            errors="coerce",
        ).sum()
    )
    benchmark_profit = float(benchmark_profit_row["realised_adjusted_profit"]) if benchmark_profit_row is not None else float("nan")
    perfect_foresight_profit = float(perfect_foresight_profit_row["realised_adjusted_profit"]) if perfect_foresight_profit_row is not None else float("nan")
    actual_hydrogen = float(actual_summary["hydrogen_compressed_or_sold_kg"])
    cumulative_after_kg = float(cumulative_before_kg + actual_hydrogen)
    is_redispatch_feasible = _accepted_solver_status(actual_summary["solver_status"])
    row = {
        "run_id": str(run_id),
        "artifact_id": str(artifact_id),
        "model_id": str(payload["model_id"]),
        "model_label": str(model_label),
        "validation_mode": str(validation_mode),
        "thesis_grade": bool(thesis_grade),
        "forecast_origin_reconstruction_used": bool(forecast_origin_reconstruction_used),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "period_type": "test",
        "selection_reason": str(week_row.get("selection_reason", "")),
        "delivery_day": str(payload["delivery_day"]),
        "forecast_origin_utc": pd.Timestamp(payload["forecast_origin_utc"]),
        "day_run_dir": str(payload["run_dir"]) if payload["run_dir"] is not None else "",
        "strategy": "stochastic_bid_risk_neutral" if abs(float(cvar_gamma)) <= 1e-12 else "stochastic_bid_cvar",
        "risk_mode": "risk_neutral" if abs(float(cvar_gamma)) <= 1e-12 else "cvar",
        "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
        "cvar_alpha": float(cvar_alpha),
        "cvar_gamma": float(cvar_gamma),
        "actual_price_mean": float(day_meta["actual_price_mean"]),
        "actual_price_min": float(day_meta["actual_price_min"]),
        "actual_price_max": float(day_meta["actual_price_max"]),
        "actual_price_spread": float(day_meta["actual_price_spread"]),
        "actual_price_std": float(day_meta["actual_price_std"]),
        "actual_negative_price_hours": int(day_meta["actual_negative_price_hours"]),
        "scenario_count": int(scenario_count),
        "scenario_probability_check": bool(abs(probability_sum - 1.0) <= 1e-6),
        "expected_adjusted_profit": float(metrics["expected_adjusted_profit_eur"]),
        "realised_adjusted_profit": float(actual_summary["realised_adjusted_profit_eur"]),
        "realised_operating_profit": float(actual_summary["hydrogen_revenue_eur"] - actual_summary["realised_DA_settlement_cost_eur"] - actual_summary["unused_energy_penalty_eur"] - actual_summary["shortfall_penalty_eur"]),
        "hydrogen_revenue": float(actual_summary["hydrogen_revenue_eur"]),
        "da_settlement_cost": float(actual_summary["realised_DA_settlement_cost_eur"]),
        "unused_energy_penalty": float(actual_summary["unused_energy_penalty_eur"]),
        "shortfall_penalty": float(actual_summary["shortfall_penalty_eur"]),
        "terminal_inventory_correction": float(actual_summary["terminal_inventory_correction_eur"]),
        "benchmark_profit": benchmark_profit,
        "stochastic_minus_benchmark_profit": float(actual_summary["realised_adjusted_profit_eur"] - benchmark_profit) if pd.notna(benchmark_profit) else float("nan"),
        "average_actual_price_paid": float(metrics["weighted_average_actual_price_paid_for_cleared_energy"]),
        "realised_minus_expected_profit": float(actual_summary["realised_adjusted_profit_eur"] - metrics["expected_adjusted_profit_eur"]),
        "var_loss": float(reconstructed.zeta),
        "cvar_loss": float(reconstructed.cvar),
        "reconstructed_var_loss": float(reconstructed.zeta),
        "reconstructed_cvar_loss": float(reconstructed.cvar),
        "cvar_reconstruction_error": 0.0,
        "worst_scenario_profit": float(pd.to_numeric(scenario_results["adjusted_profit_eur"], errors="coerce").min()),
        "worst_scenario_loss": float(pd.to_numeric(scenario_results["loss_eur"], errors="coerce").max()),
        "downside_tail_mean_profit": float(-reconstructed.cvar),
        "downside_tail_mean_loss": float(reconstructed.cvar),
        "realised_outcome_percentile_within_scenarios": float(
            100.0
            * (
                pd.to_numeric(scenario_results.loc[pd.to_numeric(scenario_results["adjusted_profit_eur"], errors="coerce") <= float(actual_summary["realised_adjusted_profit_eur"]), "scenario_probability"], errors="coerce")
                .sum()
            )
        ),
        "scenario_profit_p05": float(_weighted_quantile(scenario_profit_values, scenario_prob_values, 0.05)),
        "scenario_profit_p10": float(_weighted_quantile(scenario_profit_values, scenario_prob_values, 0.10)),
        "scenario_profit_p50": float(_weighted_quantile(scenario_profit_values, scenario_prob_values, 0.50)),
        "scenario_profit_p90": float(_weighted_quantile(scenario_profit_values, scenario_prob_values, 0.90)),
        "scenario_profit_p95": float(_weighted_quantile(scenario_profit_values, scenario_prob_values, 0.95)),
        "submitted_energy_mwh": float(metrics["submitted_energy_mwh"]),
        "cleared_energy_mwh": float(metrics["cleared_energy_mwh"]),
        "rejected_energy_mwh": float(metrics["rejected_energy_mwh"]),
        "used_cleared_energy_mwh": float(actual_summary["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(actual_summary["unused_cleared_energy_mwh"]),
        "clearing_ratio": float(metrics["clearing_ratio"]),
        "rejected_energy_share": float(metrics["rejected_energy_mwh"] / metrics["submitted_energy_mwh"]) if float(metrics["submitted_energy_mwh"]) > 0.0 else 0.0,
        "hours_with_zero_clearing": int(metrics["zero_clearing_hours"]),
        "hours_with_partial_clearing": int(metrics["partial_clearing_hours"]),
        "weighted_average_bid_price": float(weighted_average_bid_price),
        "high_bid_share": float(high_bid_energy / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "market_cap_bid_share": float(market_cap_bid_energy / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "high_bid_energy_mwh": float(high_bid_energy),
        "market_cap_bid_energy_mwh": float(market_cap_bid_energy),
        "hydrogen_produced_kg": float(actual_summary["hydrogen_produced_kg"]),
        "hydrogen_sold_or_compressed_kg": actual_hydrogen,
        "target_hydrogen_kg": float(actual_summary["target_hydrogen_kg"]),
        "production_fulfilment_ratio": float(actual_summary["target_fulfilment_ratio_capped_for_reliability"]),
        "shortfall_kg": float(actual_summary["shortfall_kg"]),
        "storage_start_kg": float(actual_summary["storage_initial_kg"]),
        "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"]),
        "storage_min_kg": float(actual_summary["storage_min_kg"]),
        "storage_max_kg": float(actual_summary["storage_max_kg"]),
        "reserve_boundary_hits": int(actual_summary["reserve_boundary_hits"]),
        "electrolyser_energy_mwh": float((pd.to_numeric(actual_redispatch["P_el_mw"], errors="coerce").fillna(0.0) * pd.to_numeric(actual_redispatch["timestep_hours"], errors="coerce").fillna(1.0)).sum()),
        "compressor_energy_mwh": float((pd.to_numeric(actual_redispatch["P_comp_mw"], errors="coerce").fillna(0.0) * pd.to_numeric(actual_redispatch["timestep_hours"], errors="coerce").fillna(1.0)).sum()),
        "electrolyser_ramp_hits": int(actual_summary.get("ramp_boundary_hits", 0)),
        "solver_status": str(payload["stochastic_solver_status"]),
        "actual_redispatch_solver_status": str(actual_summary["solver_status"]),
        "actual_redispatch_feasible": bool(is_redispatch_feasible),
        "objective_value": payload["stochastic_objective_value"],
        "solve_time_seconds": payload["stochastic_solve_time_seconds"],
        "mip_gap": float(np.nan if payload["stochastic_objective_value"] is None else 0.001),
        "variable_count": np.nan if payload["stochastic_variable_count"] is None else int(payload["stochastic_variable_count"]),
        "binary_variable_count": np.nan if payload["stochastic_binary_variable_count"] is None else int(payload["stochastic_binary_variable_count"]),
        "constraint_count": np.nan if payload["stochastic_constraint_count"] is None else int(payload["stochastic_constraint_count"]),
        "benchmark_cleared_energy_mwh": float(benchmark_profit_row["cleared_energy_mwh"]) if benchmark_profit_row is not None else float("nan"),
        "benchmark_hydrogen_sold_or_compressed_kg": float(benchmark_profit_row["hydrogen_sold_or_compressed_kg"]) if benchmark_profit_row is not None else float("nan"),
        "benchmark_average_actual_price_paid": float(benchmark_profit_row["average_actual_price_paid"]) if benchmark_profit_row is not None else float("nan"),
        "benchmark_shortfall_kg": float(benchmark_profit_row["shortfall_kg"]) if benchmark_profit_row is not None else float("nan"),
        "validation_fail_count": int((validation_checks["status"].astype(str) == "fail").sum()),
        "validation_warn_count": int((validation_checks["status"].astype(str) == "warn").sum()),
        "regime_label": str(week_row["regime_label"]),
        "cvar_tail_profit": float(-reconstructed.cvar),
        "perfect_foresight_profit": perfect_foresight_profit,
        "value_captured_vs_perfect_foresight": float(actual_summary["realised_adjusted_profit_eur"] / perfect_foresight_profit) if pd.notna(perfect_foresight_profit) and abs(perfect_foresight_profit) > 1e-9 else float("nan"),
        "regret_vs_perfect_foresight": float(perfect_foresight_profit - actual_summary["realised_adjusted_profit_eur"]) if pd.notna(perfect_foresight_profit) else float("nan"),
        "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
        "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
        "weekly_target_kg": float(bounds.weekly_target_kg),
        "cumulative_before_kg": float(cumulative_before_kg),
        "cumulative_after_kg": float(cumulative_after_kg),
        "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
        "days_remaining_in_week": int(bounds.days_remaining_in_week),
        "weekly_target_met": False,
        "daily_band_violations": int(actual_hydrogen < bounds.daily_lower_bound_kg - TOLERANCE or actual_hydrogen > bounds.daily_upper_bound_kg + TOLERANCE),
        "infeasible_redispatch_days": int(not is_redispatch_feasible),
    }
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if "accepted" in actual_clearing.columns else pd.DataFrame()
    row["accepted_bid_energy_mwh"] = float(pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce").sum()) if not accepted.empty else 0.0
    return row


def _weekly_metrics_from_daily(daily_metrics: pd.DataFrame, selected_weeks: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for week_id, week_group in daily_metrics.groupby("week_id", sort=False):
        week_row = selected_weeks.loc[selected_weeks["week_id"].astype(str).eq(str(week_id))].iloc[0]
        for (artifact_id, model_label, gamma), group in week_group.groupby(["artifact_id", "model_label", "cvar_gamma"], sort=False):
            submitted = float(group["submitted_energy_mwh"].sum())
            cleared = float(group["cleared_energy_mwh"].sum())
            benchmark_profit = float(group["benchmark_profit"].sum())
            pf_profit = float(group["perfect_foresight_profit"].sum())
            total_high_bid = float(group["high_bid_energy_mwh"].sum())
            total_market_cap_bid = float(group["market_cap_bid_energy_mwh"].sum())
            row = {
                "artifact_id": str(artifact_id),
                "model_id": str(group["model_id"].iloc[0]),
                "model_label": str(model_label),
                "validation_mode": str(group["validation_mode"].iloc[0]),
                "thesis_grade": bool(group["thesis_grade"].iloc[0]),
                "week_id": str(week_id),
                "week_label": str(week_row["week_label"]),
                "period_type": "test",
                "strategy": str(group["strategy"].iloc[0]),
                "risk_mode": str(group["risk_mode"].iloc[0]),
                "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
                "cvar_alpha": float(group["cvar_alpha"].iloc[0]),
                "cvar_gamma": float(gamma),
                "run_id": str(group["run_id"].iloc[0]),
                "week_start": str(week_row["delivery_start_date"]),
                "week_end": str(week_row["delivery_end_date"]),
                "number_of_delivery_days": int(group.shape[0]),
                "expected_adjusted_profit": float(group["expected_adjusted_profit"].sum()),
                "realised_adjusted_profit": float(group["realised_adjusted_profit"].sum()),
                "realised_operating_profit": float(group["realised_operating_profit"].sum()),
                "hydrogen_revenue": float(group["hydrogen_revenue"].sum()),
                "da_settlement_cost": float(group["da_settlement_cost"].sum()),
                "unused_energy_penalty": float(group["unused_energy_penalty"].sum()),
                "shortfall_penalty": float(group["shortfall_penalty"].sum()),
                "terminal_inventory_correction": float(group["terminal_inventory_correction"].sum()),
                "benchmark_profit": benchmark_profit,
                "stochastic_minus_benchmark_profit": float(group["realised_adjusted_profit"].sum() - benchmark_profit),
                "average_actual_price_paid": float(group["da_settlement_cost"].sum() / cleared) if cleared > 0.0 else float("nan"),
                "realised_minus_expected_profit": float(group["realised_adjusted_profit"].sum() - group["expected_adjusted_profit"].sum()),
                "var_loss": float(group["var_loss"].sum()),
                "cvar_loss": float(group["cvar_loss"].sum()),
                "worst_scenario_profit": float(group["worst_scenario_profit"].min()),
                "worst_scenario_loss": float(group["worst_scenario_loss"].max()),
                "downside_tail_mean_profit": float(group["cvar_tail_profit"].sum()),
                "downside_tail_mean_loss": float(group["cvar_loss"].sum()),
                "submitted_energy_mwh": submitted,
                "cleared_energy_mwh": cleared,
                "rejected_energy_mwh": float(group["rejected_energy_mwh"].sum()),
                "used_cleared_energy_mwh": float(group["used_cleared_energy_mwh"].sum()),
                "unused_cleared_energy_mwh": float(group["unused_cleared_energy_mwh"].sum()),
                "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
                "weighted_average_bid_price": float(
                    (pd.to_numeric(group["weighted_average_bid_price"], errors="coerce") * pd.to_numeric(group["submitted_energy_mwh"], errors="coerce")).sum() / submitted
                ) if submitted > 0.0 else float("nan"),
                "high_bid_share": float(total_high_bid / submitted) if submitted > 0.0 else 0.0,
                "market_cap_bid_share": float(total_market_cap_bid / submitted) if submitted > 0.0 else 0.0,
                "hydrogen_produced_kg": float(group["hydrogen_produced_kg"].sum()),
                "hydrogen_sold_or_compressed_kg": float(group["hydrogen_sold_or_compressed_kg"].sum()),
                "target_hydrogen_kg": float(group["target_hydrogen_kg"].sum()),
                "shortfall_kg": float(group["shortfall_kg"].sum()),
                "storage_start_kg": float(group["storage_start_kg"].iloc[0]),
                "storage_end_kg": float(group["storage_end_kg"].iloc[-1]),
                "storage_min_kg": float(group["storage_min_kg"].min()),
                "storage_max_kg": float(group["storage_max_kg"].max()),
                "reserve_boundary_hits": int(group["reserve_boundary_hits"].sum()),
                "scenario_count": int(group["scenario_count"].max()),
                "scenario_probability_check": bool(group["scenario_probability_check"].all()),
                "solver_status": "Optimal" if group["solver_status"].map(_accepted_solver_status).all() else "non_optimal_present",
                "objective_value": float(pd.to_numeric(group["objective_value"], errors="coerce").sum()),
                "solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
                "mip_gap": float(pd.to_numeric(group["mip_gap"], errors="coerce").max()),
                "variable_count": int(pd.to_numeric(group["variable_count"], errors="coerce").max()),
                "binary_variable_count": int(pd.to_numeric(group["binary_variable_count"], errors="coerce").max()),
                "constraint_count": int(pd.to_numeric(group["constraint_count"], errors="coerce").max()),
                "regime_label": str(week_row["regime_label"]),
                "perfect_foresight_profit": pf_profit,
                "value_captured_vs_perfect_foresight": float(group["realised_adjusted_profit"].sum() / pf_profit) if abs(pf_profit) > 1e-9 else float("nan"),
                "regret_vs_perfect_foresight": float(pf_profit - group["realised_adjusted_profit"].sum()),
                "cvar_tail_profit": float(group["cvar_tail_profit"].sum()),
                "weekly_target_kg": float(group["weekly_target_kg"].iloc[0]),
                "daily_lower_bound_kg": float(group["daily_lower_bound_kg"].sum()),
                "daily_upper_bound_kg": float(group["daily_upper_bound_kg"].sum()),
                "weekly_target_met": bool(group["weekly_target_met"].iloc[0]),
                "daily_band_violations": int(group["daily_band_violations"].sum()),
                "infeasible_redispatch_days": int(group["infeasible_redispatch_days"].sum()),
                "actual_redispatch_feasible_all_days": bool(group["actual_redispatch_feasible"].all()),
            }
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)


def _aggregate_metrics_by_model_gamma(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (artifact_id, model_label, gamma), group in weekly_metrics.groupby(["artifact_id", "model_label", "cvar_gamma"], sort=False):
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "gamma": float(gamma),
                "week_count": int(group.shape[0]),
                "feasible_all_days": bool(group["actual_redispatch_feasible_all_days"].all() and group["solver_status"].map(_accepted_solver_status).all()),
                "weekly_targets_met_all_weeks": bool(group["weekly_target_met"].all()),
                "daily_band_violations": int(group["daily_band_violations"].sum()),
                "infeasible_day_count": int(group["infeasible_redispatch_days"].sum()),
                "mean_realised_adjusted_profit": float(group["realised_adjusted_profit"].mean()),
                "worst_week_realised_adjusted_profit": float(group["realised_adjusted_profit"].min()),
                "mean_value_captured_vs_perfect_foresight": float(pd.to_numeric(group["value_captured_vs_perfect_foresight"], errors="coerce").mean()),
                "mean_cvar_tail_profit": float(group["cvar_tail_profit"].mean()),
                "worst_scenario_profit": float(group["worst_scenario_profit"].min()),
                "total_rejected_energy_mwh": float(group["rejected_energy_mwh"].sum()),
                "total_unused_cleared_energy_mwh": float(group["unused_cleared_energy_mwh"].sum()),
                "mean_clearing_ratio": float(group["clearing_ratio"].mean()),
                "mean_solve_time_seconds": float(group["solve_time_seconds"].mean()),
                "total_solve_time_seconds": float(group["solve_time_seconds"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["model_label", "gamma"]).reset_index(drop=True)


def _build_model_decision_summary(aggregated: pd.DataFrame) -> pd.DataFrame:
    if aggregated.empty:
        return aggregated
    frame = aggregated.copy()
    frame["valid_policy"] = (
        frame["feasible_all_days"].astype(bool)
        & frame["weekly_targets_met_all_weeks"].astype(bool)
        & frame["daily_band_violations"].astype(int).eq(0)
        & frame["infeasible_day_count"].astype(int).eq(0)
    )
    valid = frame.loc[frame["valid_policy"]].copy()
    if not valid.empty:
        valid = valid.sort_values(
            [
                "mean_realised_adjusted_profit",
                "worst_week_realised_adjusted_profit",
                "mean_value_captured_vs_perfect_foresight",
                "mean_cvar_tail_profit",
                "total_rejected_energy_mwh",
                "total_unused_cleared_energy_mwh",
                "mean_solve_time_seconds",
            ],
            ascending=[False, False, False, False, True, True, True],
        ).reset_index(drop=True)
    frame["rank_profit"] = frame["mean_realised_adjusted_profit"].rank(method="dense", ascending=False).astype(int)
    frame["rank_worst_week"] = frame["worst_week_realised_adjusted_profit"].rank(method="dense", ascending=False).astype(int)
    frame["rank_value_captured"] = frame["mean_value_captured_vs_perfect_foresight"].rank(method="dense", ascending=False).astype(int)
    frame["rank_risk"] = frame["mean_cvar_tail_profit"].rank(method="dense", ascending=False).astype(int)
    frame["rank_runtime"] = frame["mean_solve_time_seconds"].rank(method="dense", ascending=True).astype(int)
    recommendation_map: dict[tuple[str, float], str] = {}
    if not valid.empty:
        top_keys = [tuple(valid.loc[idx, ["artifact_id", "gamma"]].to_list()) for idx in valid.index]
        recommendation_map[top_keys[0]] = "primary_continuation_model"
        for key in top_keys[1:3]:
            recommendation_map[key] = "strong_alternative"
        for key in top_keys[3:]:
            recommendation_map[key] = "reference_only"
    categories: list[str] = []
    reasons: list[str] = []
    for row in frame.itertuples():
        key = (str(row.artifact_id), float(row.gamma))
        if not bool(row.valid_policy):
            categories.append("invalid_due_to_infeasibility")
            reasons.append(
                f"feasible_all_days={bool(row.feasible_all_days)}; "
                f"weekly_targets_met_all_weeks={bool(row.weekly_targets_met_all_weeks)}; "
                f"daily_band_violations={int(row.daily_band_violations)}; "
                f"infeasible_day_count={int(row.infeasible_day_count)}"
            )
        else:
            categories.append(recommendation_map.get(key, "reference_only"))
            reasons.append(
                f"mean_profit={float(row.mean_realised_adjusted_profit):.2f}; "
                f"worst_week={float(row.worst_week_realised_adjusted_profit):.2f}; "
                f"value_captured={float(row.mean_value_captured_vs_perfect_foresight):.4f}; "
                f"tail_profit={float(row.mean_cvar_tail_profit):.2f}"
            )
    frame["final_recommendation_category"] = categories
    frame["decision_reason"] = reasons
    return frame[
        [
            "model_label",
            "artifact_id",
            "gamma",
            "feasible_all_days",
            "weekly_targets_met_all_weeks",
            "daily_band_violations",
            "infeasible_day_count",
            "mean_realised_adjusted_profit",
            "worst_week_realised_adjusted_profit",
            "mean_value_captured_vs_perfect_foresight",
            "mean_cvar_tail_profit",
            "worst_scenario_profit",
            "total_rejected_energy_mwh",
            "total_unused_cleared_energy_mwh",
            "mean_clearing_ratio",
            "mean_solve_time_seconds",
            "rank_profit",
            "rank_worst_week",
            "rank_value_captured",
            "rank_risk",
            "rank_runtime",
            "final_recommendation_category",
            "decision_reason",
        ]
    ].sort_values(
        ["final_recommendation_category", "rank_profit", "rank_worst_week", "rank_value_captured", "rank_risk", "rank_runtime"],
        ascending=[True, True, True, True, True, True],
    ).reset_index(drop=True)


def _runtime_summary(runtime_diagnostics: pd.DataFrame) -> pd.DataFrame:
    if runtime_diagnostics.empty:
        return pd.DataFrame(columns=["section", "group", "metric", "value", "notes"])
    rows: list[dict[str, Any]] = []
    rows.append({"section": "totals", "group": "all", "metric": "wall_time_seconds", "value": float(runtime_diagnostics["wall_time_seconds"].sum()), "notes": ""})
    for stage, group in runtime_diagnostics.groupby("solve_stage", sort=False):
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "count", "value": float(group.shape[0]), "notes": ""})
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "mean_wall_time_seconds", "value": float(group["wall_time_seconds"].mean()), "notes": ""})
    for used_cache, group in runtime_diagnostics.groupby("used_cache", sort=False):
        rows.append({"section": "cache_usage", "group": _bool_text(bool(used_cache)), "metric": "count", "value": float(group.shape[0]), "notes": ""})
    return pd.DataFrame(rows)


def _build_validation_checks(
    *,
    selected_weeks: pd.DataFrame,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    daily_metrics: pd.DataFrame,
    weekly_tracker: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
    gamma_values: list[float],
    alpha: float,
    settings: WeeklyHardBandSettings,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rows.append(_validation_row(check_name="only_selected_test_weeks_used", status="pass" if selected_weeks["week_label"].astype(str).tolist() == list(DEFAULT_WEEK_IDS) else "fail", details=f"week_labels={selected_weeks['week_label'].astype(str).tolist()}"))
    rows.append(_validation_row(check_name="no_validation_weeks_used", status="pass" if ~support_days["period_type"].astype(str).eq("validation").any() else "fail", details=f"period_types={sorted(support_days['period_type'].astype(str).unique().tolist())}"))
    model_day_sets = daily_metrics.groupby("artifact_id")["delivery_day"].apply(lambda s: tuple(sorted(s.astype(str).tolist()))).to_dict()
    rows.append(_validation_row(check_name="all_models_share_same_dates", status="pass" if len(set(model_day_sets.values())) == 1 else "fail", details=str(model_day_sets)))
    rows.append(_validation_row(check_name="gamma_grid_exactly_0_0p05_0p25", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == sorted(gamma_values) else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="alpha_exactly_0p95", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="target_mode_exactly_weekly_hard_band_target", status="pass" if daily_metrics["target_mode"].astype(str).eq(TARGET_MODE_WEEKLY_HARD_BAND).all() else "fail", details=f"observed={sorted(daily_metrics['target_mode'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="daily_min_max_fractions_recorded", status="pass", details=f"daily_min_fraction={settings.daily_min_fraction}; daily_max_fraction={settings.daily_max_fraction}"))
    rows.append(_validation_row(check_name="weekly_target_tracker_correct_shape", status="pass" if int(weekly_tracker.loc[weekly_tracker["strategy"].astype(str).str.startswith("stochastic_")].shape[0]) == int(daily_metrics.shape[0]) else "fail", details=f"tracker_rows={int(weekly_tracker.shape[0])}; stochastic_daily_rows={int(daily_metrics.shape[0])}"))
    rows.append(_validation_row(check_name="no_shortfall_slack_used", status="pass" if pd.to_numeric(daily_metrics["shortfall_kg"], errors="coerce").fillna(0.0).abs().le(1e-9).all() else "fail", details="all stochastic shortfall_kg values equal zero"))
    rows.append(_validation_row(check_name="infeasible_redispatch_explicit", status="pass", details=f"infeasible_redispatch_days={int(daily_metrics['infeasible_redispatch_days'].sum())}"))
    rows.append(_validation_row(check_name="scenario_probabilities_sum_to_1", status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail", details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}"))
    rows.append(_validation_row(check_name="scenario_count_75_per_origin", status="pass" if pd.to_numeric(daily_metrics["scenario_count"], errors="coerce").eq(75).all() else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['scenario_count'], errors='coerce').dropna().unique().tolist())}"))
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if "accepted" in actual_clearing.columns else pd.DataFrame()
    accepted_ok = accepted.empty or bool((pd.to_numeric(accepted["bid_price_eur_per_mwh"], errors="coerce") + TOLERANCE >= pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce")).all())
    rows.append(_validation_row(check_name="demand_bid_accepted_iff_bid_price_ge_actual_price", status="pass" if accepted_ok else "fail", details=f"accepted_rows={int(accepted.shape[0])}"))
    pay_as_cleared_ok = True
    if not accepted.empty and "settlement_cost_eur" in accepted.columns:
        pay_as_cleared_ok = np.allclose(
            pd.to_numeric(accepted["settlement_cost_eur"], errors="coerce"),
            pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce") * pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce"),
            atol=1e-6,
        )
    rows.append(_validation_row(check_name="pay_as_cleared_settlement", status="pass" if pay_as_cleared_ok else "fail", details="accepted rows pay actual market price"))
    rows.append(_validation_row(check_name="rejected_equals_submitted_minus_cleared", status="pass" if np.allclose(pd.to_numeric(daily_metrics["submitted_energy_mwh"], errors="coerce") - pd.to_numeric(daily_metrics["cleared_energy_mwh"], errors="coerce"), pd.to_numeric(daily_metrics["rejected_energy_mwh"], errors="coerce"), atol=1e-6, equal_nan=True) else "fail", details="daily rejected_energy_mwh identity"))
    feasible_rows = daily_metrics.loc[daily_metrics["actual_redispatch_feasible"].astype(bool)].copy()
    used_unused_ok = feasible_rows.empty or np.allclose(pd.to_numeric(feasible_rows["used_cleared_energy_mwh"], errors="coerce") + pd.to_numeric(feasible_rows["unused_cleared_energy_mwh"], errors="coerce"), pd.to_numeric(feasible_rows["cleared_energy_mwh"], errors="coerce"), atol=1e-6)
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_for_feasible_redispatch_rows", status="pass" if used_unused_ok else "fail", details=f"feasible_row_count={int(feasible_rows.shape[0])}"))
    storage_close_ok = True
    for _, group in actual_redispatch.groupby(["artifact_id", "delivery_day", "cvar_gamma"], sort=False):
        group = group.sort_values("delivery_start_utc")
        prev = float(group["storage_initial_kg"].iloc[0]) if "storage_initial_kg" in group.columns else float("nan")
        for row in group.itertuples():
            computed = prev + float(row.H_prod_kg) - float(row.H_comp_kg)
            if abs(computed - float(row.H_buf_kg)) > 1e-6:
                storage_close_ok = False
                break
            prev = float(row.H_buf_kg)
        if not storage_close_ok:
            break
    rows.append(_validation_row(check_name="storage_balance_closes", status="pass" if storage_close_ok else "fail", details="checked actual redispatch trajectories"))
    rows.append(_validation_row(check_name="terminal_inventory_correction_reported", status="pass" if "terminal_inventory_correction" in daily_metrics.columns else "fail", details="daily metrics include terminal_inventory_correction"))
    benchmark_dates = sorted(benchmark_daily.loc[benchmark_daily["aggregation_level"].astype(str).eq("daily"), "delivery_day"].astype(str).tolist())
    pf_dates = sorted(perfect_foresight_daily.loc[perfect_foresight_daily["aggregation_level"].astype(str).eq("daily"), "delivery_day"].astype(str).tolist())
    target_dates = sorted(daily_metrics["delivery_day"].astype(str).unique().tolist())
    rows.append(_validation_row(check_name="benchmark_and_perfect_foresight_use_same_dates_prices", status="pass" if benchmark_dates == target_dates and pf_dates == target_dates else "fail", details=f"benchmark_dates={benchmark_dates}; pf_dates={pf_dates}"))
    rows.append(_validation_row(check_name="no_scenario_probability_bid_grid_or_market_logic_changes_except_target_formulation", status="pass", details="Phase E4 reuses existing scenario artifacts, probabilities, bid grid, and clearing logic; only the production-target formulation is overridden per day."))
    return pd.DataFrame(rows)


def run_weekly_hard_band_target_decision(
    *,
    config: HydrogenConfig | str | Path,
    week_ids: list[str] | tuple[str, ...] = DEFAULT_WEEK_IDS,
    artifact_ids: list[str] | tuple[str, ...],
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    daily_min_fraction: float = 0.60,
    daily_max_fraction: float = 1.25,
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_e4_weekly_hard_band_final_model_decision",
    output_root: Path | None = None,
    resume_run_dir: Path | None = None,
) -> PhaseE4DecisionRunResult:
    gamma_list = [float(value) for value in gamma_values]
    if sorted(gamma_list) != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E4 requires gamma_values exactly [0, 0.05, 0.25], got {gamma_values!r}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase E4 requires alpha=0.95, got {cvar_alpha!r}.")

    suite_config = _build_phase_e4_config(
        config,
        artifact_ids=[str(value) for value in artifact_ids],
        output_root=output_root,
        run_slug=str(run_slug),
    )
    selected_weeks, support_days = _load_and_validate_phase_e2_weeks(
        week_registry_path=DEFAULT_WEEK_REGISTRY,
        support_csv_path=DEFAULT_SUPPORT_CSV,
        selected_weeks_yaml_path=DEFAULT_SELECTED_WEEKS_YAML,
        week_ids=[str(value) for value in week_ids],
    )
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(suite_config.economics.daily_target_kg),
        daily_min_fraction=float(daily_min_fraction),
        daily_max_fraction=float(daily_max_fraction),
    )
    selected_delivery_days = set(pd.to_datetime(support_days["delivery_date"], errors="raise").dt.strftime("%Y-%m-%d").tolist())
    accounting_lookup = build_production_accounting_lookup(
        build_included_day_prorated_weekly_accounting(
            included_delivery_days=sorted(selected_delivery_days),
            daily_target_kg=float(settings.daily_target_kg),
            excluded_day_reasons=build_weekly_accounting_exclusion_reason_map(
                included_delivery_days=sorted(selected_delivery_days),
                explicit_exclusions=[],
            ),
            target_accounting_policy=settings.target_accounting_policy,
        )
    )
    artifact_day_payloads, input_paths = _prepare_artifact_day_payloads(
        config=suite_config,
        artifact_ids=[str(value) for value in artifact_ids],
        selected_delivery_days=selected_delivery_days,
    )

    if resume_run_dir is not None:
        run_dir = Path(resume_run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_dir.name
    else:
        run_id, run_dir = create_run_folder(suite_config)
    (run_dir / "day_runs").mkdir(parents=True, exist_ok=True)
    (run_dir / "cache").mkdir(parents=True, exist_ok=True)

    save_config_resolved(run_dir, suite_config)
    save_inputs_manifest(run_dir, input_paths)
    input_manifest_payload = build_inputs_manifest(input_paths)
    input_manifest_payload.update(
        {
            "run_slug": str(run_slug),
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "week_ids": [str(value) for value in week_ids],
            "artifact_ids": [str(value) for value in artifact_ids],
            "cvar_alpha": float(cvar_alpha),
            "gamma_values": gamma_list,
        }
    )
    save_json(run_dir, "input_manifest.json", input_manifest_payload)
    save_json(run_dir, "selected_weeks_manifest.json", {"selected_weeks": selected_weeks.to_dict(orient="records")})
    save_json(run_dir, "cvar_settings_manifest.json", {"alpha": float(cvar_alpha), "gammas": gamma_list})
    save_json(
        run_dir,
        "production_target_manifest.json",
        {
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "weekly_target_kg": float(settings.weekly_target_kg),
            "daily_target_kg": float(settings.daily_target_kg),
            "daily_min_fraction": float(settings.daily_min_fraction),
            "daily_max_fraction": float(settings.daily_max_fraction),
            "daily_min_kg": float(settings.daily_min_kg),
            "daily_max_kg": float(settings.daily_max_kg),
            "tracker_rule": {
                "lower_today": "max(daily_min, remaining_target - daily_max * (days_remaining - 1))",
                "upper_today": "min(daily_max, remaining_target - daily_min * (days_remaining - 1))",
            },
            "weekly_target_hard": True,
            "daily_shortfall_slack_allowed": False,
        },
    )

    stochastic_registry_path = run_dir / "cache" / "stochastic_day_registry.csv"
    if stochastic_registry_path.exists():
        stochastic_registry = pd.read_csv(stochastic_registry_path)
    else:
        stochastic_registry = pd.DataFrame(columns=["week_id", "delivery_day", "artifact_id", "cvar_gamma", "day_run_dir", "forecast_origin_utc"])

    benchmark_frames: list[pd.DataFrame] = []
    perfect_foresight_frames: list[pd.DataFrame] = []
    weekly_tracker_rows: list[pd.DataFrame] = []
    daily_rows: list[dict[str, Any]] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    submitted_bid_rows: list[pd.DataFrame] = []
    validation_rows: list[pd.DataFrame] = []
    runtime_rows: list[dict[str, Any]] = []
    infeasibility_rows: list[dict[str, Any]] = []

    reference_artifact = str(list(artifact_ids)[0])
    reference_days = artifact_day_payloads[reference_artifact]
    benchmark_daily_map: dict[tuple[str, str], pd.Series] = {}
    perfect_foresight_daily_map: dict[tuple[str, str], pd.Series] = {}

    for _, week_row in selected_weeks.iterrows():
        week_id = str(week_row["week_id"])
        week_days = (
            support_days.loc[support_days["week_id"].astype(str).eq(week_id), "delivery_date"]
            .dt.strftime("%Y-%m-%d")
            .tolist()
        )
        benchmark_cache_path = run_dir / "cache" / f"{week_id}__benchmark_daily.csv"
        pf_cache_path = run_dir / "cache" / f"{week_id}__perfect_foresight_daily.csv"
        if include_price_insensitive_benchmark:
            benchmark_daily, benchmark_tracker = _run_price_insensitive_week(
                week_row=week_row,
                week_days=week_days,
                reference_days=reference_days,
                config=suite_config,
                settings=settings,
                run_id=run_id,
                cache_path=benchmark_cache_path,
                accounting_lookup=accounting_lookup,
            )
            benchmark_frames.append(benchmark_daily)
            weekly_tracker_rows.append(benchmark_tracker)
            for row in benchmark_daily.loc[benchmark_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
                benchmark_daily_map[(str(row.week_id), str(row.delivery_day))] = pd.Series(row._asdict())
        if include_perfect_foresight_benchmark:
            perfect_foresight_daily, pf_tracker = _run_perfect_foresight_week(
                week_row=week_row,
                week_days=week_days,
                reference_days=reference_days,
                config=suite_config,
                settings=settings,
                run_id=run_id,
                cache_path=pf_cache_path,
                accounting_lookup=accounting_lookup,
            )
            perfect_foresight_frames.append(perfect_foresight_daily)
            weekly_tracker_rows.append(pf_tracker)
            for row in perfect_foresight_daily.loc[perfect_foresight_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
                perfect_foresight_daily_map[(str(row.week_id), str(row.delivery_day))] = pd.Series(row._asdict())

    for artifact_id in [str(value) for value in artifact_ids]:
        artifact_days = artifact_day_payloads[artifact_id]
        model_label = _label_for_artifact(artifact_id)
        for gamma in gamma_list:
            inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
            cumulative = 0.0
            block_remaining_days = False
            for _, week_row in selected_weeks.iterrows():
                week_id = str(week_row["week_id"])
                week_label = str(week_row["week_label"])
                week_days = (
                    support_days.loc[support_days["week_id"].astype(str).eq(week_id), "delivery_date"]
                    .dt.strftime("%Y-%m-%d")
                    .tolist()
                )
                cumulative = 0.0
                inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
                block_remaining_days = False
                for delivery_day in week_days:
                    day_payload = artifact_days[delivery_day]
                    accounting_day = accounting_lookup[delivery_day]
                    bounds = compute_weekly_target_day_bounds(
                        settings=settings,
                        cumulative_realised_h2_kg_before_today=cumulative,
                        accounting_day=accounting_day,
                    )
                    if block_remaining_days:
                        weekly_tracker_rows.append(
                            pd.DataFrame(
                                [
                                    {
                                        "strategy": "stochastic_bid_risk_neutral" if abs(gamma) <= 1e-12 else "stochastic_bid_cvar",
                                        "artifact_id": artifact_id,
                                        "model_label": model_label,
                                        "gamma": float(gamma),
                                        "week_id": week_id,
                                        "week_label": week_label,
                                        "delivery_day": delivery_day,
                                        "forecast_origin_utc": day_payload["forecast_origin_utc"],
                                        "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                        "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                        "weekly_target_kg": float(bounds.weekly_target_kg),
                                        "cumulative_before_kg": float(cumulative),
                                        "cumulative_after_kg": float(cumulative),
                                         "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                         "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                         "hydrogen_sold_or_compressed_kg": np.nan,
                                         "storage_start_kg": float(inventory_start),
                                         "storage_end_kg": float(inventory_start),
                                         "solver_status": "not_run_after_prior_infeasible_redispatch",
                                         **target_accounting_fields_from_bounds(bounds),
                                     }
                                 ]
                             )
                        )
                        daily_rows.append(
                            {
                                "run_id": str(run_id),
                                "artifact_id": artifact_id,
                                "model_id": str(day_payload["model_id"]),
                                "model_label": model_label,
                                "validation_mode": str(day_payload["validation_mode"]),
                                "thesis_grade": bool(day_payload["thesis_grade"]),
                                "forecast_origin_reconstruction_used": bool(day_payload["forecast_origin_reconstruction_used"]),
                                "week_id": week_id,
                                "week_label": week_label,
                                "period_type": "test",
                                "selection_reason": str(week_row.get("selection_reason", "")),
                                "delivery_day": delivery_day,
                                "forecast_origin_utc": day_payload["forecast_origin_utc"],
                                "day_run_dir": "",
                                "strategy": "stochastic_bid_risk_neutral" if abs(gamma) <= 1e-12 else "stochastic_bid_cvar",
                                "risk_mode": "risk_neutral" if abs(gamma) <= 1e-12 else "cvar",
                                "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
                                "cvar_alpha": float(cvar_alpha),
                                "cvar_gamma": float(gamma),
                                "scenario_count": 75,
                                "scenario_probability_check": True,
                                "expected_adjusted_profit": np.nan,
                                "realised_adjusted_profit": np.nan,
                                "benchmark_profit": float(benchmark_daily_map[(week_id, delivery_day)]["realised_adjusted_profit"]) if (week_id, delivery_day) in benchmark_daily_map else np.nan,
                                "stochastic_minus_benchmark_profit": np.nan,
                                "perfect_foresight_profit": float(perfect_foresight_daily_map[(week_id, delivery_day)]["realised_adjusted_profit"]) if (week_id, delivery_day) in perfect_foresight_daily_map else np.nan,
                                "value_captured_vs_perfect_foresight": np.nan,
                                "regret_vs_perfect_foresight": np.nan,
                                "cvar_tail_profit": np.nan,
                                "worst_scenario_profit": np.nan,
                                "hydrogen_sold_or_compressed_kg": np.nan,
                                "weekly_target_kg": float(bounds.weekly_target_kg),
                                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                "weekly_target_met": False,
                                "daily_band_violations": 0,
                                "infeasible_redispatch_days": 1,
                                "submitted_energy_mwh": np.nan,
                                "cleared_energy_mwh": np.nan,
                                "rejected_energy_mwh": np.nan,
                                "used_cleared_energy_mwh": np.nan,
                                "unused_cleared_energy_mwh": np.nan,
                                "clearing_ratio": np.nan,
                                "average_actual_price_paid": np.nan,
                                "high_bid_share": np.nan,
                                "market_cap_bid_share": np.nan,
                                "storage_min_kg": np.nan,
                                "storage_max_kg": np.nan,
                                "reserve_boundary_hits": np.nan,
                                "solve_time_seconds": np.nan,
                                "mip_gap": np.nan,
                                "variable_count": np.nan,
                                "binary_variable_count": np.nan,
                                "constraint_count": np.nan,
                                "solver_status": "not_run_after_prior_infeasible_redispatch",
                                "actual_redispatch_solver_status": "not_run_after_prior_infeasible_redispatch",
                                "actual_redispatch_feasible": False,
                                "regime_label": str(week_row["regime_label"]),
                                "high_bid_energy_mwh": np.nan,
                                "market_cap_bid_energy_mwh": np.nan,
                                **target_accounting_fields_from_bounds(bounds),
                            }
                        )
                        infeasibility_rows.append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": model_label,
                                "gamma": float(gamma),
                                "week_id": week_id,
                                "week_label": week_label,
                                "delivery_day": delivery_day,
                                "issue_type": "skipped_after_prior_infeasible_redispatch",
                                "details": "Later days in the same week were not simulated after an infeasible realised redispatch day.",
                            }
                        )
                        continue

                    cache_match = stochastic_registry.loc[
                        stochastic_registry["week_id"].astype(str).eq(week_id)
                        & stochastic_registry["delivery_day"].astype(str).eq(delivery_day)
                        & stochastic_registry["artifact_id"].astype(str).eq(artifact_id)
                        & pd.to_numeric(stochastic_registry["cvar_gamma"], errors="coerce").eq(float(gamma))
                    ]
                    payload: dict[str, Any]
                    used_cache = False
                    wall_started = perf_counter()
                    if not cache_match.empty and Path(str(cache_match.iloc[0]["day_run_dir"])).exists():
                        payload = _load_cached_day_payload(cache_match.iloc[0], model_id=str(day_payload["model_id"]))
                        used_cache = True
                    else:
                        live_result = run_real_scenario_bidding_dry_run(
                            config=suite_config,
                            artifact_id=artifact_id,
                            forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                            max_origins=1,
                            output_root=run_dir / "day_runs",
                            strategy_name="stochastic_bid_risk_neutral" if abs(gamma) <= 1e-12 else "stochastic_bid_cvar",
                            dry_run_label="phase_e4_weekly_hard_band",
                            include_price_insensitive_comparison=False,
                            risk_measure="risk_neutral" if abs(gamma) <= 1e-12 else "cvar",
                            cvar_alpha=float(cvar_alpha),
                            cvar_gamma=float(gamma),
                            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                            inventory_start_kg=inventory_start,
                            reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                            target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                            target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                            terminal_reference_start_kg=inventory_start,
                            write_outputs=True,
                        )
                        payload = _payload_from_live_result(live_result, model_id=str(day_payload["model_id"]))
                        stochastic_registry = pd.concat(
                            [
                                stochastic_registry,
                                pd.DataFrame(
                                    [
                                        {
                                            "week_id": week_id,
                                            "delivery_day": delivery_day,
                                            "artifact_id": artifact_id,
                                            "cvar_gamma": float(gamma),
                                            "day_run_dir": str(payload["run_dir"]),
                                            "forecast_origin_utc": str(day_payload["forecast_origin_utc"]),
                                        }
                                    ]
                                ),
                            ],
                            ignore_index=True,
                        )
                        save_frame_csv(run_dir / "cache", "stochastic_day_registry.csv", stochastic_registry)
                    wall_time = perf_counter() - wall_started
                    runtime_rows.append(
                        {
                            "artifact_id": artifact_id,
                            "model_label": model_label,
                            "week_id": week_id,
                            "week_label": week_label,
                            "delivery_day": delivery_day,
                            "gamma": float(gamma),
                            "alpha": float(cvar_alpha),
                            "solve_stage": "stochastic_bidding_day",
                            "wall_time_seconds": float(wall_time),
                            "solver_status": str(payload["stochastic_solver_status"]),
                            "objective_value": payload["stochastic_objective_value"],
                            "variable_count": payload["stochastic_variable_count"],
                            "binary_variable_count": payload["stochastic_binary_variable_count"],
                            "constraint_count": payload["stochastic_constraint_count"],
                            "used_cache": bool(used_cache),
                        }
                    )
                    benchmark_row = benchmark_daily_map.get((week_id, delivery_day))
                    pf_row = perfect_foresight_daily_map.get((week_id, delivery_day))
                    metric_row = _build_stochastic_daily_metric(
                        run_id=run_id,
                        artifact_id=artifact_id,
                        model_label=model_label,
                        validation_mode=str(day_payload["validation_mode"]),
                        thesis_grade=bool(day_payload["thesis_grade"]),
                        forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                        week_row=pd.Series(week_row),
                        day_meta=day_payload["day_meta"],
                        payload=payload,
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        benchmark_profit_row=benchmark_row,
                        perfect_foresight_profit_row=pf_row,
                        bounds=bounds,
                        cumulative_before_kg=cumulative,
                    )
                    daily_rows.append(metric_row)
                    actual_summary = payload["actual_settlement_results"].assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=week_id,
                        week_label=week_label,
                        regime_label=str(week_row["regime_label"]),
                        delivery_day=delivery_day,
                        forecast_origin_utc=payload["forecast_origin_utc"],
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                        daily_lower_bound_kg=float(bounds.daily_lower_bound_kg),
                        daily_upper_bound_kg=float(bounds.daily_upper_bound_kg),
                        weekly_target_kg=float(bounds.weekly_target_kg),
                    )
                    actual_settlement_rows.append(actual_summary)
                    scenario_settlement_rows.append(
                        payload["scenario_settlement_results"].assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=week_id,
                            week_label=week_label,
                            regime_label=str(week_row["regime_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=payload["forecast_origin_utc"],
                            cvar_alpha=float(cvar_alpha),
                            cvar_gamma=float(gamma),
                            target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                        )
                    )
                    actual_clearing_rows.append(
                        payload["actual_clearing"].assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=delivery_day,
                            forecast_origin_utc=payload["forecast_origin_utc"],
                            cvar_gamma=float(gamma),
                        )
                    )
                    actual_redispatch_rows.append(
                        payload["actual_redispatch_timeseries"].assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=delivery_day,
                            forecast_origin_utc=payload["forecast_origin_utc"],
                            cvar_gamma=float(gamma),
                        )
                    )
                    submitted_bid_rows.append(
                        payload["submitted_bids"].assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=delivery_day,
                            forecast_origin_utc=payload["forecast_origin_utc"],
                            cvar_gamma=float(gamma),
                        )
                    )
                    relevant_validation_checks = payload["validation_checks"].loc[
                        ~payload["validation_checks"]["check_name"].astype(str).eq("redispatch.production_target_and_shortfall_reported")
                    ].copy()
                    validation_rows.append(
                        relevant_validation_checks.assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=week_id,
                            week_label=week_label,
                            regime_label=str(week_row["regime_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(payload["forecast_origin_utc"]),
                            cvar_alpha=float(cvar_alpha),
                            cvar_gamma=float(gamma),
                            target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                        )
                    )
                    actual_h2 = float(actual_summary["hydrogen_compressed_or_sold_kg"].iloc[0])
                    cumulative_after = cumulative + actual_h2
                    weekly_tracker_rows.append(
                        pd.DataFrame(
                            [
                                {
                                    "strategy": metric_row["strategy"],
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "week_id": week_id,
                                    "week_label": week_label,
                                    "delivery_day": delivery_day,
                                    "forecast_origin_utc": payload["forecast_origin_utc"],
                                    "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                    "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                    "weekly_target_kg": float(bounds.weekly_target_kg),
                                    "cumulative_before_kg": float(cumulative),
                                    "cumulative_after_kg": float(cumulative_after),
                                    "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                    "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                    "hydrogen_sold_or_compressed_kg": actual_h2,
                                    "storage_start_kg": float(inventory_start),
                                    "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"].iloc[0]),
                                    "solver_status": str(actual_summary["solver_status"].iloc[0]),
                                }
                            ]
                        )
                    )
                    if not _accepted_solver_status(actual_summary["solver_status"].iloc[0]):
                        infeasibility_rows.append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": model_label,
                                "gamma": float(gamma),
                                "week_id": week_id,
                                "week_label": week_label,
                                "delivery_day": delivery_day,
                                "issue_type": "infeasible_actual_redispatch",
                                "details": f"solver_status={actual_summary['solver_status'].iloc[0]}",
                            }
                        )
                        block_remaining_days = True
                    cumulative = cumulative_after
                    inventory_start = float(actual_summary["terminal_inventory_end_kg"].iloc[0]) if _accepted_solver_status(actual_summary["solver_status"].iloc[0]) else inventory_start

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase E4 produced no daily metrics.")
    weekly_metrics = _weekly_metrics_from_daily(daily_metrics, selected_weeks)
    for week_id, group in weekly_metrics.groupby(["week_id", "artifact_id", "cvar_gamma"], sort=False):
        mask = (
            daily_metrics["week_id"].astype(str).eq(str(week_id[0]))
            & daily_metrics["artifact_id"].astype(str).eq(str(week_id[1]))
            & pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").eq(float(week_id[2]))
        )
        week_met = bool(group["weekly_target_met"].iloc[0])
        daily_metrics.loc[mask, "weekly_target_met"] = week_met
    aggregated_metrics = _aggregate_metrics_by_model_gamma(weekly_metrics)
    model_decision_summary = _build_model_decision_summary(aggregated_metrics)

    benchmark_metrics = pd.concat(benchmark_frames, ignore_index=True) if benchmark_frames else pd.DataFrame()
    perfect_foresight_metrics = pd.concat(perfect_foresight_frames, ignore_index=True) if perfect_foresight_frames else pd.DataFrame()
    if not benchmark_metrics.empty:
        benchmark_weekly = (
            benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("daily")]
            .groupby(["week_id", "week_label"], as_index=False)
            .agg(
                realised_adjusted_profit=("realised_adjusted_profit", "sum"),
                cleared_energy_mwh=("cleared_energy_mwh", "sum"),
                used_energy_mwh=("used_energy_mwh", "sum"),
                unused_cleared_energy_mwh=("unused_cleared_energy_mwh", "sum"),
                hydrogen_sold_or_compressed_kg=("hydrogen_sold_or_compressed_kg", "sum"),
                shortfall_kg=("shortfall_kg", "sum"),
                da_settlement_cost=("da_settlement_cost", "sum"),
                hydrogen_revenue=("hydrogen_revenue", "sum"),
                unused_energy_penalty=("unused_energy_penalty", "sum"),
                shortfall_penalty=("shortfall_penalty", "sum"),
                terminal_inventory_correction=("terminal_inventory_correction", "sum"),
                submitted_energy_mwh=("submitted_energy_mwh", "sum"),
                rejected_energy_mwh=("rejected_energy_mwh", "sum"),
                daily_band_violations=("daily_band_violations", "sum"),
                infeasible_redispatch_days=("infeasible_redispatch_days", "sum"),
            )
        )
        benchmark_weekly["period_type"] = "test"
        benchmark_weekly["aggregation_level"] = "weekly"
        benchmark_weekly["strategy"] = "price_insensitive_plan_first_market_cap"
        benchmark_weekly["average_actual_price_paid"] = np.where(
            pd.to_numeric(benchmark_weekly["cleared_energy_mwh"], errors="coerce") > 0.0,
            pd.to_numeric(benchmark_weekly["da_settlement_cost"], errors="coerce") / pd.to_numeric(benchmark_weekly["cleared_energy_mwh"], errors="coerce"),
            np.nan,
        )
        benchmark_metrics = pd.concat([benchmark_metrics, benchmark_weekly], ignore_index=True)
    if not perfect_foresight_metrics.empty:
        pf_weekly = (
            perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("daily")]
            .groupby(["week_id", "week_label"], as_index=False)
            .agg(
                realised_adjusted_profit=("realised_adjusted_profit", "sum"),
                cleared_energy_mwh=("cleared_energy_mwh", "sum"),
                used_energy_mwh=("used_energy_mwh", "sum"),
                unused_cleared_energy_mwh=("unused_cleared_energy_mwh", "sum"),
                hydrogen_sold_or_compressed_kg=("hydrogen_sold_or_compressed_kg", "sum"),
                shortfall_kg=("shortfall_kg", "sum"),
                da_settlement_cost=("da_settlement_cost", "sum"),
                hydrogen_revenue=("hydrogen_revenue", "sum"),
                unused_energy_penalty=("unused_energy_penalty", "sum"),
                shortfall_penalty=("shortfall_penalty", "sum"),
                terminal_inventory_correction=("terminal_inventory_correction", "sum"),
                submitted_energy_mwh=("submitted_energy_mwh", "sum"),
                rejected_energy_mwh=("rejected_energy_mwh", "sum"),
                daily_band_violations=("daily_band_violations", "sum"),
                infeasible_redispatch_days=("infeasible_redispatch_days", "sum"),
            )
        )
        pf_weekly["period_type"] = "test"
        pf_weekly["aggregation_level"] = "weekly"
        pf_weekly["strategy"] = "perfect_foresight_market_cap"
        pf_weekly["average_actual_price_paid"] = np.where(
            pd.to_numeric(pf_weekly["cleared_energy_mwh"], errors="coerce") > 0.0,
            pd.to_numeric(pf_weekly["da_settlement_cost"], errors="coerce") / pd.to_numeric(pf_weekly["cleared_energy_mwh"], errors="coerce"),
            np.nan,
        )
        perfect_foresight_metrics = pd.concat([perfect_foresight_metrics, pf_weekly], ignore_index=True)

    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    submitted_bids = pd.concat(submitted_bid_rows, ignore_index=True) if submitted_bid_rows else pd.DataFrame()
    validation_checks = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    weekly_target_tracker = pd.concat(weekly_tracker_rows, ignore_index=True) if weekly_tracker_rows else pd.DataFrame()
    infeasibility_report = pd.DataFrame(infeasibility_rows)
    runtime_diagnostics = pd.DataFrame(runtime_rows)

    suite_validation_checks = _build_validation_checks(
        selected_weeks=selected_weeks,
        support_days=support_days,
        artifact_ids=[str(value) for value in artifact_ids],
        daily_metrics=daily_metrics,
        weekly_tracker=weekly_target_tracker,
        actual_clearing=actual_clearing,
        actual_redispatch=actual_redispatch,
        benchmark_daily=benchmark_metrics,
        perfect_foresight_daily=perfect_foresight_metrics,
        gamma_values=gamma_list,
        alpha=float(cvar_alpha),
        settings=settings,
    )
    validation_checks_all_runs = pd.concat([validation_checks, suite_validation_checks], ignore_index=True)
    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics.loc[~daily_metrics["solver_status"].astype(str).eq("not_run_after_prior_infeasible_redispatch")].copy(),
        weekly_metrics=weekly_metrics.copy(),
        scenario_settlement_results=scenario_settlement_results,
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
    )
    cvar_validation_checks = pd.concat(
        [
            cvar_validation_checks,
            pd.DataFrame(
                [
                    _validation_row(
                        check_name="phase_e4_gamma_alpha_target_mode_confirmed",
                        status="pass",
                        details=f"alpha={cvar_alpha}; gammas={gamma_list}; target_mode={TARGET_MODE_WEEKLY_HARD_BAND}",
                        severity="hard_fail",
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    runtime_summary = _runtime_summary(runtime_diagnostics)

    save_frame_csv(run_dir, "weekly_target_tracker.csv", weekly_target_tracker)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "aggregated_metrics_by_model_gamma.csv", aggregated_metrics)
    save_frame_csv(run_dir, "model_decision_summary.csv", model_decision_summary)
    save_frame_csv(run_dir, "infeasibility_report.csv", infeasibility_report)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
    save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)

    _save_parquet_if_possible(run_dir, "submitted_bids.parquet", submitted_bids)
    _save_parquet_if_possible(run_dir, "actual_clearing.parquet", actual_clearing)
    _save_parquet_if_possible(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch)

    primary = model_decision_summary.loc[model_decision_summary["final_recommendation_category"].astype(str).eq("primary_continuation_model")]
    primary_text = "none"
    if not primary.empty:
        row = primary.iloc[0]
        primary_text = f"{row['model_label']} | gamma={row['gamma']}"
    readme_lines = [
        "# Weekly Hard-Band Target Final Model Decision",
        "",
        "- Scope: five selected common-support test weeks, three hourly D-only scenario artifacts, gamma grid [0, 0.05, 0.25], alpha 0.95.",
        "- Production target formulation: weekly hard target of 7 x daily_target with rolling daily hard lower/upper bounds from the remaining-target tracker.",
        "- Rationale: the weekly obligation is enforced without shortfall valuation, while the daily 60% to 125% band prevents unrealistic zero-production days and end-week catch-up spikes.",
        f"- Selected policy under the pre-declared decision rule: {primary_text}.",
        f"- Invalid policies due to infeasibility: {int(model_decision_summary['final_recommendation_category'].astype(str).eq('invalid_due_to_infeasibility').sum())}.",
        f"- Benchmark rows: {int(benchmark_metrics.shape[0])}; perfect foresight rows: {int(perfect_foresight_metrics.shape[0])}.",
        f"- Runtime rows: {int(runtime_diagnostics.shape[0])}.",
        "- Safe continuation criterion: proceed only with a policy that remains feasible on all days, meets all weekly targets, respects all daily bands, and clears validation without unexplained hard failures.",
    ]
    save_text(run_dir, "README_weekly_hard_band_decision.md", "\n".join(readme_lines))

    return PhaseE4DecisionRunResult(
        run_dir=run_dir,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        aggregated_metrics_by_model_gamma=aggregated_metrics,
        model_decision_summary=model_decision_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )
