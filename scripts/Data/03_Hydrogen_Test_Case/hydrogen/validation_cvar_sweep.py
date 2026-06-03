from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .bidding_backtest import run_real_scenario_bidding_dry_run
from .cvar import compute_weighted_cvar_from_frame
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import create_run_folder, save_config_resolved, save_frame_csv, save_frame_parquet, save_inputs_manifest, save_json, save_text
from .selected_week_policy import (
    VALIDATION_SELECTED_REGIME_LABELS,
    resolve_registry_rows,
    run_selected_week_input_preflight,
)
from .selected_week_smoke import (
    DEFAULT_ARTIFACT_IDS,
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    TOLERANCE,
    _label_for_artifact,
    _validation_row,
    _weighted_quantile,
)
from .selected_week_suite import _valid_daily_registry_for_artifact

try:
    from visual_style import MODEL_COLORS, apply_visual_style
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR Strict": "#C97941",
        "LEAR FS3 pruned candidate": "#3A7D7C",
        "XGBoost FS3 pruned candidate": "#1F4E79",
        "Price insensitive benchmark": "#333333",
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
DEFAULT_GAMMAS = (0.0, 0.05, 0.25)


@dataclass(frozen=True)
class PhaseDValidationSweepResult:
    run_dir: Path
    selected_week: pd.Series
    support_days: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    cvar_sweep_daily: pd.DataFrame
    cvar_sweep_weekly: pd.DataFrame
    cvar_frontier_by_model: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    validation_checks: pd.DataFrame


def _weighted_percentile_leq(values: pd.Series, weights: pd.Series, threshold: float) -> float:
    frame = pd.DataFrame({"value": values, "weight": weights}).dropna()
    if frame.empty:
        return float("nan")
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0).astype(float)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(float)
    total_weight = float(frame["weight"].sum())
    if total_weight <= 0.0:
        return float("nan")
    mass = float(frame.loc[frame["value"] <= float(threshold), "weight"].sum())
    return float(100.0 * mass / total_weight)


def _normalized_gamma_tag(gamma: float) -> str:
    text = str(float(gamma)).replace("-", "m").replace(".", "p")
    return text


def _load_and_validate_phase_d_week(
    *,
    week_registry_path: Path,
    support_csv_path: Path,
    selected_weeks_yaml_path: Path | None,
    week_id: str,
) -> tuple[pd.Series, pd.DataFrame]:
    if selected_weeks_yaml_path is None:
        raise ValueError("Phase D requires the official selected validation-week config.")
    row = resolve_registry_rows(
        registry_path=week_registry_path,
        selected_weeks_yaml_path=selected_weeks_yaml_path,
        requested_identifiers=[str(week_id)],
        expected_split="validation",
    ).iloc[0].copy()
    expected_start = str(row["delivery_start_date"])
    expected_end = str(row["delivery_end_date"])

    checks = {
        "regime_label": (
            str(row["regime_label"]) in VALIDATION_SELECTED_REGIME_LABELS,
            f"expected one of {list(VALIDATION_SELECTED_REGIME_LABELS)}, got {row['regime_label']}",
        ),
        "delivery_start_date": (str(row["delivery_start_date"]) == expected_start, f"expected {expected_start}, got {row['delivery_start_date']}"),
        "delivery_end_date": (str(row["delivery_end_date"]) == expected_end, f"expected {expected_end}, got {row['delivery_end_date']}"),
        "period_type": (str(row["period_type"]) == "validation", f"expected validation, got {row['period_type']}"),
        "number_of_delivery_days": (int(row["number_of_delivery_days"]) == 7, f"expected 7, got {row['number_of_delivery_days']}"),
        "complete_for_lear_strict": (bool(row["complete_for_lear_strict"]), "LEAR Strict week row is not complete."),
        "complete_for_lear_fs3": (bool(row["complete_for_lear_fs3"]), "LEAR FS3 week row is not complete."),
        "complete_for_xgboost_fs3": (bool(row["complete_for_xgboost_fs3"]), "XGBoost FS3 week row is not complete."),
        "complete_actual_prices": (bool(row["complete_actual_prices"]), "Actual prices are not complete."),
        "support_status": (str(row["support_status"]) == "common_complete_support_selected", f"expected common_complete_support_selected, got {row['support_status']}"),
        "methodological_use": (str(row["methodological_use"]) == "cvar_selection", f"expected cvar_selection, got {row['methodological_use']}"),
    }
    failures = [f"{name}: {message}" for name, (ok, message) in checks.items() if not ok]
    if failures:
        raise ValueError("Phase D selected-week validation failed: " + "; ".join(failures))

    if not support_csv_path.exists():
        raise FileNotFoundError(f"Common-support day table not found: {support_csv_path}")
    support_days = pd.read_csv(support_csv_path)
    support_days["delivery_date"] = pd.to_datetime(support_days["delivery_date"], errors="raise")
    week_days = support_days.loc[
        (support_days["delivery_date"] >= pd.Timestamp(expected_start))
        & (support_days["delivery_date"] <= pd.Timestamp(expected_end))
    ].copy()
    if int(week_days.shape[0]) != 7:
        raise ValueError(f"Expected 7 common-support day rows for {row['week_label']}, found {int(week_days.shape[0])}.")
    expected_dates = pd.date_range(expected_start, expected_end, freq="D")
    actual_dates = pd.DatetimeIndex(week_days["delivery_date"]).sort_values()
    if not actual_dates.equals(expected_dates):
        raise ValueError(f"Validation-week support rows are not exactly the requested dates: {actual_dates.strftime('%Y-%m-%d').tolist()}")
    required_complete = (
        week_days["period_type"].astype(str).eq("validation")
        & week_days["complete_actual_prices"].astype(bool)
        & week_days["complete_for_lear_strict"].astype(bool)
        & week_days["complete_for_lear_fs3"].astype(bool)
        & week_days["complete_for_xgboost_fs3"].astype(bool)
        & week_days["common_complete_support"].astype(bool)
        & week_days["n_hours_actual"].astype(int).eq(24)
        & week_days["n_hours_lear_strict"].astype(int).eq(24)
        & week_days["n_hours_lear_fs3"].astype(int).eq(24)
        & week_days["n_hours_xgboost_fs3"].astype(int).eq(24)
        & week_days["n_scenarios_per_origin_lear_strict"].astype(int).eq(75)
        & week_days["n_scenarios_per_origin_lear_fs3"].astype(int).eq(75)
        & week_days["n_scenarios_per_origin_xgboost_fs3"].astype(int).eq(75)
    )
    if not bool(required_complete.all()):
        failing_days = week_days.loc[~required_complete, "delivery_date"].dt.strftime("%Y-%m-%d").tolist()
        raise ValueError(f"Validation week contains days that are not exact common complete support: {failing_days}")
    return row, week_days.reset_index(drop=True)


def _build_phase_d_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_ids: list[str] | tuple[str, ...],
    output_root: Path | None,
    experiment_name: str,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    updated = replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(experiment_name),
            execution_mode="validation_week_cvar_sweep",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=("stochastic_cvar_selected_validation_week",),
    )
    if output_root is not None:
        updated = replace(updated, outputs=replace(updated.outputs, root=Path(output_root)))
    return updated


def _scenario_coverage_by_day(scenario_frame: pd.DataFrame) -> pd.DataFrame:
    if scenario_frame.empty:
        return pd.DataFrame(
            columns=[
                "artifact_id",
                "model_label",
                "delivery_day",
                "cvar_gamma",
                "actual_price_within_scenario_minmax_share",
                "actual_price_within_p10_p90_share",
                "actual_price_within_p05_p95_share",
            ]
        )
    frame = scenario_frame.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(["artifact_id", "model_label", "delivery_day", "cvar_gamma"], sort=False):
        artifact_id, model_label, delivery_day, gamma = keys
        within_minmax = 0
        within_p10_p90 = 0
        within_p05_p95 = 0
        hour_count = 0
        for _, hour_group in group.groupby("delivery_start_utc", sort=True):
            values = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            weights = hour_group["scenario_probability"].astype(float).to_numpy()
            actual = float(hour_group["actual_price_eur_per_mwh"].iloc[0])
            if values.size == 0:
                continue
            hour_count += 1
            scenario_min = float(np.min(values))
            scenario_max = float(np.max(values))
            p10 = _weighted_quantile(values, weights, 0.10)
            p90 = _weighted_quantile(values, weights, 0.90)
            p05 = _weighted_quantile(values, weights, 0.05)
            p95 = _weighted_quantile(values, weights, 0.95)
            within_minmax += int(scenario_min - TOLERANCE <= actual <= scenario_max + TOLERANCE)
            within_p10_p90 += int(p10 - TOLERANCE <= actual <= p90 + TOLERANCE)
            within_p05_p95 += int(p05 - TOLERANCE <= actual <= p95 + TOLERANCE)
        denom = max(hour_count, 1)
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "delivery_day": str(delivery_day),
                "cvar_gamma": float(gamma),
                "actual_price_within_scenario_minmax_share": float(within_minmax / denom),
                "actual_price_within_p10_p90_share": float(within_p10_p90 / denom),
                "actual_price_within_p05_p95_share": float(within_p05_p95 / denom),
            }
        )
    return pd.DataFrame(rows)


def _benchmark_daily_row(
    *,
    benchmark_row: pd.Series,
    artifact_id: str,
    model_label: str,
    week_id: str,
    week_label: str,
    delivery_day: str,
    forecast_origin_utc: pd.Timestamp,
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "artifact_id": str(artifact_id),
        "model_label": str(model_label),
        "week_id": str(week_id),
        "week_label": str(week_label),
        "period_type": "validation",
        "aggregation_level": "daily",
        "delivery_day": str(delivery_day),
        "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
        "strategy": "price_insensitive_plan_first_market_cap",
        "realised_adjusted_profit": float(benchmark_row["realised_adjusted_profit_eur"]),
        "cleared_energy_mwh": float(benchmark_row["cleared_energy_mwh"]),
        "used_energy_mwh": float(benchmark_row["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(benchmark_row["unused_cleared_energy_mwh"]),
        "hydrogen_sold_or_compressed_kg": float(benchmark_row["hydrogen_compressed_or_sold_kg"]),
        "shortfall_kg": float(benchmark_row["shortfall_kg"]),
        "da_settlement_cost": float(benchmark_row["realised_DA_settlement_cost_eur"]),
        "hydrogen_revenue": float(benchmark_row["hydrogen_revenue_eur"]),
        "unused_energy_penalty": float(benchmark_row["unused_energy_penalty_eur"]),
        "shortfall_penalty": float(benchmark_row["shortfall_penalty_eur"]),
        "terminal_inventory_correction": float(benchmark_row["terminal_inventory_correction_eur"]),
        "average_actual_price_paid": float(benchmark_row["weighted_average_actual_price_paid_for_cleared_energy"]),
        "solver_status": str(benchmark_row["solver_status"]),
        "solve_time_seconds": float(benchmark_row["solve_time_seconds"]),
    }


def _build_daily_metric_row(
    *,
    result: Any,
    artifact_id: str,
    model_label: str,
    validation_mode: str,
    thesis_grade: bool,
    forecast_origin_reconstruction_used: bool,
    week_row: pd.Series,
    day_row: pd.Series,
    cvar_alpha: float,
    cvar_gamma: float,
    benchmark_row: pd.Series | None,
) -> dict[str, Any]:
    metrics = result.metrics_summary.iloc[0]
    summary = result.optimisation_result.summary.iloc[0]
    actual_summary = result.actual_settlement_results.iloc[0]
    submitted = result.optimisation_result.submitted_bids.copy()
    actual_clearing = result.actual_clearing.copy()
    scenario_results = result.scenario_objective_summary.copy()
    actual_redispatch = result.actual_redispatch_timeseries.copy()
    scenario_probs = scenario_results[["scenario_id", "scenario_probability"]].drop_duplicates(subset=["scenario_id"]).copy()
    scenario_count = int(scenario_probs["scenario_id"].astype(str).nunique())
    probability_sum = float(scenario_probs["scenario_probability"].astype(float).sum())

    submitted_energy_total = float(submitted["bid_quantity_mw"].astype(float).sum())
    weighted_avg_bid_price = float(summary["weighted_average_bid_price_eur_per_mwh"])
    bid_energy_ge_250 = float(submitted.loc[submitted["bid_price_eur_per_mwh"].astype(float) >= 250.0, "bid_quantity_mw"].astype(float).sum())
    bid_energy_at_market_cap = float(
        submitted.loc[np.isclose(submitted["bid_price_eur_per_mwh"].astype(float), submitted["bid_price_eur_per_mwh"].astype(float).max()), "bid_quantity_mw"].astype(float).sum()
    )
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy()
    accepted["bid_headroom"] = accepted["bid_price_eur_per_mwh"].astype(float) - accepted["actual_price_eur_per_mwh"].astype(float)
    accepted_energy = float(accepted["cleared_energy_mwh"].astype(float).sum()) if not accepted.empty else 0.0
    accepted_headroom_numerator = float((accepted["bid_headroom"].astype(float) * accepted["cleared_energy_mwh"].astype(float)).sum()) if not accepted.empty else 0.0

    reconstructed = compute_weighted_cvar_from_frame(
        scenario_results,
        loss_column="loss_eur",
        probability_column="scenario_probability",
        alpha=float(cvar_alpha),
    )
    realised_profit = float(metrics["realised_adjusted_profit_eur"])
    expected_profit = float(metrics["expected_adjusted_profit_eur"])
    realised_profit_percentile = _weighted_percentile_leq(
        scenario_results["adjusted_profit_eur"],
        scenario_results["scenario_probability"],
        realised_profit,
    )
    scenario_profit_values = scenario_results["adjusted_profit_eur"].astype(float).to_numpy()
    scenario_prob_values = scenario_results["scenario_probability"].astype(float).to_numpy()
    p05 = _weighted_quantile(scenario_profit_values, scenario_prob_values, 0.05)
    p10 = _weighted_quantile(scenario_profit_values, scenario_prob_values, 0.10)
    p50 = _weighted_quantile(scenario_profit_values, scenario_prob_values, 0.50)
    p90 = _weighted_quantile(scenario_profit_values, scenario_prob_values, 0.90)
    p95 = _weighted_quantile(scenario_profit_values, scenario_prob_values, 0.95)
    electrolyser_energy = float(
        (pd.to_numeric(actual_redispatch["P_el_mw"], errors="coerce").fillna(0.0) * pd.to_numeric(actual_redispatch["timestep_hours"], errors="coerce").fillna(1.0)).sum()
    )
    compressor_energy = float(
        (pd.to_numeric(actual_redispatch["P_comp_mw"], errors="coerce").fillna(0.0) * pd.to_numeric(actual_redispatch["timestep_hours"], errors="coerce").fillna(1.0)).sum()
    )
    validation_fail_count = int((result.validation_checks["status"].astype(str) == "fail").sum())
    validation_warn_count = int((result.validation_checks["status"].astype(str) == "warn").sum())

    benchmark_profit = float(benchmark_row["realised_adjusted_profit_eur"]) if benchmark_row is not None else float("nan")
    benchmark_cleared = float(benchmark_row["cleared_energy_mwh"]) if benchmark_row is not None else float("nan")
    benchmark_hydrogen = float(benchmark_row["hydrogen_compressed_or_sold_kg"]) if benchmark_row is not None else float("nan")
    benchmark_price_paid = float(benchmark_row["weighted_average_actual_price_paid_for_cleared_energy"]) if benchmark_row is not None else float("nan")
    benchmark_shortfall = float(benchmark_row["shortfall_kg"]) if benchmark_row is not None else float("nan")

    risk_mode = "risk_neutral" if abs(float(cvar_gamma)) <= 1e-12 else "cvar"
    return {
        "artifact_id": str(artifact_id),
        "model_id": str(result.scenarios["model_id"].astype(str).iloc[0]),
        "model_label": str(model_label),
        "validation_mode": str(validation_mode),
        "thesis_grade": bool(thesis_grade),
        "forecast_origin_reconstruction_used": bool(forecast_origin_reconstruction_used),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "period_type": "validation",
        "selection_reason": str(week_row["selection_reason"]),
        "delivery_day": str(result.delivery_day),
        "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
        "day_run_dir": str(result.run_dir) if result.run_dir is not None else "",
        "strategy": "stochastic_bid_risk_neutral" if risk_mode == "risk_neutral" else "stochastic_bid_cvar",
        "risk_mode": str(risk_mode),
        "cvar_alpha": float(cvar_alpha),
        "cvar_gamma": float(cvar_gamma),
        "actual_price_mean": float(day_row["actual_price_mean"]),
        "actual_price_min": float(day_row["actual_price_min"]),
        "actual_price_max": float(day_row["actual_price_max"]),
        "actual_price_spread": float(day_row["actual_price_spread"]),
        "actual_price_std": float(day_row["actual_price_std"]),
        "actual_negative_price_hours": int(day_row["actual_negative_price_hours"]),
        "scenario_count": int(scenario_count),
        "scenario_probability_check": bool(abs(probability_sum - 1.0) <= 1e-6),
        "expected_adjusted_profit": float(expected_profit),
        "realised_adjusted_profit": float(realised_profit),
        "realised_operating_profit": float(actual_summary["hydrogen_revenue_eur"] - actual_summary["realised_DA_settlement_cost_eur"] - actual_summary["unused_energy_penalty_eur"] - actual_summary["shortfall_penalty_eur"]),
        "hydrogen_revenue": float(actual_summary["hydrogen_revenue_eur"]),
        "da_settlement_cost": float(actual_summary["realised_DA_settlement_cost_eur"]),
        "unused_energy_penalty": float(actual_summary["unused_energy_penalty_eur"]),
        "shortfall_penalty": float(actual_summary["shortfall_penalty_eur"]),
        "terminal_inventory_correction": float(actual_summary["terminal_inventory_correction_eur"]),
        "benchmark_profit": benchmark_profit,
        "stochastic_minus_benchmark_profit": float(realised_profit - benchmark_profit) if pd.notna(benchmark_profit) else float("nan"),
        "average_actual_price_paid": float(metrics["weighted_average_actual_price_paid_for_cleared_energy"]),
        "realised_minus_expected_profit": float(realised_profit - expected_profit),
        "var_loss": float(summary["VaR_loss_zeta"]),
        "cvar_loss": float(summary["CVaR_loss"]),
        "reconstructed_var_loss": float(reconstructed.zeta),
        "reconstructed_cvar_loss": float(reconstructed.cvar),
        "cvar_reconstruction_error": float(abs(float(summary["CVaR_loss"]) - float(reconstructed.cvar))),
        "worst_scenario_profit": float(summary["worst_scenario_profit"]),
        "worst_scenario_loss": float(summary["worst_scenario_loss"]),
        "downside_tail_mean_profit": float(-reconstructed.cvar),
        "downside_tail_mean_loss": float(reconstructed.cvar),
        "realised_outcome_percentile_within_scenarios": float(realised_profit_percentile),
        "scenario_profit_p05": float(p05),
        "scenario_profit_p10": float(p10),
        "scenario_profit_p50": float(p50),
        "scenario_profit_p90": float(p90),
        "scenario_profit_p95": float(p95),
        "submitted_energy_mwh": float(metrics["submitted_energy_mwh"]),
        "cleared_energy_mwh": float(metrics["cleared_energy_mwh"]),
        "rejected_energy_mwh": float(metrics["rejected_energy_mwh"]),
        "used_cleared_energy_mwh": float(actual_summary["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(actual_summary["unused_cleared_energy_mwh"]),
        "clearing_ratio": float(metrics["clearing_ratio"]),
        "rejected_energy_share": float(metrics["rejected_energy_mwh"] / metrics["submitted_energy_mwh"]) if float(metrics["submitted_energy_mwh"]) > 0.0 else 0.0,
        "hours_with_zero_clearing": int(metrics["zero_clearing_hours"]),
        "hours_with_partial_clearing": int(metrics["partial_clearing_hours"]),
        "weighted_average_bid_price": float(weighted_avg_bid_price),
        "high_bid_share": float(summary["high_bid_energy_share_ge_250"]),
        "market_cap_bid_share": float(bid_energy_at_market_cap / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "average_bid_headroom_for_accepted_blocks": float(accepted_headroom_numerator / accepted_energy) if accepted_energy > 0.0 else float("nan"),
        "hydrogen_produced_kg": float(actual_summary["hydrogen_produced_kg"]),
        "hydrogen_sold_or_compressed_kg": float(actual_summary["hydrogen_compressed_or_sold_kg"]),
        "target_hydrogen_kg": float(actual_summary["target_hydrogen_kg"]),
        "production_fulfilment_ratio": float(actual_summary["target_fulfilment_ratio_capped_for_reliability"]),
        "shortfall_kg": float(actual_summary["shortfall_kg"]),
        "storage_start_kg": float(actual_summary["terminal_inventory_start_kg"]),
        "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"]),
        "storage_min_kg": float(actual_summary["storage_min_kg"]),
        "storage_max_kg": float(actual_summary["storage_max_kg"]),
        "reserve_boundary_hits": int(actual_summary["reserve_boundary_hits"]),
        "electrolyser_energy_mwh": float(electrolyser_energy),
        "compressor_energy_mwh": float(compressor_energy),
        "electrolyser_ramp_hits": int(actual_summary["ramp_boundary_hits"]),
        "solver_status": str(summary["solver_status"]),
        "objective_value": float(summary["objective_with_regularisation"]),
        "solve_time_seconds": float(summary["solve_time_seconds"]),
        "mip_gap": float(result.optimisation_result.solver.mip_gap) if result.optimisation_result.solver.mip_gap is not None else float("nan"),
        "variable_count": int(summary["variable_count"]),
        "binary_variable_count": int(summary["binary_variable_count"]),
        "constraint_count": int(summary["constraint_count"]),
        "benchmark_cleared_energy_mwh": benchmark_cleared,
        "benchmark_hydrogen_sold_or_compressed_kg": benchmark_hydrogen,
        "benchmark_average_actual_price_paid": benchmark_price_paid,
        "benchmark_shortfall_kg": benchmark_shortfall,
        "accepted_bid_energy_mwh": float(accepted_energy),
        "accepted_bid_headroom_weighted_numerator": float(accepted_headroom_numerator),
        "validation_fail_count": int(validation_fail_count),
        "validation_warn_count": int(validation_warn_count),
    }


def _aggregate_weekly_metrics(daily_metrics: pd.DataFrame, *, selected_week: pd.Series) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = [
        "artifact_id",
        "model_id",
        "model_label",
        "validation_mode",
        "thesis_grade",
        "week_id",
        "week_label",
        "period_type",
        "strategy",
        "risk_mode",
        "cvar_alpha",
        "cvar_gamma",
    ]
    for keys, group in daily_metrics.groupby(group_cols, sort=False, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = {column: value for column, value in zip(group_cols, keys)}
        submitted = float(group["submitted_energy_mwh"].sum())
        cleared = float(group["cleared_energy_mwh"].sum())
        accepted_energy = float(group["accepted_bid_energy_mwh"].sum())
        record.update(
            {
                "run_id": str(group["run_id"].iloc[0]),
                "week_start": str(selected_week["delivery_start_date"]),
                "week_end": str(selected_week["delivery_end_date"]),
                "number_of_delivery_days": int(group["delivery_day"].nunique()),
                "expected_adjusted_profit": float(group["expected_adjusted_profit"].sum()),
                "realised_adjusted_profit": float(group["realised_adjusted_profit"].sum()),
                "realised_operating_profit": float(group["realised_operating_profit"].sum()),
                "hydrogen_revenue": float(group["hydrogen_revenue"].sum()),
                "da_settlement_cost": float(group["da_settlement_cost"].sum()),
                "unused_energy_penalty": float(group["unused_energy_penalty"].sum()),
                "shortfall_penalty": float(group["shortfall_penalty"].sum()),
                "terminal_inventory_correction": float(group["terminal_inventory_correction"].sum()),
                "benchmark_profit": float(group["benchmark_profit"].sum()),
                "stochastic_minus_benchmark_profit": float(group["stochastic_minus_benchmark_profit"].sum()),
                "average_actual_price_paid": float(group["da_settlement_cost"].sum() / cleared) if cleared > 0.0 else float("nan"),
                "realised_minus_expected_profit": float(group["realised_minus_expected_profit"].sum()),
                "var_loss": float(group["var_loss"].sum()),
                "cvar_loss": float(group["cvar_loss"].sum()),
                "reconstructed_var_loss": float(group["reconstructed_var_loss"].sum()),
                "reconstructed_cvar_loss": float(group["reconstructed_cvar_loss"].sum()),
                "cvar_reconstruction_error": float(group["cvar_reconstruction_error"].sum()),
                "worst_scenario_profit": float(group["worst_scenario_profit"].sum()),
                "worst_scenario_loss": float(group["worst_scenario_loss"].sum()),
                "downside_tail_mean_profit": float(group["downside_tail_mean_profit"].sum()),
                "downside_tail_mean_loss": float(group["downside_tail_mean_loss"].sum()),
                "realised_outcome_percentile_within_scenarios": float(group["realised_outcome_percentile_within_scenarios"].mean()),
                "scenario_profit_p05": float(group["scenario_profit_p05"].mean()),
                "scenario_profit_p10": float(group["scenario_profit_p10"].mean()),
                "scenario_profit_p50": float(group["scenario_profit_p50"].mean()),
                "scenario_profit_p90": float(group["scenario_profit_p90"].mean()),
                "scenario_profit_p95": float(group["scenario_profit_p95"].mean()),
                "submitted_energy_mwh": submitted,
                "cleared_energy_mwh": cleared,
                "rejected_energy_mwh": float(group["rejected_energy_mwh"].sum()),
                "used_cleared_energy_mwh": float(group["used_cleared_energy_mwh"].sum()),
                "unused_cleared_energy_mwh": float(group["unused_cleared_energy_mwh"].sum()),
                "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
                "rejected_energy_share": float(group["rejected_energy_mwh"].sum() / submitted) if submitted > 0.0 else 0.0,
                "hours_with_zero_clearing": int(group["hours_with_zero_clearing"].sum()),
                "hours_with_partial_clearing": int(group["hours_with_partial_clearing"].sum()),
                "weighted_average_bid_price": float(np.average(group["weighted_average_bid_price"], weights=group["submitted_energy_mwh"])) if submitted > 0.0 else float("nan"),
                "high_bid_share": float(group["submitted_energy_mwh"].mul(group["high_bid_share"]).sum() / submitted) if submitted > 0.0 else 0.0,
                "market_cap_bid_share": float(group["submitted_energy_mwh"].mul(group["market_cap_bid_share"]).sum() / submitted) if submitted > 0.0 else 0.0,
                "average_bid_headroom_for_accepted_blocks": float(group["accepted_bid_headroom_weighted_numerator"].sum() / accepted_energy) if accepted_energy > 0.0 else float("nan"),
                "hydrogen_produced_kg": float(group["hydrogen_produced_kg"].sum()),
                "hydrogen_sold_or_compressed_kg": float(group["hydrogen_sold_or_compressed_kg"].sum()),
                "target_hydrogen_kg": float(group["target_hydrogen_kg"].sum()),
                "production_fulfilment_ratio": float(min(group["hydrogen_sold_or_compressed_kg"].sum(), group["target_hydrogen_kg"].sum()) / group["target_hydrogen_kg"].sum()) if float(group["target_hydrogen_kg"].sum()) > 0.0 else float("nan"),
                "shortfall_kg": float(group["shortfall_kg"].sum()),
                "storage_start_kg": float(group["storage_start_kg"].iloc[0]),
                "storage_end_kg": float(group["storage_end_kg"].iloc[-1]),
                "storage_min_kg": float(group["storage_min_kg"].min()),
                "storage_max_kg": float(group["storage_max_kg"].max()),
                "reserve_boundary_hits": int(group["reserve_boundary_hits"].sum()),
                "electrolyser_energy_mwh": float(group["electrolyser_energy_mwh"].sum()),
                "compressor_energy_mwh": float(group["compressor_energy_mwh"].sum()),
                "electrolyser_ramp_hits": int(group["electrolyser_ramp_hits"].sum()),
                "scenario_count": int(group["scenario_count"].mode().iloc[0]),
                "scenario_probability_check": bool(group["scenario_probability_check"].all()),
                "actual_price_within_scenario_minmax_share": float(group["actual_price_within_scenario_minmax_share"].mean()),
                "actual_price_within_p10_p90_share": float(group["actual_price_within_p10_p90_share"].mean()),
                "actual_price_within_p05_p95_share": float(group["actual_price_within_p05_p95_share"].mean()),
                "solver_status": "Optimal" if group["solver_status"].astype(str).eq("Optimal").all() else "mixed",
                "objective_value": float(group["objective_value"].sum()),
                "solve_time_seconds": float(group["solve_time_seconds"].sum()),
                "mip_gap": float(group["mip_gap"].max(skipna=True)) if not group["mip_gap"].dropna().empty else float("nan"),
                "variable_count": int(group["variable_count"].max()),
                "binary_variable_count": int(group["binary_variable_count"].max()),
                "constraint_count": int(group["constraint_count"].max()),
            }
        )
        rows.append(record)
    return pd.DataFrame(rows)


def _aggregate_benchmark_metrics(benchmark_daily: pd.DataFrame, *, selected_week: pd.Series) -> pd.DataFrame:
    if benchmark_daily.empty:
        return pd.DataFrame()
    weekly = (
        benchmark_daily.groupby(["run_id", "artifact_id", "model_label", "week_id", "week_label", "period_type"], as_index=False)
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
        )
    )
    weekly["week_start"] = str(selected_week["delivery_start_date"])
    weekly["week_end"] = str(selected_week["delivery_end_date"])
    weekly["strategy"] = "price_insensitive_plan_first_market_cap"
    weekly["aggregation_level"] = "weekly"
    weekly["average_actual_price_paid"] = weekly["da_settlement_cost"] / weekly["cleared_energy_mwh"]
    benchmark_daily = benchmark_daily.copy()
    benchmark_daily["aggregation_level"] = "daily"
    benchmark_daily["strategy"] = "price_insensitive_plan_first_market_cap"
    return pd.concat([benchmark_daily, weekly], ignore_index=True, sort=False)


def _build_model_stats_by_gamma(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    return (
        daily_metrics.groupby(["artifact_id", "model_label", "cvar_alpha", "cvar_gamma"], as_index=False)
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
        .sort_values(["model_label", "cvar_gamma"])
        .reset_index(drop=True)
    )


def _build_cvar_frontier_by_model(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "artifact_id",
        "model_label",
        "cvar_alpha",
        "cvar_gamma",
        "expected_adjusted_profit",
        "realised_adjusted_profit",
        "cvar_loss",
        "reconstructed_cvar_loss",
        "worst_scenario_profit",
        "worst_scenario_loss",
        "stochastic_minus_benchmark_profit",
    ]
    return weekly_metrics[cols].copy().sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)


def _build_cvar_bid_firmness_metrics(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "artifact_id",
        "model_label",
        "cvar_alpha",
        "cvar_gamma",
        "weighted_average_bid_price",
        "high_bid_share",
        "market_cap_bid_share",
        "submitted_energy_mwh",
        "rejected_energy_mwh",
        "clearing_ratio",
        "average_bid_headroom_for_accepted_blocks",
    ]
    return weekly_metrics[cols].copy().sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)


def _build_solver_log_manifest(day_run_dirs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in day_run_dirs.to_dict(orient="records"):
        run_dir = Path(str(row["run_dir"]))
        log_names = ["solver_log.txt", "actual_redispatch_solver_log.txt", "bench_solver_log.txt", "bench_redisp_log.txt"]
        for name in log_names:
            path = run_dir / name
            rows.append(
                {
                    "artifact_id": str(row["artifact_id"]),
                    "model_label": str(row["model_label"]),
                    "delivery_day": str(row["delivery_day"]),
                    "cvar_gamma": float(row["cvar_gamma"]),
                    "log_type": str(name),
                    "exists": bool(path.exists()),
                    "path": str(path),
                }
            )
    return pd.DataFrame(rows)


def _build_cvar_validation_checks(
    *,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    gamma_values: list[float],
    cvar_alpha: float,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    rows.append(
        _validation_row(
            check_name="alpha_is_0p95_for_all_runs",
            status="pass" if daily_metrics["cvar_alpha"].astype(float).eq(float(cvar_alpha)).all() else "fail",
            details=f"unique_alpha={sorted(daily_metrics['cvar_alpha'].astype(float).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="gamma_grid_exact_match",
            status="pass" if sorted(daily_metrics["cvar_gamma"].astype(float).unique().tolist()) == sorted([float(v) for v in gamma_values]) else "fail",
            details=f"observed_gamma_values={sorted(daily_metrics['cvar_gamma'].astype(float).unique().tolist())}",
        )
    )
    gamma_zero = daily_metrics.loc[daily_metrics["cvar_gamma"].astype(float).abs() <= 1e-12]
    rows.append(
        _validation_row(
            check_name="gamma_zero_is_risk_neutral",
            status="pass" if not gamma_zero.empty and gamma_zero["risk_mode"].astype(str).eq("risk_neutral").all() else "fail",
            details=f"gamma_zero_risk_modes={sorted(gamma_zero['risk_mode'].astype(str).unique().tolist()) if not gamma_zero.empty else []}",
        )
    )
    rows.append(
        _validation_row(
            check_name="var_and_cvar_finite",
            status="pass" if np.isfinite(daily_metrics["var_loss"].astype(float)).all() and np.isfinite(daily_metrics["cvar_loss"].astype(float)).all() else "fail",
            details="finite(var_loss) and finite(cvar_loss) for all daily runs",
        )
    )
    rows.append(
        _validation_row(
            check_name="excess_loss_variables_nonnegative",
            status="pass" if (scenario_settlement_results["xi_loss_excess_eur"].astype(float) >= -1e-9).all() else "fail",
            details=f"min_xi={float(scenario_settlement_results['xi_loss_excess_eur'].astype(float).min()):.9f}",
        )
    )
    rows.append(
        _validation_row(
            check_name="cvar_loss_ge_var_loss",
            status="pass" if (daily_metrics["cvar_loss"].astype(float) + 1e-8 >= daily_metrics["var_loss"].astype(float)).all() else "fail",
            details="CVaR loss is at least VaR loss within tolerance",
        )
    )
    max_recon_error = float(daily_metrics["cvar_reconstruction_error"].astype(float).max())
    rows.append(
        _validation_row(
            check_name="reconstructed_cvar_matches_reported",
            status="pass" if max_recon_error <= 1e-6 else "fail",
            details=f"max_cvar_reconstruction_error={max_recon_error:.9f}",
        )
    )
    prob_sums = (
        scenario_settlement_results.groupby(["artifact_id", "delivery_day", "cvar_gamma"], as_index=False)["scenario_probability"]
        .sum()
    )
    max_prob_error = float(prob_sums["scenario_probability"].astype(float).sub(1.0).abs().max()) if not prob_sums.empty else float("nan")
    rows.append(
        _validation_row(
            check_name="scenario_probabilities_sum_to_one_per_origin",
            status="pass" if not prob_sums.empty and max_prob_error <= 1e-6 else "fail",
            details=f"max_probability_sum_error={max_prob_error:.9f}",
        )
    )
    rows.append(
        _validation_row(
            check_name="worst_scenario_loss_ge_var_loss",
            status="pass" if (daily_metrics["worst_scenario_loss"].astype(float) + 1e-8 >= daily_metrics["var_loss"].astype(float)).all() else "fail",
            details="worst_scenario_loss >= var_loss within tolerance",
        )
    )
    changed_models: list[str] = []
    no_effect_models: list[str] = []
    for model_label, group in weekly_metrics.groupby("model_label", sort=False):
        if group["cvar_gamma"].nunique() <= 1:
            no_effect_models.append(str(model_label))
            continue
        effect = (
            group["cvar_loss"].astype(float).max() - group["cvar_loss"].astype(float).min() > 1e-6
            or group["weighted_average_bid_price"].astype(float).max() - group["weighted_average_bid_price"].astype(float).min() > 1e-6
            or group["expected_adjusted_profit"].astype(float).max() - group["expected_adjusted_profit"].astype(float).min() > 1e-6
        )
        if effect:
            changed_models.append(str(model_label))
        else:
            no_effect_models.append(str(model_label))
    rows.append(
        _validation_row(
            check_name="increasing_gamma_changes_objective_components_or_is_explicitly_flat",
            status="pass",
            severity="informational",
            details=f"changed_models={changed_models}; no_effect_models={no_effect_models}",
        )
    )
    return pd.DataFrame(rows)


def _build_general_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_week: pd.Series,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    daily_metrics: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    day_run_dirs: pd.DataFrame,
) -> pd.DataFrame:
    checks = existing_checks.copy()
    week_id = str(selected_week["week_id"])
    week_label = str(selected_week["week_label"])
    rows: list[dict[str, str]] = []
    rows.append(_validation_row(check_name="selected_week_is_validation_tail_week_only", status="pass" if week_label == EXPECTED_VALIDATION_WEEK_LABEL else "fail", details=f"week_label={week_label}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="all_selected_days_inside_common_validation_support", status="pass" if support_days["period_type"].astype(str).eq("validation").all() and support_days["common_complete_support"].astype(bool).all() else "fail", details=f"selected_day_count={int(support_days.shape[0])}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="no_selected_test_days_used", status="pass" if ~support_days["period_type"].astype(str).eq("test").any() else "fail", details=f"period_types={sorted(support_days['period_type'].astype(str).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="complete_actual_prices_for_selected_days", status="pass" if support_days["complete_actual_prices"].astype(bool).all() else "fail", details="complete_actual_prices all true", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="artifacts_run_on_same_validation_week", status="pass" if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == sorted([str(v) for v in artifact_ids]) else "fail", details=f"artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="scenario_count_75_for_all_selected_days", status="pass" if daily_metrics["scenario_count"].astype(int).eq(75).all() else "fail", details=f"scenario_count_values={sorted(daily_metrics['scenario_count'].astype(int).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="scenario_probability_check_passes", status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail", details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="submitted_minus_cleared_equals_rejected", status="pass" if np.allclose(daily_metrics["submitted_energy_mwh"].astype(float) - daily_metrics["cleared_energy_mwh"].astype(float), daily_metrics["rejected_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily submitted - cleared = rejected", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared", status="pass" if np.allclose(daily_metrics["used_cleared_energy_mwh"].astype(float) + daily_metrics["unused_cleared_energy_mwh"].astype(float), daily_metrics["cleared_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily used + unused = cleared", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="benchmark_same_actual_prices_and_days", status="pass" if int(benchmark_daily.shape[0]) == 21 else "fail", details=f"benchmark_daily_rows={int(benchmark_daily.shape[0])}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="cvar_only_on_requested_validation_sweep", status="pass" if sorted(daily_metrics["period_type"].astype(str).unique().tolist()) == ["validation"] else "fail", details=f"period_types={sorted(daily_metrics['period_type'].astype(str).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="no_quarter_hour_data_used", status="pass" if actual_clearing["granularity"].astype(str).eq("hourly").all() and pd.to_numeric(actual_clearing["timestep_hours"], errors="coerce").fillna(0.0).eq(1.0).all() else "fail", details=f"granularities={sorted(actual_clearing['granularity'].astype(str).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="no_d_plus_4_data_used", status="pass" if actual_clearing["horizon"].astype(str).eq("D_only").all() else "fail", details=f"horizons={sorted(actual_clearing['horizon'].astype(str).unique().tolist())}", week_id=week_id, week_label=week_label))
    rows.append(_validation_row(check_name="solver_log_manifest_present", status="pass" if not day_run_dirs.empty else "fail", details=f"day_run_rows={int(day_run_dirs.shape[0])}", week_id=week_id, week_label=week_label))
    appended = pd.DataFrame(rows)
    return pd.concat([checks, appended], ignore_index=True)


def _plot_lines_by_model_gamma(frame: pd.DataFrame, *, y_columns: list[str], titles: list[str], output_path: Path) -> None:
    if frame.empty:
        return
    apply_visual_style()
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in frame["model_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(y_columns), 1, figsize=(10, max(4.0, 3.6 * len(y_columns))), sharex=True)
    if len(y_columns) == 1:
        axes = [axes]
    for ax, column, title in zip(axes, y_columns, titles, strict=True):
        for model_label in models:
            group = frame.loc[frame["model_label"].astype(str) == model_label].sort_values("cvar_gamma")
            ax.plot(group["cvar_gamma"], pd.to_numeric(group[column], errors="coerce"), marker="o", label=model_label, color=MODEL_COLORS.get(model_label, "#1F4E79"))
        ax.set_title(title)
        ax.set_ylabel(column)
        ax.legend(loc="best")
    axes[-1].set_xlabel("Gamma")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_risk_return_frontier(frame: pd.DataFrame, output_path: Path) -> None:
    if frame.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for model_label, group in frame.groupby("model_label", sort=False):
        group = group.sort_values("cvar_gamma")
        ax.plot(group["cvar_loss"], group["expected_adjusted_profit"], marker="o", label=model_label, color=MODEL_COLORS.get(str(model_label), "#1F4E79"))
        for _, row in group.iterrows():
            ax.annotate(f"g={row['cvar_gamma']:.2f}", (row["cvar_loss"], row["expected_adjusted_profit"]), fontsize=8)
    ax.set_xlabel("CVaR loss")
    ax.set_ylabel("Expected adjusted profit")
    ax.set_title("Validation-week risk-return frontier")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_scenario_distribution_by_gamma(scenario_results: pd.DataFrame, output_dir: Path) -> None:
    if scenario_results.empty:
        return
    apply_visual_style()
    for model_label, group in scenario_results.groupby("model_label", sort=False):
        gammas = sorted(group["cvar_gamma"].astype(float).unique().tolist())
        data = [group.loc[group["cvar_gamma"].astype(float).eq(gamma), "adjusted_profit_eur"].astype(float).to_numpy() for gamma in gammas]
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.boxplot(data, tick_labels=[str(g) for g in gammas])
        ax.set_title(f"Scenario profit distribution by gamma: {model_label}")
        ax.set_xlabel("Gamma")
        ax.set_ylabel("Scenario adjusted profit (EUR)")
        fig.tight_layout()
        fig.savefig(output_dir / f"scenario_profit_distribution_{str(model_label).lower().replace(' ', '_')}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _plot_scenario_fan_by_model(scenario_frame: pd.DataFrame, output_dir: Path) -> None:
    if scenario_frame.empty:
        return
    apply_visual_style()
    gamma_zero = scenario_frame.loc[scenario_frame["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = scenario_frame.copy()
    for model_label, group in gamma_zero.groupby("model_label", sort=False):
        rows: list[dict[str, Any]] = []
        for ts, hour_group in group.groupby("delivery_start_utc", sort=True):
            vals = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            probs = hour_group["scenario_probability"].astype(float).to_numpy()
            rows.append(
                {
                    "delivery_start_utc": pd.Timestamp(ts),
                    "q05": _weighted_quantile(vals, probs, 0.05),
                    "q50": _weighted_quantile(vals, probs, 0.50),
                    "q95": _weighted_quantile(vals, probs, 0.95),
                    "actual": float(hour_group["actual_price_eur_per_mwh"].iloc[0]),
                }
            )
        quant = pd.DataFrame(rows).sort_values("delivery_start_utc")
        fig, ax = plt.subplots(figsize=(12, 5))
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.fill_between(quant["delivery_start_utc"], quant["q05"], quant["q95"], alpha=0.22, color=color, label="p05-p95")
        ax.plot(quant["delivery_start_utc"], quant["q50"], color=color, linewidth=1.5, label="median")
        ax.plot(quant["delivery_start_utc"], quant["actual"], color="#222222", linewidth=1.8, label="actual")
        ax.set_title(f"Scenario fan vs realised price: {model_label}")
        ax.set_ylabel("EUR/MWh")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(output_dir / f"scenario_fan_{str(model_label).lower().replace(' ', '_')}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _plot_economic_decomposition(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    frame = weekly_metrics.copy().sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)
    labels = [f"{row['model_label']}\ng={row['cvar_gamma']}" for row in frame.to_dict(orient="records")]
    x = np.arange(frame.shape[0])
    components = [
        ("hydrogen_revenue", "#31a354", 1.0),
        ("da_settlement_cost", "#2b8cbe", -1.0),
        ("unused_energy_penalty", "#d95f0e", -1.0),
        ("shortfall_penalty", "#6a3d9a", -1.0),
        ("terminal_inventory_correction", "#636363", 1.0),
    ]
    fig, ax = plt.subplots(figsize=(12, 6))
    pos = np.zeros(frame.shape[0])
    neg = np.zeros(frame.shape[0])
    for column, color, sign in components:
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0).to_numpy() * sign
        positive = np.where(values >= 0.0, values, 0.0)
        negative = np.where(values < 0.0, values, 0.0)
        ax.bar(x, positive, bottom=pos, color=color, label=column)
        ax.bar(x, negative, bottom=neg, color=color)
        pos += positive
        neg += negative
    ax.scatter(x, pd.to_numeric(frame["realised_adjusted_profit"], errors="coerce"), color="#111111", label="realised_adjusted_profit", zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("EUR")
    ax.set_title("Economic decomposition by gamma")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_figures(
    *,
    run_dir: Path,
    cvar_frontier_by_model: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    scenario_frame: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _plot_risk_return_frontier(cvar_frontier_by_model, figures_dir / "01_risk_return_frontier_by_model.png")
    _plot_lines_by_model_gamma(
        weekly_metrics,
        y_columns=["cvar_loss"],
        titles=["Gamma vs CVaR loss"],
        output_path=figures_dir / "02_gamma_vs_cvar_loss.png",
    )
    _plot_lines_by_model_gamma(
        weekly_metrics,
        y_columns=["worst_scenario_profit", "realised_adjusted_profit"],
        titles=["Gamma vs worst-scenario profit", "Gamma vs realised adjusted profit"],
        output_path=figures_dir / "03_gamma_vs_profit_metrics.png",
    )
    _plot_lines_by_model_gamma(
        weekly_metrics,
        y_columns=["clearing_ratio", "rejected_energy_mwh"],
        titles=["Gamma vs clearing ratio", "Gamma vs rejected energy"],
        output_path=figures_dir / "04_gamma_vs_clearing_and_rejection.png",
    )
    _plot_lines_by_model_gamma(
        weekly_metrics,
        y_columns=["hydrogen_sold_or_compressed_kg", "shortfall_kg"],
        titles=["Gamma vs hydrogen sold/compressed", "Gamma vs shortfall"],
        output_path=figures_dir / "05_gamma_vs_hydrogen_and_shortfall.png",
    )
    _plot_lines_by_model_gamma(
        weekly_metrics,
        y_columns=["weighted_average_bid_price", "high_bid_share", "market_cap_bid_share"],
        titles=["Gamma vs weighted average bid price", "Gamma vs high-bid share", "Gamma vs market-cap share"],
        output_path=figures_dir / "06_gamma_vs_bid_firmness.png",
    )
    _plot_scenario_distribution_by_gamma(scenario_settlement_results, figures_dir)
    _plot_scenario_fan_by_model(scenario_frame, figures_dir)
    _plot_economic_decomposition(weekly_metrics, figures_dir / "07_economic_decomposition_by_gamma.png")


def _write_readme(
    *,
    run_dir: Path,
    selected_week: pd.Series,
    artifact_ids: list[str],
    cvar_alpha: float,
    gamma_values: list[float],
    weekly_metrics: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
    validation_checks: pd.DataFrame,
) -> None:
    summary = weekly_metrics[
        [
            "model_label",
            "cvar_gamma",
            "expected_adjusted_profit",
            "realised_adjusted_profit",
            "benchmark_profit",
            "stochastic_minus_benchmark_profit",
            "var_loss",
            "cvar_loss",
            "worst_scenario_profit",
            "clearing_ratio",
            "rejected_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "shortfall_kg",
            "weighted_average_bid_price",
        ]
    ].copy()
    hard_fail_count = int(validation_checks.loc[(validation_checks["severity"].astype(str) == "hard_fail") & (validation_checks["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    lines = [
        "# Phase D Validation-Week CVaR Smoke/Sweep",
        "",
        "## Scope",
        "",
        "- label: three-model hourly selected-week comparison on common partial support",
        "- period role: validation only",
        "- market scope: hourly, D-only, DA-only",
        "- selected week scope: exactly one selected validation week",
        "- no test weeks were used",
        "- no quarter-hour, D+4, mFRR, or exclusive group bids were added",
        "",
        "## Selected Validation Week",
        "",
        f"- week_label: `{selected_week['week_label']}`",
        f"- week_id: `{selected_week['week_id']}`",
        f"- delivery_start_date: `{selected_week['delivery_start_date']}`",
        f"- delivery_end_date: `{selected_week['delivery_end_date']}`",
        f"- selection_reason: {selected_week['selection_reason']}",
        "- rationale: strongest validation tail/peak regime for first downside-risk smoke/sweep.",
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
            "- gamma is not selected from test performance.",
            "",
            "## Method",
            "",
            "Pipeline: `scenario optimisation with CVaR -> submitted bids -> actual clearing -> deterministic redispatch -> pay-as-cleared settlement -> weekly aggregation`.",
            "",
            "Sign convention:",
            "- scenario loss is defined as `loss = - adjusted_profit`;",
            "- the objective is `expected_adjusted_profit - gamma * CVaR_loss`;",
            "- higher gamma is an insurance premium, not automatically a better result.",
            "",
            "## Weekly Results",
            "",
            "```csv",
            summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Validation Status",
            "",
            f"- hard validation failures: {hard_fail_count}",
            f"- CVaR reconstruction / consistency failures: {cvar_fail_count}",
            "",
            "## Interpretation Guardrails",
            "",
            "- this is validation-only CVaR diagnostics, not final test reporting;",
            "- test weeks remain reserved for later diagnostic reporting only;",
            "- any later frozen gamma policy must come from validation evidence, not the December 2024 test week;",
            "- weekly CVaR fields here are aggregated from day-level optimisation runs because each delivery day is solved independently.",
            "",
            "## Phase Status",
            "",
            f"- Phase D status: {'pass' if hard_fail_count == 0 and cvar_fail_count == 0 else 'fail'}",
            f"- safe to expand gamma grid: {'yes' if hard_fail_count == 0 and cvar_fail_count == 0 else 'not yet'}",
            f"- safe to add a second validation week: {'yes' if hard_fail_count == 0 and cvar_fail_count == 0 else 'not yet'}",
        ]
    )
    save_text(run_dir, "README_cvar_validation_sweep.md", "\n".join(lines))


def run_validation_week_cvar_smoke_sweep(
    *,
    config: HydrogenConfig | str | Path,
    week_id: str,
    artifact_ids: list[str] | tuple[str, ...] = DEFAULT_ARTIFACT_IDS,
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    include_price_insensitive_benchmark: bool = True,
    run_slug: str = "phase_d_validation_tail_cvar_smoke_three_model",
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
) -> PhaseDValidationSweepResult:
    gamma_list = [float(value) for value in gamma_values]
    if gamma_list != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase D smoke/sweep requires gamma grid exactly [0, 0.05, 0.25], got {gamma_list}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase D smoke/sweep requires alpha 0.95, got {cvar_alpha}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase D requires the price-insensitive benchmark to be included.")

    selected_week, support_days = _load_and_validate_phase_d_week(
        week_registry_path=Path(week_registry_path),
        support_csv_path=Path(support_csv_path),
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        week_id=week_id,
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
        requested_identifiers=[str(week_id)],
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        expected_split="validation",
        cache_root=run_dir / "cache",
        output_policy_name="minimal",
    )
    save_frame_csv(run_dir, "selected_week_input_preflight.csv", preflight.audit_rows)
    save_frame_csv(run_dir, "selected_week_input_runtime_profile.csv", preflight.runtime_profile)
    if not preflight.audit_rows.empty and not preflight.audit_rows["status"].astype(str).eq("pass").all():
        raise RuntimeError(
            "Phase D selected-week input preflight failed before optimisation; "
            f"see {run_dir / 'selected_week_input_preflight.csv'}."
        )

    selected_week_manifest = {
        "week_id": str(selected_week["week_id"]),
        "week_label": str(selected_week["week_label"]),
        "regime_label": str(selected_week["regime_label"]),
        "period_type": str(selected_week["period_type"]),
        "delivery_start_date": str(selected_week["delivery_start_date"]),
        "delivery_end_date": str(selected_week["delivery_end_date"]),
        "methodological_use": str(selected_week["methodological_use"]),
        "support_status": str(selected_week["support_status"]),
        "selected_delivery_days": support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist(),
    }
    save_json(run_dir, "selected_week_manifest.json", selected_week_manifest)
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

    day_output_root = run_dir / "day_runs"
    day_output_root.mkdir(parents=True, exist_ok=True)
    day_run_config = replace(suite_config, outputs=replace(suite_config.outputs, save_figures=False))

    daily_rows: list[dict[str, Any]] = []
    validation_rows: list[pd.DataFrame] = []
    submitted_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    benchmark_daily_rows: list[dict[str, Any]] = []
    scenario_fan_rows: list[pd.DataFrame] = []
    day_run_dir_rows: list[dict[str, Any]] = []
    scenario_manifest_rows: list[dict[str, Any]] = []
    benchmark_cache: dict[tuple[str, str], pd.Series] = {}

    for artifact_id in [str(value) for value in artifact_ids]:
        selected_daily, _, spec, catalog_entry, manifest = _valid_daily_registry_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
        )
        selected_daily["delivery_day_dt"] = pd.to_datetime(selected_daily["delivery_day"], errors="raise")
        day_window = selected_daily.loc[
            (selected_daily["delivery_day_dt"] >= pd.Timestamp(EXPECTED_VALIDATION_START))
            & (selected_daily["delivery_day_dt"] <= pd.Timestamp(EXPECTED_VALIDATION_END))
        ].copy()
        if int(day_window.shape[0]) != 7:
            raise ValueError(f"Artifact {artifact_id!r} produced {int(day_window.shape[0])} selected validation days; expected 7.")
        model_label = _label_for_artifact(artifact_id)
        validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
        thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
        reconstruction_used = bool(manifest.get("forecast_origin_reconstruction_used", manifest.get("forecast_origin_reconstructed", False)))

        for day_record in day_window.to_dict(orient="records"):
            benchmark_key = (artifact_id, str(day_record["delivery_day"]))
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
                    dry_run_label=f"validation_week_{selected_week['week_label']}_gamma_{_normalized_gamma_tag(gamma)}",
                    include_price_insensitive_comparison=include_benchmark,
                    risk_measure=risk_mode,
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    write_outputs=True,
                )
                benchmark_row = None
                if not result.benchmark_comparison.empty:
                    benchmark_row = result.benchmark_comparison.iloc[0].copy()
                    benchmark_cache[benchmark_key] = benchmark_row
                    benchmark_daily_rows.append(
                        _benchmark_daily_row(
                            benchmark_row=benchmark_row,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            delivery_day=str(result.delivery_day),
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                            run_id=run_id,
                        )
                    )
                elif benchmark_key in benchmark_cache:
                    benchmark_row = benchmark_cache[benchmark_key]

                daily_rows.append(
                    _build_daily_metric_row(
                        result=result,
                        artifact_id=artifact_id,
                        model_label=model_label,
                        validation_mode=validation_mode,
                        thesis_grade=thesis_grade,
                        forecast_origin_reconstruction_used=reconstruction_used,
                        week_row=selected_week,
                        day_row=pd.Series(day_record),
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        benchmark_row=benchmark_row,
                    )
                )
                validation_rows.append(
                    result.validation_checks.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(selected_week["week_id"]),
                        week_label=str(selected_week["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        risk_mode=str(risk_mode),
                    )
                )
                metadata = {
                    "artifact_id": artifact_id,
                    "model_label": model_label,
                    "week_id": str(selected_week["week_id"]),
                    "week_label": str(selected_week["week_label"]),
                    "delivery_day": str(result.delivery_day),
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
                day_run_dir_rows.append(
                    {
                        **metadata,
                        "run_dir": str(result.run_dir) if result.run_dir is not None else "",
                    }
                )
                day_scenario_manifest = json.loads((Path(str(result.run_dir)) / "scenario_manifest.json").read_text(encoding="utf-8")) if result.run_dir is not None else {}
                day_scenario_manifest.update(metadata)
                scenario_manifest_rows.append(day_scenario_manifest)

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase D produced no daily metrics.")
    daily_metrics["run_id"] = str(run_id)

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_checks_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["model_label", "delivery_day"]).reset_index(drop=True)
    scenario_frame = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    coverage = _scenario_coverage_by_day(scenario_frame)
    daily_metrics = daily_metrics.merge(
        coverage,
        on=["artifact_id", "model_label", "delivery_day", "cvar_gamma"],
        how="left",
    )
    benchmark_metrics = _aggregate_benchmark_metrics(benchmark_daily, selected_week=selected_week)
    weekly_metrics = _aggregate_weekly_metrics(daily_metrics, selected_week=selected_week).sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)
    weekly_metrics["value_captured_vs_perfect_foresight"] = pd.NA
    weekly_metrics_by_model_gamma = weekly_metrics.copy()
    model_stats_by_gamma = _build_model_stats_by_gamma(daily_metrics)
    cvar_sweep_daily = daily_metrics.copy()
    cvar_sweep_weekly = weekly_metrics.copy()
    cvar_frontier_by_model = _build_cvar_frontier_by_model(weekly_metrics)
    cvar_bid_firmness_metrics = _build_cvar_bid_firmness_metrics(weekly_metrics)
    solver_log_manifest = _build_solver_log_manifest(day_run_dirs)
    scenario_manifest = {
        "phase": "D",
        "support_label": "validation-period CVaR diagnostics on common partial support",
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
    validation_checks_all_runs = _build_general_validation_checks(
        existing_checks=validation_checks_existing,
        selected_week=selected_week,
        support_days=support_days,
        artifact_ids=[str(value) for value in artifact_ids],
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        day_run_dirs=day_run_dirs,
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
    save_frame_csv(run_dir, "cvar_sweep_daily.csv", cvar_sweep_daily)
    save_frame_csv(run_dir, "cvar_sweep_weekly.csv", cvar_sweep_weekly)
    save_frame_csv(run_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model)
    save_frame_csv(run_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "day_run_dirs.csv", day_run_dirs)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model)
    save_frame_csv(notebook_inputs_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    if not scenario_frame.empty:
        save_frame_parquet(notebook_inputs_dir, "scenario_fan_inputs.parquet", scenario_frame)
    if not submitted_bids.empty:
        save_frame_parquet(notebook_inputs_dir, "submitted_bids.parquet", submitted_bids)
    if not scenario_settlement_results.empty:
        save_frame_csv(notebook_inputs_dir, "scenario_settlement_results.csv", scenario_settlement_results)

    _create_figures(
        run_dir=run_dir,
        cvar_frontier_by_model=cvar_frontier_by_model,
        weekly_metrics=weekly_metrics,
        scenario_settlement_results=scenario_settlement_results,
        scenario_frame=scenario_frame,
    )
    _write_readme(
        run_dir=run_dir,
        selected_week=selected_week,
        artifact_ids=[str(value) for value in artifact_ids],
        cvar_alpha=float(cvar_alpha),
        gamma_values=gamma_list,
        weekly_metrics=weekly_metrics,
        cvar_validation_checks=cvar_validation_checks,
        validation_checks=validation_checks_all_runs,
    )

    hard_fail_count = int(validation_checks_all_runs.loc[(validation_checks_all_runs["severity"].astype(str) == "hard_fail") & (validation_checks_all_runs["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    if hard_fail_count > 0 or cvar_fail_count > 0:
        raise RuntimeError(
            f"Phase D completed but validation failed (hard_fail_count={hard_fail_count}, cvar_fail_count={cvar_fail_count}); see run folder {run_dir}."
        )

    return PhaseDValidationSweepResult(
        run_dir=run_dir,
        selected_week=selected_week,
        support_days=support_days,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        benchmark_metrics=benchmark_metrics,
        cvar_sweep_daily=cvar_sweep_daily,
        cvar_sweep_weekly=cvar_sweep_weekly,
        cvar_frontier_by_model=cvar_frontier_by_model,
        cvar_validation_checks=cvar_validation_checks,
        validation_checks=validation_checks_all_runs,
    )
