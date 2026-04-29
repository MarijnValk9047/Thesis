from __future__ import annotations

import argparse
import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.pipeline import prepare_data_bundle
from hourly_da.core.plotting import plot_week_actual_only, plot_week_actual_vs_models
from hourly_da.core.progress import ProgressReporter
from hourly_da.core.reporting import find_latest_run, load_csv, load_json
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.storage import create_run_directory, write_csv, write_json
from hourly_da.core.visual_weeks import (
    build_stitched_day_ahead_predictions,
    build_week_winner_summary,
    build_weekly_feature_table,
    filter_week_window,
    prepare_test_actuals,
    select_case_weeks,
    summarize_week_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create standardized objective-week plots and metrics for a selected prediction run.")
    parser.add_argument(
        "--prediction-run-label",
        type=str,
        default="model_comparison",
        help="Run label used to locate the latest prediction run.",
    )
    parser.add_argument(
        "--selection-run-label",
        type=str,
        default="case_week_selection",
        help="Run label used to locate the latest frozen objective-week selection.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Optional subset of model names to include in the overlay plots and week metrics.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = HourlyDAPipelineConfig()
    progress = ProgressReporter(total=9, desc="visual_case_weeks")
    prepared = prepare_data_bundle(config)
    progress.step(model_name="prepare_data")
    comparison_run_dir = find_latest_run(config.output_root, args.prediction_run_label)
    comparison_summary = load_json(comparison_run_dir, "run_summary.json")
    comparison_predictions = load_csv(comparison_run_dir, "predictions_long.csv")
    comparison_suite_models = load_json(comparison_run_dir, "suite_models.json").get("models", [])
    try:
        official_naive = load_json(comparison_run_dir, "official_naive_reference.json")
        official_naive_model = str(official_naive.get("model", "")) or None
    except FileNotFoundError:
        official_naive_model = None
    comparison_model_order = [
        str(record.get("model") or record.get("name"))
        for record in comparison_suite_models
        if (record.get("model") or record.get("name"))
    ]
    if args.models:
        comparison_predictions = comparison_predictions[comparison_predictions["model"].isin(args.models)].copy()
        comparison_model_order = [
            model_name for model_name in comparison_model_order if model_name in set(map(str, args.models))
        ]
        comparison_model_order.extend(
            [str(model_name) for model_name in args.models if str(model_name) not in set(comparison_model_order)]
        )

    run_id, run_dir = create_run_directory(config.output_root, "visual_case_weeks")
    progress.step(model_name="load_prediction_run")
    try:
        selection_run_dir = find_latest_run(config.output_root, args.selection_run_label)
        weekly_features = load_csv(selection_run_dir, "weekly_features.csv")
        candidate_weeks = load_csv(selection_run_dir, "candidate_weeks.csv")
        selected_weeks = load_csv(selection_run_dir, "selected_weeks.csv")
    except FileNotFoundError:
        selection_run_dir = None
        weekly_features = build_weekly_feature_table(prepared["canonical_frame"], config)
        candidate_weeks, selected_weeks = select_case_weeks(weekly_features, config)
    progress.step(model_name="load_or_build_selection")
    stitched_predictions = build_stitched_day_ahead_predictions(comparison_predictions, config)
    test_actuals = prepare_test_actuals(prepared["canonical_frame"], config).rename(columns={config.target_col: "y_true"})
    progress.step(model_name="prepare_weeks")

    selected_prediction_frames = []
    selected_actual_frames = []
    for week_row in selected_weeks.to_dict(orient="records"):
        actual_week = filter_week_window(
            test_actuals,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
            timestamp_col="timestamp_local",
        )
        actual_week["category"] = week_row["category"]
        actual_week["iso_week_id"] = week_row["iso_week_id"]
        selected_actual_frames.append(actual_week)
        plot_week_actual_only(
            actual_week=actual_week[["timestamp_local", "y_true"]],
            output_path=run_dir / "plots" / f"{week_row['category']}_actual_only.png",
            title=f"{week_row['category'].replace('_', ' ').title()} ({week_row['iso_week_id']}) Actual DA Prices",
        )

        prediction_week = filter_week_window(
            stitched_predictions,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
            timestamp_col="target_timestamp_local",
        )
        prediction_week["category"] = week_row["category"]
        prediction_week["iso_week_id"] = week_row["iso_week_id"]
        selected_prediction_frames.append(prediction_week)
        plot_week_actual_vs_models(
            prediction_week=prediction_week,
            output_path=run_dir / "plots" / f"{week_row['category']}_actual_vs_all_models.png",
            title=f"{week_row['category'].replace('_', ' ').title()} ({week_row['iso_week_id']}) Stitched D Forecasts",
            model_order=comparison_model_order,
        )
    progress.step(model_name="plot_week_overlays")

    week_metrics = summarize_week_metrics(
        stitched_predictions,
        selected_weeks,
        model_order=comparison_model_order,
        benchmark_model=official_naive_model,
    )
    week_winners = build_week_winner_summary(week_metrics, model_order=comparison_model_order)
    selected_predictions = pd.concat(selected_prediction_frames, ignore_index=True) if selected_prediction_frames else pd.DataFrame()
    selected_actuals = pd.concat(selected_actual_frames, ignore_index=True) if selected_actual_frames else pd.DataFrame()
    progress.step(model_name="summarize_weeks")

    write_csv(run_dir / "weekly_features.csv", weekly_features)
    write_csv(run_dir / "candidate_weeks.csv", candidate_weeks)
    write_csv(run_dir / "selected_weeks.csv", selected_weeks)
    write_csv(run_dir / "selected_week_predictions.csv", selected_predictions)
    write_csv(run_dir / "selected_week_actuals.csv", selected_actuals)
    write_csv(run_dir / "week_metrics.csv", week_metrics)
    write_csv(run_dir / "week_winners.csv", week_winners)
    progress.step(model_name="write_tables")
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "comparison_run_id": comparison_summary["run_id"],
            "comparison_run_dir": str(comparison_run_dir),
            "selection_run_dir": str(selection_run_dir) if selection_run_dir is not None else None,
            "included_models": [
                model_name
                for model_name in comparison_model_order
                if model_name in set(comparison_predictions["model"].dropna().astype(str).tolist())
            ]
            if not comparison_predictions.empty
            else [],
            "official_naive_model": official_naive_model,
            "selection_rule_notes": {
                "typical_week_rule": "closest week to the standardized seasonal centroid",
                "high_volatility_rule": "highest weekly standard deviation",
                "high_price_rule": "highest weekly mean price with very-high-hour count as a tie-breaker",
                "low_price_rule": "lowest weekly mean price with negative-hour share as a tie-breaker",
                "negative_price_rule": "highest negative-hour share among eligible weeks",
                "visual_plot_forecast_rule": "stitched D-only operational day-ahead forecasts",
                "minimum_observed_coverage_pct": config.visual_week_min_observed_coverage_pct,
                "very_high_price_threshold": config.visual_week_high_price_threshold,
            },
        },
    )
    progress.step(model_name="write_summary")

    print(f"Run completed: {run_id}")
    print(selected_weeks[["category", "iso_week_id", "week_start_local_date", "week_end_local_date"]].to_string(index=False))
    print()
    print(candidate_weeks[["category", "candidate_rank", "iso_week_id", "selection_score"]].to_string(index=False))
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)
    progress.step(model_name="complete")
    progress.close()


if __name__ == "__main__":
    main()
