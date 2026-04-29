from __future__ import annotations

import argparse

import pandas as pd

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    aggregate_run_label_for_scheme,
    fs2_ablation_scheme_payload,
    supported_fs2_layer2_target_blocks,
    supported_layer2_target_blocks,
)
from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.external_features import load_external_feature_store
from hourly_da.core.feature_value import (
    apply_inherited_rmae_to_child_run,
    build_fs2_ablation_preflight,
    build_fs3_ablation_preflight,
    build_parent_child_comparison_frames,
    feature_family_metadata_payload,
    instantiate_model_from_parent_context,
    resolve_parent_stage_run,
)
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.reporting import resolve_tabular_path
from hourly_da.core.schedule import generate_forecast_origins
from hourly_da.core.storage import create_run_directory, write_csv, write_json
from hourly_da.models.registry import build_naive_baseline_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged block ablation against an existing FS2 or FS3 parent run.")
    parser.add_argument("--fs-level", type=str, required=True, choices=["FS2", "FS3"])
    parser.add_argument("--model-family", type=str, required=True, choices=["lear", "xgboost", "prophet"])
    parser.add_argument("--parent-run-label", type=str, required=True)
    parser.add_argument(
        "--ablation-schemes",
        nargs="+",
        default=[SCHEME_NAME_STAGE_A, SCHEME_NAME_LAYER_1],
        choices=[SCHEME_NAME_STAGE_A, SCHEME_NAME_LAYER_1, SCHEME_NAME_LAYER_2],
    )
    parser.add_argument("--layer2-target-block", nargs="+", default=None)
    parser.add_argument("--show-progress", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-origins-per-split", type=int, default=2)
    return parser.parse_args()


def smoke_origin_schedules(config: HourlyDAPipelineConfig, limit: int) -> dict[str, pd.DataFrame]:
    return {
        split_name: generate_forecast_origins(config, split_name).head(int(limit)).reset_index(drop=True)
        for split_name in config.evaluation_splits()
    }


def _ordered_unique(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered


def _scheme_requests(args: argparse.Namespace, *, config: HourlyDAPipelineConfig) -> list[dict[str, str | None]]:
    requested = _ordered_unique([str(value) for value in (args.ablation_schemes or [SCHEME_NAME_STAGE_A, SCHEME_NAME_LAYER_1])])
    if args.layer2_target_block and SCHEME_NAME_LAYER_2 not in requested:
        requested.append(SCHEME_NAME_LAYER_2)

    requests: list[dict[str, str | None]] = []
    if args.fs_level == "FS2":
        supported_targets = set(supported_fs2_layer2_target_blocks())
    else:
        store = load_external_feature_store(config)
        supported_targets = set(supported_layer2_target_blocks(store.experiment_map()))

    for scheme_name in requested:
        if str(scheme_name) != SCHEME_NAME_LAYER_2:
            requests.append({"scheme_name": str(scheme_name), "target_block": None})
            continue
        target_blocks = _ordered_unique([str(value) for value in (args.layer2_target_block or [])])
        if not target_blocks:
            continue
        unknown = [block_name for block_name in target_blocks if block_name not in supported_targets]
        if unknown:
            raise ValueError(f"Unsupported Layer 2 target blocks: {unknown}. Supported targets: {sorted(supported_targets)}")
        for target_block in target_blocks:
            requests.append({"scheme_name": SCHEME_NAME_LAYER_2, "target_block": str(target_block)})
    return requests


def _write_scheme_aggregate_artifacts(
    *,
    aggregate_run_dir,
    by_origin: pd.DataFrame,
    by_reporting_level: pd.DataFrame,
    summary: pd.DataFrame,
    parent_child_map: pd.DataFrame,
    metadata: dict[str, object],
    run_summary_payload: dict[str, object],
    preflight_summary: pd.DataFrame,
    preflight_assignments: pd.DataFrame,
    preflight_block_sizes: pd.DataFrame,
) -> None:
    write_csv(aggregate_run_dir / "feature_family_value_by_origin.csv", by_origin)
    write_csv(aggregate_run_dir / "feature_family_value_by_reporting_level.csv", by_reporting_level)
    write_csv(aggregate_run_dir / "feature_family_value_summary.csv", summary)
    write_csv(aggregate_run_dir / "feature_family_parent_child_map.csv", parent_child_map)
    write_csv(aggregate_run_dir / "ablation_preflight_summary.csv", preflight_summary)
    write_csv(aggregate_run_dir / "ablation_preflight_assignments.csv", preflight_assignments)
    write_csv(aggregate_run_dir / "ablation_preflight_block_sizes.csv", preflight_block_sizes)
    write_json(aggregate_run_dir / "feature_family_value_metadata.json", metadata)
    write_json(aggregate_run_dir / "run_summary.json", run_summary_payload)


def _run_label_from_run_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _resolve_existing_complete_child_run_dir(
    *,
    config: HourlyDAPipelineConfig,
    run_label: str,
) -> tuple[str, object] | None:
    run_root = config.output_root / "runs"
    if not run_root.exists():
        return None
    candidates = sorted(
        candidate
        for candidate in run_root.iterdir()
        if candidate.is_dir() and _run_label_from_run_dir_name(candidate.name) == str(run_label)
    )
    for candidate in reversed(candidates):
        try:
            resolve_tabular_path(candidate, "predictions_long.csv")
            resolve_tabular_path(candidate, "metrics_by_reporting_level.csv")
        except FileNotFoundError:
            continue
        if not (candidate / "run_summary.json").exists():
            continue
        return candidate.name, candidate
    return None


def main() -> None:
    args = parse_args()
    config = HourlyDAPipelineConfig()
    parent = resolve_parent_stage_run(
        config,
        model_family=args.model_family,
        fs_level=args.fs_level,
        parent_run_label=args.parent_run_label,
    )
    scheme_requests = _scheme_requests(args, config=config)
    if not scheme_requests:
        raise RuntimeError("No ablation schemes remain after filtering the requested Layer 2 targets.")

    origin_schedule_by_split = smoke_origin_schedules(config, args.smoke_origins_per_split) if args.smoke_test else None
    include_external_features = str(args.fs_level) == "FS3"
    experiment_map = load_external_feature_store(config).experiment_map() if include_external_features else {}
    parent_model = instantiate_model_from_parent_context(parent)

    for request in scheme_requests:
        scheme_name = str(request["scheme_name"])
        target_block = str(request["target_block"]) if request["target_block"] else None
        if args.fs_level == "FS2":
            preflight = build_fs2_ablation_preflight(
                config=config,
                model=parent_model,
                scheme_name=scheme_name,
                target_block=target_block,
            )
            scheme_payload = fs2_ablation_scheme_payload(scheme_name=scheme_name, target_block=target_block)
        else:
            preflight = build_fs3_ablation_preflight(
                config=config,
                model=parent_model,
                experiment_map=experiment_map,
                scheme_name=scheme_name,
                target_block=target_block,
            )
            scheme_payload = dict(preflight["scheme_payload"])
        block_names = [str(block["block_name"]) for block in preflight["scheme_payload"]["blocks"]]
        aggregate_run_label = aggregate_run_label_for_scheme(
            parent_run_label=parent.run_label,
            scheme_name=scheme_name,
            scheme_version=str(preflight["scheme_payload"]["scheme_version"]),
            target_block=target_block,
        )
        aggregate_run_id, aggregate_run_dir = create_run_directory(config.output_root, aggregate_run_label)

        metadata = feature_family_metadata_payload(
            parent,
            aggregate_run_id=aggregate_run_id,
            aggregate_run_label=aggregate_run_label,
            selected_feature_families=block_names,
            smoke_test=args.smoke_test,
            smoke_origins_per_split=args.smoke_origins_per_split if args.smoke_test else None,
        )
        metadata.update(
            {
                "comparison_unit_name": "ablation_block",
                "artifact_field_name": "feature_family",
                "selected_blocks": block_names,
                "ablation_scheme": preflight["scheme_payload"],
                "scheme_name": preflight["scheme_payload"]["scheme_name"],
                "scheme_version": preflight["scheme_payload"]["scheme_version"],
                "stage_name": preflight["scheme_payload"]["stage_name"],
                "layer_name": preflight["scheme_payload"]["layer_name"],
                "target_block": target_block or "",
                "scheme_hash": preflight["scheme_payload"]["scheme_hash"],
                "static_scheme_hash": preflight["scheme_payload"]["static_scheme_hash"],
                "feature_taxonomy_hash": preflight["scheme_payload"]["feature_taxonomy_hash"],
                "preflight_valid": bool(preflight["valid"]),
                "aggregate_status": "invalid" if not preflight["valid"] else "complete",
                "run_completeness_status": "invalid" if not preflight["valid"] else "complete",
                "execution_status": "invalid_preflight" if not preflight["valid"] else "success",
            }
        )

        if not preflight["valid"]:
            _write_scheme_aggregate_artifacts(
                aggregate_run_dir=aggregate_run_dir,
                by_origin=pd.DataFrame(),
                by_reporting_level=pd.DataFrame(),
                summary=pd.DataFrame(),
                parent_child_map=pd.DataFrame(),
                metadata=metadata,
                run_summary_payload={
                    "run_id": aggregate_run_id,
                    "run_label": aggregate_run_label,
                    "run_role": "feature_family_ablation_aggregate",
                    "model": parent.model_name,
                    "model_family": parent.model_family,
                    "fs_stage": parent.fs_level,
                    "parent_run_id": parent.run_id,
                    "parent_run_label": parent.run_label,
                    "feature_families": block_names,
                    "smoke_test": bool(args.smoke_test),
                    "aggregate_status": "invalid",
                    "execution_status": "invalid_preflight",
                    "completed_child_count": 0,
                    "expected_child_count": len(block_names),
                    "scheme_name": preflight["scheme_payload"]["scheme_name"],
                    "scheme_version": preflight["scheme_payload"]["scheme_version"],
                    "layer_name": preflight["scheme_payload"]["layer_name"],
                    "stage_name": preflight["scheme_payload"]["stage_name"],
                    "target_block": target_block or "",
                    "scheme_hash": preflight["scheme_payload"]["scheme_hash"],
                    "feature_taxonomy_hash": preflight["scheme_payload"]["feature_taxonomy_hash"],
                },
                preflight_summary=preflight["summary"],
                preflight_assignments=preflight["assignments"],
                preflight_block_sizes=preflight["block_sizes"],
            )
            print(f"Skipped invalid scheme {scheme_name} for {parent.run_label}: effective-column preflight failed.")
            continue

        all_origin_frames: list[pd.DataFrame] = []
        all_reporting_frames: list[pd.DataFrame] = []
        all_summary_frames: list[pd.DataFrame] = []
        parent_child_rows: list[dict[str, object]] = []
        failed_blocks: list[str] = []

        for block_name in block_names:
            child_run_label = f"{parent.run_label}__remove_{block_name}"
            child_model = instantiate_model_from_parent_context(
                parent,
                excluded_feature_families=(block_name,),
                ablation_scheme_name=scheme_name,
                ablation_target_block=target_block,
            )
            child_run_id = ""
            try:
                existing_child = _resolve_existing_complete_child_run_dir(
                    config=config,
                    run_label=child_run_label,
                )
                if existing_child is None:
                    child_run_id, _, _, _, _ = run_benchmark_suite(
                        config=config,
                        run_label=child_run_label,
                        models=[*build_naive_baseline_models(), child_model],
                        include_external_features=include_external_features,
                        show_progress=args.show_progress,
                        progress_label=f"{args.fs_level}_{args.model_family}_{scheme_name}_remove_{block_name}",
                        origin_schedule_by_split=origin_schedule_by_split,
                    )
                    child_run_dir = config.output_root / "runs" / child_run_id
                    apply_inherited_rmae_to_child_run(child_run_dir, parent, feature_family=block_name)
                    child_status = "complete"
                else:
                    child_run_id, child_run_dir = existing_child
                    child_status = "reused_complete"
                by_origin, by_reporting_level, summary = build_parent_child_comparison_frames(
                    parent,
                    child_run_dir=child_run_dir,
                    feature_family=block_name,
                    smoke_test=args.smoke_test,
                )
                for frame in (by_origin, by_reporting_level, summary):
                    frame["scheme_name"] = preflight["scheme_payload"]["scheme_name"]
                    frame["scheme_version"] = preflight["scheme_payload"]["scheme_version"]
                    frame["layer_name"] = preflight["scheme_payload"]["layer_name"]
                    frame["stage_name"] = preflight["scheme_payload"]["stage_name"]
                    frame["target_block"] = target_block or ""
                    frame["scheme_hash"] = preflight["scheme_payload"]["scheme_hash"]
                    frame["feature_taxonomy_hash"] = preflight["scheme_payload"]["feature_taxonomy_hash"]
                all_origin_frames.append(by_origin)
                all_reporting_frames.append(by_reporting_level)
                all_summary_frames.append(summary)
                parent_child_rows.append(
                    {
                        "model": parent.model_name,
                        "model_family": parent.model_family,
                        "fs_stage": parent.fs_level,
                        "feature_family": block_name,
                        "scheme_name": preflight["scheme_payload"]["scheme_name"],
                        "scheme_version": preflight["scheme_payload"]["scheme_version"],
                        "layer_name": preflight["scheme_payload"]["layer_name"],
                        "stage_name": preflight["scheme_payload"]["stage_name"],
                        "target_block": target_block or "",
                        "scheme_hash": preflight["scheme_payload"]["scheme_hash"],
                        "feature_taxonomy_hash": preflight["scheme_payload"]["feature_taxonomy_hash"],
                        "parent_run_id": parent.run_id,
                        "parent_run_label": parent.run_label,
                        "child_run_id": child_run_id,
                        "child_run_label": child_run_label,
                        "child_run_dir": str(child_run_dir),
                        "aggregate_run_id": aggregate_run_id,
                        "aggregate_run_label": aggregate_run_label,
                        "comparison_type": "grouped_ablation",
                        "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                        "comparison_unit_name": "ablation_block",
                        "child_status": child_status,
                        "status": "complete",
                        "smoke_test": bool(args.smoke_test),
                    }
                )
            except Exception as exc:
                failed_blocks.append(block_name)
                parent_child_rows.append(
                    {
                        "model": parent.model_name,
                        "model_family": parent.model_family,
                        "fs_stage": parent.fs_level,
                        "feature_family": block_name,
                        "scheme_name": preflight["scheme_payload"]["scheme_name"],
                        "scheme_version": preflight["scheme_payload"]["scheme_version"],
                        "layer_name": preflight["scheme_payload"]["layer_name"],
                        "stage_name": preflight["scheme_payload"]["stage_name"],
                        "target_block": target_block or "",
                        "scheme_hash": preflight["scheme_payload"]["scheme_hash"],
                        "feature_taxonomy_hash": preflight["scheme_payload"]["feature_taxonomy_hash"],
                        "parent_run_id": parent.run_id,
                        "parent_run_label": parent.run_label,
                        "child_run_id": child_run_id,
                        "child_run_label": child_run_label,
                        "child_run_dir": "",
                        "aggregate_run_id": aggregate_run_id,
                        "aggregate_run_label": aggregate_run_label,
                        "comparison_type": "grouped_ablation",
                        "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                        "comparison_unit_name": "ablation_block",
                        "child_status": "artifact_incomplete",
                        "status": "partial",
                        "smoke_test": bool(args.smoke_test),
                        "error_message": str(exc),
                    }
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

        aggregate_status = "partial" if failed_blocks else ("smoke_test" if args.smoke_test else "complete")
        metadata.update(
            {
                "aggregate_status": aggregate_status,
                "run_completeness_status": aggregate_status,
                "execution_status": "success" if not failed_blocks else "partial",
            }
        )
        _write_scheme_aggregate_artifacts(
            aggregate_run_dir=aggregate_run_dir,
            by_origin=feature_value_by_origin,
            by_reporting_level=feature_value_by_reporting_level,
            summary=feature_value_summary,
            parent_child_map=feature_value_parent_child_map,
            metadata=metadata,
            run_summary_payload={
                "run_id": aggregate_run_id,
                "run_label": aggregate_run_label,
                "run_role": "feature_family_ablation_aggregate",
                "model": parent.model_name,
                "model_family": parent.model_family,
                "fs_stage": parent.fs_level,
                "parent_run_id": parent.run_id,
                "parent_run_label": parent.run_label,
                "feature_families": block_names,
                "child_run_ids": [row["child_run_id"] for row in parent_child_rows if row.get("child_run_id")],
                "smoke_test": bool(args.smoke_test),
                "aggregate_status": aggregate_status,
                "execution_status": "success" if not failed_blocks else "partial",
                "completed_child_count": int(
                    sum(1 for row in parent_child_rows if row.get("child_status") in {"complete", "reused_complete"})
                ),
                "expected_child_count": len(block_names),
                "failed_child_family_codes": failed_blocks,
                "scheme_name": preflight["scheme_payload"]["scheme_name"],
                "scheme_version": preflight["scheme_payload"]["scheme_version"],
                "layer_name": preflight["scheme_payload"]["layer_name"],
                "stage_name": preflight["scheme_payload"]["stage_name"],
                "target_block": target_block or "",
                "scheme_hash": preflight["scheme_payload"]["scheme_hash"],
                "feature_taxonomy_hash": preflight["scheme_payload"]["feature_taxonomy_hash"],
            },
            preflight_summary=preflight["summary"],
            preflight_assignments=preflight["assignments"],
            preflight_block_sizes=preflight["block_sizes"],
        )
        print(
            f"Completed {args.fs_level} {args.model_family} staged ablation: "
            f"parent={parent.run_id}, aggregate={aggregate_run_id}, blocks={len(block_names)}, status={aggregate_status}"
        )


if __name__ == "__main__":
    main()
