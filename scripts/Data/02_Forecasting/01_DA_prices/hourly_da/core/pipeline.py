from __future__ import annotations

import json

import pandas as pd

from ..models.base import ForecastModel
from .config import HourlyDAPipelineConfig
from .data_loading import audit_timezone_handling, build_canonical_hourly_frame, load_hourly_price_frame, summarize_gaps
from .evaluation import run_walk_forward_for_split
from .external_features import load_external_feature_store
from .methodology import methodology_snapshot
from .metrics import (
    add_error_columns,
    add_rmae_column,
    build_inherited_rmae_reference_snapshot,
    choose_official_naive_reference,
    pairwise_dm_results,
    pairwise_dm_results_by_reporting_level,
    rmae_policy_snapshot,
    summarize_metrics_by_lead_day,
    summarize_metrics_by_reporting_level,
    summarize_overall_metrics,
)
from .plotting import plot_lead_day_mae, plot_price_overview
from .progress import ProgressReporter
from .provenance import model_settings_summary_frame
from .schedule import build_split_summary, generate_forecast_origins
from .storage import create_run_directory, write_csv, write_json, write_parquet
from .tuning import benchmark_context_fs_level, effective_policy_summary, tuning_snapshot


def prepare_data_bundle(config: HourlyDAPipelineConfig, include_external_features: bool = False) -> dict[str, object]:
    source_frame = load_hourly_price_frame(config)
    canonical_frame = build_canonical_hourly_frame(source_frame, config)
    timezone_audit = audit_timezone_handling(config)
    gap_summary, gap_intervals = summarize_gaps(canonical_frame, config)
    split_summary = build_split_summary(config)
    return {
        "source_frame": source_frame,
        "canonical_frame": canonical_frame,
        "timezone_audit": timezone_audit,
        "gap_summary": gap_summary,
        "gap_intervals": gap_intervals,
        "split_summary": split_summary,
        "external_feature_store": load_external_feature_store(config) if include_external_features else None,
    }


def _summarize_timing(timing_df: pd.DataFrame) -> pd.DataFrame:
    if timing_df.empty:
        return pd.DataFrame()
    grouped = (
        timing_df.groupby(["dataset_split", "model", "model_family", "fs_level"], as_index=False)
        .agg(
            origins=("forecast_origin_utc", "size"),
            fit_time_mean_sec=("fit_time_sec", "mean"),
            fit_time_median_sec=("fit_time_sec", "median"),
            fit_time_max_sec=("fit_time_sec", "max"),
            fit_time_warning_count=("fit_time_warning", "sum"),
            predict_time_mean_sec=("predict_time_sec", "mean"),
            predict_time_median_sec=("predict_time_sec", "median"),
        )
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return grouped


def run_benchmark_suite(
    config: HourlyDAPipelineConfig,
    run_label: str,
    models: list[ForecastModel],
    include_external_features: bool = False,
    show_progress: bool = False,
    progress_label: str | None = None,
    origin_schedule_by_split: dict[str, pd.DataFrame] | None = None,
) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    prepared = prepare_data_bundle(config, include_external_features=include_external_features)
    run_id, run_dir = create_run_directory(config.output_root, run_label)

    origin_schedules = (
        {split_name: origin_schedule_by_split[split_name].copy() for split_name in config.evaluation_splits()}
        if origin_schedule_by_split is not None
        else {split_name: generate_forecast_origins(config, split_name) for split_name in config.evaluation_splits()}
    )
    progress_bar = None
    if show_progress:
        total_work_units = sum(int(schedule.shape[0]) * len(models) for schedule in origin_schedules.values())
        progress_bar = ProgressReporter(
            total=total_work_units,
            desc=progress_label or run_label,
        )

    predictions_by_split: list[pd.DataFrame] = []
    timing_by_split: list[pd.DataFrame] = []
    origins_by_split: list[pd.DataFrame] = []
    try:
        for split_name in config.evaluation_splits():
            split_predictions, split_timing, origin_schedule = run_walk_forward_for_split(
                canonical_frame=prepared["canonical_frame"],
                config=config,
                split_name=split_name,
                models=models,
                run_id=run_id,
                external_feature_store=prepared["external_feature_store"],
                origin_schedule=origin_schedules[split_name],
                progress_bar=progress_bar,
            )
            predictions_by_split.append(split_predictions)
            timing_by_split.append(split_timing)
            origins_by_split.append(origin_schedule)
    finally:
        if progress_bar is not None:
            progress_bar.close()

    predictions = pd.concat(predictions_by_split, ignore_index=True) if predictions_by_split else pd.DataFrame()
    timing = pd.concat(timing_by_split, ignore_index=True) if timing_by_split else pd.DataFrame()
    origins = pd.concat(origins_by_split, ignore_index=True) if origins_by_split else pd.DataFrame()

    requested_model_specs = [{"name": model.name, "family": model.family, "fs_level": model.fs_level} for model in models]
    model_settings_summary = model_settings_summary_frame(models)
    context_fs_level = benchmark_context_fs_level([str(model.fs_level) for model in models])
    requested_model_names = [spec["name"] for spec in requested_model_specs]
    prediction_models = set(predictions["model"].astype(str).unique().tolist()) if not predictions.empty else set()
    timing_models = set(timing["model"].astype(str).unique().tolist()) if not timing.empty else set()
    missing_prediction_models = sorted(model_name for model_name in requested_model_names if model_name not in prediction_models)
    missing_timing_models = sorted(model_name for model_name in requested_model_names if model_name not in timing_models)
    if missing_prediction_models or missing_timing_models:
        raise RuntimeError(
            "Benchmark run completed with missing requested models. "
            f"Missing from predictions: {missing_prediction_models or 'none'}. "
            f"Missing from timing: {missing_timing_models or 'none'}."
        )

    scored = add_error_columns(predictions)
    overall_metrics = summarize_overall_metrics(scored)
    lead_day_metrics = summarize_metrics_by_lead_day(scored)
    reporting_level_metrics = summarize_metrics_by_reporting_level(scored)
    official_naive = choose_official_naive_reference(
        reporting_level_metrics,
        reporting_level="stitched_all_horizon",
    )
    overall_metrics = add_rmae_column(overall_metrics, benchmark_model=str(official_naive["model"]))
    lead_day_metrics = add_rmae_column(
        lead_day_metrics,
        benchmark_model=str(official_naive["model"]),
        group_keys=["dataset_split", "lead_day", "lead_day_label"],
    )
    reporting_level_metrics = add_rmae_column(
        reporting_level_metrics,
        benchmark_model=str(official_naive["model"]),
        group_keys=["dataset_split", "reporting_level", "reporting_level_label", "reporting_level_sort_order"],
    )

    challenger_models = sorted(set(predictions["model"]) - {str(official_naive["model"])}) if not predictions.empty else []
    dm_results = pairwise_dm_results(
        predictions=scored,
        benchmark_model=str(official_naive["model"]),
        challenger_models=challenger_models,
    )
    dm_results_by_reporting_level = pairwise_dm_results_by_reporting_level(
        predictions=scored,
        benchmark_model=str(official_naive["model"]),
        challenger_models=challenger_models,
    )
    timing_summary = _summarize_timing(timing)

    write_json(run_dir / "config_snapshot.json", config.to_json_dict())
    write_json(run_dir / "methodology_snapshot.json", methodology_snapshot())
    write_json(run_dir / "tuning_policy_snapshot.json", tuning_snapshot())
    write_json(run_dir / "timezone_audit.json", prepared["timezone_audit"].to_dict())
    write_csv(run_dir / "gap_summary.csv", prepared["gap_summary"])
    write_csv(run_dir / "gap_intervals.csv", prepared["gap_intervals"])
    write_csv(run_dir / "split_summary.csv", prepared["split_summary"])
    write_csv(run_dir / "origin_schedule.csv", origins)
    write_parquet(run_dir / "predictions_long.parquet", predictions)
    write_csv(run_dir / "origin_timing.csv", timing)
    write_csv(run_dir / "origin_timing_summary.csv", timing_summary)
    write_csv(run_dir / "metrics_overall.csv", overall_metrics)
    write_csv(run_dir / "metrics_by_lead_day.csv", lead_day_metrics)
    write_csv(run_dir / "metrics_by_reporting_level.csv", reporting_level_metrics)
    write_csv(run_dir / "diebold_mariano_results.csv", dm_results)
    write_csv(run_dir / "diebold_mariano_by_reporting_level.csv", dm_results_by_reporting_level)
    write_csv(run_dir / "model_settings_summary.csv", model_settings_summary)
    write_json(run_dir / "official_naive_reference.json", official_naive)
    write_json(
        run_dir / "suite_models.json",
        {"models": requested_model_specs},
    )

    plot_price_overview(
        canonical_frame=prepared["canonical_frame"],
        split_summary=prepared["split_summary"],
        output_path=run_dir / "plots" / "price_overview_with_splits.png",
        target_col=config.target_col,
    )
    for split_name in config.evaluation_splits():
        plot_lead_day_mae(
            metrics_by_lead_day=lead_day_metrics,
            output_path=run_dir / "plots" / f"{split_name}_lead_day_mae.png",
            split_name=split_name,
        )

    summary_payload = {
        "run_id": run_id,
        "run_label": run_label,
        "context_fs_level": context_fs_level,
        "official_naive_reference": official_naive,
        "policy_snapshot": effective_policy_summary(context_fs_level, run_role="benchmark_parent"),
        "rmae_policy": rmae_policy_snapshot(),
        "parent_benchmark_rmae_reference": build_inherited_rmae_reference_snapshot(
            official_naive,
            source_run_id=run_id,
            source_run_label=run_label,
        ),
        "available_models": sorted(set(predictions["model"])) if not predictions.empty else [],
        "timing_models": json.loads(
            timing_summary[["model", "fit_time_mean_sec", "fit_time_median_sec", "fit_time_warning_count"]]
            .to_json(orient="records")
        )
        if not timing_summary.empty
        else [],
    }
    write_json(run_dir / "run_summary.json", summary_payload)

    return run_id, overall_metrics, lead_day_metrics, timing_summary, official_naive
