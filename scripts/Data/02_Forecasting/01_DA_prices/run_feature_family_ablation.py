from __future__ import annotations

import argparse

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.feature_value import (
    apply_inherited_rmae_to_child_run,
    build_parent_child_comparison_frames,
    feature_families_for_context,
    feature_family_metadata_payload,
    instantiate_child_model,
    resolve_parent_stage_run,
)
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.schedule import generate_forecast_origins
from hourly_da.core.storage import create_run_directory, write_csv, write_json
from hourly_da.models.registry import build_naive_baseline_models


SUPPORTED_CONTEXTS = (
    ("FS1", "lear"),
    ("FS1", "xgboost"),
    ("FS2", "lear"),
    ("FS2", "xgboost"),
    ("FS2", "prophet"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run grouped feature-family ablations for the active hourly DAM pipeline.")
    parser.add_argument("--fs-level", nargs="+", default=["all"], choices=["FS1", "FS2", "all"])
    parser.add_argument("--model-family", nargs="+", default=["all"], choices=["lear", "xgboost", "prophet", "all"])
    parser.add_argument("--feature-family", nargs="+", default=["all"])
    parser.add_argument("--parent-run-label", type=str, default=None)
    parser.add_argument("--show-progress", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-origins-per-split", type=int, default=2)
    return parser.parse_args()


def selected_contexts(args: argparse.Namespace) -> list[tuple[str, str]]:
    fs_levels = {value for value in args.fs_level if value != "all"}
    model_families = {value for value in args.model_family if value != "all"}
    contexts = []
    for fs_level, model_family in SUPPORTED_CONTEXTS:
        if fs_levels and fs_level not in fs_levels:
            continue
        if model_families and model_family not in model_families:
            continue
        contexts.append((fs_level, model_family))
    return contexts


def smoke_origin_schedules(config: HourlyDAPipelineConfig, limit: int) -> dict[str, pd.DataFrame]:
    return {
        split_name: generate_forecast_origins(config, split_name).head(int(limit)).reset_index(drop=True)
        for split_name in config.evaluation_splits()
    }


def main() -> None:
    args = parse_args()
    config = HourlyDAPipelineConfig()
    contexts = selected_contexts(args)
    if not contexts:
        raise RuntimeError("No FS/model contexts matched the requested target filters.")

    selected_family_filter = {value for value in args.feature_family if value != "all"}
    origin_schedule_by_split = (
        smoke_origin_schedules(config, args.smoke_origins_per_split) if args.smoke_test else None
    )

    for fs_level, model_family in contexts:
        parent = resolve_parent_stage_run(
            config,
            model_family=model_family,
            fs_level=fs_level,
            parent_run_label=args.parent_run_label,
        )
        families = feature_families_for_context(fs_level, model_family)
        if selected_family_filter:
            unknown = sorted(selected_family_filter - set(families))
            if unknown:
                raise RuntimeError(
                    f"Requested feature families {unknown} are not supported for {model_family} at {fs_level}. "
                    f"Supported families: {families}"
                )
            families = [family for family in families if family in selected_family_filter]
        if not families:
            raise RuntimeError(f"No feature families remain to run for {model_family} at {fs_level}.")

        aggregate_run_label = f"feature_family_ablation__{parent.run_label}"
        aggregate_run_id, aggregate_run_dir = create_run_directory(config.output_root, aggregate_run_label)
        metadata = feature_family_metadata_payload(
            parent,
            aggregate_run_id=aggregate_run_id,
            aggregate_run_label=aggregate_run_label,
            selected_feature_families=families,
            smoke_test=args.smoke_test,
            smoke_origins_per_split=args.smoke_origins_per_split if args.smoke_test else None,
        )

        all_origin_frames: list[pd.DataFrame] = []
        all_reporting_frames: list[pd.DataFrame] = []
        all_summary_frames: list[pd.DataFrame] = []
        parent_child_rows: list[dict[str, object]] = []

        for feature_family in families:
            child_run_label = f"{parent.run_label}__ablate_{feature_family}"
            child_model = instantiate_child_model(parent, excluded_feature_family=feature_family)
            models = [*build_naive_baseline_models(), child_model]
            run_id, _, _, _, _ = run_benchmark_suite(
                config=config,
                run_label=child_run_label,
                models=models,
                show_progress=args.show_progress,
                progress_label=child_run_label,
                origin_schedule_by_split=origin_schedule_by_split,
            )
            child_run_dir = config.output_root / "runs" / run_id
            apply_inherited_rmae_to_child_run(child_run_dir, parent, feature_family=feature_family)
            by_origin, by_reporting_level, summary = build_parent_child_comparison_frames(
                parent,
                child_run_dir=child_run_dir,
                feature_family=feature_family,
                smoke_test=args.smoke_test,
            )
            all_origin_frames.append(by_origin)
            all_reporting_frames.append(by_reporting_level)
            all_summary_frames.append(summary)
            parent_child_rows.append(
                {
                    "model": parent.model_name,
                    "model_family": parent.model_family,
                    "fs_stage": parent.fs_level,
                    "feature_family": feature_family,
                    "parent_run_id": parent.run_id,
                    "parent_run_label": parent.run_label,
                    "child_run_id": run_id,
                    "child_run_label": child_run_label,
                    "child_run_dir": str(child_run_dir),
                    "aggregate_run_id": aggregate_run_id,
                    "aggregate_run_label": aggregate_run_label,
                    "comparison_type": "grouped_ablation",
                    "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                }
            )
            print(
                f"Completed {model_family} {fs_level} ablation for {feature_family}: "
                f"parent={parent.run_id}, child={run_id}, aggregate={aggregate_run_id}"
            )

        feature_value_by_origin = pd.concat(all_origin_frames, ignore_index=True) if all_origin_frames else pd.DataFrame()
        feature_value_by_reporting_level = (
            pd.concat(all_reporting_frames, ignore_index=True) if all_reporting_frames else pd.DataFrame()
        )
        feature_value_summary = pd.concat(all_summary_frames, ignore_index=True) if all_summary_frames else pd.DataFrame()
        feature_value_parent_child_map = pd.DataFrame(parent_child_rows)

        for frame in (feature_value_by_origin, feature_value_by_reporting_level, feature_value_summary):
            if "dataset_split" in frame.columns:
                frame.rename(columns={"dataset_split": "split"}, inplace=True)

        write_csv(aggregate_run_dir / "feature_family_value_by_origin.csv", feature_value_by_origin)
        write_csv(aggregate_run_dir / "feature_family_value_by_reporting_level.csv", feature_value_by_reporting_level)
        write_csv(aggregate_run_dir / "feature_family_value_summary.csv", feature_value_summary)
        write_csv(aggregate_run_dir / "feature_family_parent_child_map.csv", feature_value_parent_child_map)
        write_json(aggregate_run_dir / "feature_family_value_metadata.json", metadata)
        write_json(
            aggregate_run_dir / "run_summary.json",
            {
                "run_id": aggregate_run_id,
                "run_label": aggregate_run_label,
                "run_role": "feature_family_ablation_aggregate",
                "model": parent.model_name,
                "model_family": parent.model_family,
                "fs_stage": parent.fs_level,
                "parent_run_id": parent.run_id,
                "parent_run_label": parent.run_label,
                "feature_families": families,
                "child_run_ids": [row["child_run_id"] for row in parent_child_rows],
                "smoke_test": bool(args.smoke_test),
            },
        )
        print(
            f"Aggregate feature-family ablation run completed for {model_family} {fs_level}: "
            f"{aggregate_run_id} ({len(families)} families)"
        )


if __name__ == "__main__":
    main()
