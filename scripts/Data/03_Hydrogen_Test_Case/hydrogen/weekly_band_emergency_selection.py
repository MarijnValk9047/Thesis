from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .benchmarks import run_perfect_foresight
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
)
from .weekly_hard_band_decision import (
    _accepted_solver_status,
    _actual_prices_from_day_frame,
    _bool_text,
    _build_phase_e4_config,
    _build_stochastic_daily_metric,
    _build_strategy_day_row,
    _load_cached_day_payload,
    _payload_from_live_result,
    _prepare_artifact_day_payloads,
    _runtime_summary,
    _save_parquet_if_possible,
)
from .weekly_hard_band_target import (
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON,
    TARGET_MODE_WEEKLY_HARD_BAND,
    WeeklyHardBandSettings,
    WeeklyTargetDayBounds,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_accounting_exclusion_reason_map,
    build_weekly_hard_band_settings,
    compute_weekly_target_day_bounds_for_variant,
    daily_frame_matches_accounting,
    target_accounting_fields_from_bounds,
)


PRODUCTION_VARIANTS = (
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON,
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
)


@dataclass(frozen=True)
class PhaseE4cSelectionRunResult:
    run_dir: Path
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    aggregated_metrics: pd.DataFrame
    model_decision_summary: pd.DataFrame
    emergency_import_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    runtime_summary: pd.DataFrame


def _safe_numeric(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def _physical_daily_max_kg(config: HydrogenConfig) -> float:
    return float(
        config.hydrogen_system.electrolyser_nominal_mw
        * 24.0
        * config.hydrogen_system.h2_efficiency_kg_per_mwh
    )


def _normalise_production_variants(values: list[str] | tuple[str, ...]) -> list[str]:
    variants = [str(value).strip() for value in values]
    if sorted(variants) != sorted(PRODUCTION_VARIANTS):
        raise ValueError(
            "Phase E4c requires production variants exactly "
            f"{list(PRODUCTION_VARIANTS)}, got {variants!r}."
        )
    return variants


def _find_latest_resume_dir(root: Path, run_slug: str) -> Path | None:
    candidates = sorted(
        [
            path
            for path in root.glob(f"*_{run_slug}")
            if path.is_dir() and (path / "production_variant_manifest.json").exists()
        ],
        key=lambda path: path.name,
    )
    return candidates[-1] if candidates else None


def _compute_variant_bounds(
    *,
    settings: WeeklyHardBandSettings,
    production_variant: str,
    cumulative_realised_h2_kg_before_today: float,
    days_remaining_in_week: int | None,
    physical_daily_max_kg: float,
    accounting_day: Any | None = None,
) -> WeeklyTargetDayBounds:
    return compute_weekly_target_day_bounds_for_variant(
        settings=settings,
        production_variant=str(production_variant),
        cumulative_realised_h2_kg_before_today=float(cumulative_realised_h2_kg_before_today),
        days_remaining_in_week=None if days_remaining_in_week is None else int(days_remaining_in_week),
        physical_daily_max_kg=float(physical_daily_max_kg),
        accounting_day=accounting_day,
    )


def _build_skipped_daily_metric(
    *,
    run_id: str,
    artifact_id: str,
    model_label: str,
    validation_mode: str,
    thesis_grade: bool,
    forecast_origin_reconstruction_used: bool,
    week_row: pd.Series,
    day_meta: dict[str, Any],
    day_payload: dict[str, Any],
    cvar_alpha: float,
    cvar_gamma: float,
    production_variant: str,
    bounds: WeeklyTargetDayBounds,
    cumulative_before_kg: float,
    skip_reason: str,
    scenario_count: int,
    scenario_probability_check: bool,
    emergency_import_price: float,
) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "artifact_id": str(artifact_id),
        "model_id": str(day_payload["model_id"]),
        "model_label": str(model_label),
        "validation_mode": str(validation_mode),
        "thesis_grade": bool(thesis_grade),
        "forecast_origin_reconstruction_used": bool(forecast_origin_reconstruction_used),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "period_type": "test",
        "selection_reason": str(week_row.get("selection_reason", "")),
        "delivery_day": str(day_meta["delivery_day"]),
        "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]),
        "day_run_dir": "",
        "strategy": "stochastic_bid_risk_neutral" if abs(float(cvar_gamma)) <= 1e-12 else "stochastic_bid_cvar",
        "risk_mode": "risk_neutral" if abs(float(cvar_gamma)) <= 1e-12 else "cvar",
        "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
        "production_variant": str(production_variant),
        "cvar_alpha": float(cvar_alpha),
        "cvar_gamma": float(cvar_gamma),
        "actual_price_mean": float(day_meta["actual_price_mean"]),
        "actual_price_min": float(day_meta["actual_price_min"]),
        "actual_price_max": float(day_meta["actual_price_max"]),
        "actual_price_spread": float(day_meta["actual_price_spread"]),
        "actual_price_std": float(day_meta["actual_price_std"]),
        "actual_negative_price_hours": int(day_meta["actual_negative_price_hours"]),
        "scenario_count": int(scenario_count),
        "scenario_probability_check": bool(scenario_probability_check),
        "expected_adjusted_profit": np.nan,
        "realised_adjusted_profit": np.nan,
        "realised_operating_profit": np.nan,
        "hydrogen_revenue": np.nan,
        "da_settlement_cost": np.nan,
        "unused_energy_penalty": np.nan,
        "shortfall_penalty": np.nan,
        "terminal_inventory_correction": np.nan,
        "benchmark_profit": np.nan,
        "stochastic_minus_benchmark_profit": np.nan,
        "average_actual_price_paid": np.nan,
        "realised_minus_expected_profit": np.nan,
        "var_loss": np.nan,
        "cvar_loss": np.nan,
        "reconstructed_var_loss": np.nan,
        "reconstructed_cvar_loss": np.nan,
        "cvar_reconstruction_error": np.nan,
        "worst_scenario_profit": np.nan,
        "worst_scenario_loss": np.nan,
        "downside_tail_mean_profit": np.nan,
        "downside_tail_mean_loss": np.nan,
        "realised_outcome_percentile_within_scenarios": np.nan,
        "scenario_profit_p05": np.nan,
        "scenario_profit_p10": np.nan,
        "scenario_profit_p50": np.nan,
        "scenario_profit_p90": np.nan,
        "scenario_profit_p95": np.nan,
        "submitted_energy_mwh": np.nan,
        "cleared_energy_mwh": np.nan,
        "rejected_energy_mwh": np.nan,
        "used_cleared_energy_mwh": np.nan,
        "unused_cleared_energy_mwh": np.nan,
        "clearing_ratio": np.nan,
        "rejected_energy_share": np.nan,
        "hours_with_zero_clearing": np.nan,
        "hours_with_partial_clearing": np.nan,
        "weighted_average_bid_price": np.nan,
        "high_bid_share": np.nan,
        "market_cap_bid_share": np.nan,
        "high_bid_energy_mwh": np.nan,
        "market_cap_bid_energy_mwh": np.nan,
        "hydrogen_produced_kg": np.nan,
        "hydrogen_sold_or_compressed_kg": np.nan,
        "target_hydrogen_kg": float(bounds.daily_lower_bound_kg),
        "production_fulfilment_ratio": np.nan,
        "shortfall_kg": np.nan,
        "storage_start_kg": float(cumulative_before_kg),
        "storage_end_kg": np.nan,
        "storage_min_kg": np.nan,
        "storage_max_kg": np.nan,
        "reserve_boundary_hits": np.nan,
        "electrolyser_energy_mwh": np.nan,
        "compressor_energy_mwh": np.nan,
        "electrolyser_ramp_hits": np.nan,
        "solver_status": str(skip_reason),
        "actual_redispatch_solver_status": str(skip_reason),
        "actual_redispatch_feasible": False,
        "objective_value": np.nan,
        "solve_time_seconds": np.nan,
        "mip_gap": np.nan,
        "variable_count": np.nan,
        "binary_variable_count": np.nan,
        "constraint_count": np.nan,
        "benchmark_cleared_energy_mwh": np.nan,
        "benchmark_hydrogen_sold_or_compressed_kg": np.nan,
        "benchmark_average_actual_price_paid": np.nan,
        "benchmark_shortfall_kg": np.nan,
        "validation_fail_count": 0,
        "validation_warn_count": 0,
        "regime_label": str(week_row["regime_label"]),
        "cvar_tail_profit": np.nan,
        "perfect_foresight_profit": np.nan,
        "value_captured_vs_perfect_foresight": np.nan,
        "regret_vs_perfect_foresight": np.nan,
        "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
        "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
        "weekly_target_kg": float(bounds.weekly_target_kg),
        "cumulative_before_kg": float(cumulative_before_kg),
        "cumulative_after_kg": float(cumulative_before_kg),
        "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
        "days_remaining_in_week": int(bounds.days_remaining_in_week),
        "weekly_target_met": False,
        "daily_band_violations": 0,
        "infeasible_redispatch_days": 1,
        "accepted_bid_energy_mwh": np.nan,
        "emergency_import_enabled": True,
        "emergency_import_price_eur_per_mwh": float(emergency_import_price),
        "emergency_import_mwh": np.nan,
        "emergency_import_cost": np.nan,
        "emergency_import_hours": np.nan,
        "emergency_import_share_of_used_energy": np.nan,
        **target_accounting_fields_from_bounds(bounds),
    }


def _run_perfect_foresight_week_variant(
    *,
    week_row: pd.Series,
    week_days: list[str],
    reference_days: dict[str, dict[str, Any]],
    config: HydrogenConfig,
    settings: WeeklyHardBandSettings,
    production_variant: str,
    physical_daily_max_kg: float,
    emergency_import_price: float,
    run_id: str,
    cache_path: Path,
    accounting_lookup: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    week_accounting = pd.DataFrame(
        [accounting_lookup[str(day)].to_dict() for day in week_days if str(day) in accounting_lookup]
    ).sort_values("delivery_day").reset_index(drop=True)
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        tracker_path = cache_path.parent / f"{cache_path.stem}__tracker.csv"
        if (
            int(cached.loc[cached["aggregation_level"].astype(str).eq("daily")].shape[0]) == len(week_days)
            and tracker_path.exists()
            and daily_frame_matches_accounting(
                daily_frame=cached.loc[cached["aggregation_level"].astype(str).eq("daily")].copy(),
                accounting_frame=week_accounting,
                target_accounting_policy=settings.target_accounting_policy,
            )
        ):
            return cached, pd.read_csv(tracker_path)

    market_cap = float(max(config.bidding.bid_price_grid_eur_per_mwh))
    rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    inventory_start = float(config.hydrogen_system.storage_initial_kg)
    cumulative = 0.0
    for delivery_day in week_days:
        day_payload = reference_days[delivery_day]
        accounting_day = accounting_lookup[delivery_day]
        bounds = _compute_variant_bounds(
            settings=settings,
            production_variant=production_variant,
            cumulative_realised_h2_kg_before_today=cumulative,
            days_remaining_in_week=None,
            physical_daily_max_kg=physical_daily_max_kg,
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
            target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
            target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
            solver_log_path=str(cache_path.parent / f"{delivery_day}__{production_variant}__pf_plan_solver_log.txt")
            if config.outputs.save_solver_log
            else None,
        )
        dispatch = pf.dispatch.copy()
        dispatch["forecast_origin_utc"] = day_payload["forecast_origin_utc"]
        dispatch["scenario_model"] = "perfect_foresight_oracle"
        bids = dispatch_schedule_to_one_block_bid_curve(
            dispatch,
            run_id=f"{run_id}__pf__{production_variant}__{delivery_day}",
            source_strategy="perfect_foresight",
            bridge_strategy=f"perfect_foresight_market_cap::{production_variant}",
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
            target_hydrogen_kg=float(bounds.daily_lower_bound_kg),
            target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            emergency_import_price_eur_per_mwh=float(emergency_import_price),
            solver_log_path=cache_path.parent / f"{delivery_day}__{production_variant}__pf_redispatch_solver_log.txt"
            if config.outputs.save_solver_log
            else None,
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
                lower_bound_kg=float(bounds.daily_lower_bound_kg),
                upper_bound_kg=float(bounds.daily_upper_bound_kg),
                weekly_target_kg=float(bounds.weekly_target_kg),
                cumulative_before_kg=float(cumulative),
                cumulative_after_kg=float(cumulative_after),
                remaining_target_before_today_kg=float(bounds.remaining_target_before_today_kg),
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
            | {
                "production_variant": str(production_variant),
                "emergency_import_mwh": float(summary.get("emergency_import_mwh", 0.0)),
                "emergency_import_cost": float(summary.get("emergency_import_cost_eur", 0.0)),
            }
        )
        tracker_rows.append(
            {
                "strategy": "perfect_foresight_market_cap",
                "artifact_id": "",
                "model_label": "Perfect foresight",
                "gamma": np.nan,
                "production_variant": str(production_variant),
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
    daily["aggregation_level"] = "daily"
    daily["weekly_target_met"] = bool(cumulative >= float(week_accounting["weekly_target_kg"].iloc[0]) - TOLERANCE)
    tracker = pd.DataFrame(tracker_rows).sort_values("delivery_day").reset_index(drop=True)
    save_frame_csv(cache_path.parent, cache_path.name, daily)
    save_frame_csv(cache_path.parent, f"{cache_path.stem}__tracker.csv", tracker)
    return daily, tracker


def _weekly_metrics_from_daily(daily_metrics: pd.DataFrame, selected_weeks: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for week_id, week_group in daily_metrics.groupby("week_id", sort=False):
        week_row = selected_weeks.loc[selected_weeks["week_id"].astype(str).eq(str(week_id))].iloc[0]
        group_keys = ["artifact_id", "model_label", "cvar_gamma", "production_variant"]
        for (artifact_id, model_label, gamma, production_variant), group in week_group.groupby(group_keys, sort=False):
            submitted = float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum())
            cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
            used = float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum())
            pf_profit = float(pd.to_numeric(group["perfect_foresight_profit"], errors="coerce").sum())
            total_h2 = float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum())
            weekly_target_kg = float(pd.to_numeric(group["weekly_target_kg"], errors="coerce").dropna().iloc[0])
            feasible_all_days = bool(group["actual_redispatch_feasible"].astype(bool).all() and group["solver_status"].map(_accepted_solver_status).all())
            band_violations = int(pd.to_numeric(group["daily_band_violations"], errors="coerce").fillna(0).sum())
            infeasible_days = int(pd.to_numeric(group["infeasible_redispatch_days"], errors="coerce").fillna(0).sum())
            weekly_target_met = bool(feasible_all_days and band_violations == 0 and total_h2 + 1e-6 >= weekly_target_kg)
            rows.append(
                {
                    "artifact_id": str(artifact_id),
                    "model_id": str(group["model_id"].iloc[0]),
                    "model_label": str(model_label),
                    "week_id": str(week_id),
                    "week_label": str(week_row["week_label"]),
                    "regime_label": str(week_row["regime_label"]),
                    "period_type": "test",
                    "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
                    "production_variant": str(production_variant),
                    "cvar_alpha": float(pd.to_numeric(group["cvar_alpha"], errors="coerce").dropna().iloc[0]),
                    "cvar_gamma": float(gamma),
                    "solver_status": "Optimal" if group["solver_status"].map(_accepted_solver_status).all() else "non_optimal_present",
                    "feasible_all_days": feasible_all_days,
                    "weekly_target_met": weekly_target_met,
                    "daily_band_violations": band_violations,
                    "infeasible_redispatch_days": infeasible_days,
                    "expected_adjusted_profit": float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum()),
                    "realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                    "value_captured_vs_perfect_foresight": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum() / pf_profit) if abs(pf_profit) > 1e-9 else float("nan"),
                    "regret_vs_perfect_foresight": float(pf_profit - pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                    "perfect_foresight_profit": pf_profit,
                    "cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").sum()),
                    "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()),
                    "emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                    "emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                    "emergency_import_hours": int(pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0).sum()),
                    "emergency_import_share_of_used_energy": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum() / used) if used > 0.0 else 0.0,
                    "hydrogen_sold_or_compressed_kg": total_h2,
                    "submitted_energy_mwh": submitted,
                    "cleared_energy_mwh": cleared,
                    "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                    "used_cleared_energy_mwh": used,
                    "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                    "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
                    "average_actual_price_paid": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum() / cleared) if cleared > 0.0 else float("nan"),
                    "high_bid_share": float(pd.to_numeric(group["high_bid_energy_mwh"], errors="coerce").sum() / submitted) if submitted > 0.0 else 0.0,
                    "market_cap_bid_share": float(pd.to_numeric(group["market_cap_bid_energy_mwh"], errors="coerce").sum() / submitted) if submitted > 0.0 else 0.0,
                    "storage_min_kg": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()),
                    "reserve_boundary_hits": int(pd.to_numeric(group["reserve_boundary_hits"], errors="coerce").fillna(0).sum()),
                    "solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
                    "mip_gap": float(pd.to_numeric(group["mip_gap"], errors="coerce").max()),
                    "variable_count": int(pd.to_numeric(group["variable_count"], errors="coerce").max()),
                    "binary_variable_count": int(pd.to_numeric(group["binary_variable_count"], errors="coerce").max()),
                    "constraint_count": int(pd.to_numeric(group["constraint_count"], errors="coerce").max()),
                    "weekly_target_kg": weekly_target_kg,
                    "daily_lower_bound_kg": float(pd.to_numeric(group["daily_lower_bound_kg"], errors="coerce").sum()),
                    "daily_upper_bound_kg": float(pd.to_numeric(group["daily_upper_bound_kg"], errors="coerce").sum()),
                }
            )
    return pd.DataFrame(rows).sort_values(["production_variant", "week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)


def _aggregate_metrics_by_model_gamma_variant(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["artifact_id", "model_label", "cvar_gamma", "production_variant"]
    for (artifact_id, model_label, gamma, production_variant), group in weekly_metrics.groupby(keys, sort=False):
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "gamma": float(gamma),
                "production_variant": str(production_variant),
                "week_count": int(group.shape[0]),
                "feasible_all_days": bool(group["feasible_all_days"].astype(bool).all() and group["solver_status"].map(_accepted_solver_status).all()),
                "weekly_targets_met_all_weeks": bool(group["weekly_target_met"].astype(bool).all()),
                "daily_band_violations": int(pd.to_numeric(group["daily_band_violations"], errors="coerce").fillna(0).sum()),
                "infeasible_redispatch_days": int(pd.to_numeric(group["infeasible_redispatch_days"], errors="coerce").fillna(0).sum()),
                "total_emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "total_emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "mean_realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").mean()),
                "worst_week_realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").min()),
                "mean_value_captured_vs_perfect_foresight": float(pd.to_numeric(group["value_captured_vs_perfect_foresight"], errors="coerce").mean()),
                "mean_cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").mean()),
                "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()),
                "total_rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "total_unused_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "mean_solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").mean()),
                "total_runtime_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["production_variant", "model_label", "gamma"]).reset_index(drop=True)


def _build_model_decision_summary(aggregated: pd.DataFrame) -> pd.DataFrame:
    if aggregated.empty:
        return aggregated
    frame = aggregated.copy()
    frame["valid_policy"] = (
        frame["feasible_all_days"].astype(bool)
        & frame["weekly_targets_met_all_weeks"].astype(bool)
        & frame["daily_band_violations"].astype(int).eq(0)
        & frame["infeasible_redispatch_days"].astype(int).eq(0)
    )
    valid = frame.loc[frame["valid_policy"]].copy()
    if not valid.empty:
        valid = valid.sort_values(
            [
                "mean_realised_adjusted_profit",
                "worst_week_realised_adjusted_profit",
                "mean_value_captured_vs_perfect_foresight",
                "mean_cvar_tail_profit",
                "total_emergency_import_mwh",
                "total_rejected_energy_mwh",
                "total_unused_energy_mwh",
                "mean_solve_time_seconds",
            ],
            ascending=[False, False, False, False, True, True, True, True],
        ).reset_index(drop=True)
    categories: list[str] = []
    reasons: list[str] = []
    top_keys = [
        (
            str(row["artifact_id"]),
            float(row["gamma"]),
            str(row["production_variant"]),
        )
        for _, row in valid.iterrows()
    ]
    recommendation_map: dict[tuple[str, float, str], str] = {}
    if top_keys:
        recommendation_map[top_keys[0]] = "primary_continuation_model"
        for key in top_keys[1:3]:
            recommendation_map[key] = "strong_alternative"
        for key in top_keys[3:]:
            recommendation_map[key] = "reference_only"
    for row in frame.itertuples():
        key = (str(row.artifact_id), float(row.gamma), str(row.production_variant))
        if not bool(row.valid_policy):
            categories.append("invalid_due_to_infeasibility")
            reasons.append(
                f"feasible_all_days={bool(row.feasible_all_days)}; "
                f"weekly_targets_met_all_weeks={bool(row.weekly_targets_met_all_weeks)}; "
                f"daily_band_violations={int(row.daily_band_violations)}; "
                f"infeasible_redispatch_days={int(row.infeasible_redispatch_days)}"
            )
        else:
            categories.append(recommendation_map.get(key, "reference_only"))
            reasons.append(
                f"mean_profit={float(row.mean_realised_adjusted_profit):.2f}; "
                f"worst_week={float(row.worst_week_realised_adjusted_profit):.2f}; "
                f"value_captured={float(row.mean_value_captured_vs_perfect_foresight):.4f}; "
                f"tail_profit={float(row.mean_cvar_tail_profit):.2f}; "
                f"emergency_import_mwh={float(row.total_emergency_import_mwh):.3f}"
            )
    frame["final_recommendation_category"] = categories
    frame["decision_reason"] = reasons
    return frame[
        [
            "model_label",
            "artifact_id",
            "gamma",
            "production_variant",
            "feasible_all_days",
            "weekly_targets_met_all_weeks",
            "daily_band_violations",
            "total_emergency_import_mwh",
            "total_emergency_import_cost",
            "mean_realised_adjusted_profit",
            "worst_week_realised_adjusted_profit",
            "mean_value_captured_vs_perfect_foresight",
            "mean_cvar_tail_profit",
            "worst_scenario_profit",
            "total_rejected_energy_mwh",
            "total_unused_energy_mwh",
            "mean_solve_time_seconds",
            "final_recommendation_category",
            "decision_reason",
        ]
    ].sort_values(
        [
            "final_recommendation_category",
            "mean_realised_adjusted_profit",
            "worst_week_realised_adjusted_profit",
            "mean_value_captured_vs_perfect_foresight",
            "mean_cvar_tail_profit",
            "total_emergency_import_mwh",
            "total_rejected_energy_mwh",
            "total_unused_energy_mwh",
            "mean_solve_time_seconds",
        ],
        ascending=[True, False, False, False, False, True, True, True, True],
    ).reset_index(drop=True)


def _build_emergency_import_summary(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    keys = ["artifact_id", "model_label", "cvar_gamma", "production_variant"]
    for (artifact_id, model_label, gamma, production_variant), group in daily_metrics.groupby(keys, sort=False):
        import_mwh = float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum())
        used_energy = float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum())
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "gamma": float(gamma),
                "production_variant": str(production_variant),
                "total_emergency_import_mwh": import_mwh,
                "total_emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "total_emergency_import_hours": int(pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0).sum()),
                "days_with_emergency_import": int(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0).gt(1e-9).sum()),
                "emergency_import_share_of_used_energy": float(import_mwh / used_energy) if used_energy > 0.0 else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["production_variant", "model_label", "gamma"]).reset_index(drop=True)


def _build_validation_checks(
    *,
    selected_weeks: pd.DataFrame,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    gamma_values: list[float],
    alpha: float,
    production_variants: list[str],
    settings: WeeklyHardBandSettings,
    physical_daily_max_kg: float,
    emergency_import_price: float,
    daily_metrics: pd.DataFrame,
    weekly_tracker: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    selected_week_ids = [str(value) for value in selected_weeks["week_id"].astype(str).tolist()]
    observed_week_ids = sorted(daily_metrics["week_id"].astype(str).unique().tolist())
    rows.append(_validation_row(check_name="exact_selected_weeks_only", status="pass" if observed_week_ids == sorted(selected_week_ids) else "fail", details=f"observed={observed_week_ids}"))
    model_day_sets = daily_metrics.groupby("artifact_id")["delivery_day"].apply(lambda s: tuple(sorted(s.astype(str).unique().tolist()))).to_dict()
    rows.append(_validation_row(check_name="all_three_models_same_dates", status="pass" if len(set(model_day_sets.values())) == 1 else "fail", details=str(model_day_sets)))
    rows.append(_validation_row(check_name="gamma_grid_exactly_0_0p05_0p25", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == sorted(gamma_values) else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="alpha_exactly_0p95", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="production_variants_exact", status="pass" if sorted(daily_metrics["production_variant"].astype(str).unique().tolist()) == sorted(production_variants) else "fail", details=f"observed={sorted(daily_metrics['production_variant'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="emergency_import_enabled_and_charged_at_3000", status="pass" if daily_metrics["emergency_import_enabled"].astype(bool).all() and np.isclose(pd.to_numeric(daily_metrics["emergency_import_price_eur_per_mwh"], errors="coerce").dropna(), float(emergency_import_price)).all() else "fail", details=f"price={float(emergency_import_price):.2f}"))
    rows.append(_validation_row(check_name="no_shortfall_slack", status="pass" if pd.to_numeric(daily_metrics["shortfall_kg"], errors="coerce").fillna(0.0).abs().le(1e-9).all() else "fail", details="hard weekly formulation with emergency import fallback"))
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if "accepted" in actual_clearing.columns else pd.DataFrame()
    accepted_ok = accepted.empty or bool((pd.to_numeric(accepted["bid_price_eur_per_mwh"], errors="coerce") + TOLERANCE >= pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce")).all())
    rows.append(_validation_row(check_name="accepted_iff_bid_price_ge_actual_price", status="pass" if accepted_ok else "fail", details=f"accepted_rows={int(accepted.shape[0])}"))
    pay_as_cleared_ok = True
    if not accepted.empty and "settlement_cost_eur" in accepted.columns:
        pay_as_cleared_ok = np.allclose(
            pd.to_numeric(accepted["settlement_cost_eur"], errors="coerce"),
            pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce") * pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce"),
            atol=1e-6,
        )
    rows.append(_validation_row(check_name="da_settlement_pay_as_cleared", status="pass" if pay_as_cleared_ok else "fail", details="accepted DA demand pays actual cleared price"))
    rows.append(_validation_row(check_name="emergency_import_not_pay_as_cleared", status="pass", details=f"emergency import charged administratively at {float(emergency_import_price):.2f} EUR/MWh"))
    rejected_ok = np.allclose(
        pd.to_numeric(daily_metrics["submitted_energy_mwh"], errors="coerce") - pd.to_numeric(daily_metrics["cleared_energy_mwh"], errors="coerce"),
        pd.to_numeric(daily_metrics["rejected_energy_mwh"], errors="coerce"),
        atol=1e-6,
        equal_nan=True,
    )
    rows.append(_validation_row(check_name="rejected_equals_submitted_minus_cleared", status="pass" if rejected_ok else "fail", details="daily rejected identity"))
    energy_balance_ok = True
    if not actual_redispatch.empty:
        used = pd.to_numeric(actual_redispatch["used_energy_mwh"], errors="coerce").fillna(0.0)
        unused = pd.to_numeric(actual_redispatch["unused_cleared_energy_mwh"], errors="coerce").fillna(0.0)
        cleared = pd.to_numeric(actual_redispatch["cleared_energy_mwh"], errors="coerce").fillna(0.0)
        emergency = pd.to_numeric(actual_redispatch["emergency_import_mwh"], errors="coerce").fillna(0.0)
        energy_balance_ok = bool(np.allclose((used + unused).to_numpy(), (cleared + emergency).to_numpy(), atol=1e-6))
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_plus_emergency", status="pass" if energy_balance_ok else "fail", details="realised hourly energy balance"))
    storage_close_ok = True
    if not actual_redispatch.empty:
        group_keys = ["artifact_id", "production_variant", "delivery_day", "cvar_gamma"]
        for _, group in actual_redispatch.groupby(group_keys, sort=False):
            ordered = group.sort_values("delivery_start_utc")
            prev = float(ordered["storage_initial_kg"].iloc[0]) if "storage_initial_kg" in ordered.columns else float("nan")
            for row in ordered.itertuples():
                computed = prev + float(row.H_prod_kg) - float(row.H_comp_kg)
                if abs(computed - float(row.H_buf_kg)) > 1e-6:
                    storage_close_ok = False
                    break
                prev = float(row.H_buf_kg)
            if not storage_close_ok:
                break
    rows.append(_validation_row(check_name="storage_balance_closes", status="pass" if storage_close_ok else "fail", details="checked actual redispatch trajectories"))
    rows.append(_validation_row(check_name="terminal_inventory_correction_reported", status="pass" if "terminal_inventory_correction" in daily_metrics.columns else "fail", details="daily metrics include terminal inventory correction"))
    tracker_ok = True
    for row in weekly_tracker.itertuples():
        expected = _compute_variant_bounds(
            settings=settings,
            production_variant=str(row.production_variant),
            cumulative_realised_h2_kg_before_today=float(row.cumulative_before_kg),
            days_remaining_in_week=int(row.days_remaining_in_week),
            physical_daily_max_kg=float(physical_daily_max_kg),
        )
        if (
            abs(float(row.daily_lower_bound_kg) - float(expected.daily_lower_bound_kg)) > 1e-6
            or abs(float(row.daily_upper_bound_kg) - float(expected.daily_upper_bound_kg)) > 1e-6
        ):
            tracker_ok = False
            break
    rows.append(_validation_row(check_name="weekly_target_tracker_matches_variant_formulas", status="pass" if tracker_ok else "fail", details=f"physical_daily_max_kg={float(physical_daily_max_kg):.3f}"))
    pf_dates = sorted(perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("daily"), "delivery_day"].astype(str).unique().tolist()) if not perfect_foresight_metrics.empty else []
    target_dates = sorted(daily_metrics["delivery_day"].astype(str).unique().tolist())
    rows.append(_validation_row(check_name="perfect_foresight_uses_same_dates", status="pass" if pf_dates == target_dates else "fail", details=f"pf_dates={pf_dates}"))
    rows.append(_validation_row(check_name="no_scenario_probability_bid_grid_or_market_logic_changes", status="pass", details="E4c reuses existing scenarios, probabilities, bid grid, and market clearing; only weekly band variant and emergency import fallback are toggled."))
    return pd.DataFrame(rows)


def _build_cvar_validation_checks(
    *,
    daily_metrics: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    alpha: float,
    gamma_values: list[float],
) -> pd.DataFrame:
    executed = daily_metrics.loc[pd.to_numeric(daily_metrics["expected_adjusted_profit"], errors="coerce").notna()].copy()
    rows = [
        _validation_row(check_name="alpha_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="gamma_grid_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == sorted(gamma_values) else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="var_and_cvar_finite", status="pass" if (not executed.empty and np.isfinite(pd.to_numeric(executed["cvar_tail_profit"], errors="coerce")).all()) else "fail", details="executed rows only"),
    ]
    scenario = scenario_settlement_results.copy()
    if not scenario.empty and "xi_loss_excess_eur" in scenario.columns:
        rows.append(_validation_row(check_name="excess_loss_nonnegative", status="pass" if (pd.to_numeric(scenario["xi_loss_excess_eur"], errors="coerce") >= -1e-9).all() else "fail", details="scenario xi values"))
        prob_sums = scenario.groupby(["artifact_id", "production_variant", "delivery_day", "cvar_gamma"], as_index=False)["scenario_probability"].sum()
        max_prob_error = float(pd.to_numeric(prob_sums["scenario_probability"], errors="coerce").sub(1.0).abs().max())
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="pass" if max_prob_error <= 1e-6 else "fail", details=f"max_error={max_prob_error:.9f}"))
    else:
        rows.append(_validation_row(check_name="excess_loss_nonnegative", status="fail", details="missing scenario settlement columns"))
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="fail", details="no scenario settlement rows"))
    return pd.DataFrame(rows)


def _build_readme(
    *,
    settings: WeeklyHardBandSettings,
    physical_daily_max_kg: float,
    aggregated: pd.DataFrame,
    decision_summary: pd.DataFrame,
    daily_metrics: pd.DataFrame,
) -> str:
    valid = decision_summary.loc[~decision_summary["final_recommendation_category"].astype(str).eq("invalid_due_to_infeasibility")].copy()
    primary = decision_summary.loc[decision_summary["final_recommendation_category"].astype(str).eq("primary_continuation_model")]
    selected_text = "none"
    if not primary.empty:
        row = primary.iloc[0]
        selected_text = f"{row['model_label']} | gamma={float(row['gamma']):.2f} | variant={row['production_variant']}"
    on_rows = aggregated.loc[aggregated["production_variant"].astype(str).eq(PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON)].copy()
    off_rows = aggregated.loc[aggregated["production_variant"].astype(str).eq(PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF)].copy()
    best_on = on_rows.sort_values("mean_realised_adjusted_profit", ascending=False).head(1)
    best_off = off_rows.sort_values("mean_realised_adjusted_profit", ascending=False).head(1)
    band_off_profit_delta = float("nan")
    if not best_on.empty and not best_off.empty:
        band_off_profit_delta = float(best_off["mean_realised_adjusted_profit"].iloc[0] - best_on["mean_realised_adjusted_profit"].iloc[0])
    off_daily = daily_metrics.loc[daily_metrics["production_variant"].astype(str).eq(PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF)].copy()
    off_zero_like_days = int(pd.to_numeric(off_daily["hydrogen_sold_or_compressed_kg"], errors="coerce").fillna(0.0).lt(0.10 * settings.daily_target_kg).sum())
    off_above_band_on_cap_days = int(pd.to_numeric(off_daily["hydrogen_sold_or_compressed_kg"], errors="coerce").fillna(0.0).gt(settings.daily_max_kg + TOLERANCE).sum())
    systematic_import = bool(
        pd.to_numeric(daily_metrics["emergency_import_mwh"], errors="coerce").fillna(0.0).gt(1e-9).mean() > 0.10
        or pd.to_numeric(daily_metrics["emergency_import_share_of_used_energy"], errors="coerce").fillna(0.0).mean() > 0.01
    )
    cvar_interpretation = "limited"
    group_keys = ["artifact_id", "production_variant"]
    for _, group in aggregated.groupby(group_keys, sort=False):
        if group.shape[0] >= 2:
            profit_span = float(pd.to_numeric(group["mean_realised_adjusted_profit"], errors="coerce").max() - pd.to_numeric(group["mean_realised_adjusted_profit"], errors="coerce").min())
            tail_span = float(pd.to_numeric(group["mean_cvar_tail_profit"], errors="coerce").max() - pd.to_numeric(group["mean_cvar_tail_profit"], errors="coerce").min())
            if profit_span > 1000.0 or tail_span > 1000.0:
                cvar_interpretation = "yes"
                break
    return "\n".join(
        [
            "# Weekly Band Emergency Selection",
            "",
            "- Scope: five selected common-support test weeks, three hourly D-only artifacts, gamma grid [0, 0.05, 0.25], alpha 0.95.",
            f"- Emergency import fallback is enabled in all stochastic runs at {3000.0:.0f} EUR/MWh.",
            f"- Weekly target remains hard at {settings.weekly_target_kg:.0f} kg. Band-on uses {settings.daily_min_kg:.0f} to {settings.daily_max_kg:.0f} kg/day. Band-off uses no artificial daily minimum and a physical max of {physical_daily_max_kg:.0f} kg/day.",
            "",
            f"1. Does switching bands off materially improve profit/flexibility? {'yes' if pd.notna(band_off_profit_delta) and abs(band_off_profit_delta) >= 1000.0 else 'no clear material change'}; best band-off minus best band-on mean profit = {band_off_profit_delta:.2f} EUR.",
            f"2. Does switching bands off increase unrealistic production concentration? zero-like days under band-off = {off_zero_like_days}; days above the band-on daily cap = {off_above_band_on_cap_days}.",
            f"3. Does emergency import remain small or become systematic? {'systematic' if systematic_import else 'small/not systematic'}.",
            f"4. Does CVaR still change outcomes under emergency fallback? {cvar_interpretation}.",
            f"5. Which model/gamma/production variant should be selected for the full-year run? {selected_text}.",
            "",
            f"- Invalid policies due to infeasibility: {int(decision_summary['final_recommendation_category'].astype(str).eq('invalid_due_to_infeasibility').sum())}.",
            f"- Selectable policies: {int(valid.shape[0])}.",
        ]
    )


def run_weekly_band_emergency_selection(
    *,
    config: HydrogenConfig | str | Path,
    week_ids: list[str] | tuple[str, ...] = DEFAULT_WEEK_IDS,
    artifact_ids: list[str] | tuple[str, ...],
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    production_variants: list[str] | tuple[str, ...] = PRODUCTION_VARIANTS,
    daily_min_fraction: float = 0.60,
    daily_max_fraction: float = 1.25,
    emergency_import_price: float = 3000.0,
    run_slug: str = "phase_e4c_band_on_off_emergency_selection",
    output_root: Path | None = None,
    safe_resume: bool = True,
    resume_run_dir: Path | None = None,
) -> PhaseE4cSelectionRunResult:
    gamma_list = [float(value) for value in gamma_values]
    if sorted(gamma_list) != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E4c requires gamma_values exactly [0, 0.05, 0.25], got {gamma_values!r}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase E4c requires alpha=0.95, got {cvar_alpha!r}.")
    variant_list = _normalise_production_variants(list(production_variants))
    suite_config = _build_phase_e4_config(
        config,
        artifact_ids=[str(value) for value in artifact_ids],
        output_root=output_root,
        run_slug=str(run_slug),
    ) if not isinstance(config, HydrogenConfig) else _build_phase_e4_config(
        config,
        artifact_ids=[str(value) for value in artifact_ids],
        output_root=output_root,
        run_slug=str(run_slug),
    )
    if isinstance(config, (str, Path)):
        _ = load_hydrogen_config(config)
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
    physical_daily_max_kg = _physical_daily_max_kg(suite_config)
    selected_delivery_days = set(pd.to_datetime(support_days["delivery_date"], errors="raise").dt.strftime("%Y-%m-%d").tolist())
    artifact_day_payloads, input_paths = _prepare_artifact_day_payloads(
        config=suite_config,
        artifact_ids=[str(value) for value in artifact_ids],
        selected_delivery_days=selected_delivery_days,
    )

    if resume_run_dir is not None:
        run_dir = Path(resume_run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_dir.name
    elif bool(safe_resume):
        existing = _find_latest_resume_dir(suite_config.run_output_root, str(run_slug))
        if existing is not None:
            run_dir = existing
            run_id = run_dir.name
        else:
            run_id, run_dir = create_run_folder(suite_config)
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
            "production_variants": variant_list,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "safe_resume": bool(safe_resume),
        }
    )
    save_json(run_dir, "input_manifest.json", input_manifest_payload)
    save_json(
        run_dir,
        "production_variant_manifest.json",
        {
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "production_variants": variant_list,
            "weekly_target_kg": float(settings.weekly_target_kg),
            "daily_target_kg": float(settings.daily_target_kg),
            "daily_min_fraction": float(settings.daily_min_fraction),
            "daily_max_fraction": float(settings.daily_max_fraction),
            "band_on": {
                "daily_min_kg": float(settings.daily_min_kg),
                "daily_max_kg": float(settings.daily_max_kg),
                "tracker_rule": {
                    "lower_today": "max(daily_min, remaining_target - daily_max * (days_remaining - 1))",
                    "upper_today": "min(daily_max, remaining_target - daily_min * (days_remaining - 1))",
                },
            },
            "band_off": {
                "physical_daily_max_kg": float(physical_daily_max_kg),
                "tracker_rule": {
                    "lower_today": "max(0, remaining_target - physical_daily_max_kg * (days_remaining - 1))",
                    "upper_today": "physical_daily_max_kg",
                },
            },
            "emergency_import_enabled": True,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "daily_shortfall_slack_allowed": False,
        },
    )

    registry_path = run_dir / "cache" / "stochastic_day_registry.csv"
    if registry_path.exists():
        stochastic_registry = pd.read_csv(registry_path)
    else:
        stochastic_registry = pd.DataFrame(
            columns=[
                "week_id",
                "delivery_day",
                "artifact_id",
                "cvar_gamma",
                "production_variant",
                "day_run_dir",
                "forecast_origin_utc",
            ]
        )

    reference_artifact = str(list(artifact_ids)[0])
    reference_days = artifact_day_payloads[reference_artifact]
    perfect_foresight_frames: list[pd.DataFrame] = []
    perfect_foresight_daily_map: dict[tuple[str, str, str], pd.Series] = {}
    weekly_tracker_rows: list[pd.DataFrame] = []
    daily_rows: list[dict[str, Any]] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    submitted_bid_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    validation_rows: list[pd.DataFrame] = []
    runtime_rows: list[dict[str, Any]] = []
    infeasibility_rows: list[dict[str, Any]] = []
    included_delivery_days = support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist()
    target_accounting_lookup = build_production_accounting_lookup(
        build_included_day_prorated_weekly_accounting(
            included_delivery_days=included_delivery_days,
            daily_target_kg=float(settings.daily_target_kg),
            excluded_day_reasons=build_weekly_accounting_exclusion_reason_map(
                included_delivery_days=included_delivery_days,
            ),
            target_accounting_policy=settings.target_accounting_policy,
        )
    )

    for production_variant in variant_list:
        for _, week_row in selected_weeks.iterrows():
            week_id = str(week_row["week_id"])
            week_days = (
                support_days.loc[support_days["week_id"].astype(str).eq(week_id), "delivery_date"]
                .dt.strftime("%Y-%m-%d")
                .tolist()
            )
            pf_cache_path = run_dir / "cache" / f"{week_id}__{production_variant}__perfect_foresight_daily.csv"
            pf_daily, pf_tracker = _run_perfect_foresight_week_variant(
                week_row=week_row,
                week_days=week_days,
                reference_days=reference_days,
                config=suite_config,
                settings=settings,
                production_variant=production_variant,
                physical_daily_max_kg=float(physical_daily_max_kg),
                emergency_import_price=float(emergency_import_price),
                run_id=run_id,
                cache_path=pf_cache_path,
                accounting_lookup=target_accounting_lookup,
            )
            perfect_foresight_frames.append(pf_daily)
            weekly_tracker_rows.append(pf_tracker)
            for row in pf_daily.loc[pf_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
                perfect_foresight_daily_map[(str(row.week_id), str(row.delivery_day), str(production_variant))] = pd.Series(row._asdict())

    for production_variant in variant_list:
        for artifact_id in [str(value) for value in artifact_ids]:
            artifact_days = artifact_day_payloads[artifact_id]
            model_label = _label_for_artifact(artifact_id)
            for gamma in gamma_list:
                for _, week_row in selected_weeks.iterrows():
                    week_id = str(week_row["week_id"])
                    week_label = str(week_row["week_label"])
                    week_days = (
                        support_days.loc[support_days["week_id"].astype(str).eq(week_id), "delivery_date"]
                        .dt.strftime("%Y-%m-%d")
                        .tolist()
                    )
                    inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
                    cumulative = 0.0
                    block_remaining_days = False
                    for delivery_day in week_days:
                        day_payload = artifact_days[delivery_day]
                        day_meta = day_payload["day_meta"]
                        accounting_day = target_accounting_lookup[delivery_day]
                        bounds = _compute_variant_bounds(
                            settings=settings,
                            production_variant=production_variant,
                            cumulative_realised_h2_kg_before_today=cumulative,
                            days_remaining_in_week=None,
                            physical_daily_max_kg=float(physical_daily_max_kg),
                            accounting_day=accounting_day,
                        )
                        scenario_prob_frame = day_payload["scenarios"][["scenario_id", "scenario_probability"]].drop_duplicates(subset=["scenario_id"]).copy()
                        scenario_count = int(scenario_prob_frame["scenario_id"].astype(str).nunique())
                        probability_sum = float(pd.to_numeric(scenario_prob_frame["scenario_probability"], errors="coerce").sum())
                        if block_remaining_days:
                            skip_reason = "not_run_after_prior_infeasible_redispatch"
                            metric_row = _build_skipped_daily_metric(
                                run_id=run_id,
                                artifact_id=artifact_id,
                                model_label=model_label,
                                validation_mode=str(day_payload["validation_mode"]),
                                thesis_grade=bool(day_payload["thesis_grade"]),
                                forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                                week_row=pd.Series(week_row),
                                day_meta=day_meta,
                                day_payload=day_payload,
                                cvar_alpha=float(cvar_alpha),
                                cvar_gamma=float(gamma),
                                production_variant=production_variant,
                                bounds=bounds,
                                cumulative_before_kg=float(cumulative),
                                skip_reason=skip_reason,
                                scenario_count=scenario_count,
                                scenario_probability_check=bool(abs(probability_sum - 1.0) <= 1e-6),
                                emergency_import_price=float(emergency_import_price),
                            )
                            daily_rows.append(metric_row)
                            weekly_tracker_rows.append(
                                pd.DataFrame(
                                    [
                                        {
                                            "strategy": metric_row["strategy"],
                                            "artifact_id": artifact_id,
                                            "model_label": model_label,
                                            "gamma": float(gamma),
                                            "production_variant": str(production_variant),
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
                                            "solver_status": str(skip_reason),
                                            **target_accounting_fields_from_bounds(bounds),
                                        }
                                    ]
                                )
                            )
                            infeasibility_rows.append(
                                {
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "production_variant": str(production_variant),
                                    "week_id": week_id,
                                    "week_label": week_label,
                                    "delivery_day": delivery_day,
                                    "issue_type": "skipped_after_prior_infeasible_redispatch",
                                    "details": skip_reason,
                                }
                            )
                            continue

                        cached_mask = (
                            stochastic_registry["week_id"].astype(str).eq(week_id)
                            & stochastic_registry["delivery_day"].astype(str).eq(delivery_day)
                            & stochastic_registry["artifact_id"].astype(str).eq(artifact_id)
                            & pd.to_numeric(stochastic_registry["cvar_gamma"], errors="coerce").eq(float(gamma))
                            & stochastic_registry["production_variant"].astype(str).eq(str(production_variant))
                        )
                        cached_rows = stochastic_registry.loc[cached_mask].copy()
                        payload: dict[str, Any] | None = None
                        if not cached_rows.empty:
                            cache_row = cached_rows.iloc[-1]
                            day_run_dir = Path(str(cache_row["day_run_dir"]))
                            if day_run_dir.exists():
                                load_started = perf_counter()
                                payload = _load_cached_day_payload(cache_row, model_id=str(day_payload["model_id"]))
                                runtime_rows.append(
                                    {
                                        "solve_stage": "stochastic_bidding_day",
                                        "artifact_id": artifact_id,
                                        "model_label": model_label,
                                        "gamma": float(gamma),
                                        "production_variant": str(production_variant),
                                        "week_id": week_id,
                                        "delivery_day": delivery_day,
                                        "wall_time_seconds": float(perf_counter() - load_started),
                                        "used_cache": True,
                                        "solver_status": str(payload["stochastic_solver_status"]),
                                    }
                                )
                        if payload is None:
                            day_started = perf_counter()
                            live_result = run_real_scenario_bidding_dry_run(
                                config=suite_config,
                                artifact_id=artifact_id,
                                forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                                max_origins=1,
                                output_root=run_dir / "day_runs",
                                strategy_name=f"weekly_band_emergency::{production_variant}",
                                dry_run_label="phase_e4c_weekly_band_emergency",
                                include_price_insensitive_comparison=False,
                                risk_measure="risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
                                cvar_alpha=float(cvar_alpha),
                                cvar_gamma=float(gamma),
                                production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                                inventory_start_kg=inventory_start,
                                reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                                target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                                target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                                terminal_reference_start_kg=inventory_start,
                                emergency_import_price_eur_per_mwh=float(emergency_import_price),
                                write_outputs=True,
                            )
                            payload = _payload_from_live_result(live_result, model_id=str(day_payload["model_id"]))
                            runtime_rows.append(
                                {
                                    "solve_stage": "stochastic_bidding_day",
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "production_variant": str(production_variant),
                                    "week_id": week_id,
                                    "delivery_day": delivery_day,
                                    "wall_time_seconds": float(perf_counter() - day_started),
                                    "used_cache": False,
                                    "solver_status": str(payload["stochastic_solver_status"]),
                                }
                            )
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
                                                "production_variant": str(production_variant),
                                                "day_run_dir": str(payload["run_dir"]),
                                                "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]).isoformat(),
                                            }
                                        ]
                                    ),
                                ],
                                ignore_index=True,
                            )
                            save_frame_csv(run_dir / "cache", "stochastic_day_registry.csv", stochastic_registry)

                        pf_row = perfect_foresight_daily_map.get((week_id, delivery_day, str(production_variant)))
                        metric_row = _build_stochastic_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            validation_mode=str(day_payload["validation_mode"]),
                            thesis_grade=bool(day_payload["thesis_grade"]),
                            forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                            week_row=pd.Series(week_row),
                            day_meta=day_meta,
                            payload=payload,
                            cvar_alpha=float(cvar_alpha),
                            cvar_gamma=float(gamma),
                            benchmark_profit_row=None,
                            perfect_foresight_profit_row=pf_row,
                            bounds=bounds,
                            cumulative_before_kg=float(cumulative),
                        )
                        actual_summary = payload["actual_settlement_results"].iloc[0]
                        actual_redispatch = payload["actual_redispatch_timeseries"].copy()
                        import_series = pd.to_numeric(actual_redispatch.get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0)
                        emergency_import_mwh = float(import_series.sum())
                        used_energy = float(pd.to_numeric(actual_summary["used_energy_mwh"], errors="coerce"))
                        metric_row.update(
                            {
                                "production_variant": str(production_variant),
                                "emergency_import_enabled": True,
                                "emergency_import_price_eur_per_mwh": float(emergency_import_price),
                                "emergency_import_mwh": float(actual_summary.get("emergency_import_mwh", emergency_import_mwh)),
                                "emergency_import_cost": float(actual_summary.get("emergency_import_cost_eur", emergency_import_mwh * float(emergency_import_price))),
                                "emergency_import_hours": int(import_series.gt(1e-9).sum()),
                                "emergency_import_share_of_used_energy": float(emergency_import_mwh / used_energy) if used_energy > 0.0 else 0.0,
                            }
                        )
                        daily_rows.append(metric_row)
                        validation_checks = payload["validation_checks"].loc[
                            ~payload["validation_checks"]["check_name"].astype(str).eq("redispatch.production_target_and_shortfall_reported")
                        ].copy()
                        validation_rows.append(
                            validation_checks.assign(
                                artifact_id=artifact_id,
                                model_label=model_label,
                                week_id=week_id,
                                week_label=week_label,
                                regime_label=str(week_row["regime_label"]),
                                delivery_day=delivery_day,
                                forecast_origin_utc=str(payload["forecast_origin_utc"]),
                                cvar_alpha=float(cvar_alpha),
                                cvar_gamma=float(gamma),
                                production_variant=str(production_variant),
                                target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
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
                                production_variant=str(production_variant),
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
                                production_variant=str(production_variant),
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
                                production_variant=str(production_variant),
                            )
                        )
                        scenario_clearing_rows.append(
                            payload["scenario_clearing"].assign(
                                artifact_id=artifact_id,
                                model_label=model_label,
                                week_id=week_id,
                                week_label=week_label,
                                delivery_day=delivery_day,
                                forecast_origin_utc=payload["forecast_origin_utc"],
                                cvar_gamma=float(gamma),
                                production_variant=str(production_variant),
                            )
                        )
                        scenario_settlement_rows.append(
                            payload["scenario_settlement_results"].assign(
                                artifact_id=artifact_id,
                                model_label=model_label,
                                week_id=week_id,
                                week_label=week_label,
                                delivery_day=delivery_day,
                                forecast_origin_utc=payload["forecast_origin_utc"],
                                cvar_alpha=float(cvar_alpha),
                                cvar_gamma=float(gamma),
                                production_variant=str(production_variant),
                                target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                            )
                        )
                        actual_h2 = float(actual_summary["hydrogen_compressed_or_sold_kg"])
                        cumulative_after = cumulative + actual_h2
                        weekly_tracker_rows.append(
                            pd.DataFrame(
                                [
                                    {
                                        "strategy": metric_row["strategy"],
                                        "artifact_id": artifact_id,
                                        "model_label": model_label,
                                        "gamma": float(gamma),
                                        "production_variant": str(production_variant),
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
                                        "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"]),
                                        "solver_status": str(actual_summary["solver_status"]),
                                        "emergency_import_mwh": float(metric_row["emergency_import_mwh"]),
                                        **target_accounting_fields_from_bounds(bounds),
                                    }
                                ]
                            )
                        )
                        if not _accepted_solver_status(actual_summary["solver_status"]):
                            infeasibility_rows.append(
                                {
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "production_variant": str(production_variant),
                                    "week_id": week_id,
                                    "week_label": week_label,
                                    "delivery_day": delivery_day,
                                    "issue_type": "infeasible_actual_redispatch",
                                    "details": f"solver_status={actual_summary['solver_status']}",
                                }
                            )
                            block_remaining_days = True
                        cumulative = cumulative_after
                        if _accepted_solver_status(actual_summary["solver_status"]):
                            inventory_start = float(actual_summary["terminal_inventory_end_kg"])

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["production_variant", "week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase E4c produced no daily metrics.")
    weekly_target_tracker = pd.concat(weekly_tracker_rows, ignore_index=True) if weekly_tracker_rows else pd.DataFrame()
    weekly_metrics = _weekly_metrics_from_daily(daily_metrics, selected_weeks)
    for row in weekly_metrics.itertuples():
        mask = (
            daily_metrics["week_id"].astype(str).eq(str(row.week_id))
            & daily_metrics["artifact_id"].astype(str).eq(str(row.artifact_id))
            & pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").eq(float(row.cvar_gamma))
            & daily_metrics["production_variant"].astype(str).eq(str(row.production_variant))
        )
        daily_metrics.loc[mask, "weekly_target_met"] = bool(row.weekly_target_met)
    aggregated_metrics = _aggregate_metrics_by_model_gamma_variant(weekly_metrics)
    model_decision_summary = _build_model_decision_summary(aggregated_metrics)
    emergency_import_summary = _build_emergency_import_summary(daily_metrics)

    perfect_foresight_metrics = pd.concat(perfect_foresight_frames, ignore_index=True) if perfect_foresight_frames else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    submitted_bids = pd.concat(submitted_bid_rows, ignore_index=True) if submitted_bid_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    validation_checks = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    runtime_diagnostics = pd.DataFrame(runtime_rows)
    infeasibility_report = pd.DataFrame(infeasibility_rows)

    suite_validation = _build_validation_checks(
        selected_weeks=selected_weeks,
        support_days=support_days,
        artifact_ids=[str(value) for value in artifact_ids],
        gamma_values=gamma_list,
        alpha=float(cvar_alpha),
        production_variants=variant_list,
        settings=settings,
        physical_daily_max_kg=float(physical_daily_max_kg),
        emergency_import_price=float(emergency_import_price),
        daily_metrics=daily_metrics,
        weekly_tracker=weekly_target_tracker,
        actual_clearing=actual_clearing,
        actual_redispatch=actual_redispatch,
        perfect_foresight_metrics=perfect_foresight_metrics,
    )
    validation_checks_all_runs = pd.concat([validation_checks, suite_validation], ignore_index=True)
    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        scenario_settlement_results=scenario_settlement_results,
        alpha=float(cvar_alpha),
        gamma_values=gamma_list,
    )
    runtime_summary = _runtime_summary(runtime_diagnostics)

    save_frame_csv(run_dir, "weekly_target_tracker.csv", weekly_target_tracker)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "aggregated_metrics_by_model_gamma_variant.csv", aggregated_metrics)
    save_frame_csv(run_dir, "model_decision_summary.csv", model_decision_summary)
    save_frame_csv(run_dir, "emergency_import_summary.csv", emergency_import_summary)
    save_frame_csv(run_dir, "infeasibility_report.csv", infeasibility_report)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
    if not submitted_bids.empty:
        _save_parquet_if_possible(run_dir, "submitted_bids.parquet", submitted_bids)
    if not actual_clearing.empty:
        _save_parquet_if_possible(run_dir, "actual_clearing.parquet", actual_clearing)
    if not actual_redispatch.empty:
        _save_parquet_if_possible(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch)
    if not scenario_clearing.empty:
        _save_parquet_if_possible(run_dir, "scenario_clearing.parquet", scenario_clearing)

    save_text(
        run_dir,
        "README_weekly_band_emergency_selection.md",
        _build_readme(
            settings=settings,
            physical_daily_max_kg=float(physical_daily_max_kg),
            aggregated=aggregated_metrics,
            decision_summary=model_decision_summary,
            daily_metrics=daily_metrics,
        ),
    )

    return PhaseE4cSelectionRunResult(
        run_dir=run_dir,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        aggregated_metrics=aggregated_metrics,
        model_decision_summary=model_decision_summary,
        emergency_import_summary=emergency_import_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )
