from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from .bidding_backtest import run_real_scenario_bidding_dry_run
from .optimisation.input_resolver import InputSliceRequest, resolve_input_slice
from .optimisation.output_policy import get_output_policy
from .optimisation.progress_reporting import ProgressReporter
from .optimisation.runtime_profiling import RuntimeProfiler
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs

try:
    from visual_style import MODEL_COLORS, STRATEGY_COLORS, apply_visual_style, save_figure
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR Strict": "#C97941",
        "LEAR FS3 pruned candidate": "#3A7D7C",
        "XGBoost FS3 pruned candidate": "#1F4E79",
        "Price insensitive benchmark": "#333333",
    }
    STRATEGY_COLORS = {
        "stochastic_risk_neutral": "#1F4E79",
        "price_insensitive": "#333333",
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

    def save_figure(fig: plt.Figure, output_stem: str | Path, *, save_pdf: bool = True) -> None:
        path = Path(output_stem).with_suffix("")
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight")
        if save_pdf:
            fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")


MODEL_ORDER = [
    "LEAR Strict",
    "LEAR FS3 pruned candidate",
    "XGBoost FS3 pruned candidate",
]

REGIME_ORDER = [
    "high_volatility_week",
    "stable_summer_week",
    "stable_winter_week",
    "low_price_week",
    "tail_week",
]


@dataclass(frozen=True)
class SelectedWeekSuiteResult:
    suite_dir: Path
    selected_week_registry: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    weekly_metrics_by_model: pd.DataFrame
    benchmark_comparison_daily: pd.DataFrame
    benchmark_comparison_weekly: pd.DataFrame
    validation_checks_all_runs: pd.DataFrame
    model_stats_daily: pd.DataFrame
    day_run_dirs: pd.DataFrame
    submitted_bids: pd.DataFrame
    scenario_clearing: pd.DataFrame
    actual_clearing: pd.DataFrame
    actual_clearing_by_hour: pd.DataFrame
    actual_redispatch_timeseries: pd.DataFrame
    scenario_settlement_results: pd.DataFrame
    actual_settlement_results: pd.DataFrame
    benchmark_comparison: pd.DataFrame
    scenario_fan_inputs: pd.DataFrame
    suite_runtime_profile: pd.DataFrame
    execution_audit: pd.DataFrame
    slice_audit: pd.DataFrame
    scenario_manifests: list[dict[str, Any]]
    input_manifests: list[dict[str, Any]]


def _artifact_label(artifact_id: str) -> str:
    mapping = {
        "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support": "LEAR Strict",
        "hourly_lear_strict": "LEAR Strict",
        "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate": "LEAR FS3 pruned candidate",
        "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate": "XGBoost FS3 pruned candidate",
    }
    return mapping.get(str(artifact_id), str(artifact_id))


def _catalog_entries(config: HydrogenConfig) -> dict[str, Any]:
    payload = yaml.safe_load(config.models.scenario_catalog.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid scenario catalog YAML: {config.models.scenario_catalog}")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("scenario_catalog.yaml is missing an artifacts mapping.")
    return artifacts


def _artifact_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path.parent / "scenario_export_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _safe_weighted_average(values: pd.Series, weights: pd.Series) -> float:
    value_array = pd.to_numeric(values, errors="coerce").astype(float).to_numpy()
    weight_array = pd.to_numeric(weights, errors="coerce").fillna(0.0).astype(float).to_numpy()
    mask = np.isfinite(value_array) & np.isfinite(weight_array) & (weight_array > 0.0)
    if not bool(mask.any()):
        return float("nan")
    return float(np.average(value_array[mask], weights=weight_array[mask]))


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


def _week_start_from_day(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, errors="raise")
    return timestamps - pd.to_timedelta(timestamps.dt.weekday, unit="D")


def _build_suite_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_ids: list[str] | tuple[str, ...],
    output_root: Path | None,
    experiment_name: str = "hydrogen_phase6d_selected_week_real_scenarios",
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    updated = replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(experiment_name),
            execution_mode="selected_weeks_real_scenario_suite",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=("stochastic_risk_neutral",),
    )
    if output_root is not None:
        updated = replace(updated, outputs=replace(updated.outputs, root=Path(output_root)))
    return updated


def _valid_daily_registry_for_artifact(
    *,
    config: HydrogenConfig,
    artifact_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, Any, dict[str, Any], dict[str, Any]]:
    artifact_config = replace(config, models=replace(config.models, include=(str(artifact_id),)))
    spec = resolve_artifact_specs(artifact_config)[0]
    catalog_entry = _catalog_entries(config)[artifact_id]
    manifest = _artifact_manifest(spec.path)
    scenarios, _ = load_scenarios_for_artifact(spec, config=artifact_config)
    scenarios = scenarios.copy()
    scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True, errors="raise")
    scenarios["delivery_start_utc"] = pd.to_datetime(scenarios["delivery_start_utc"], utc=True, errors="raise")
    scenarios["delivery_day"] = pd.to_datetime(scenarios["delivery_day"], errors="raise").dt.strftime("%Y-%m-%d")

    unique_prob = (
        scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
    )
    actual_rows = (
        scenarios[["forecast_origin_utc", "delivery_start_utc", "delivery_day", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["forecast_origin_utc", "delivery_start_utc"])
        .sort_values(["forecast_origin_utc", "delivery_start_utc"])
        .reset_index(drop=True)
    )
    actual_daily = (
        actual_rows.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_day=("delivery_day", "first"),
            actual_hour_count=("delivery_start_utc", "nunique"),
            missing_actual_rows=("actual_price_eur_per_mwh", lambda s: int(s.isna().sum())),
            actual_price_mean=("actual_price_eur_per_mwh", "mean"),
            actual_price_min=("actual_price_eur_per_mwh", "min"),
            actual_price_max=("actual_price_eur_per_mwh", "max"),
            actual_price_std=("actual_price_eur_per_mwh", "std"),
            actual_negative_price_hours=("actual_price_eur_per_mwh", lambda s: int((s.astype(float) < 0.0).sum())),
        )
    )
    duplicate_rows = (
        scenarios.duplicated(
            subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
            keep=False,
        )
        .groupby(scenarios["forecast_origin_utc"])
        .sum()
        .rename("duplicate_row_count")
        .reset_index()
    )
    registry = actual_daily.merge(unique_prob, on="forecast_origin_utc", how="inner").merge(
        duplicate_rows, on="forecast_origin_utc", how="left"
    )
    registry["duplicate_row_count"] = registry["duplicate_row_count"].fillna(0).astype(int)
    registry["actual_price_spread"] = registry["actual_price_max"].astype(float) - registry["actual_price_min"].astype(float)
    registry["actual_top_price"] = registry["actual_price_max"].astype(float)
    registry["actual_bottom_price"] = registry["actual_price_min"].astype(float)
    registry["artifact_id"] = str(artifact_id)
    registry["model_id"] = str(spec.model_id)
    registry["model_label"] = _artifact_label(artifact_id)
    registry["validation_mode"] = str(catalog_entry.get("validation_mode", spec.validation_mode))
    registry["thesis_grade"] = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", spec.validation_mode == "thesis_grade")))
    registry["forecast_origin_reconstruction_used"] = bool(
        manifest.get(
            "forecast_origin_reconstruction_used",
            manifest.get("forecast_origin_reconstructed", False),
        )
    )
    good_count_mask = (
        (registry["actual_hour_count"].astype(int) == 24)
        & (registry["missing_actual_rows"].astype(int) == 0)
        & (registry["duplicate_row_count"].astype(int) == 0)
        & (registry["probability_sum"].astype(float).between(0.999999, 1.000001))
    )
    count_candidates = registry.loc[good_count_mask, "scenario_count"].astype(int)
    if count_candidates.empty:
        raise ValueError(f"No valid daily origins found for artifact '{artifact_id}'.")
    expected_scenario_count = int(count_candidates.mode().iloc[0])
    registry["expected_scenario_count"] = expected_scenario_count
    valid = registry.loc[
        good_count_mask
        & (registry["scenario_count"].astype(int) == expected_scenario_count)
    ].copy()
    if valid.empty:
        raise ValueError(f"No complete daily origins remain for artifact '{artifact_id}' after scenario-count filtering.")

    selected_daily = (
        valid.sort_values(["delivery_day", "forecast_origin_utc"])
        .groupby("delivery_day", as_index=False)
        .tail(1)
        .sort_values("delivery_day")
        .reset_index(drop=True)
    )
    selected_actual = actual_rows.loc[
        actual_rows["forecast_origin_utc"].isin(selected_daily["forecast_origin_utc"])
    ].copy()
    selected_actual["artifact_id"] = str(artifact_id)
    selected_actual["model_label"] = _artifact_label(artifact_id)
    return selected_daily, selected_actual, spec, catalog_entry, manifest


def _select_week_row(
    candidates: pd.DataFrame,
    *,
    chosen_week_ids: set[str],
    sort_columns: list[str],
    ascending: list[bool],
    week_label: str,
    base_reason: str,
) -> dict[str, Any]:
    ranked = candidates.sort_values(sort_columns, ascending=ascending).reset_index(drop=True)
    skipped_duplicates = 0
    for row in ranked.to_dict(orient="records"):
        if str(row["week_id"]) in chosen_week_ids:
            skipped_duplicates += 1
            continue
        note = "complete_7d_common_support"
        if skipped_duplicates > 0:
            note += f"; selected_distinct_candidate_after_skipping_{skipped_duplicates}_higher-ranked_duplicate(s)"
        return {
            "week_id": str(row["week_id"]),
            "week_label": week_label,
            "selection_reason": base_reason,
            "delivery_start_date": str(row["delivery_start_date"]),
            "delivery_end_date": str(row["delivery_end_date"]),
            "number_of_delivery_days": int(row["number_of_delivery_days"]),
            "actual_price_mean": float(row["actual_price_mean"]),
            "actual_price_min": float(row["actual_price_min"]),
            "actual_price_max": float(row["actual_price_max"]),
            "actual_price_spread": float(row["actual_price_spread"]),
            "actual_price_std": float(row["actual_price_std"]),
            "actual_negative_price_hours": int(row["actual_negative_price_hours"]),
            "actual_top_price": float(row["actual_top_price"]),
            "actual_bottom_price": float(row["actual_bottom_price"]),
            "completeness_status": str(row["completeness_status"]),
            "notes": note,
        }
    raise ValueError(f"Unable to select a distinct week for {week_label}.")


def build_selected_week_registry(
    *,
    config: HydrogenConfig | str | Path,
    artifact_ids: list[str] | tuple[str, ...],
    week_count: int = 5,
    selection_method: str = "price_diagnostics",
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    if str(selection_method) != "price_diagnostics":
        raise ValueError(f"Unsupported selection_method={selection_method!r}.")
    if int(week_count) not in {4, 5}:
        raise ValueError("week_count must be 4 or 5 for the current selected-week diagnostic suite.")

    suite_config = _build_suite_config(config, artifact_ids=artifact_ids, output_root=None)
    registry_by_artifact: dict[str, pd.DataFrame] = {}
    actual_hourly_by_artifact: dict[str, pd.DataFrame] = {}
    for artifact_id in [str(value) for value in artifact_ids]:
        selected_daily, selected_actual, _, _, _ = _valid_daily_registry_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
        )
        registry_by_artifact[artifact_id] = selected_daily
        actual_hourly_by_artifact[artifact_id] = selected_actual

    common_days = sorted(
        set.intersection(
            *[set(frame["delivery_day"].astype(str).tolist()) for frame in registry_by_artifact.values()]
        )
    )
    if not common_days:
        raise ValueError("No common delivery days are available across the requested thesis-grade artifacts.")

    reference_artifact_id = str(list(artifact_ids)[0])
    reference_daily = registry_by_artifact[reference_artifact_id].copy()
    reference_daily = reference_daily.loc[reference_daily["delivery_day"].isin(common_days)].copy()
    reference_actual = actual_hourly_by_artifact[reference_artifact_id].copy()
    reference_actual = reference_actual.loc[reference_actual["delivery_day"].isin(common_days)].copy()

    reference_daily["delivery_date"] = pd.to_datetime(reference_daily["delivery_day"], errors="raise")
    reference_daily["week_start"] = _week_start_from_day(reference_daily["delivery_day"])
    reference_daily["iso_week"] = reference_daily["week_start"].dt.isocalendar().week.astype(int)
    reference_daily["iso_year"] = reference_daily["week_start"].dt.isocalendar().year.astype(int)
    reference_actual["delivery_date"] = pd.to_datetime(reference_actual["delivery_day"], errors="raise")
    reference_actual["week_start"] = _week_start_from_day(reference_actual["delivery_day"])

    weekly_rows: list[dict[str, Any]] = []
    for week_start, day_group in reference_daily.groupby("week_start", sort=True):
        actual_group = reference_actual.loc[reference_actual["week_start"] == week_start].copy()
        day_count = int(day_group["delivery_day"].nunique())
        hour_count = int(actual_group["delivery_start_utc"].nunique())
        completeness_status = "complete_7d_common_support" if day_count == 7 and hour_count == 168 else "incomplete"
        weekly_rows.append(
            {
                "week_id": f"{int(day_group['iso_year'].iloc[0])}-W{int(day_group['iso_week'].iloc[0]):02d}",
                "week_start": pd.Timestamp(week_start),
                "delivery_start_date": pd.Timestamp(day_group["delivery_date"].min()).strftime("%Y-%m-%d"),
                "delivery_end_date": pd.Timestamp(day_group["delivery_date"].max()).strftime("%Y-%m-%d"),
                "number_of_delivery_days": day_count,
                "actual_price_mean": float(actual_group["actual_price_eur_per_mwh"].mean()),
                "actual_price_min": float(actual_group["actual_price_eur_per_mwh"].min()),
                "actual_price_max": float(actual_group["actual_price_eur_per_mwh"].max()),
                "actual_price_spread": float(actual_group["actual_price_eur_per_mwh"].max() - actual_group["actual_price_eur_per_mwh"].min()),
                "actual_price_std": float(actual_group["actual_price_eur_per_mwh"].std(ddof=1)),
                "actual_negative_price_hours": int((actual_group["actual_price_eur_per_mwh"].astype(float) < 0.0).sum()),
                "actual_top_price": float(actual_group["actual_price_eur_per_mwh"].max()),
                "actual_bottom_price": float(actual_group["actual_price_eur_per_mwh"].min()),
                "completeness_status": completeness_status,
                "month": int(pd.Timestamp(week_start).month),
                "notes": "common_support_across_all_requested_artifacts",
            }
        )
    weekly_candidates = pd.DataFrame(weekly_rows)
    complete_weeks = weekly_candidates.loc[weekly_candidates["completeness_status"] == "complete_7d_common_support"].copy()
    if complete_weeks.empty:
        raise ValueError("No complete 7-day common-support weeks are available across all requested artifacts.")

    summer_candidates = complete_weeks.loc[complete_weeks["month"].isin([6, 7, 8])].copy()
    winter_candidates = complete_weeks.loc[complete_weeks["month"].isin([12, 1, 2])].copy()
    chosen_week_ids: set[str] = set()
    selections: list[dict[str, Any]] = []

    selections.append(
        _select_week_row(
            complete_weeks,
            chosen_week_ids=chosen_week_ids,
            sort_columns=["actual_price_std", "actual_price_spread", "actual_top_price", "week_start"],
            ascending=[False, False, False, True],
            week_label="high_volatility_week",
            base_reason="highest weekly actual-price standard deviation with complete common support",
        )
    )
    chosen_week_ids.add(str(selections[-1]["week_id"]))

    if summer_candidates.empty:
        raise ValueError("No complete summer-week candidates are available.")
    selections.append(
        _select_week_row(
            summer_candidates,
            chosen_week_ids=chosen_week_ids,
            sort_columns=["actual_price_std", "actual_price_spread", "actual_price_mean", "week_start"],
            ascending=[True, True, True, True],
            week_label="stable_summer_week",
            base_reason="summer week with low realised volatility and complete common support",
        )
    )
    chosen_week_ids.add(str(selections[-1]["week_id"]))

    if winter_candidates.empty:
        raise ValueError("No complete winter-week candidates are available.")
    selections.append(
        _select_week_row(
            winter_candidates,
            chosen_week_ids=chosen_week_ids,
            sort_columns=["actual_price_std", "actual_price_spread", "actual_price_mean", "week_start"],
            ascending=[True, True, True, True],
            week_label="stable_winter_week",
            base_reason="winter week with low realised volatility and complete common support",
        )
    )
    chosen_week_ids.add(str(selections[-1]["week_id"]))

    selections.append(
        _select_week_row(
            complete_weeks,
            chosen_week_ids=chosen_week_ids,
            sort_columns=["actual_price_mean", "actual_bottom_price", "week_start"],
            ascending=[True, True, True],
            week_label="low_price_week",
            base_reason="lowest weekly average realised DA price with complete common support",
        )
    )
    chosen_week_ids.add(str(selections[-1]["week_id"]))

    if int(week_count) == 5:
        selections.append(
            _select_week_row(
                complete_weeks,
                chosen_week_ids=chosen_week_ids,
                sort_columns=["actual_top_price", "actual_price_spread", "actual_price_std", "week_start"],
                ascending=[False, False, False, True],
                week_label="tail_week",
                base_reason="week with extreme realised peak price and wide spread under complete common support",
            )
        )
        chosen_week_ids.add(str(selections[-1]["week_id"]))
    else:
        selections[0]["notes"] = str(selections[0]["notes"]) + "; high_volatility_and_tail_week_merged_due_to_week_count_limit"

    selected_registry = pd.DataFrame(selections)
    selected_registry["week_label"] = pd.Categorical(selected_registry["week_label"], categories=REGIME_ORDER, ordered=True)
    selected_registry = selected_registry.sort_values(["week_label", "delivery_start_date"]).reset_index(drop=True)
    selected_registry["week_label"] = selected_registry["week_label"].astype(str)
    return selected_registry, registry_by_artifact


def _build_day_metric_row(
    *,
    result: Any,
    config: HydrogenConfig,
    artifact_id: str,
    model_label: str,
    validation_mode: str,
    thesis_grade: bool,
    forecast_origin_reconstruction_used: bool,
    week_row: pd.Series,
    day_row: pd.Series,
) -> dict[str, Any]:
    metrics = result.metrics_summary.iloc[0]
    actual_summary = result.actual_settlement_results.iloc[0]
    benchmark = result.benchmark_comparison.iloc[0] if not result.benchmark_comparison.empty else pd.Series(dtype=object)
    submitted = result.optimisation_result.submitted_bids.copy()
    actual_clearing = result.actual_clearing.copy()
    scenarios = result.scenarios.copy()
    scenario_objective = result.scenario_objective_summary.copy()
    scenario_probs = scenarios[["scenario_id", "scenario_probability"]].drop_duplicates(subset=["scenario_id"])
    scenario_count = int(scenario_probs["scenario_id"].nunique())
    probability_sum = float(scenario_probs["scenario_probability"].astype(float).sum())

    submitted_energy_total = float(submitted["bid_quantity_mw"].astype(float).sum())
    weighted_avg_bid_price = _safe_weighted_average(
        submitted["bid_price_eur_per_mwh"],
        submitted["bid_quantity_mw"],
    )
    bid_energy_ge_250 = float(submitted.loc[submitted["bid_price_eur_per_mwh"].astype(float) >= 250.0, "bid_quantity_mw"].astype(float).sum())
    bid_energy_at_market_cap = float(
        submitted.loc[
            np.isclose(
                submitted["bid_price_eur_per_mwh"].astype(float),
                float(config.bidding.price_insensitive_bid_price_eur_per_mwh),
            ),
            "bid_quantity_mw",
        ]
        .astype(float)
        .sum()
    )
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy()
    accepted["bid_headroom"] = accepted["bid_price_eur_per_mwh"].astype(float) - accepted["actual_price_eur_per_mwh"].astype(float)
    accepted_energy = float(accepted["cleared_energy_mwh"].astype(float).sum()) if not accepted.empty else 0.0
    accepted_headroom_numerator = float(
        (accepted["bid_headroom"].astype(float) * accepted["cleared_energy_mwh"].astype(float)).sum()
    ) if not accepted.empty else 0.0

    hourly_band = (
        scenarios.groupby("delivery_start_utc", as_index=False)
        .agg(
            actual_price_eur_per_mwh=("actual_price_eur_per_mwh", "first"),
            scenario_band_min=("scenario_price_eur_per_mwh", "min"),
            scenario_band_max=("scenario_price_eur_per_mwh", "max"),
        )
    )
    outside_band_count = int(
        (
            (hourly_band["actual_price_eur_per_mwh"].astype(float) < hourly_band["scenario_band_min"].astype(float) - 1e-9)
            | (hourly_band["actual_price_eur_per_mwh"].astype(float) > hourly_band["scenario_band_max"].astype(float) + 1e-9)
        ).sum()
    )
    realised_profit = float(metrics["realised_adjusted_profit_eur"])
    expected_profit = float(metrics["expected_adjusted_profit_eur"])
    realised_profit_percentile = _weighted_percentile_leq(
        scenario_objective["adjusted_profit_eur"],
        scenario_objective["scenario_probability"],
        realised_profit,
    )

    validation_fail_count = int((result.validation_checks["status"].astype(str) == "fail").sum())
    validation_warn_count = int((result.validation_checks["status"].astype(str) == "warn").sum())

    benchmark_profit = float(benchmark.get("realised_adjusted_profit_eur", np.nan))
    benchmark_cleared = float(benchmark.get("cleared_energy_mwh", np.nan))
    benchmark_hydrogen = float(benchmark.get("hydrogen_compressed_or_sold_kg", np.nan))
    benchmark_price_paid = float(benchmark.get("weighted_average_actual_price_paid_for_cleared_energy", np.nan))
    benchmark_shortfall = float(benchmark.get("shortfall_kg", np.nan))

    return {
        "artifact_id": artifact_id,
        "model_id": str(result.scenarios["model_id"].astype(str).iloc[0]),
        "model_label": model_label,
        "validation_mode": validation_mode,
        "thesis_grade": bool(thesis_grade),
        "forecast_origin_reconstruction_used": bool(forecast_origin_reconstruction_used),
        "week_id": str(week_row["week_id"]),
        "week_label": str(week_row["week_label"]),
        "selection_reason": str(week_row["selection_reason"]),
        "delivery_day": str(result.delivery_day),
        "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
        "day_run_dir": str(result.run_dir) if result.run_dir is not None else "",
        "actual_price_mean": float(day_row["actual_price_mean"]),
        "actual_price_min": float(day_row["actual_price_min"]),
        "actual_price_max": float(day_row["actual_price_max"]),
        "actual_price_spread": float(day_row["actual_price_spread"]),
        "actual_price_std": float(day_row["actual_price_std"]),
        "actual_negative_price_hours": int(day_row["actual_negative_price_hours"]),
        "actual_top_price": float(day_row["actual_top_price"]),
        "actual_bottom_price": float(day_row["actual_bottom_price"]),
        "probability_sum_per_origin": probability_sum,
        "scenario_count": scenario_count,
        "expected_adjusted_profit": expected_profit,
        "realised_adjusted_profit": realised_profit,
        "price_insensitive_realised_adjusted_profit": benchmark_profit,
        "stochastic_minus_benchmark_profit": realised_profit - benchmark_profit if pd.notna(benchmark_profit) else float("nan"),
        "DA_settlement_cost": float(actual_summary["realised_DA_settlement_cost_eur"]),
        "hydrogen_revenue": float(actual_summary["hydrogen_revenue_eur"]),
        "unused_energy_penalty_eur": float(actual_summary["unused_energy_penalty_eur"]),
        "shortfall_penalty_eur": float(actual_summary["shortfall_penalty_eur"]),
        "terminal_inventory_correction_eur": float(actual_summary["terminal_inventory_correction_eur"]),
        "weighted_average_actual_price_paid": float(metrics["weighted_average_actual_price_paid_for_cleared_energy"]),
        "value_vs_price_insensitive": realised_profit - benchmark_profit if pd.notna(benchmark_profit) else float("nan"),
        "submitted_energy_mwh": float(metrics["submitted_energy_mwh"]),
        "cleared_energy_mwh": float(metrics["cleared_energy_mwh"]),
        "rejected_energy_mwh": float(metrics["rejected_energy_mwh"]),
        "clearing_ratio": float(metrics["clearing_ratio"]),
        "zero_clearing_hours": int(metrics["zero_clearing_hours"]),
        "partial_clearing_hours": int(metrics["partial_clearing_hours"]),
        "weighted_average_bid_price": weighted_avg_bid_price,
        "bid_energy_ge_250_mwh": bid_energy_ge_250,
        "share_bid_energy_ge_250": float(bid_energy_ge_250 / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "bid_energy_at_market_cap_mwh": bid_energy_at_market_cap,
        "share_bid_energy_at_market_cap": float(bid_energy_at_market_cap / submitted_energy_total) if submitted_energy_total > 0.0 else 0.0,
        "accepted_bid_energy_mwh": accepted_energy,
        "accepted_bid_headroom_weighted_numerator": accepted_headroom_numerator,
        "bid_price_minus_actual_price_for_accepted_blocks_weighted": float(accepted_headroom_numerator / accepted_energy) if accepted_energy > 0.0 else float("nan"),
        "used_energy_mwh": float(actual_summary["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(actual_summary["unused_cleared_energy_mwh"]),
        "hydrogen_produced_kg": float(actual_summary["hydrogen_produced_kg"]),
        "hydrogen_compressed_or_sold_kg": float(actual_summary["hydrogen_compressed_or_sold_kg"]),
        "hydrogen_above_target_kg": float(actual_summary["hydrogen_above_target_kg"]),
        "target_fulfilment_ratio_capped_for_reliability": float(actual_summary["target_fulfilment_ratio_capped_for_reliability"]),
        "production_to_target_ratio_uncapped": float(actual_summary["production_to_target_ratio_uncapped"]),
        "shortfall_kg": float(actual_summary["shortfall_kg"]),
        "storage_min_kg": float(actual_summary["storage_min_kg"]),
        "storage_max_kg": float(actual_summary["storage_max_kg"]),
        "reserve_boundary_hits": int(actual_summary["reserve_boundary_hits"]),
        "terminal_inventory_change_kg": float(actual_summary["terminal_inventory_change_kg"]),
        "worst_scenario_profit": float(metrics["worst_scenario_profit_eur"]),
        "expected_vs_realised_profit_delta": realised_profit - expected_profit,
        "realised_profit_percentile_within_scenarios": realised_profit_percentile,
        "actual_price_outside_scenario_band_count": outside_band_count,
        "scenario_fan_coverage_share": float(1.0 - outside_band_count / max(len(hourly_band), 1)),
        "solver_status": str(metrics["solver_status"]),
        "objective_value": float(metrics["objective_with_regularisation"]),
        "solve_time_seconds": float(metrics["solve_time_seconds"]),
        "mip_gap": float(result.optimisation_result.solver.mip_gap) if result.optimisation_result.solver.mip_gap is not None else float("nan"),
        "variables": int(result.optimisation_result.model_stats.variable_count),
        "binaries": int(result.optimisation_result.model_stats.binary_variable_count),
        "constraints": int(result.optimisation_result.model_stats.constraint_count),
        "failed_run": int(validation_fail_count > 0 or str(metrics["solver_status"]) != "Optimal"),
        "validation_fail_count": validation_fail_count,
        "validation_warn_count": validation_warn_count,
        "benchmark_cleared_energy_mwh": benchmark_cleared,
        "benchmark_hydrogen_compressed_or_sold_kg": benchmark_hydrogen,
        "benchmark_weighted_average_actual_price_paid": benchmark_price_paid,
        "benchmark_shortfall_kg": benchmark_shortfall,
    }


def _aggregate_weekly_metrics(daily_metrics: pd.DataFrame, *, daily_target_kg: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = ["artifact_id", "model_id", "model_label", "validation_mode", "thesis_grade", "week_id", "week_label"]
    for keys, group in daily_metrics.groupby(group_columns, sort=False, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = {column: value for column, value in zip(group_columns, keys)}
        submitted = float(group["submitted_energy_mwh"].sum())
        cleared = float(group["cleared_energy_mwh"].sum())
        accepted_energy = float(group["accepted_bid_energy_mwh"].sum())
        total_target = float(group.shape[0] * daily_target_kg)
        stochastic_profit = float(group["realised_adjusted_profit"].sum())
        benchmark_profit = float(group["price_insensitive_realised_adjusted_profit"].sum())
        record.update(
            {
                "number_of_delivery_days": int(group["delivery_day"].nunique()),
                "expected_adjusted_profit": float(group["expected_adjusted_profit"].sum()),
                "realised_adjusted_profit": stochastic_profit,
                "price_insensitive_realised_adjusted_profit": benchmark_profit,
                "stochastic_minus_benchmark_profit": float(group["stochastic_minus_benchmark_profit"].sum()),
                "DA_settlement_cost": float(group["DA_settlement_cost"].sum()),
                "hydrogen_revenue": float(group["hydrogen_revenue"].sum()),
                "unused_energy_penalty_eur": float(group["unused_energy_penalty_eur"].sum()),
                "shortfall_penalty_eur": float(group["shortfall_penalty_eur"].sum()),
                "terminal_inventory_correction_eur": float(group["terminal_inventory_correction_eur"].sum()),
                "submitted_energy_mwh": submitted,
                "cleared_energy_mwh": cleared,
                "rejected_energy_mwh": float(group["rejected_energy_mwh"].sum()),
                "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
                "zero_clearing_hours": int(group["zero_clearing_hours"].sum()),
                "partial_clearing_hours": int(group["partial_clearing_hours"].sum()),
                "weighted_average_bid_price": _safe_weighted_average(
                    group["weighted_average_bid_price"],
                    group["submitted_energy_mwh"],
                ),
                "share_bid_energy_ge_250": float(group["bid_energy_ge_250_mwh"].sum() / submitted) if submitted > 0.0 else 0.0,
                "share_bid_energy_at_market_cap": float(group["bid_energy_at_market_cap_mwh"].sum() / submitted) if submitted > 0.0 else 0.0,
                "bid_price_minus_actual_price_for_accepted_blocks_weighted": float(
                    group["accepted_bid_headroom_weighted_numerator"].sum() / accepted_energy
                ) if accepted_energy > 0.0 else float("nan"),
                "used_energy_mwh": float(group["used_energy_mwh"].sum()),
                "unused_cleared_energy_mwh": float(group["unused_cleared_energy_mwh"].sum()),
                "hydrogen_produced_kg": float(group["hydrogen_produced_kg"].sum()),
                "hydrogen_compressed_or_sold_kg": float(group["hydrogen_compressed_or_sold_kg"].sum()),
                "hydrogen_above_target_kg": float(group["hydrogen_above_target_kg"].sum()),
                "target_fulfilment_ratio_capped_for_reliability": float(min(group["hydrogen_compressed_or_sold_kg"].sum(), total_target) / total_target) if total_target > 0.0 else float("nan"),
                "production_to_target_ratio_uncapped": float(group["hydrogen_compressed_or_sold_kg"].sum() / total_target) if total_target > 0.0 else float("nan"),
                "shortfall_kg": float(group["shortfall_kg"].sum()),
                "storage_min_kg": float(group["storage_min_kg"].min()),
                "storage_max_kg": float(group["storage_max_kg"].max()),
                "reserve_boundary_hits": int(group["reserve_boundary_hits"].sum()),
                "terminal_inventory_change_kg": float(group["terminal_inventory_change_kg"].sum()),
                "worst_scenario_profit": float(group["worst_scenario_profit"].sum()),
                "expected_vs_realised_profit_delta": float(group["expected_vs_realised_profit_delta"].sum()),
                "realised_profit_percentile_within_scenarios": float(group["realised_profit_percentile_within_scenarios"].mean()),
                "actual_price_outside_scenario_band_count": int(group["actual_price_outside_scenario_band_count"].sum()),
                "scenario_fan_coverage_share": float(1.0 - group["actual_price_outside_scenario_band_count"].sum() / max(group.shape[0] * 24, 1)),
                "weighted_average_actual_price_paid": float(group["DA_settlement_cost"].sum() / cleared) if cleared > 0.0 else float("nan"),
                "value_vs_price_insensitive": stochastic_profit - benchmark_profit,
                "solver_status": "all_optimal" if (group["solver_status"].astype(str) == "Optimal").all() else "mixed",
                "objective_value": float(group["objective_value"].sum()),
                "solve_time_seconds": float(group["solve_time_seconds"].sum()),
                "mip_gap": float(group["mip_gap"].max(skipna=True)) if not group["mip_gap"].dropna().empty else float("nan"),
                "variables": int(group["variables"].max()),
                "binaries": int(group["binaries"].max()),
                "constraints": int(group["constraints"].max()),
                "scenario_count": int(group["scenario_count"].mode().iloc[0]),
                "failed_runs": int(group["failed_run"].sum()),
                "validation_fail_count": int(group["validation_fail_count"].sum()),
                "validation_warn_count": int(group["validation_warn_count"].sum()),
                "actual_price_mean": float(group["actual_price_mean"].mean()),
                "actual_price_min": float(group["actual_price_min"].min()),
                "actual_price_max": float(group["actual_price_max"].max()),
                "actual_price_spread": float(group["actual_price_max"].max() - group["actual_price_min"].min()),
                "actual_price_std": float(group["actual_price_mean"].std(ddof=1)) if group.shape[0] > 1 else 0.0,
            }
        )
        rows.append(record)
    weekly = pd.DataFrame(rows)
    if weekly.empty:
        return weekly
    weekly["week_label"] = pd.Categorical(weekly["week_label"], categories=REGIME_ORDER, ordered=True)
    weekly = weekly.sort_values(["week_label", "model_label"]).reset_index(drop=True)
    weekly["week_label"] = weekly["week_label"].astype(str)
    return weekly


def _aggregate_by_model(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model_label, group in weekly_metrics.groupby("model_label", sort=False):
        rows.append(
            {
                "model_label": str(model_label),
                "artifact_id": str(group["artifact_id"].iloc[0]),
                "week_count": int(group.shape[0]),
                "mean_realised_adjusted_profit": float(group["realised_adjusted_profit"].mean()),
                "mean_price_insensitive_realised_adjusted_profit": float(group["price_insensitive_realised_adjusted_profit"].mean()),
                "mean_stochastic_minus_benchmark_profit": float(group["stochastic_minus_benchmark_profit"].mean()),
                "median_stochastic_minus_benchmark_profit": float(group["stochastic_minus_benchmark_profit"].median()),
                "mean_clearing_ratio": float(group["clearing_ratio"].mean()),
                "mean_rejected_energy_mwh": float(group["rejected_energy_mwh"].mean()),
                "mean_hydrogen_compressed_or_sold_kg": float(group["hydrogen_compressed_or_sold_kg"].mean()),
                "mean_shortfall_kg": float(group["shortfall_kg"].mean()),
                "mean_weighted_average_actual_price_paid": float(group["weighted_average_actual_price_paid"].mean()),
                "failed_runs": int(group["failed_runs"].sum()),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["model_order"] = frame["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    return frame.sort_values(["model_order", "model_label"]).drop(columns=["model_order"]).reset_index(drop=True)


def _plot_weekly_profit_vs_benchmark(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    ordered = weekly_metrics.copy()
    ordered["week_order"] = ordered["week_label"].map({label: idx for idx, label in enumerate(REGIME_ORDER)})
    ordered["model_order"] = ordered["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    ordered = ordered.sort_values(["week_order", "model_order"]).reset_index(drop=True)
    weeks = [label for label in REGIME_ORDER if label in ordered["week_label"].tolist()]
    x = np.arange(len(weeks))
    width = 0.22
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for idx, model_label in enumerate(MODEL_ORDER):
        subset = ordered.loc[ordered["model_label"] == model_label].set_index("week_label").reindex(weeks)
        if subset["realised_adjusted_profit"].isna().all():
            continue
        ax.bar(
            x + (idx - 1) * width,
            subset["realised_adjusted_profit"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
    benchmark = ordered.groupby("week_label", as_index=False)["price_insensitive_realised_adjusted_profit"].mean().set_index("week_label").reindex(weeks)
    ax.plot(
        x,
        benchmark["price_insensitive_realised_adjusted_profit"].to_numpy(),
        color=MODEL_COLORS.get("Price insensitive", STRATEGY_COLORS.get("price_insensitive", "#333333")),
        linewidth=2.0,
        marker="o",
        label="Price insensitive benchmark",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(weeks, rotation=15)
    ax.set_ylabel("Weekly realised adjusted profit (EUR)")
    ax.set_title("Weekly realised profit by model with benchmark reference")
    ax.legend(ncol=2)
    save_figure(fig, output_dir / "01_weekly_realised_profit_vs_benchmark")
    plt.close(fig)


def _plot_weekly_profit_delta_heatmap(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    pivot = (
        weekly_metrics.pivot_table(
            index="week_label",
            columns="model_label",
            values="stochastic_minus_benchmark_profit",
            aggfunc="first",
        )
        .reindex([label for label in REGIME_ORDER if label in weekly_metrics["week_label"].tolist()])
        .reindex(columns=MODEL_ORDER)
    )
    fig, ax = plt.subplots(figsize=(9, 4.8))
    values = pivot.to_numpy(dtype=float)
    image = ax.imshow(values, aspect="auto", cmap="RdYlGn")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(list(pivot.columns), rotation=20, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(list(pivot.index))
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            if np.isfinite(values[i, j]):
                ax.text(j, i, f"{values[i, j]:.0f}", ha="center", va="center", fontsize=8)
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Stochastic - benchmark profit (EUR)")
    ax.set_title("Cross-week stochastic uplift over price-insensitive benchmark")
    save_figure(fig, output_dir / "02_weekly_stochastic_minus_benchmark_heatmap")
    plt.close(fig)


def _plot_clearing_and_rejected_energy(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    ordered = weekly_metrics.copy()
    ordered["week_order"] = ordered["week_label"].map({label: idx for idx, label in enumerate(REGIME_ORDER)})
    ordered["model_order"] = ordered["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    ordered = ordered.sort_values(["week_order", "model_order"]).reset_index(drop=True)
    weeks = [label for label in REGIME_ORDER if label in ordered["week_label"].tolist()]
    x = np.arange(len(weeks))
    width = 0.22
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for idx, model_label in enumerate(MODEL_ORDER):
        subset = ordered.loc[ordered["model_label"] == model_label].set_index("week_label").reindex(weeks)
        if subset["clearing_ratio"].isna().all():
            continue
        axes[0].bar(
            x + (idx - 1) * width,
            subset["clearing_ratio"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
        axes[1].bar(
            x + (idx - 1) * width,
            subset["rejected_energy_mwh"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
    axes[0].set_ylabel("Clearing ratio")
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_title("Weekly clearing ratio by model")
    axes[0].legend(ncol=2)
    axes[1].set_ylabel("Rejected energy (MWh)")
    axes[1].set_title("Weekly rejected energy by model")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(weeks, rotation=15)
    save_figure(fig, output_dir / "03_weekly_clearing_and_rejected_energy")
    plt.close(fig)


def _plot_hydrogen_and_shortfall(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    ordered = weekly_metrics.copy()
    ordered["week_order"] = ordered["week_label"].map({label: idx for idx, label in enumerate(REGIME_ORDER)})
    ordered["model_order"] = ordered["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    ordered = ordered.sort_values(["week_order", "model_order"]).reset_index(drop=True)
    weeks = [label for label in REGIME_ORDER if label in ordered["week_label"].tolist()]
    x = np.arange(len(weeks))
    width = 0.22
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for idx, model_label in enumerate(MODEL_ORDER):
        subset = ordered.loc[ordered["model_label"] == model_label].set_index("week_label").reindex(weeks)
        if subset["hydrogen_compressed_or_sold_kg"].isna().all():
            continue
        axes[0].bar(
            x + (idx - 1) * width,
            subset["hydrogen_compressed_or_sold_kg"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
        axes[1].bar(
            x + (idx - 1) * width,
            subset["shortfall_kg"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
    axes[0].set_ylabel("Hydrogen compressed/sold (kg)")
    axes[0].set_title("Weekly hydrogen delivery by model")
    axes[0].legend(ncol=2)
    axes[1].set_ylabel("Shortfall (kg)")
    axes[1].set_title("Weekly shortfall by model")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(weeks, rotation=15)
    save_figure(fig, output_dir / "04_weekly_hydrogen_and_shortfall")
    plt.close(fig)


def _plot_average_price_paid(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    ordered = weekly_metrics.copy()
    ordered["week_order"] = ordered["week_label"].map({label: idx for idx, label in enumerate(REGIME_ORDER)})
    ordered["model_order"] = ordered["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    ordered = ordered.sort_values(["week_order", "model_order"]).reset_index(drop=True)
    weeks = [label for label in REGIME_ORDER if label in ordered["week_label"].tolist()]
    x = np.arange(len(weeks))
    width = 0.22
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for idx, model_label in enumerate(MODEL_ORDER):
        subset = ordered.loc[ordered["model_label"] == model_label].set_index("week_label").reindex(weeks)
        if subset["weighted_average_actual_price_paid"].isna().all():
            continue
        ax.bar(
            x + (idx - 1) * width,
            subset["weighted_average_actual_price_paid"].to_numpy(),
            width=width,
            color=MODEL_COLORS.get(model_label, "#7A7A7A"),
            label=model_label,
        )
    ax.set_xticks(x)
    ax.set_xticklabels(weeks, rotation=15)
    ax.set_ylabel("Average actual price paid (EUR/MWh)")
    ax.set_title("Weekly average actual price paid by model")
    ax.legend(ncol=2)
    save_figure(fig, output_dir / "05_weekly_average_actual_price_paid")
    plt.close(fig)


def _plot_spread_vs_profit_delta(weekly_metrics: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    for model_label, group in weekly_metrics.groupby("model_label", sort=False):
        ax.scatter(
            group["actual_price_spread"].astype(float),
            group["stochastic_minus_benchmark_profit"].astype(float),
            color=MODEL_COLORS.get(str(model_label), "#7A7A7A"),
            label=str(model_label),
            s=60,
        )
    ax.axhline(0.0, color="#333333", linewidth=1.0)
    ax.set_xlabel("Weekly actual price spread (EUR/MWh)")
    ax.set_ylabel("Stochastic - benchmark profit (EUR)")
    ax.set_title("Does wider realised price spread coincide with stochastic uplift?")
    ax.legend()
    save_figure(fig, output_dir / "06_price_spread_vs_profit_delta")
    plt.close(fig)


def _plot_weekly_scenario_fans(scenario_fan_inputs: pd.DataFrame, output_dir: Path) -> None:
    apply_visual_style()
    for week_label, week_frame in scenario_fan_inputs.groupby("week_label", sort=False):
        fig, axes = plt.subplots(len(MODEL_ORDER), 1, figsize=(12, 3.4 * len(MODEL_ORDER)), sharex=True)
        if len(MODEL_ORDER) == 1:
            axes = [axes]
        for ax, model_label in zip(axes, MODEL_ORDER, strict=True):
            model_frame = week_frame.loc[week_frame["model_label"] == model_label].copy()
            if model_frame.empty:
                ax.set_visible(False)
                continue
            quantiles = []
            for ts, group in model_frame.groupby("delivery_start_utc", sort=True):
                probs = group["scenario_probability"].astype(float).to_numpy()
                vals = group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
                order = np.argsort(vals)
                vals = vals[order]
                probs = probs[order]
                cumulative = np.cumsum(probs)

                def q(alpha: float) -> float:
                    idx = min(np.searchsorted(cumulative, alpha, side="left"), len(vals) - 1)
                    return float(vals[idx])

                quantiles.append(
                    {
                        "delivery_start_utc": pd.Timestamp(ts),
                        "q05": q(0.05),
                        "q50": q(0.50),
                        "q95": q(0.95),
                        "actual": float(group["actual_price_eur_per_mwh"].iloc[0]),
                    }
                )
            quantile_frame = pd.DataFrame(quantiles).sort_values("delivery_start_utc")
            color = MODEL_COLORS.get(model_label, "#7A7A7A")
            ax.fill_between(
                quantile_frame["delivery_start_utc"],
                quantile_frame["q05"],
                quantile_frame["q95"],
                alpha=0.22,
                color=color,
                label=f"{model_label} p05-p95",
            )
            ax.plot(
                quantile_frame["delivery_start_utc"],
                quantile_frame["q50"],
                color=color,
                linewidth=1.6,
                label=f"{model_label} p50",
            )
            ax.plot(
                quantile_frame["delivery_start_utc"],
                quantile_frame["actual"],
                color="#222222",
                linewidth=1.8,
                label="Actual price",
            )
            ax.set_ylabel("EUR/MWh")
            ax.set_title(f"{week_label}: {model_label}")
            ax.legend(loc="upper left")
        axes[-1].set_xlabel("Delivery hour")
        save_figure(fig, output_dir / f"scenario_fan_{week_label}")
        plt.close(fig)


def _write_selected_week_readme(
    *,
    suite_dir: Path,
    selected_week_registry: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    weekly_metrics_by_model: pd.DataFrame,
    artifact_ids: list[str],
) -> None:
    support_lines = [
        "# Selected-Week Real-Scenario Bidding Suite",
        "",
        "This suite runs hourly D-only DA-only stochastic bidding on selected diagnostic weeks.",
        "",
        "- strategy: `stochastic_bid_risk_neutral`",
        "- benchmark: `price_insensitive_plan_first_market_cap`",
        "- granularity: `hourly`",
        "- horizon: `D_ONLY`",
        "- scenario methodology: thesis-grade hourly scenario artifacts with explicit probabilities",
        "- support: common delivery weeks across all requested thesis-grade artifacts",
        "- caveat: selected-week diagnostics are not an unbiased full-period backtest",
        "",
        "## Artifacts",
        "",
    ]
    for artifact_id in artifact_ids:
        support_lines.append(f"- `{artifact_id}`")
    support_lines.extend(
        [
            "",
            "## Selected Week Registry",
            "",
            "```csv",
            selected_week_registry.to_csv(index=False).strip(),
            "```",
            "",
            "## Weekly Metrics",
            "",
            "```csv",
            weekly_metrics[
                [
                    "week_label",
                    "model_label",
                    "realised_adjusted_profit",
                    "price_insensitive_realised_adjusted_profit",
                    "stochastic_minus_benchmark_profit",
                    "clearing_ratio",
                    "rejected_energy_mwh",
                    "hydrogen_compressed_or_sold_kg",
                    "shortfall_kg",
                    "weighted_average_actual_price_paid",
                ]
            ].to_csv(index=False).strip(),
            "```",
            "",
            "## Model Summary",
            "",
            "```csv",
            weekly_metrics_by_model.to_csv(index=False).strip(),
            "```",
            "",
            "## Support Statements",
            "",
            "- all models are compared on the same selected delivery weeks;",
            "- actual prices are historical realised DA prices from the scenario artifacts;",
            "- expected stochastic objective and realised settlement remain distinct quantities;",
            "- no mFRR, quarter-hour, or CVaR sensitivity was included in this suite;",
            "- scenario quality limitations still apply and should be reported alongside economics.",
        ]
    )
    save_text(suite_dir, "README_selected_week_suite.md", "\n".join(support_lines))


def run_real_scenario_selected_week_suite(
    *,
    config: HydrogenConfig | str | Path,
    artifact_ids: list[str] | tuple[str, ...],
    week_registry: Path | None = None,
    selection_method: str = "price_diagnostics",
    week_count: int = 5,
    output_root: Path | None = None,
    strategy_name: str = "stochastic_bid_risk_neutral",
    include_price_insensitive_benchmark: bool = True,
    risk_measure: str = "risk_neutral",
    experiment_name: str = "hydrogen_phase6d_selected_week_real_scenarios",
    output_policy_name: str = "full",
    cache_root: Path | None = None,
    progress_reporting: bool = False,
    progress_metadata: dict[str, Any] | None = None,
    external_progress_reporter: ProgressReporter | None = None,
) -> SelectedWeekSuiteResult:
    if str(risk_measure) != "risk_neutral":
        raise ValueError("The selected-week real-scenario suite currently supports risk_neutral only.")
    output_policy = get_output_policy(output_policy_name)
    profiler = RuntimeProfiler()
    suite_config = _build_suite_config(
        config,
        artifact_ids=artifact_ids,
        output_root=output_root,
        experiment_name=experiment_name,
    )
    if week_registry is not None:
        selected_week_registry = pd.read_csv(week_registry)
        registry_by_artifact: dict[str, pd.DataFrame] = {}
    else:
        selected_week_registry, registry_by_artifact = build_selected_week_registry(
            config=suite_config,
            artifact_ids=artifact_ids,
            week_count=week_count,
            selection_method=selection_method,
        )

    suite_run_id, suite_dir = create_run_folder(suite_config)
    save_config_resolved(suite_dir, suite_config)
    save_inputs_manifest(suite_dir, [suite_config.config_path, suite_config.models.scenario_catalog])
    progress_reporter = (
        ProgressReporter(
            run_id=suite_run_id,
            run_folder=suite_dir,
            split=str((progress_metadata or {}).get("split", suite_config.experiment.dataset_split)),
            period_mode=str((progress_metadata or {}).get("period_mode", "selected_regimes")),
            total_solves=int(len([str(value) for value in artifact_ids]) * selected_week_registry.shape[0] * 7),
        )
        if progress_reporting
        else None
    )

    daily_rows: list[dict[str, Any]] = []
    benchmark_daily_rows: list[dict[str, Any]] = []
    validation_rows: list[pd.DataFrame] = []
    model_stats_rows: list[dict[str, Any]] = []
    day_run_dir_rows: list[dict[str, Any]] = []
    scenario_fan_rows: list[pd.DataFrame] = []
    redispatch_rows: list[pd.DataFrame] = []
    clearing_by_hour_rows: list[pd.DataFrame] = []
    submitted_bid_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    benchmark_comparison_rows: list[pd.DataFrame] = []
    suite_runtime_rows: list[pd.DataFrame] = []
    execution_audit_rows: list[pd.DataFrame] = []
    slice_audit_rows: list[dict[str, Any]] = []
    scenario_manifest_rows: list[dict[str, Any]] = []
    input_manifest_rows: list[dict[str, Any]] = []

    day_output_root = suite_dir / "day_runs"
    day_output_root.mkdir(parents=True, exist_ok=True)
    day_run_config = replace(
        suite_config,
        outputs=replace(
            suite_config.outputs,
            save_figures=bool(output_policy.save_figures),
            save_timeseries=bool(output_policy.save_timeseries),
            save_solver_log=False,
        ),
    )
    failure_day_config = replace(
        suite_config,
        outputs=replace(
            suite_config.outputs,
            save_figures=True,
            save_timeseries=True,
            save_solver_log=True,
        ),
    )

    catalog_map = _catalog_entries(suite_config)
    benchmark_cache_by_day: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    for artifact_id in [str(value) for value in artifact_ids]:
        model_label = _artifact_label(artifact_id)
        catalog_entry = catalog_map[artifact_id]
        spec = resolve_artifact_specs(replace(suite_config, models=replace(suite_config.models, include=(artifact_id,))))[0]
        manifest = _artifact_manifest(spec.path)
        validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
        thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
        forecast_origin_reconstruction_used = bool(
            manifest.get(
                "forecast_origin_reconstruction_used",
                manifest.get("forecast_origin_reconstructed", False),
            )
        )
        for week_row in selected_week_registry.to_dict(orient="records"):
            with profiler.track(
                "week_input_slice_resolve",
                artifact_id=str(artifact_id),
                week_label=str(week_row["week_label"]),
                cache_root="" if cache_root is None else str(cache_root),
                accounting_bucket="wall",
            ):
                resolved_slice = resolve_input_slice(
                    suite_config,
                    request=InputSliceRequest(
                        artifact_id=str(artifact_id),
                        start_local_date=str(week_row["delivery_start_date"]),
                        end_local_date=str(week_row["delivery_end_date"]),
                        period_mode="selected_weeks",
                        period_labels=(str(week_row["week_label"]),),
                        dataset_split=str(week_row.get("period_type", "")) or str(suite_config.experiment.dataset_split),
                    ),
                    output_policy_name=output_policy.name,
                    cache_root=cache_root,
                )
            actual_day_stats = (
                resolved_slice.market_actuals.groupby("delivery_day", as_index=False)
                .agg(
                    actual_price_mean=("actual_price_eur_per_mwh", "mean"),
                    actual_price_min=("actual_price_eur_per_mwh", "min"),
                    actual_price_max=("actual_price_eur_per_mwh", "max"),
                    actual_price_std=("actual_price_eur_per_mwh", "std"),
                    actual_negative_price_hours=("actual_price_eur_per_mwh", lambda s: int((pd.to_numeric(s, errors="coerce") < 0.0).sum())),
                )
            )
            actual_day_stats["actual_price_spread"] = actual_day_stats["actual_price_max"].astype(float) - actual_day_stats["actual_price_min"].astype(float)
            actual_day_stats["actual_top_price"] = actual_day_stats["actual_price_max"].astype(float)
            actual_day_stats["actual_bottom_price"] = actual_day_stats["actual_price_min"].astype(float)
            day_window = resolved_slice.origin_registry.merge(actual_day_stats, on="delivery_day", how="left").copy()
            if day_window.empty:
                raise ValueError(
                    f"Artifact '{artifact_id}' has no valid selected-day rows for week {week_row['week_label']} "
                    f"({week_row['delivery_start_date']}..{week_row['delivery_end_date']})."
                )
            slice_audit_rows.append(
                {
                    "artifact_id": str(artifact_id),
                    "model_label": str(model_label),
                    "week_id": str(week_row["week_id"]),
                    "week_label": str(week_row["week_label"]),
                    "cache_status": str(resolved_slice.cache_status),
                    "source_used": "input_resolver_cache" if str(resolved_slice.cache_status) == "hit" else "input_resolver_raw_then_cached",
                    "raw_artifact_read_again": bool(str(resolved_slice.cache_status) != "hit"),
                    "scenario_rows": int(resolved_slice.scenarios.shape[0]),
                    "delivery_day_count": int(day_window["delivery_day"].nunique()),
                    "cache_entry_dir": "" if resolved_slice.cache_entry_dir is None else str(resolved_slice.cache_entry_dir),
                    "slice_fingerprint": str(resolved_slice.slice_fingerprint),
                    "selected_period": json.dumps(resolved_slice.selected_period, default=str),
                }
            )
            for day_row in day_window.to_dict(orient="records"):
                delivery_day = str(day_row["delivery_day"])
                forecast_origin = pd.Timestamp(day_row["forecast_origin_utc"])
                with profiler.track(
                    "day_scenario_slice_resolve",
                    artifact_id=str(artifact_id),
                    model_label=str(model_label),
                    week_label=str(week_row["week_label"]),
                    delivery_day=delivery_day,
                    forecast_origin_utc=forecast_origin.isoformat(),
                    cache_status=str(resolved_slice.cache_status),
                    accounting_bucket="wall",
                ):
                    day_scenarios = resolved_slice.scenarios.loc[
                        pd.to_datetime(resolved_slice.scenarios["forecast_origin_utc"], utc=True, errors="raise").eq(forecast_origin)
                        & resolved_slice.scenarios["delivery_day"].astype(str).eq(delivery_day)
                    ].copy()
                with profiler.track(
                    "day_market_actual_slice_resolve",
                    artifact_id=str(artifact_id),
                    model_label=str(model_label),
                    week_label=str(week_row["week_label"]),
                    delivery_day=delivery_day,
                    accounting_bucket="wall",
                ):
                    day_actuals = resolved_slice.market_actuals.loc[
                        resolved_slice.market_actuals["delivery_day"].astype(str).eq(delivery_day)
                    ].copy()
                if day_scenarios.empty or day_actuals.empty:
                    raise ValueError(
                        f"Resolved input slice for artifact '{artifact_id}' is missing day data for {delivery_day}."
                    )
                benchmark_override = benchmark_cache_by_day.get(delivery_day)
                result = run_real_scenario_bidding_dry_run(
                    config=day_run_config,
                    artifact_id=artifact_id,
                    forecast_origin_utc=str(forecast_origin.isoformat()),
                    max_origins=1,
                    output_root=day_output_root,
                    strategy_name=strategy_name,
                    dry_run_label=f"selected_week_{week_row['week_label']}",
                    include_price_insensitive_comparison=bool(include_price_insensitive_benchmark),
                    selected_scenarios_override=day_scenarios,
                    actual_prices_override=day_actuals,
                    loader_findings_override=list(resolved_slice.findings),
                    benchmark_result_override=benchmark_override,
                    input_cache_status=str(resolved_slice.cache_status),
                    input_source_used="resolved_input_slice",
                    raw_artifact_read_again=False,
                    write_outputs=bool(output_policy.retain_nested_day_outputs),
                )
                if include_price_insensitive_benchmark and benchmark_override is None and not result.benchmark_comparison.empty:
                    benchmark_cache_by_day[delivery_day] = (
                        result.benchmark_comparison.copy(),
                        result.benchmark_clearing.copy(),
                        result.benchmark_timeseries.copy(),
                    )
                day_hard_fail_count = int(
                    result.validation_checks.loc[
                        result.validation_checks["severity"].astype(str).eq("hard_fail")
                        & result.validation_checks["status"].astype(str).eq("fail")
                    ].shape[0]
                )
                needs_failure_diagnostics = (
                    not bool(output_policy.retain_nested_day_outputs)
                    and (
                        str(result.optimisation_result.solver.status) != "Optimal"
                        or str(result.actual_redispatch_solver.status) != "Optimal"
                        or day_hard_fail_count > 0
                    )
                )
                if needs_failure_diagnostics:
                    result = run_real_scenario_bidding_dry_run(
                        config=failure_day_config,
                        artifact_id=artifact_id,
                        forecast_origin_utc=str(forecast_origin.isoformat()),
                        max_origins=1,
                        output_root=day_output_root,
                        strategy_name=strategy_name,
                        dry_run_label=f"selected_week_{week_row['week_label']}",
                        include_price_insensitive_comparison=bool(include_price_insensitive_benchmark),
                        selected_scenarios_override=day_scenarios,
                        actual_prices_override=day_actuals,
                        loader_findings_override=list(resolved_slice.findings),
                        benchmark_result_override=benchmark_cache_by_day.get(delivery_day),
                        input_cache_status=str(resolved_slice.cache_status),
                        input_source_used="resolved_input_slice",
                        raw_artifact_read_again=False,
                        write_outputs=True,
                    )
                daily_row = _build_day_metric_row(
                    result=result,
                    config=suite_config,
                    artifact_id=artifact_id,
                    model_label=model_label,
                    validation_mode=validation_mode,
                    thesis_grade=thesis_grade,
                    forecast_origin_reconstruction_used=forecast_origin_reconstruction_used,
                    week_row=pd.Series(week_row),
                    day_row=pd.Series(day_row),
                )
                daily_rows.append(daily_row)
                if not result.benchmark_comparison.empty:
                    benchmark_daily_rows.append(
                        {
                            "artifact_id": artifact_id,
                            "model_label": model_label,
                            "week_id": str(week_row["week_id"]),
                            "week_label": str(week_row["week_label"]),
                            "delivery_day": str(result.delivery_day),
                            "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
                            "stochastic_realised_adjusted_profit": float(daily_row["realised_adjusted_profit"]),
                            "price_insensitive_realised_adjusted_profit": float(daily_row["price_insensitive_realised_adjusted_profit"]),
                            "stochastic_minus_benchmark_profit": float(daily_row["stochastic_minus_benchmark_profit"]),
                            "stochastic_cleared_energy_mwh": float(daily_row["cleared_energy_mwh"]),
                            "benchmark_cleared_energy_mwh": float(daily_row["benchmark_cleared_energy_mwh"]),
                            "stochastic_hydrogen_compressed_or_sold_kg": float(daily_row["hydrogen_compressed_or_sold_kg"]),
                            "benchmark_hydrogen_compressed_or_sold_kg": float(daily_row["benchmark_hydrogen_compressed_or_sold_kg"]),
                            "stochastic_weighted_average_actual_price_paid": float(daily_row["weighted_average_actual_price_paid"]),
                            "benchmark_weighted_average_actual_price_paid": float(daily_row["benchmark_weighted_average_actual_price_paid"]),
                            "stochastic_shortfall_kg": float(daily_row["shortfall_kg"]),
                            "benchmark_shortfall_kg": float(daily_row["benchmark_shortfall_kg"]),
                        }
                    )
                validation = result.validation_checks.copy()
                validation["artifact_id"] = artifact_id
                validation["model_label"] = model_label
                validation["week_id"] = str(week_row["week_id"])
                validation["week_label"] = str(week_row["week_label"])
                validation["delivery_day"] = str(result.delivery_day)
                validation["forecast_origin_utc"] = pd.Timestamp(result.forecast_origin_utc)
                validation_rows.append(validation)
                suite_runtime_rows.append(
                    result.runtime_profile.assign(
                        artifact_id=str(artifact_id),
                        model_label=str(model_label),
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        delivery_day=str(result.delivery_day),
                    )
                )
                execution_audit_rows.append(
                    result.execution_audit.assign(
                        artifact_id=str(artifact_id),
                        model_label=str(model_label),
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                    )
                )
                scenario_manifest_rows.append(dict(result.scenario_manifest_payload))
                input_manifest_rows.append(dict(result.input_manifest_payload))
                model_stats_rows.append(
                    {
                        "artifact_id": artifact_id,
                        "model_label": model_label,
                        "week_id": str(week_row["week_id"]),
                        "week_label": str(week_row["week_label"]),
                        "delivery_day": str(result.delivery_day),
                        "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
                        "solver_status": str(result.optimisation_result.solver.status),
                        "objective_value": float(result.optimisation_result.solver.objective_value),
                        "solve_time_seconds": float(result.optimisation_result.solver.runtime_seconds),
                        "model_build_time_seconds": float(result.optimisation_result.solver.model_build_time_seconds)
                        if result.optimisation_result.solver.model_build_time_seconds is not None
                        else float("nan"),
                        "solver_time_seconds": float(result.optimisation_result.solver.solver_time_seconds)
                        if result.optimisation_result.solver.solver_time_seconds is not None
                        else float("nan"),
                        "postprocess_time_seconds": float(result.optimisation_result.solver.postprocess_time_seconds)
                        if result.optimisation_result.solver.postprocess_time_seconds is not None
                        else float("nan"),
                        "mip_gap": float(result.optimisation_result.solver.mip_gap) if result.optimisation_result.solver.mip_gap is not None else float("nan"),
                        "variables": int(result.optimisation_result.model_stats.variable_count),
                        "binaries": int(result.optimisation_result.model_stats.binary_variable_count),
                        "constraints": int(result.optimisation_result.model_stats.constraint_count),
                        "scenario_count": int(result.optimisation_result.model_stats.scenario_count),
                        "redispatch_solver_status": str(result.actual_settlement_results["solver_status"].iloc[0]),
                        "redispatch_solve_time_seconds": float(result.actual_settlement_results["solve_time_seconds"].iloc[0]),
                        "redispatch_model_build_time_seconds": float(result.actual_redispatch_solver.model_build_time_seconds)
                        if result.actual_redispatch_solver.model_build_time_seconds is not None
                        else float("nan"),
                        "redispatch_solver_time_seconds": float(result.actual_redispatch_solver.solver_time_seconds)
                        if result.actual_redispatch_solver.solver_time_seconds is not None
                        else float("nan"),
                        "redispatch_postprocess_time_seconds": float(result.actual_redispatch_solver.postprocess_time_seconds)
                        if result.actual_redispatch_solver.postprocess_time_seconds is not None
                        else float("nan"),
                    }
                )
                if progress_reporter is not None:
                    progress_reporter.record_solve(
                        regime=str(week_row["week_label"]),
                        model=str(model_label),
                        delivery_day=str(result.delivery_day),
                        gamma=float((progress_metadata or {}).get("gamma", 0.0)),
                        build_seconds=float(result.optimisation_result.solver.model_build_time_seconds or 0.0),
                        solver_seconds=float(result.optimisation_result.solver.solver_time_seconds or 0.0),
                        postprocess_seconds=float(result.optimisation_result.solver.postprocess_time_seconds or 0.0),
                        status=str(result.optimisation_result.solver.status),
                        mip_gap=result.optimisation_result.solver.mip_gap,
                        variables=int(result.optimisation_result.model_stats.variable_count),
                        binaries=int(result.optimisation_result.model_stats.binary_variable_count),
                        constraints=int(result.optimisation_result.model_stats.constraint_count),
                        warning="" if day_hard_fail_count == 0 else f"hard_validation_failures={day_hard_fail_count}",
                    )
                if external_progress_reporter is not None:
                    external_progress_reporter.record_solve(
                        regime=str(week_row["week_label"]),
                        model=str(model_label),
                        delivery_day=str(result.delivery_day),
                        gamma=float((progress_metadata or {}).get("gamma", 0.0)),
                        build_seconds=float(result.optimisation_result.solver.model_build_time_seconds or 0.0),
                        solver_seconds=float(result.optimisation_result.solver.solver_time_seconds or 0.0),
                        postprocess_seconds=float(result.optimisation_result.solver.postprocess_time_seconds or 0.0),
                        status=str(result.optimisation_result.solver.status),
                        mip_gap=result.optimisation_result.solver.mip_gap,
                        variables=int(result.optimisation_result.model_stats.variable_count),
                        binaries=int(result.optimisation_result.model_stats.binary_variable_count),
                        constraints=int(result.optimisation_result.model_stats.constraint_count),
                        warning="" if day_hard_fail_count == 0 else f"hard_validation_failures={day_hard_fail_count}",
                    )
                day_run_dir_rows.append(
                    {
                        "artifact_id": artifact_id,
                        "model_label": model_label,
                        "week_id": str(week_row["week_id"]),
                        "week_label": str(week_row["week_label"]),
                        "delivery_day": str(result.delivery_day),
                        "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
                        "run_dir": str(result.run_dir) if result.run_dir is not None else "",
                    }
                )
                scenario_clearing_rows.append(
                    result.optimisation_result.scenario_clearing.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                scenario_settlement_rows.append(
                    result.optimisation_result.scenario_economics.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                actual_clearing_rows.append(
                    result.actual_clearing.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                actual_settlement_rows.append(
                    result.actual_settlement_results.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                if not result.benchmark_comparison.empty:
                    benchmark_comparison_rows.append(
                        result.benchmark_comparison.assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(week_row["week_id"]),
                            week_label=str(week_row["week_label"]),
                            delivery_day=str(result.delivery_day),
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        )
                    )
                scenario_fan_rows.append(
                    result.scenarios.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                    )
                )
                redispatch_rows.append(
                    result.actual_redispatch_timeseries.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                clearing_by_hour_rows.append(
                    result.actual_clearing_by_hour.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )
                submitted_bid_rows.append(
                    result.optimisation_result.submitted_bids.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(week_row["week_id"]),
                        week_label=str(week_row["week_label"]),
                        delivery_day=str(result.delivery_day),
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    )
                )

    daily_metrics = pd.DataFrame(daily_rows)
    if daily_metrics.empty:
        raise RuntimeError("Selected-week suite produced no daily metrics.")
    daily_metrics["model_order"] = daily_metrics["model_label"].map({label: idx for idx, label in enumerate(MODEL_ORDER)})
    daily_metrics["week_order"] = daily_metrics["week_label"].map({label: idx for idx, label in enumerate(REGIME_ORDER)})
    daily_metrics = daily_metrics.sort_values(["week_order", "model_order", "delivery_day"]).drop(columns=["model_order", "week_order"]).reset_index(drop=True)

    weekly_metrics = _aggregate_weekly_metrics(daily_metrics, daily_target_kg=float(suite_config.economics.daily_target_kg))
    weekly_metrics_by_model = _aggregate_by_model(weekly_metrics)
    benchmark_comparison_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["week_label", "model_label", "delivery_day"]).reset_index(drop=True)
    benchmark_comparison_weekly = weekly_metrics[
        [
            "artifact_id",
            "model_label",
            "week_id",
            "week_label",
            "realised_adjusted_profit",
            "price_insensitive_realised_adjusted_profit",
            "stochastic_minus_benchmark_profit",
            "cleared_energy_mwh",
            "hydrogen_compressed_or_sold_kg",
            "weighted_average_actual_price_paid",
            "shortfall_kg",
        ]
    ].copy()
    validation_checks_all_runs = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    model_stats_daily = pd.DataFrame(model_stats_rows).sort_values(["week_label", "model_label", "delivery_day"]).reset_index(drop=True)
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["week_label", "model_label", "delivery_day"]).reset_index(drop=True)
    scenario_fan_inputs = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    actual_redispatch_inputs = pd.concat(redispatch_rows, ignore_index=True) if redispatch_rows else pd.DataFrame()
    actual_clearing_by_hour_inputs = pd.concat(clearing_by_hour_rows, ignore_index=True) if clearing_by_hour_rows else pd.DataFrame()
    submitted_bid_inputs = pd.concat(submitted_bid_rows, ignore_index=True) if submitted_bid_rows else pd.DataFrame()
    scenario_clearing_inputs = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_inputs = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_settlement_inputs = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    actual_clearing_inputs = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    benchmark_comparison_inputs = pd.concat(benchmark_comparison_rows, ignore_index=True) if benchmark_comparison_rows else pd.DataFrame()
    suite_runtime_profile = pd.concat(suite_runtime_rows, ignore_index=True) if suite_runtime_rows else pd.DataFrame()
    execution_audit = pd.concat(execution_audit_rows, ignore_index=True) if execution_audit_rows else pd.DataFrame()
    slice_audit = pd.DataFrame(slice_audit_rows)

    with profiler.track("suite_output_writing", output_policy_name=output_policy.name, accounting_bucket="wall"):
        save_frame_csv(suite_dir, "selected_week_registry.csv", selected_week_registry)
        save_frame_csv(suite_dir, "daily_metrics.csv", daily_metrics)
        save_frame_csv(suite_dir, "weekly_metrics.csv", weekly_metrics)
        save_frame_csv(suite_dir, "weekly_metrics_by_model.csv", weekly_metrics_by_model)
        save_frame_csv(suite_dir, "benchmark_comparison_daily.csv", benchmark_comparison_daily)
        save_frame_csv(suite_dir, "benchmark_comparison_weekly.csv", benchmark_comparison_weekly)
        save_frame_csv(suite_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
        save_frame_csv(suite_dir, "model_stats_daily.csv", model_stats_daily)
        save_frame_csv(suite_dir, "day_run_dirs.csv", day_run_dirs)
        save_frame_csv(suite_dir, "selected_week_execution_audit.csv", execution_audit)
        save_frame_csv(suite_dir, "selected_week_slice_audit.csv", slice_audit)
        save_frame_csv(suite_dir, "suite_runtime_profile.csv", suite_runtime_profile)

    notebook_inputs_dir = suite_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    if output_policy.save_timeseries:
        save_frame_csv(notebook_inputs_dir, "selected_week_registry.csv", selected_week_registry)
        save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
        save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
        save_frame_csv(notebook_inputs_dir, "weekly_metrics_by_model.csv", weekly_metrics_by_model)
        save_frame_csv(notebook_inputs_dir, "benchmark_comparison_daily.csv", benchmark_comparison_daily)
        save_frame_csv(notebook_inputs_dir, "benchmark_comparison_weekly.csv", benchmark_comparison_weekly)
        save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
        save_frame_csv(notebook_inputs_dir, "model_stats_daily.csv", model_stats_daily)
        if not scenario_fan_inputs.empty:
            save_frame_parquet(notebook_inputs_dir, "scenario_fan_inputs.parquet", scenario_fan_inputs)
        if not actual_redispatch_inputs.empty:
            save_frame_parquet(notebook_inputs_dir, "actual_redispatch_timeseries_daily.parquet", actual_redispatch_inputs)
        if not actual_clearing_by_hour_inputs.empty:
            save_frame_parquet(notebook_inputs_dir, "actual_clearing_by_hour_daily.parquet", actual_clearing_by_hour_inputs)
        if not submitted_bid_inputs.empty:
            save_frame_parquet(notebook_inputs_dir, "submitted_bids_daily.parquet", submitted_bid_inputs)

    figures_dir = suite_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    with profiler.track("suite_figure_generation", output_policy_name=output_policy.name, accounting_bucket="wall"):
        if output_policy.save_figures:
            _plot_weekly_profit_vs_benchmark(weekly_metrics, figures_dir)
            _plot_weekly_profit_delta_heatmap(weekly_metrics, figures_dir)
            _plot_clearing_and_rejected_energy(weekly_metrics, figures_dir)
            _plot_hydrogen_and_shortfall(weekly_metrics, figures_dir)
            _plot_average_price_paid(weekly_metrics, figures_dir)
            _plot_spread_vs_profit_delta(weekly_metrics, figures_dir)
            if not scenario_fan_inputs.empty:
                _plot_weekly_scenario_fans(scenario_fan_inputs, figures_dir)

    run_manifest = {
        "suite_run_id": suite_run_id,
        "suite_dir": str(suite_dir),
        "artifact_ids": [str(value) for value in artifact_ids],
        "strategy_name": str(strategy_name),
        "risk_measure": str(risk_measure),
        "include_price_insensitive_benchmark": bool(include_price_insensitive_benchmark),
        "selection_method": str(selection_method),
        "output_policy_name": str(output_policy.name),
        "selected_week_count": int(selected_week_registry.shape[0]),
        "selected_week_labels": selected_week_registry["week_label"].astype(str).tolist(),
        "day_run_count": int(day_run_dirs.shape[0]),
        "validation_checks_path": str(suite_dir / "validation_checks_all_runs.csv"),
        "notebook_inputs_dir": str(notebook_inputs_dir),
        "figures_dir": str(figures_dir),
        "execution_audit_path": str(suite_dir / "selected_week_execution_audit.csv"),
        "slice_audit_path": str(suite_dir / "selected_week_slice_audit.csv"),
        "suite_runtime_profile_path": str(suite_dir / "suite_runtime_profile.csv"),
    }
    save_json(suite_dir, "run_manifest.json", run_manifest)

    _write_selected_week_readme(
        suite_dir=suite_dir,
        selected_week_registry=selected_week_registry,
        weekly_metrics=weekly_metrics,
        weekly_metrics_by_model=weekly_metrics_by_model,
        artifact_ids=[str(value) for value in artifact_ids],
    )
    suite_runtime_container = profiler.to_frame()
    final_suite_runtime_profile = (
        pd.concat([suite_runtime_profile, suite_runtime_container], ignore_index=True, sort=False)
        if not suite_runtime_container.empty
        else suite_runtime_profile
    )
    save_frame_csv(suite_dir, "suite_runtime_profile.csv", final_suite_runtime_profile)

    return SelectedWeekSuiteResult(
        suite_dir=suite_dir,
        selected_week_registry=selected_week_registry,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        weekly_metrics_by_model=weekly_metrics_by_model,
        benchmark_comparison_daily=benchmark_comparison_daily,
        benchmark_comparison_weekly=benchmark_comparison_weekly,
        validation_checks_all_runs=validation_checks_all_runs,
        model_stats_daily=model_stats_daily,
        day_run_dirs=day_run_dirs,
        submitted_bids=submitted_bid_inputs,
        scenario_clearing=scenario_clearing_inputs,
        actual_clearing=actual_clearing_inputs,
        actual_clearing_by_hour=actual_clearing_by_hour_inputs,
        actual_redispatch_timeseries=actual_redispatch_inputs,
        scenario_settlement_results=scenario_settlement_inputs,
        actual_settlement_results=actual_settlement_inputs,
        benchmark_comparison=benchmark_comparison_inputs,
        scenario_fan_inputs=scenario_fan_inputs,
        suite_runtime_profile=final_suite_runtime_profile,
        execution_audit=execution_audit,
        slice_audit=slice_audit,
        scenario_manifests=scenario_manifest_rows,
        input_manifests=input_manifest_rows,
    )
