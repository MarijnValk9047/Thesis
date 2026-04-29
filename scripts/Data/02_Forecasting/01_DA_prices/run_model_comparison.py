from __future__ import annotations

import argparse
import json

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.methodology import methodology_snapshot
from hourly_da.core.metrics import (
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
from hourly_da.core.pipeline import prepare_data_bundle
from hourly_da.core.plotting import plot_lead_day_mae, plot_metric_bar, plot_price_overview
from hourly_da.core.progress import ProgressReporter
from hourly_da.core.provenance import model_settings_summary_from_source_runs
from hourly_da.core.reporting import find_latest_run, load_csv, source_run_record
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.storage import create_run_directory, write_csv, write_json, write_parquet
from hourly_da.core.tuning import effective_policy_summary, tuning_snapshot


FS_LAYER_CONFIGS = {
    "FS1": {
        "output_run_label": "fs1_model_comparison",
        "run_model_selection": {
            "naive_benchmark": ["naive_previous_week", "naive_previous_year"],
            "lear_fs1_benchmark": ["lear_fs1"],
            "xgboost_fs1_benchmark": ["xgboost_fs1"],
        },
        "model_order": [
            "naive_previous_week",
            "naive_previous_year",
            "lear_fs1",
            "xgboost_fs1",
        ],
    },
    "FS2": {
        "output_run_label": "model_comparison",
        "run_model_selection": {
            "naive_benchmark": ["naive_previous_week", "naive_previous_year"],
            "lear_fs2_benchmark": ["lear_fs2"],
            "xgboost_fs2_benchmark": ["xgboost_fs2"],
            "prophet_benchmark": ["prophet_fs2"],
        },
        "model_order": [
            "naive_previous_week",
            "naive_previous_year",
            "lear_fs2",
            "xgboost_fs2",
            "prophet_fs2",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate saved model runs into one FS-layer comparison run.")
    parser.add_argument("--fs-level", type=str, default="FS2", choices=sorted(FS_LAYER_CONFIGS.keys()))
    parser.add_argument("--run-label", type=str, default=None)
    parser.add_argument("--naive-run-label", type=str, default=None)
    parser.add_argument("--lear-run-label", type=str, default=None)
    parser.add_argument("--xgboost-run-label", type=str, default=None)
    parser.add_argument("--prophet-run-label", type=str, default=None)
    return parser.parse_args()


def _load_selected_rows(run_dir, filename: str, models: list[str], comparison_run_id: str) -> pd.DataFrame:
    frame = load_csv(run_dir, filename)
    available_models = set(frame["model"].astype(str).unique().tolist()) if "model" in frame.columns else set()
    missing_models = sorted(model_name for model_name in models if model_name not in available_models)
    if missing_models:
        raise RuntimeError(
            f"Run {run_dir} is missing expected models {missing_models} in {filename}. "
            "Refresh the upstream benchmark run before rebuilding model_comparison."
        )
    frame = frame[frame["model"].isin(models)].copy()
    if frame.empty:
        return frame
    frame = _normalize_aggregate_frame(frame)
    frame["source_run_id"] = frame["run_id"]
    frame["run_id"] = comparison_run_id
    return frame


def _normalize_local_date_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        local_dates = pd.to_datetime(series, errors="coerce")
        return local_dates.dt.strftime("%Y-%m-%d")
    if series.dtype == object:
        return series.map(lambda value: value.isoformat() if pd.notna(value) and hasattr(value, "isoformat") else value)
    return series.map(lambda value: None if pd.isna(value) else str(value))


def _normalize_utc_timestamp_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _normalize_aggregate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        column_name = str(column)
        if column_name.endswith("_utc"):
            normalized[column] = _normalize_utc_timestamp_series(normalized[column])
            continue
        if column_name.endswith("_local_date"):
            normalized[column] = _normalize_local_date_series(normalized[column])
    return normalized


def main() -> None:
    args = parse_args()
    layer_config = FS_LAYER_CONFIGS[args.fs_level]
    run_model_selection = dict(layer_config["run_model_selection"])
    override_map = {
        "naive_benchmark": args.naive_run_label,
        "lear_fs1_benchmark": args.lear_run_label if args.fs_level == "FS1" else None,
        "xgboost_fs1_benchmark": args.xgboost_run_label if args.fs_level == "FS1" else None,
        "lear_fs2_benchmark": args.lear_run_label if args.fs_level == "FS2" else None,
        "xgboost_fs2_benchmark": args.xgboost_run_label if args.fs_level == "FS2" else None,
        "prophet_benchmark": args.prophet_run_label if args.fs_level == "FS2" else None,
    }
    for source_run_label, override_label in override_map.items():
        if override_label and source_run_label in run_model_selection:
            run_model_selection[str(override_label)] = run_model_selection.pop(source_run_label)
    notebook_model_order = layer_config["model_order"]
    output_run_label = str(args.run_label or layer_config["output_run_label"])
    config = HourlyDAPipelineConfig()
    total_steps = len(run_model_selection) + 17
    progress = ProgressReporter(total=total_steps, desc=output_run_label)

    def advance(split_name: str | None = None, model_name: str | None = None) -> None:
        progress.step(increment=1, split_name=split_name, model_name=model_name)

    prepared = prepare_data_bundle(config)
    advance(model_name="prepare_data")
    run_id, run_dir = create_run_directory(config.output_root, output_run_label)

    source_runs: list[dict[str, object]] = []
    predictions_frames: list[pd.DataFrame] = []
    timing_frames: list[pd.DataFrame] = []
    for source_run_label, models in run_model_selection.items():
        try:
            run_path = find_latest_run(config.output_root, source_run_label)
        except FileNotFoundError:
            print(f"Skipping {source_run_label}: no completed upstream run was found.")
            continue
        source_runs.append(source_run_record(run_path))
        predictions_frames.append(_load_selected_rows(run_path, "predictions_long.csv", models, run_id))
        timing_frames.append(_load_selected_rows(run_path, "origin_timing.csv", models, run_id))
        advance(model_name=source_run_label)

    if not predictions_frames or not timing_frames:
        raise RuntimeError("No completed upstream benchmark runs were available for model_comparison.")

    predictions = pd.concat(predictions_frames, ignore_index=True)
    predictions["forecast_origin_utc"] = pd.to_datetime(predictions["forecast_origin_utc"], utc=True)
    predictions["target_timestamp_utc"] = pd.to_datetime(predictions["target_timestamp_utc"], utc=True)
    predictions = predictions.sort_values(["dataset_split", "model", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(
        drop=True
    )
    advance(model_name="combine_predictions")

    timing = pd.concat(timing_frames, ignore_index=True)
    timing["forecast_origin_utc"] = pd.to_datetime(timing["forecast_origin_utc"], utc=True)
    timing = timing.sort_values(["dataset_split", "model", "forecast_origin_utc"]).reset_index(drop=True)

    scored = add_error_columns(predictions)
    overall_metrics = summarize_overall_metrics(scored)
    reporting_level_metrics = summarize_metrics_by_reporting_level(scored)
    official_naive = choose_official_naive_reference(
        reporting_level_metrics,
        reporting_level="stitched_all_horizon",
    )
    overall_metrics = add_rmae_column(overall_metrics, benchmark_model=str(official_naive["model"]))
    lead_day_metrics = summarize_metrics_by_lead_day(scored)
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
    challenger_models = sorted(set(predictions["model"]) - {str(official_naive["model"])})
    dm_results = pairwise_dm_results(scored, benchmark_model=str(official_naive["model"]), challenger_models=challenger_models)
    dm_results_by_reporting_level = pairwise_dm_results_by_reporting_level(
        scored,
        benchmark_model=str(official_naive["model"]),
        challenger_models=challenger_models,
    )
    advance(model_name="metrics")

    available_model_catalog = (
        predictions[["model", "model_family", "fs_level"]]
        .drop_duplicates(subset=["model"])
        .reset_index(drop=True)
    )
    model_settings_summary = model_settings_summary_from_source_runs(
        source_runs,
        selected_models=set(available_model_catalog["model"].astype(str).tolist()),
    )
    available_model_names = set(available_model_catalog["model"].astype(str).tolist())
    ordered_suite_models: list[dict[str, object]] = []
    for model_name in notebook_model_order:
        if model_name not in available_model_names:
            continue
        record = available_model_catalog[available_model_catalog["model"].astype(str) == str(model_name)].head(1)
        if record.empty:
            continue
        ordered_suite_models.append(record.iloc[0].to_dict())
    advance(model_name="model_catalog")

    timing_summary = (
        timing.groupby(["dataset_split", "model", "model_family", "fs_level"], as_index=False)
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
    advance(model_name="timing_summary")

    write_json(run_dir / "config_snapshot.json", config.to_json_dict())
    write_json(run_dir / "methodology_snapshot.json", methodology_snapshot())
    write_json(run_dir / "tuning_policy_snapshot.json", tuning_snapshot())
    write_json(run_dir / "timezone_audit.json", prepared["timezone_audit"].to_dict())
    write_csv(run_dir / "gap_summary.csv", prepared["gap_summary"])
    write_csv(run_dir / "gap_intervals.csv", prepared["gap_intervals"])
    write_csv(run_dir / "split_summary.csv", prepared["split_summary"])
    advance(model_name="write_snapshots")
    write_parquet(run_dir / "predictions_long.parquet", predictions)
    write_csv(run_dir / "origin_timing.csv", timing)
    write_csv(run_dir / "origin_timing_summary.csv", timing_summary)
    advance(model_name="write_predictions")
    write_csv(run_dir / "metrics_overall.csv", overall_metrics)
    write_csv(run_dir / "metrics_by_lead_day.csv", lead_day_metrics)
    write_csv(run_dir / "metrics_by_reporting_level.csv", reporting_level_metrics)
    write_csv(run_dir / "diebold_mariano_results.csv", dm_results)
    write_csv(run_dir / "diebold_mariano_by_reporting_level.csv", dm_results_by_reporting_level)
    write_csv(run_dir / "model_settings_summary.csv", model_settings_summary)
    write_json(run_dir / "official_naive_reference.json", official_naive)
    advance(model_name="write_metrics")
    write_json(run_dir / "source_runs.json", {"source_runs": source_runs})
    write_json(
        run_dir / "suite_models.json",
        {"models": ordered_suite_models},
    )
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "comparison_fs_level": args.fs_level,
            "comparison_run_label": output_run_label,
            "official_naive_reference": official_naive,
            "policy_snapshot": effective_policy_summary(args.fs_level, run_role="aggregate_parent_comparison"),
            "rmae_policy": rmae_policy_snapshot(),
            "parent_benchmark_rmae_reference": build_inherited_rmae_reference_snapshot(
                official_naive,
                source_run_id=run_id,
                source_run_label=output_run_label,
            ),
            "source_run_ids": [record["run_id"] for record in source_runs],
            "source_run_labels": list(run_model_selection.keys()),
            "available_models": sorted(predictions["model"].unique().tolist()),
        },
    )
    advance(model_name="write_summary")

    plot_price_overview(
        canonical_frame=prepared["canonical_frame"],
        split_summary=prepared["split_summary"],
        output_path=run_dir / "plots" / "price_overview_with_splits.png",
        target_col=config.target_col,
    )
    advance(model_name="plot_price_overview")
    for split_name in config.evaluation_splits():
        plot_lead_day_mae(lead_day_metrics, run_dir / "plots" / f"{split_name}_lead_day_mae.png", split_name)
        advance(split_name=split_name, model_name="plot_lead_day_mae")
        plot_metric_bar(
            overall_metrics,
            run_dir / "plots" / f"{split_name}_overall_mae.png",
            split_name=split_name,
            metric_col="mae",
            title=f"Overall MAE by Model ({split_name.capitalize()})",
        )
        advance(split_name=split_name, model_name="plot_overall_mae")
        plot_metric_bar(
            overall_metrics,
            run_dir / "plots" / f"{split_name}_overall_rmae.png",
            split_name=split_name,
            metric_col="rmae_vs_official_naive",
            title=f"Relative MAE vs Naive Benchmark ({split_name.capitalize()})",
        )
        advance(split_name=split_name, model_name="plot_overall_rmae")

    print(f"Run completed: {run_id}")
    print(f"Comparison stage: {args.fs_level}")
    print(f"Selected naive benchmark on validation: {official_naive['model']} (MAE={official_naive['mae']:.4f})")
    print(overall_metrics[["model", "dataset_split", "coverage_pct", "mae", "rmae_vs_official_naive"]].to_string(index=False))
    print(
        reporting_level_metrics[
            ["model", "dataset_split", "reporting_level", "coverage_pct", "mae", "rmae_vs_official_naive"]
        ].to_string(index=False)
    )
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)
    advance(model_name="complete")
    progress.close()


if __name__ == "__main__":
    main()
