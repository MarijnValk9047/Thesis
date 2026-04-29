from __future__ import annotations

import json

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.pipeline import prepare_data_bundle
from hourly_da.core.plotting import plot_week_actual_only
from hourly_da.core.progress import ProgressReporter
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.storage import create_run_directory, write_csv, write_json
from hourly_da.core.visual_weeks import (
    build_weekly_feature_table,
    filter_week_window,
    prepare_test_actuals,
    select_case_weeks,
)


def main() -> None:
    config = HourlyDAPipelineConfig()
    progress = ProgressReporter(total=8, desc="case_week_selection")
    prepared = prepare_data_bundle(config)
    progress.step(model_name="prepare_data")
    run_id, run_dir = create_run_directory(config.output_root, "case_week_selection")

    weekly_features = build_weekly_feature_table(prepared["canonical_frame"], config)
    candidate_weeks, selected_weeks = select_case_weeks(weekly_features, config)
    progress.step(model_name="select_weeks")
    test_actuals = prepare_test_actuals(prepared["canonical_frame"], config).rename(columns={config.target_col: "y_true"})
    progress.step(model_name="prepare_actuals")

    selected_actual_frames: list[pd.DataFrame] = []
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
    progress.step(model_name="plot_actual_weeks")

    selected_actuals = pd.concat(selected_actual_frames, ignore_index=True) if selected_actual_frames else pd.DataFrame()
    progress.step(model_name="combine_outputs")

    write_csv(run_dir / "weekly_features.csv", weekly_features)
    write_csv(run_dir / "candidate_weeks.csv", candidate_weeks)
    write_csv(run_dir / "selected_weeks.csv", selected_weeks)
    write_csv(run_dir / "selected_week_actuals.csv", selected_actuals)
    progress.step(model_name="write_tables")
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "selection_rule_notes": {
                "typical_week_rule": "closest week to the standardized seasonal centroid",
                "high_volatility_rule": "highest weekly standard deviation",
                "high_price_rule": "highest weekly mean price with very-high-hour count as a tie-breaker",
                "low_price_rule": "lowest weekly mean price with negative-hour share as a tie-breaker",
                "negative_price_rule": "highest negative-hour share among eligible weeks",
                "minimum_observed_coverage_pct": config.visual_week_min_observed_coverage_pct,
                "very_high_price_threshold": config.visual_week_high_price_threshold,
            },
        },
    )
    progress.step(model_name="write_summary")

    print(f"Run completed: {run_id}")
    if not selected_weeks.empty:
        print(selected_weeks[["category", "iso_week_id", "week_start_local_date", "week_end_local_date"]].to_string(index=False))
        print()
    if not candidate_weeks.empty:
        print(candidate_weeks[["category", "candidate_rank", "iso_week_id", "selection_score"]].to_string(index=False))
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)
    progress.step(model_name="complete")
    progress.close()


if __name__ == "__main__":
    main()
