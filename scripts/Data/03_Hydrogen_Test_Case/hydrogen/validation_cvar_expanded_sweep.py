from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from .benchmarks import run_perfect_foresight
from .bidding import dispatch_schedule_to_one_block_bid_curve
from .bidding_backtest import run_real_scenario_bidding_dry_run
from .clearing import aggregate_cleared_energy, clear_hourly_bids
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .redispatch import solve_actual_redispatch_from_cleared_energy
from .run_registry import create_run_folder, save_config_resolved, save_frame_csv, save_frame_parquet, save_inputs_manifest, save_json, save_text
from .selected_week_smoke import (
    DEFAULT_ARTIFACT_IDS,
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    TOLERANCE,
    _label_for_artifact,
    _validation_row,
)
from .selected_week_policy import VALIDATION_SELECTED_REGIME_LABELS, resolve_registry_rows, run_selected_week_input_preflight
from .selected_week_suite import _valid_daily_registry_for_artifact
from .validation_cvar_sweep import (
    _aggregate_benchmark_metrics,
    _aggregate_weekly_metrics,
    _benchmark_daily_row,
    _build_cvar_validation_checks,
    _build_daily_metric_row,
    _build_phase_d_config,
    _build_solver_log_manifest,
    _scenario_coverage_by_day,
)

try:
    from visual_style import MODEL_COLORS, apply_visual_style
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR Strict": "#C97941",
        "LEAR FS3 pruned candidate": "#3A7D7C",
        "XGBoost FS3 pruned candidate": "#1F4E79",
        "Price insensitive benchmark": "#333333",
        "Perfect foresight": "#111111",
    }

    def apply_visual_style() -> None:
        plt.rcParams.update(
            {
                "figure.figsize": (8, 4.5),
                "figure.dpi": 120,
                "savefig.dpi": 300,
                "axes.grid": True,
                "grid.alpha": 0.5,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "legend.frameon": False,
            }
        )


DEFAULT_ALPHA = 0.95
DEFAULT_GAMMAS = (0.0, 0.01, 0.05, 0.10, 0.25, 0.50)
DEFAULT_WEEK_IDS = (
    "typical_summer",
    "winter_proxy",
    "high_volatility",
    "high_price",
)
EXAMPLE_DAY_GAMMAS = (0.0, 0.05, 0.25, 0.50)


@dataclass(frozen=True)
class PhaseD2ExpandedSweepResult:
    run_dir: Path
    notebook_path: Path
    selected_weeks: pd.DataFrame
    support_days: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    cvar_frontier_aggregated: pd.DataFrame
    gamma_policy_candidate_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    perfect_foresight_metrics: pd.DataFrame


def _normalized_gamma_tag(gamma: float) -> str:
    return str(float(gamma)).replace("-", "m").replace(".", "p")


def _load_and_validate_phase_d2_weeks(
    *,
    week_registry_path: Path,
    support_csv_path: Path,
    selected_weeks_yaml_path: Path | None,
    week_ids: list[str] | tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not week_registry_path.exists():
        raise FileNotFoundError(f"selected_week_registry_common_support.csv not found: {week_registry_path}")
    if not support_csv_path.exists():
        raise FileNotFoundError(f"common_support_three_model_hourly.csv not found: {support_csv_path}")
    support = pd.read_csv(support_csv_path)
    support["delivery_date"] = pd.to_datetime(support["delivery_date"], errors="raise")
    if selected_weeks_yaml_path is None:
        raise ValueError("Phase D2 requires the official selected validation-week config.")
    registry_rows = resolve_registry_rows(
        registry_path=week_registry_path,
        selected_weeks_yaml_path=selected_weeks_yaml_path,
        requested_identifiers=[str(value) for value in week_ids],
        expected_split="validation",
    )

    week_rows: list[dict[str, Any]] = []
    support_rows: list[pd.DataFrame] = []
    seen_period_types: set[str] = set()
    for requested_week, row in zip([str(value) for value in week_ids], registry_rows.to_dict(orient="records"), strict=True):
        checks = {
            "regime_label": str(row["regime_label"]) in VALIDATION_SELECTED_REGIME_LABELS,
            "period_type": str(row["period_type"]) == "validation",
            "number_of_delivery_days": int(row["number_of_delivery_days"]) == 7,
            "complete_for_lear_strict": bool(row["complete_for_lear_strict"]),
            "complete_for_lear_fs3": bool(row["complete_for_lear_fs3"]),
            "complete_for_xgboost_fs3": bool(row["complete_for_xgboost_fs3"]),
            "complete_actual_prices": bool(row["complete_actual_prices"]),
            "support_status": str(row["support_status"]) == "common_complete_support_selected",
            "methodological_use": str(row["methodological_use"]) == "cvar_selection",
        }
        failures = [name for name, ok in checks.items() if not ok]
        if failures:
            raise ValueError(f"Phase D2 selected-week validation failed for {requested_week}: {failures}")
        start = str(row["delivery_start_date"])
        end = str(row["delivery_end_date"])
        week_support = support.loc[
            (support["delivery_date"] >= pd.Timestamp(start))
            & (support["delivery_date"] <= pd.Timestamp(end))
        ].copy()
        if int(week_support.shape[0]) != 7:
            raise ValueError(f"Expected 7 support rows for {requested_week}, found {int(week_support.shape[0])}.")
        expected_dates = pd.date_range(start, end, freq="D")
        actual_dates = pd.DatetimeIndex(week_support["delivery_date"]).sort_values()
        if not actual_dates.equals(expected_dates):
            raise ValueError(f"Support rows for {requested_week} are not exactly {start}..{end}.")
        required_complete = (
            week_support["period_type"].astype(str).eq("validation")
            & week_support["complete_actual_prices"].astype(bool)
            & week_support["complete_for_lear_strict"].astype(bool)
            & week_support["complete_for_lear_fs3"].astype(bool)
            & week_support["complete_for_xgboost_fs3"].astype(bool)
            & week_support["common_complete_support"].astype(bool)
            & week_support["n_hours_actual"].astype(int).eq(24)
            & week_support["n_hours_lear_strict"].astype(int).eq(24)
            & week_support["n_hours_lear_fs3"].astype(int).eq(24)
            & week_support["n_hours_xgboost_fs3"].astype(int).eq(24)
            & week_support["n_scenarios_per_origin_lear_strict"].astype(int).eq(75)
            & week_support["n_scenarios_per_origin_lear_fs3"].astype(int).eq(75)
            & week_support["n_scenarios_per_origin_xgboost_fs3"].astype(int).eq(75)
        )
        if not bool(required_complete.all()):
            bad_days = week_support.loc[~required_complete, "delivery_date"].dt.strftime("%Y-%m-%d").tolist()
            raise ValueError(f"Week {requested_week} contains incomplete common-support days: {bad_days}")
        week_support["week_id"] = str(row["week_id"])
        week_support["week_label"] = str(row["week_label"])
        week_support["regime_label"] = str(row["regime_label"])
        support_rows.append(week_support)
        seen_period_types.update(week_support["period_type"].astype(str).unique().tolist())
        week_rows.append(dict(row))

    if any(period == "test" for period in seen_period_types):
        raise ValueError("Phase D2 validation-week set unexpectedly includes test days.")
    selected_weeks = pd.DataFrame(week_rows)
    support_days = pd.concat(support_rows, ignore_index=True).sort_values(["delivery_date"]).reset_index(drop=True)
    return selected_weeks, support_days


def _run_perfect_foresight_badarinath_style_comparison(
    *,
    day_frame: pd.DataFrame,
    actual_prices: pd.DataFrame,
    config: HydrogenConfig,
    run_id: str,
    forecast_origin_utc: pd.Timestamp,
    solver_log_root: Path | None,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pf = run_perfect_foresight(
        day_frame=day_frame,
        config=config,
        inventory_start_kg=float(config.hydrogen_system.storage_initial_kg),
        reserve_kg=float(config.hydrogen_system.reserve_kg),
        apply_terminal_value=True,
        terminal_reference_start_kg=float(config.hydrogen_system.storage_initial_kg),
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=str(solver_log_root / "pf_solver_log.txt") if solver_log_root is not None and config.outputs.save_solver_log else None,
    )
    dispatch = pf.dispatch.copy()
    dispatch["forecast_origin_utc"] = forecast_origin_utc
    dispatch["scenario_model"] = "perfect_foresight_oracle"
    market_cap = float(max(config.bidding.bid_price_grid_eur_per_mwh))
    bids = dispatch_schedule_to_one_block_bid_curve(
        dispatch,
        run_id=f"{run_id}__perfect_foresight",
        source_strategy="perfect_foresight",
        bridge_strategy="perfect_foresight_market_cap",
        bid_price_eur_per_mwh=market_cap,
        scenario_model="perfect_foresight_oracle",
        forecast_origin_utc=forecast_origin_utc,
    )
    clearing = clear_hourly_bids(bids, actual_prices)
    clearing_by_hour = aggregate_cleared_energy(clearing)
    clearing_by_hour["redispatch_case"] = "historical_actual_da"
    clearing_by_hour["timestep_hours"] = float(config.delta_t_hours)
    redispatch = solve_actual_redispatch_from_cleared_energy(
        clearing_by_hour,
        config=config,
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=solver_log_root / "pf_redisp_solver_log.txt" if solver_log_root is not None and config.outputs.save_solver_log else None,
    )
    summary = redispatch.summary.copy()
    summary["submitted_energy_mwh"] = float(clearing_by_hour["submitted_energy_mwh"].sum())
    summary["cleared_energy_mwh"] = float(clearing_by_hour["cleared_energy_mwh"].sum())
    summary["weighted_average_actual_price_paid_for_cleared_energy"] = (
        float(
            (
                clearing_by_hour["actual_price_eur_per_mwh"].astype(float)
                * clearing_by_hour["cleared_energy_mwh"].astype(float)
            ).sum()
            / summary["cleared_energy_mwh"].iloc[0]
        )
        if float(summary["cleared_energy_mwh"].iloc[0]) > 0.0
        else float("nan")
    )
    summary["strategy_label"] = "perfect_foresight_oracle_market_cap"
    return summary, clearing, redispatch.timeseries


def _perfect_foresight_daily_row(
    *,
    pf_row: pd.Series,
    week_id: str,
    week_label: str,
    regime_label: str,
    delivery_day: str,
    forecast_origin_utc: pd.Timestamp,
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "week_id": str(week_id),
        "week_label": str(week_label),
        "regime_label": str(regime_label),
        "period_type": "validation",
        "aggregation_level": "daily",
        "delivery_day": str(delivery_day),
        "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
        "strategy": "perfect_foresight_oracle_market_cap",
        "realised_adjusted_profit": float(pf_row["realised_adjusted_profit_eur"]),
        "cleared_energy_mwh": float(pf_row["cleared_energy_mwh"]),
        "used_energy_mwh": float(pf_row["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(pf_row["unused_cleared_energy_mwh"]),
        "hydrogen_sold_or_compressed_kg": float(pf_row["hydrogen_compressed_or_sold_kg"]),
        "shortfall_kg": float(pf_row["shortfall_kg"]),
        "da_settlement_cost": float(pf_row["realised_DA_settlement_cost_eur"]),
        "hydrogen_revenue": float(pf_row["hydrogen_revenue_eur"]),
        "unused_energy_penalty": float(pf_row["unused_energy_penalty_eur"]),
        "shortfall_penalty": float(pf_row["shortfall_penalty_eur"]),
        "terminal_inventory_correction": float(pf_row["terminal_inventory_correction_eur"]),
        "average_actual_price_paid": float(pf_row["weighted_average_actual_price_paid_for_cleared_energy"]),
        "solver_status": str(pf_row["solver_status"]),
        "solve_time_seconds": float(pf_row["solve_time_seconds"]),
    }


def _aggregate_perfect_foresight_metrics(pf_daily: pd.DataFrame) -> pd.DataFrame:
    if pf_daily.empty:
        return pd.DataFrame()
    weekly = (
        pf_daily.groupby(["run_id", "week_id", "week_label", "regime_label", "period_type"], as_index=False)
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
            solve_time_seconds=("solve_time_seconds", "sum"),
            solver_status=("solver_status", lambda s: "Optimal" if pd.Series(s).astype(str).eq("Optimal").all() else "mixed"),
            number_of_delivery_days=("delivery_day", "nunique"),
        )
    )
    weekly["aggregation_level"] = "weekly"
    weekly["strategy"] = "perfect_foresight_oracle_market_cap"
    weekly["average_actual_price_paid"] = weekly["da_settlement_cost"] / weekly["cleared_energy_mwh"]
    daily = pf_daily.copy()
    daily["strategy"] = "perfect_foresight_oracle_market_cap"
    return pd.concat([daily, weekly], ignore_index=True, sort=False)


def _build_model_stats_by_gamma_week(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    stats = (
        daily_metrics.groupby(["week_id", "week_label", "regime_label", "artifact_id", "model_label", "cvar_alpha", "cvar_gamma"], as_index=False)
        .agg(
            solver_status=("solver_status", lambda s: "Optimal" if pd.Series(s).astype(str).eq("Optimal").all() else "mixed"),
            objective_value=("objective_value", "sum"),
            solve_time_seconds=("solve_time_seconds", "sum"),
            mip_gap=("mip_gap", "max"),
            variable_count=("variable_count", "max"),
            binary_variable_count=("binary_variable_count", "max"),
            constraint_count=("constraint_count", "max"),
            scenario_count=("scenario_count", "max"),
            number_of_delivery_days=("delivery_day", "nunique"),
        )
    )
    return stats.sort_values(["week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)


def _build_cvar_frontier_by_model_week(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    frame = weekly_metrics.copy()
    frame["cvar_tail_profit"] = -pd.to_numeric(frame["cvar_loss"], errors="coerce")
    cols = [
        "artifact_id",
        "model_label",
        "week_id",
        "week_label",
        "regime_label",
        "cvar_alpha",
        "cvar_gamma",
        "expected_adjusted_profit",
        "realised_adjusted_profit",
        "cvar_loss",
        "cvar_tail_profit",
        "reconstructed_cvar_loss",
        "worst_scenario_profit",
        "worst_scenario_loss",
        "stochastic_minus_benchmark_profit",
        "perfect_foresight_profit",
        "value_captured_vs_perfect_foresight",
        "regret_vs_perfect_foresight",
    ]
    return frame[cols].copy().sort_values(["week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)


def _build_cvar_frontier_aggregated(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    frame = weekly_metrics.copy()
    frame["cvar_tail_profit"] = -pd.to_numeric(frame["cvar_loss"], errors="coerce")
    aggregated = (
        frame.groupby(["artifact_id", "model_label", "cvar_alpha", "cvar_gamma"], as_index=False)
        .agg(
            validation_week_count=("week_id", "nunique"),
            mean_expected_adjusted_profit=("expected_adjusted_profit", "mean"),
            mean_realised_adjusted_profit=("realised_adjusted_profit", "mean"),
            median_realised_adjusted_profit=("realised_adjusted_profit", "median"),
            worst_week_realised_adjusted_profit=("realised_adjusted_profit", "min"),
            mean_cvar_loss=("cvar_loss", "mean"),
            mean_cvar_tail_profit=("cvar_tail_profit", "mean"),
            worst_scenario_profit=("worst_scenario_profit", "min"),
            mean_clearing_ratio=("clearing_ratio", "mean"),
            mean_rejected_energy=("rejected_energy_mwh", "mean"),
            mean_shortfall=("shortfall_kg", "mean"),
            mean_unused_cleared_energy=("unused_cleared_energy_mwh", "mean"),
            mean_high_bid_share=("high_bid_share", "mean"),
            mean_uplift_vs_price_insensitive=("stochastic_minus_benchmark_profit", "mean"),
            mean_value_captured_vs_perfect_foresight=("value_captured_vs_perfect_foresight", "mean"),
            mean_regret_vs_perfect_foresight=("regret_vs_perfect_foresight", "mean"),
            mean_solve_time_seconds=("solve_time_seconds", "mean"),
        )
    )
    return aggregated.sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)


def _build_gamma_policy_candidate_summary(cvar_frontier_aggregated: pd.DataFrame) -> pd.DataFrame:
    if cvar_frontier_aggregated.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for model_label, group in cvar_frontier_aggregated.groupby("model_label", sort=False):
        ordered = group.sort_values("cvar_gamma").reset_index(drop=True)
        for _, row in ordered.iterrows():
            dominated_by: list[str] = []
            for _, challenger in ordered.iterrows():
                if float(challenger["cvar_gamma"]) == float(row["cvar_gamma"]):
                    continue
                no_worse = (
                    float(challenger["mean_realised_adjusted_profit"]) >= float(row["mean_realised_adjusted_profit"]) - 1e-9
                    and float(challenger["mean_cvar_tail_profit"]) >= float(row["mean_cvar_tail_profit"]) - 1e-9
                    and float(challenger["mean_shortfall"]) <= float(row["mean_shortfall"]) + 1e-9
                    and float(challenger["mean_unused_cleared_energy"]) <= float(row["mean_unused_cleared_energy"]) + 1e-9
                )
                strictly_better = (
                    float(challenger["mean_realised_adjusted_profit"]) > float(row["mean_realised_adjusted_profit"]) + 1e-9
                    or float(challenger["mean_cvar_tail_profit"]) > float(row["mean_cvar_tail_profit"]) + 1e-9
                    or float(challenger["mean_shortfall"]) < float(row["mean_shortfall"]) - 1e-9
                    or float(challenger["mean_unused_cleared_energy"]) < float(row["mean_unused_cleared_energy"]) - 1e-9
                )
                if no_worse and strictly_better:
                    dominated_by.append(f"{float(challenger['cvar_gamma']):.2f}")
            notes = ""
            if dominated_by:
                notes = f"dominated_by_gamma={dominated_by}"
            elif float(row["cvar_gamma"]) in {0.0, 0.05, 0.25}:
                notes = "retain_in_core_sensitivity_set_candidate"
            rows.append(
                {
                    "artifact_id": str(row["artifact_id"]),
                    "model": str(model_label),
                    "gamma": float(row["cvar_gamma"]),
                    "mean_realised_adjusted_profit": float(row["mean_realised_adjusted_profit"]),
                    "median_realised_adjusted_profit": float(row["median_realised_adjusted_profit"]),
                    "worst_week_realised_adjusted_profit": float(row["worst_week_realised_adjusted_profit"]),
                    "mean_expected_adjusted_profit": float(row["mean_expected_adjusted_profit"]),
                    "mean_cvar_tail_profit": float(row["mean_cvar_tail_profit"]),
                    "worst_scenario_profit": float(row["worst_scenario_profit"]),
                    "mean_clearing_ratio": float(row["mean_clearing_ratio"]),
                    "mean_rejected_energy": float(row["mean_rejected_energy"]),
                    "mean_shortfall": float(row["mean_shortfall"]),
                    "mean_unused_cleared_energy": float(row["mean_unused_cleared_energy"]),
                    "mean_high_bid_share": float(row["mean_high_bid_share"]),
                    "mean_value_captured_vs_perfect_foresight": float(row["mean_value_captured_vs_perfect_foresight"]) if pd.notna(row["mean_value_captured_vs_perfect_foresight"]) else float("nan"),
                    "dominated_flag": bool(len(dominated_by) > 0),
                    "notes": notes,
                }
            )
    return pd.DataFrame(rows).sort_values(["model", "gamma"]).reset_index(drop=True)


def _build_general_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_weeks: pd.DataFrame,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    daily_metrics: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
    perfect_foresight_included: bool,
    gamma_values: list[float],
    cvar_alpha: float,
    benchmark_identity_checks: pd.DataFrame,
    perfect_foresight_identity_checks: pd.DataFrame,
) -> pd.DataFrame:
    checks = existing_checks.copy()
    rows: list[dict[str, str]] = []
    rows.append(
        _validation_row(
            check_name="selected_weeks_exact_validation_cvar_set",
            status="pass" if selected_weeks["regime_label"].astype(str).tolist() == list(DEFAULT_WEEK_IDS) else "fail",
            details=f"regime_labels={selected_weeks['regime_label'].astype(str).tolist()}",
        )
    )
    rows.append(_validation_row(check_name="all_selected_days_inside_common_validation_support", status="pass" if support_days["period_type"].astype(str).eq("validation").all() and support_days["common_complete_support"].astype(bool).all() else "fail", details=f"selected_day_count={int(support_days.shape[0])}"))
    rows.append(_validation_row(check_name="no_selected_test_days_used", status="pass" if ~support_days["period_type"].astype(str).eq("test").any() else "fail", details=f"period_types={sorted(support_days['period_type'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="complete_actual_prices_for_selected_days", status="pass" if support_days["complete_actual_prices"].astype(bool).all() else "fail", details="complete_actual_prices all true"))
    rows.append(_validation_row(check_name="artifacts_run_on_same_validation_weeks", status="pass" if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == sorted([str(v) for v in artifact_ids]) else "fail", details=f"artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="scenario_count_75_for_all_selected_days", status="pass" if daily_metrics["scenario_count"].astype(int).eq(75).all() else "fail", details=f"scenario_count_values={sorted(daily_metrics['scenario_count'].astype(int).unique().tolist())}"))
    rows.append(_validation_row(check_name="scenario_probability_check_passes", status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail", details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}"))
    rows.append(_validation_row(check_name="submitted_minus_cleared_equals_rejected", status="pass" if np.allclose(daily_metrics["submitted_energy_mwh"].astype(float) - daily_metrics["cleared_energy_mwh"].astype(float), daily_metrics["rejected_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily submitted - cleared = rejected"))
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared", status="pass" if np.allclose(daily_metrics["used_cleared_energy_mwh"].astype(float) + daily_metrics["unused_cleared_energy_mwh"].astype(float), daily_metrics["cleared_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily used + unused = cleared"))
    expected_day_count = int(support_days.shape[0])
    rows.append(_validation_row(check_name="benchmark_same_actual_prices_and_days", status="pass" if int(benchmark_daily.shape[0]) == expected_day_count * len(artifact_ids) else "fail", details=f"benchmark_daily_rows={int(benchmark_daily.shape[0])}; expected={expected_day_count * len(artifact_ids)}"))
    if not benchmark_identity_checks.empty:
        same_benchmark = benchmark_identity_checks["status"].astype(str).eq("pass").all()
        rows.append(_validation_row(check_name="benchmark_identical_across_artifacts_per_day", status="pass" if same_benchmark else "fail", details=f"checks={benchmark_identity_checks[['delivery_day','details']].to_dict(orient='records')}"))
    if perfect_foresight_included:
        rows.append(_validation_row(check_name="perfect_foresight_same_actual_prices_and_days", status="pass" if int(perfect_foresight_daily.shape[0]) == expected_day_count else "fail", details=f"perfect_foresight_daily_rows={int(perfect_foresight_daily.shape[0])}; expected={expected_day_count}"))
        same_pf = perfect_foresight_identity_checks["status"].astype(str).eq("pass").all() if not perfect_foresight_identity_checks.empty else False
        rows.append(_validation_row(check_name="perfect_foresight_identical_across_artifacts_per_day", status="pass" if same_pf else "fail", details=f"checks={perfect_foresight_identity_checks[['delivery_day','details']].to_dict(orient='records') if not perfect_foresight_identity_checks.empty else []}"))
    rows.append(_validation_row(check_name="cvar_alpha_exactly_0p95", status="pass" if abs(float(cvar_alpha) - 0.95) <= 1e-12 and daily_metrics["cvar_alpha"].astype(float).eq(0.95).all() else "fail", details=f"unique_alpha={sorted(daily_metrics['cvar_alpha'].astype(float).unique().tolist())}"))
    rows.append(_validation_row(check_name="gamma_grid_exactly_requested", status="pass" if sorted(daily_metrics["cvar_gamma"].astype(float).unique().tolist()) == sorted([float(v) for v in gamma_values]) else "fail", details=f"observed_gamma_values={sorted(daily_metrics['cvar_gamma'].astype(float).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_quarter_hour_data_used", status="pass" if actual_clearing["granularity"].astype(str).eq("hourly").all() and pd.to_numeric(actual_clearing["timestep_hours"], errors="coerce").fillna(0.0).eq(1.0).all() else "fail", details=f"granularities={sorted(actual_clearing['granularity'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_d_plus_4_data_used", status="pass" if actual_clearing["horizon"].astype(str).eq("D_only").all() else "fail", details=f"horizons={sorted(actual_clearing['horizon'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_mfrr_used", status="pass", details="phase D2 runner does not invoke mFRR modules"))
    rows.append(_validation_row(check_name="actual_redispatch_timeseries_present", status="pass" if not actual_redispatch_timeseries.empty else "fail", details=f"rows={int(actual_redispatch_timeseries.shape[0])}"))
    appended = pd.DataFrame(rows)
    return pd.concat([checks, appended], ignore_index=True)


def _select_example_dates(daily_metrics: pd.DataFrame) -> dict[str, str]:
    base = (
        daily_metrics.loc[daily_metrics["cvar_gamma"].astype(float).abs() <= 1e-12]
        .sort_values(["week_label", "delivery_day", "model_label"])
        .groupby(["week_label", "delivery_day"], as_index=False)
        .first()
    )
    picks: dict[str, str] = {}
    high_price = base.loc[base["regime_label"].astype(str) == "high_price"].copy()
    typical_summer = base.loc[base["regime_label"].astype(str) == "typical_summer"].copy()
    winter_proxy = base.loc[base["regime_label"].astype(str) == "winter_proxy"].copy()
    high_volatility = base.loc[base["regime_label"].astype(str) == "high_volatility"].copy()
    if not high_price.empty:
        picks["high_price"] = str(high_price.sort_values(["actual_price_max", "actual_price_spread"], ascending=[False, False])["delivery_day"].iloc[0])
    if not typical_summer.empty:
        picks["typical_summer"] = str(typical_summer.sort_values(["actual_price_std", "actual_price_spread"], ascending=[True, True])["delivery_day"].iloc[0])
    if not winter_proxy.empty:
        picks["winter_proxy"] = str(winter_proxy.sort_values(["actual_price_std", "actual_price_spread"], ascending=[True, True])["delivery_day"].iloc[0])
    if not high_volatility.empty:
        picks["high_volatility"] = str(high_volatility.sort_values(["actual_price_std", "actual_price_spread"], ascending=[False, False])["delivery_day"].iloc[0])
    return picks


def _plot_validation_price_scenario_fans(scenario_frame: pd.DataFrame, output_dir: Path) -> None:
    if scenario_frame.empty:
        return
    apply_visual_style()
    gamma_zero = scenario_frame.loc[scenario_frame["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = scenario_frame.copy()
    for (week_label, model_label), group in gamma_zero.groupby(["week_label", "model_label"], sort=False):
        rows: list[dict[str, Any]] = []
        for ts, hour_group in group.groupby("delivery_start_utc", sort=True):
            vals = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            probs = hour_group["scenario_probability"].astype(float).to_numpy()
            rows.append(
                {
                    "delivery_start_utc": pd.Timestamp(ts),
                    "q05": float(np.quantile(vals, 0.05)) if probs.sum() <= 0 else float(np.sort(vals)[min(len(vals) - 1, int(np.searchsorted(np.cumsum(probs[np.argsort(vals)]), 0.05 * probs.sum(), side="left")))]),
                    "q10": float(np.quantile(vals, 0.10)) if probs.sum() <= 0 else float(np.sort(vals)[min(len(vals) - 1, int(np.searchsorted(np.cumsum(probs[np.argsort(vals)]), 0.10 * probs.sum(), side="left")))]),
                    "q50": float(np.quantile(vals, 0.50)) if probs.sum() <= 0 else float(np.sort(vals)[min(len(vals) - 1, int(np.searchsorted(np.cumsum(probs[np.argsort(vals)]), 0.50 * probs.sum(), side="left")))]),
                    "q90": float(np.quantile(vals, 0.90)) if probs.sum() <= 0 else float(np.sort(vals)[min(len(vals) - 1, int(np.searchsorted(np.cumsum(probs[np.argsort(vals)]), 0.90 * probs.sum(), side="left")))]),
                    "q95": float(np.quantile(vals, 0.95)) if probs.sum() <= 0 else float(np.sort(vals)[min(len(vals) - 1, int(np.searchsorted(np.cumsum(probs[np.argsort(vals)]), 0.95 * probs.sum(), side="left")))]),
                    "actual": float(hour_group["actual_price_eur_per_mwh"].iloc[0]),
                }
            )
        quant = pd.DataFrame(rows).sort_values("delivery_start_utc")
        fig, ax = plt.subplots(figsize=(12, 4.8))
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.fill_between(quant["delivery_start_utc"], quant["q05"], quant["q95"], alpha=0.18, color=color, label="p05-p95")
        ax.fill_between(quant["delivery_start_utc"], quant["q10"], quant["q90"], alpha=0.25, color=color, label="p10-p90")
        ax.plot(quant["delivery_start_utc"], quant["q50"], color=color, linewidth=1.6, label="scenario median")
        ax.plot(quant["delivery_start_utc"], quant["actual"], color="#222222", linewidth=1.8, label="actual price")
        ax.set_title(f"{week_label}: scenario fan vs realised price for {model_label}")
        ax.set_ylabel("EUR/MWh")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(output_dir / f"fig_validation_price_scenario_fan_{week_label}_{str(model_label).lower().replace(' ', '_')}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _plot_gamma_metric_by_model_week(frame: pd.DataFrame, metric: str, ylabel: str, title: str, output_path: Path) -> None:
    if frame.empty:
        return
    apply_visual_style()
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in frame["model_label"].astype(str).unique().tolist()]
    weeks = [label for label in DEFAULT_WEEK_IDS if label in frame["regime_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(models), 1, figsize=(10, max(4.0, 3.4 * len(models))), sharex=True)
    if len(models) == 1:
        axes = [axes]
    week_colors = {
        "high_price": "#7F3C8D",
        "typical_summer": "#11A579",
        "winter_proxy": "#F2B701",
        "high_volatility": "#3969AC",
    }
    for ax, model_label in zip(axes, models, strict=True):
        model_group = frame.loc[frame["model_label"].astype(str) == model_label].copy()
        for regime_label in weeks:
            group = model_group.loc[model_group["regime_label"].astype(str) == regime_label].sort_values("cvar_gamma")
            if group.empty:
                continue
            ax.plot(group["cvar_gamma"], pd.to_numeric(group[metric], errors="coerce"), marker="o", linewidth=1.6, label=regime_label, color=week_colors.get(regime_label, "#666666"))
        ax.set_title(model_label)
        ax.set_ylabel(ylabel)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Gamma")
    fig.suptitle(title, y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_risk_return_frontier_by_model(frame: pd.DataFrame, output_path: Path) -> None:
    if frame.empty:
        return
    apply_visual_style()
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in frame["model_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(1, len(models), figsize=(5.2 * len(models), 4.8), sharey=True)
    if len(models) == 1:
        axes = [axes]
    week_colors = {
        "high_price": "#7F3C8D",
        "typical_summer": "#11A579",
        "winter_proxy": "#F2B701",
        "high_volatility": "#3969AC",
    }
    for ax, model_label in zip(axes, models, strict=True):
        model_group = frame.loc[frame["model_label"].astype(str) == model_label].copy()
        for regime_label, week_group in model_group.groupby("regime_label", sort=False):
            week_group = week_group.sort_values("cvar_gamma")
            ax.plot(
                pd.to_numeric(week_group["cvar_tail_profit"], errors="coerce"),
                pd.to_numeric(week_group["realised_adjusted_profit"], errors="coerce"),
                marker="o",
                linewidth=1.5,
                label=str(regime_label),
                color=week_colors.get(str(regime_label), "#666666"),
            )
            for _, row in week_group.iterrows():
                ax.annotate(f"g={float(row['cvar_gamma']):.2f}", (float(row["cvar_tail_profit"]), float(row["realised_adjusted_profit"])), fontsize=7)
        ax.set_title(model_label)
        ax.set_xlabel("CVaR tail profit (-CVaR loss)")
        ax.legend(loc="best", fontsize=8)
    axes[0].set_ylabel("Realised adjusted profit (EUR)")
    fig.suptitle("Validation-period CVaR risk-return frontier by model", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_bid_firmness_by_gamma(submitted_bids: pd.DataFrame, weekly_metrics: pd.DataFrame, scenario_frame: pd.DataFrame, output_dir: Path) -> None:
    if submitted_bids.empty or weekly_metrics.empty:
        return
    apply_visual_style()
    gamma_list = [float(value) for value in DEFAULT_GAMMAS]
    gamma_zero = scenario_frame.loc[scenario_frame["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    for (week_label, model_label), group in submitted_bids.groupby(["week_label", "model_label"], sort=False):
        fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=False)
        tier = (
            group.groupby(["cvar_gamma", "bid_price_eur_per_mwh"], as_index=False)["bid_quantity_mw"]
            .sum()
            .sort_values(["cvar_gamma", "bid_price_eur_per_mwh"])
        )
        for gamma in gamma_list:
            subset = tier.loc[tier["cvar_gamma"].astype(float).eq(gamma)]
            axes[0].plot(subset["bid_price_eur_per_mwh"], subset["bid_quantity_mw"], marker="o", label=f"g={gamma:.2f}")
        axes[0].set_title("Submitted energy by bid-price tier")
        axes[0].set_ylabel("MW")
        axes[0].legend(loc="best", fontsize=8)

        week_metrics = weekly_metrics.loc[
            weekly_metrics["week_label"].astype(str).eq(str(week_label))
            & weekly_metrics["model_label"].astype(str).eq(str(model_label))
        ].sort_values("cvar_gamma")
        axes[1].plot(week_metrics["cvar_gamma"], week_metrics["weighted_average_bid_price"], marker="o", label="weighted_average_bid_price")
        axes[1].plot(week_metrics["cvar_gamma"], week_metrics["high_bid_share"] * 100.0, marker="s", label="high_bid_share_pct")
        axes[1].plot(week_metrics["cvar_gamma"], week_metrics["market_cap_bid_share"] * 100.0, marker="^", label="market_cap_share_pct")
        axes[1].set_title("Bid firmness summary by gamma")
        axes[1].set_xlabel("Gamma")
        axes[1].legend(loc="best", fontsize=8)

        actual = gamma_zero.loc[
            gamma_zero["week_label"].astype(str).eq(str(week_label))
            & gamma_zero["model_label"].astype(str).eq(str(model_label))
        ]
        if not actual.empty:
            hourly = (
                actual.groupby("delivery_start_utc", as_index=False)["actual_price_eur_per_mwh"]
                .first()
                .sort_values("delivery_start_utc")
            )
            axes[2].plot(hourly["delivery_start_utc"], hourly["actual_price_eur_per_mwh"], color="#222222", linewidth=1.8, label="actual_price")
        axes[2].set_title("Actual price overlay for the validation week")
        axes[2].set_ylabel("EUR/MWh")
        axes[2].legend(loc="best", fontsize=8)
        fig.suptitle(f"{week_label}: bid firmness by gamma for {model_label}", y=0.995)
        fig.tight_layout()
        fig.savefig(output_dir / f"fig_bid_firmness_by_gamma_{week_label}_{str(model_label).lower().replace(' ', '_')}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _plot_example_day_operations(
    *,
    submitted_bids: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
    example_dates: dict[str, str],
    output_dir: Path,
) -> None:
    if submitted_bids.empty or actual_clearing.empty or actual_redispatch_timeseries.empty:
        return
    apply_visual_style()
    gamma_display = [float(value) for value in EXAMPLE_DAY_GAMMAS]
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in submitted_bids["model_label"].astype(str).unique().tolist()]
    for week_label, delivery_day in example_dates.items():
        for model_label in models:
            fig, axes = plt.subplots(5, 1, figsize=(11, 13), sharex=True)
            for gamma in gamma_display:
                fan = scenario_frame.loc[
                    scenario_frame["week_label"].astype(str).eq(str(week_label))
                    & scenario_frame["model_label"].astype(str).eq(str(model_label))
                    & scenario_frame["delivery_day"].astype(str).eq(str(delivery_day))
                    & scenario_frame["cvar_gamma"].astype(float).eq(gamma)
                ].copy()
                if fan.empty:
                    continue
                hourly_rows: list[dict[str, Any]] = []
                for ts, hour_group in fan.groupby("delivery_start_utc", sort=True):
                    vals = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
                    probs = hour_group["scenario_probability"].astype(float).to_numpy()
                    actual = float(hour_group["actual_price_eur_per_mwh"].iloc[0])
                    order = np.argsort(vals)
                    vals = vals[order]
                    probs = probs[order]
                    cum = np.cumsum(probs)
                    def _wq(alpha: float) -> float:
                        idx = min(int(np.searchsorted(cum, alpha * probs.sum(), side="left")), len(vals) - 1)
                        return float(vals[idx])
                    hourly_rows.append({"delivery_start_utc": pd.Timestamp(ts), "q10": _wq(0.10), "q50": _wq(0.50), "q90": _wq(0.90), "actual": actual})
                hourly = pd.DataFrame(hourly_rows).sort_values("delivery_start_utc")
                axes[0].plot(hourly["delivery_start_utc"], hourly["q50"], linewidth=1.2, label=f"median g={gamma:.2f}")
                if gamma == gamma_display[0]:
                    axes[0].plot(hourly["delivery_start_utc"], hourly["actual"], color="#222222", linewidth=1.8, label="actual")

                clearing_hour = (
                    actual_clearing.loc[
                        actual_clearing["week_label"].astype(str).eq(str(week_label))
                        & actual_clearing["model_label"].astype(str).eq(str(model_label))
                        & actual_clearing["delivery_day"].astype(str).eq(str(delivery_day))
                        & actual_clearing["cvar_gamma"].astype(float).eq(gamma)
                    ]
                    .groupby("delivery_start_utc", as_index=False)
                    .agg(
                        submitted_energy_mwh=("bid_quantity_mw", "sum"),
                        cleared_energy_mwh=("cleared_energy_mwh", "sum"),
                    )
                )
                clearing_hour["rejected_energy_mwh"] = clearing_hour["submitted_energy_mwh"] - clearing_hour["cleared_energy_mwh"]
                axes[1].plot(clearing_hour["delivery_start_utc"], clearing_hour["submitted_energy_mwh"], linewidth=1.1, label=f"submitted g={gamma:.2f}")
                axes[1].plot(clearing_hour["delivery_start_utc"], clearing_hour["cleared_energy_mwh"], linewidth=1.1, linestyle="--", label=f"cleared g={gamma:.2f}")
                axes[1].plot(clearing_hour["delivery_start_utc"], clearing_hour["rejected_energy_mwh"], linewidth=1.1, linestyle=":", label=f"rejected g={gamma:.2f}")

                redispatch = actual_redispatch_timeseries.loc[
                    actual_redispatch_timeseries["week_label"].astype(str).eq(str(week_label))
                    & actual_redispatch_timeseries["model_label"].astype(str).eq(str(model_label))
                    & actual_redispatch_timeseries["delivery_day"].astype(str).eq(str(delivery_day))
                    & actual_redispatch_timeseries["cvar_gamma"].astype(float).eq(gamma)
                ].sort_values("delivery_start_utc")
                axes[2].plot(redispatch["delivery_start_utc"], redispatch["cleared_energy_mwh"], linewidth=1.1, label=f"cleared g={gamma:.2f}")
                axes[2].plot(redispatch["delivery_start_utc"], redispatch["used_energy_mwh"], linewidth=1.1, linestyle="--", label=f"used g={gamma:.2f}")
                axes[2].plot(redispatch["delivery_start_utc"], redispatch["unused_cleared_energy_mwh"], linewidth=1.1, linestyle=":", label=f"unused g={gamma:.2f}")
                axes[3].plot(redispatch["delivery_start_utc"], redispatch["P_el_mw"], linewidth=1.1, label=f"P_el g={gamma:.2f}")
                axes[3].plot(redispatch["delivery_start_utc"], redispatch["P_comp_mw"], linewidth=1.1, linestyle="--", label=f"P_comp g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["H_buf_kg"], linewidth=1.1, label=f"H_buf g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["H_prod_kg"], linewidth=1.1, linestyle="--", label=f"H_prod g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["H_comp_kg"], linewidth=1.1, linestyle=":", label=f"H_comp g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["shortfall_kg"], linewidth=1.1, linestyle="-.", label=f"shortfall g={gamma:.2f}")
            axes[0].set_title("Scenario fan median and realised price")
            axes[1].set_title("Submitted, cleared, and rejected electricity")
            axes[2].set_title("Cleared, used, and unused electricity")
            axes[3].set_title("Electrolyser and compressor power")
            axes[4].set_title("Hydrogen production, compression, storage, and shortfall")
            axes[0].legend(loc="best", fontsize=7, ncol=2)
            axes[1].legend(loc="best", fontsize=7, ncol=2)
            axes[2].legend(loc="best", fontsize=7, ncol=2)
            axes[3].legend(loc="best", fontsize=7, ncol=2)
            axes[4].legend(loc="best", fontsize=7, ncol=2)
            fig.suptitle(f"Example-day operation: {delivery_day} | {week_label} | {model_label}", y=0.995)
            fig.tight_layout()
            fig.savefig(output_dir / f"fig_example_day_operation_{delivery_day}_{str(model_label).lower().replace(' ', '_')}.png", dpi=300, bbox_inches="tight")
            plt.close(fig)


def _plot_value_captured_vs_perfect_foresight(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty or weekly_metrics["value_captured_vs_perfect_foresight"].dropna().empty:
        return
    _plot_gamma_metric_by_model_week(
        weekly_metrics,
        metric="value_captured_vs_perfect_foresight",
        ylabel="Share of PF realised profit",
        title="Gamma vs value captured vs perfect foresight",
        output_path=output_path,
    )


def _plot_gamma_policy_summary(summary: pd.DataFrame, output_path: Path) -> None:
    if summary.empty:
        return
    apply_visual_style()
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in summary["model"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(models), 1, figsize=(10, max(4.0, 3.0 * len(models))), sharex=True)
    if len(models) == 1:
        axes = [axes]
    for ax, model_label in zip(axes, models, strict=True):
        group = summary.loc[summary["model"].astype(str).eq(model_label)].sort_values("gamma")
        colors = ["#D55E00" if flag else MODEL_COLORS.get(model_label, "#1F4E79") for flag in group["dominated_flag"].astype(bool)]
        ax.scatter(group["gamma"], group["mean_realised_adjusted_profit"], c=colors, s=60, label="mean_realised_adjusted_profit")
        ax2 = ax.twinx()
        ax2.plot(group["gamma"], group["mean_cvar_tail_profit"], color="#333333", marker="o", linestyle="--", label="mean_cvar_tail_profit")
        ax.set_title(model_label)
        ax.set_ylabel("Mean realised profit")
        ax2.set_ylabel("Mean CVaR tail profit")
    axes[-1].set_xlabel("Gamma")
    fig.suptitle("Gamma-policy summary with dominated candidates highlighted", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_figures(
    *,
    run_dir: Path,
    daily_metrics: pd.DataFrame,
    submitted_bids: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    gamma_policy_candidate_summary: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    cvar_frontier_by_model_week = _build_cvar_frontier_by_model_week(weekly_metrics)
    _plot_validation_price_scenario_fans(scenario_frame, figures_dir)
    _plot_risk_return_frontier_by_model(cvar_frontier_by_model_week, figures_dir / "fig_risk_return_frontier_by_model.png")
    _plot_gamma_metric_by_model_week(weekly_metrics, "realised_adjusted_profit", "EUR", "Gamma vs realised adjusted profit by model and week", figures_dir / "fig_gamma_vs_realised_profit_by_model_week.png")
    _plot_gamma_metric_by_model_week(weekly_metrics.assign(cvar_tail_profit=lambda df: -pd.to_numeric(df["cvar_loss"], errors="coerce")), "cvar_tail_profit", "EUR", "Gamma vs CVaR tail profit by model and week", figures_dir / "fig_gamma_vs_cvar_tail_profit_by_model_week.png")
    _plot_gamma_metric_by_model_week(weekly_metrics, "shortfall_kg", "kg", "Gamma vs shortfall by model and week", figures_dir / "fig_gamma_vs_shortfall_by_model_week.png")
    _plot_gamma_metric_by_model_week(weekly_metrics, "clearing_ratio", "ratio", "Gamma vs clearing ratio by model and week", figures_dir / "fig_gamma_vs_clearing_ratio_by_model_week.png")
    _plot_bid_firmness_by_gamma(submitted_bids, weekly_metrics, scenario_frame, figures_dir)
    _plot_value_captured_vs_perfect_foresight(weekly_metrics, figures_dir / "fig_value_captured_vs_perfect_foresight.png")
    _plot_gamma_policy_summary(gamma_policy_candidate_summary, figures_dir / "fig_gamma_policy_summary.png")
    _plot_example_day_operations(
        submitted_bids=submitted_bids,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
        example_dates=_select_example_dates(daily_metrics),
        output_dir=figures_dir,
    )


def _write_readme(
    *,
    run_dir: Path,
    selected_weeks: pd.DataFrame,
    artifact_ids: list[str],
    cvar_alpha: float,
    gamma_values: list[float],
    benchmark_included: bool,
    perfect_foresight_included: bool,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    gamma_policy_candidate_summary: pd.DataFrame,
    validation_checks: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
) -> None:
    hard_fail_count = int(validation_checks.loc[(validation_checks["severity"].astype(str) == "hard_fail") & (validation_checks["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    week_summary = weekly_metrics[
        [
            "week_label",
            "model_label",
            "cvar_gamma",
            "expected_adjusted_profit",
            "realised_adjusted_profit",
            "benchmark_profit",
            "perfect_foresight_profit",
            "stochastic_minus_benchmark_profit",
            "cvar_loss",
            "worst_scenario_profit",
            "clearing_ratio",
            "shortfall_kg",
            "high_bid_share",
        ]
    ].copy()
    lines = [
        "# Phase D2 Expanded Validation CVaR Sensitivity Sweep",
        "",
        "## Scope",
        "",
        "- label: validation-period CVaR sensitivity analysis on common partial support",
        "- hourly, D-only, DA-only",
        "- validation weeks only",
        "- no selected test weeks were used",
        "- no quarter-hour, D+4, mFRR, or exclusive group bids were added",
        "",
        "## Selected Validation Weeks",
        "",
        "```csv",
        selected_weeks[["week_label", "delivery_start_date", "delivery_end_date", "regime_label", "selection_reason"]].to_csv(index=False).strip(),
        "```",
        "",
        "## Artifacts",
        "",
    ]
    for artifact_id in artifact_ids:
        lines.append(f"- `{artifact_id}`")
    lines.extend(
        [
            "",
            "## CVaR Settings",
            "",
            f"- alpha: `{float(cvar_alpha):.4f}`",
            f"- gamma grid: `{[float(v) for v in gamma_values]}`",
            "- gamma = 0 is the risk-neutral baseline.",
            "- gamma policy preparation remains validation-based only.",
            "",
            "## Benchmarks",
            "",
            f"- price-insensitive benchmark included: `{bool(benchmark_included)}`",
            f"- perfect foresight included: `{bool(perfect_foresight_included)}`",
            "- perfect foresight is treated as an oracle upper bound, not a realistic strategy.",
            "",
            "## Solve Counts",
            "",
            f"- stochastic bidding MILP solves: `{int(daily_metrics.shape[0])}`",
            f"- delivery days covered: `{int(daily_metrics['delivery_day'].astype(str).nunique())}`",
            f"- weekly model-gamma rows: `{int(weekly_metrics.shape[0])}`",
            "",
            "## Weekly Results",
            "",
            "```csv",
            week_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Gamma-Policy Candidate Summary",
            "",
            "```csv",
            gamma_policy_candidate_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Validation Status",
            "",
            f"- hard validation failures: {hard_fail_count}",
            f"- CVaR reconstruction / consistency failures: {cvar_fail_count}",
            "",
            "## Interpretation Guardrails",
            "",
            "- this is validation-only sensitivity analysis, not final test reporting;",
            "- no test week was used to tune gamma;",
            "- scenario undercoverage still limits risk interpretation;",
            "- value captured vs perfect foresight is diagnostic only and does not justify gamma selection by itself.",
            "",
            "## Phase Status",
            "",
            f"- Phase D2 status: {'pass' if hard_fail_count == 0 and cvar_fail_count == 0 else 'fail'}",
            f"- safe to proceed to Phase E: {'yes, with a frozen sensitivity set' if hard_fail_count == 0 and cvar_fail_count == 0 else 'not yet'}",
        ]
    )
    save_text(run_dir, "README_cvar_expanded_validation_sweep.md", "\n".join(lines))


def run_validation_cvar_expanded_sweep(
    *,
    config: HydrogenConfig | str | Path,
    week_ids: list[str] | tuple[str, ...] = DEFAULT_WEEK_IDS,
    artifact_ids: list[str] | tuple[str, ...] = DEFAULT_ARTIFACT_IDS,
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_d2_validation_cvar_expanded_three_model",
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
) -> PhaseD2ExpandedSweepResult:
    gamma_list = [float(value) for value in gamma_values]
    if gamma_list != [0.0, 0.01, 0.05, 0.10, 0.25, 0.50]:
        raise ValueError(f"Phase D2 requires gamma grid exactly [0, 0.01, 0.05, 0.10, 0.25, 0.50], got {gamma_list}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase D2 requires alpha 0.95, got {cvar_alpha}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase D2 requires the price-insensitive benchmark to be included.")

    selected_weeks, support_days = _load_and_validate_phase_d2_weeks(
        week_registry_path=Path(week_registry_path),
        support_csv_path=Path(support_csv_path),
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        week_ids=week_ids,
    )

    suite_config = _build_phase_d_config(
        config,
        artifact_ids=[str(value) for value in artifact_ids],
        output_root=output_root,
        experiment_name=str(run_slug),
    )
    run_id, run_dir = create_run_folder(suite_config)
    save_config_resolved(run_dir, suite_config)
    input_paths = [suite_config.config_path, suite_config.models.scenario_catalog, Path(week_registry_path), Path(support_csv_path)]
    if selected_weeks_yaml_path is not None:
        input_paths.append(Path(selected_weeks_yaml_path))
    save_inputs_manifest(run_dir, input_paths)
    preflight = run_selected_week_input_preflight(
        config=suite_config,
        artifact_ids=[str(value) for value in artifact_ids],
        requested_identifiers=[str(value) for value in week_ids],
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        expected_split="validation",
        cache_root=run_dir / "cache",
        output_policy_name="minimal",
    )
    save_frame_csv(run_dir, "selected_week_input_preflight.csv", preflight.audit_rows)
    save_frame_csv(run_dir, "selected_week_input_runtime_profile.csv", preflight.runtime_profile)
    if not preflight.audit_rows.empty and not preflight.audit_rows["status"].astype(str).eq("pass").all():
        raise RuntimeError(
            "Phase D2 selected-week input preflight failed before optimisation; "
            f"see {run_dir / 'selected_week_input_preflight.csv'}."
        )

    save_json(
        run_dir,
        "selected_weeks_manifest.json",
        {
            "selected_weeks": selected_weeks[["week_id", "week_label", "delivery_start_date", "delivery_end_date", "regime_label", "methodological_use", "support_status"]].to_dict(orient="records"),
            "selected_delivery_days": support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist(),
            "support_label": "validation-period CVaR sensitivity analysis on common partial support",
        },
    )
    save_json(
        run_dir,
        "cvar_settings_manifest.json",
        {
            "alpha": float(cvar_alpha),
            "gamma_values": gamma_list,
            "gamma_zero_label": "risk_neutral",
            "objective_convention": "maximize_expected_adjusted_profit_minus_gamma_times_cvar_loss",
            "loss_convention": "loss = - adjusted_profit",
        },
    )
    save_json(
        run_dir,
        "benchmark_manifest.json",
        {
            "price_insensitive_benchmark_included": bool(include_price_insensitive_benchmark),
            "perfect_foresight_benchmark_included": bool(include_perfect_foresight_benchmark),
            "perfect_foresight_description": "oracle upper bound using realised prices known in advance" if include_perfect_foresight_benchmark else "deferred",
        },
    )

    day_output_root = run_dir / "day_runs"
    day_output_root.mkdir(parents=True, exist_ok=True)
    day_run_config = replace(suite_config, outputs=replace(suite_config.outputs, save_figures=False))

    week_row_lookup = {
        str(row["week_label"]): pd.Series(row)
        for row in selected_weeks.to_dict(orient="records")
    }
    delivery_to_week = {
        pd.Timestamp(row["delivery_date"]).strftime("%Y-%m-%d"): {
            "week_id": str(row["week_id"]),
            "week_label": str(row["week_label"]),
            "regime_label": str(row["regime_label"]),
        }
        for row in support_days.to_dict(orient="records")
    }
    selected_delivery_days = set(delivery_to_week.keys())

    daily_rows: list[dict[str, Any]] = []
    validation_rows: list[pd.DataFrame] = []
    submitted_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    benchmark_daily_rows: list[dict[str, Any]] = []
    perfect_foresight_daily_rows: list[dict[str, Any]] = []
    scenario_fan_rows: list[pd.DataFrame] = []
    day_run_dir_rows: list[dict[str, Any]] = []
    scenario_manifest_rows: list[dict[str, Any]] = []
    benchmark_identity_rows: list[dict[str, str]] = []
    perfect_foresight_identity_rows: list[dict[str, str]] = []
    benchmark_cache: dict[tuple[str, str], pd.Series] = {}
    benchmark_signature_by_day: dict[str, tuple[float, ...]] = {}
    perfect_foresight_profit_by_day: dict[str, pd.Series] = {}
    perfect_foresight_signature_by_day: dict[str, tuple[float, ...]] = {}

    for artifact_id in [str(value) for value in artifact_ids]:
        selected_daily, _, spec, catalog_entry, manifest = _valid_daily_registry_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
        )
        selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(selected_delivery_days)].copy()
        if int(selected_daily.shape[0]) != len(selected_delivery_days):
            raise ValueError(f"Artifact {artifact_id!r} produced {int(selected_daily.shape[0])} validation days for Phase D2; expected {len(selected_delivery_days)}.")
        selected_daily = selected_daily.sort_values("delivery_day").reset_index(drop=True)
        model_label = _label_for_artifact(artifact_id)
        validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
        thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
        reconstruction_used = bool(manifest.get("forecast_origin_reconstruction_used", manifest.get("forecast_origin_reconstructed", False)))

        for day_record in selected_daily.to_dict(orient="records"):
            delivery_day = str(day_record["delivery_day"])
            week_meta = delivery_to_week[delivery_day]
            week_row = week_row_lookup[str(week_meta["week_label"])].copy()
            benchmark_key = (artifact_id, delivery_day)
            for gamma in gamma_list:
                risk_mode = "risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar"
                include_benchmark = include_price_insensitive_benchmark and benchmark_key not in benchmark_cache
                result = run_real_scenario_bidding_dry_run(
                    config=day_run_config,
                    artifact_id=artifact_id,
                    forecast_origin_utc=str(pd.Timestamp(day_record["forecast_origin_utc"]).isoformat()),
                    max_origins=1,
                    output_root=day_output_root,
                    strategy_name="stochastic_bid_risk_neutral" if risk_mode == "risk_neutral" else "stochastic_bid_cvar",
                    dry_run_label=f"{week_meta['week_label']}_gamma_{_normalized_gamma_tag(gamma)}",
                    include_price_insensitive_comparison=include_benchmark,
                    risk_measure=risk_mode,
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    write_outputs=True,
                )
                actual_price_signature = tuple(np.round(result.actual_prices["actual_price_eur_per_mwh"].astype(float).to_numpy(), 9).tolist())
                if delivery_day in benchmark_signature_by_day:
                    same_benchmark_signature = benchmark_signature_by_day[delivery_day] == actual_price_signature
                    benchmark_identity_rows.append(
                        _validation_row(
                            check_name="benchmark_day_price_signature_consistent_across_artifacts",
                            status="pass" if same_benchmark_signature else "fail",
                            details=f"delivery_day={delivery_day}; same_actual_price_signature={same_benchmark_signature}",
                            severity="hard_fail",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                        )
                    )
                else:
                    benchmark_signature_by_day[delivery_day] = actual_price_signature
                if not result.benchmark_comparison.empty:
                    benchmark_row = result.benchmark_comparison.iloc[0].copy()
                    benchmark_cache[benchmark_key] = benchmark_row
                    benchmark_daily_rows.append(
                        _benchmark_daily_row(
                            benchmark_row=benchmark_row,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                            run_id=run_id,
                        )
                    )
                else:
                    benchmark_row = benchmark_cache.get(benchmark_key)

                if include_perfect_foresight_benchmark and delivery_day not in perfect_foresight_profit_by_day:
                    pf_log_root = run_dir / "perfect_foresight_day_runs" / delivery_day
                    pf_log_root.mkdir(parents=True, exist_ok=True)
                    pf_summary, _, _ = _run_perfect_foresight_badarinath_style_comparison(
                        day_frame=result.scenarios,
                        actual_prices=result.actual_prices,
                        config=day_run_config,
                        run_id=run_id,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        solver_log_root=pf_log_root,
                    )
                    pf_row = pf_summary.iloc[0].copy()
                    perfect_foresight_profit_by_day[delivery_day] = pf_row
                    perfect_foresight_signature_by_day[delivery_day] = actual_price_signature
                    perfect_foresight_daily_rows.append(
                        _perfect_foresight_daily_row(
                            pf_row=pf_row,
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
                            regime_label=str(week_meta["regime_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                            run_id=run_id,
                        )
                    )
                elif include_perfect_foresight_benchmark:
                    pf_same_signature = perfect_foresight_signature_by_day[delivery_day] == actual_price_signature
                    perfect_foresight_identity_rows.append(
                        _validation_row(
                            check_name="perfect_foresight_day_price_signature_consistent_across_artifacts",
                            status="pass" if pf_same_signature else "fail",
                            details=f"delivery_day={delivery_day}; same_actual_price_signature={pf_same_signature}",
                            severity="hard_fail",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                        )
                    )
                pf_row = perfect_foresight_profit_by_day.get(delivery_day)

                metric_row = _build_daily_metric_row(
                    result=result,
                    artifact_id=artifact_id,
                    model_label=model_label,
                    validation_mode=validation_mode,
                    thesis_grade=thesis_grade,
                    forecast_origin_reconstruction_used=reconstruction_used,
                    week_row=week_row,
                    day_row=pd.Series(day_record),
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    benchmark_row=benchmark_row,
                )
                metric_row["regime_label"] = str(week_meta["regime_label"])
                metric_row["cvar_tail_profit"] = float(-metric_row["cvar_loss"])
                if pf_row is not None:
                    pf_profit = float(pf_row["realised_adjusted_profit_eur"])
                    metric_row["perfect_foresight_profit"] = pf_profit
                    metric_row["value_captured_vs_perfect_foresight"] = float(metric_row["realised_adjusted_profit"] / pf_profit) if abs(pf_profit) > 1e-9 else float("nan")
                    metric_row["regret_vs_perfect_foresight"] = float(pf_profit - metric_row["realised_adjusted_profit"])
                else:
                    metric_row["perfect_foresight_profit"] = pd.NA
                    metric_row["value_captured_vs_perfect_foresight"] = pd.NA
                    metric_row["regret_vs_perfect_foresight"] = pd.NA
                daily_rows.append(metric_row)

                validation_rows.append(
                    result.validation_checks.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_meta["week_id"]),
                        week_label=str(week_meta["week_label"]),
                        regime_label=str(week_meta["regime_label"]),
                        delivery_day=delivery_day,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        risk_mode=str(risk_mode),
                    )
                )
                metadata = {
                    "artifact_id": artifact_id,
                    "model_label": model_label,
                    "week_id": str(week_meta["week_id"]),
                    "week_label": str(week_meta["week_label"]),
                    "regime_label": str(week_meta["regime_label"]),
                    "delivery_day": delivery_day,
                    "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
                    "cvar_alpha": float(cvar_alpha),
                    "cvar_gamma": float(gamma),
                    "risk_mode": str(risk_mode),
                }
                submitted_rows.append(result.optimisation_result.submitted_bids.assign(**metadata))
                scenario_clearing_rows.append(result.optimisation_result.scenario_clearing.assign(**metadata))
                scenario_settlement_rows.append(result.optimisation_result.scenario_economics.assign(**metadata))
                actual_clearing_rows.append(result.actual_clearing.assign(**metadata))
                actual_redispatch_rows.append(result.actual_redispatch_timeseries.assign(**metadata))
                actual_settlement_rows.append(result.actual_settlement_results.assign(**metadata))
                scenario_fan_rows.append(result.scenarios.assign(**metadata))
                day_run_dir_rows.append({**metadata, "run_dir": str(result.run_dir) if result.run_dir is not None else ""})
                day_manifest_path = Path(str(result.run_dir)) / "scenario_manifest.json" if result.run_dir is not None else None
                day_manifest = json.loads(day_manifest_path.read_text(encoding="utf-8")) if day_manifest_path is not None and day_manifest_path.exists() else {}
                day_manifest.update(metadata)
                scenario_manifest_rows.append(day_manifest)

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase D2 produced no daily metrics.")
    daily_metrics["run_id"] = str(run_id)
    daily_metrics["period_type"] = "validation"

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_checks_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["week_label", "model_label", "delivery_day"]).reset_index(drop=True)
    perfect_foresight_daily = pd.DataFrame(perfect_foresight_daily_rows).sort_values(["week_label", "delivery_day"]).reset_index(drop=True)
    scenario_frame = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    coverage = _scenario_coverage_by_day(scenario_frame)
    daily_metrics = daily_metrics.merge(
        coverage,
        on=["artifact_id", "model_label", "delivery_day", "cvar_gamma"],
        how="left",
    )

    benchmark_metrics_parts: list[pd.DataFrame] = []
    weekly_parts: list[pd.DataFrame] = []
    for _, week_row in selected_weeks.iterrows():
        week_id = str(week_row["week_id"])
        week_daily = daily_metrics.loc[daily_metrics["week_id"].astype(str).eq(week_id)].copy()
        week_weekly = _aggregate_weekly_metrics(week_daily, selected_week=pd.Series(week_row)).copy()
        week_weekly["regime_label"] = str(week_row["regime_label"])
        weekly_parts.append(week_weekly)
        bench_subset = benchmark_daily.loc[benchmark_daily["week_id"].astype(str).eq(week_id)].copy()
        if not bench_subset.empty:
            bench_week = _aggregate_benchmark_metrics(bench_subset, selected_week=pd.Series(week_row)).copy()
            bench_week["regime_label"] = str(week_row["regime_label"])
            benchmark_metrics_parts.append(bench_week)
    weekly_metrics = pd.concat(weekly_parts, ignore_index=True).sort_values(["week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)
    benchmark_metrics = pd.concat(benchmark_metrics_parts, ignore_index=True) if benchmark_metrics_parts else pd.DataFrame()
    perfect_foresight_metrics = _aggregate_perfect_foresight_metrics(perfect_foresight_daily)

    if not perfect_foresight_metrics.empty:
        pf_weekly = perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly"), ["week_id", "realised_adjusted_profit"]].rename(columns={"realised_adjusted_profit": "perfect_foresight_profit"})
        weekly_metrics = weekly_metrics.merge(pf_weekly, on="week_id", how="left")
        weekly_metrics["value_captured_vs_perfect_foresight"] = np.where(
            pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce").abs() > 1e-9,
            pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce") / pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce"),
            np.nan,
        )
        weekly_metrics["regret_vs_perfect_foresight"] = pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce") - pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")
    else:
        weekly_metrics["perfect_foresight_profit"] = pd.NA
        weekly_metrics["value_captured_vs_perfect_foresight"] = pd.NA
        weekly_metrics["regret_vs_perfect_foresight"] = pd.NA
    weekly_metrics["cvar_tail_profit"] = -pd.to_numeric(weekly_metrics["cvar_loss"], errors="coerce")
    weekly_metrics_by_model_gamma = weekly_metrics.copy()
    cvar_sweep_daily = daily_metrics.copy()
    cvar_sweep_weekly = weekly_metrics.copy()
    cvar_frontier_by_model_week = _build_cvar_frontier_by_model_week(weekly_metrics)
    cvar_frontier_aggregated = _build_cvar_frontier_aggregated(weekly_metrics)
    gamma_policy_candidate_summary = _build_gamma_policy_candidate_summary(cvar_frontier_aggregated)
    cvar_bid_firmness_metrics = weekly_metrics[["week_id", "week_label", "regime_label", "artifact_id", "model_label", "cvar_alpha", "cvar_gamma", "weighted_average_bid_price", "high_bid_share", "market_cap_bid_share", "clearing_ratio", "rejected_energy_mwh"]].copy()
    model_stats_by_gamma = _build_model_stats_by_gamma_week(daily_metrics)
    solver_log_manifest = _build_solver_log_manifest(day_run_dirs)
    scenario_manifest = {
        "phase": "D2",
        "support_label": "validation-period CVaR sensitivity analysis on common partial support",
        "artifacts": scenario_manifest_rows,
    }
    save_json(run_dir, "scenario_manifest.json", scenario_manifest)

    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        scenario_settlement_results=scenario_settlement_results,
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
    )
    benchmark_identity_checks = pd.DataFrame(benchmark_identity_rows)
    perfect_foresight_identity_checks = pd.DataFrame(perfect_foresight_identity_rows)
    validation_checks_all_runs = _build_general_validation_checks(
        existing_checks=validation_checks_existing,
        selected_weeks=selected_weeks,
        support_days=support_days,
        artifact_ids=[str(value) for value in artifact_ids],
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        perfect_foresight_daily=perfect_foresight_daily,
        perfect_foresight_included=bool(include_perfect_foresight_benchmark),
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
        benchmark_identity_checks=benchmark_identity_checks,
        perfect_foresight_identity_checks=perfect_foresight_identity_checks,
    )

    save_frame_csv(run_dir, "model_stats_by_gamma.csv", model_stats_by_gamma)
    save_frame_csv(run_dir, "solver_log_manifest.csv", solver_log_manifest)
    save_frame_parquet(run_dir, "submitted_bids.parquet", submitted_bids)
    save_frame_parquet(run_dir, "scenario_clearing.parquet", scenario_clearing)
    save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
    save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)
    save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "weekly_metrics_by_model_gamma.csv", weekly_metrics_by_model_gamma)
    save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(run_dir, "cvar_sweep_daily.csv", cvar_sweep_daily)
    save_frame_csv(run_dir, "cvar_sweep_weekly.csv", cvar_sweep_weekly)
    save_frame_csv(run_dir, "cvar_frontier_by_model_week.csv", cvar_frontier_by_model_week)
    save_frame_csv(run_dir, "cvar_frontier_aggregated.csv", cvar_frontier_aggregated)
    save_frame_csv(run_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "gamma_policy_candidate_summary.csv", gamma_policy_candidate_summary)
    save_frame_csv(run_dir, "day_run_dirs.csv", day_run_dirs)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "selected_weeks_manifest_table.csv", selected_weeks)
    save_frame_csv(notebook_inputs_dir, "support_days.csv", support_days)
    save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_by_model_week.csv", cvar_frontier_by_model_week)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_aggregated.csv", cvar_frontier_aggregated)
    save_frame_csv(notebook_inputs_dir, "gamma_policy_candidate_summary.csv", gamma_policy_candidate_summary)
    save_frame_csv(notebook_inputs_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(notebook_inputs_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    if not scenario_frame.empty:
        save_frame_parquet(notebook_inputs_dir, "scenario_fan_inputs.parquet", scenario_frame)
    if not submitted_bids.empty:
        save_frame_parquet(notebook_inputs_dir, "submitted_bids.parquet", submitted_bids)
    if not actual_clearing.empty:
        save_frame_parquet(notebook_inputs_dir, "actual_clearing.parquet", actual_clearing)
    if not actual_redispatch_timeseries.empty:
        save_frame_parquet(notebook_inputs_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    if not scenario_settlement_results.empty:
        save_frame_csv(notebook_inputs_dir, "scenario_settlement_results.csv", scenario_settlement_results)

    _create_figures(
        run_dir=run_dir,
        daily_metrics=daily_metrics,
        submitted_bids=submitted_bids,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
        weekly_metrics=weekly_metrics,
        gamma_policy_candidate_summary=gamma_policy_candidate_summary,
    )
    _write_readme(
        run_dir=run_dir,
        selected_weeks=selected_weeks,
        artifact_ids=[str(value) for value in artifact_ids],
        cvar_alpha=float(cvar_alpha),
        gamma_values=gamma_list,
        benchmark_included=bool(include_price_insensitive_benchmark),
        perfect_foresight_included=bool(include_perfect_foresight_benchmark),
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        gamma_policy_candidate_summary=gamma_policy_candidate_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )

    hard_fail_count = int(validation_checks_all_runs.loc[(validation_checks_all_runs["severity"].astype(str) == "hard_fail") & (validation_checks_all_runs["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    if hard_fail_count > 0 or cvar_fail_count > 0:
        raise RuntimeError(
            f"Phase D2 completed but validation failed (hard_fail_count={hard_fail_count}, cvar_fail_count={cvar_fail_count}); see run folder {run_dir}."
        )

    notebook_path = Path("scripts/Data/03_Hydrogen_Test_Case/notebooks/11_cvar_validation_sensitivity_analysis.ipynb")
    return PhaseD2ExpandedSweepResult(
        run_dir=run_dir,
        notebook_path=notebook_path,
        selected_weeks=selected_weeks,
        support_days=support_days,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        cvar_frontier_aggregated=cvar_frontier_aggregated,
        gamma_policy_candidate_summary=gamma_policy_candidate_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
    )
