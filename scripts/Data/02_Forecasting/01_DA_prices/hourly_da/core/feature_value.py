from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..models.branched import BranchedForecastModel
from ..models.lear import LEARModel, LEARSettings
from ..models.prophet_model import ProphetModel, ProphetSettings
from ..models.xgboost_model import XGBoostModel, XGBoostSettings
from .ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_VERSION,
    fs2_ablation_scheme_payload,
    fs2_block_map_from_feature_columns,
    fs3_ablation_scheme_payload,
    fs3_block_map_from_feature_columns,
)
from .config import HourlyDAPipelineConfig
from .external_features import FS3Experiment
from .feature_families import supported_feature_families
from .metrics import (
    add_rmae_alias_column,
    add_error_columns,
    build_inherited_rmae_reference_snapshot,
    pairwise_dm_results,
    pairwise_dm_results_by_reporting_level,
    rmae_policy_snapshot,
    summarize_metrics_by_lead_day,
    summarize_metrics_by_reporting_level,
    summarize_overall_metrics,
)
from .reporting import load_csv, load_json, reporting_level_specs
from .storage import write_csv, write_json
from .tabular import feature_columns_for_fs_level
from .tuning import effective_policy_summary


PARENT_BENCHMARK_RUN_LABELS = {
    ("lear", "FS1"): "lear_fs1_benchmark",
    ("xgboost", "FS1"): "xgboost_fs1_benchmark",
    ("lear", "FS2"): "lear_fs2_benchmark",
    ("xgboost", "FS2"): "xgboost_fs2_benchmark",
    ("prophet", "FS2"): "prophet_benchmark",
}

COMPATIBILITY_CONFIG_KEYS = (
    "target_col",
    "feature_source_col",
    "known_at_col",
    "train_start_local",
    "train_end_local",
    "validation_start_local",
    "validation_end_local",
    "test_start_local",
    "test_end_local",
    "forecast_horizon_days",
    "forecast_origin_local_hour",
    "forecast_origin_local_minute",
    "origin_step_days",
    "timestamp_col",
    "business_timezone",
)

PARENT_CONTEXT_REQUIRED_FILES = (
    "run_summary.json",
    "config_snapshot.json",
    "methodology_snapshot.json",
    "model_settings_summary.csv",
    "official_naive_reference.json",
    "metrics_overall.csv",
    "metrics_by_lead_day.csv",
    "metrics_by_reporting_level.csv",
    "predictions_long.parquet",
)


@dataclass(frozen=True)
class ParentRunContext:
    run_id: str
    run_label: str
    run_dir: Path
    model_name: str
    model_family: str
    fs_level: str
    run_summary: dict[str, object]
    config_snapshot: dict[str, object]
    methodology_snapshot: dict[str, object]
    official_naive_reference: dict[str, object]
    model_settings_row: dict[str, object]
    settings_payload: dict[str, object]
    metrics_overall: pd.DataFrame
    metrics_by_lead_day: pd.DataFrame
    metrics_by_reporting_level: pd.DataFrame
    predictions_long: pd.DataFrame
    inherited_rmae_overall: pd.DataFrame
    inherited_rmae_by_reporting_level: pd.DataFrame
    inherited_rmae_by_lead_day: pd.DataFrame
    compatibility_snapshot: dict[str, object]


def _run_label_from_run_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _matching_run_dirs(output_root: Path, run_label: str) -> list[Path]:
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        return []
    return sorted(
        [
            candidate
            for candidate in run_root.iterdir()
            if candidate.is_dir() and _run_label_from_run_dir_name(candidate.name) == str(run_label)
        ]
    )


def _missing_required_artifacts(run_dir: Path) -> list[str]:
    missing: list[str] = []
    for filename in PARENT_CONTEXT_REQUIRED_FILES:
        if not (run_dir / filename).exists():
            missing.append(filename)
    return missing


def _expected_parent_run_label(model_family: str, fs_level: str) -> str:
    key = (str(model_family), str(fs_level))
    if key not in PARENT_BENCHMARK_RUN_LABELS:
        raise ValueError(f"No parent benchmark label is registered for {model_family} at {fs_level}.")
    return PARENT_BENCHMARK_RUN_LABELS[key]


def _critical_config_subset(snapshot: dict[str, object]) -> dict[str, object]:
    return {key: snapshot.get(key) for key in COMPATIBILITY_CONFIG_KEYS}


def _reporting_level_definition_snapshot() -> list[dict[str, object]]:
    return [spec.to_columns() for spec in reporting_level_specs()]


def _extract_parent_model_settings_row(
    model_settings_summary: pd.DataFrame,
    *,
    model_family: str,
    fs_level: str,
) -> dict[str, object]:
    target_rows = model_settings_summary[
        (model_settings_summary["model_family"].astype(str) == str(model_family))
        & (model_settings_summary["fs_level"].astype(str) == str(fs_level))
    ].copy()
    if target_rows.empty:
        raise RuntimeError(
            f"Parent run is missing a model_settings_summary row for {model_family} at {fs_level}."
        )
    if target_rows.shape[0] != 1:
        raise RuntimeError(
            f"Parent run has {target_rows.shape[0]} matching model settings rows for {model_family} at {fs_level}; expected exactly one."
        )
    return target_rows.iloc[0].to_dict()


def _parse_settings_payload(model_settings_row: dict[str, object]) -> dict[str, object]:
    settings_json = model_settings_row.get("settings_json")
    if not isinstance(settings_json, str) or not settings_json.strip():
        raise RuntimeError("Parent model settings row is missing settings_json.")
    payload = json.loads(settings_json)
    if not isinstance(payload, dict):
        raise RuntimeError("Parent model settings payload must be a JSON object.")
    return payload


def _validate_reporting_level_definition(parent_metrics: pd.DataFrame) -> dict[str, object]:
    expected = pd.DataFrame(_reporting_level_definition_snapshot()).sort_values("reporting_level").reset_index(drop=True)
    observed_cols = [
        "reporting_level",
        "reporting_level_label",
        "reporting_level_sort_order",
        "reporting_lead_days",
        "reporting_lead_day_start",
        "reporting_lead_day_end",
        "reporting_lead_day_count",
    ]
    observed = (
        parent_metrics[observed_cols]
        .drop_duplicates(subset=["reporting_level"])
        .sort_values("reporting_level")
        .reset_index(drop=True)
    )
    if observed.empty or expected.to_dict(orient="records") != observed.to_dict(orient="records"):
        raise RuntimeError("Parent metrics_by_reporting_level.csv is incompatible with the current reporting-level definition.")
    return {"expected_reporting_levels": expected.to_dict(orient="records")}


def _materialize_inherited_rmae_denominators(
    official_naive_reference: dict[str, object],
    metrics_overall: pd.DataFrame,
    metrics_by_lead_day: pd.DataFrame,
    metrics_by_reporting_level: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    benchmark_model = str(official_naive_reference["model"])
    overall = (
        metrics_overall.loc[metrics_overall["model"].astype(str) == benchmark_model, ["dataset_split", "mae"]]
        .rename(columns={"mae": "inherited_benchmark_mae"})
        .reset_index(drop=True)
    )
    by_reporting = (
        metrics_by_reporting_level.loc[
            metrics_by_reporting_level["model"].astype(str) == benchmark_model,
            ["dataset_split", "reporting_level", "mae"],
        ]
        .rename(columns={"mae": "inherited_benchmark_mae"})
        .reset_index(drop=True)
    )
    by_lead_day = (
        metrics_by_lead_day.loc[
            metrics_by_lead_day["model"].astype(str) == benchmark_model,
            ["dataset_split", "lead_day", "lead_day_label", "mae"],
        ]
        .rename(columns={"mae": "inherited_benchmark_mae"})
        .reset_index(drop=True)
    )
    if overall.empty or by_reporting.empty or by_lead_day.empty:
        raise RuntimeError("Parent run is missing the metrics needed to materialize inherited rMAE denominators.")
    return overall, by_reporting, by_lead_day


def _apply_inherited_rmae(
    metrics: pd.DataFrame,
    *,
    denominators: pd.DataFrame,
    join_keys: list[str],
    output_col: str = "rmae_vs_official_naive",
) -> pd.DataFrame:
    merged = metrics.merge(denominators, on=join_keys, how="left")
    if merged["inherited_benchmark_mae"].isna().any():
        missing = merged.loc[merged["inherited_benchmark_mae"].isna(), join_keys].drop_duplicates()
        raise RuntimeError(
            "Missing inherited rMAE denominator rows for the child metrics. "
            f"Missing keys: {missing.to_dict(orient='records')}"
    )
    merged[output_col] = merged["mae"] / merged["inherited_benchmark_mae"]
    merged.loc[merged["inherited_benchmark_mae"] == 0.0, output_col] = np.nan
    merged = merged.drop(columns=["inherited_benchmark_mae"])
    return add_rmae_alias_column(merged, source_col=output_col)


def _resolve_parent_context_from_run_dir(
    config: HourlyDAPipelineConfig,
    *,
    model_family: str,
    fs_level: str,
    run_label: str,
    run_dir: Path,
) -> ParentRunContext:
    run_summary = load_json(run_dir, "run_summary.json")
    if "policy_snapshot" not in run_summary:
        raise RuntimeError("Parent run is missing the Phase 2 policy snapshot in run_summary.json.")
    if "rmae_policy" not in run_summary:
        raise RuntimeError("Parent run is missing the Phase 2 rMAE policy metadata in run_summary.json.")

    config_snapshot = load_json(run_dir, "config_snapshot.json")
    methodology_snapshot = load_json(run_dir, "methodology_snapshot.json")
    model_settings_summary = load_csv(run_dir, "model_settings_summary.csv")
    official_naive_reference = load_json(run_dir, "official_naive_reference.json")
    metrics_overall = load_csv(run_dir, "metrics_overall.csv")
    metrics_by_lead_day = load_csv(run_dir, "metrics_by_lead_day.csv")
    metrics_by_reporting_level = load_csv(run_dir, "metrics_by_reporting_level.csv")
    predictions_long = load_csv(run_dir, "predictions_long.csv")

    current_subset = _critical_config_subset(config.to_json_dict())
    parent_subset = _critical_config_subset(config_snapshot)
    if current_subset != parent_subset:
        raise RuntimeError(
            "Parent run failed compatibility checks for methodology-critical config fields. "
            f"Current={current_subset}, parent={parent_subset}"
        )

    reporting_snapshot = _validate_reporting_level_definition(metrics_by_reporting_level)
    model_settings_row = _extract_parent_model_settings_row(
        model_settings_summary,
        model_family=model_family,
        fs_level=fs_level,
    )
    settings_payload = _parse_settings_payload(model_settings_row)
    overall_denominators, reporting_denominators, lead_day_denominators = _materialize_inherited_rmae_denominators(
        official_naive_reference,
        metrics_overall,
        metrics_by_lead_day,
        metrics_by_reporting_level,
    )

    return ParentRunContext(
        run_id=str(run_summary["run_id"]),
        run_label=str(run_summary.get("run_label") or run_label or _run_label_from_run_dir_name(run_dir.name)),
        run_dir=run_dir,
        model_name=str(model_settings_row["model"]),
        model_family=str(model_family),
        fs_level=str(fs_level),
        run_summary=run_summary,
        config_snapshot=config_snapshot,
        methodology_snapshot=methodology_snapshot,
        official_naive_reference=official_naive_reference,
        model_settings_row=model_settings_row,
        settings_payload=settings_payload,
        metrics_overall=metrics_overall,
        metrics_by_lead_day=metrics_by_lead_day,
        metrics_by_reporting_level=metrics_by_reporting_level,
        predictions_long=predictions_long,
        inherited_rmae_overall=overall_denominators,
        inherited_rmae_by_reporting_level=reporting_denominators,
        inherited_rmae_by_lead_day=lead_day_denominators,
        compatibility_snapshot={
            "config_fields": current_subset,
            "reporting_level_definition": reporting_snapshot["expected_reporting_levels"],
            "resolved_parent_run_dir": str(run_dir),
        },
    )


def resolve_parent_stage_run(
    config: HourlyDAPipelineConfig,
    *,
    model_family: str,
    fs_level: str,
    parent_run_label: str | None = None,
) -> ParentRunContext:
    run_label = str(parent_run_label or _expected_parent_run_label(model_family, fs_level))
    candidates = _matching_run_dirs(config.output_root, run_label)
    if not candidates:
        raise FileNotFoundError(
            f"No run directories found for parent label '{run_label}' in {Path(config.output_root) / 'runs'}."
        )

    errors: list[str] = []
    for run_dir in reversed(candidates):
        missing = _missing_required_artifacts(run_dir)
        if missing:
            errors.append(f"{run_dir.name}: missing required artifacts {missing}")
            continue
        try:
            return _resolve_parent_context_from_run_dir(
                config,
                model_family=model_family,
                fs_level=fs_level,
                run_label=run_label,
                run_dir=run_dir,
            )
        except Exception as exc:
            errors.append(f"{run_dir.name}: {exc}")

    detail = "; ".join(errors[-5:]) if errors else "no compatible candidates were found"
    raise RuntimeError(f"No compatible completed parent run was found for label '{run_label}'. {detail}")


def feature_families_for_context(fs_level: str, model_family: str) -> list[str]:
    families = supported_feature_families(fs_level, model_family)
    if not families:
        raise ValueError(f"No supported feature families are defined for {model_family} at {fs_level}.")
    return families


def instantiate_child_model(parent: ParentRunContext, *, excluded_feature_family: str):
    settings_payload = dict(parent.settings_payload)
    inherited_exclusions = tuple(str(value) for value in settings_payload.get("excluded_feature_families", ()))
    settings_payload["excluded_feature_families"] = tuple(sorted(set(inherited_exclusions + (excluded_feature_family,))))
    settings_payload["fs_level"] = parent.fs_level
    settings_payload["fs3_experiment"] = None

    if parent.model_family == "lear":
        settings = LEARSettings(**settings_payload)
        return LEARModel(settings)
    if parent.model_family == "xgboost":
        settings = XGBoostSettings(**settings_payload)
        return XGBoostModel(settings)
    if parent.model_family == "prophet":
        settings = ProphetSettings(**settings_payload)
        return ProphetModel(settings)
    raise ValueError(f"Unsupported model family for ablation: {parent.model_family}")


def apply_inherited_rmae_to_child_run(child_run_dir: Path, parent: ParentRunContext, *, feature_family: str) -> None:
    predictions = load_csv(child_run_dir, "predictions_long.csv")
    scored = add_error_columns(predictions)
    overall_metrics = summarize_overall_metrics(scored)
    lead_day_metrics = summarize_metrics_by_lead_day(scored)
    reporting_metrics = summarize_metrics_by_reporting_level(scored)
    overall_metrics = _apply_inherited_rmae(
        overall_metrics,
        denominators=parent.inherited_rmae_overall,
        join_keys=["dataset_split"],
    )
    lead_day_metrics = _apply_inherited_rmae(
        lead_day_metrics,
        denominators=parent.inherited_rmae_by_lead_day,
        join_keys=["dataset_split", "lead_day", "lead_day_label"],
    )
    reporting_metrics = _apply_inherited_rmae(
        reporting_metrics,
        denominators=parent.inherited_rmae_by_reporting_level,
        join_keys=["dataset_split", "reporting_level"],
    )

    challenger_models = sorted(set(predictions["model"].astype(str)) - {str(parent.official_naive_reference["model"])})
    dm_results = pairwise_dm_results(
        predictions=scored,
        benchmark_model=str(parent.official_naive_reference["model"]),
        challenger_models=challenger_models,
    )
    dm_results_by_reporting_level = pairwise_dm_results_by_reporting_level(
        predictions=scored,
        benchmark_model=str(parent.official_naive_reference["model"]),
        challenger_models=challenger_models,
    )

    write_csv(child_run_dir / "metrics_overall.csv", overall_metrics)
    write_csv(child_run_dir / "metrics_by_lead_day.csv", lead_day_metrics)
    write_csv(child_run_dir / "metrics_by_reporting_level.csv", reporting_metrics)
    write_csv(child_run_dir / "diebold_mariano_results.csv", dm_results)
    write_csv(child_run_dir / "diebold_mariano_by_reporting_level.csv", dm_results_by_reporting_level)
    write_json(child_run_dir / "official_naive_reference.json", parent.official_naive_reference)

    summary = load_json(child_run_dir, "run_summary.json")
    summary["run_label"] = _run_label_from_run_dir_name(child_run_dir.name)
    summary["context_fs_level"] = parent.fs_level
    summary["official_naive_reference"] = parent.official_naive_reference
    summary["run_role"] = "feature_family_ablation_child"
    summary["feature_family"] = feature_family
    summary["parent_run_id"] = parent.run_id
    summary["parent_run_label"] = parent.run_label
    summary["parent_model"] = parent.model_name
    summary["parent_model_family"] = parent.model_family
    summary["parent_fs_level"] = parent.fs_level
    summary["settings_inheritance_policy"] = "reuse_parent_stage_tuned_hyperparameters"
    summary["policy_snapshot"] = effective_policy_summary(parent.fs_level, run_role="feature_family_ablation_child")
    summary["rmae_policy"] = rmae_policy_snapshot()
    summary.update(
        build_inherited_rmae_reference_snapshot(
            parent.official_naive_reference,
            source_run_id=parent.run_id,
            source_run_label=parent.run_label,
        )
    )
    summary["parent_benchmark_rmae_reference"] = build_inherited_rmae_reference_snapshot(
        parent.official_naive_reference,
        source_run_id=parent.run_id,
        source_run_label=parent.run_label,
    )
    write_json(child_run_dir / "run_summary.json", summary)


def _metric_records_from_group(group: pd.DataFrame) -> dict[str, float]:
    valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
    if valid.empty:
        return {"mae": np.nan, "rmse": np.nan, "bias": np.nan}
    mae = float(valid["abs_error"].mean())
    rmse = float(np.sqrt(valid["squared_error"].mean()))
    bias = float(valid["error"].mean())
    return {"mae": mae, "rmse": rmse, "bias": bias}


def _origin_metric_frame(
    scored: pd.DataFrame,
    *,
    denominators: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for spec in reporting_level_specs():
        subset = scored[scored["lead_day"].isin(spec.lead_days)].copy()
        if subset.empty:
            continue
        for keys, group in subset.groupby(["dataset_split", "forecast_origin_utc"], dropna=False):
            split_name, forecast_origin_utc = keys
            metric_values = _metric_records_from_group(group)
            denominator_row = denominators[
                (denominators["dataset_split"].astype(str) == str(split_name))
                & (denominators["reporting_level"].astype(str) == spec.reporting_level)
            ]
            if denominator_row.empty:
                raise RuntimeError(
                    f"Missing inherited rMAE denominator for split={split_name}, reporting_level={spec.reporting_level}."
                )
            denominator_mae = float(denominator_row["inherited_benchmark_mae"].iloc[0])
            rmae = metric_values["mae"] / denominator_mae if pd.notna(denominator_mae) and denominator_mae != 0.0 else np.nan
            for metric_name, metric_value in {**metric_values, "rmae_vs_official_naive": rmae}.items():
                rows.append(
                    {
                        "dataset_split": str(split_name),
                        "forecast_origin_utc": pd.Timestamp(forecast_origin_utc).isoformat(),
                        **spec.to_columns(),
                        "metric": metric_name,
                        "value": float(metric_value) if pd.notna(metric_value) else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def _reporting_metric_frame(
    scored: pd.DataFrame,
    *,
    denominators_overall: pd.DataFrame,
    denominators_by_reporting_level: pd.DataFrame,
) -> pd.DataFrame:
    overall = summarize_overall_metrics(scored)
    overall = _apply_inherited_rmae(
        overall,
        denominators=denominators_overall,
        join_keys=["dataset_split"],
    )
    overall_rows = overall.assign(
        reporting_level="overall",
        reporting_level_label="Overall",
        reporting_level_sort_order=-1,
        reporting_lead_days="all",
        reporting_lead_day_start=0,
        reporting_lead_day_end=4,
        reporting_lead_day_count=5,
    )
    reporting = summarize_metrics_by_reporting_level(scored)
    reporting = _apply_inherited_rmae(
        reporting,
        denominators=denominators_by_reporting_level,
        join_keys=["dataset_split", "reporting_level"],
    )
    value_cols = ["mae", "rmse", "bias", "rmae_vs_official_naive"]
    base_cols = [
        "dataset_split",
        "reporting_level",
        "reporting_level_label",
        "reporting_level_sort_order",
        "reporting_lead_days",
        "reporting_lead_day_start",
        "reporting_lead_day_end",
        "reporting_lead_day_count",
    ]
    frames = []
    for frame in (overall_rows, reporting):
        rows: list[dict[str, object]] = []
        for _, record in frame.iterrows():
            for metric_name in value_cols:
                rows.append(
                    {
                        **{column: record[column] for column in base_cols},
                        "metric": metric_name,
                        "value": float(record[metric_name]) if pd.notna(record[metric_name]) else np.nan,
                    }
                )
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True).sort_values(
        ["dataset_split", "reporting_level_sort_order", "metric"]
    ).reset_index(drop=True)


def _child_better(parent_value: float, child_value: float, metric: str) -> float:
    if pd.isna(parent_value) or pd.isna(child_value):
        return np.nan
    if metric == "bias":
        return float(abs(child_value) < abs(parent_value))
    return float(child_value < parent_value)


def build_parent_child_comparison_frames(
    parent: ParentRunContext,
    *,
    child_run_dir: Path,
    feature_family: str,
    smoke_test: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    child_predictions = load_csv(child_run_dir, "predictions_long.csv")
    parent_model_predictions = parent.predictions_long[parent.predictions_long["model"].astype(str) == parent.model_name].copy()
    child_model_predictions = child_predictions[child_predictions["model"].astype(str) == parent.model_name].copy()
    if child_model_predictions.empty:
        raise RuntimeError(f"Child run {child_run_dir} does not contain predictions for model {parent.model_name}.")

    comparison_keys = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"]
    parent_model_predictions["forecast_origin_utc"] = pd.to_datetime(parent_model_predictions["forecast_origin_utc"], utc=True)
    child_model_predictions["forecast_origin_utc"] = pd.to_datetime(child_model_predictions["forecast_origin_utc"], utc=True)
    parent_model_predictions["target_timestamp_utc"] = pd.to_datetime(parent_model_predictions["target_timestamp_utc"], utc=True)
    child_model_predictions["target_timestamp_utc"] = pd.to_datetime(child_model_predictions["target_timestamp_utc"], utc=True)

    child_keys = child_model_predictions[comparison_keys].drop_duplicates()
    parent_subset = parent_model_predictions.merge(child_keys, on=comparison_keys, how="inner")
    if parent_subset.empty:
        raise RuntimeError(f"Parent run {parent.run_id} has no overlapping predictions with child run {child_run_dir.name}.")
    if not smoke_test and parent_subset.shape[0] != child_model_predictions.shape[0]:
        raise RuntimeError(
            "Parent and child prediction sets differ under full ablation execution; chronology mismatch was detected."
        )

    parent_scored = add_error_columns(parent_subset)
    child_scored = add_error_columns(child_model_predictions)
    parent_origin = _origin_metric_frame(parent_scored, denominators=parent.inherited_rmae_by_reporting_level)
    child_origin = _origin_metric_frame(child_scored, denominators=parent.inherited_rmae_by_reporting_level)
    origin = parent_origin.merge(
        child_origin,
        on=[
            "dataset_split",
            "forecast_origin_utc",
            "reporting_level",
            "reporting_level_label",
            "reporting_level_sort_order",
            "reporting_lead_days",
            "reporting_lead_day_start",
            "reporting_lead_day_end",
            "reporting_lead_day_count",
            "metric",
        ],
        suffixes=("_parent", "_child"),
        how="inner",
    )
    origin = origin.rename(columns={"value_parent": "parent_value", "value_child": "child_value"})
    origin["delta"] = origin["child_value"] - origin["parent_value"]
    origin["relative_delta"] = origin["delta"] / origin["parent_value"].abs().replace(0.0, np.nan)

    parent_reporting = _reporting_metric_frame(
        parent_scored,
        denominators_overall=parent.inherited_rmae_overall,
        denominators_by_reporting_level=parent.inherited_rmae_by_reporting_level,
    )
    child_reporting = _reporting_metric_frame(
        child_scored,
        denominators_overall=parent.inherited_rmae_overall,
        denominators_by_reporting_level=parent.inherited_rmae_by_reporting_level,
    )
    by_reporting = parent_reporting.merge(
        child_reporting,
        on=[
            "dataset_split",
            "reporting_level",
            "reporting_level_label",
            "reporting_level_sort_order",
            "reporting_lead_days",
            "reporting_lead_day_start",
            "reporting_lead_day_end",
            "reporting_lead_day_count",
            "metric",
        ],
        suffixes=("_parent", "_child"),
        how="inner",
    )
    by_reporting = by_reporting.rename(columns={"value_parent": "parent_value", "value_child": "child_value"})
    by_reporting["delta"] = by_reporting["child_value"] - by_reporting["parent_value"]
    by_reporting["relative_delta"] = by_reporting["delta"] / by_reporting["parent_value"].abs().replace(0.0, np.nan)

    origin = origin.assign(
        model=parent.model_name,
        model_family=parent.model_family,
        fs_stage=parent.fs_level,
        comparison_type="grouped_ablation",
        feature_family=feature_family,
        parent_run_id=parent.run_id,
        parent_run_label=parent.run_label,
        child_run_id=child_run_dir.name,
        child_run_label=_run_label_from_run_dir_name(child_run_dir.name),
        ablation_policy="reuse_parent_stage_tuned_hyperparameters",
        rmae_reference_source=f"{parent.run_id}:official_naive_reference.json",
    )
    by_reporting = by_reporting.assign(
        model=parent.model_name,
        model_family=parent.model_family,
        fs_stage=parent.fs_level,
        comparison_type="grouped_ablation",
        feature_family=feature_family,
        parent_run_id=parent.run_id,
        parent_run_label=parent.run_label,
        child_run_id=child_run_dir.name,
        child_run_label=_run_label_from_run_dir_name(child_run_dir.name),
        ablation_policy="reuse_parent_stage_tuned_hyperparameters",
        rmae_reference_source=f"{parent.run_id}:official_naive_reference.json",
    )

    stability_rows: list[dict[str, object]] = []
    for keys, group in origin.groupby(["feature_family", "dataset_split", "reporting_level", "metric"], dropna=False):
        feature_family_name, split_name, reporting_level_name, metric_name = keys
        better_flags = [
            _child_better(parent_value=row["parent_value"], child_value=row["child_value"], metric=str(metric_name))
            for _, row in group.iterrows()
        ]
        stability_rows.append(
            {
                "feature_family": str(feature_family_name),
                "dataset_split": str(split_name),
                "reporting_level": str(reporting_level_name),
                "metric": str(metric_name),
                "origin_count": int(group.shape[0]),
                "mean_origin_delta": float(group["delta"].mean()),
                "std_origin_delta": float(group["delta"].std(ddof=0)) if group.shape[0] > 1 else 0.0,
                "child_better_origin_rate": float(np.nanmean(better_flags)) if better_flags else np.nan,
            }
        )
    stability = pd.DataFrame(stability_rows)
    summary = by_reporting.merge(
        stability,
        on=["feature_family", "dataset_split", "reporting_level", "metric"],
        how="left",
    )
    summary["validation_first"] = summary["dataset_split"].astype(str) == "validation"
    return (
        origin.sort_values(["feature_family", "dataset_split", "forecast_origin_utc", "reporting_level_sort_order", "metric"]).reset_index(drop=True),
        by_reporting.sort_values(["feature_family", "dataset_split", "reporting_level_sort_order", "metric"]).reset_index(drop=True),
        summary.sort_values(["feature_family", "dataset_split", "reporting_level_sort_order", "metric"]).reset_index(drop=True),
    )


def feature_family_metadata_payload(
    parent: ParentRunContext,
    *,
    aggregate_run_id: str,
    aggregate_run_label: str,
    selected_feature_families: list[str],
    smoke_test: bool,
    smoke_origins_per_split: int | None,
) -> dict[str, object]:
    return {
        "run_id": aggregate_run_id,
        "run_label": aggregate_run_label,
        "run_role": "feature_family_ablation_aggregate",
        "model": parent.model_name,
        "model_family": parent.model_family,
        "fs_stage": parent.fs_level,
        "parent_run_id": parent.run_id,
        "parent_run_label": parent.run_label,
        "settings_inheritance_policy": "reuse_parent_stage_tuned_hyperparameters",
        "selected_feature_families": selected_feature_families,
        "smoke_test": bool(smoke_test),
        "smoke_origins_per_split": int(smoke_origins_per_split) if smoke_origins_per_split is not None else None,
        "validation_first_decision_rule": True,
        "test_is_observational_only": True,
        "policy_snapshot": effective_policy_summary(parent.fs_level, run_role="feature_family_ablation_aggregate"),
        "rmae_policy": rmae_policy_snapshot(),
        "parent_benchmark_rmae_reference": build_inherited_rmae_reference_snapshot(
            parent.official_naive_reference,
            source_run_id=parent.run_id,
            source_run_label=parent.run_label,
        ),
        "compatibility_snapshot": parent.compatibility_snapshot,
        "future_fs3_taxonomy_inventory_hint": "scripts/Data/02_Forecasting/01_DA_prices/docs/fs3_taxonomy_inventory.csv",
    }


def _stable_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _model_branch_map(model) -> dict[str, object]:
    if isinstance(model, BranchedForecastModel):
        return model.branch_models()
    if hasattr(model, "branch_models"):
        return dict(model.branch_models())
    return {"main": model}


def _build_staged_ablation_preflight(
    *,
    config: HourlyDAPipelineConfig,
    model,
    fs_level: str,
    scheme_name: str,
    target_block: str | None = None,
    experiment_map: dict[str, object] | None = None,
) -> dict[str, object]:
    if str(fs_level) == "FS2":
        scheme_payload = fs2_ablation_scheme_payload(
            scheme_name=scheme_name,
            target_block=target_block,
        )
    elif str(fs_level) == "FS3":
        if experiment_map is None:
            raise ValueError("FS3 preflight requires an experiment_map.")
        scheme_payload = fs3_ablation_scheme_payload(
            experiment_map,
            scheme_name=scheme_name,
            target_block=target_block,
        )
    else:
        raise ValueError(f"Unsupported staged ablation fs_level: {fs_level}")
    assignment_rows: list[dict[str, object]] = []
    block_size_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    effective_branch_payload: list[dict[str, object]] = []

    for branch_name, branch_model in _model_branch_map(model).items():
        settings = getattr(branch_model, "settings", None)
        fs_level = str(getattr(settings, "fs_level", branch_model.fs_level))
        fs3_experiment = getattr(settings, "fs3_experiment", None)
        excluded_feature_families = tuple(
            str(value) for value in (getattr(settings, "excluded_feature_families", ()) or ())
        )
        excluded_feature_columns = tuple(
            str(value) for value in (getattr(settings, "excluded_feature_columns", ()) or ())
        )
        active_ablation_scheme_name = (
            str(getattr(settings, "ablation_scheme_name"))
            if getattr(settings, "ablation_scheme_name", None)
            else None
        )
        active_ablation_target_block = (
            str(getattr(settings, "ablation_target_block"))
            if getattr(settings, "ablation_target_block", None)
            else None
        )
        feature_columns = feature_columns_for_fs_level(
            config,
            fs_level,
            fs3_experiment=fs3_experiment,
            model_family=branch_model.family,
            excluded_feature_families=excluded_feature_families,
            excluded_feature_columns=excluded_feature_columns,
            ablation_scheme_name=active_ablation_scheme_name,
            ablation_target_block=active_ablation_target_block,
        )
        if str(scheme_name) == SCHEME_NAME_LAYER_2 and target_block:
            if str(fs_level) == "FS2":
                parent_layer1_map = fs2_block_map_from_feature_columns(
                    feature_columns,
                    scheme_name=SCHEME_NAME_LAYER_1,
                )
            elif str(fs_level) == "FS3":
                parent_layer1_map = fs3_block_map_from_feature_columns(
                    feature_columns,
                    domestic_market=str(config.market_area),
                    scheme_name=SCHEME_NAME_LAYER_1,
                )
            else:
                raise ValueError(f"Unsupported staged ablation fs_level: {fs_level}")
            feature_columns = list(parent_layer1_map.get(str(target_block), ()))
        if str(fs_level) == "FS2":
            block_map = fs2_block_map_from_feature_columns(
                feature_columns,
                scheme_name=scheme_name,
                target_block=target_block,
            )
        elif str(fs_level) == "FS3":
            block_map = fs3_block_map_from_feature_columns(
                feature_columns,
                domestic_market=str(config.market_area),
                scheme_name=scheme_name,
                target_block=target_block,
            )
        else:
            raise ValueError(f"Unsupported staged ablation fs_level: {fs_level}")
        feature_assignments: list[dict[str, object]] = []
        duplicate_columns: list[str] = []
        unassigned_columns: list[str] = []
        assigned_once_count = 0

        for column in feature_columns:
            matching_blocks = [block_name for block_name, columns in block_map.items() if str(column) in set(columns)]
            assignment_count = len(matching_blocks)
            if assignment_count == 1:
                assigned_once_count += 1
            elif assignment_count == 0:
                unassigned_columns.append(str(column))
            else:
                duplicate_columns.append(str(column))
            feature_assignments.append(
                {
                    "branch_name": str(branch_name),
                    "branch_fs_level": fs_level,
                    "feature_column": str(column),
                    "assignment_count": int(assignment_count),
                    "assigned_blocks": ", ".join(matching_blocks),
                    "is_assigned_exactly_once": bool(assignment_count == 1),
                    "is_duplicate_assignment": bool(assignment_count > 1),
                    "is_unassigned": bool(assignment_count == 0),
                }
            )

        for block_name, columns in block_map.items():
            block_size_rows.append(
                {
                    "branch_name": str(branch_name),
                    "branch_fs_level": fs_level,
                    "block_name": str(block_name),
                    "block_size": int(len(columns)),
                    "is_zero_size_block": bool(len(columns) == 0),
                    "columns": ", ".join(columns),
                }
            )

        branch_valid = not duplicate_columns and not unassigned_columns
        summary_rows.append(
            {
                "branch_name": str(branch_name),
                "branch_fs_level": fs_level,
                "total_effective_columns": int(len(feature_columns)),
                "assigned_exactly_once_count": int(assigned_once_count),
                "duplicate_assignment_count": int(len(duplicate_columns)),
                "unassigned_column_count": int(len(unassigned_columns)),
                "zero_size_block_count": int(sum(1 for columns in block_map.values() if not columns)),
                "valid": bool(branch_valid),
                "duplicate_columns": ", ".join(duplicate_columns),
                "unassigned_columns": ", ".join(unassigned_columns),
            }
        )
        assignment_rows.extend(feature_assignments)
        effective_branch_payload.append(
            {
                "branch_name": str(branch_name),
                "branch_fs_level": fs_level,
                "feature_columns": list(feature_columns),
                "block_map": {block_name: list(columns) for block_name, columns in block_map.items()},
            }
        )

    summary_frame = pd.DataFrame(summary_rows).sort_values(["branch_name"]).reset_index(drop=True)
    assignment_frame = pd.DataFrame(assignment_rows).sort_values(["branch_name", "feature_column"]).reset_index(drop=True)
    block_size_frame = pd.DataFrame(block_size_rows).sort_values(["branch_name", "block_name"]).reset_index(drop=True)

    effective_scheme_payload = {
        "scheme_name": str(scheme_name),
        "scheme_version": SCHEME_VERSION,
        "target_block": str(target_block) if target_block else None,
        "effective_branches": effective_branch_payload,
    }
    effective_scheme_hash = _stable_hash(
        {
            "scheme_payload": scheme_payload,
            "effective_scheme_payload": effective_scheme_payload,
        }
    )
    valid = bool(summary_frame["valid"].all()) if not summary_frame.empty else False
    return {
        "scheme_payload": {
            **scheme_payload,
            "static_scheme_hash": scheme_payload["scheme_hash"],
            "scheme_hash": effective_scheme_hash,
        },
        "summary": summary_frame,
        "assignments": assignment_frame,
        "block_sizes": block_size_frame,
        "valid": valid,
    }


def build_fs2_ablation_preflight(
    *,
    config: HourlyDAPipelineConfig,
    model,
    scheme_name: str,
    target_block: str | None = None,
) -> dict[str, object]:
    return _build_staged_ablation_preflight(
        config=config,
        model=model,
        fs_level="FS2",
        scheme_name=scheme_name,
        target_block=target_block,
        experiment_map=None,
    )


def build_fs3_ablation_preflight(
    *,
    config: HourlyDAPipelineConfig,
    model,
    experiment_map: dict[str, object],
    scheme_name: str,
    target_block: str | None = None,
) -> dict[str, object]:
    return _build_staged_ablation_preflight(
        config=config,
        model=model,
        fs_level="FS3",
        scheme_name=scheme_name,
        target_block=target_block,
        experiment_map=experiment_map,
    )


def _coerce_fs3_experiment_payload(value: object) -> FS3Experiment | None:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, FS3Experiment):
        return value
    if isinstance(value, dict):
        return FS3Experiment(
            code=str(value.get("code", "")),
            description=str(value.get("description", "")),
            direct_columns=tuple(str(item) for item in value.get("direct_columns", ()) or ()),
            lagged_columns=tuple(str(item) for item in value.get("lagged_columns", ()) or ()),
            lag_hours=tuple(int(item) for item in value.get("lag_hours", ()) or ()),
        )
    raise ValueError(f"Unsupported FS3 experiment payload: {value}")


def _normalized_model_settings_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    if "excluded_feature_families" in normalized and normalized["excluded_feature_families"] is not None:
        normalized["excluded_feature_families"] = tuple(str(value) for value in normalized["excluded_feature_families"])
    if "excluded_feature_columns" in normalized and normalized["excluded_feature_columns"] is not None:
        normalized["excluded_feature_columns"] = tuple(str(value) for value in normalized["excluded_feature_columns"])
    if "fs3_experiment" in normalized:
        normalized["fs3_experiment"] = _coerce_fs3_experiment_payload(normalized.get("fs3_experiment"))
    return normalized


def _excluded_feature_columns_from_settings_payload(
    *,
    fs_level: str,
    model_family: str,
    settings_payload: dict[str, object],
) -> tuple[str, ...]:
    inherited_blocks = tuple(str(value) for value in settings_payload.get("excluded_feature_families", ()))
    scheme_name = settings_payload.get("ablation_scheme_name")
    if not inherited_blocks or not scheme_name:
        return tuple()
    config = HourlyDAPipelineConfig()
    fs3_experiment = _coerce_fs3_experiment_payload(settings_payload.get("fs3_experiment"))
    base_columns = feature_columns_for_fs_level(
        config,
        str(fs_level),
        fs3_experiment=fs3_experiment,
        model_family=str(model_family),
    )
    kept_columns = feature_columns_for_fs_level(
        config,
        str(fs_level),
        fs3_experiment=fs3_experiment,
        model_family=str(model_family),
        excluded_feature_families=inherited_blocks,
        ablation_scheme_name=str(scheme_name),
        ablation_target_block=str(settings_payload.get("ablation_target_block")) if settings_payload.get("ablation_target_block") else None,
    )
    kept_set = set(kept_columns)
    return tuple(column for column in base_columns if column not in kept_set)


def _reinstantiated_settings_payload(
    *,
    fs_level: str,
    model_family: str,
    base_payload: dict[str, object],
    override_exclusions: tuple[str, ...],
    ablation_scheme_name: str | None,
    ablation_target_block: str | None,
) -> dict[str, object]:
    normalized = _normalized_model_settings_payload(base_payload)
    inherited_exclusions = tuple(str(value) for value in normalized.get("excluded_feature_families", ()))
    inherited_scheme = str(normalized.get("ablation_scheme_name")) if normalized.get("ablation_scheme_name") else None
    persistent_columns = tuple(str(value) for value in normalized.get("excluded_feature_columns", ()))
    active_exclusions = tuple(dict.fromkeys([*inherited_exclusions, *override_exclusions]))
    if ablation_scheme_name is not None and inherited_exclusions and inherited_scheme and str(ablation_scheme_name) != inherited_scheme:
        inherited_columns = _excluded_feature_columns_from_settings_payload(
            fs_level=str(fs_level),
            model_family=str(model_family),
            settings_payload=normalized,
        )
        persistent_columns = tuple(dict.fromkeys([*persistent_columns, *inherited_columns]))
        active_exclusions = tuple(override_exclusions)

    if persistent_columns:
        normalized["excluded_feature_columns"] = persistent_columns
    elif "excluded_feature_columns" in normalized:
        normalized["excluded_feature_columns"] = tuple()

    if active_exclusions:
        normalized["excluded_feature_families"] = active_exclusions
    elif "excluded_feature_families" in normalized:
        normalized["excluded_feature_families"] = tuple()

    if ablation_scheme_name is not None:
        normalized["ablation_scheme_name"] = str(ablation_scheme_name)
    if ablation_target_block is not None or "ablation_target_block" in normalized:
        normalized["ablation_target_block"] = str(ablation_target_block) if ablation_target_block else None
    return normalized


def instantiate_model_from_parent_context(
    parent: ParentRunContext,
    *,
    excluded_feature_families: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
    settings_overrides: dict[str, object] | None = None,
    name_override: str | None = None,
):
    override_exclusions = tuple(str(value) for value in (excluded_feature_families or ()))
    settings_overrides = dict(settings_overrides or {})
    settings_payload = dict(parent.settings_payload)
    if str(settings_payload.get("branch_mode")) == "d_only_vs_guidance":
        d_payload = _reinstantiated_settings_payload(
            fs_level=parent.fs_level,
            model_family=str(settings_payload.get("d_only_model_family", parent.model_family)),
            base_payload=dict(settings_payload.get("d_only_model_settings") or {}),
            override_exclusions=override_exclusions,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
        d_payload.update(settings_overrides)
        g_payload = _reinstantiated_settings_payload(
            fs_level=parent.fs_level,
            model_family=str(settings_payload.get("guidance_model_family", parent.model_family)),
            base_payload=dict(settings_payload.get("guidance_model_settings") or {}),
            override_exclusions=override_exclusions,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
        g_payload.update(settings_overrides)
        d_family = str(settings_payload.get("d_only_model_family", parent.model_family))
        g_family = str(settings_payload.get("guidance_model_family", parent.model_family))
        if d_family == "lear":
            d_model = LEARModel(LEARSettings(**d_payload))
        elif d_family == "xgboost":
            d_model = XGBoostModel(XGBoostSettings(**d_payload))
        else:
            raise ValueError(f"Unsupported d-only branch family in parent settings: {d_family}")
        if g_family == "lear":
            g_model = LEARModel(LEARSettings(**g_payload))
        elif g_family == "xgboost":
            g_model = XGBoostModel(XGBoostSettings(**g_payload))
        else:
            raise ValueError(f"Unsupported guidance branch family in parent settings: {g_family}")
        d_model.name = str(settings_payload.get("d_only_model_name", d_model.name))
        g_model.name = str(settings_payload.get("guidance_model_name", g_model.name))
        return BranchedForecastModel(
            name=str(name_override or parent.model_name),
            family=parent.model_family,
            fs_level=parent.fs_level,
            d_only_model=d_model,
            guidance_model=g_model,
        )

    normalized = _reinstantiated_settings_payload(
        fs_level=parent.fs_level,
        model_family=parent.model_family,
        base_payload=settings_payload,
        override_exclusions=override_exclusions,
        ablation_scheme_name=ablation_scheme_name,
        ablation_target_block=ablation_target_block,
    )
    normalized.update(settings_overrides)
    if parent.model_family == "lear":
        model = LEARModel(LEARSettings(**normalized))
    elif parent.model_family == "xgboost":
        model = XGBoostModel(XGBoostSettings(**normalized))
    elif parent.model_family == "prophet":
        model = ProphetModel(ProphetSettings(**normalized))
    else:
        raise ValueError(f"Unsupported parent model family: {parent.model_family}")
    model.name = str(name_override or parent.model_name)
    return model
