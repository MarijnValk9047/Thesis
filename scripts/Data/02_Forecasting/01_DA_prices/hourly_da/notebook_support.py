from __future__ import annotations

import base64
import math
import time
from datetime import timedelta
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
from IPython.display import HTML
from matplotlib import colors
from matplotlib import dates as mdates
from matplotlib import pyplot as plt

from .core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    aggregate_run_label_for_scheme,
    fs2_block_map_from_feature_columns,
    fs3_block_map_from_feature_columns,
    supported_fs2_layer2_target_blocks,
)
from .core.config import HourlyDAPipelineConfig
from .core.feature_value import (
    build_fs2_ablation_preflight,
    build_fs3_ablation_preflight,
    instantiate_model_from_parent_context,
    resolve_parent_stage_run,
)
from .core.metrics import add_error_columns
from .core.pipeline import prepare_data_bundle
from .core.reporting import find_latest_run, load_csv, load_json, reporting_level_specs, resolve_tabular_path
from .core.schedule import build_target_schedule_for_origin, generate_forecast_origins
from .core.external_features import build_feature_context_for_origin, load_external_feature_store
from .core.visual_weeks import (
    build_stitched_day_ahead_predictions,
    build_week_winner_summary,
    filter_week_window,
    summarize_week_metrics,
)


def apply_notebook_display_defaults(
    *,
    max_columns: int | None = 200,
    width: int | None = 220,
) -> None:
    pd.set_option("display.max_columns", max_columns)
    pd.set_option("display.max_colwidth", None)
    pd.set_option("display.width", width)
    pd.set_option("display.expand_frame_repr", False)


def format_duration(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "unknown"
    total_seconds = int(round(float(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def estimate_run_duration_seconds(output_root: Path, run_label: str) -> dict[str, object] | None:
    try:
        run_dir = find_latest_run(output_root, run_label)
    except FileNotFoundError:
        return None

    timing_summary_path = run_dir / "origin_timing_summary.csv"
    if not timing_summary_path.exists():
        return None

    timing_summary = pd.read_csv(timing_summary_path)
    required_cols = {"origins", "fit_time_mean_sec", "predict_time_mean_sec"}
    if timing_summary.empty or not required_cols.issubset(timing_summary.columns):
        return None

    estimate_seconds = float(
        (
            timing_summary["origins"].astype(float)
            * (timing_summary["fit_time_mean_sec"].astype(float) + timing_summary["predict_time_mean_sec"].astype(float))
        ).sum()
    )
    return {
        "run_dir": run_dir,
        "run_id": run_dir.name,
        "estimate_seconds": estimate_seconds,
    }


def run_suite_with_feedback(
    config: HourlyDAPipelineConfig,
    run_label: str,
    models: list,
    include_external_features: bool = False,
    show_progress: bool = True,
    progress_label: str | None = None,
    origin_schedule_by_split: dict[str, pd.DataFrame] | None = None,
) -> dict[str, object]:
    from .core.pipeline import run_benchmark_suite

    estimate = estimate_run_duration_seconds(config.output_root, run_label)
    if estimate is not None:
        print(
            f"Heavy rerun warning: '{run_label}' uses the shared rolling-origin benchmark pipeline. "
            f"Latest comparable run {estimate['run_id']} took about {format_duration(float(estimate['estimate_seconds']))}."
        )
    else:
        print(f"Heavy rerun warning: '{run_label}' uses the shared rolling-origin benchmark pipeline and may take a while.")

    started = time.perf_counter()
    run_id, overall_metrics, lead_day_metrics, timing_summary, official_naive = run_benchmark_suite(
        config=config,
        run_label=run_label,
        models=models,
        include_external_features=include_external_features,
        show_progress=show_progress,
        progress_label=progress_label or run_label,
        origin_schedule_by_split=origin_schedule_by_split,
    )
    elapsed_seconds = time.perf_counter() - started
    print(f"Run completed: {run_id}")
    print(f"Actual wall-clock time: {format_duration(elapsed_seconds)}")
    if estimate is not None:
        delta = elapsed_seconds - float(estimate["estimate_seconds"])
        print(f"Estimate delta versus latest comparable run: {delta:+.1f}s")

    return {
        "run_id": run_id,
        "run_dir": config.output_root / "runs" / run_id,
        "elapsed_seconds": elapsed_seconds,
        "estimate": estimate,
        "overall_metrics": overall_metrics,
        "lead_day_metrics": lead_day_metrics,
        "timing_summary": timing_summary,
        "official_naive": official_naive,
    }


def load_selected_case_weeks(output_root: Path, run_label: str = "case_week_selection") -> tuple[Path, pd.DataFrame]:
    run_dir = find_latest_run(output_root, run_label)
    return run_dir, load_csv(run_dir, "selected_weeks.csv")


FEATURE_FAMILY_ABLATION_CONTEXT_SPECS: tuple[dict[str, object], ...] = (
    {
        "context_order": 0,
        "parent_context": "LEAR FS1",
        "model": "lear_fs1",
        "model_family": "lear",
        "fs_stage": "FS1",
        "parent_run_label": "lear_fs1_benchmark",
    },
    {
        "context_order": 1,
        "parent_context": "XGBoost FS1",
        "model": "xgboost_fs1",
        "model_family": "xgboost",
        "fs_stage": "FS1",
        "parent_run_label": "xgboost_fs1_benchmark",
    },
    {
        "context_order": 2,
        "parent_context": "LEAR FS2",
        "model": "lear_fs2",
        "model_family": "lear",
        "fs_stage": "FS2",
        "parent_run_label": "lear_fs2_benchmark",
    },
    {
        "context_order": 3,
        "parent_context": "XGBoost FS2",
        "model": "xgboost_fs2",
        "model_family": "xgboost",
        "fs_stage": "FS2",
        "parent_run_label": "xgboost_fs2_benchmark",
    },
    {
        "context_order": 4,
        "parent_context": "Prophet FS2",
        "model": "prophet_fs2",
        "model_family": "prophet",
        "fs_stage": "FS2",
        "parent_run_label": "prophet_benchmark",
    },
)

FEATURE_FAMILY_ABLATION_REQUIRED_FILES: tuple[str, ...] = (
    "feature_family_value_summary.csv",
    "feature_family_value_by_origin.csv",
    "feature_family_value_by_reporting_level.csv",
    "feature_family_value_metadata.json",
    "feature_family_parent_child_map.csv",
    "run_summary.json",
)

FS3_SCHEME_ABLATION_REQUIRED_FILES: tuple[str, ...] = (
    *FEATURE_FAMILY_ABLATION_REQUIRED_FILES,
    "ablation_preflight_summary.csv",
    "ablation_preflight_assignments.csv",
    "ablation_preflight_block_sizes.csv",
)


def feature_family_reporting_context_frame() -> pd.DataFrame:
    return pd.DataFrame(FEATURE_FAMILY_ABLATION_CONTEXT_SPECS).copy()


def _feature_family_dynamic_context_spec(
    *,
    parent_run_label: str,
    metadata: dict[str, object] | None,
    context_order: int,
) -> dict[str, object]:
    metadata = metadata or {}
    model_family = str(metadata.get("model_family", ""))
    fs_stage = str(metadata.get("fs_stage", metadata.get("stage", "")))
    model_name = str(metadata.get("model", f"{model_family}_{str(fs_stage).lower()}")).strip("_")
    parent_context = str(metadata.get("parent_context_label") or parent_run_label)
    return {
        "context_order": int(context_order),
        "parent_context": parent_context,
        "model": model_name,
        "model_family": model_family,
        "fs_stage": fs_stage,
        "parent_run_label": str(parent_run_label),
    }


def _feature_family_context_frame_with_dynamic(output_root: Path) -> pd.DataFrame:
    base = feature_family_reporting_context_frame()
    known_labels = set(base["parent_run_label"].astype(str)) if not base.empty else set()
    dynamic_specs: list[dict[str, object]] = []
    next_order = int(base["context_order"].max()) + 1 if not base.empty else 0
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        return base

    aggregate_run_labels = sorted(
        {
            _run_label_from_run_dir_name_local(candidate.name)
            for candidate in run_root.iterdir()
            if candidate.is_dir() and _run_label_from_run_dir_name_local(candidate.name).startswith("feature_family_ablation__")
        }
    )
    for aggregate_run_label in aggregate_run_labels:
        parent_run_label = str(aggregate_run_label).removeprefix("feature_family_ablation__")
        if parent_run_label in known_labels:
            continue
        latest_complete = find_latest_complete_run(
            output_root=output_root,
            run_label=aggregate_run_label,
            required_files=FEATURE_FAMILY_ABLATION_REQUIRED_FILES,
        )
        metadata = None
        if latest_complete is not None:
            metadata = load_json(latest_complete, "feature_family_value_metadata.json")
        dynamic_specs.append(
            _feature_family_dynamic_context_spec(
                parent_run_label=parent_run_label,
                metadata=metadata,
                context_order=next_order,
            )
        )
        next_order += 1

    if not dynamic_specs:
        return base
    return pd.concat([base, pd.DataFrame(dynamic_specs)], ignore_index=True)


def _run_label_from_run_dir_name_local(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _parse_run_timestamp(run_id: str) -> pd.Timestamp | pd.NaT:
    text = str(run_id)
    parts = text.split("_", 2)
    if len(parts) < 2:
        return pd.NaT
    try:
        return pd.to_datetime(f"{parts[0]}_{parts[1]}", format="%Y%m%d_%H%M%S", errors="raise")
    except Exception:
        return pd.NaT


def _matching_run_dirs(output_root: Path, run_label: str) -> list[Path]:
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        return []
    return sorted(
        [
            candidate
            for candidate in run_root.iterdir()
            if candidate.is_dir() and _run_label_from_run_dir_name_local(candidate.name) == str(run_label)
        ]
    )


def _run_dir_has_required_files(run_dir: Path, required_files: tuple[str, ...]) -> bool:
    return all((run_dir / filename).exists() for filename in required_files)


def find_latest_complete_run(
    output_root: Path,
    run_label: str,
    required_files: tuple[str, ...],
) -> Path | None:
    candidates = _matching_run_dirs(output_root, run_label)
    for candidate in reversed(candidates):
        if _run_dir_has_required_files(candidate, required_files):
            return candidate
    return None


def find_latest_complete_feature_family_ablation_run(output_root: Path, parent_run_label: str) -> Path | None:
    return find_latest_complete_run(
        output_root=output_root,
        run_label=f"feature_family_ablation__{parent_run_label}",
        required_files=FEATURE_FAMILY_ABLATION_REQUIRED_FILES,
    )


def summarize_feature_family_ablation_availability(output_root: Path) -> pd.DataFrame:
    context_frame = _feature_family_context_frame_with_dynamic(output_root)
    rows: list[dict[str, object]] = []

    for context in context_frame.to_dict(orient="records"):
        parent_run_label = str(context["parent_run_label"])
        aggregate_run_label = f"feature_family_ablation__{parent_run_label}"
        candidates = _matching_run_dirs(output_root, aggregate_run_label)
        latest_candidate = candidates[-1] if candidates else None
        latest_complete = find_latest_complete_feature_family_ablation_run(output_root, parent_run_label)

        latest_reference = latest_complete or latest_candidate
        latest_run_id = str(latest_reference.name) if latest_reference is not None else ""
        latest_timestamp = _parse_run_timestamp(latest_run_id)

        availability_status = "missing"
        status_note = "No saved aggregate ablation run was found for this parent context."
        run_id = ""
        run_label = ""
        smoke_test = False
        feature_family_count = 0
        feature_families = ""

        if latest_complete is not None:
            metadata = load_json(latest_complete, "feature_family_value_metadata.json")
            selected_families = [str(value) for value in metadata.get("selected_feature_families", [])]
            run_id = str(metadata.get("run_id", latest_complete.name))
            run_label = str(metadata.get("run_label", aggregate_run_label))
            smoke_test = bool(metadata.get("smoke_test", False))
            feature_family_count = int(len(selected_families))
            feature_families = ", ".join(selected_families)
            availability_status = "available"
            status_note = "Latest complete aggregate ablation run is ready for reporting."
            if latest_candidate is not None and latest_candidate != latest_complete:
                status_note = (
                    f"Using latest complete run {latest_complete.name}; "
                    f"newer incomplete folder {latest_candidate.name} was ignored."
                )
        elif latest_candidate is not None:
            availability_status = "incomplete"
            run_id = str(latest_candidate.name)
            run_label = aggregate_run_label
            status_note = "A matching ablation folder exists, but the required aggregate artifact set is incomplete."

        rows.append(
            {
                "context_order": int(context["context_order"]),
                "parent_context": str(context["parent_context"]),
                "model": str(context["model"]),
                "model_family": str(context["model_family"]),
                "fs_stage": str(context["fs_stage"]),
                "parent_run_label": parent_run_label,
                "aggregate_run_label": aggregate_run_label,
                "run_id": run_id,
                "run_label": run_label,
                "latest_timestamp": latest_timestamp,
                "availability_status": availability_status,
                "smoke_test": smoke_test,
                "feature_family_count": feature_family_count,
                "feature_families": feature_families,
                "status_note": status_note,
            }
        )

    availability = pd.DataFrame(rows).sort_values(["context_order", "parent_context"]).reset_index(drop=True)
    if not availability.empty:
        availability["latest_timestamp_label"] = availability["latest_timestamp"].apply(
            lambda value: "-" if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        )
    return availability


def _normalize_feature_family_frame(
    frame: pd.DataFrame,
    *,
    metadata: dict[str, object],
    context_spec: dict[str, object],
) -> pd.DataFrame:
    normalized = frame.copy()
    if normalized.empty:
        return normalized

    if "split" in normalized.columns and "dataset_split" not in normalized.columns:
        normalized["dataset_split"] = normalized["split"].astype(str)
    if "fs_stage" in normalized.columns and "fs_level" not in normalized.columns:
        normalized["fs_level"] = normalized["fs_stage"].astype(str)
    elif "fs_level" not in normalized.columns:
        normalized["fs_level"] = str(metadata.get("fs_stage", context_spec["fs_stage"]))
    if "fs_stage" not in normalized.columns:
        normalized["fs_stage"] = str(metadata.get("fs_stage", context_spec["fs_stage"]))

    normalized["parent_context"] = str(context_spec["parent_context"])
    normalized["context_order"] = int(context_spec["context_order"])
    normalized["aggregate_run_id"] = str(metadata.get("run_id", ""))
    normalized["aggregate_run_label"] = str(metadata.get("run_label", ""))
    normalized["smoke_test"] = bool(metadata.get("smoke_test", False))
    normalized["run_timestamp"] = _parse_run_timestamp(str(metadata.get("run_id", "")))
    return normalized


def load_feature_family_ablation_bundle(output_root: Path, parent_run_label: str) -> dict[str, object] | None:
    context_frame = _feature_family_context_frame_with_dynamic(output_root)
    context_match = context_frame[context_frame["parent_run_label"] == str(parent_run_label)].copy()
    run_dir = find_latest_complete_feature_family_ablation_run(output_root, parent_run_label)
    if run_dir is None:
        return None

    metadata = load_json(run_dir, "feature_family_value_metadata.json")
    if context_match.empty:
        context_spec = _feature_family_dynamic_context_spec(
            parent_run_label=str(parent_run_label),
            metadata=metadata,
            context_order=int(context_frame["context_order"].max()) + 1 if not context_frame.empty else 0,
        )
    else:
        context_spec = context_match.iloc[0].to_dict()
    summary = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_summary.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    by_origin = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_by_origin.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    by_reporting_level = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_by_reporting_level.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    parent_child_map = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_parent_child_map.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    run_summary = load_json(run_dir, "run_summary.json")

    return {
        "context_spec": context_spec,
        "context_label": str(context_spec["parent_context"]),
        "run_dir": run_dir,
        "metadata": metadata,
        "run_summary": run_summary,
        "summary": summary,
        "by_origin": by_origin,
        "by_reporting_level": by_reporting_level,
        "parent_child_map": parent_child_map,
    }


def load_feature_family_ablation_report_dataset(output_root: Path) -> dict[str, object]:
    availability = summarize_feature_family_ablation_availability(output_root)
    available = availability[availability["availability_status"] == "available"].copy()

    bundles: list[dict[str, object]] = []
    for parent_run_label in available["parent_run_label"].astype(str).tolist():
        bundle = load_feature_family_ablation_bundle(output_root, parent_run_label)
        if bundle is not None:
            bundles.append(bundle)

    artifact_names = ("summary", "by_origin", "by_reporting_level", "parent_child_map")
    combined = {
        artifact_name: (
            pd.concat([bundle[artifact_name] for bundle in bundles], ignore_index=True)
            if bundles
            else pd.DataFrame()
        )
        for artifact_name in artifact_names
    }

    return {
        "availability": availability,
        "available_contexts": available.reset_index(drop=True),
        "bundles": bundles,
        **combined,
    }


def _infer_model_family_from_parent_run_label(parent_run_label: str) -> str:
    label = str(parent_run_label)
    if label.startswith("lear_") or "_lear_" in label:
        return "lear"
    if label.startswith("xgboost_") or "_xgboost_" in label:
        return "xgboost"
    raise ValueError(f"Could not infer model family from parent run label: {parent_run_label}")


def _current_staged_scheme_descriptor(
    config: HourlyDAPipelineConfig,
    *,
    fs_level: str,
    parent_run_label: str,
    model_family: str,
    scheme_name: str,
    target_block: str | None = None,
    store=None,
) -> dict[str, object]:
    parent = resolve_parent_stage_run(
        config,
        model_family=model_family,
        fs_level=fs_level,
        parent_run_label=parent_run_label,
    )
    model = instantiate_model_from_parent_context(parent)
    if str(fs_level) == "FS2":
        preflight = build_fs2_ablation_preflight(
            config=config,
            model=model,
            scheme_name=scheme_name,
            target_block=target_block,
        )
    elif str(fs_level) == "FS3":
        active_store = store if store is not None else load_external_feature_store(config)
        preflight = build_fs3_ablation_preflight(
            config=config,
            model=model,
            experiment_map=active_store.experiment_map(),
            scheme_name=scheme_name,
            target_block=target_block,
        )
    else:
        raise ValueError(f"Unsupported staged ablation fs_level: {fs_level}")
    return {
        "parent": parent,
        "model": model,
        "preflight": preflight,
        "aggregate_run_label": aggregate_run_label_for_scheme(
            parent_run_label=parent_run_label,
            scheme_name=scheme_name,
            scheme_version=str(preflight["scheme_payload"]["scheme_version"]),
            target_block=target_block,
        ),
    }


def _summarize_staged_ablation_availability(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    fs_level: str,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> pd.DataFrame:
    store = load_external_feature_store(config) if str(fs_level) == "FS3" else None
    rows: list[dict[str, object]] = []

    for parent_spec in parent_specs:
        parent_run_label = str(parent_spec["parent_run_label"])
        model_family = str(parent_spec.get("model_family") or _infer_model_family_from_parent_run_label(parent_run_label))
        model_label = str(parent_spec.get("model_label") or model_family.title())
        for request in scheme_requests:
            scheme_name = str(request["scheme_name"])
            target_block = str(request["target_block"]) if request.get("target_block") else None
            availability_status = "missing"
            status_note = "No saved aggregate run was found for this parent and scheme."
            run_id = ""
            run_label = ""
            latest_timestamp = pd.NaT
            aggregate_run_label = ""
            expected_scheme_hash = ""
            expected_feature_taxonomy_hash = ""
            expected_layer_name = ""
            try:
                descriptor = _current_staged_scheme_descriptor(
                    config,
                    fs_level=fs_level,
                    parent_run_label=parent_run_label,
                    model_family=model_family,
                    scheme_name=scheme_name,
                    target_block=target_block,
                    store=store,
                )
                aggregate_run_label = str(descriptor["aggregate_run_label"])
                expected_scheme_hash = str(descriptor["preflight"]["scheme_payload"]["scheme_hash"])
                expected_feature_taxonomy_hash = str(descriptor["preflight"]["scheme_payload"]["feature_taxonomy_hash"])
                expected_layer_name = str(descriptor["preflight"]["scheme_payload"]["layer_name"])
            except Exception as exc:
                availability_status = "incompatible_parent"
                status_note = str(exc)
                rows.append(
                    {
                        "parent_run_label": parent_run_label,
                        "model_family": model_family,
                        "model_label": model_label,
                        "scheme_name": scheme_name,
                        "layer_name": expected_layer_name,
                        "target_block": target_block or "",
                        "aggregate_run_label": aggregate_run_label,
                        "run_id": run_id,
                        "run_label": run_label,
                        "latest_timestamp": latest_timestamp,
                        "availability_status": availability_status,
                        "status_note": status_note,
                        "expected_scheme_hash": expected_scheme_hash,
                        "expected_feature_taxonomy_hash": expected_feature_taxonomy_hash,
                    }
                )
                continue

            candidates = _matching_run_dirs(output_root, aggregate_run_label)
            latest_candidate = candidates[-1] if candidates else None
            latest_complete = find_latest_complete_run(
                output_root,
                aggregate_run_label,
                FS3_SCHEME_ABLATION_REQUIRED_FILES,
            )
            latest_reference = latest_complete or latest_candidate
            if latest_reference is not None:
                latest_timestamp = _parse_run_timestamp(str(latest_reference.name))
                run_id = str(latest_reference.name)
                run_label = aggregate_run_label

            if latest_complete is None and latest_candidate is not None:
                availability_status = "incomplete"
                status_note = "A matching aggregate folder exists, but the required artifact set is incomplete."
            elif latest_complete is not None:
                metadata = load_json(latest_complete, "feature_family_value_metadata.json")
                stored_scheme_hash = str(metadata.get("scheme_hash", ""))
                stored_feature_taxonomy_hash = str(metadata.get("feature_taxonomy_hash", ""))
                preflight_valid = bool(metadata.get("preflight_valid", False))
                aggregate_status = str(metadata.get("aggregate_status", ""))
                if not stored_scheme_hash or not stored_feature_taxonomy_hash:
                    availability_status = "legacy_incompatible"
                    status_note = "Saved run is missing current scheme/taxonomy metadata and is treated as legacy only."
                elif stored_scheme_hash != expected_scheme_hash or stored_feature_taxonomy_hash != expected_feature_taxonomy_hash:
                    availability_status = "legacy_incompatible"
                    status_note = (
                        "Saved run exists, but its scheme or taxonomy hash no longer matches the current staged workflow."
                    )
                elif not preflight_valid or aggregate_status == "invalid":
                    availability_status = "invalid"
                    status_note = "Saved aggregate exists, but its stored preflight marked the block assignment invalid."
                else:
                    availability_status = "available"
                    status_note = "Latest complete run is compatible with the current staged block scheme."

            rows.append(
                {
                    "parent_run_label": parent_run_label,
                    "model_family": model_family,
                    "model_label": model_label,
                    "scheme_name": scheme_name,
                    "layer_name": expected_layer_name,
                    "target_block": target_block or "",
                    "aggregate_run_label": aggregate_run_label,
                    "run_id": run_id,
                    "run_label": run_label,
                    "latest_timestamp": latest_timestamp,
                    "availability_status": availability_status,
                    "status_note": status_note,
                    "expected_scheme_hash": expected_scheme_hash,
                    "expected_feature_taxonomy_hash": expected_feature_taxonomy_hash,
                }
            )

    availability = pd.DataFrame(rows)
    if availability.empty:
        return availability
    availability = availability.sort_values(
        ["model_family", "scheme_name", "target_block", "parent_run_label"]
    ).reset_index(drop=True)
    availability["latest_timestamp_label"] = availability["latest_timestamp"].apply(
        lambda value: "-" if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    )
    return availability


def summarize_fs2_ablation_availability(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> pd.DataFrame:
    return _summarize_staged_ablation_availability(
        output_root,
        config,
        fs_level="FS2",
        parent_specs=parent_specs,
        scheme_requests=scheme_requests,
    )


def summarize_fs3_ablation_availability(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> pd.DataFrame:
    return _summarize_staged_ablation_availability(
        output_root,
        config,
        fs_level="FS3",
        parent_specs=parent_specs,
        scheme_requests=scheme_requests,
    )


def _load_staged_ablation_bundle(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    fs_level: str,
    parent_run_label: str,
    model_family: str | None = None,
    scheme_name: str,
    target_block: str | None = None,
    store=None,
) -> dict[str, object] | None:
    resolved_family = str(model_family or _infer_model_family_from_parent_run_label(parent_run_label))
    descriptor = _current_staged_scheme_descriptor(
        config,
        fs_level=fs_level,
        parent_run_label=parent_run_label,
        model_family=resolved_family,
        scheme_name=scheme_name,
        target_block=target_block,
        store=store,
    )
    aggregate_run_label = str(descriptor["aggregate_run_label"])
    run_dir = find_latest_complete_run(output_root, aggregate_run_label, FS3_SCHEME_ABLATION_REQUIRED_FILES)
    if run_dir is None:
        return None

    metadata = load_json(run_dir, "feature_family_value_metadata.json")
    if (
        str(metadata.get("scheme_hash", "")) != str(descriptor["preflight"]["scheme_payload"]["scheme_hash"])
        or str(metadata.get("feature_taxonomy_hash", "")) != str(descriptor["preflight"]["scheme_payload"]["feature_taxonomy_hash"])
        or not bool(metadata.get("preflight_valid", False))
    ):
        return None

    context_spec = {
        "parent_context": str(metadata.get("parent_context_label") or parent_run_label),
        "context_order": 0,
        "fs_stage": str(fs_level),
    }
    summary = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_summary.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    by_origin = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_by_origin.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    by_reporting_level = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_value_by_reporting_level.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    parent_child_map = _normalize_feature_family_frame(
        load_csv(run_dir, "feature_family_parent_child_map.csv"),
        metadata=metadata,
        context_spec=context_spec,
    )
    preflight_summary = load_csv(run_dir, "ablation_preflight_summary.csv")
    preflight_assignments = load_csv(run_dir, "ablation_preflight_assignments.csv")
    preflight_block_sizes = load_csv(run_dir, "ablation_preflight_block_sizes.csv")
    run_summary = load_json(run_dir, "run_summary.json")
    return {
        "context_label": str(context_spec["parent_context"]),
        "run_dir": run_dir,
        "metadata": metadata,
        "run_summary": run_summary,
        "summary": summary,
        "by_origin": by_origin,
        "by_reporting_level": by_reporting_level,
        "parent_child_map": parent_child_map,
        "preflight_summary": preflight_summary,
        "preflight_assignments": preflight_assignments,
        "preflight_block_sizes": preflight_block_sizes,
        "current_scheme": descriptor["preflight"]["scheme_payload"],
    }


def load_fs2_ablation_bundle(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_run_label: str,
    model_family: str | None = None,
    scheme_name: str,
    target_block: str | None = None,
    store=None,
) -> dict[str, object] | None:
    return _load_staged_ablation_bundle(
        output_root,
        config,
        fs_level="FS2",
        parent_run_label=parent_run_label,
        model_family=model_family,
        scheme_name=scheme_name,
        target_block=target_block,
        store=None,
    )


def load_fs3_ablation_bundle(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_run_label: str,
    model_family: str | None = None,
    scheme_name: str,
    target_block: str | None = None,
    store=None,
) -> dict[str, object] | None:
    return _load_staged_ablation_bundle(
        output_root,
        config,
        fs_level="FS3",
        parent_run_label=parent_run_label,
        model_family=model_family,
        scheme_name=scheme_name,
        target_block=target_block,
        store=store,
    )


def _load_staged_ablation_report_dataset(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    fs_level: str,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> dict[str, object]:
    availability = _summarize_staged_ablation_availability(
        output_root,
        config,
        fs_level=fs_level,
        parent_specs=parent_specs,
        scheme_requests=scheme_requests,
    )
    store = load_external_feature_store(config) if str(fs_level) == "FS3" else None
    bundles: list[dict[str, object]] = []
    for row in availability[availability["availability_status"] == "available"].to_dict(orient="records"):
        bundle = _load_staged_ablation_bundle(
            output_root,
            config,
            fs_level=fs_level,
            parent_run_label=str(row["parent_run_label"]),
            model_family=str(row["model_family"]),
            scheme_name=str(row["scheme_name"]),
            target_block=str(row["target_block"]) or None,
            store=store,
        )
        if bundle is not None:
            bundles.append(bundle)

    artifact_names = ("summary", "by_origin", "by_reporting_level", "parent_child_map")
    combined = {
        artifact_name: (
            pd.concat([bundle[artifact_name] for bundle in bundles], ignore_index=True)
            if bundles
            else pd.DataFrame()
        )
        for artifact_name in artifact_names
    }
    return {
        "availability": availability,
        "bundles": bundles,
        **combined,
    }


def load_fs2_ablation_report_dataset(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> dict[str, object]:
    return _load_staged_ablation_report_dataset(
        output_root,
        config,
        fs_level="FS2",
        parent_specs=parent_specs,
        scheme_requests=scheme_requests,
    )


def load_fs3_ablation_report_dataset(
    output_root: Path,
    config: HourlyDAPipelineConfig,
    *,
    parent_specs: list[dict[str, str]],
    scheme_requests: list[dict[str, str | None]],
) -> dict[str, object]:
    return _load_staged_ablation_report_dataset(
        output_root,
        config,
        fs_level="FS3",
        parent_specs=parent_specs,
        scheme_requests=scheme_requests,
    )


def _feature_family_interpretation_flag(relative_delta: float | int | None, metric: str) -> str:
    if relative_delta is None or pd.isna(relative_delta):
        return "insufficient data"
    if str(metric) == "bias":
        return "bias-specific: interpret the sign and absolute size carefully"

    value = float(relative_delta)
    if value >= 0.05:
        return "strong loss when removed"
    if value >= 0.01:
        return "modest loss when removed"
    if value <= -0.05:
        return "improved when removed"
    if abs(value) < 0.01:
        return "weak effect"
    return "small mixed effect"


def classify_ablation_relative_delta(relative_delta: float | int | None) -> str:
    if relative_delta is None or pd.isna(relative_delta):
        return "insufficient_data"
    value = float(relative_delta)
    if value >= 0.01:
        return "strong_helpful"
    if value >= 0.0025:
        return "mild_helpful"
    if value <= -0.01:
        return "strong_harmful"
    if value <= -0.0025:
        return "mild_harmful"
    return "near_zero_uncertain"


def ablation_effect_label(effect_bucket: str) -> str:
    labels = {
        "strong_helpful": "Strong helpful",
        "mild_helpful": "Mild helpful",
        "near_zero_uncertain": "Near-zero / uncertain",
        "mild_harmful": "Mild harmful",
        "strong_harmful": "Strong harmful",
        "insufficient_data": "Insufficient data",
        "robustly_helpful_across_models": "Robustly helpful across both models",
        "robustly_harmful_across_models": "Robustly harmful across both models",
        "model_dependent_unstable": "Model-dependent / unstable",
        "requires_more_investigation": "Requires more investigation",
    }
    return labels.get(str(effect_bucket), str(effect_bucket).replace("_", " ").title())


def annotate_ablation_metric_slice(metric_slice: pd.DataFrame) -> pd.DataFrame:
    if metric_slice.empty:
        return metric_slice.copy()
    annotated = metric_slice.copy()
    annotated["effect_bucket"] = annotated["relative_delta"].apply(classify_ablation_relative_delta)
    annotated["effect_label"] = annotated["effect_bucket"].map(ablation_effect_label)
    return annotated


def summarize_ablation_cross_model(metric_slice: pd.DataFrame) -> pd.DataFrame:
    if metric_slice.empty:
        return pd.DataFrame()
    annotated = annotate_ablation_metric_slice(metric_slice)
    rows: list[dict[str, object]] = []
    for feature_family, group in annotated.groupby("feature_family", dropna=False):
        model_rows = group.sort_values(["model_family", "model"])
        relative_deltas = model_rows["relative_delta"].astype(float).tolist()
        models = model_rows["model_family"].astype(str).tolist()
        if len(relative_deltas) >= 2 and all(value >= 0.01 for value in relative_deltas):
            combined_bucket = "robustly_helpful_across_models"
        elif len(relative_deltas) >= 2 and all(value <= -0.01 for value in relative_deltas):
            combined_bucket = "robustly_harmful_across_models"
        elif relative_deltas and all(abs(value) < 0.0025 for value in relative_deltas):
            combined_bucket = "near_zero_uncertain"
        elif relative_deltas and min(relative_deltas) < 0.0 < max(relative_deltas):
            combined_bucket = "model_dependent_unstable"
        else:
            combined_bucket = "requires_more_investigation"
        rows.append(
            {
                "feature_family": str(feature_family),
                "models_available": ", ".join(models),
                "model_count": int(group["model_family"].astype(str).nunique()),
                "mean_delta": float(group["delta"].mean()),
                "mean_relative_delta": float(group["relative_delta"].mean()),
                "combined_bucket": combined_bucket,
                "combined_label": ablation_effect_label(combined_bucket),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["combined_label", "mean_relative_delta", "feature_family"], ascending=[True, False, True])
        .reset_index(drop=True)
    )


def select_feature_family_metric_slice(
    summary_frame: pd.DataFrame,
    *,
    split: str = "validation",
    reporting_level: str = "stitched_all_horizon",
    metric: str = "mae",
) -> pd.DataFrame:
    if summary_frame.empty:
        return pd.DataFrame()

    selected = summary_frame.copy()
    selected = selected[selected["dataset_split"].astype(str) == str(split)].copy()
    selected = selected[selected["reporting_level"].astype(str) == str(reporting_level)].copy()
    selected = selected[selected["metric"].astype(str) == str(metric)].copy()
    if selected.empty:
        return pd.DataFrame()

    selected["interpretation_flag"] = selected["relative_delta"].apply(
        lambda value: _feature_family_interpretation_flag(value, metric=str(metric))
    )
    selected["removal_hurt"] = selected["delta"].astype(float) > 0.0
    selected["removal_helped"] = selected["delta"].astype(float) < 0.0
    selected = selected.sort_values(
        ["context_order", "delta", "feature_family"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return selected


def summarize_feature_family_cross_context(
    summary_frame: pd.DataFrame,
    *,
    split: str = "validation",
    reporting_level: str = "stitched_all_horizon",
    metric: str = "mae",
) -> pd.DataFrame:
    selected = select_feature_family_metric_slice(
        summary_frame,
        split=split,
        reporting_level=reporting_level,
        metric=metric,
    )
    if selected.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for feature_family, group in selected.groupby("feature_family", dropna=False):
        contexts = group.sort_values(["context_order", "parent_context"])["parent_context"].astype(str).tolist()
        hurt_count = int(group["removal_hurt"].sum())
        help_count = int(group["removal_helped"].sum())
        context_count = int(group.shape[0])
        if context_count == 1:
            stability_note = "Single context only"
        elif hurt_count == context_count:
            stability_note = "Consistently valuable where tested"
        elif help_count == context_count:
            stability_note = "Consistently weak where tested"
        else:
            stability_note = "Model/stage specific pattern"
        if bool(group["smoke_test"].all()):
            stability_note += " (smoke-test evidence only)"

        rows.append(
            {
                "feature_family": str(feature_family),
                "contexts_available": ", ".join(contexts),
                "context_count": context_count,
                "mean_delta": float(group["delta"].mean()),
                "mean_relative_delta": float(group["relative_delta"].mean()),
                "removal_hurt_count": hurt_count,
                "removal_help_count": help_count,
                "smoke_test_context_count": int(group["smoke_test"].astype(bool).sum()),
                "stability_note": stability_note,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["mean_delta", "context_count", "feature_family"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def plot_feature_family_delta_bars(metric_slice: pd.DataFrame) -> plt.Figure | None:
    if metric_slice.empty:
        return None

    context_order = (
        metric_slice[["context_order", "parent_context"]]
        .drop_duplicates()
        .sort_values(["context_order", "parent_context"])
    )
    n_contexts = int(context_order.shape[0])
    fig, axes = _prepare_report_subplot_grid(
        n_contexts,
        1,
        figsize=(10.5, max(3.4 * n_contexts, 4.2)),
        sharex=False,
        sharey=False,
    )
    axes_flat = axes.reshape(-1)

    split_name = str(metric_slice["dataset_split"].iloc[0])
    reporting_label = str(metric_slice["reporting_level_label"].iloc[0])
    metric_name = str(metric_slice["metric"].iloc[0]).upper()

    for axis_index, (_, context_row) in enumerate(context_order.iterrows()):
        ax = axes_flat[axis_index]
        context_name = str(context_row["parent_context"])
        part = metric_slice[metric_slice["parent_context"] == context_name].copy()
        part = part.sort_values(["delta", "feature_family"], ascending=[True, True]).reset_index(drop=True)
        colors_by_bar = ["#c1684b" if float(value) >= 0.0 else "#5c8a63" for value in part["delta"].astype(float)]

        ax.barh(part["feature_family"], part["delta"], color=colors_by_bar, alpha=0.9)
        ax.axvline(0.0, color="#7b8895", linestyle="--", linewidth=1.1)
        x_offset = 0.02 * max(float(part["delta"].abs().max()), 1.0)
        for _, row in part.iterrows():
            delta_value = float(row["delta"])
            ax.text(
                delta_value + (x_offset if delta_value >= 0.0 else -x_offset),
                str(row["feature_family"]),
                f"{delta_value:+.2f}",
                va="center",
                ha="left" if delta_value >= 0.0 else "right",
                fontsize=9,
                color=REPORT_TEXT,
            )
        title_suffix = " (smoke test)" if bool(part["smoke_test"].all()) else ""
        _finish_report_axis(
            ax,
            title=f"{context_name}{title_suffix}",
            xlabel=f"{metric_name} delta (child - parent)",
            ylabel="Feature family",
        )

    fig.suptitle(
        f"Feature-family delta overview: {metric_name} on {split_name.title()} / {reporting_label}",
        x=0.01,
        y=1.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
        color=REPORT_TEXT,
    )
    return fig


def plot_feature_family_heatmap(metric_slice: pd.DataFrame) -> plt.Figure | None:
    if metric_slice.empty:
        return None

    pivot = (
        metric_slice.pivot_table(
            index="parent_context",
            columns="feature_family",
            values="delta",
            aggfunc="first",
        )
        .sort_index()
    )
    if pivot.empty:
        return None

    context_order = (
        metric_slice[["context_order", "parent_context"]]
        .drop_duplicates()
        .sort_values(["context_order", "parent_context"])
    )
    ordered_rows = [value for value in context_order["parent_context"].astype(str).tolist() if value in pivot.index]
    pivot = pivot.reindex(index=ordered_rows)

    values = pivot.to_numpy(dtype=float)
    finite_values = values[np.isfinite(values)]
    if finite_values.size == 0:
        return None

    max_abs = float(np.nanmax(np.abs(finite_values)))
    cmap = colors.LinearSegmentedColormap.from_list(
        "feature_family_delta",
        ["#5c8a63", "#f7f5ef", "#c1684b"],
    )

    fig, ax = _prepare_report_figure((1.6 * max(pivot.shape[1], 3) + 3.0, 1.1 * max(pivot.shape[0], 3) + 2.2))
    image = ax.imshow(values, aspect="auto", cmap=cmap, vmin=-max_abs, vmax=max_abs)
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns.astype(str).tolist(), rotation=35, ha="right")
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index.astype(str).tolist())
    _finish_report_axis(
        ax,
        title="Cross-context heatmap",
        xlabel="Feature family",
        ylabel="Parent context",
    )
    for row_index in range(pivot.shape[0]):
        for col_index in range(pivot.shape[1]):
            value = values[row_index, col_index]
            if np.isfinite(value):
                ax.text(col_index, row_index, f"{float(value):+.2f}", ha="center", va="center", fontsize=9, color=REPORT_TEXT)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86, pad=0.02)
    colorbar.ax.set_ylabel("Delta (child - parent)", color=REPORT_MUTED, fontsize=10)
    colorbar.ax.tick_params(colors=REPORT_MUTED, labelsize=9)
    return fig


def plot_feature_family_origin_stability(
    by_origin_frame: pd.DataFrame,
    *,
    split: str = "validation",
    reporting_level: str = "stitched_all_horizon",
    metric: str = "mae",
) -> plt.Figure | None:
    if by_origin_frame.empty:
        return None

    selected = by_origin_frame.copy()
    selected = selected[selected["dataset_split"].astype(str) == str(split)].copy()
    selected = selected[selected["reporting_level"].astype(str) == str(reporting_level)].copy()
    selected = selected[selected["metric"].astype(str) == str(metric)].copy()
    if selected.empty:
        return None

    counts = (
        selected.groupby(["parent_context", "feature_family"], dropna=False)
        .size()
        .rename("origin_count")
        .reset_index()
    )
    counts = counts[counts["origin_count"] >= 2].copy()
    if counts.empty:
        return None

    selected = selected.merge(counts, on=["parent_context", "feature_family"], how="inner")
    context_order = (
        selected[["context_order", "parent_context"]]
        .drop_duplicates()
        .sort_values(["context_order", "parent_context"])
    )
    fig, axes = _prepare_report_subplot_grid(
        int(context_order.shape[0]),
        1,
        figsize=(10.5, max(3.4 * int(context_order.shape[0]), 4.2)),
        sharex=False,
        sharey=False,
    )
    axes_flat = axes.reshape(-1)

    for axis_index, (_, context_row) in enumerate(context_order.iterrows()):
        ax = axes_flat[axis_index]
        context_name = str(context_row["parent_context"])
        part = selected[selected["parent_context"] == context_name].copy()
        family_order = (
            part.groupby("feature_family", dropna=False)["delta"]
            .median()
            .sort_values(ascending=False)
            .index.astype(str)
            .tolist()
        )
        delta_groups = [
            part[part["feature_family"].astype(str) == family_name]["delta"].astype(float).tolist()
            for family_name in family_order
        ]
        ax.boxplot(
            delta_groups,
            tick_labels=family_order,
            patch_artist=True,
            boxprops={"facecolor": "#dfeaf4", "color": "#7b8895"},
            whiskerprops={"color": "#7b8895"},
            capprops={"color": "#7b8895"},
            medianprops={"color": "#c1684b", "linewidth": 1.4},
        )
        ax.axhline(0.0, color="#7b8895", linestyle="--", linewidth=1.1)
        ax.tick_params(axis="x", rotation=25)
        _finish_report_axis(
            ax,
            title=f"{context_name}",
            xlabel="Feature family",
            ylabel="Delta across origins",
        )

    fig.suptitle(
        f"Origin-level stability: {str(metric).upper()} on {str(split).title()} / {str(reporting_level)}",
        x=0.01,
        y=1.01,
        ha="left",
        fontsize=15,
        fontweight="bold",
        color=REPORT_TEXT,
    )
    return fig


def _representative_origin_row(
    config: HourlyDAPipelineConfig,
    *,
    split_name: str = "validation",
) -> dict[str, object]:
    origins = generate_forecast_origins(config, split_name)
    if origins.empty:
        raise RuntimeError(f"No forecast origins are available for split '{split_name}'.")
    return origins.iloc[-1].to_dict()


def _compute_parent_block_diagnostics(
    config: HourlyDAPipelineConfig,
    *,
    fs_level: str,
    parent_run_label: str,
    model_family: str | None = None,
    split_name: str = "validation",
    scheme_name: str = SCHEME_NAME_LAYER_1,
    store=None,
    prepared_bundle: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_family = str(model_family or _infer_model_family_from_parent_run_label(parent_run_label))
    parent = resolve_parent_stage_run(
        config,
        model_family=resolved_family,
        fs_level=str(fs_level),
        parent_run_label=parent_run_label,
    )
    model = instantiate_model_from_parent_context(parent)
    include_external_features = str(fs_level) == "FS3"
    prepared = prepared_bundle or prepare_data_bundle(config, include_external_features=include_external_features)
    external_store = None
    if include_external_features:
        external_store = prepared.get("external_feature_store")
        if external_store is None:
            external_store = store if store is not None else load_external_feature_store(config)
    origin_row = _representative_origin_row(config, split_name=split_name)
    forecast_origin_utc = pd.Timestamp(origin_row["forecast_origin_utc"])
    delivery_start_local_date = pd.Timestamp(origin_row["delivery_start_local_date"]).date()
    canonical_frame = prepared["canonical_frame"]
    history = canonical_frame[canonical_frame[config.known_at_col] <= forecast_origin_utc].copy()
    target_schedule = build_target_schedule_for_origin(config, delivery_start_local_date)
    target_index_utc = pd.DatetimeIndex(target_schedule["target_timestamp_utc"])
    feature_context = (
        build_feature_context_for_origin(external_store, forecast_origin_utc)
        if external_store is not None
        else None
    )
    model.fit(
        history=history,
        target_index_utc=target_index_utc,
        config=config,
        feature_context=feature_context,
    )

    branch_models = model.branch_models() if hasattr(model, "branch_models") else {"main": model}
    tables: list[dict[str, object]] = []
    for branch_name, branch_model in branch_models.items():
        feature_columns = branch_model.get_feature_columns() if hasattr(branch_model, "get_feature_columns") else []
        if not feature_columns:
            continue
        if str(fs_level) == "FS2":
            block_map = fs2_block_map_from_feature_columns(
                feature_columns,
                scheme_name=scheme_name,
            )
        elif str(fs_level) == "FS3":
            block_map = fs3_block_map_from_feature_columns(
                feature_columns,
                domestic_market=str(config.market_area),
                scheme_name=scheme_name,
            )
        else:
            raise ValueError(f"Unsupported diagnostic fs_level: {fs_level}")
        feature_to_block = {
            column: block_name
            for block_name, columns in block_map.items()
            for column in columns
        }
        if hasattr(branch_model, "coefficient_frame"):
            coefficient_frame = branch_model.coefficient_frame()
            if coefficient_frame.empty:
                continue
            coefficient_frame["block_name"] = coefficient_frame["feature"].map(feature_to_block).fillna("unassigned")
            grouped = (
                coefficient_frame.groupby("block_name", dropna=False)
                .agg(
                    total_features=("feature", "size"),
                    active_nonzero_coefficients=("is_nonzero", "sum"),
                    sum_abs_standardized_coefficient=("abs_coefficient", "sum"),
                )
                .reset_index()
                .sort_values(
                    ["sum_abs_standardized_coefficient", "active_nonzero_coefficients", "block_name"],
                    ascending=[False, False, True],
                )
                .reset_index(drop=True)
            )
            tables.append(
                {
                    "branch_name": str(branch_name),
                    "diagnostic_type": "lear_coefficients",
                    "table": grouped,
                }
            )
            continue

        if hasattr(branch_model, "importance_frame"):
            importance_frame = branch_model.importance_frame()
            if importance_frame.empty:
                continue
            importance_frame["block_name"] = importance_frame["feature"].map(feature_to_block).fillna("unassigned")
            grouped = (
                importance_frame.groupby("block_name", dropna=False)
                .agg(
                    total_features=("feature", "size"),
                    nonzero_gain_features=("gain", lambda values: int((pd.Series(values) > 0.0).sum())),
                    total_gain=("gain", "sum"),
                    total_split_count=("split_count", "sum"),
                )
                .reset_index()
                .sort_values(["total_gain", "total_split_count", "block_name"], ascending=[False, False, True])
                .reset_index(drop=True)
            )
            tables.append(
                {
                    "branch_name": str(branch_name),
                    "diagnostic_type": "xgboost_importance",
                    "table": grouped,
                }
            )

    return {
        "reference": pd.DataFrame(
            [
                {
                    "parent_run_label": parent_run_label,
                    "parent_run_id": parent.run_id,
                    "fs_level": str(fs_level),
                    "model_family": resolved_family,
                    "split_name": split_name,
                    "forecast_origin_utc": forecast_origin_utc,
                    "delivery_start_local_date": str(delivery_start_local_date),
                }
            ]
        ),
        "tables": tables,
    }


def compute_fs2_parent_block_diagnostics(
    config: HourlyDAPipelineConfig,
    *,
    parent_run_label: str,
    model_family: str | None = None,
    split_name: str = "validation",
    scheme_name: str = SCHEME_NAME_LAYER_1,
    prepared_bundle: dict[str, object] | None = None,
) -> dict[str, object]:
    return _compute_parent_block_diagnostics(
        config,
        fs_level="FS2",
        parent_run_label=parent_run_label,
        model_family=model_family,
        split_name=split_name,
        scheme_name=scheme_name,
        prepared_bundle=prepared_bundle,
    )


def compute_fs3_parent_block_diagnostics(
    config: HourlyDAPipelineConfig,
    *,
    parent_run_label: str,
    model_family: str | None = None,
    split_name: str = "validation",
    scheme_name: str = SCHEME_NAME_LAYER_1,
    store=None,
    prepared_bundle: dict[str, object] | None = None,
) -> dict[str, object]:
    return _compute_parent_block_diagnostics(
        config,
        fs_level="FS3",
        parent_run_label=parent_run_label,
        model_family=model_family,
        split_name=split_name,
        scheme_name=scheme_name,
        store=store,
        prepared_bundle=prepared_bundle,
    )


def build_week_metrics_for_predictions(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    selected_weeks: pd.DataFrame,
    *,
    split_name: str = "test",
    reporting_level: str = "d_only",
    models: list[str] | None = None,
    benchmark_model: str | None = None,
    model_order: list[str] | None = None,
) -> pd.DataFrame:
    resolved_models = models or sorted(predictions["model"].astype(str).unique().tolist())
    selected = select_week_reporting_slice(
        predictions=predictions,
        config=config,
        selected_weeks=selected_weeks,
        split_name=split_name,
        models=resolved_models,
        reporting_level=reporting_level,
    )
    return summarize_week_metrics(
        selected,
        selected_weeks,
        model_order=model_order or resolved_models,
        benchmark_model=benchmark_model,
    )


def write_week_plots_for_models(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    selected_weeks: pd.DataFrame,
    output_dir: Path,
    models: list[str],
    title_prefix: str,
) -> list[Path]:
    from .core.plotting import plot_week_actual_vs_models

    stitched_predictions = build_stitched_day_ahead_predictions(predictions, config)
    if models:
        stitched_predictions = stitched_predictions[stitched_predictions["model"].isin(models)].copy()

    output_paths: list[Path] = []
    for week_row in selected_weeks.to_dict(orient="records"):
        prediction_week = filter_week_window(
            stitched_predictions,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
            timestamp_col="target_timestamp_local",
        )
        if prediction_week.empty:
            continue
        plot_path = output_dir / f"{week_row['category']}_actual_vs_models.png"
        plot_week_actual_vs_models(
            prediction_week=prediction_week,
            output_path=plot_path,
            title=f"{title_prefix}: {week_row['category'].replace('_', ' ').title()} ({week_row['iso_week_id']})",
        )
        output_paths.append(plot_path)
    return output_paths


def build_reporting_metric_grid(
    metrics_by_reporting_level: pd.DataFrame,
    metric_col: str,
    models: list[str] | None = None,
    dataset_splits: tuple[str, ...] = ("validation", "test"),
) -> pd.DataFrame:
    if metrics_by_reporting_level.empty or metric_col not in metrics_by_reporting_level.columns:
        return pd.DataFrame()

    frame = metrics_by_reporting_level.copy()
    if models:
        frame = frame[frame["model"].isin(models)].copy()
    if frame.empty:
        return pd.DataFrame()

    frame = frame[frame["dataset_split"].isin(dataset_splits)].copy()
    frame = frame[frame["reporting_level"] != "guidance_only"].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["dataset_split_label"] = frame["dataset_split"].map(
        {"validation": "Validation", "test": "Test"}
    ).fillna(frame["dataset_split"].astype(str).str.title())

    pivot = frame.pivot_table(
        index="model",
        columns=["reporting_level_label", "dataset_split_label"],
        values=metric_col,
        aggfunc="first",
    )
    if pivot.empty:
        return pd.DataFrame()

    reporting_order = (
        frame[["reporting_level_sort_order", "reporting_level_label"]]
        .drop_duplicates()
        .sort_values(["reporting_level_sort_order", "reporting_level_label"])
    )
    split_order = ["Validation", "Test"]
    ordered_columns = [
        (str(level_label), split_label)
        for _, level_label in reporting_order.itertuples(index=False)
        for split_label in split_order
        if (str(level_label), split_label) in pivot.columns
    ]
    if ordered_columns:
        pivot = pivot.reindex(columns=pd.MultiIndex.from_tuples(ordered_columns))

    sort_frame = frame[
        (frame["reporting_level"] == "stitched_all_horizon") & (frame["dataset_split"] == "validation")
    ][["model", metric_col]].copy()
    if not sort_frame.empty:
        if metric_col == "coverage_pct":
            sort_frame = sort_frame.sort_values(metric_col, ascending=False)
        elif metric_col == "bias":
            sort_frame["_sort_value"] = sort_frame[metric_col].abs()
            sort_frame = sort_frame.sort_values("_sort_value", ascending=True)
        else:
            sort_frame = sort_frame.sort_values(metric_col, ascending=True)
        ordered_models = sort_frame["model"].drop_duplicates().tolist()
        remaining_models = [model for model in pivot.index.tolist() if model not in ordered_models]
        pivot = pivot.reindex(ordered_models + remaining_models)

    return pivot


def _metric_visual_spec(metric_col: str) -> dict[str, object]:
    if metric_col == "coverage_pct":
        return {
            "cmap": colors.LinearSegmentedColormap.from_list("coverage_soft", ["#d9a3a1", "#f3e8c8", "#8fc59b"]),
            "rule_text": "Higher is better",
            "format": lambda value: "-" if pd.isna(value) else f"{float(value):.2f}%",
            "gmap_transform": lambda frame: frame.astype(float),
        }
    if metric_col == "bias":
        return {
            "cmap": colors.LinearSegmentedColormap.from_list("bias_soft", ["#8fc59b", "#f3e8c8", "#d9a3a1"]),
            "rule_text": "Closer to 0 is better",
            "format": lambda value: "-" if pd.isna(value) else f"{float(value):.2f}",
            "gmap_transform": lambda frame: frame.astype(float).abs(),
        }
    return {
        "cmap": colors.LinearSegmentedColormap.from_list("error_soft", ["#8fc59b", "#f3e8c8", "#d9a3a1"]),
        "rule_text": "Lower is better",
        "format": lambda value: "-" if pd.isna(value) else (f"{float(value):.3f}" if metric_col == "rmae_vs_official_naive" else f"{float(value):.2f}"),
        "gmap_transform": lambda frame: frame.astype(float),
    }


def _text_color_for_hex(color_hex: str) -> str:
    red, green, blue = colors.to_rgb(color_hex)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#183247" if luminance >= 0.62 else "#ffffff"


def _display_column_label(column_key: object) -> str:
    if isinstance(column_key, tuple):
        parts = [str(part).strip() for part in column_key if str(part).strip()]
        return "\n".join(parts)
    return str(column_key)


def _display_metric_grid(metric_grid: pd.DataFrame) -> tuple[pd.DataFrame, dict[object, str]]:
    display_grid = metric_grid.copy()
    column_map = {column_key: _display_column_label(column_key) for column_key in metric_grid.columns}
    display_grid.columns = [column_map[column_key] for column_key in metric_grid.columns]
    display_grid.insert(0, "Model", metric_grid.index.astype(str))
    display_grid = display_grid.reset_index(drop=True)
    display_grid.columns.name = None
    return display_grid, column_map


def _cell_style_frame(metric_grid: pd.DataFrame, metric_col: str) -> pd.DataFrame:
    spec = _metric_visual_spec(metric_col)
    numeric_gmap = spec["gmap_transform"](metric_grid)
    finite_values = numeric_gmap.to_numpy(dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    if finite_values.size == 0 or float(finite_values.min()) == float(finite_values.max()):
        norm = None
    else:
        norm = colors.Normalize(vmin=float(finite_values.min()), vmax=float(finite_values.max()))

    style_frame = pd.DataFrame("", index=metric_grid.index, columns=metric_grid.columns)
    for row_key in metric_grid.index:
        for column_key in metric_grid.columns:
            value = numeric_gmap.loc[row_key, column_key]
            if pd.isna(value):
                style_frame.loc[row_key, column_key] = "background-color: #f5f7f9; color: #61717f; font-weight: 600;"
                continue
            normalized = 0.5 if norm is None else float(norm(float(value)))
            color_hex = colors.to_hex(spec["cmap"](normalized))
            text_color = _text_color_for_hex(color_hex)
            style_frame.loc[row_key, column_key] = (
                f"background-color: {color_hex}; color: {text_color}; font-weight: 700;"
            )
    return style_frame


def style_reporting_metric_grid(
    metric_grid: pd.DataFrame,
    metric_col: str,
    caption: str,
):
    if metric_grid.empty:
        return metric_grid

    display_grid, column_map = _display_metric_grid(metric_grid)

    spec = _metric_visual_spec(metric_col)
    formatter = spec["format"]
    metric_style_frame = _cell_style_frame(metric_grid, metric_col)
    style_frame = pd.DataFrame("", index=display_grid.index, columns=display_grid.columns)
    model_column = "Model"
    style_frame.loc[:, model_column] = (
        "background-color: #fbfcfd; color: #183247; font-weight: 600; text-align: left;"
    )
    for row_position, row_label in enumerate(metric_grid.index):
        for column_key in metric_grid.columns:
            display_column = column_map[column_key]
            style_frame.loc[row_position, display_column] = metric_style_frame.loc[row_label, column_key]

    styler = display_grid.style
    metric_columns = [column_name for column_name in display_grid.columns if column_name != model_column]
    if metric_columns:
        styler = styler.format(formatter, na_rep="-", subset=metric_columns)
    styler = styler.apply(lambda _: style_frame, axis=None)
    try:
        styler = styler.hide(axis="index")
    except Exception:
        pass
    styler = styler.set_table_styles(
        [
            {"selector": "", "props": [("border-collapse", "separate"), ("border-spacing", "0"), ("width", "100%"), ("font-size", "12px")]},
            {"selector": "th.col_heading", "props": [("background", "#edf3f7"), ("color", "#183247"), ("border", "1px solid #dce5eb"), ("padding", "9px 10px"), ("text-align", "center"), ("white-space", "pre-line")]},
            {"selector": "th.row_heading", "props": [("background", "#fbfcfd"), ("color", "#183247"), ("border", "1px solid #e5ecf1"), ("padding", "8px 10px"), ("text-align", "left"), ("white-space", "nowrap"), ("font-weight", "600")]},
            {"selector": "td", "props": [("border", "1px solid #eef2f6"), ("padding", "8px 10px"), ("text-align", "center"), ("min-width", "82px")]},
        ],
        overwrite=False,
    )
    return styler


def render_plot_gallery(
    plot_paths: list[Path | str],
    columns: int = 2,
):
    if not plot_paths:
        return HTML("<div style='color: #61717f;'>No plots available.</div>")

    safe_columns = max(int(columns), 1)
    cards = []
    for plot_path in plot_paths:
        path_obj = Path(plot_path)
        if not path_obj.exists():
            cards.append(
                "<div class='plot-gallery-card'>"
                f"<div style='color: #8a4b4b; font-size: 12px;'>Missing plot: {escape(str(path_obj))}</div>"
                "</div>"
            )
            continue

        image_bytes = path_obj.read_bytes()
        suffix = path_obj.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"
        elif suffix == ".svg":
            mime_type = "image/svg+xml"
        else:
            mime_type = "image/png"
        image_uri = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        cards.append(
            "<div class='plot-gallery-card'>"
            f"<img src='{escape(image_uri)}' style='width: 100%; height: auto; display: block; border-radius: 14px;'/>"
            "</div>"
        )

    gallery_html = (
        """
        <style>
        .plot-gallery-grid {
            display: grid;
            gap: 16px;
            align-items: start;
        }
        .plot-gallery-card {
            border: 1px solid #dde4ea;
            border-radius: 16px;
            background: #ffffff;
            box-shadow: 0 8px 20px rgba(16, 24, 40, 0.06);
            padding: 10px;
        }
        @media (max-width: 1100px) {
            .plot-gallery-grid {
                grid-template-columns: 1fr !important;
            }
        }
        </style>
        """
        f"<div class='plot-gallery-grid' style='grid-template-columns: repeat({safe_columns}, minmax(0, 1fr));'>"
        f"{''.join(cards)}"
        "</div>"
    )
    return HTML(gallery_html)


def render_reporting_metric_dashboard(
    metrics_by_reporting_level: pd.DataFrame,
    models: list[str],
    model_descriptions: dict[str, str] | None = None,
    title: str | None = None,
    metric_specs: list[tuple[str, str]] | None = None,
):
    metric_specs = metric_specs or [
        ("coverage_pct", "Coverage"),
        ("mae", "MAE"),
        ("rmse", "RMSE"),
        ("bias", "Bias"),
        ("rmae_vs_official_naive", "rMAE"),
    ]

    dashboard_cards: list[str] = []
    for metric_col, caption in metric_specs:
        metric_grid = build_reporting_metric_grid(
            metrics_by_reporting_level=metrics_by_reporting_level,
            metric_col=metric_col,
            models=models,
        )
        if metric_grid.empty:
            continue
        styler = style_reporting_metric_grid(metric_grid, metric_col=metric_col, caption=caption)
        rule_text = _metric_visual_spec(metric_col)["rule_text"]
        card_html = (
            "<div class='metric-card'>"
            "<div class='metric-card-header'>"
            f"<div class='metric-card-title'>{escape(caption)}</div>"
            f"<div class='metric-card-rule'>{escape(str(rule_text))}</div>"
            "</div>"
            "<div class='metric-card-table'>"
            f"{styler.to_html()}"
            "</div>"
            "</div>"
        )
        dashboard_cards.append(card_html)

    explanation_items = [
        "Rows are the models in this notebook.",
        "Columns are reporting level crossed with Validation and Test.",
        "D only = lead day 0, Full-horizon = lead days 0 to 4 combined.",
        "Green means better, red means worse, using the rule written on each card.",
    ]
    explanation_html = "".join([f"<li style='margin: 4px 0;'>{escape(item)}</li>" for item in explanation_items])

    model_html = ""
    if model_descriptions:
        model_lines = "".join(
            [
                f"<li style='margin: 4px 0;'><span style='font-weight: 700;'>{escape(model_name)}</span>: {escape(description)}</li>"
                for model_name, description in model_descriptions.items()
            ]
        )
        model_html = (
            "<div style='margin-top: 12px;'>"
            "<div style='font-weight: 700; color: #183247; margin-bottom: 6px;'>Models in this notebook</div>"
            f"<ul style='margin: 0; padding-left: 18px; color: #425466;'>{model_lines}</ul>"
            "</div>"
        )

    intro_title = escape(title or "Comparison dashboard")
    intro_block = (
        "<div class='dashboard-intro'>"
        f"<div class='dashboard-title'>{intro_title}</div>"
        "<ul class='dashboard-explanation'>"
        f"{explanation_html}"
        "</ul>"
        f"{model_html}"
        "</div>"
    )

    dashboard_html = (
        """
        <style>
        .metric-dashboard {
            display: flex;
            flex-direction: column;
            gap: 18px;
        }
        .dashboard-intro {
            border: 1px solid #dde4ea;
            border-radius: 18px;
            background: linear-gradient(135deg, #fbfcfd 0%, #f3f8fa 100%);
            padding: 18px 20px;
            box-shadow: 0 8px 22px rgba(16, 24, 40, 0.05);
        }
        .dashboard-title {
            font-size: 19px;
            font-weight: 700;
            color: #183247;
            margin-bottom: 10px;
        }
        .dashboard-explanation {
            margin: 0;
            padding-left: 18px;
            color: #425466;
        }
        .dashboard-cards {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            align-items: start;
        }
        .metric-card {
            border: 1px solid #dde4ea;
            border-radius: 16px;
            background: #ffffff;
            box-shadow: 0 10px 24px rgba(16, 24, 40, 0.06);
            overflow: hidden;
        }
        .metric-card-header {
            padding: 14px 16px 10px 16px;
            border-bottom: 1px solid #eef2f6;
            background: linear-gradient(180deg, #fcfdff 0%, #f7fafc 100%);
        }
        .metric-card-title {
            font-size: 15px;
            font-weight: 700;
            color: #183247;
        }
        .metric-card-rule {
            font-size: 12px;
            color: #5b6b79;
            margin-top: 4px;
        }
        .metric-card-table {
            padding: 12px 14px 14px 14px;
        }
        .metric-card-table table {
            width: 100%;
        }
        .metric-card-table th.blank {
            display: none;
        }
        @media (max-width: 1300px) {
            .dashboard-cards {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """
        "<div class='metric-dashboard'>"
        f"{intro_block}"
        "<div class='dashboard-cards'>"
        f"{''.join(dashboard_cards)}"
        "</div>"
        "</div>"
    )
    return HTML(dashboard_html)


def summarize_timing_compact(timing_summary: pd.DataFrame) -> pd.DataFrame:
    if timing_summary.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for (model, model_family, fs_level), group in timing_summary.groupby(["model", "model_family", "fs_level"], dropna=False):
        weights = group["origins"].astype(float)
        total_origins = int(weights.sum())
        fit_mean = float(np.average(group["fit_time_mean_sec"].astype(float), weights=weights))
        predict_mean = float(np.average(group["predict_time_mean_sec"].astype(float), weights=weights))
        rows.append(
            {
                "model": model,
                "model_family": model_family,
                "fs_level": fs_level,
                "origins_total": total_origins,
                "fit_time_mean_sec": fit_mean,
                "predict_time_mean_sec": predict_mean,
                "fit_time_max_sec": float(group["fit_time_max_sec"].astype(float).max()),
                "fit_time_warning_count": int(group["fit_time_warning_count"].astype(int).sum()),
            }
        )

    return pd.DataFrame(rows).sort_values(["fit_time_mean_sec", "model"]).reset_index(drop=True)


STANDARD_REPORT_METRICS: tuple[tuple[str, str], ...] = (
    ("mae", "MAE"),
    ("rmse", "RMSE"),
    ("rmae_vs_official_naive", "rMAE"),
    ("bias", "Bias"),
    ("coverage_pct", "Coverage"),
)

REPORT_FIGURE_FACE = "#ffffff"
REPORT_AX_FACE = "#ffffff"
REPORT_TEXT = "#183247"
REPORT_MUTED = "#5b6b79"
REPORT_GRID = "#d9e2ea"
REPORT_SPINE = "#dce5eb"
REPORT_ACTUAL = "#18212a"
REPORT_PALETTE = [
    "#2f5d8a",
    "#c1684b",
    "#5c8a63",
    "#92704e",
    "#6c7a95",
    "#6b9aa2",
]


def apply_standard_matplotlib_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": REPORT_FIGURE_FACE,
            "axes.facecolor": REPORT_AX_FACE,
            "savefig.facecolor": REPORT_FIGURE_FACE,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "axes.labelcolor": REPORT_MUTED,
            "axes.edgecolor": REPORT_SPINE,
            "axes.linewidth": 1.0,
            "axes.grid": True,
            "grid.color": REPORT_GRID,
            "grid.alpha": 0.6,
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
            "xtick.color": REPORT_MUTED,
            "ytick.color": REPORT_MUTED,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.frameon": True,
            "legend.facecolor": "#fbfcfd",
            "legend.edgecolor": REPORT_SPINE,
            "legend.framealpha": 1.0,
            "legend.fontsize": 9,
            "figure.dpi": 120,
            "savefig.dpi": 180,
        }
    )


def _friendly_model_name(model_name: str) -> str:
    return str(model_name).replace("_", " ").title()


def _run_label_from_dir(run_dir: Path | str) -> str:
    run_name = Path(run_dir).name
    parts = run_name.split("_", 2)
    return parts[2] if len(parts) == 3 else run_name


def _load_run_model_catalog(run_dir: Path) -> pd.DataFrame:
    suite_models_path = run_dir / "suite_models.json"
    if suite_models_path.exists():
        suite_models = load_json(run_dir, "suite_models.json")
        rows: list[dict[str, object]] = []
        for record in suite_models.get("models", []):
            model_name = record.get("model") or record.get("name")
            if not model_name:
                continue
            rows.append(
                {
                    "model": str(model_name),
                    "model_family": str(record.get("model_family") or record.get("family") or ""),
                    "fs_level": str(record.get("fs_level") or ""),
                }
            )
        if rows:
            return pd.DataFrame(rows).drop_duplicates(subset=["model"]).reset_index(drop=True)

    metrics_overall_path = run_dir / "metrics_overall.csv"
    if metrics_overall_path.exists():
        metrics_overall = pd.read_csv(metrics_overall_path)
        required_cols = [column for column in ["model", "model_family", "fs_level"] if column in metrics_overall.columns]
        if "model" in required_cols:
            return (
                metrics_overall[required_cols]
                .drop_duplicates(subset=["model"])
                .assign(
                    model_family=lambda frame: frame["model_family"] if "model_family" in frame.columns else "",
                    fs_level=lambda frame: frame["fs_level"] if "fs_level" in frame.columns else "",
                )
                .reset_index(drop=True)
            )

    return pd.DataFrame(columns=["model", "model_family", "fs_level"])


def _read_filtered_csv(
    path: Path,
    filters: dict[str, set[str]] | None = None,
    usecols: list[str] | None = None,
    dtype: dict[str, str] | None = None,
    chunksize: int = 250_000,
) -> pd.DataFrame:
    try:
        resolved_path = resolve_tabular_path(path.parent, path.name)
    except FileNotFoundError:
        return pd.DataFrame()

    if resolved_path.suffix.lower() == ".parquet":
        requested_columns = (
            list(dict.fromkeys([*usecols, *((filters or {}).keys())]))
            if usecols is not None
            else None
        )
        read_parquet_kwargs: dict[str, object] = {}
        if requested_columns is not None:
            read_parquet_kwargs["columns"] = requested_columns
        try:
            frame = pd.read_parquet(resolved_path, **read_parquet_kwargs)
        except (KeyError, ValueError):
            available = [column for column in (usecols or []) if column in pd.read_parquet(resolved_path).columns]
            return pd.DataFrame(columns=available)

        if dtype:
            applicable_dtype = {
                column: column_dtype
                for column, column_dtype in dtype.items()
                if column in frame.columns
            }
            if applicable_dtype:
                frame = frame.astype(applicable_dtype, copy=False)

        if filters:
            mask = pd.Series(True, index=frame.index)
            for column, allowed_values in filters.items():
                if column not in frame.columns:
                    return pd.DataFrame(columns=(usecols or frame.columns.tolist()))
                mask &= frame[column].astype(str).isin(allowed_values)
            frame = frame.loc[mask].copy()

        if usecols:
            frame = frame[[column for column in usecols if column in frame.columns]]
        return frame.reset_index(drop=True)

    header = pd.read_csv(resolved_path, nrows=0)
    requested_columns = (
        list(dict.fromkeys([*usecols, *((filters or {}).keys())]))
        if usecols is not None
        else None
    )
    if requested_columns is not None:
        missing_requested = [column for column in requested_columns if column not in header.columns]
        if missing_requested:
            available = [column for column in (usecols or []) if column in header.columns]
            return pd.DataFrame(columns=available)

    read_csv_kwargs: dict[str, object] = {}
    if requested_columns is not None:
        read_csv_kwargs["usecols"] = requested_columns
    if dtype:
        applicable_dtype = {
            column: column_dtype
            for column, column_dtype in dtype.items()
            if requested_columns is None or column in requested_columns
        }
        if applicable_dtype:
            read_csv_kwargs["dtype"] = applicable_dtype

    if not filters:
        return pd.read_csv(resolved_path, **read_csv_kwargs)

    missing = [column for column in filters if column not in header.columns]
    if missing:
        return pd.DataFrame(columns=(usecols or header.columns.tolist()))

    parts: list[pd.DataFrame] = []
    for chunk in pd.read_csv(resolved_path, chunksize=chunksize, **read_csv_kwargs):
        mask = pd.Series(True, index=chunk.index)
        for column, allowed_values in filters.items():
            mask &= chunk[column].astype(str).isin(allowed_values)
        filtered = chunk.loc[mask].copy()
        if not filtered.empty:
            if usecols:
                filtered = filtered[[column for column in usecols if column in filtered.columns]]
            parts.append(filtered)

    if not parts:
        return pd.DataFrame(columns=(usecols or header.columns.tolist()))
    return pd.concat(parts, ignore_index=True)


def _coerce_utc_datetime_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    coerced = frame.copy()
    for column in columns:
        if column in coerced.columns:
            coerced[column] = pd.to_datetime(coerced[column], utc=True, errors="coerce")
    return coerced


def _resolve_comparison_spec_run_dir(
    output_root: Path,
    current_run_dir: Path,
    spec: dict[str, object],
) -> Path:
    run_label_value = spec.get("run_label")
    if spec.get("source") is None and run_label_value:
        source_value = str(run_label_value)
    else:
        source_value = str(spec.get("source", "current"))
    if source_value == "current":
        return current_run_dir
    run_label = str(run_label_value or source_value)
    return find_latest_run(output_root, run_label)


def filter_available_comparison_specs(
    output_root: Path,
    current_run_dir: Path,
    candidate_specs: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not candidate_specs:
        return []

    available_specs: list[dict[str, object]] = []
    catalog_cache: dict[Path, set[str]] = {}
    for spec in candidate_specs:
        model_name = str(spec.get("model", "")).strip()
        if not model_name:
            continue
        try:
            run_dir = _resolve_comparison_spec_run_dir(output_root, current_run_dir, spec)
        except FileNotFoundError:
            continue

        if run_dir not in catalog_cache:
            catalog = _load_run_model_catalog(run_dir)
            catalog_cache[run_dir] = set(catalog["model"].astype(str).tolist()) if not catalog.empty else set()
        if model_name not in catalog_cache[run_dir]:
            continue

        available_specs.append(dict(spec))
    return available_specs


def choose_best_available_comparison_spec(
    output_root: Path,
    current_run_dir: Path,
    candidate_specs: list[dict[str, object]],
    split_name: str = "validation",
    reporting_level: str = "stitched_all_horizon",
) -> dict[str, object] | None:
    if not candidate_specs:
        return None

    catalog_cache: dict[Path, set[str]] = {}
    metric_cache: dict[Path, pd.DataFrame] = {}
    ranked_rows: list[dict[str, object]] = []
    for spec_index, spec in enumerate(candidate_specs):
        model_name = str(spec.get("model", "")).strip()
        if not model_name:
            continue
        try:
            run_dir = _resolve_comparison_spec_run_dir(output_root, current_run_dir, spec)
        except FileNotFoundError:
            continue

        if run_dir not in catalog_cache:
            catalog = _load_run_model_catalog(run_dir)
            catalog_cache[run_dir] = set(catalog["model"].astype(str).tolist()) if not catalog.empty else set()
        if model_name not in catalog_cache[run_dir]:
            continue

        if run_dir not in metric_cache:
            metrics = load_csv(run_dir, "metrics_by_reporting_level.csv")
            metric_cache[run_dir] = metrics if not metrics.empty else pd.DataFrame()
        metrics = metric_cache[run_dir]
        if metrics.empty:
            continue

        part = metrics[
            (metrics["model"].astype(str) == model_name)
            & (metrics["dataset_split"].astype(str) == split_name)
            & (metrics["reporting_level"].astype(str) == reporting_level)
        ].copy()
        if part.empty:
            continue

        part["abs_bias"] = part["bias"].astype(float).abs()
        best_row = (
            part.sort_values(["mae", "rmse", "abs_bias", "model"])
            .iloc[0]
            .to_dict()
        )
        ranked_rows.append(
            {
                "spec_index": int(spec_index),
                "spec": dict(spec),
                "mae": float(best_row["mae"]),
                "rmse": float(best_row["rmse"]),
                "abs_bias": float(best_row["abs_bias"]),
            }
        )

    if not ranked_rows:
        return None

    ranked_rows.sort(key=lambda row: (row["mae"], row["rmse"], row["abs_bias"], row["spec_index"]))
    return dict(ranked_rows[0]["spec"])


def resolve_comparison_model_specs(
    output_root: Path,
    current_run_dir: Path,
    comparison_specs: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    if comparison_specs is None:
        current_catalog = _load_run_model_catalog(current_run_dir)
        comparison_specs = [{"model": model_name, "role": "current"} for model_name in current_catalog["model"].tolist()]

    rows: list[dict[str, object]] = []
    for order, spec in enumerate(comparison_specs):
        model_name = str(spec["model"])
        run_dir = _resolve_comparison_spec_run_dir(output_root, current_run_dir, spec)

        rows.append(
            {
                "comparison_order": int(order),
                "model": model_name,
                "display_name": str(spec.get("display_name") or _friendly_model_name(model_name)),
                "description": str(spec.get("description") or ""),
                "role": str(spec.get("role") or ("current" if run_dir == current_run_dir else "prior")),
                "run_dir": Path(run_dir),
                "source_run_id": Path(run_dir).name,
                "source_run_label": _run_label_from_dir(run_dir),
                "is_current_run": bool(Path(run_dir) == current_run_dir),
                "color": spec.get("color"),
                "linestyle": spec.get("linestyle"),
            }
        )

    if not rows:
        return pd.DataFrame()

    spec_frame = pd.DataFrame(rows)
    catalog_frames: list[pd.DataFrame] = []
    for run_dir in spec_frame["run_dir"].drop_duplicates().tolist():
        catalog = _load_run_model_catalog(Path(run_dir))
        if catalog.empty:
            continue
        catalog["run_dir"] = Path(run_dir)
        catalog_frames.append(catalog)

    if catalog_frames:
        catalog_all = pd.concat(catalog_frames, ignore_index=True)
        spec_frame = spec_frame.merge(catalog_all, on=["run_dir", "model"], how="left")
    else:
        spec_frame["model_family"] = ""
        spec_frame["fs_level"] = ""

    spec_frame["model_family"] = spec_frame["model_family"].fillna("")
    spec_frame["fs_level"] = spec_frame["fs_level"].fillna("")
    return spec_frame.sort_values("comparison_order").reset_index(drop=True)


def _recompute_rmae_against_current_benchmark(
    metrics: pd.DataFrame,
    benchmark_model: str,
    benchmark_source_run_id: str,
    group_keys: list[str],
    output_col: str = "rmae_vs_official_naive",
) -> pd.DataFrame:
    if metrics.empty or benchmark_model not in metrics["model"].astype(str).unique():
        return metrics

    reference = metrics[
        (metrics["model"].astype(str) == str(benchmark_model))
        & (metrics["source_run_id"].astype(str) == str(benchmark_source_run_id))
    ][group_keys + ["mae"]].copy()
    if reference.empty:
        return metrics

    reference = reference.drop_duplicates(subset=group_keys).rename(columns={"mae": "_benchmark_mae"})
    merged = metrics.merge(reference, on=group_keys, how="left")
    merged[output_col] = merged["mae"] / merged["_benchmark_mae"]
    merged.loc[merged["_benchmark_mae"].isna() | (merged["_benchmark_mae"] == 0.0), output_col] = np.nan
    return merged.drop(columns=["_benchmark_mae"])


def load_standard_report_bundle(
    output_root: Path,
    current_run_dir: Path,
    comparison_specs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    spec_frame = resolve_comparison_model_specs(
        output_root=output_root,
        current_run_dir=current_run_dir,
        comparison_specs=comparison_specs,
    )
    if spec_frame.empty:
        raise ValueError("No comparison models were resolved for the notebook report.")

    artifact_frames: dict[str, list[pd.DataFrame]] = {
        "metrics_overall": [],
        "metrics_by_reporting_level": [],
        "metrics_by_lead_day": [],
        "predictions_long": [],
        "timing_summary": [],
    }
    artifact_specs = {
        "metrics_overall": {"filename": "metrics_overall.csv"},
        "metrics_by_reporting_level": {"filename": "metrics_by_reporting_level.csv"},
        "metrics_by_lead_day": {"filename": "metrics_by_lead_day.csv"},
        "predictions_long": {
            "filename": "predictions_long.csv",
            "usecols": [
                "model",
                "dataset_split",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "target_hour_local",
                "target_known_at_utc",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "y_true",
                "y_pred",
            ],
            "dtype": {
                "model": "category",
                "dataset_split": "category",
                "forecast_origin_utc": "string",
                "target_timestamp_utc": "string",
                "target_known_at_utc": "string",
                "target_hour_local": "int8",
                "lead_day": "int8",
                "lead_day_label": "string",
                "horizon_index": "int16",
                "y_true": "float32",
                "y_pred": "float32",
            },
            "chunksize": 50_000,
        },
        "timing_summary": {"filename": "origin_timing_summary.csv"},
    }
    merge_columns = [
        "model",
        "display_name",
        "description",
        "role",
        "comparison_order",
        "source_run_id",
        "source_run_label",
        "is_current_run",
        "model_family",
        "fs_level",
    ]

    for run_dir, spec_group in spec_frame.groupby("run_dir", sort=False):
        model_filter = {"model": set(spec_group["model"].astype(str).tolist())}
        metadata = spec_group[merge_columns].drop_duplicates(subset=["model"]).copy()
        metadata["model"] = metadata["model"].astype(str)

        for artifact_name, artifact_spec in artifact_specs.items():
            frame = _read_filtered_csv(
                Path(run_dir) / str(artifact_spec["filename"]),
                filters=model_filter,
                usecols=artifact_spec.get("usecols"),
                dtype=artifact_spec.get("dtype"),
                chunksize=int(artifact_spec.get("chunksize", 250_000)),
            )
            if frame.empty:
                continue
            frame["model"] = frame["model"].astype(str)
            frame = frame.merge(metadata, on="model", how="left", suffixes=("", "_spec"))
            artifact_frames[artifact_name].append(frame)

    bundle = {
        artifact_name: (
            pd.concat(parts, ignore_index=True).sort_values(["comparison_order"]).reset_index(drop=True)
            if parts
            else pd.DataFrame()
        )
        for artifact_name, parts in artifact_frames.items()
    }
    bundle["predictions_long"] = _coerce_utc_datetime_columns(
        bundle["predictions_long"],
        ["forecast_origin_utc", "target_timestamp_utc", "target_known_at_utc"],
    )

    official_naive = load_json(current_run_dir, "official_naive_reference.json")
    benchmark_model = str(official_naive.get("model", ""))
    benchmark_source_run_id = current_run_dir.name
    bundle["metrics_overall"] = _recompute_rmae_against_current_benchmark(
        bundle["metrics_overall"],
        benchmark_model=benchmark_model,
        benchmark_source_run_id=benchmark_source_run_id,
        group_keys=["dataset_split"],
    )
    bundle["metrics_by_lead_day"] = _recompute_rmae_against_current_benchmark(
        bundle["metrics_by_lead_day"],
        benchmark_model=benchmark_model,
        benchmark_source_run_id=benchmark_source_run_id,
        group_keys=["dataset_split", "lead_day", "lead_day_label"],
    )
    bundle["metrics_by_reporting_level"] = _recompute_rmae_against_current_benchmark(
        bundle["metrics_by_reporting_level"],
        benchmark_model=benchmark_model,
        benchmark_source_run_id=benchmark_source_run_id,
        group_keys=["dataset_split", "reporting_level", "reporting_level_label", "reporting_level_sort_order"],
    )

    dm_reporting = _read_filtered_csv(
        current_run_dir / "diebold_mariano_by_reporting_level.csv",
        filters={"challenger_model": set(spec_frame["model"].astype(str).tolist())},
    )
    if not dm_reporting.empty:
        challenger_map = (
            spec_frame[["model", "display_name"]]
            .drop_duplicates(subset=["model"])
            .set_index("model")["display_name"]
            .to_dict()
        )
        dm_reporting["challenger_display_name"] = dm_reporting["challenger_model"].map(challenger_map).fillna(
            dm_reporting["challenger_model"].map(_friendly_model_name)
        )
        dm_reporting["benchmark_display_name"] = dm_reporting["benchmark_model"].map(challenger_map).fillna(
            dm_reporting["benchmark_model"].map(_friendly_model_name)
        )

    bundle["diebold_mariano_by_reporting_level"] = dm_reporting
    bundle["comparison_specs"] = spec_frame
    bundle["model_order"] = spec_frame.sort_values("comparison_order")["display_name"].tolist()
    bundle["model_key_order"] = spec_frame.sort_values("comparison_order")["model"].tolist()
    bundle["official_naive"] = official_naive
    return bundle


def build_compared_models_overview(
    comparison_specs: pd.DataFrame,
    official_naive_model: str | None = None,
) -> pd.DataFrame:
    if comparison_specs.empty:
        return pd.DataFrame()

    overview = comparison_specs.copy().sort_values("comparison_order").reset_index(drop=True)
    overview["role_label"] = overview["role"].astype(str).str.replace("_", " ").str.title()
    overview["source_scope"] = np.where(overview["is_current_run"], "Current run", "Previous run")
    overview["official_benchmark"] = overview["model"].astype(str) == str(official_naive_model or "")
    return overview[
        [
            "display_name",
            "model",
            "model_family",
            "fs_level",
            "role_label",
            "source_scope",
            "source_run_label",
            "official_benchmark",
            "description",
        ]
    ].rename(
        columns={
            "display_name": "Model",
            "model": "Internal model",
            "model_family": "Family",
            "fs_level": "FS level",
            "role_label": "Role",
            "source_scope": "Source scope",
            "source_run_label": "Source run",
            "official_benchmark": "Naive benchmark",
            "description": "Description",
        }
    )


def style_model_overview_table(overview: pd.DataFrame):
    if overview.empty:
        return overview

    styler = overview.style.hide(axis="index")
    styler = styler.format({"Naive benchmark": lambda value: "Yes" if bool(value) else ""})
    styler = styler.apply(
        lambda row: [
            "background-color: #eef5fb; font-weight: 600;" if row["Source scope"] == "Current run" else ""
            for _ in row
        ],
        axis=1,
    )
    styler = styler.map(
        lambda value: "background-color: #e4f1e6; color: #1e5a2b; font-weight: 700;"
        if bool(value)
        else "",
        subset=["Naive benchmark"],
    )
    styler = styler.set_table_styles(
        [
            {"selector": "", "props": [("border-collapse", "collapse"), ("width", "100%"), ("font-size", "12px")]},
            {"selector": "th", "props": [("background", "#edf3f7"), ("color", REPORT_TEXT), ("padding", "8px 10px"), ("border", "1px solid #dce5eb")]},
            {"selector": "td", "props": [("padding", "8px 10px"), ("border", "1px solid #e8edf1"), ("vertical-align", "top")]},
        ],
        overwrite=False,
    )
    return styler


def _table_formatter(metric_label: str):
    if metric_label == "rMAE":
        return lambda value: "-" if pd.isna(value) else f"{float(value):.3f}"
    if metric_label == "Coverage":
        return lambda value: "-" if pd.isna(value) else f"{float(value):.2f}%"
    if metric_label == "Bias":
        return lambda value: "-" if pd.isna(value) else f"{float(value):+.2f}"
    return lambda value: "-" if pd.isna(value) else f"{float(value):.2f}"


def build_reporting_summary_table(
    metrics_by_reporting_level: pd.DataFrame,
    split_name: str,
    model_order: list[str],
    metric_specs: tuple[tuple[str, str], ...] | None = None,
) -> pd.DataFrame:
    if metrics_by_reporting_level.empty:
        return pd.DataFrame()

    metric_specs = metric_specs or STANDARD_REPORT_METRICS
    part = metrics_by_reporting_level[metrics_by_reporting_level["dataset_split"] == split_name].copy()
    part = part[part["reporting_level"] != "guidance_only"].copy()
    if part.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for spec in reporting_level_specs():
        reporting_part = part[part["reporting_level"] == spec.reporting_level].copy()
        if reporting_part.empty:
            continue
        reporting_part = reporting_part.sort_values(["comparison_order", "display_name"]).drop_duplicates(
            subset=["display_name"], keep="first"
        )
        reporting_part = reporting_part.set_index("display_name")
        column_series: dict[tuple[str, str], pd.Series] = {}
        for metric_col, metric_label in metric_specs:
            if metric_col in reporting_part.columns:
                column_series[(spec.reporting_level_label, metric_label)] = reporting_part[metric_col]
        if column_series:
            frames.append(pd.DataFrame(column_series))

    if not frames:
        return pd.DataFrame()

    table = pd.concat(frames, axis=1)
    ordered_models = [model_name for model_name in model_order if model_name in table.index]
    remainder = [model_name for model_name in table.index.tolist() if model_name not in ordered_models]
    table = table.reindex(ordered_models + remainder)
    table.index.name = "Model"
    return table


def style_reporting_summary_table(summary_table: pd.DataFrame, caption: str | None = None):
    if summary_table.empty:
        return summary_table

    style_frame = pd.DataFrame("", index=summary_table.index, columns=summary_table.columns)
    for column in summary_table.columns:
        values = pd.to_numeric(summary_table[column], errors="coerce")
        metric_label = str(column[1]) if isinstance(column, tuple) else str(column)
        valid = values.dropna()
        if valid.empty:
            continue
        if metric_label == "Coverage":
            best_mask = values == float(valid.max())
        elif metric_label == "Bias":
            best_mask = values.abs() == float(values.abs().dropna().min())
        else:
            best_mask = values == float(valid.min())
        style_frame.loc[best_mask, column] = "background-color: #e4f1e6; color: #1e5a2b; font-weight: 700;"
        style_frame.loc[values.isna(), column] = "color: #7b8895;"

    formatter_map = {column: _table_formatter(str(column[1])) for column in summary_table.columns}
    styler = summary_table.style.format(formatter_map)
    styler = styler.apply(lambda _: style_frame, axis=None)
    if caption:
        styler = styler.set_caption(caption)
    styler = styler.set_table_styles(
        [
            {"selector": "caption", "props": [("caption-side", "top"), ("font-weight", "700"), ("font-size", "14px"), ("color", REPORT_TEXT), ("padding-bottom", "6px")]},
            {"selector": "", "props": [("border-collapse", "collapse"), ("width", "100%"), ("font-size", "12px")]},
            {"selector": "th", "props": [("background", "#edf3f7"), ("color", REPORT_TEXT), ("padding", "8px 10px"), ("border", "1px solid #dce5eb")]},
            {"selector": "td", "props": [("padding", "8px 10px"), ("border", "1px solid #e8edf1"), ("text-align", "center")]},
            {"selector": "th.row_heading", "props": [("text-align", "left"), ("background", "#fbfcfd"), ("font-weight", "600")]},
        ],
        overwrite=False,
    )
    return styler


def build_model_style_map(
    comparison_specs: pd.DataFrame,
    official_naive_model: str | None = None,
) -> dict[str, dict[str, object]]:
    if comparison_specs.empty:
        return {}

    style_map: dict[str, dict[str, object]] = {}
    for color_index, (_, row) in enumerate(comparison_specs.sort_values("comparison_order").iterrows()):
        model_name = str(row["model"])
        role = str(row.get("role", "current"))
        default_color = REPORT_PALETTE[color_index % len(REPORT_PALETTE)]
        if model_name == str(official_naive_model or ""):
            default_color = "#244f7a"
        default_linestyle = "--" if role in {"prior", "benchmark"} else "-"
        style_map[model_name] = {
            "label": str(row["display_name"]),
            "color": row["color"] if pd.notna(row["color"]) else default_color,
            "linestyle": row["linestyle"] if pd.notna(row["linestyle"]) else default_linestyle,
            "linewidth": 2.6 if model_name == str(official_naive_model or "") else 2.0,
            "alpha": 0.98 if model_name == str(official_naive_model or "") else 0.92,
        }
    return style_map


def _reporting_level_to_lead_days(reporting_level: str) -> tuple[int, ...]:
    mapping = {
        "d_only": (0,),
        "guidance_only": (1, 2, 3, 4),
        "stitched_all_horizon": (0, 1, 2, 3, 4),
    }
    if reporting_level not in mapping:
        raise ValueError(f"Unsupported reporting level: {reporting_level}")
    return mapping[reporting_level]


def select_prediction_slice(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    split_name: str,
    models: list[str],
    reporting_level: str = "d_only",
    unique_targets: bool = True,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()

    part = predictions.copy()
    part = part[part["dataset_split"] == split_name].copy()
    part = part[part["model"].isin(models)].copy()
    part = part[part["lead_day"].astype(int).isin(_reporting_level_to_lead_days(reporting_level))].copy()
    if part.empty:
        return pd.DataFrame()

    part = _coerce_utc_datetime_columns(part, ["forecast_origin_utc", "target_timestamp_utc"])
    if unique_targets:
        part = (
            part.sort_values(["model", "target_timestamp_utc", "forecast_origin_utc"])
            .drop_duplicates(subset=["model", "target_timestamp_utc"], keep="last")
            .reset_index(drop=True)
        )
    part["target_timestamp_local"] = part["target_timestamp_utc"].dt.tz_convert(config.resolved_business_timezone())
    if "display_name" not in part.columns:
        part["display_name"] = part["model"].map(_friendly_model_name)
    return part


def select_week_reporting_slice(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    selected_weeks: pd.DataFrame,
    split_name: str,
    models: list[str],
    reporting_level: str = "d_only",
) -> pd.DataFrame:
    if reporting_level != "stitched_all_horizon":
        return select_prediction_slice(
            predictions=predictions,
            config=config,
            split_name=split_name,
            models=models,
            reporting_level=reporting_level,
            unique_targets=True,
        )

    if predictions.empty or selected_weeks.empty:
        return pd.DataFrame()

    frozen = select_prediction_slice(
        predictions=predictions,
        config=config,
        split_name=split_name,
        models=models,
        reporting_level=reporting_level,
        unique_targets=False,
    )
    if frozen.empty:
        return pd.DataFrame()

    frozen["forecast_origin_local"] = frozen["forecast_origin_utc"].dt.tz_convert(config.resolved_business_timezone())
    frozen["forecast_origin_local_date"] = frozen["forecast_origin_local"].dt.date
    frozen["target_local_date"] = frozen["target_timestamp_local"].dt.date

    week_frames: list[pd.DataFrame] = []
    for week_row in selected_weeks.to_dict(orient="records"):
        week_start_local_date = pd.Timestamp(week_row["week_start_local_date"]).date()
        week_end_local_date = pd.Timestamp(week_row["week_end_local_date"]).date()
        frozen_origin_local_date = week_start_local_date - timedelta(days=1)
        week_part = frozen[
            (frozen["forecast_origin_local_date"] == frozen_origin_local_date)
            & (frozen["target_local_date"] >= week_start_local_date)
            & (frozen["target_local_date"] <= week_end_local_date)
        ].copy()
        if week_part.empty:
            continue

        week_part = (
            week_part.sort_values(["model", "target_timestamp_utc", "forecast_origin_utc"])
            .drop_duplicates(subset=["model", "target_timestamp_utc"], keep="last")
            .reset_index(drop=True)
        )
        week_part["selected_week_category"] = str(week_row["category"])
        week_part["selected_week_iso_week_id"] = str(week_row["iso_week_id"])
        week_frames.append(week_part)

    if not week_frames:
        return pd.DataFrame()

    return (
        pd.concat(week_frames, ignore_index=True)
        .sort_values(["comparison_order", "forecast_origin_utc", "target_timestamp_local"])
        .reset_index(drop=True)
    )


def _build_week_actual_series(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    split_name: str,
    week_start_local_date: str,
    week_end_local_date: str,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(columns=["target_timestamp_local", "y_true"])

    actual = predictions[predictions["dataset_split"] == split_name][["target_timestamp_utc", "y_true"]].copy()
    if actual.empty:
        return pd.DataFrame(columns=["target_timestamp_local", "y_true"])

    actual["target_timestamp_utc"] = pd.to_datetime(actual["target_timestamp_utc"], utc=True)
    actual["target_timestamp_local"] = actual["target_timestamp_utc"].dt.tz_convert(config.resolved_business_timezone())
    actual = (
        actual.drop_duplicates(subset=["target_timestamp_utc"])
        .sort_values("target_timestamp_utc")
        .reset_index(drop=True)
    )
    actual = filter_week_window(
        actual,
        week_start_local_date=week_start_local_date,
        week_end_local_date=week_end_local_date,
        timestamp_col="target_timestamp_local",
    )
    return actual[["target_timestamp_local", "y_true"]].reset_index(drop=True)


def _prepare_report_figure(figsize: tuple[float, float]) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(REPORT_FIGURE_FACE)
    ax.set_facecolor(REPORT_AX_FACE)
    for spine in ax.spines.values():
        spine.set_color(REPORT_SPINE)
        spine.set_linewidth(1.0)
    ax.grid(color=REPORT_GRID, alpha=0.6, linewidth=0.8)
    ax.tick_params(colors=REPORT_MUTED, labelsize=10)
    ax.set_axisbelow(True)
    return fig, ax


def _prepare_report_subplot_grid(
    rows: int,
    cols: int,
    figsize: tuple[float, float],
    sharex: bool = False,
    sharey: bool = False,
):
    fig, axes = plt.subplots(rows, cols, figsize=figsize, sharex=sharex, sharey=sharey)
    fig.patch.set_facecolor(REPORT_FIGURE_FACE)
    axes_array = np.atleast_1d(axes).reshape(rows, cols)
    for row_axes in axes_array:
        for ax in row_axes:
            ax.set_facecolor(REPORT_AX_FACE)
            for spine in ax.spines.values():
                spine.set_color(REPORT_SPINE)
                spine.set_linewidth(1.0)
            ax.grid(color=REPORT_GRID, alpha=0.6, linewidth=0.8)
            ax.tick_params(colors=REPORT_MUTED, labelsize=10)
            ax.set_axisbelow(True)
    return fig, axes_array


def _finish_report_axis(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=14, fontweight="bold", color=REPORT_TEXT, pad=10)
    ax.set_xlabel(xlabel, color=REPORT_MUTED, fontsize=11, labelpad=8)
    ax.set_ylabel(ylabel, color=REPORT_MUTED, fontsize=11, labelpad=8)


def _save_and_close_figure(fig: plt.Figure, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return output_path


def write_standard_week_selection_plots(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    selected_weeks: pd.DataFrame,
    output_dir: Path,
    model_order: list[str],
    model_styles: dict[str, dict[str, object]],
    split_name: str = "test",
    reporting_level: str = "d_only",
    title_prefix: str = "Forecast vs actual",
) -> list[Path]:
    selected = select_week_reporting_slice(
        predictions=predictions,
        config=config,
        selected_weeks=selected_weeks,
        split_name=split_name,
        models=model_order,
        reporting_level=reporting_level,
    )
    if selected.empty or selected_weeks.empty:
        return []

    selected = selected.sort_values(["comparison_order", "target_timestamp_local"]).reset_index(drop=True)
    paths: list[Path] = []
    for week_row in selected_weeks.to_dict(orient="records"):
        week_frame = filter_week_window(
            selected,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
            timestamp_col="target_timestamp_local",
        )
        if week_frame.empty:
            continue

        fig, ax = _prepare_report_figure((15.0, 4.8))
        actual = _build_week_actual_series(
            predictions=predictions,
            config=config,
            split_name=split_name,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
        )
        ax.plot(actual["target_timestamp_local"], actual["y_true"], color=REPORT_ACTUAL, linewidth=2.8, label="Actual")
        for model_name in model_order:
            model_frame = week_frame[week_frame["model"] == model_name].copy()
            if model_frame.empty:
                continue
            model_frame = model_frame.sort_values("target_timestamp_local")
            style = model_styles.get(model_name, {})
            ax.plot(
                model_frame["target_timestamp_local"],
                model_frame["y_pred"],
                color=str(style.get("color", REPORT_PALETTE[0])),
                linestyle=str(style.get("linestyle", "-")),
                linewidth=float(style.get("linewidth", 2.0)),
                alpha=float(style.get("alpha", 0.92)),
                label=str(style.get("label", model_name)),
            )
        _finish_report_axis(
            ax,
            title=f"{title_prefix}: {week_row['category'].replace('_', ' ').title()} ({week_row['iso_week_id']})",
            xlabel="Local timestamp",
            ylabel="EUR/MWh",
        )
        if reporting_level == "stitched_all_horizon" and "forecast_origin_local" in week_frame.columns:
            origin_candidates = week_frame["forecast_origin_local"].dropna().sort_values()
            if not origin_candidates.empty:
                origin_local = pd.Timestamp(origin_candidates.iloc[0])
                ax.text(
                    0.0,
                    1.01,
                    f"Frozen origin: {origin_local.strftime('%d %b %Y %H:%M %Z')}",
                    transform=ax.transAxes,
                    ha="left",
                    va="bottom",
                    fontsize=10,
                    color=REPORT_MUTED,
                )
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        ax.margins(x=0.01)
        ax.legend(loc="best", ncol=2 if len(model_order) >= 3 else 1)
        fig.autofmt_xdate()
        paths.append(_save_and_close_figure(fig, output_dir / f"{week_row['category']}_{reporting_level}_forecast_vs_actual.png"))
    return paths


def write_horizon_error_plot(
    metrics_by_lead_day: pd.DataFrame,
    output_path: Path,
    model_order: list[str],
    model_styles: dict[str, dict[str, object]],
    splits: tuple[str, ...] = ("validation", "test"),
    metric_col: str = "mae",
) -> Path | None:
    if metrics_by_lead_day.empty:
        return None

    available_splits = [split_name for split_name in splits if split_name in metrics_by_lead_day["dataset_split"].astype(str).unique()]
    if not available_splits:
        return None

    fig, axes = _prepare_report_subplot_grid(1, len(available_splits), figsize=(6.2 * len(available_splits), 4.4), sharey=True)
    for axis_index, split_name in enumerate(available_splits):
        ax = axes[0, axis_index]
        split_frame = metrics_by_lead_day[metrics_by_lead_day["dataset_split"] == split_name].copy()
        split_frame = split_frame.sort_values(["comparison_order", "lead_day"])
        tick_frame = split_frame[["lead_day", "lead_day_label"]].drop_duplicates().sort_values("lead_day")
        for model_name in model_order:
            model_frame = split_frame[split_frame["model"] == model_name].copy()
            if model_frame.empty:
                continue
            style = model_styles.get(model_name, {})
            ax.plot(
                model_frame["lead_day"],
                model_frame[metric_col],
                color=str(style.get("color", REPORT_PALETTE[0])),
                linestyle=str(style.get("linestyle", "-")),
                linewidth=float(style.get("linewidth", 2.0)),
                marker="o",
                markersize=5,
                label=str(style.get("label", model_name)),
            )
        ax.set_xticks(tick_frame["lead_day"].tolist())
        ax.set_xticklabels(tick_frame["lead_day_label"].tolist())
        _finish_report_axis(ax, f"{split_name.title()}", "Lead day", metric_col.upper())
    handles, labels = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 4), bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Error by horizon", x=0.01, y=1.05, ha="left", fontsize=15, fontweight="bold", color=REPORT_TEXT)
    return _save_and_close_figure(fig, output_path)


def write_mae_by_hour_of_day_plot(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    output_path: Path,
    model_order: list[str],
    model_styles: dict[str, dict[str, object]],
    split_name: str = "test",
    reporting_level: str = "d_only",
) -> Path | None:
    sliced = select_prediction_slice(
        predictions=predictions,
        config=config,
        split_name=split_name,
        models=model_order,
        reporting_level=reporting_level,
        unique_targets=True,
    )
    if sliced.empty:
        return None

    scored = add_error_columns(sliced)
    if "target_hour_local" not in scored.columns:
        scored["target_hour_local"] = scored["target_timestamp_local"].dt.hour
    hourly_mae = (
        scored.groupby(["model", "display_name", "target_hour_local"], as_index=False)["abs_error"]
        .mean()
        .sort_values(["model", "target_hour_local"])
    )

    fig, ax = _prepare_report_figure((10.0, 4.4))
    for model_name in model_order:
        model_frame = hourly_mae[hourly_mae["model"] == model_name].copy()
        if model_frame.empty:
            continue
        style = model_styles.get(model_name, {})
        ax.plot(
            model_frame["target_hour_local"],
            model_frame["abs_error"],
            color=str(style.get("color", REPORT_PALETTE[0])),
            linestyle=str(style.get("linestyle", "-")),
            linewidth=float(style.get("linewidth", 2.0)),
            marker="o",
            markersize=4,
            label=str(style.get("label", model_name)),
        )
    ax.set_xticks(list(range(24)))
    _finish_report_axis(ax, "MAE by hour of day", "Local delivery hour", "MAE")
    ax.legend(loc="best", ncol=2 if len(model_order) >= 3 else 1)
    return _save_and_close_figure(fig, output_path)


def write_residual_distribution_plot(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    output_path: Path,
    model_order: list[str],
    model_styles: dict[str, dict[str, object]],
    split_name: str = "test",
    reporting_level: str = "d_only",
    bins: int = 40,
) -> Path | None:
    sliced = select_prediction_slice(
        predictions=predictions,
        config=config,
        split_name=split_name,
        models=model_order,
        reporting_level=reporting_level,
        unique_targets=True,
    )
    if sliced.empty:
        return None

    scored = add_error_columns(sliced)
    scored = scored[np.isfinite(scored["error"].astype(float))].copy()
    if scored.empty:
        return None

    q_low = float(scored["error"].quantile(0.01))
    q_high = float(scored["error"].quantile(0.99))
    fig, ax = _prepare_report_figure((10.0, 4.4))
    for model_name in model_order:
        model_frame = scored[scored["model"] == model_name].copy()
        if model_frame.empty:
            continue
        clipped = model_frame["error"].clip(lower=q_low, upper=q_high)
        style = model_styles.get(model_name, {})
        ax.hist(
            clipped,
            bins=bins,
            density=True,
            histtype="step",
            linewidth=float(style.get("linewidth", 2.0)),
            color=str(style.get("color", REPORT_PALETTE[0])),
            label=str(style.get("label", model_name)),
        )
    ax.axvline(0.0, color="#7b8895", linewidth=1.2, linestyle="--")
    _finish_report_axis(ax, "Residual distribution", "Prediction error (EUR/MWh)", "Density")
    ax.legend(loc="best", ncol=2 if len(model_order) >= 3 else 1)
    return _save_and_close_figure(fig, output_path)


def write_actual_vs_predicted_scatter_plot(
    predictions: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    output_path: Path,
    model_order: list[str],
    model_styles: dict[str, dict[str, object]],
    split_name: str = "test",
    reporting_level: str = "d_only",
) -> Path | None:
    sliced = select_prediction_slice(
        predictions=predictions,
        config=config,
        split_name=split_name,
        models=model_order,
        reporting_level=reporting_level,
        unique_targets=True,
    )
    if sliced.empty:
        return None

    subset_models = [model_name for model_name in model_order if model_name in sliced["model"].astype(str).unique()]
    if not subset_models:
        return None

    n_models = len(subset_models)
    cols = min(n_models, 2)
    rows = int(math.ceil(n_models / cols))
    fig, axes = _prepare_report_subplot_grid(rows, cols, figsize=(6.0 * cols, 4.6 * rows), sharex=True, sharey=True)
    valid = sliced[np.isfinite(sliced["y_true"].astype(float)) & np.isfinite(sliced["y_pred"].astype(float))].copy()
    lower = float(min(valid["y_true"].min(), valid["y_pred"].min()))
    upper = float(max(valid["y_true"].max(), valid["y_pred"].max()))

    for index, model_name in enumerate(subset_models):
        ax = axes[index // cols, index % cols]
        model_frame = valid[valid["model"] == model_name].copy()
        style = model_styles.get(model_name, {})
        ax.scatter(
            model_frame["y_true"],
            model_frame["y_pred"],
            s=10,
            alpha=0.18,
            color=str(style.get("color", REPORT_PALETTE[0])),
            edgecolors="none",
        )
        ax.plot([lower, upper], [lower, upper], linestyle="--", linewidth=1.2, color="#7b8895")
        ax.set_xlim(lower, upper)
        ax.set_ylim(lower, upper)
        _finish_report_axis(ax, str(style.get("label", model_name)), "Actual", "Predicted")

    for index in range(n_models, rows * cols):
        axes[index // cols, index % cols].set_visible(False)

    fig.suptitle("Actual vs predicted", x=0.01, y=1.02, ha="left", fontsize=15, fontweight="bold", color=REPORT_TEXT)
    return _save_and_close_figure(fig, output_path)


def build_dm_summary_table(
    dm_reporting: pd.DataFrame,
    challenger_display_order: list[str] | None = None,
    alpha: float = 0.05,
) -> pd.DataFrame:
    if dm_reporting.empty:
        return pd.DataFrame()

    table = dm_reporting.copy()
    if "reporting_level" in table.columns:
        table = table[table["reporting_level"].astype(str) != "guidance_only"].copy()
    if table.empty:
        return pd.DataFrame()

    def _verdict(row: pd.Series) -> str:
        dm_stat = row.get("dm_stat")
        p_value = row.get("p_value")
        if pd.isna(dm_stat) or pd.isna(p_value):
            return "Insufficient data"
        if float(p_value) >= alpha:
            return "No significant difference"
        return "Challenger better" if float(dm_stat) < 0.0 else "Benchmark better"

    table["verdict"] = table.apply(_verdict, axis=1)
    if challenger_display_order:
        order_map = {name: position for position, name in enumerate(challenger_display_order)}
        table["_challenger_order"] = table["challenger_display_name"].map(order_map).fillna(len(order_map))
    else:
        table["_challenger_order"] = 0

    return (
        table[
            [
                "dataset_split",
                "challenger_display_name",
                "benchmark_display_name",
                "reporting_level_label",
                "n_obs",
                "dm_stat",
                "p_value",
                "verdict",
                "_challenger_order",
            ]
        ]
        .rename(
            columns={
                "dataset_split": "Split",
                "challenger_display_name": "Challenger",
                "benchmark_display_name": "Benchmark",
                "reporting_level_label": "Reporting level",
                "n_obs": "Observations",
                "dm_stat": "DM stat",
                "p_value": "p-value",
                "verdict": "Verdict",
            }
        )
        .sort_values(["Split", "_challenger_order", "Reporting level"])
        .drop(columns=["_challenger_order"])
        .reset_index(drop=True)
    )


def style_dm_summary_table(dm_summary: pd.DataFrame):
    if dm_summary.empty:
        return dm_summary

    styler = dm_summary.style.hide(axis="index")
    styler = styler.format(
        {
            "Observations": "{:,.0f}",
            "DM stat": lambda value: "-" if pd.isna(value) else f"{float(value):.2f}",
            "p-value": lambda value: "-" if pd.isna(value) else ("<0.001" if float(value) < 0.001 else f"{float(value):.3f}"),
        }
    )
    styler = styler.map(
        lambda value: "background-color: #e4f1e6; color: #1e5a2b; font-weight: 700;"
        if value == "Challenger better"
        else (
            "background-color: #f7e4e4; color: #7a2f2f; font-weight: 700;"
            if value == "Benchmark better"
            else "background-color: #f7f8fa; color: #52606d;"
        ),
        subset=["Verdict"],
    )
    styler = styler.set_table_styles(
        [
            {"selector": "", "props": [("border-collapse", "collapse"), ("width", "100%"), ("font-size", "12px")]},
            {"selector": "th", "props": [("background", "#edf3f7"), ("color", REPORT_TEXT), ("padding", "8px 10px"), ("border", "1px solid #dce5eb")]},
            {"selector": "td", "props": [("padding", "8px 10px"), ("border", "1px solid #e8edf1")]},
        ],
        overwrite=False,
    )
    return styler


def build_runtime_summary_table(
    timing_summary: pd.DataFrame,
    model_order: list[str],
) -> pd.DataFrame:
    if timing_summary.empty:
        return pd.DataFrame()

    table = timing_summary[
        [
            "display_name",
            "dataset_split",
            "origins",
            "fit_time_mean_sec",
            "predict_time_mean_sec",
            "fit_time_max_sec",
            "fit_time_warning_count",
        ]
    ].rename(
        columns={
            "display_name": "Model",
            "dataset_split": "Split",
            "origins": "Origins",
            "fit_time_mean_sec": "Fit mean (s)",
            "predict_time_mean_sec": "Predict mean (s)",
            "fit_time_max_sec": "Fit max (s)",
            "fit_time_warning_count": "Fit warnings",
        }
    )
    order_map = {name: position for position, name in enumerate(model_order)}
    split_order = {"validation": 0, "test": 1}
    table["_model_order"] = table["Model"].map(order_map).fillna(len(order_map))
    table["_split_order"] = table["Split"].map(split_order).fillna(99)
    return table.sort_values(["_model_order", "_split_order"]).drop(columns=["_model_order", "_split_order"]).reset_index(drop=True)


def _format_runtime_seconds(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    value = float(value)
    if value >= 10.0:
        return f"{value:.1f}"
    if value >= 1.0:
        return f"{value:.2f}"
    if value >= 0.1:
        return f"{value:.3f}"
    return f"{value:.4f}"


def style_runtime_summary_table(runtime_summary: pd.DataFrame):
    if runtime_summary.empty:
        return runtime_summary

    styler = runtime_summary.style.hide(axis="index")
    styler = styler.format(
        {
            "Origins": "{:,.0f}",
            "Fit mean (s)": _format_runtime_seconds,
            "Predict mean (s)": _format_runtime_seconds,
            "Fit max (s)": _format_runtime_seconds,
            "Fit warnings": "{:,.0f}",
        }
    )
    styler = styler.map(
        lambda value: "background-color: #f7e4e4; color: #7a2f2f; font-weight: 700;" if float(value) > 0.0 else "",
        subset=["Fit warnings"],
    )
    styler = styler.set_table_styles(
        [
            {"selector": "", "props": [("border-collapse", "collapse"), ("width", "100%"), ("font-size", "12px")]},
            {"selector": "th", "props": [("background", "#edf3f7"), ("color", REPORT_TEXT), ("padding", "8px 10px"), ("border", "1px solid #dce5eb")]},
            {"selector": "td", "props": [("padding", "8px 10px"), ("border", "1px solid #e8edf1")]},
        ],
        overwrite=False,
    )
    return styler
