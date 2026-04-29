from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.reporting import find_latest_run, load_csv
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.storage import write_csv, write_json, write_text
from hourly_da.core.tuning_workbench import (
    XGBOOST_FS3_ACTIVE_MODEL_NAME,
    XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL,
    XGBOOST_FS3_TUNING_AUTO_FULL_VALIDATION_TOP_K,
    XGBOOST_FS3_TUNING_MIN_VALIDATION_COVERAGE_PCT,
    XGBOOST_FS3_TUNING_PILOT_ORIGIN_COUNT,
    XGBOOST_FS3_TUNING_PRIMARY_SPLIT,
    XGBOOST_FS3_TUNING_RUN_LABEL_PREFIX,
    auto_select_full_validation_candidates,
    build_origin_schedule_by_split,
    build_pilot_sequence_frame,
    build_tuning_candidate_detail,
    build_tuning_candidate_summary,
    build_xgboost_fs3_tuning_baselines,
    build_xgboost_fs3_tuning_candidate_models,
    default_xgboost_fs3_pilot_candidate_plan,
    origin_schedule_summary_frame,
    save_xgboost_fs3_pilot_plots,
    with_selected_evaluation_splits,
)
from hourly_da.notebook_support import format_duration, run_suite_with_feedback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the validation-only XGBoost FS3 tuning pilot and save a compact report bundle.")
    parser.add_argument("--pilot-origin-count", type=int, default=XGBOOST_FS3_TUNING_PILOT_ORIGIN_COUNT)
    parser.add_argument("--top-k", type=int, default=XGBOOST_FS3_TUNING_AUTO_FULL_VALIDATION_TOP_K)
    parser.add_argument("--run-label", type=str, default=f"{XGBOOST_FS3_TUNING_RUN_LABEL_PREFIX}_pilot_v1")
    parser.add_argument("--existing-run-id", type=str, default="", help="Reuse a completed pilot run for post-processing only.")
    return parser.parse_args()


def _runtime_projection_frame(
    output_root: Path,
    *,
    pilot_origin_count: int,
    candidate_count: int,
    top_k: int,
) -> pd.DataFrame:
    try:
        benchmark_run_dir = find_latest_run(output_root, XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL)
    except FileNotFoundError:
        return pd.DataFrame()

    timing = load_csv(benchmark_run_dir, "origin_timing_summary.csv")
    current_rows = timing[
        (timing["dataset_split"].astype(str) == XGBOOST_FS3_TUNING_PRIMARY_SPLIT)
        & (timing["model"].astype(str) == XGBOOST_FS3_ACTIVE_MODEL_NAME)
    ].copy()
    if current_rows.empty:
        return pd.DataFrame()

    row = current_rows.iloc[0]
    per_origin_seconds = float(row["fit_time_mean_sec"]) + float(row["predict_time_mean_sec"])
    full_validation_origins = int(row["origins"])

    pilot_models = int(candidate_count) + 2
    full_validation_models = int(top_k) + 2

    return pd.DataFrame(
        [
            {
                "reference_run_id": benchmark_run_dir.name,
                "per_origin_seconds": per_origin_seconds,
                "pilot_origin_count": int(pilot_origin_count),
                "pilot_model_count": pilot_models,
                "pilot_projected_seconds": per_origin_seconds * int(pilot_origin_count) * pilot_models,
                "pilot_projected_duration": format_duration(per_origin_seconds * int(pilot_origin_count) * pilot_models),
                "full_validation_origin_count": full_validation_origins,
                "full_validation_model_count": full_validation_models,
                "full_validation_projected_seconds": per_origin_seconds * full_validation_origins * full_validation_models,
                "full_validation_projected_duration": format_duration(
                    per_origin_seconds * full_validation_origins * full_validation_models
                ),
                "combined_projected_seconds": (
                    per_origin_seconds * int(pilot_origin_count) * pilot_models
                    + per_origin_seconds * full_validation_origins * full_validation_models
                ),
                "combined_projected_duration": format_duration(
                    per_origin_seconds * int(pilot_origin_count) * pilot_models
                    + per_origin_seconds * full_validation_origins * full_validation_models
                ),
            }
        ]
    )


def _pilot_markdown_report(
    *,
    run_id: str,
    pilot_origin_count: int,
    schedule_summary: pd.DataFrame,
    runtime_projection: pd.DataFrame,
    pilot_summary: pd.DataFrame,
    promoted_candidate_ids: list[str],
    plot_paths: dict[str, str],
) -> str:
    lines = [
        "# XGBoost FS3 tuning pilot report",
        "",
        f"Pilot run id: `{run_id}`",
        f"Primary split: `{XGBOOST_FS3_TUNING_PRIMARY_SPLIT}`",
        f"Pilot origin count: `{pilot_origin_count}`",
        "",
    ]

    if not schedule_summary.empty:
        sampled = schedule_summary.iloc[0].to_dict()
        lines.extend(
            [
                "## Sampled validation schedule",
                "",
                f"- sampled origins: `{int(sampled['sample_origin_count'])}` of `{int(sampled['full_origin_count'])}`",
                f"- sample share: `{float(sampled['sample_share_pct']):.2f}%`",
                f"- first sampled origin: `{sampled['sample_first_origin_utc']}`",
                f"- last sampled origin: `{sampled['sample_last_origin_utc']}`",
                "",
            ]
        )

    if not runtime_projection.empty:
        projection = runtime_projection.iloc[0].to_dict()
        lines.extend(
            [
                "## Runtime projection from the current FS3 benchmark",
                "",
                f"- projected pilot runtime: `{projection['pilot_projected_duration']}`",
                f"- projected pilot + full-validation runtime: `{projection['combined_projected_duration']}`",
                "",
            ]
        )

    if not pilot_summary.empty:
        baseline = pilot_summary[pilot_summary["model"].astype(str) == "xgboost_fs3_current_baseline"].copy()
        candidates = pilot_summary[pilot_summary["model"].astype(str).str.startswith("xgboost_fs3_tune_")].copy()
        winner = candidates.sort_values(
            ["mae_stitched_all_horizon", "mae_d_only", "fit_time_mean_sec"],
            ascending=[True, True, True],
        ).head(1)
        if not baseline.empty:
            baseline_row = baseline.iloc[0]
            lines.extend(
                [
                    "## Baseline",
                    "",
                    f"- current FS3 stitched MAE: `{float(baseline_row['mae_stitched_all_horizon']):.4f}`",
                    f"- current FS3 stitched rMAE: `{float(baseline_row['rmae_stitched_all_horizon']):.4f}`",
                    "",
                ]
            )
        if not winner.empty:
            winner_row = winner.iloc[0]
            lines.extend(
                [
                    "## Best pilot candidate",
                    "",
                    f"- candidate: `{winner_row['model']}`",
                    f"- stitched MAE: `{float(winner_row['mae_stitched_all_horizon']):.4f}`",
                    f"- stitched rMAE: `{float(winner_row['rmae_stitched_all_horizon']):.4f}`",
                    f"- delta vs current FS3 baseline: `{float(winner_row['delta_vs_baseline_stitched_mae']):+.4f}`",
                    "",
                ]
            )

    lines.extend(
        [
            "## Auto-promoted candidates for full validation",
            "",
        ]
    )
    if promoted_candidate_ids:
        lines.extend(f"- `{candidate_id}`" for candidate_id in promoted_candidate_ids)
    else:
        lines.append("- none")
    lines.append("")

    if plot_paths:
        lines.extend(
            [
                "## Saved plots",
                "",
                *(f"- `{name}`: `{path}`" for name, path in plot_paths.items()),
                "",
            ]
        )

    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    config = HourlyDAPipelineConfig()
    analysis_root = config.output_root / "analysis" / "xgboost_fs3_tuning"
    analysis_root.mkdir(parents=True, exist_ok=True)

    candidate_plan = default_xgboost_fs3_pilot_candidate_plan()
    validation_only_config = with_selected_evaluation_splits(config, (XGBOOST_FS3_TUNING_PRIMARY_SPLIT,))
    full_validation_schedule = build_origin_schedule_by_split(
        validation_only_config,
        split_names=(XGBOOST_FS3_TUNING_PRIMARY_SPLIT,),
    )
    pilot_validation_schedule = build_origin_schedule_by_split(
        validation_only_config,
        split_names=(XGBOOST_FS3_TUNING_PRIMARY_SPLIT,),
        max_origins_by_split={XGBOOST_FS3_TUNING_PRIMARY_SPLIT: int(args.pilot_origin_count)},
    )
    schedule_summary = pd.concat(
        [
            origin_schedule_summary_frame(
                validation_only_config,
                split_name=XGBOOST_FS3_TUNING_PRIMARY_SPLIT,
                sampled_schedule=pilot_validation_schedule[XGBOOST_FS3_TUNING_PRIMARY_SPLIT],
            ).assign(note="pilot_sample"),
            origin_schedule_summary_frame(
                validation_only_config,
                split_name=XGBOOST_FS3_TUNING_PRIMARY_SPLIT,
                sampled_schedule=full_validation_schedule[XGBOOST_FS3_TUNING_PRIMARY_SPLIT],
            ).assign(note="full_validation_reference"),
        ],
        ignore_index=True,
    )
    runtime_projection = _runtime_projection_frame(
        config.output_root,
        pilot_origin_count=int(args.pilot_origin_count),
        candidate_count=int(candidate_plan.shape[0]),
        top_k=int(args.top_k),
    )

    print("Pilot candidate plan:")
    print(
        candidate_plan[
            [
                "candidate_id",
                "learning_rate",
                "max_depth",
                "n_estimators",
                "subsample",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ]
        ].to_string(index=False)
    )
    print("")
    print("Schedule summary:")
    print(schedule_summary.to_string(index=False))
    print("")
    if not runtime_projection.empty:
        print("Runtime projection:")
        print(runtime_projection.to_string(index=False))
        print("")

    if str(args.existing_run_id).strip():
        run_dir = config.output_root / "runs" / str(args.existing_run_id).strip()
        if not run_dir.exists():
            raise FileNotFoundError(f"Pilot run directory does not exist: {run_dir}")
        print(f"Reusing existing pilot run for post-processing: {run_dir.name}")
    else:
        pilot_models = [
            *build_xgboost_fs3_tuning_baselines(
                validation_only_config,
                current_baseline_name="xgboost_fs3_current_baseline",
            ),
            *build_xgboost_fs3_tuning_candidate_models(validation_only_config, candidate_plan),
        ]

        pilot_result = run_suite_with_feedback(
            validation_only_config,
            run_label=str(args.run_label),
            models=pilot_models,
            include_external_features=True,
            show_progress=True,
            progress_label=str(args.run_label),
            origin_schedule_by_split=pilot_validation_schedule,
        )
        run_dir = Path(pilot_result["run_dir"])
    analysis_dir = analysis_root / run_dir.name
    plots_dir = analysis_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    metrics_by_reporting_level = load_csv(run_dir, "metrics_by_reporting_level.csv")
    origin_timing_summary = load_csv(run_dir, "origin_timing_summary.csv")
    model_order = [
        "naive_previous_week",
        "naive_previous_year",
        "xgboost_fs2_anchor",
        "xgboost_fs3_current_baseline",
        *candidate_plan["candidate_id"].astype(str).tolist(),
    ]
    pilot_summary = build_tuning_candidate_summary(
        metrics_by_reporting_level,
        origin_timing_summary,
        split_name=XGBOOST_FS3_TUNING_PRIMARY_SPLIT,
        baseline_model="xgboost_fs3_current_baseline",
        model_order=model_order,
    )
    pilot_detail = build_tuning_candidate_detail(candidate_plan, pilot_summary)
    pilot_sequence = build_pilot_sequence_frame(pilot_detail, candidate_plan)
    promoted_candidate_ids = auto_select_full_validation_candidates(
        pilot_summary,
        candidate_plan,
        top_k=int(args.top_k),
        min_coverage_pct=XGBOOST_FS3_TUNING_MIN_VALIDATION_COVERAGE_PCT,
    )
    plot_paths = save_xgboost_fs3_pilot_plots(pilot_detail, candidate_plan, plots_dir)

    write_csv(analysis_dir / "candidate_plan.csv", candidate_plan)
    write_csv(analysis_dir / "schedule_summary.csv", schedule_summary)
    if not runtime_projection.empty:
        write_csv(analysis_dir / "runtime_projection.csv", runtime_projection)
    write_csv(analysis_dir / "pilot_summary.csv", pilot_summary)
    write_csv(analysis_dir / "pilot_detail.csv", pilot_detail)
    if not pilot_sequence.empty:
        write_csv(analysis_dir / "pilot_sequence_metrics.csv", pilot_sequence)

    auto_promotion_payload = {
        "run_id": run_dir.name,
        "run_label": str(args.run_label),
        "primary_split": XGBOOST_FS3_TUNING_PRIMARY_SPLIT,
        "pilot_origin_count": int(args.pilot_origin_count),
        "min_validation_coverage_pct": XGBOOST_FS3_TUNING_MIN_VALIDATION_COVERAGE_PCT,
        "top_k": int(args.top_k),
        "promoted_candidate_ids": promoted_candidate_ids,
        "plot_paths": plot_paths,
    }
    write_json(analysis_dir / "pilot_auto_promotions.json", auto_promotion_payload)
    write_text(
        analysis_dir / "pilot_report.md",
        _pilot_markdown_report(
            run_id=run_dir.name,
            pilot_origin_count=int(args.pilot_origin_count),
            schedule_summary=schedule_summary[schedule_summary["note"].astype(str) == "pilot_sample"].copy(),
            runtime_projection=runtime_projection,
            pilot_summary=pilot_summary,
            promoted_candidate_ids=promoted_candidate_ids,
            plot_paths=plot_paths,
        ),
    )

    print("Pilot summary:")
    print(
        pilot_summary[
            [
                "model",
                "mae_stitched_all_horizon",
                "rmae_stitched_all_horizon",
                "mae_d_only",
                "mae_guidance_only",
                "coverage_stitched_all_horizon_pct",
                "delta_vs_baseline_stitched_mae",
                "fit_time_mean_sec",
            ]
        ].to_string(index=False)
    )
    print("")
    print(f"Auto-promoted candidates for full validation: {promoted_candidate_ids or ['none']}")
    print(f"Pilot report bundle saved to: {analysis_dir}")

    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)


if __name__ == "__main__":
    main()
