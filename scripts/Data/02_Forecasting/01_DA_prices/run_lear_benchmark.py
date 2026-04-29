from __future__ import annotations

import argparse
from dataclasses import replace

from hourly_da.core.config import HourlyDAPipelineConfig, MonitoringConfig
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.models.lear import LEARModel, LEARSettings
from hourly_da.models.registry import build_naive_baseline_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hourly DA naive + LEAR benchmark.")
    parser.add_argument("--fs-level", type=str, default="FS1", choices=["FS1", "FS2"])
    parser.add_argument("--training-window-days", type=int, default=90)
    parser.add_argument("--min-train-days", type=int, default=30)
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--fit-time-threshold-sec", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_label = f"lear_{args.fs_level.lower()}_benchmark"
    config = replace(
        HourlyDAPipelineConfig(),
        monitoring=MonitoringConfig(fit_time_absolute_threshold_sec=args.fit_time_threshold_sec),
    )
    models = [
        *build_naive_baseline_models(),
        LEARModel(
            LEARSettings(
                fs_level=args.fs_level,
                training_window_hours=args.training_window_days * 24,
                min_train_rows=args.min_train_days * 24,
                alpha=args.alpha,
            )
        ),
    ]
    run_id, overall_metrics, _, timing_summary, official_naive = run_benchmark_suite(
        config=config,
        run_label=run_label,
        models=models,
        show_progress=True,
        progress_label=run_label,
    )

    validation = overall_metrics[overall_metrics["dataset_split"] == "validation"].copy()
    validation = validation.sort_values(["mae", "model"]).reset_index(drop=True)
    print(f"Run completed: {run_id}")
    print(f"Benchmark stage: {args.fs_level}")
    print(f"Official naive benchmark on validation: {official_naive['model']} (MAE={official_naive['mae']:.4f})")
    if not validation.empty:
        print(validation[["model", "mae", "rmae_vs_official_naive"]].to_string(index=False))
    learner_timing = timing_summary[timing_summary["model"].str.startswith("lear_")]
    if not learner_timing.empty:
        print(learner_timing[["model", "fit_time_mean_sec", "fit_time_warning_count"]].to_string(index=False))
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)


if __name__ == "__main__":
    main()
