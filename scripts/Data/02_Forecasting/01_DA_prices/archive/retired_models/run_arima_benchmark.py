from __future__ import annotations

import argparse
from dataclasses import replace

from hourly_da.core.config import HourlyDAPipelineConfig, MonitoringConfig
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.models.arima import ARIMASettings, ARIMAModel
from hourly_da.models.naive import PreviousWeekNaiveModel, PreviousYearNaiveModel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hourly DA naive + ARIMA benchmark.")
    parser.add_argument("--history-window-days", type=int, default=30)
    parser.add_argument("--min-history-days", type=int, default=20)
    parser.add_argument("--maxiter", type=int, default=10)
    parser.add_argument("--fit-time-threshold-sec", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = replace(
        HourlyDAPipelineConfig(),
        monitoring=MonitoringConfig(fit_time_absolute_threshold_sec=args.fit_time_threshold_sec),
    )
    arima_settings = ARIMASettings(
        history_window_hours=args.history_window_days * 24,
        min_observed_history_hours=args.min_history_days * 24,
        maxiter=args.maxiter,
    )
    run_id, overall_metrics, _, timing_summary, official_naive = run_benchmark_suite(
        config=config,
        run_label="arima_benchmark",
        models=[PreviousWeekNaiveModel(), PreviousYearNaiveModel(), ARIMAModel(settings=arima_settings)],
    )

    validation = overall_metrics[overall_metrics["dataset_split"] == "validation"].copy()
    validation = validation.sort_values(["mae", "model"]).reset_index(drop=True)
    print(f"Run completed: {run_id}")
    print(f"Official naive benchmark on validation: {official_naive['model']} (MAE={official_naive['mae']:.4f})")
    if not validation.empty:
        best = validation.iloc[0]
        print(f"Best validation model in ARIMA suite: {best['model']} (MAE={best['mae']:.4f})")
    arima_timing = timing_summary[timing_summary["model"] == "arima"]
    if not arima_timing.empty:
        row = arima_timing.iloc[0]
        print(f"ARIMA mean fit time: {row['fit_time_mean_sec']:.2f}s | warnings: {int(row['fit_time_warning_count'])}")


if __name__ == "__main__":
    main()
