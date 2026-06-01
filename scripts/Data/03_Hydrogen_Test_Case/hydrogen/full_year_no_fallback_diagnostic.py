from __future__ import annotations

import json
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
from .full_year_repaired_lear_strict import (
    _atomic_write_csv,
    _build_selected_artifact_manifest,
    _build_support_preflight,
    _expected_24h_days,
    _load_or_build_support_cache,
    _load_pickle_or_parquet,
    _physical_daily_max_kg,
    _safe_read_csv,
    _stage_runtime_row,
    _week_manifest_from_days,
)
from .plant_parameters import HydrogenConfig
from .production_target import (
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    validate_target_accounting_policy,
)
from .redispatch import RedispatchSolveResult, solve_actual_redispatch_from_cleared_energy
from .run_registry import (
    build_inputs_manifest,
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .selected_week_smoke import TOLERANCE, _label_for_artifact
from .weekly_band_emergency_selection import (
    _build_skipped_daily_metric,
    _compute_variant_bounds,
)
from .weekly_hard_band_decision import (
    _accepted_solver_status,
    _actual_prices_from_day_frame,
    _build_phase_e4_config,
    _build_stochastic_daily_metric,
    _save_parquet_if_possible,
)
from .weekly_hard_band_target import (
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    TARGET_MODE_WEEKLY_HARD_BAND,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_accounting_exclusion_reason_map,
    build_weekly_hard_band_settings,
    target_accounting_fields_from_bounds,
)


DEFAULT_PHASE_E5_BASELINE_RUN_DIR = Path(
    "scripts/Data/03_Hydrogen_Test_Case/runs/20260523_124731_phase_e5_full_year_repaired_lear_strict_g0_g025_band_off"
)
DEFAULT_PHASE_E5C_RUN_SLUG = "phase_e5c_no_fallback_diagnostic"
RESTORATION_EMERGENCY_IMPORT_PRICE_EUR_PER_MWH = 3000.0
PERSIST_SCENARIO_CLEARING_CHECKPOINT = False


@dataclass(frozen=True)
class PhaseE5cNoFallbackResult:
    baseline_run_dir: Path
    run_dir: Path
    flexibility_value_capture_summary: pd.DataFrame
    flexibility_value_capture_by_week: pd.DataFrame
    policy_similarity_diagnostics: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    annual_metrics_by_gamma: pd.DataFrame
    infeasibility_report: pd.DataFrame
    restoration_diagnostics: pd.DataFrame
    fallback_on_off_annual_comparison: pd.DataFrame
    fallback_on_off_weekly_comparison: pd.DataFrame
    fallback_on_off_diagnostic_summary: pd.DataFrame


def _find_latest_resume_dir(root: Path, run_slug: str) -> Path | None:
    candidates = [
        path
        for path in root.glob(f"*_{run_slug}")
        if path.is_dir() and (path / "support_preflight.csv").exists()
    ]
    if not candidates:
        return None

    def _progress_key(path: Path) -> tuple[int, str]:
        checkpoint_path = path / "cache" / "no_fallback_checkpoint_daily_metrics.csv"
        if not checkpoint_path.exists():
            return 0, path.name
        try:
            progress = int(pd.read_csv(checkpoint_path).shape[0])
        except Exception:
            progress = 0
        return progress, path.name

    return sorted(candidates, key=_progress_key)[-1]


def _no_fallback_checkpoint_paths(cache_dir: Path) -> dict[str, Path]:
    return {
        "registry": cache_dir / "no_fallback_day_registry.csv",
        "daily_metrics": cache_dir / "no_fallback_checkpoint_daily_metrics.csv",
        "actual_settlement": cache_dir / "no_fallback_checkpoint_actual_settlement_results.csv",
        "scenario_settlement": cache_dir / "no_fallback_checkpoint_scenario_settlement_results.csv",
        "actual_clearing": cache_dir / "no_fallback_checkpoint_actual_clearing.csv",
        "submitted_bids": cache_dir / "no_fallback_checkpoint_submitted_bids.csv",
        "scenario_clearing": cache_dir / "no_fallback_checkpoint_scenario_clearing.csv",
        "weekly_tracker": cache_dir / "no_fallback_checkpoint_weekly_target_tracker.csv",
        "runtime_diagnostics": cache_dir / "no_fallback_checkpoint_runtime_diagnostics.csv",
        "infeasibility_report": cache_dir / "no_fallback_checkpoint_infeasibility_report.csv",
        "restoration_diagnostics": cache_dir / "no_fallback_checkpoint_restoration_diagnostics.csv",
        "progress": cache_dir / "no_fallback_progress_summary.csv",
    }


def _load_checkpoint_store(cache_dir: Path) -> dict[str, pd.DataFrame]:
    paths = _no_fallback_checkpoint_paths(cache_dir)
    return {
        "registry": _safe_read_csv(paths["registry"]),
        "daily_metrics": _safe_read_csv(paths["daily_metrics"]),
        "actual_settlement": _safe_read_csv(paths["actual_settlement"]),
        "scenario_settlement": _safe_read_csv(paths["scenario_settlement"]),
        "actual_clearing": _safe_read_csv(paths["actual_clearing"]),
        "submitted_bids": _safe_read_csv(paths["submitted_bids"]),
        "scenario_clearing": (
            _safe_read_csv(paths["scenario_clearing"]) if PERSIST_SCENARIO_CLEARING_CHECKPOINT else pd.DataFrame()
        ),
        "weekly_tracker": _safe_read_csv(paths["weekly_tracker"]),
        "runtime_diagnostics": _safe_read_csv(paths["runtime_diagnostics"]),
        "infeasibility_report": _safe_read_csv(paths["infeasibility_report"]),
        "restoration_diagnostics": _safe_read_csv(paths["restoration_diagnostics"]),
    }


def _append_or_replace(base: pd.DataFrame, new_rows: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    if new_rows.empty:
        return base.copy()
    if base.empty:
        combined = new_rows.copy()
    else:
        combined = pd.concat([base, new_rows], ignore_index=True)
    if not key_columns:
        return combined.reset_index(drop=True)
    return combined.drop_duplicates(subset=key_columns, keep="last").reset_index(drop=True)


def _deduplicate_registry(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "week_id",
                "delivery_day",
                "artifact_id",
                "cvar_gamma",
                "day_run_dir",
                "forecast_origin_utc",
                "solver_status",
                "actual_redispatch_solver_status",
                "committed_at_utc",
            ]
        )
    dedup = frame.copy()
    for column in ["week_id", "delivery_day", "artifact_id", "day_run_dir", "forecast_origin_utc", "solver_status", "actual_redispatch_solver_status", "committed_at_utc"]:
        if column not in dedup.columns:
            dedup[column] = ""
        dedup[column] = dedup[column].astype(str)
    dedup["cvar_gamma"] = pd.to_numeric(dedup["cvar_gamma"], errors="coerce")
    dedup = dedup.sort_values(["cvar_gamma", "delivery_day", "committed_at_utc", "day_run_dir"]).drop_duplicates(
        subset=["artifact_id", "cvar_gamma", "delivery_day"],
        keep="last",
    )
    return dedup.reset_index(drop=True)


def _progress_counts_from_registry(
    registry: pd.DataFrame,
    *,
    artifact_id: str,
    gammas: list[float],
    expected_days: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for gamma in gammas:
        group = registry.loc[
            registry["artifact_id"].astype(str).eq(str(artifact_id))
            & pd.to_numeric(registry["cvar_gamma"], errors="coerce").eq(float(gamma))
        ].copy()
        completed_days = sorted(set(group["delivery_day"].astype(str).tolist()))
        expected_set = set(expected_days)
        remaining_days = sorted(expected_set.difference(completed_days))
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "gamma": float(gamma),
                "completed_solves": int(len(completed_days)),
                "remaining_solves": int(len(remaining_days)),
                "last_completed_day": completed_days[-1] if completed_days else "",
                "first_remaining_day": remaining_days[0] if remaining_days else "",
            }
        )
    return pd.DataFrame(rows)


def _flush_checkpoint_store(
    *,
    cache_dir: Path,
    existing_store: dict[str, pd.DataFrame],
    pending_store: dict[str, list[pd.DataFrame] | list[dict[str, Any]]],
    expected_days: list[str],
    artifact_id: str,
    gammas: list[float],
) -> dict[str, pd.DataFrame]:
    paths = _no_fallback_checkpoint_paths(cache_dir)

    registry_pending = pd.DataFrame(pending_store["registry"])
    existing_store["registry"] = _deduplicate_registry(
        pd.concat([existing_store["registry"], registry_pending], ignore_index=True)
        if not registry_pending.empty
        else existing_store["registry"]
    )
    key_map = {
        "daily_metrics": ["artifact_id", "cvar_gamma", "delivery_day"],
        "actual_settlement": ["artifact_id", "cvar_gamma", "delivery_day"],
        "scenario_settlement": ["artifact_id", "cvar_gamma", "delivery_day", "scenario_id"],
        "actual_clearing": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc", "bid_block"],
        "submitted_bids": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc", "bid_block"],
        "scenario_clearing": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc", "scenario_id", "bid_block"],
        "weekly_tracker": ["artifact_id", "gamma", "delivery_day"],
        "runtime_diagnostics": ["solve_stage", "artifact_id", "gamma", "week_id", "delivery_day"],
        "infeasibility_report": ["artifact_id", "gamma", "delivery_day", "record_type"],
        "restoration_diagnostics": ["artifact_id", "gamma", "delivery_day"],
    }
    for key, columns in key_map.items():
        if key == "scenario_clearing" and not PERSIST_SCENARIO_CLEARING_CHECKPOINT:
            existing_store[key] = pd.DataFrame()
            continue
        pending_items = pending_store[key]
        if not pending_items:
            pending_frame = pd.DataFrame()
        elif all(isinstance(item, pd.DataFrame) for item in pending_items):
            pending_frame = pd.concat(pending_items, ignore_index=True)
        else:
            normalized_rows: list[pd.DataFrame] = []
            for item in pending_items:
                if isinstance(item, pd.DataFrame):
                    normalized_rows.append(item)
                else:
                    normalized_rows.append(pd.DataFrame([item]))
            pending_frame = pd.concat(normalized_rows, ignore_index=True) if normalized_rows else pd.DataFrame()
        existing_store[key] = _append_or_replace(existing_store[key], pending_frame, columns)

    _atomic_write_csv(paths["registry"], existing_store["registry"])
    for key in [
        "daily_metrics",
        "actual_settlement",
        "scenario_settlement",
        "actual_clearing",
        "submitted_bids",
        "weekly_tracker",
        "runtime_diagnostics",
        "infeasibility_report",
        "restoration_diagnostics",
    ]:
        _atomic_write_csv(paths[key], existing_store[key])
    if PERSIST_SCENARIO_CLEARING_CHECKPOINT:
        _atomic_write_csv(paths["scenario_clearing"], existing_store["scenario_clearing"])
    _atomic_write_csv(
        paths["progress"],
        _progress_counts_from_registry(
            existing_store["registry"],
            artifact_id=artifact_id,
            gammas=gammas,
            expected_days=expected_days,
        ),
    )
    return existing_store


def _annual_row_from_benchmark(benchmark_metrics: pd.DataFrame) -> pd.Series:
    annual = benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("annual")].copy()
    if annual.empty:
        annual = pd.DataFrame(
            [
                {
                    "realised_adjusted_profit": np.nan,
                    "hydrogen_revenue": np.nan,
                    "da_settlement_cost": np.nan,
                    "cleared_energy_mwh": np.nan,
                    "unused_cleared_energy_mwh": np.nan,
                    "rejected_energy_mwh": np.nan,
                    "average_actual_price_paid": np.nan,
                    "hydrogen_sold_or_compressed_kg": np.nan,
                }
            ]
        )
    return annual.iloc[0]


def _daily_rows_from_benchmark(benchmark_metrics: pd.DataFrame) -> pd.DataFrame:
    return benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("daily")].copy()


def _share_near_physical_max(day_frame: pd.DataFrame, *, physical_daily_max_kg: float, threshold: float = 0.95) -> float:
    if day_frame.empty or physical_daily_max_kg <= 0.0:
        return np.nan
    produced = pd.to_numeric(day_frame["hydrogen_sold_or_compressed_kg"], errors="coerce")
    return float(produced.ge(float(threshold) * float(physical_daily_max_kg) - 1e-9).mean())


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    mask = v.notna() & w.notna()
    if not bool(mask.any()):
        return np.nan
    w_sum = float(w.loc[mask].sum())
    if abs(w_sum) <= 1e-12:
        return np.nan
    return float((v.loc[mask] * w.loc[mask]).sum() / w_sum)


def _build_policy_similarity_diagnostics(
    *,
    stochastic_daily: pd.DataFrame,
    stochastic_weekly: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    true_pf_weekly: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    true_pf_weekly = true_pf_weekly.copy()
    true_pf_weekly["week_id"] = true_pf_weekly["week_id"].astype(str)
    for gamma, group in stochastic_daily.groupby(pd.to_numeric(stochastic_daily["cvar_gamma"], errors="coerce"), sort=True):
        day_join = group.copy()
        submitted_weights = pd.to_numeric(day_join["submitted_energy_mwh"], errors="coerce").fillna(0.0)
        rows.extend(
            [
                {
                    "gamma": float(gamma),
                    "comparator": "benchmark_daily",
                    "metric": "mean_abs_profit_difference_eur_per_day",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(day_join["realised_adjusted_profit"], errors="coerce") - pd.to_numeric(day_join["benchmark_profit"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "benchmark_daily",
                    "metric": "mean_abs_cleared_energy_difference_mwh_per_day",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(day_join["cleared_energy_mwh"], errors="coerce") - pd.to_numeric(day_join["benchmark_cleared_energy_mwh"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "benchmark_daily",
                    "metric": "mean_abs_h2_difference_kg_per_day",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(day_join["hydrogen_sold_or_compressed_kg"], errors="coerce") - pd.to_numeric(day_join["benchmark_hydrogen_sold_or_compressed_kg"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "benchmark_daily",
                    "metric": "weighted_high_bid_share",
                    "value": _weighted_mean(day_join["high_bid_share"], submitted_weights),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "benchmark_daily",
                    "metric": "weighted_market_cap_bid_share",
                    "value": _weighted_mean(day_join["market_cap_bid_share"], submitted_weights),
                },
            ]
        )
    for gamma, group in stochastic_weekly.groupby(pd.to_numeric(stochastic_weekly["cvar_gamma"], errors="coerce"), sort=True):
        join = group.merge(
            true_pf_weekly[
                [
                    "week_id",
                    "realised_adjusted_profit",
                    "cleared_energy_mwh",
                    "hydrogen_sold_or_compressed_kg",
                    "average_actual_price_paid",
                ]
            ].rename(
                columns={
                    "realised_adjusted_profit": "true_pf_profit",
                    "cleared_energy_mwh": "true_pf_cleared_energy_mwh",
                    "hydrogen_sold_or_compressed_kg": "true_pf_h2_kg",
                    "average_actual_price_paid": "true_pf_avg_price_paid",
                }
            ),
            on="week_id",
            how="left",
        )
        rows.extend(
            [
                {
                    "gamma": float(gamma),
                    "comparator": "true_pf_weekly",
                    "metric": "mean_abs_profit_difference_eur_per_week",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(join["realised_adjusted_profit"], errors="coerce") - pd.to_numeric(join["true_pf_profit"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "true_pf_weekly",
                    "metric": "mean_abs_cleared_energy_difference_mwh_per_week",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(join["cleared_energy_mwh"], errors="coerce") - pd.to_numeric(join["true_pf_cleared_energy_mwh"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "true_pf_weekly",
                    "metric": "mean_abs_h2_difference_kg_per_week",
                    "value": float(np.nanmean(np.abs(pd.to_numeric(join["hydrogen_sold_or_compressed_kg"], errors="coerce") - pd.to_numeric(join["true_pf_h2_kg"], errors="coerce")))),
                },
                {
                    "gamma": float(gamma),
                    "comparator": "true_pf_weekly",
                    "metric": "weeks_with_profit_regret_gt_0",
                    "value": float(pd.to_numeric(join["regret_vs_perfect_foresight"], errors="coerce").gt(0.0).mean()),
                },
            ]
        )
    return pd.DataFrame(rows)


def run_flexibility_value_audit(
    *,
    baseline_run_dir: Path,
    config: HydrogenConfig | str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline_run_dir = Path(baseline_run_dir)
    annual = pd.read_csv(baseline_run_dir / "annual_metrics_by_gamma_with_true_pf.csv")
    true_pf_annual = pd.read_csv(baseline_run_dir / "true_perfect_foresight_annual_metrics.csv")
    benchmark_metrics = pd.read_csv(baseline_run_dir / "benchmark_metrics.csv")
    emergency_summary = pd.read_csv(baseline_run_dir / "emergency_import_summary.csv")
    daily_metrics = pd.read_csv(baseline_run_dir / "daily_metrics.csv")
    weekly_metrics = pd.read_csv(baseline_run_dir / "weekly_metrics.csv")
    true_pf_weekly = pd.read_csv(baseline_run_dir / "true_perfect_foresight_weekly_metrics.csv")

    suite_config = load_hydrogen_config(config) if not isinstance(config, HydrogenConfig) else config
    physical_daily_max_kg = _physical_daily_max_kg(suite_config)
    benchmark_annual = _annual_row_from_benchmark(benchmark_metrics)
    benchmark_daily = _daily_rows_from_benchmark(benchmark_metrics)
    true_pf_annual_row = true_pf_annual.loc[true_pf_annual["aggregation_level"].astype(str).eq("annual")].iloc[0]

    summary_rows: list[dict[str, Any]] = []
    weekly_rows: list[dict[str, Any]] = []
    for row in annual.itertuples():
        gamma = float(row.gamma)
        daily_gamma = daily_metrics.loc[pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").eq(gamma)].copy()
        weekly_gamma = weekly_metrics.loc[pd.to_numeric(weekly_metrics["cvar_gamma"], errors="coerce").eq(gamma)].copy()
        emergency_row = emergency_summary.loc[pd.to_numeric(emergency_summary["gamma"], errors="coerce").eq(gamma)].head(1)
        benchmark_profit = float(benchmark_annual["realised_adjusted_profit"])
        stochastic_profit = float(row.annual_realised_adjusted_profit)
        true_pf_profit = float(row.true_pf_annual_profit)
        uplift = stochastic_profit - benchmark_profit
        max_possible_uplift = true_pf_profit - benchmark_profit
        daily_gamma["near_physical_max"] = pd.to_numeric(daily_gamma["hydrogen_sold_or_compressed_kg"], errors="coerce").ge(0.95 * float(physical_daily_max_kg) - 1e-9)
        summary_rows.append(
            {
                "gamma": gamma,
                "stochastic_realised_profit": stochastic_profit,
                "true_pf_profit": true_pf_profit,
                "price_insensitive_benchmark_profit": benchmark_profit,
                "absolute_regret_vs_true_pf": float(true_pf_profit - stochastic_profit),
                "uplift_vs_price_insensitive": float(uplift),
                "max_possible_uplift": float(max_possible_uplift),
                "flexibility_value_captured": float(uplift / max_possible_uplift) if abs(max_possible_uplift) > 1e-9 else np.nan,
                "benchmark_profit_share_of_stochastic_profit": float(benchmark_profit / stochastic_profit) if abs(stochastic_profit) > 1e-9 else np.nan,
                "benchmark_profit_share_of_true_pf_profit": float(benchmark_profit / true_pf_profit) if abs(true_pf_profit) > 1e-9 else np.nan,
                "incremental_flexibility_share_of_stochastic_profit": float(uplift / stochastic_profit) if abs(stochastic_profit) > 1e-9 else np.nan,
                "emergency_import_mwh": float(emergency_row["total_emergency_import_mwh"].iloc[0]) if not emergency_row.empty else float(row.total_emergency_import_mwh),
                "emergency_import_cost": float(emergency_row["total_emergency_import_cost"].iloc[0]) if not emergency_row.empty else float(row.emergency_import_cost),
                "rejected_energy_mwh": float(row.total_rejected_energy),
                "unused_cleared_energy_mwh": float(row.total_unused_cleared_energy),
                "average_actual_price_paid": float(row.average_actual_price_paid),
                "high_bid_share_weighted": _weighted_mean(daily_gamma["high_bid_share"], daily_gamma["submitted_energy_mwh"]),
                "market_cap_bid_share_weighted": _weighted_mean(daily_gamma["market_cap_bid_share"], daily_gamma["submitted_energy_mwh"]),
                "days_near_physical_max_share": float(daily_gamma["near_physical_max"].mean()) if not daily_gamma.empty else np.nan,
                "days_near_physical_max_count": int(daily_gamma["near_physical_max"].sum()) if not daily_gamma.empty else 0,
                "weekly_target_fulfilment_share": float(weekly_gamma["weekly_target_met"].astype(bool).mean()) if not weekly_gamma.empty else np.nan,
                "weekly_target_fulfilment_count": int(weekly_gamma["weekly_target_met"].astype(bool).sum()) if not weekly_gamma.empty else 0,
                "weekly_count": int(weekly_gamma.shape[0]),
                "hydrogen_revenue_eur": float(pd.to_numeric(daily_gamma["hydrogen_revenue"], errors="coerce").sum()),
                "benchmark_hydrogen_revenue_eur": float(pd.to_numeric(benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("annual"), "hydrogen_revenue"], errors="coerce").iloc[0]),
                "true_pf_hydrogen_revenue_eur": float(true_pf_annual_row["hydrogen_revenue"]),
                "updated_gamma_recommendation": str(getattr(row, "updated_gamma_recommendation", "")),
            }
        )

        benchmark_weekly = benchmark_metrics.loc[
            benchmark_metrics["aggregation_level"].astype(str).eq("weekly")
        ][["week_id", "realised_adjusted_profit", "cleared_energy_mwh", "unused_cleared_energy_mwh", "rejected_energy_mwh", "average_actual_price_paid"]].rename(
            columns={
                "realised_adjusted_profit": "benchmark_profit",
                "cleared_energy_mwh": "benchmark_cleared_energy_mwh",
                "unused_cleared_energy_mwh": "benchmark_unused_energy_mwh",
                "rejected_energy_mwh": "benchmark_rejected_energy_mwh",
                "average_actual_price_paid": "benchmark_average_actual_price_paid",
            }
        )
        weekly_enriched = weekly_gamma.merge(benchmark_weekly, on="week_id", how="left").merge(
            true_pf_weekly[
                ["week_id", "realised_adjusted_profit", "cleared_energy_mwh", "unused_cleared_energy_mwh", "rejected_energy_mwh", "average_actual_price_paid"]
            ].rename(
                columns={
                    "realised_adjusted_profit": "true_pf_profit",
                    "cleared_energy_mwh": "true_pf_cleared_energy_mwh",
                    "unused_cleared_energy_mwh": "true_pf_unused_energy_mwh",
                    "rejected_energy_mwh": "true_pf_rejected_energy_mwh",
                    "average_actual_price_paid": "true_pf_average_actual_price_paid",
                }
            ),
            on="week_id",
            how="left",
        )
        near_max_by_week = (
            daily_gamma.assign(near_physical_max=daily_gamma["near_physical_max"].astype(int))
            .groupby("week_id", as_index=False)
            .agg(
                near_physical_max_day_count=("near_physical_max", "sum"),
                included_delivery_day_count_daily=("delivery_day", "count"),
            )
        )
        weekly_enriched = weekly_enriched.merge(near_max_by_week, on="week_id", how="left")
        weekly_enriched["uplift_vs_benchmark"] = pd.to_numeric(weekly_enriched["realised_adjusted_profit"], errors="coerce") - pd.to_numeric(weekly_enriched["benchmark_profit"], errors="coerce")
        weekly_enriched["max_possible_uplift"] = pd.to_numeric(weekly_enriched["true_pf_profit"], errors="coerce") - pd.to_numeric(weekly_enriched["benchmark_profit"], errors="coerce")
        weekly_enriched["flexibility_value_captured"] = np.where(
            pd.to_numeric(weekly_enriched["max_possible_uplift"], errors="coerce").abs() > 1e-9,
            pd.to_numeric(weekly_enriched["uplift_vs_benchmark"], errors="coerce") / pd.to_numeric(weekly_enriched["max_possible_uplift"], errors="coerce"),
            np.nan,
        )
        weekly_enriched["absolute_regret_vs_true_pf"] = pd.to_numeric(weekly_enriched["true_pf_profit"], errors="coerce") - pd.to_numeric(weekly_enriched["realised_adjusted_profit"], errors="coerce")
        weekly_enriched["gamma"] = gamma
        weekly_rows.append(
            weekly_enriched[
                [
                    "gamma",
                    "week_id",
                    "week_label",
                    "realised_adjusted_profit",
                    "benchmark_profit",
                    "true_pf_profit",
                    "absolute_regret_vs_true_pf",
                    "uplift_vs_benchmark",
                    "max_possible_uplift",
                    "flexibility_value_captured",
                    "emergency_import_mwh",
                    "emergency_import_cost",
                    "rejected_energy_mwh",
                    "unused_cleared_energy_mwh",
                    "average_actual_price_paid",
                    "high_bid_share",
                    "market_cap_bid_share",
                    "near_physical_max_day_count",
                    "included_delivery_day_count",
                    "weekly_target_met",
                ]
            ].copy()
        )

    flexibility_value_capture_summary = pd.DataFrame(summary_rows).sort_values("gamma").reset_index(drop=True)
    flexibility_value_capture_by_week = pd.concat(weekly_rows, ignore_index=True) if weekly_rows else pd.DataFrame()
    policy_similarity_diagnostics = _build_policy_similarity_diagnostics(
        stochastic_daily=daily_metrics,
        stochastic_weekly=weekly_metrics,
        benchmark_daily=benchmark_daily,
        true_pf_weekly=true_pf_weekly,
    )

    summary_path = baseline_run_dir / "flexibility_value_capture_summary.csv"
    by_week_path = baseline_run_dir / "flexibility_value_capture_by_week.csv"
    policy_path = baseline_run_dir / "policy_similarity_diagnostics.csv"
    flexibility_value_capture_summary.to_csv(summary_path, index=False)
    flexibility_value_capture_by_week.to_csv(by_week_path, index=False)
    policy_similarity_diagnostics.to_csv(policy_path, index=False)

    lines = ["# Flexibility Value Audit", ""]
    for row in flexibility_value_capture_summary.itertuples():
        lines.extend(
            [
                f"## Gamma {row.gamma:.2f}",
                "",
                f"1. High value captured vs true PF is **not mainly incremental flexibility capture**. The common price-insensitive floor already explains {row.benchmark_profit_share_of_true_pf_profit:.2%} of true-PF profit and {row.benchmark_profit_share_of_stochastic_profit:.2%} of stochastic profit.",
                f"2. True flexibility value captured above the benchmark is {row.flexibility_value_captured:.2%} of the benchmark-to-true-PF gap ({row.uplift_vs_price_insensitive:,.0f} EUR captured out of {row.max_possible_uplift:,.0f} EUR).",
                f"3. Stochastic is materially better than price-insensitive on realised profit by {row.uplift_vs_price_insensitive:,.0f} EUR.",
                f"4. Decisions are meaningfully different from the benchmark: weighted high-bid share is {row.high_bid_share_weighted:.2%}, weighted market-cap share is {row.market_cap_bid_share_weighted:.2%}, rejected energy is {row.rejected_energy_mwh:,.1f} MWh, and days near physical max occur on {row.days_near_physical_max_share:.2%} of included days.",
                f"5. Forecast/scenario input adds value, but the dominant floor still comes from the production policy: the benchmark alone captures {row.benchmark_profit_share_of_true_pf_profit:.2%} of true-PF profit, while the stochastic policy captures {row.flexibility_value_captured:.2%} of the incremental flexibility gap.",
                "",
            ]
        )
    save_text(baseline_run_dir, "README_flexibility_value_audit.md", "\n".join(lines))
    return flexibility_value_capture_summary, flexibility_value_capture_by_week, policy_similarity_diagnostics


def _scenario_probability_check(scenario_summary: pd.DataFrame) -> bool:
    if scenario_summary.empty:
        return False
    probs = (
        scenario_summary[["scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["scenario_id"])
        .loc[:, "scenario_probability"]
    )
    return bool(abs(float(pd.to_numeric(probs, errors="coerce").sum()) - 1.0) <= 1e-6)


def _summarize_bid_firmness(submitted_bids: pd.DataFrame) -> dict[str, float]:
    submitted_energy_total = float(pd.to_numeric(submitted_bids["bid_quantity_mw"], errors="coerce").sum())
    if submitted_energy_total <= 0.0:
        return {
            "weighted_average_bid_price": np.nan,
            "high_bid_share": 0.0,
            "market_cap_bid_share": 0.0,
            "high_bid_energy_mwh": 0.0,
            "market_cap_bid_energy_mwh": 0.0,
        }
    bid_prices = pd.to_numeric(submitted_bids["bid_price_eur_per_mwh"], errors="coerce")
    bid_qty = pd.to_numeric(submitted_bids["bid_quantity_mw"], errors="coerce")
    market_cap = float(bid_prices.max())
    high_bid_energy = float(pd.to_numeric(submitted_bids.loc[bid_prices.ge(250.0), "bid_quantity_mw"], errors="coerce").sum())
    market_cap_bid_energy = float(pd.to_numeric(submitted_bids.loc[np.isclose(bid_prices, market_cap), "bid_quantity_mw"], errors="coerce").sum())
    return {
        "weighted_average_bid_price": float((bid_prices * bid_qty).sum() / submitted_energy_total),
        "high_bid_share": float(high_bid_energy / submitted_energy_total),
        "market_cap_bid_share": float(market_cap_bid_energy / submitted_energy_total),
        "high_bid_energy_mwh": float(high_bid_energy),
        "market_cap_bid_energy_mwh": float(market_cap_bid_energy),
    }


def _build_infeasible_daily_metric(
    *,
    run_id: str,
    artifact_id: str,
    model_label: str,
    day_payload: dict[str, Any],
    week_series: pd.Series,
    bounds: Any,
    gamma: float,
    alpha: float,
    inventory_start_kg: float,
    cumulative_before_kg: float,
    payload: dict[str, Any],
    restoration_row: dict[str, Any],
) -> pd.DataFrame:
    scenario_summary = payload["scenario_objective_summary"].copy()
    actual_summary = payload["actual_settlement_results"].iloc[0]
    actual_clearing = payload["actual_clearing"].copy()
    actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
    actual_clearing_by_hour["timestep_hours"] = 1.0
    metrics_row = payload["metrics_summary"].iloc[0]
    skipped = _build_skipped_daily_metric(
        run_id=run_id,
        artifact_id=artifact_id,
        model_label=model_label,
        validation_mode=str(day_payload["validation_mode"]),
        thesis_grade=bool(day_payload["thesis_grade"]),
        forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
        week_row=week_series,
        day_meta=day_payload["day_meta"],
        day_payload=day_payload,
        cvar_alpha=float(alpha),
        cvar_gamma=float(gamma),
        production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
        bounds=bounds,
        cumulative_before_kg=float(cumulative_before_kg),
        skip_reason=str(actual_summary["solver_status"]),
        scenario_count=int(scenario_summary["scenario_id"].astype(str).nunique()),
        scenario_probability_check=_scenario_probability_check(scenario_summary),
        emergency_import_price=0.0,
    )
    firmness = _summarize_bid_firmness(payload["submitted_bids"])
    reconstruction = compute_weighted_cvar_from_frame(
        scenario_summary,
        loss_column="loss_eur",
        probability_column="scenario_probability",
        alpha=float(alpha),
    )
    skipped.update(
        {
            "strategy": "stochastic_bid_risk_neutral" if abs(float(gamma)) <= 1e-12 else "stochastic_bid_cvar",
            "risk_mode": "risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
            "scenario_count": int(scenario_summary["scenario_id"].astype(str).nunique()),
            "scenario_probability_check": _scenario_probability_check(scenario_summary),
            "expected_adjusted_profit": float(metrics_row["expected_adjusted_profit_eur"]),
            "submitted_energy_mwh": float(metrics_row["submitted_energy_mwh"]),
            "cleared_energy_mwh": float(metrics_row["cleared_energy_mwh"]),
            "rejected_energy_mwh": float(metrics_row["rejected_energy_mwh"]),
            "clearing_ratio": float(metrics_row["clearing_ratio"]),
            "rejected_energy_share": float(metrics_row["rejected_energy_mwh"] / metrics_row["submitted_energy_mwh"]) if float(metrics_row["submitted_energy_mwh"]) > 0.0 else 0.0,
            "hours_with_zero_clearing": int(metrics_row["zero_clearing_hours"]),
            "hours_with_partial_clearing": int(metrics_row["partial_clearing_hours"]),
            "weighted_average_bid_price": firmness["weighted_average_bid_price"],
            "high_bid_share": firmness["high_bid_share"],
            "market_cap_bid_share": firmness["market_cap_bid_share"],
            "high_bid_energy_mwh": firmness["high_bid_energy_mwh"],
            "market_cap_bid_energy_mwh": firmness["market_cap_bid_energy_mwh"],
            "worst_scenario_profit": float(pd.to_numeric(scenario_summary["adjusted_profit_eur"], errors="coerce").min()),
            "worst_scenario_loss": float(pd.to_numeric(scenario_summary["loss_eur"], errors="coerce").max()),
            "cvar_tail_profit": float(-reconstruction.cvar),
            "storage_start_kg": float(inventory_start_kg),
            "average_actual_price_paid": float(metrics_row["weighted_average_actual_price_paid_for_cleared_energy"]) if float(metrics_row["cleared_energy_mwh"]) > 0.0 else np.nan,
            "solver_status": str(payload["stochastic_solver_status"]),
            "actual_redispatch_solver_status": str(actual_summary["solver_status"]),
            "actual_redispatch_feasible": False,
            "infeasible_redispatch_days": 1,
            "profit_valid_for_ranking": False,
            "invalid_week_due_to_infeasibility": True,
            "used_cleared_energy_mwh": np.nan,
            "unused_cleared_energy_mwh": np.nan,
            "hydrogen_produced_kg": np.nan,
            "hydrogen_sold_or_compressed_kg": np.nan,
            "storage_end_kg": np.nan,
            "storage_min_kg": np.nan,
            "storage_max_kg": np.nan,
            "reserve_boundary_hits": np.nan,
            "electrolyser_energy_mwh": np.nan,
            "compressor_energy_mwh": np.nan,
            "electrolyser_ramp_hits": np.nan,
            "emergency_import_enabled": False,
            "emergency_import_price_eur_per_mwh": np.nan,
            "emergency_import_mwh": np.nan,
            "emergency_import_cost": np.nan,
            "emergency_import_hours": np.nan,
            "emergency_import_share_of_used_energy": np.nan,
            "minimum_restoration_emergency_mwh": restoration_row.get("minimum_restoration_emergency_mwh"),
            "restoration_cost_at_3000": restoration_row.get("restoration_cost_at_3000"),
            "restoration_hours": restoration_row.get("restoration_hours"),
            "likely_failure_type": restoration_row.get("likely_failure_type"),
        }
    )
    return pd.DataFrame([skipped])


def _build_feasible_daily_metric(
    *,
    run_id: str,
    artifact_id: str,
    model_label: str,
    day_payload: dict[str, Any],
    week_series: pd.Series,
    bounds: Any,
    gamma: float,
    alpha: float,
    cumulative_before_kg: float,
    payload: dict[str, Any],
) -> pd.DataFrame:
    metric = _build_stochastic_daily_metric(
        run_id=run_id,
        artifact_id=artifact_id,
        model_label=model_label,
        validation_mode=str(day_payload["validation_mode"]),
        thesis_grade=bool(day_payload["thesis_grade"]),
        forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
        week_row=week_series,
        day_meta=day_payload["day_meta"],
        payload=payload,
        cvar_alpha=float(alpha),
        cvar_gamma=float(gamma),
        benchmark_profit_row=None,
        perfect_foresight_profit_row=None,
        bounds=bounds,
        cumulative_before_kg=float(cumulative_before_kg),
    )
    actual_summary = payload["actual_settlement_results"].iloc[0]
    import_series = pd.to_numeric(payload["actual_redispatch_timeseries"].get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0)
    metric.update(
        {
            "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            "emergency_import_enabled": False,
            "emergency_import_price_eur_per_mwh": np.nan,
            "emergency_import_mwh": float(actual_summary.get("emergency_import_mwh", float(import_series.sum()))),
            "emergency_import_cost": float(actual_summary.get("emergency_import_cost_eur", 0.0)),
            "emergency_import_hours": int(import_series.gt(1e-9).sum()),
            "emergency_import_share_of_used_energy": 0.0,
            "profit_valid_for_ranking": True,
            "invalid_week_due_to_infeasibility": False,
            "minimum_restoration_emergency_mwh": 0.0,
            "restoration_cost_at_3000": 0.0,
            "restoration_hours": 0,
            "likely_failure_type": "",
        }
    )
    return pd.DataFrame([metric])


def _classify_failure_type(
    *,
    restoration_result: RedispatchSolveResult | None,
    cleared_energy_mwh: float,
    rejected_energy_mwh: float,
    config: HydrogenConfig,
) -> str:
    if restoration_result is None or not _accepted_solver_status(restoration_result.summary.iloc[0]["solver_status"]):
        return "unknown"
    summary = restoration_result.summary.iloc[0]
    timeseries = restoration_result.timeseries.copy()
    restoration_mwh = float(summary.get("emergency_import_mwh", 0.0))
    if restoration_mwh <= 1e-9:
        return "unknown"
    used_energy = float(summary.get("used_energy_mwh", 0.0))
    reserve_floor = float(config.hydrogen_system.reserve_kg)
    if cleared_energy_mwh + 1e-6 < used_energy:
        return "under_clearing"
    if float(summary.get("storage_min_kg", np.inf)) <= reserve_floor + 1e-6:
        return "storage_reserve"
    if bool(
        pd.to_numeric(timeseries["P_el_mw"], errors="coerce").ge(float(config.hydrogen_system.electrolyser_nominal_mw) - 1e-6).any()
        or pd.to_numeric(timeseries["P_comp_mw"], errors="coerce").ge(float(config.hydrogen_system.compressor_max_mw) - 1e-6).any()
    ):
        return "compressor_or_electrolyser_limit"
    if rejected_energy_mwh > 1e-6:
        return "timing_constraint"
    return "unknown"


def _run_restoration_diagnostic(
    *,
    artifact_id: str,
    model_label: str,
    gamma: float,
    week_id: str,
    week_label: str,
    delivery_day: str,
    actual_clearing_by_hour: pd.DataFrame,
    inventory_start_kg: float,
    bounds: Any,
    config: HydrogenConfig,
    run_dir: Path,
) -> dict[str, Any]:
    restoration = solve_actual_redispatch_from_cleared_energy(
        actual_clearing_by_hour,
        config=config,
        inventory_start_kg=float(inventory_start_kg),
        reserve_kg=float(config.hydrogen_system.reserve_kg),
        target_hydrogen_kg=float(bounds.daily_lower_bound_kg),
        target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
        terminal_reference_start_kg=float(inventory_start_kg),
        production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
        emergency_import_price_eur_per_mwh=float(RESTORATION_EMERGENCY_IMPORT_PRICE_EUR_PER_MWH),
        solver_log_path=run_dir / "cache" / f"{week_id}__{delivery_day}__g{str(gamma).replace('.', 'p')}__restoration_solver_log.txt",
    )
    summary = restoration.summary.iloc[0]
    cleared_energy = float(pd.to_numeric(actual_clearing_by_hour["cleared_energy_mwh"], errors="coerce").sum())
    rejected_energy = float(pd.to_numeric(actual_clearing_by_hour["submitted_energy_mwh"], errors="coerce").sum() - cleared_energy) if "submitted_energy_mwh" in actual_clearing_by_hour.columns else np.nan
    row = {
        "artifact_id": artifact_id,
        "model_label": model_label,
        "gamma": float(gamma),
        "delivery_day": str(delivery_day),
        "accounting_week_id": str(week_id),
        "week_label": str(week_label),
        "redispatch_status": str(summary["solver_status"]),
        "cleared_energy_mwh": cleared_energy,
        "rejected_energy_mwh": rejected_energy,
        "used_energy_mwh": float(summary["used_energy_mwh"]) if _accepted_solver_status(summary["solver_status"]) else np.nan,
        "storage_start_kg": float(inventory_start_kg),
        "storage_min_kg": float(summary["storage_min_kg"]) if _accepted_solver_status(summary["solver_status"]) else np.nan,
        "weekly_target_remaining_kg": float(bounds.remaining_target_before_today_kg),
        "minimum_restoration_emergency_mwh": float(summary["emergency_import_mwh"]) if _accepted_solver_status(summary["solver_status"]) else np.nan,
        "restoration_cost_at_3000": float(summary["emergency_import_cost_eur"]) if _accepted_solver_status(summary["solver_status"]) else np.nan,
        "restoration_hours": int(pd.to_numeric(restoration.timeseries.get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0).gt(1e-9).sum()) if _accepted_solver_status(summary["solver_status"]) else np.nan,
        "likely_failure_type": _classify_failure_type(
            restoration_result=restoration,
            cleared_energy_mwh=cleared_energy,
            rejected_energy_mwh=rejected_energy,
            config=config,
        ),
    }
    return row


def _build_weekly_metrics_no_fallback(
    *,
    daily_metrics: pd.DataFrame,
    week_manifest: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if daily_metrics.empty:
        return pd.DataFrame()
    for _, week_row in week_manifest.iterrows():
        week_days = set(week_row["included_delivery_days"])
        group = daily_metrics.loc[daily_metrics["delivery_day"].astype(str).isin(week_days)].copy()
        if group.empty:
            continue
        for gamma, gamma_group in group.groupby(pd.to_numeric(group["cvar_gamma"], errors="coerce"), sort=True):
            feasible = gamma_group.loc[gamma_group["profit_valid_for_ranking"].astype(bool)].copy()
            week_valid = bool(feasible.shape[0] == int(week_row["included_delivery_day_count"]) and gamma_group["actual_redispatch_feasible"].astype(bool).all())
            rows.append(
                {
                    "artifact_id": str(gamma_group["artifact_id"].iloc[0]),
                    "model_label": str(gamma_group["model_label"].iloc[0]),
                    "cvar_gamma": float(gamma),
                    "week_id": str(week_row["week_id"]),
                    "week_label": str(week_row["week_label"]),
                    "week_start": str(week_row["week_start"]),
                    "week_end": str(week_row["week_end"]),
                    "included_delivery_day_count": int(week_row["included_delivery_day_count"]),
                    "is_partial_week": bool(week_row["is_partial_week"]),
                    "aggregation_level": "weekly",
                    "strategy": str(gamma_group["strategy"].iloc[0]),
                    "risk_mode": str(gamma_group["risk_mode"].iloc[0]),
                    "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                    "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                    "cvar_alpha": float(gamma_group["cvar_alpha"].iloc[0]),
                    "number_of_delivery_days": int(gamma_group.shape[0]),
                    "feasible_day_count": int(feasible.shape[0]),
                    "infeasible_day_count": int((~gamma_group["actual_redispatch_feasible"].astype(bool)).sum()),
                    "skipped_day_count": int(gamma_group["actual_redispatch_solver_status"].astype(str).eq("not_run_after_prior_infeasible_redispatch").sum()),
                    "week_valid_for_profit_ranking": bool(week_valid),
                    "realised_adjusted_profit_feasible_days_only": float(pd.to_numeric(feasible["realised_adjusted_profit"], errors="coerce").sum()),
                    "expected_adjusted_profit_feasible_days_only": float(pd.to_numeric(feasible["expected_adjusted_profit"], errors="coerce").sum()),
                    "submitted_energy_mwh": float(pd.to_numeric(gamma_group["submitted_energy_mwh"], errors="coerce").sum()),
                    "cleared_energy_mwh": float(pd.to_numeric(gamma_group["cleared_energy_mwh"], errors="coerce").sum()),
                    "rejected_energy_mwh": float(pd.to_numeric(gamma_group["rejected_energy_mwh"], errors="coerce").sum()),
                    "used_cleared_energy_mwh_feasible_days_only": float(pd.to_numeric(feasible["used_cleared_energy_mwh"], errors="coerce").sum()),
                    "unused_cleared_energy_mwh_feasible_days_only": float(pd.to_numeric(feasible["unused_cleared_energy_mwh"], errors="coerce").sum()),
                    "clearing_ratio_mean": float(pd.to_numeric(gamma_group["clearing_ratio"], errors="coerce").mean()),
                    "average_actual_price_paid_feasible_days_only": float(pd.to_numeric(feasible["da_settlement_cost"], errors="coerce").sum() / pd.to_numeric(feasible["cleared_energy_mwh"], errors="coerce").sum()) if float(pd.to_numeric(feasible["cleared_energy_mwh"], errors="coerce").sum()) > 0.0 else np.nan,
                    "hydrogen_sold_or_compressed_kg_feasible_days_only": float(pd.to_numeric(feasible["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                    "high_bid_share_weighted": _weighted_mean(gamma_group["high_bid_share"], gamma_group["submitted_energy_mwh"]),
                    "market_cap_bid_share_weighted": _weighted_mean(gamma_group["market_cap_bid_share"], gamma_group["submitted_energy_mwh"]),
                    "cvar_tail_profit_feasible_days_only": float(pd.to_numeric(feasible["cvar_tail_profit"], errors="coerce").sum()),
                    "worst_scenario_profit_any_solved_day": float(pd.to_numeric(gamma_group["worst_scenario_profit"], errors="coerce").min()) if gamma_group["worst_scenario_profit"].notna().any() else np.nan,
                    "weekly_target_kg": float(pd.to_numeric(gamma_group["weekly_target_kg"], errors="coerce").iloc[0]),
                    "weekly_target_met": bool(week_valid and pd.to_numeric(feasible["hydrogen_sold_or_compressed_kg"], errors="coerce").sum() + 1e-6 >= float(pd.to_numeric(gamma_group["weekly_target_kg"], errors="coerce").iloc[0])),
                    "invalid_week_due_to_infeasibility": bool(not week_valid),
                }
            )
    return pd.DataFrame(rows).sort_values(["cvar_gamma", "week_start"]).reset_index(drop=True)


def _build_annual_metrics_no_fallback(
    *,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    restoration_diagnostics: pd.DataFrame,
    runtime_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if daily_metrics.empty:
        return pd.DataFrame()
    if restoration_diagnostics.empty or "gamma" not in restoration_diagnostics.columns:
        restoration_diagnostics = pd.DataFrame(
            columns=[
                "gamma",
                "minimum_restoration_emergency_mwh",
                "restoration_cost_at_3000",
                "restoration_hours",
            ]
        )
    for gamma, group in daily_metrics.groupby(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce"), sort=True):
        feasible = group.loc[group["profit_valid_for_ranking"].astype(bool)].copy()
        weekly_group = weekly_metrics.loc[pd.to_numeric(weekly_metrics["cvar_gamma"], errors="coerce").eq(float(gamma))].copy()
        restoration_group = restoration_diagnostics.loc[pd.to_numeric(restoration_diagnostics["gamma"], errors="coerce").eq(float(gamma))].copy()
        valid_weeks = weekly_group.loc[weekly_group["week_valid_for_profit_ranking"].astype(bool)].copy()
        rows.append(
            {
                "gamma": float(gamma),
                "annual_feasible_days_only_realised_profit": float(pd.to_numeric(feasible["realised_adjusted_profit"], errors="coerce").sum()),
                "annual_feasible_days_only_expected_profit": float(pd.to_numeric(feasible["expected_adjusted_profit"], errors="coerce").sum()),
                "annual_valid_weeks_only_realised_profit": float(pd.to_numeric(valid_weeks["realised_adjusted_profit_feasible_days_only"], errors="coerce").sum()),
                "feasible_day_count": int(feasible.shape[0]),
                "infeasible_day_count": int((~group["actual_redispatch_feasible"].astype(bool)).sum()),
                "skipped_day_count": int(group["actual_redispatch_solver_status"].astype(str).eq("not_run_after_prior_infeasible_redispatch").sum()),
                "invalid_week_count": int((~weekly_group["week_valid_for_profit_ranking"].astype(bool)).sum()),
                "valid_week_count": int(weekly_group["week_valid_for_profit_ranking"].astype(bool).sum()),
                "all_days_feasible": bool(group["actual_redispatch_feasible"].astype(bool).all()),
                "total_rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "total_unused_cleared_energy_mwh_feasible_only": float(pd.to_numeric(feasible["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "mean_clearing_ratio": float(pd.to_numeric(group["clearing_ratio"], errors="coerce").mean()),
                "average_actual_price_paid_feasible_only": float(pd.to_numeric(feasible["da_settlement_cost"], errors="coerce").sum() / pd.to_numeric(feasible["cleared_energy_mwh"], errors="coerce").sum()) if float(pd.to_numeric(feasible["cleared_energy_mwh"], errors="coerce").sum()) > 0.0 else np.nan,
                "worst_feasible_week_profit": float(pd.to_numeric(valid_weeks["realised_adjusted_profit_feasible_days_only"], errors="coerce").min()) if not valid_weeks.empty else np.nan,
                "cvar_tail_profit_feasible_days_only": float(pd.to_numeric(feasible["cvar_tail_profit"], errors="coerce").sum()),
                "worst_scenario_profit_any_solved_day": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()) if group["worst_scenario_profit"].notna().any() else np.nan,
                "posthoc_minimum_restoration_emergency_mwh": float(pd.to_numeric(restoration_group["minimum_restoration_emergency_mwh"], errors="coerce").sum()) if not restoration_group.empty else 0.0,
                "posthoc_restoration_cost_at_3000": float(pd.to_numeric(restoration_group["restoration_cost_at_3000"], errors="coerce").sum()) if not restoration_group.empty else 0.0,
                "posthoc_restoration_hours": int(pd.to_numeric(restoration_group["restoration_hours"], errors="coerce").fillna(0.0).sum()) if not restoration_group.empty else 0,
                "weekly_targets_met_all_valid_weeks": bool(valid_weeks["weekly_target_met"].astype(bool).all()) if not valid_weeks.empty else False,
                "total_runtime_seconds": float(
                    pd.to_numeric(
                        runtime_diagnostics.loc[
                            runtime_diagnostics["solve_stage"].astype(str).eq("stochastic_bidding_day")
                            & pd.to_numeric(runtime_diagnostics["gamma"], errors="coerce").eq(float(gamma)),
                            "wall_time_seconds",
                        ],
                        errors="coerce",
                    ).sum()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("gamma").reset_index(drop=True)


def _write_no_fallback_readme(
    *,
    run_dir: Path,
    annual_metrics_by_gamma: pd.DataFrame,
    infeasibility_report: pd.DataFrame,
    restoration_diagnostics: pd.DataFrame,
) -> None:
    lines = ["# Fallback OFF Diagnostic", ""]
    for row in annual_metrics_by_gamma.itertuples():
        lines.extend(
            [
                f"## Gamma {row.gamma:.2f}",
                "",
                f"- Feasible-days-only realised profit: {row.annual_feasible_days_only_realised_profit:,.0f} EUR.",
                f"- Feasible days: {int(row.feasible_day_count)}.",
                f"- Infeasible days: {int(row.infeasible_day_count)}.",
                f"- Invalid weeks: {int(row.invalid_week_count)}.",
                f"- Post-hoc minimum restoration emergency: {row.posthoc_minimum_restoration_emergency_mwh:,.3f} MWh costing {row.posthoc_restoration_cost_at_3000:,.0f} EUR.",
                "",
            ]
        )
    if not infeasibility_report.empty:
        lines.append("Affected weeks were invalidated after the first infeasible redispatch day and the state was reset only at the next accounting week.")
    save_text(run_dir, "README_fallback_off_diagnostic.md", "\n".join(lines))


def _build_on_off_comparison(
    *,
    baseline_run_dir: Path,
    off_run_dir: Path,
    off_weekly_metrics: pd.DataFrame,
    off_annual_metrics: pd.DataFrame,
    off_restoration_diagnostics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    on_annual = pd.read_csv(baseline_run_dir / "annual_metrics_by_gamma_with_true_pf.csv")
    on_weekly = pd.read_csv(baseline_run_dir / "weekly_metrics.csv")

    annual = on_annual.merge(
        off_annual_metrics,
        left_on="gamma",
        right_on="gamma",
        how="outer",
        suffixes=("_fallback_on", "_fallback_off"),
    )
    def _num(frame: pd.DataFrame, column: str) -> pd.Series:
        return pd.to_numeric(frame[column], errors="coerce") if column in frame.columns else pd.Series(np.nan, index=frame.index)

    annual["fallback_on_annual_realised_profit"] = pd.to_numeric(annual["annual_realised_adjusted_profit"], errors="coerce")
    annual["fallback_off_feasible_days_only_realised_profit"] = pd.to_numeric(annual["annual_feasible_days_only_realised_profit"], errors="coerce")
    annual["fallback_off_infeasible_day_count"] = _num(annual, "infeasible_day_count")
    annual["fallback_off_infeasible_week_count"] = _num(annual, "invalid_week_count")
    annual["fallback_on_emergency_import_mwh"] = _num(annual, "total_emergency_import_mwh")
    annual["fallback_off_posthoc_minimum_restoration_emergency_mwh"] = _num(annual, "posthoc_minimum_restoration_emergency_mwh")
    annual["fallback_on_emergency_cost"] = _num(annual, "emergency_import_cost")
    annual["fallback_off_posthoc_restoration_cost"] = _num(annual, "posthoc_restoration_cost_at_3000")
    annual["fallback_on_rejected_energy_mwh"] = _num(annual, "total_rejected_energy")
    annual["fallback_off_rejected_energy_mwh"] = _num(annual, "total_rejected_energy_mwh")
    annual["fallback_on_unused_energy_mwh"] = _num(annual, "total_unused_cleared_energy")
    annual["fallback_off_unused_energy_mwh"] = _num(annual, "total_unused_cleared_energy_mwh_feasible_only")
    annual["fallback_on_clearing_ratio"] = _num(annual, "mean_clearing_ratio_fallback_on").combine_first(_num(annual, "mean_clearing_ratio"))
    annual["fallback_off_clearing_ratio"] = _num(annual, "mean_clearing_ratio_fallback_off").combine_first(_num(annual, "mean_clearing_ratio"))
    annual["fallback_off_worst_feasible_week_profit"] = _num(annual, "worst_feasible_week_profit")
    annual["invalid_weeks_due_to_infeasibility"] = _num(annual, "invalid_week_count")
    annual["fallback_off_cvar_tail_profit_if_available"] = _num(annual, "cvar_tail_profit_feasible_days_only")
    annual["fallback_off_worst_scenario_profit_if_available"] = _num(annual, "worst_scenario_profit_any_solved_day")
    annual["fallback_preference"] = np.where(
        pd.to_numeric(annual["fallback_off_infeasible_day_count"], errors="coerce").fillna(0).gt(0)
        | pd.to_numeric(annual["fallback_off_infeasible_week_count"], errors="coerce").fillna(0).gt(0),
        "fallback_on",
        np.where(
            pd.to_numeric(annual["fallback_off_feasible_days_only_realised_profit"], errors="coerce")
            > pd.to_numeric(annual["fallback_on_annual_realised_profit"], errors="coerce") + 1e-6,
            "fallback_off",
            "fallback_on",
        ),
    )
    annual["ranking_warning"] = np.where(
        pd.to_numeric(annual["fallback_off_infeasible_day_count"], errors="coerce").fillna(0).gt(0),
        "do_not_rank_fallback_off_above_fallback_on_by_profit_alone",
        "",
    )

    weekly = on_weekly.merge(
        off_weekly_metrics,
        on=["week_id", "cvar_gamma"],
        how="outer",
        suffixes=("_fallback_on", "_fallback_off"),
    )
    weekly["gamma"] = pd.to_numeric(weekly["cvar_gamma"], errors="coerce")

    summary_rows: list[dict[str, Any]] = []
    annual_by_gamma = annual.sort_values("gamma")
    if not annual_by_gamma.empty:
        for row in annual_by_gamma.itertuples():
            summary_rows.append(
                {
                    "scope": "gamma",
                    "gamma": float(row.gamma),
                    "fallback_needed_for_feasibility": bool((pd.notna(row.fallback_off_infeasible_day_count) and float(row.fallback_off_infeasible_day_count) > 0.0) or (pd.notna(row.fallback_off_infeasible_week_count) and float(row.fallback_off_infeasible_week_count) > 0.0)),
                    "fallback_preference": str(row.fallback_preference),
                    "fallback_on_annual_realised_profit": float(row.fallback_on_annual_realised_profit) if pd.notna(row.fallback_on_annual_realised_profit) else np.nan,
                    "fallback_off_feasible_days_only_realised_profit": float(row.fallback_off_feasible_days_only_realised_profit) if pd.notna(row.fallback_off_feasible_days_only_realised_profit) else np.nan,
                    "fallback_on_emergency_import_mwh": float(row.fallback_on_emergency_import_mwh) if pd.notna(row.fallback_on_emergency_import_mwh) else np.nan,
                    "fallback_off_posthoc_minimum_restoration_emergency_mwh": float(row.fallback_off_posthoc_minimum_restoration_emergency_mwh) if pd.notna(row.fallback_off_posthoc_minimum_restoration_emergency_mwh) else np.nan,
                    "ranking_warning": str(row.ranking_warning),
                }
            )
    if annual_by_gamma.shape[0] >= 2:
        on_delta = float(pd.to_numeric(annual_by_gamma["annual_realised_adjusted_profit"], errors="coerce").diff().iloc[-1])
        off_delta = float(pd.to_numeric(annual_by_gamma["annual_feasible_days_only_realised_profit"], errors="coerce").diff().iloc[-1])
        on_restoration_proxy = float(pd.to_numeric(annual_by_gamma["total_emergency_import_mwh"], errors="coerce").diff().iloc[-1])
        off_restoration_proxy = float(pd.to_numeric(annual_by_gamma["posthoc_minimum_restoration_emergency_mwh"], errors="coerce").diff().iloc[-1])
        off_infeasible_delta = float(pd.to_numeric(annual_by_gamma["infeasible_day_count"], errors="coerce").diff().iloc[-1])
        summary_rows.append(
            {
                "scope": "overall",
                "gamma": np.nan,
                "fallback_needed_for_feasibility": bool(pd.to_numeric(annual_by_gamma["infeasible_day_count"], errors="coerce").fillna(0.0).gt(0.0).any()),
                "fallback_preference": "fallback_on" if pd.to_numeric(annual_by_gamma["infeasible_day_count"], errors="coerce").fillna(0.0).gt(0.0).any() else "compare_both",
                "cvar_more_useful_without_fallback": bool(
                    (off_delta > on_delta + 1e-6)
                    and (off_restoration_proxy < on_restoration_proxy - 1e-6)
                    and (off_infeasible_delta <= 1e-6)
                ),
                "thesis_default": "keep_fallback_on" if pd.to_numeric(annual_by_gamma["infeasible_day_count"], errors="coerce").fillna(0.0).gt(0.0).any() else "conditional",
                "warning": "Fallback OFF has infeasible days; do not rank it above fallback ON by profit alone." if pd.to_numeric(annual_by_gamma["infeasible_day_count"], errors="coerce").fillna(0.0).gt(0.0).any() else "",
            }
        )

    summary = pd.DataFrame(summary_rows)
    save_frame_csv(off_run_dir, "fallback_on_off_annual_comparison.csv", annual)
    save_frame_csv(off_run_dir, "fallback_on_off_weekly_comparison.csv", weekly)
    save_frame_csv(off_run_dir, "fallback_on_off_diagnostic_summary.csv", summary)

    readme_lines = ["# Fallback ON/OFF Comparison", ""]
    def _safe_int(value: Any) -> str:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return "n/a" if pd.isna(numeric) else str(int(numeric))

    for row in annual.sort_values("gamma").itertuples():
        readme_lines.extend(
            [
                f"## Gamma {row.gamma:.2f}",
                "",
                f"- Fallback ON realised profit: {float(row.fallback_on_annual_realised_profit):,.0f} EUR." if pd.notna(row.fallback_on_annual_realised_profit) else "- Fallback ON realised profit: n/a.",
                f"- Fallback OFF feasible-days-only realised profit: {float(row.fallback_off_feasible_days_only_realised_profit):,.0f} EUR." if pd.notna(row.fallback_off_feasible_days_only_realised_profit) else "- Fallback OFF feasible-days-only realised profit: n/a.",
                f"- Fallback OFF infeasible days: {_safe_int(row.fallback_off_infeasible_day_count)}.",
                f"- Fallback OFF invalid weeks: {_safe_int(row.fallback_off_infeasible_week_count)}.",
                f"- Fallback ON emergency import: {float(row.fallback_on_emergency_import_mwh):,.3f} MWh costing {float(row.fallback_on_emergency_cost):,.0f} EUR." if pd.notna(row.fallback_on_emergency_import_mwh) else "- Fallback ON emergency import: n/a.",
                f"- Fallback OFF post-hoc restoration burden: {float(row.fallback_off_posthoc_minimum_restoration_emergency_mwh):,.3f} MWh costing {float(row.fallback_off_posthoc_restoration_cost):,.0f} EUR." if pd.notna(row.fallback_off_posthoc_minimum_restoration_emergency_mwh) else "- Fallback OFF post-hoc restoration burden: n/a.",
                f"- Preferred default for this gamma: {row.fallback_preference}.",
                "",
            ]
        )
    if not summary.empty:
        overall = summary.loc[summary["scope"].astype(str).eq("overall")].head(1)
        if not overall.empty:
            overall_row = overall.iloc[0]
            readme_lines.append(f"Overall thesis default: {overall_row.get('thesis_default', '')}.")
            warning = str(overall_row.get("warning", "")).strip()
            if warning:
                readme_lines.append(warning)
    save_text(off_run_dir, "README_fallback_on_off_diagnostic.md", "\n".join(readme_lines))
    return annual, weekly, summary


def load_hydrogen_config(config_or_path: HydrogenConfig | str | Path) -> HydrogenConfig:
    if isinstance(config_or_path, HydrogenConfig):
        return config_or_path
    from .plant_parameters import load_hydrogen_config as _load

    return _load(config_or_path)


def run_full_year_no_fallback_diagnostic(
    *,
    config: HydrogenConfig | str | Path,
    artifact_id: str,
    test_start: str,
    test_end: str,
    alpha: float,
    gammas: list[float] | tuple[float, ...],
    target_mode: str,
    target_accounting_policy: str,
    emergency_import_mode: str,
    reporting_mode: str,
    safe_resume: bool,
    run_slug: str,
    output_root: Path | None = None,
    resume_run_dir: Path | None = None,
    chunk_start: str | None = None,
    chunk_end: str | None = None,
    max_new_solves: int | None = None,
    checkpoint_every_n_solves: int = 10,
    baseline_run_dir: Path = DEFAULT_PHASE_E5_BASELINE_RUN_DIR,
    build_true_pf_no_fallback: bool = True,
) -> PhaseE5cNoFallbackResult:
    if str(target_mode) != PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF:
        raise ValueError(f"E5c no-fallback diagnostic requires target_mode={PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF!r}.")
    if str(emergency_import_mode).strip().lower() != "off":
        raise ValueError("E5c no-fallback diagnostic requires emergency_import_mode='off'.")
    if str(reporting_mode).strip().lower() != "machine_only":
        raise ValueError("E5c no-fallback diagnostic requires reporting_mode='machine_only'.")
    target_accounting_policy = validate_target_accounting_policy(target_accounting_policy)
    if target_accounting_policy != TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET:
        raise ValueError(
            "E5c no-fallback diagnostic requires target_accounting_policy='included_day_prorated_weekly_target'."
        )
    gamma_values = [float(value) for value in gammas]
    checkpoint_every_n_solves = max(int(checkpoint_every_n_solves), 1)

    suite_config = _build_phase_e4_config(
        config,
        artifact_ids=[str(artifact_id)],
        output_root=output_root,
        run_slug=str(run_slug),
    )
    suite_config = replace(
        suite_config,
        experiment=replace(
            suite_config.experiment,
            name=str(run_slug),
            execution_mode="full_year_no_fallback_diagnostic",
        ),
        outputs=replace(suite_config.outputs, save_figures=False),
    )

    baseline_run_dir = Path(baseline_run_dir)
    flexibility_value_capture_summary, flexibility_value_capture_by_week, policy_similarity_diagnostics = run_flexibility_value_audit(
        baseline_run_dir=baseline_run_dir,
        config=suite_config,
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

    scenarios, registry, selected_daily, spec, _support_source = _load_or_build_support_cache(
        run_dir=run_dir,
        config=suite_config,
        artifact_id=artifact_id,
    )
    support_preflight, _expected_days, dst_excluded_days = _build_support_preflight(
        artifact_id=artifact_id,
        config=suite_config,
        spec=spec,
        selected_daily=selected_daily,
        registry=registry,
        test_start=str(test_start),
        test_end=str(test_end),
        alpha=float(alpha),
        gamma_values=gamma_values,
        target_mode=str(target_mode),
        target_accounting_policy=str(target_accounting_policy),
    )

    save_config_resolved(run_dir, suite_config)
    save_inputs_manifest(run_dir, [suite_config.config_path, suite_config.models.scenario_catalog, spec.path])
    input_manifest = build_inputs_manifest([suite_config.config_path, suite_config.models.scenario_catalog, spec.path])
    input_manifest.update(
        {
            "artifact_id": str(artifact_id),
            "test_start": str(test_start),
            "test_end": str(test_end),
            "alpha": float(alpha),
            "gammas": gamma_values,
            "target_mode": str(target_mode),
            "target_accounting_policy": str(target_accounting_policy),
            "emergency_import_mode": "off",
            "reporting_mode": str(reporting_mode),
            "safe_resume": bool(safe_resume),
            "chunk_start": str(chunk_start) if chunk_start else None,
            "chunk_end": str(chunk_end) if chunk_end else None,
            "max_new_solves": None if max_new_solves is None else int(max_new_solves),
            "checkpoint_every_n_solves": int(checkpoint_every_n_solves),
            "baseline_run_dir": str(baseline_run_dir),
            "build_true_pf_no_fallback": bool(build_true_pf_no_fallback),
        }
    )
    save_json(run_dir, "input_manifest.json", input_manifest)
    save_frame_csv(run_dir, "support_preflight.csv", support_preflight)

    if (support_preflight["status"].astype(str) == "fail").any():
        raise RuntimeError("E5c support preflight failed. See support_preflight.csv.")

    selected_in_period = selected_daily.loc[selected_daily["delivery_day"].astype(str).between(str(test_start), str(test_end))].copy()
    included_days = sorted(selected_in_period["delivery_day"].astype(str).tolist())
    save_json(
        run_dir,
        "selected_artifact_manifest.json",
        _build_selected_artifact_manifest(
            config=suite_config,
            artifact_id=artifact_id,
            spec=spec,
            selected_daily=selected_in_period,
            test_start=str(test_start),
            test_end=str(test_end),
            included_days=included_days,
            dst_excluded_days=dst_excluded_days,
        ),
    )

    physical_daily_max_kg = _physical_daily_max_kg(suite_config)
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(suite_config.economics.daily_target_kg),
        daily_min_fraction=0.0,
        daily_max_fraction=float(physical_daily_max_kg / suite_config.economics.daily_target_kg),
        target_accounting_policy=str(target_accounting_policy),
    )
    save_json(
        run_dir,
        "production_target_manifest.json",
        {
            "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            "model_target_formulation": TARGET_MODE_WEEKLY_HARD_BAND,
            "weekly_target_hard": True,
            "weekly_target_kg": float(settings.weekly_target_kg),
            "daily_target_kg": float(settings.daily_target_kg),
            "daily_min_fraction": 0.0,
            "daily_min_kg": 0.0,
            "physical_daily_max_kg": float(physical_daily_max_kg),
            "shortfall_slack_allowed": False,
            "emergency_import_enabled": False,
            "week_definition": "calendar_monday_sunday_intersected_with_test_period_after_dst_exclusions",
            "target_accounting_policy": str(target_accounting_policy),
        },
    )
    save_json(run_dir, "cvar_settings_manifest.json", {"alpha": float(alpha), "gammas": gamma_values})

    target_accounting_frame = build_included_day_prorated_weekly_accounting(
        included_delivery_days=included_days,
        daily_target_kg=float(settings.daily_target_kg),
        excluded_day_reasons=build_weekly_accounting_exclusion_reason_map(
            included_delivery_days=included_days,
            explicit_exclusions=[{**item, "reason": "dst_excluded"} for item in dst_excluded_days],
        ),
        target_accounting_policy=str(target_accounting_policy),
    )
    target_accounting_lookup = build_production_accounting_lookup(target_accounting_frame)
    week_manifest = _week_manifest_from_days(included_days)

    scenarios = scenarios.copy()
    scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True, errors="raise")
    scenarios["delivery_start_utc"] = pd.to_datetime(scenarios["delivery_start_utc"], utc=True, errors="raise")
    reference_days: dict[str, dict[str, Any]] = {}
    for row in selected_in_period.sort_values(["delivery_day", "forecast_origin_utc"]).to_dict(orient="records"):
        delivery_day = str(row["delivery_day"])
        origin = pd.Timestamp(row["forecast_origin_utc"])
        reference_days[delivery_day] = {
            "day_meta": row,
            "forecast_origin_utc": origin,
            "scenarios": scenarios.loc[scenarios["forecast_origin_utc"].eq(origin)].copy().sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True),
            "model_id": str(row.get("model_id", spec.model_id)),
            "model_label": str(row["model_label"]),
            "validation_mode": str(row["validation_mode"]),
            "thesis_grade": bool(row.get("thesis_grade", True)),
            "forecast_origin_reconstruction_used": bool(row.get("forecast_origin_reconstruction_used", False)),
        }

    cache_dir = run_dir / "cache"
    checkpoint_store = _load_checkpoint_store(cache_dir)
    pending_store: dict[str, list[pd.DataFrame] | list[dict[str, Any]]] = {
        "registry": [],
        "daily_metrics": [],
        "actual_settlement": [],
        "scenario_settlement": [],
        "actual_clearing": [],
        "submitted_bids": [],
        "scenario_clearing": [],
        "weekly_tracker": [],
        "runtime_diagnostics": [],
        "infeasibility_report": [],
        "restoration_diagnostics": [],
    }

    completed_keys = {
        (
            str(row["artifact_id"]),
            float(pd.to_numeric(pd.Series([row["cvar_gamma"]]), errors="coerce").iloc[0]),
            str(row["delivery_day"]),
        )
        for _, row in checkpoint_store["daily_metrics"].iterrows()
        if pd.notna(pd.to_numeric(pd.Series([row.get("cvar_gamma")]), errors="coerce").iloc[0])
    }
    chunk_start_day = str(chunk_start) if chunk_start else None
    chunk_end_day = str(chunk_end) if chunk_end else None
    new_solve_count = 0
    pending_commit_count = 0
    stop_requested = False

    try:
        for gamma in gamma_values:
            for _, week_row in week_manifest.iterrows():
                week_id = str(week_row["week_id"])
                week_label = str(week_row["week_label"])
                week_series = pd.Series(
                    {
                        "week_id": week_id,
                        "week_label": week_label,
                        "regime_label": "full_year_test",
                        "selection_reason": "full_year_calendar_week",
                    }
                )
                inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
                cumulative = 0.0
                block_remaining_days = False
                for delivery_day in list(week_row["included_delivery_days"]):
                    day_key = (str(artifact_id), float(gamma), str(delivery_day))
                    if day_key in completed_keys:
                        continue
                    if chunk_start_day and str(delivery_day) < chunk_start_day:
                        raise RuntimeError(
                            f"Cannot start chunk at {chunk_start_day}: prerequisite delivery day {delivery_day} for gamma={gamma:.2f} is missing."
                        )
                    if chunk_end_day and str(delivery_day) > chunk_end_day:
                        stop_requested = True
                        break
                    if max_new_solves is not None and new_solve_count >= int(max_new_solves):
                        stop_requested = True
                        break

                    day_payload = reference_days[str(delivery_day)]
                    cumulative_before = float(cumulative)
                    inventory_before = float(inventory_start)
                    bounds = _compute_variant_bounds(
                        settings=settings,
                        production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        cumulative_realised_h2_kg_before_today=float(cumulative_before),
                        days_remaining_in_week=None,
                        physical_daily_max_kg=float(physical_daily_max_kg),
                        accounting_day=target_accounting_lookup[str(delivery_day)],
                    )

                    if not bool(bounds.tracker_feasible):
                        metric_row = _build_skipped_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            validation_mode=str(day_payload["validation_mode"]),
                            thesis_grade=bool(day_payload["thesis_grade"]),
                            forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                            week_row=week_series,
                            day_meta=day_payload["day_meta"],
                            day_payload=day_payload,
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                            bounds=bounds,
                            cumulative_before_kg=float(cumulative_before),
                            skip_reason="warning:infeasible_weekly_target_bounds",
                            scenario_count=int(day_payload["scenarios"]["scenario_id"].astype(str).nunique()),
                            scenario_probability_check=True,
                            emergency_import_price=0.0,
                        )
                        metric_row.update(
                            {
                                "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                "emergency_import_enabled": False,
                                "profit_valid_for_ranking": False,
                                "invalid_week_due_to_infeasibility": True,
                            }
                        )
                        pending_store["daily_metrics"].append(pd.DataFrame([metric_row]))
                        pending_store["infeasibility_report"].append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": _label_for_artifact(artifact_id),
                                "gamma": float(gamma),
                                "delivery_day": str(delivery_day),
                                "accounting_week_id": str(week_id),
                                "record_type": "infeasible_week",
                                "redispatch_status": "warning:infeasible_weekly_target_bounds",
                                "infeasibility_reason": "tracker_feasible_false",
                                "cleared_energy_mwh": np.nan,
                                "rejected_energy_mwh": np.nan,
                                "used_energy_mwh": np.nan,
                                "storage_start_kg": float(inventory_before),
                                "storage_min_kg": np.nan,
                                "weekly_target_remaining_kg": float(bounds.remaining_target_before_today_kg),
                                "minimum_restoration_emergency_mwh": np.nan,
                                "restoration_cost_at_3000": np.nan,
                                "restoration_hours": np.nan,
                                "likely_failure_type": "unknown",
                            }
                        )
                        block_remaining_days = True
                        completed_keys.add(day_key)
                        pending_commit_count += 1
                        continue

                    if block_remaining_days:
                        metric_row = _build_skipped_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            validation_mode=str(day_payload["validation_mode"]),
                            thesis_grade=bool(day_payload["thesis_grade"]),
                            forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                            week_row=week_series,
                            day_meta=day_payload["day_meta"],
                            day_payload=day_payload,
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                            bounds=bounds,
                            cumulative_before_kg=float(cumulative_before),
                            skip_reason="not_run_after_prior_infeasible_redispatch",
                            scenario_count=int(day_payload["scenarios"]["scenario_id"].astype(str).nunique()),
                            scenario_probability_check=True,
                            emergency_import_price=0.0,
                        )
                        metric_row.update(
                            {
                                "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                "emergency_import_enabled": False,
                                "profit_valid_for_ranking": False,
                                "invalid_week_due_to_infeasibility": True,
                            }
                        )
                        pending_store["daily_metrics"].append(pd.DataFrame([metric_row]))
                        pending_store["infeasibility_report"].append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": _label_for_artifact(artifact_id),
                                "gamma": float(gamma),
                                "delivery_day": str(delivery_day),
                                "accounting_week_id": str(week_id),
                                "record_type": "invalid_week_tail_day",
                                "redispatch_status": "not_run_after_prior_infeasible_redispatch",
                                "infeasibility_reason": "later_days_in_same_week_not_run",
                                "cleared_energy_mwh": np.nan,
                                "rejected_energy_mwh": np.nan,
                                "used_energy_mwh": np.nan,
                                "storage_start_kg": float(inventory_before),
                                "storage_min_kg": np.nan,
                                "weekly_target_remaining_kg": float(bounds.remaining_target_before_today_kg),
                                "minimum_restoration_emergency_mwh": np.nan,
                                "restoration_cost_at_3000": np.nan,
                                "restoration_hours": np.nan,
                                "likely_failure_type": "unknown",
                            }
                        )
                        completed_keys.add(day_key)
                        pending_commit_count += 1
                        continue

                    started = perf_counter()
                    live_result = run_real_scenario_bidding_dry_run(
                        config=suite_config,
                        artifact_id=artifact_id,
                        forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                        max_origins=1,
                        output_root=run_dir / "day_runs",
                        strategy_name="phase_e5c_no_fallback_diagnostic",
                        dry_run_label="phase_e5c_no_fallback_diagnostic",
                        include_price_insensitive_comparison=False,
                        risk_measure="risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
                        cvar_alpha=float(alpha),
                        cvar_gamma=float(gamma),
                        production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                        inventory_start_kg=float(inventory_start),
                        reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                        target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                        target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                        terminal_reference_start_kg=float(inventory_start),
                        emergency_import_price_eur_per_mwh=None,
                        write_outputs=True,
                    )
                    payload = {
                        "run_dir": live_result.run_dir,
                        "model_id": str(day_payload["model_id"]),
                        "delivery_day": str(delivery_day),
                        "forecast_origin_utc": day_payload["forecast_origin_utc"],
                        "stochastic_solver_status": str(live_result.optimisation_result.solver.status),
                        "stochastic_objective_value": live_result.optimisation_result.solver.objective_value,
                        "stochastic_solve_time_seconds": live_result.optimisation_result.solver.runtime_seconds,
                        "stochastic_variable_count": None if live_result.optimisation_result.model_stats is None else live_result.optimisation_result.model_stats.variable_count,
                        "stochastic_binary_variable_count": None if live_result.optimisation_result.model_stats is None else live_result.optimisation_result.model_stats.binary_variable_count,
                        "stochastic_constraint_count": None if live_result.optimisation_result.model_stats is None else live_result.optimisation_result.model_stats.constraint_count,
                        "submitted_bids": live_result.optimisation_result.submitted_bids.copy(),
                        "scenario_clearing": live_result.optimisation_result.scenario_clearing.copy(),
                        "actual_clearing": live_result.actual_clearing.copy(),
                        "actual_redispatch_timeseries": live_result.actual_redispatch_timeseries.copy(),
                        "actual_settlement_results": live_result.actual_settlement_results.copy(),
                        "scenario_settlement_results": live_result.optimisation_result.scenario_economics.copy(),
                        "scenario_objective_summary": live_result.scenario_objective_summary.copy(),
                        "metrics_summary": live_result.metrics_summary.copy(),
                        "validation_checks": live_result.validation_checks.copy(),
                    }
                    actual_status = str(live_result.actual_settlement_results["solver_status"].iloc[0])
                    pending_store["runtime_diagnostics"].append(
                        pd.DataFrame(
                            [
                                _stage_runtime_row(
                                    solve_stage="stochastic_bidding_day",
                                    artifact_id=artifact_id,
                                    model_label=_label_for_artifact(artifact_id),
                                    gamma=float(gamma),
                                    week_id=week_id,
                                    delivery_day=str(delivery_day),
                                    wall_time_seconds=float(perf_counter() - started),
                                    used_cache=False,
                                    solver_status=str(payload["stochastic_solver_status"]),
                                )
                            ]
                        )
                    )
                    pending_store["registry"].append(
                        {
                            "week_id": week_id,
                            "delivery_day": str(delivery_day),
                            "artifact_id": artifact_id,
                            "cvar_gamma": float(gamma),
                            "day_run_dir": "" if live_result.run_dir is None else str(live_result.run_dir),
                            "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]).isoformat(),
                            "solver_status": str(payload["stochastic_solver_status"]),
                            "actual_redispatch_solver_status": actual_status,
                            "committed_at_utc": pd.Timestamp.utcnow().isoformat(),
                        }
                    )
                    new_solve_count += 1

                    actual_clearing_by_hour = aggregate_cleared_energy(payload["actual_clearing"])
                    actual_clearing_by_hour["timestep_hours"] = float(suite_config.delta_t_hours)
                    actual_clearing_by_hour["submitted_energy_mwh"] = pd.to_numeric(actual_clearing_by_hour["submitted_energy_mwh"], errors="coerce")
                    if _accepted_solver_status(actual_status):
                        metric_frame = _build_feasible_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            day_payload=day_payload,
                            week_series=week_series,
                            bounds=bounds,
                            gamma=float(gamma),
                            alpha=float(alpha),
                            cumulative_before_kg=float(cumulative_before),
                            payload=payload,
                        )
                        actual_h2 = float(metric_frame.iloc[0]["hydrogen_sold_or_compressed_kg"])
                        cumulative_after = float(cumulative_before + actual_h2)
                        inventory_start = float(live_result.actual_settlement_results.iloc[0]["terminal_inventory_end_kg"])
                        cumulative = cumulative_after
                        pending_store["actual_settlement"].append(
                            live_result.actual_settlement_results.assign(
                                artifact_id=artifact_id,
                                model_label=_label_for_artifact(artifact_id),
                                week_id=week_id,
                                week_label=week_label,
                                delivery_day=str(delivery_day),
                                cvar_alpha=float(alpha),
                                cvar_gamma=float(gamma),
                                production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                target_mode=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                profit_valid_for_ranking=True,
                            )
                        )
                    else:
                        restoration_row = _run_restoration_diagnostic(
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            gamma=float(gamma),
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=str(delivery_day),
                            actual_clearing_by_hour=actual_clearing_by_hour,
                            inventory_start_kg=float(inventory_before),
                            bounds=bounds,
                            config=suite_config,
                            run_dir=run_dir,
                        )
                        metric_frame = _build_infeasible_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            day_payload=day_payload,
                            week_series=week_series,
                            bounds=bounds,
                            gamma=float(gamma),
                            alpha=float(alpha),
                            inventory_start_kg=float(inventory_before),
                            cumulative_before_kg=float(cumulative_before),
                            payload=payload,
                            restoration_row=restoration_row,
                        )
                        pending_store["restoration_diagnostics"].append(pd.DataFrame([restoration_row]))
                        pending_store["infeasibility_report"].append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": _label_for_artifact(artifact_id),
                                "gamma": float(gamma),
                                "delivery_day": str(delivery_day),
                                "accounting_week_id": str(week_id),
                                "record_type": "infeasible_day",
                                "redispatch_status": actual_status,
                                "infeasibility_reason": f"actual_redispatch_status={actual_status}",
                                "cleared_energy_mwh": float(pd.to_numeric(actual_clearing_by_hour["cleared_energy_mwh"], errors="coerce").sum()),
                                "rejected_energy_mwh": float(pd.to_numeric(actual_clearing_by_hour["submitted_energy_mwh"], errors="coerce").sum() - pd.to_numeric(actual_clearing_by_hour["cleared_energy_mwh"], errors="coerce").sum()),
                                "used_energy_mwh": np.nan,
                                "storage_start_kg": float(inventory_before),
                                "storage_min_kg": np.nan,
                                "weekly_target_remaining_kg": float(bounds.remaining_target_before_today_kg),
                                "minimum_restoration_emergency_mwh": restoration_row["minimum_restoration_emergency_mwh"],
                                "restoration_cost_at_3000": restoration_row["restoration_cost_at_3000"],
                                "restoration_hours": restoration_row["restoration_hours"],
                                "likely_failure_type": restoration_row["likely_failure_type"],
                            }
                        )
                        block_remaining_days = True
                        pending_store["actual_settlement"].append(
                            pd.DataFrame(
                                [
                                    {
                                        "artifact_id": artifact_id,
                                        "model_label": _label_for_artifact(artifact_id),
                                        "week_id": week_id,
                                        "week_label": week_label,
                                        "delivery_day": str(delivery_day),
                                        "cvar_alpha": float(alpha),
                                        "cvar_gamma": float(gamma),
                                        "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                        "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                                        "solver_status": actual_status,
                                        "profit_valid_for_ranking": False,
                                        "realised_adjusted_profit_eur": np.nan,
                                        "used_energy_mwh": np.nan,
                                        "unused_cleared_energy_mwh": np.nan,
                                        "hydrogen_compressed_or_sold_kg": np.nan,
                                        "storage_initial_kg": float(inventory_before),
                                        "storage_min_kg": np.nan,
                                        "storage_max_kg": np.nan,
                                        "target_hydrogen_kg": float(bounds.daily_lower_bound_kg),
                                    }
                                ]
                            )
                        )

                    tracker_row = {
                        "strategy": str(metric_frame.iloc[0]["strategy"]),
                        "artifact_id": artifact_id,
                        "model_label": _label_for_artifact(artifact_id),
                        "gamma": float(gamma),
                        "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        "week_id": week_id,
                        "week_label": week_label,
                        "delivery_day": str(delivery_day),
                        "forecast_origin_utc": day_payload["forecast_origin_utc"],
                        "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                        "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                        "weekly_target_kg": float(bounds.weekly_target_kg),
                        "cumulative_before_kg": float(cumulative_before),
                        "cumulative_after_kg": float(metric_frame.iloc[0]["cumulative_after_kg"]) if pd.notna(metric_frame.iloc[0]["cumulative_after_kg"]) else float(cumulative),
                        "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                        "days_remaining_in_week": int(bounds.days_remaining_in_week),
                        "hydrogen_sold_or_compressed_kg": metric_frame.iloc[0]["hydrogen_sold_or_compressed_kg"],
                        "storage_start_kg": float(metric_frame.iloc[0]["storage_start_kg"]) if pd.notna(metric_frame.iloc[0]["storage_start_kg"]) else float(inventory_before),
                        "storage_end_kg": metric_frame.iloc[0]["storage_end_kg"],
                        "solver_status": actual_status,
                        **target_accounting_fields_from_bounds(bounds),
                    }
                    pending_store["weekly_tracker"].append(pd.DataFrame([tracker_row]))
                    pending_store["daily_metrics"].append(metric_frame)
                    pending_store["scenario_settlement"].append(
                        payload["scenario_settlement_results"].assign(
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=str(delivery_day),
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                            target_mode=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        )
                    )
                    pending_store["submitted_bids"].append(
                        payload["submitted_bids"].assign(
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=str(delivery_day),
                            cvar_gamma=float(gamma),
                            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        )
                    )
                    pending_store["actual_clearing"].append(
                        payload["actual_clearing"].assign(
                            artifact_id=artifact_id,
                            model_label=_label_for_artifact(artifact_id),
                            week_id=week_id,
                            week_label=week_label,
                            delivery_day=str(delivery_day),
                            cvar_gamma=float(gamma),
                            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        )
                    )
                    if PERSIST_SCENARIO_CLEARING_CHECKPOINT:
                        pending_store["scenario_clearing"].append(
                            payload["scenario_clearing"].assign(
                                artifact_id=artifact_id,
                                model_label=_label_for_artifact(artifact_id),
                                week_id=week_id,
                                week_label=week_label,
                                delivery_day=str(delivery_day),
                                cvar_gamma=float(gamma),
                                production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                            )
                        )
                    completed_keys.add(day_key)
                    pending_commit_count += 1

                    if pending_commit_count % checkpoint_every_n_solves == 0:
                        checkpoint_store = _flush_checkpoint_store(
                            cache_dir=cache_dir,
                            existing_store=checkpoint_store,
                            pending_store=pending_store,
                            expected_days=included_days,
                            artifact_id=artifact_id,
                            gammas=gamma_values,
                        )
                        pending_store = {key: [] for key in pending_store}
                if stop_requested:
                    break
            if stop_requested:
                break
    except Exception:
        checkpoint_store = _flush_checkpoint_store(
            cache_dir=cache_dir,
            existing_store=checkpoint_store,
            pending_store=pending_store,
            expected_days=included_days,
            artifact_id=artifact_id,
            gammas=gamma_values,
        )
        raise

    checkpoint_store = _flush_checkpoint_store(
        cache_dir=cache_dir,
        existing_store=checkpoint_store,
        pending_store=pending_store,
        expected_days=included_days,
        artifact_id=artifact_id,
        gammas=gamma_values,
    )

    daily_metrics = checkpoint_store["daily_metrics"].copy().sort_values(["cvar_gamma", "delivery_day"]).reset_index(drop=True)
    weekly_metrics = _build_weekly_metrics_no_fallback(daily_metrics=daily_metrics, week_manifest=week_manifest)
    annual_metrics_by_gamma = _build_annual_metrics_no_fallback(
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        restoration_diagnostics=checkpoint_store["restoration_diagnostics"].copy(),
        runtime_diagnostics=checkpoint_store["runtime_diagnostics"].copy(),
    )
    infeasibility_report = checkpoint_store["infeasibility_report"].copy()
    if not infeasibility_report.empty and {"gamma", "delivery_day", "record_type"}.issubset(infeasibility_report.columns):
        infeasibility_report = infeasibility_report.sort_values(["gamma", "delivery_day", "record_type"]).reset_index(drop=True)
    restoration_diagnostics = checkpoint_store["restoration_diagnostics"].copy()
    if not restoration_diagnostics.empty and {"gamma", "delivery_day"}.issubset(restoration_diagnostics.columns):
        restoration_diagnostics = restoration_diagnostics.sort_values(["gamma", "delivery_day"]).reset_index(drop=True)

    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "annual_metrics_by_gamma.csv", annual_metrics_by_gamma)
    save_frame_csv(run_dir, "no_fallback_infeasibility_report.csv", infeasibility_report)
    save_frame_csv(run_dir, "no_fallback_restoration_diagnostics.csv", restoration_diagnostics)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", checkpoint_store["runtime_diagnostics"].copy())
    save_frame_csv(run_dir, "weekly_target_tracker.csv", checkpoint_store["weekly_tracker"].copy())
    save_frame_csv(run_dir, "actual_settlement_results.csv", checkpoint_store["actual_settlement"].copy())
    save_frame_csv(run_dir, "scenario_settlement_results.csv", checkpoint_store["scenario_settlement"].copy())
    _save_parquet_if_possible(run_dir, "actual_clearing.parquet", checkpoint_store["actual_clearing"].copy())
    _save_parquet_if_possible(run_dir, "submitted_bids.parquet", checkpoint_store["submitted_bids"].copy())
    if PERSIST_SCENARIO_CLEARING_CHECKPOINT and not checkpoint_store["scenario_clearing"].empty:
        _save_parquet_if_possible(run_dir, "scenario_clearing.parquet", checkpoint_store["scenario_clearing"].copy())

    _write_no_fallback_readme(
        run_dir=run_dir,
        annual_metrics_by_gamma=annual_metrics_by_gamma,
        infeasibility_report=infeasibility_report,
        restoration_diagnostics=restoration_diagnostics,
    )

    if bool(build_true_pf_no_fallback):
        pf_infeasible_rows: list[dict[str, Any]] = []
        pf_weekly_rows: list[dict[str, Any]] = []
        for _, week_row in week_manifest.iterrows():
            inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
            cumulative = 0.0
            week_days = list(week_row["included_delivery_days"])
            week_valid = True
            week_profit = 0.0
            week_cleared = 0.0
            week_used = 0.0
            week_h2 = 0.0
            week_da_cost = 0.0
            week_terminal = 0.0
            for delivery_day in week_days:
                day_payload = reference_days[str(delivery_day)]
                bounds = _compute_variant_bounds(
                    settings=settings,
                    production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                    cumulative_realised_h2_kg_before_today=float(cumulative),
                    days_remaining_in_week=None,
                    physical_daily_max_kg=float(physical_daily_max_kg),
                    accounting_day=target_accounting_lookup[str(delivery_day)],
                )
                day_frame = day_payload["scenarios"]
                pf = run_perfect_foresight(
                    day_frame=day_frame,
                    config=suite_config,
                    inventory_start_kg=inventory_start,
                    reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                    apply_terminal_value=True,
                    terminal_reference_start_kg=inventory_start,
                    production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                    target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                    solver_log_path=str(run_dir / "cache" / f"{week_row['week_id']}__{delivery_day}__true_pf_no_fallback_plan_solver_log.txt"),
                )
                dispatch = pf.dispatch.copy()
                dispatch["forecast_origin_utc"] = day_payload["forecast_origin_utc"]
                dispatch["scenario_model"] = "true_pf_no_fallback"
                bids = dispatch_schedule_to_one_block_bid_curve(
                    dispatch,
                    run_id=f"{run_id}__true_pf_no_fallback__{delivery_day}",
                    source_strategy="true_pf_no_fallback",
                    bridge_strategy="true_pf_no_fallback_market_cap",
                    bid_price_eur_per_mwh=float(max(suite_config.bidding.bid_price_grid_eur_per_mwh)),
                    scenario_model="true_pf_no_fallback",
                    forecast_origin_utc=day_payload["forecast_origin_utc"],
                )
                actual_clearing = clear_hourly_bids(bids, _actual_prices_from_day_frame(day_frame))
                actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
                actual_clearing_by_hour["timestep_hours"] = float(suite_config.delta_t_hours)
                redispatch = solve_actual_redispatch_from_cleared_energy(
                    actual_clearing_by_hour,
                    config=suite_config,
                    inventory_start_kg=inventory_start,
                    reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                    target_hydrogen_kg=float(bounds.daily_lower_bound_kg),
                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                    terminal_reference_start_kg=inventory_start,
                    production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                    emergency_import_price_eur_per_mwh=None,
                    solver_log_path=run_dir / "cache" / f"{week_row['week_id']}__{delivery_day}__true_pf_no_fallback_redispatch_solver_log.txt",
                )
                summary = redispatch.summary.iloc[0]
                if not _accepted_solver_status(summary["solver_status"]):
                    week_valid = False
                    pf_infeasible_rows.append(
                        {
                            "week_id": str(week_row["week_id"]),
                            "week_label": str(week_row["week_label"]),
                            "delivery_day": str(delivery_day),
                            "redispatch_status": str(summary["solver_status"]),
                        }
                    )
                    break
                week_profit += float(summary["realised_adjusted_profit_eur"])
                week_cleared += float(summary["cleared_energy_mwh"])
                week_used += float(summary["used_energy_mwh"])
                week_h2 += float(summary["hydrogen_compressed_or_sold_kg"])
                week_da_cost += float(summary["realised_DA_settlement_cost_eur"])
                week_terminal += float(summary["terminal_inventory_correction_eur"])
                cumulative += float(summary["hydrogen_compressed_or_sold_kg"])
                inventory_start = float(summary["terminal_inventory_end_kg"])
            if week_valid:
                pf_weekly_rows.append(
                    {
                        "aggregation_level": "weekly",
                        "strategy": "true_pf_no_fallback",
                        "week_id": str(week_row["week_id"]),
                        "week_label": str(week_row["week_label"]),
                        "week_start": str(week_row["week_start"]),
                        "week_end": str(week_row["week_end"]),
                        "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        "realised_adjusted_profit": float(week_profit),
                        "cleared_energy_mwh": float(week_cleared),
                        "used_energy_mwh": float(week_used),
                        "unused_cleared_energy_mwh": 0.0,
                        "hydrogen_sold_or_compressed_kg": float(week_h2),
                        "shortfall_kg": 0.0,
                        "da_settlement_cost": float(week_da_cost),
                        "hydrogen_revenue": float(week_h2 * suite_config.economics.h2_sale_price_eur_per_kg),
                        "unused_energy_penalty": 0.0,
                        "shortfall_penalty": 0.0,
                        "terminal_inventory_correction": float(week_terminal),
                        "submitted_energy_mwh": float(week_cleared),
                        "rejected_energy_mwh": 0.0,
                        "average_actual_price_paid": float(week_da_cost / week_cleared) if week_cleared > 0.0 else np.nan,
                        "daily_band_violations": 0,
                        "infeasible_redispatch_days": 0,
                        "weekly_target_met": True,
                        "emergency_import_mwh": 0.0,
                        "emergency_import_cost": 0.0,
                        "emergency_import_hours": 0,
                        "emergency_import_share_of_used_energy": 0.0,
                    }
                )
        if pf_infeasible_rows:
            save_frame_csv(run_dir, "true_pf_no_fallback_infeasibility_report.csv", pd.DataFrame(pf_infeasible_rows))
        elif pf_weekly_rows:
            pf_weekly = pd.DataFrame(pf_weekly_rows)
            pf_annual = pd.DataFrame(
                [
                    {
                        "aggregation_level": "annual",
                        "strategy": "true_pf_no_fallback",
                        "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        "production_variant": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                        "realised_adjusted_profit": float(pd.to_numeric(pf_weekly["realised_adjusted_profit"], errors="coerce").sum()),
                        "cleared_energy_mwh": float(pd.to_numeric(pf_weekly["cleared_energy_mwh"], errors="coerce").sum()),
                        "used_energy_mwh": float(pd.to_numeric(pf_weekly["used_energy_mwh"], errors="coerce").sum()),
                        "unused_cleared_energy_mwh": 0.0,
                        "hydrogen_sold_or_compressed_kg": float(pd.to_numeric(pf_weekly["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                        "shortfall_kg": 0.0,
                        "da_settlement_cost": float(pd.to_numeric(pf_weekly["da_settlement_cost"], errors="coerce").sum()),
                        "hydrogen_revenue": float(pd.to_numeric(pf_weekly["hydrogen_revenue"], errors="coerce").sum()),
                        "unused_energy_penalty": 0.0,
                        "shortfall_penalty": 0.0,
                        "terminal_inventory_correction": float(pd.to_numeric(pf_weekly["terminal_inventory_correction"], errors="coerce").sum()),
                        "submitted_energy_mwh": float(pd.to_numeric(pf_weekly["submitted_energy_mwh"], errors="coerce").sum()),
                        "rejected_energy_mwh": 0.0,
                        "average_actual_price_paid": float(pd.to_numeric(pf_weekly["da_settlement_cost"], errors="coerce").sum() / pd.to_numeric(pf_weekly["cleared_energy_mwh"], errors="coerce").sum()),
                        "emergency_import_mwh": 0.0,
                        "emergency_import_cost": 0.0,
                        "emergency_import_hours": 0,
                        "emergency_import_share_of_used_energy": 0.0,
                        "period_start": str(test_start),
                        "period_end": str(test_end),
                    }
                ]
            )
            save_frame_csv(run_dir, "true_pf_no_fallback_weekly_metrics.csv", pf_weekly)
            save_frame_csv(run_dir, "true_pf_no_fallback_annual_metrics.csv", pf_annual)

    fallback_on_off_annual_comparison, fallback_on_off_weekly_comparison, fallback_on_off_diagnostic_summary = _build_on_off_comparison(
        baseline_run_dir=baseline_run_dir,
        off_run_dir=run_dir,
        off_weekly_metrics=weekly_metrics,
        off_annual_metrics=annual_metrics_by_gamma,
        off_restoration_diagnostics=restoration_diagnostics,
    )

    return PhaseE5cNoFallbackResult(
        baseline_run_dir=baseline_run_dir,
        run_dir=run_dir,
        flexibility_value_capture_summary=flexibility_value_capture_summary,
        flexibility_value_capture_by_week=flexibility_value_capture_by_week,
        policy_similarity_diagnostics=policy_similarity_diagnostics,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        annual_metrics_by_gamma=annual_metrics_by_gamma,
        infeasibility_report=infeasibility_report,
        restoration_diagnostics=restoration_diagnostics,
        fallback_on_off_annual_comparison=fallback_on_off_annual_comparison,
        fallback_on_off_weekly_comparison=fallback_on_off_weekly_comparison,
        fallback_on_off_diagnostic_summary=fallback_on_off_diagnostic_summary,
    )
