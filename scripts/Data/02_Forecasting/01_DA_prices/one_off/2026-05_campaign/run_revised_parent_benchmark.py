from __future__ import annotations

import argparse

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.feature_value import instantiate_model_from_parent_context, resolve_parent_stage_run
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.reporting import load_json
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.storage import write_json
from hourly_da.models.registry import build_naive_baseline_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a revised FS2/FS3 parent benchmark by reconstructing the saved parent settings and excluding selected blocks."
    )
    parser.add_argument("--fs-level", type=str, required=True, choices=["FS2", "FS3"])
    parser.add_argument("--model-family", type=str, required=True, choices=["lear", "xgboost", "prophet"])
    parser.add_argument("--parent-run-label", type=str, required=True)
    parser.add_argument("--run-label", type=str, required=True)
    parser.add_argument("--ablation-scheme", type=str, required=True)
    parser.add_argument("--excluded-blocks", nargs="+", required=True)
    parser.add_argument("--ablation-target-block", type=str, default=None)
    parser.add_argument("--show-progress", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = HourlyDAPipelineConfig()
    parent = resolve_parent_stage_run(
        config,
        model_family=args.model_family,
        fs_level=args.fs_level,
        parent_run_label=args.parent_run_label,
    )
    revised_model = instantiate_model_from_parent_context(
        parent,
        excluded_feature_families=tuple(str(value) for value in args.excluded_blocks),
        ablation_scheme_name=str(args.ablation_scheme),
        ablation_target_block=str(args.ablation_target_block) if args.ablation_target_block else None,
    )
    include_external_features = str(args.fs_level) == "FS3"
    run_id, overall_metrics, _, timing_summary, official_naive = run_benchmark_suite(
        config=config,
        run_label=str(args.run_label),
        models=[*build_naive_baseline_models(), revised_model],
        include_external_features=include_external_features,
        show_progress=args.show_progress,
        progress_label=str(args.run_label),
    )

    run_dir = config.output_root / "runs" / run_id
    summary = load_json(run_dir, "run_summary.json")
    summary["lineage_parent_run_id"] = parent.run_id
    summary["lineage_parent_run_label"] = parent.run_label
    summary["lineage_validation_mode"] = "frozen_parent_settings"
    summary["lineage_ablation_scheme"] = str(args.ablation_scheme)
    summary["lineage_ablation_target_block"] = str(args.ablation_target_block or "")
    summary["lineage_excluded_blocks"] = [str(value) for value in args.excluded_blocks]
    write_json(run_dir / "run_summary.json", summary)

    validation = overall_metrics[overall_metrics["dataset_split"] == "validation"].copy()
    validation = validation.sort_values(["mae", "model"]).reset_index(drop=True)
    print(f"Run completed: {run_id}")
    print(f"Parent baseline: {parent.run_id} ({parent.run_label})")
    print(f"Validation mode: frozen_parent_settings")
    print(f"Excluded blocks: {', '.join(str(value) for value in args.excluded_blocks)}")
    print(f"Official naive benchmark on validation: {official_naive['model']} (MAE={official_naive['mae']:.4f})")
    if not validation.empty:
        print(validation[["model", "mae", "rmae_vs_official_naive"]].to_string(index=False))
    model_prefix = f"{args.model_family}_{args.fs_level.lower()}"
    timing_view = timing_summary[timing_summary["model"].astype(str).str.startswith(model_prefix)]
    if not timing_view.empty:
        print(timing_view[["model", "fit_time_mean_sec", "fit_time_warning_count"]].to_string(index=False))
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)


if __name__ == "__main__":
    main()
