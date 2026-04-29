from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from da_forecasting.backtest import run_walk_forward_for_split
from da_forecasting.config import ForecastSetup
from da_forecasting.data import load_target_frame
from da_forecasting.io_utils import create_run_directory, write_csv, write_json
from da_forecasting.metrics import add_error_columns, choose_official_naive, summarize_metrics
from da_forecasting.models.naive import NaivePreviousDayModel, NaivePreviousWeekModel
from da_forecasting.splits import build_split_summary, generate_origins_for_split, label_splits
from da_forecasting.visualization import (
    canonical_forecast_track,
    plot_split_overview,
    plot_zoom_period,
    select_week_month_periods,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rolling-origin naive benchmark for NL DA prices.")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=ForecastSetup.input_csv,
        help="Path to cleaned hourly NL DA prices CSV.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ForecastSetup.output_root,
        help="Root output directory for run artifacts.",
    )
    parser.add_argument("--market-area", type=str, default=ForecastSetup.market_area, help="Market area code.")
    parser.add_argument("--local-timezone", type=str, default=ForecastSetup.local_timezone, help="Local timezone.")
    parser.add_argument(
        "--origin-hour-local",
        type=int,
        default=ForecastSetup.origin_hour_local,
        help="Local forecast origin hour.",
    )
    parser.add_argument(
        "--origin-step-days",
        type=int,
        default=ForecastSetup.origin_step_days,
        help="Step size between origins in days.",
    )
    parser.add_argument("--horizon-days", type=int, default=ForecastSetup.horizon_days, help="Forecast horizon in days.")
    parser.add_argument(
        "--reference-metric",
        type=str,
        default="mae",
        help="Metric used to select official naive reference on validation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    setup = replace(
        ForecastSetup(),
        input_csv=args.input_csv,
        output_root=args.output_root,
        market_area=args.market_area,
        local_timezone=args.local_timezone,
        origin_hour_local=args.origin_hour_local,
        origin_step_days=args.origin_step_days,
        horizon_days=args.horizon_days,
    )

    labeled = label_splits(load_target_frame(setup), setup)
    split_summary = build_split_summary(labeled)

    models = [NaivePreviousDayModel(), NaivePreviousWeekModel()]
    validation_predictions = run_walk_forward_for_split(labeled, setup, "validation", models)
    test_predictions = run_walk_forward_for_split(labeled, setup, "test", models)

    all_predictions = pd.concat([validation_predictions, test_predictions], ignore_index=True)
    scored = add_error_columns(all_predictions)
    metrics_df = summarize_metrics(scored)
    official_naive = choose_official_naive(metrics_df, split_name="validation", metric_col=args.reference_metric)
    plot_model = str(official_naive["model"])

    origin_summary_rows: list[dict[str, object]] = []
    for split_name in ("validation", "test"):
        origin_summary_rows.append(
            {
                "split": split_name,
                "origins": len(generate_origins_for_split(setup, split_name)),
                "origin_hour_local": setup.origin_hour_local,
                "origin_step_days": setup.origin_step_days,
                "horizon_days": setup.horizon_days,
            }
        )
    origins_summary = pd.DataFrame(origin_summary_rows)

    validation_track = canonical_forecast_track(scored, split_name="validation", model_name=plot_model)
    test_track = canonical_forecast_track(scored, split_name="test", model_name=plot_model)
    period_selection = select_week_month_periods(test_track, local_timezone=setup.local_timezone)

    run_dir = create_run_directory(setup.output_root)
    plots_dir = run_dir / "plots"

    plot_split_overview(
        labeled=labeled,
        setup=setup,
        validation_track=validation_track,
        test_track=test_track,
        output_path=plots_dir / "split_overview_actual_vs_forecast.png",
        model_name=plot_model,
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["best_week"],
        output_path=plots_dir / "test_best_week.png",
        title=f"Best Test Week ({plot_model})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["worst_week"],
        output_path=plots_dir / "test_worst_week.png",
        title=f"Worst Test Week ({plot_model})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["best_month"],
        output_path=plots_dir / "test_best_month.png",
        title=f"Best Test Month ({plot_model})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["worst_month"],
        output_path=plots_dir / "test_worst_month.png",
        title=f"Worst Test Month ({plot_model})",
    )

    write_json(run_dir / "config_snapshot.json", setup.to_json_dict())
    write_csv(run_dir / "split_summary.csv", split_summary)
    write_csv(run_dir / "origin_summary.csv", origins_summary)
    write_csv(run_dir / "predictions_validation.csv", validation_predictions)
    write_csv(run_dir / "predictions_test.csv", test_predictions)
    write_csv(run_dir / "predictions_all_scored.csv", scored)
    write_csv(run_dir / "metrics_by_split_model.csv", metrics_df)
    write_json(run_dir / "official_naive_reference.json", official_naive)
    write_csv(run_dir / "canonical_validation_track.csv", validation_track)
    write_csv(run_dir / "canonical_test_track.csv", test_track)
    write_csv(run_dir / "test_weekly_mae_table.csv", period_selection["week_table"])
    write_csv(run_dir / "test_monthly_mae_table.csv", period_selection["month_table"])
    write_json(
        run_dir / "test_best_worst_periods.json",
        {
            "model": plot_model,
            "best_week": period_selection["best_week"].to_dict(),
            "worst_week": period_selection["worst_week"].to_dict(),
            "best_month": period_selection["best_month"].to_dict(),
            "worst_month": period_selection["worst_month"].to_dict(),
        },
    )

    print(f"Run completed. Artifacts written to: {run_dir}")
    print(f"Official naive reference: {official_naive['model']} ({args.reference_metric}={official_naive[args.reference_metric]:.4f})")
    print(f"Plots created for model: {plot_model}")


if __name__ == "__main__":
    main()
