from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .config import HourlyDAPipelineConfig
from .features import build_calendar_features
from .forecast_evaluation import (
    build_stitched_d_only_predictions,
    compute_topk_hour_metrics,
    load_candidate_predictions,
    normalize_prediction_schema,
)
from .reporting import load_json, load_run_model_catalog
from .visual_weeks import WEEKLY_FEATURE_COLUMNS, build_weekly_feature_table


REQUIRED_RUN_FILES: tuple[str, ...] = (
    "run_summary.json",
    "metrics_overall.csv",
    "metrics_by_lead_day.csv",
    "origin_timing_summary.csv",
)
PREDICTION_ARTIFACT_OPTIONS: tuple[str, ...] = ("predictions_long.parquet", "predictions_long.csv")
ALLOWED_RUN_ROLES: frozenset[str] = frozenset({"benchmark_parent", "aggregate_parent_comparison"})
EXCLUDED_RUN_LABEL_TOKENS: tuple[str, ...] = (
    "__",
    "feature_family_ablation",
    "pilot",
    "debug",
    "runtime_check",
)
FS_LEVEL_ORDER: dict[str, int] = {"FS0": 0, "FS1": 1, "FS2": 2, "FS3": 3, "FS4": 4}
SEASON_MAP: dict[int, str] = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}
VARIANT_COMPLEXITY: dict[str, int] = {
    "base": 0,
    "base_plus_a": 1,
    "base_plus_b": 1,
    "base_plus_c": 1,
    "base_plus_a_plus_b": 2,
    "base_plus_a_plus_b_plus_c": 3,
}
BIAS_CORRECTION_LEVEL_SPECS: dict[str, tuple[str, ...]] = {
    "season_day_type_hour": ("candidate_key", "season", "day_type", "target_local_hour"),
    "season_hour": ("candidate_key", "season", "target_local_hour"),
    "day_type_hour": ("candidate_key", "day_type", "target_local_hour"),
    "hour": ("candidate_key", "target_local_hour"),
    "global": ("candidate_key",),
}
BIAS_CORRECTION_LEVEL_PROFILES: dict[str, tuple[str, ...]] = {
    "sdth_sh_dh_h_global": ("season_day_type_hour", "season_hour", "day_type_hour", "hour", "global"),
    "sdth_h_global": ("season_day_type_hour", "hour", "global"),
    "sh_dh_h_global": ("season_hour", "day_type_hour", "hour", "global"),
    "dh_h_global": ("day_type_hour", "hour", "global"),
    "hour_global": ("hour", "global"),
    "global_only": ("global",),
}
ESSENTIAL_NOTEBOOK_ARTIFACTS: tuple[str, ...] = (
    "candidate_selection_summary.csv",
    "scenario_generation_config.json",
    "scenario_generation_run_summary.json",
    "scenario_validation_summary.csv",
    "scenario_period_quantiles.csv",
    "seasonal_regime_days.csv",
    "stress_diagnostic_days.csv",
    "selected_plot_weeks.csv",
    "final_scenario_model_comparison.csv",
    "final_scenario_recommendation.json",
    "artifact_retention_summary.json",
)
PRUNABLE_NOTEBOOK_ARTIFACTS: tuple[str, ...] = (
    "plots",
    "residual_period_table.csv",
    "residual_daily_profiles.csv",
    "scenario_prices_long.csv",
    "scenario_metadata.csv",
    "scenario_bank_logs.csv",
    "scenario_reduction_summary.csv",
)
SCENARIO_PLOT_WEEK_CATEGORIES: tuple[str, ...] = (
    "typical_winter",
    "typical_summer",
    "high_volatility",
    "low_price",
)
DAILY_PROFILE_CENTROID_COLUMNS: tuple[str, ...] = (
    "actual_daily_mean",
    "actual_daily_spread",
    "actual_daily_min",
    "abs_daily_bias",
    "negative_hours_share",
)


@dataclass(frozen=True)
class ScenarioOutputPaths:
    scenario_run_id: str
    output_dir: Path
    plots_dir: Path


@dataclass(frozen=True)
class ScenarioHorizonSpec:
    horizon_mode: str
    granularity: str
    periods_per_day: int
    horizon_days: int
    block_length: int


def resolve_scenario_horizon_spec(*, horizon_mode: str, granularity: str) -> ScenarioHorizonSpec:
    mode = str(horizon_mode).strip().upper()
    gran = str(granularity).strip().lower()
    if gran not in {"hourly", "quarter_hour"}:
        raise ValueError(f"Unsupported granularity: {granularity}")
    periods_per_day = 24 if gran == "hourly" else 96
    if mode == "D_ONLY":
        horizon_days = 1
    elif mode == "D_PLUS_4":
        horizon_days = 5
    else:
        raise ValueError(f"Unsupported horizon_mode: {horizon_mode}")
    return ScenarioHorizonSpec(
        horizon_mode=mode,
        granularity=gran,
        periods_per_day=int(periods_per_day),
        horizon_days=int(horizon_days),
        block_length=int(periods_per_day * horizon_days),
    )


def _run_label_from_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _run_timestamp_from_id(run_id: str) -> pd.Timestamp:
    parts = str(run_id).split("_", 2)
    if len(parts) < 2:
        return pd.NaT
    return pd.to_datetime(f"{parts[0]}_{parts[1]}", format="%Y%m%d_%H%M%S", utc=False, errors="coerce")


def _prediction_artifact_name(run_dir: Path) -> str | None:
    for filename in PREDICTION_ARTIFACT_OPTIONS:
        if (run_dir / filename).exists():
            return filename
    return None


def _run_is_complete(run_dir: Path) -> bool:
    return all((run_dir / filename).exists() for filename in REQUIRED_RUN_FILES) and _prediction_artifact_name(run_dir) is not None


def _prettify_candidate_identifier(candidate_id: str) -> str:
    token_map = {
        "xgboost": "XGBoost",
        "lear": "LEAR",
        "prophet": "Prophet",
        "naive": "Naive",
        "fs0": "FS0",
        "fs1": "FS1",
        "fs2": "FS2",
        "fs3": "FS3",
        "fs4": "FS4",
        "da": "DA",
    }
    tokens = [token for token in str(candidate_id).split("_") if token and token != "combo"]
    pretty_tokens: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in token_map:
            pretty_tokens.append(token_map[lowered])
        elif lowered.startswith("d+") or lowered == "d":
            pretty_tokens.append(token.upper())
        elif lowered.isdigit():
            pretty_tokens.append(lowered)
        else:
            pretty_tokens.append(lowered.replace("-", " "))
    label = " ".join(pretty_tokens).strip()
    return label[:1].upper() + label[1:] if label else str(candidate_id)


def _strip_benchmark_suffix(run_label: str) -> str:
    return str(run_label).removesuffix("_benchmark")


def _run_label_is_relevant(run_label: str) -> bool:
    lowered = str(run_label).lower()
    return not any(token in lowered for token in EXCLUDED_RUN_LABEL_TOKENS)


def _is_non_naive_model(model_name: str) -> bool:
    return not str(model_name).startswith("naive_")


def _candidate_display_group(fs_level: str) -> str:
    return str(fs_level).lower() if str(fs_level) else "unknown"


def _resolve_primary_model_name(run_label: str, catalog: pd.DataFrame) -> str | None:
    if catalog.empty:
        return None

    primary_candidate_id = _strip_benchmark_suffix(run_label)
    available_models = set(catalog["model"].astype(str).tolist())
    if primary_candidate_id in available_models:
        return primary_candidate_id

    non_naive = catalog[catalog["model"].astype(str).map(_is_non_naive_model)].copy()
    if non_naive.empty:
        return None
    if non_naive.shape[0] == 1:
        return str(non_naive.iloc[0]["model"])

    lowered_prefix = str(primary_candidate_id).split("_", 1)[0]
    family_match = non_naive[non_naive["model"].astype(str).str.startswith(lowered_prefix + "_")].copy()
    if family_match.empty:
        family_match = non_naive.copy()

    family_match["_fs_order"] = family_match["fs_level"].map(lambda value: FS_LEVEL_ORDER.get(str(value), -1))
    family_match = family_match.sort_values(["_fs_order", "model"], ascending=[False, True]).reset_index(drop=True)
    return str(family_match.iloc[0]["model"])


def _build_candidate_rows_from_aggregate(run_dir: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = load_run_model_catalog(run_dir)
    if catalog.empty:
        return []
    rows: list[dict[str, Any]] = []
    run_label = str(summary.get("run_label") or summary.get("comparison_run_label") or _run_label_from_dir_name(run_dir.name))
    for record in catalog.to_dict(orient="records"):
        model_name = str(record["model"])
        rows.append(
            {
                "candidate_key": model_name,
                "candidate_label": _prettify_candidate_identifier(model_name),
                "selected_model": model_name,
                "selected_run_dir": run_dir,
                "selected_run_id": run_dir.name,
                "run_label": run_label,
                "model_family": str(record.get("model_family") or ""),
                "fs_level": str(record.get("fs_level") or ""),
                "candidate_context": "aggregate_comparison",
                "display_group": _candidate_display_group(str(record.get("fs_level") or "")),
                "variant": "aggregate_comparison",
                "prediction_available": True,
                "run_role": "aggregate_parent_comparison",
                "run_timestamp": _run_timestamp_from_id(run_dir.name),
                "discovery_rule": "Latest aggregate comparison artifact containing this model.",
                "source_priority": 1,
            }
        )
    return rows


def _build_candidate_rows_from_benchmark(run_dir: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = load_run_model_catalog(run_dir)
    if catalog.empty:
        return []

    run_label = str(summary.get("run_label") or _run_label_from_dir_name(run_dir.name))
    rows: list[dict[str, Any]] = []
    if run_label == "naive_benchmark":
        for record in catalog.to_dict(orient="records"):
            model_name = str(record["model"])
            if _is_non_naive_model(model_name):
                continue
            rows.append(
                {
                    "candidate_key": model_name,
                    "candidate_label": _prettify_candidate_identifier(model_name),
                    "selected_model": model_name,
                    "selected_run_dir": run_dir,
                    "selected_run_id": run_dir.name,
                    "run_label": run_label,
                    "model_family": str(record.get("model_family") or ""),
                    "fs_level": str(record.get("fs_level") or ""),
                    "candidate_context": "naive_benchmark_parent",
                    "display_group": _candidate_display_group(str(record.get("fs_level") or "")),
                    "variant": "benchmark_parent",
                    "prediction_available": True,
                    "run_role": "benchmark_parent",
                    "run_timestamp": _run_timestamp_from_id(run_dir.name),
                    "discovery_rule": "Latest naive benchmark parent artifact.",
                    "source_priority": 0,
                }
            )
        return rows

    primary_model_name = _resolve_primary_model_name(run_label, catalog)
    if primary_model_name is None:
        return []

    primary_row = catalog[catalog["model"].astype(str) == str(primary_model_name)].head(1)
    if primary_row.empty:
        return []
    primary_record = primary_row.iloc[0].to_dict()
    primary_candidate_id = _strip_benchmark_suffix(run_label)
    if "_fs" not in primary_candidate_id and "_fs" in str(primary_record["model"]):
        primary_candidate_id = str(primary_record["model"])
    rows.append(
        {
            "candidate_key": primary_candidate_id,
            "candidate_label": _prettify_candidate_identifier(primary_candidate_id),
            "selected_model": str(primary_record["model"]),
            "selected_run_dir": run_dir,
            "selected_run_id": run_dir.name,
            "run_label": run_label,
            "model_family": str(primary_record.get("model_family") or ""),
            "fs_level": str(primary_record.get("fs_level") or ""),
            "candidate_context": "benchmark_parent_primary",
            "display_group": _candidate_display_group(str(primary_record.get("fs_level") or "")),
            "variant": "benchmark_parent",
            "prediction_available": True,
            "run_role": "benchmark_parent",
            "run_timestamp": _run_timestamp_from_id(run_dir.name),
            "discovery_rule": "Latest primary benchmark-parent artifact for this candidate context.",
            "source_priority": 2,
        }
    )
    return rows


def discover_scenario_candidate_sources(output_root: Path) -> dict[str, Any]:
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        raise FileNotFoundError(f"Run root does not exist: {run_root}")

    version_rows: list[dict[str, Any]] = []
    ignored_rows: list[dict[str, Any]] = []
    for run_dir in sorted(candidate for candidate in run_root.iterdir() if candidate.is_dir()):
        run_label = _run_label_from_dir_name(run_dir.name)
        if not _run_is_complete(run_dir):
            ignored_rows.append(
                {
                    "run_id": run_dir.name,
                    "run_label": run_label,
                    "status": "ignored_incomplete",
                    "reason": "Required benchmark artifacts or predictions_long were missing.",
                }
            )
            continue
        summary = load_json(run_dir, "run_summary.json")
        run_role = str(summary.get("policy_snapshot", {}).get("run_role") or "")
        if run_role not in ALLOWED_RUN_ROLES:
            ignored_rows.append(
                {
                    "run_id": run_dir.name,
                    "run_label": run_label,
                    "status": "ignored_run_role",
                    "reason": f"Run role '{run_role or 'unknown'}' is outside the scenario-discovery scope.",
                }
            )
            continue
        if not _run_label_is_relevant(run_label):
            ignored_rows.append(
                {
                    "run_id": run_dir.name,
                    "run_label": run_label,
                    "status": "ignored_non_core",
                    "reason": "Run label matches an exploratory or ablation naming pattern.",
                }
            )
            continue

        if run_role == "aggregate_parent_comparison":
            version_rows.extend(_build_candidate_rows_from_aggregate(run_dir, summary))
        else:
            version_rows.extend(_build_candidate_rows_from_benchmark(run_dir, summary))

    if not version_rows:
        raise FileNotFoundError(
            "No complete scenario candidate sources were discovered. Run the hourly DA benchmark workflow first so that "
            "saved run folders contain run_summary.json, metrics_overall.csv, metrics_by_lead_day.csv, "
            "origin_timing_summary.csv, and predictions_long.parquet or predictions_long.csv."
        )

    versions = pd.DataFrame(version_rows).sort_values(
        ["candidate_key", "run_timestamp", "source_priority", "selected_run_id"],
        ascending=[True, True, True, True],
    )
    latest = (
        versions.sort_values(["candidate_key", "run_timestamp", "source_priority"], ascending=[True, False, False])
        .drop_duplicates(subset=["candidate_key"], keep="first")
        .sort_values(["fs_level", "candidate_label", "selected_run_id"])
        .reset_index(drop=True)
    )
    latest["older_versions_found"] = latest["candidate_key"].map(
        versions.groupby("candidate_key").size().sub(1).clip(lower=0).to_dict()
    ).fillna(0).astype(int)

    availability = (
        latest[
            [
                "candidate_key",
                "candidate_label",
                "fs_level",
                "model_family",
                "run_label",
                "selected_run_id",
                "selected_model",
                "candidate_context",
                "run_role",
                "older_versions_found",
            ]
        ]
        .rename(
            columns={
                "candidate_key": "candidate_id",
                "candidate_label": "candidate_label",
                "fs_level": "fs_level",
                "model_family": "model_family",
                "run_label": "source_run_label",
                "selected_run_id": "source_run_id",
                "selected_model": "internal_model_name",
                "candidate_context": "discovery_context",
                "run_role": "source_run_role",
            }
        )
        .sort_values(["fs_level", "candidate_label", "source_run_id"], ascending=[True, True, True])
        .reset_index(drop=True)
    )

    return {
        "candidate_versions": versions.reset_index(drop=True),
        "candidate_frame": latest,
        "availability": availability,
        "ignored_runs": pd.DataFrame(ignored_rows).reset_index(drop=True),
    }


def _slice_predictions_for_lead_day(
    predictions: pd.DataFrame,
    *,
    split_name: str,
    lead_day: int,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    if int(lead_day) == 0:
        return build_stitched_d_only_predictions(predictions, split_name=split_name)
    sliced = predictions[
        (predictions["dataset_split"].astype(str) == str(split_name))
        & (predictions["lead_day"].astype(int) == int(lead_day))
    ].copy()
    if sliced.empty:
        return sliced
    sliced = sliced.sort_values(["candidate_key", "target_timestamp_utc", "forecast_origin_utc"])
    return sliced.drop_duplicates(subset=["candidate_key", "target_timestamp_utc"], keep="last").reset_index(drop=True)


def choose_target_evaluation_slice(
    predictions: pd.DataFrame,
    *,
    preferred_splits: tuple[str, ...] = ("test", "validation"),
    preferred_lead_day: int = 0,
) -> dict[str, Any]:
    if predictions.empty:
        raise ValueError("Prediction bundle is empty.")

    available_splits = set(predictions["dataset_split"].astype(str).unique().tolist())
    split_name = next((name for name in preferred_splits if name in available_splits), None)
    if split_name is None:
        split_name = sorted(available_splits)[0]

    available_lead_days = sorted(predictions[predictions["dataset_split"].astype(str) == split_name]["lead_day"].astype(int).unique().tolist())
    lead_day = int(preferred_lead_day) if int(preferred_lead_day) in available_lead_days else int(available_lead_days[0])
    lead_day_label = "D" if lead_day == 0 else f"D+{lead_day}"
    target_slice = _slice_predictions_for_lead_day(predictions, split_name=split_name, lead_day=lead_day)
    return {
        "dataset_split": split_name,
        "lead_day": lead_day,
        "lead_day_label": lead_day_label,
        "predictions": target_slice,
    }


def choose_official_naive_candidate(predictions: pd.DataFrame) -> dict[str, Any]:
    if predictions.empty:
        raise ValueError("Prediction bundle is empty.")
    split_name = "validation" if "validation" in set(predictions["dataset_split"].astype(str).unique()) else sorted(
        predictions["dataset_split"].astype(str).unique().tolist()
    )[0]
    naive_predictions = predictions[predictions["candidate_key"].astype(str).str.startswith("naive_")].copy()
    if naive_predictions.empty:
        raise ValueError("No seasonal naive candidates were available to define the rMAE denominator.")

    rows: list[dict[str, Any]] = []
    for candidate_key, group in naive_predictions.groupby("candidate_key", dropna=False):
        split_group = group[group["dataset_split"].astype(str) == split_name].copy()
        valid = split_group[split_group["y_true"].notna() & split_group["y_pred"].notna()].copy()
        observations_total = int(split_group.shape[0])
        observations_scored = int(valid.shape[0])
        coverage_pct = float(observations_scored / observations_total * 100.0) if observations_total else 0.0
        mae = float((valid["y_pred"] - valid["y_true"]).abs().mean()) if not valid.empty else np.nan
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(group["candidate_label"].iloc[0]),
                "dataset_split": split_name,
                "observations_total": observations_total,
                "observations_scored": observations_scored,
                "coverage_pct": coverage_pct,
                "mae": mae,
            }
        )
    naive_summary = pd.DataFrame(rows).sort_values(
        ["coverage_pct", "mae", "candidate_label"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    selected = naive_summary.iloc[0].to_dict()
    selected["selection_policy"] = "maximum_coverage_then_mae"
    selected["selection_split"] = split_name
    selected["selection_reporting_level"] = "full_horizon"
    return {"selected": selected, "summary": naive_summary}


def _metric_row_from_slice(group: pd.DataFrame) -> dict[str, Any]:
    valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
    if valid.empty:
        return {
            "observations_total": int(group.shape[0]),
            "observations_scored": 0,
            "coverage_pct": 0.0,
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
        }
    error = valid["y_pred"] - valid["y_true"]
    return {
        "observations_total": int(group.shape[0]),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / group.shape[0] * 100.0),
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "bias": float(error.mean()),
    }


def compute_candidate_selection_summary(
    predictions: pd.DataFrame,
    *,
    selection_split: str,
    selection_lead_day: int,
    official_naive_candidate_key: str,
    k_top_hours: int = 3,
) -> pd.DataFrame:
    sliced = _slice_predictions_for_lead_day(predictions, split_name=selection_split, lead_day=selection_lead_day)
    if sliced.empty:
        return pd.DataFrame()

    topk_daily, topk_summary = compute_topk_hour_metrics(sliced, ks=(int(k_top_hours),))
    topk_prefix = f"top{int(k_top_hours)}"
    topk_summary = topk_summary.rename(
        columns={
            f"mean_{topk_prefix}_expensive_recall": "topk_expensive_recall",
            f"mean_{topk_prefix}_cheap_recall": "topk_cheap_recall",
        }
    )

    rows: list[dict[str, Any]] = []
    for candidate_key, group in sliced.groupby("candidate_key", dropna=False):
        row = {
            "candidate_key": str(candidate_key),
            "candidate_label": str(group["candidate_label"].iloc[0]),
            "model_family": str(group["model_family"].iloc[0]),
            "fs_level": str(group["fs_level"].iloc[0]),
            "source_run_id": str(group["source_run_id"].iloc[0]),
            "source_run_label": str(group["source_run_label"].iloc[0]),
            "dataset_split": str(selection_split),
            "lead_day": int(selection_lead_day),
            "lead_day_label": "D" if int(selection_lead_day) == 0 else f"D+{int(selection_lead_day)}",
        }
        row.update(_metric_row_from_slice(group))
        rows.append(row)
    summary = pd.DataFrame(rows)

    official_row = summary[summary["candidate_key"].astype(str) == str(official_naive_candidate_key)].copy()
    if official_row.empty or pd.isna(official_row.iloc[0]["mae"]) or float(official_row.iloc[0]["mae"]) == 0.0:
        raise ValueError("The official naive candidate was missing from the evaluation slice or had an invalid MAE denominator.")
    denominator = float(official_row.iloc[0]["mae"])
    summary["rmae"] = summary["mae"] / denominator
    summary["abs_bias"] = summary["bias"].abs()

    topk_columns = [
        "candidate_key",
        "topk_expensive_recall",
        "topk_cheap_recall",
        f"valid_{topk_prefix}_expensive_days",
        f"valid_{topk_prefix}_cheap_days",
    ]
    summary = summary.merge(topk_summary[topk_columns], on="candidate_key", how="left")
    summary["ranking_score"] = 0.50 * summary["topk_expensive_recall"] + 0.50 * summary["topk_cheap_recall"]
    summary["risk_weighted_ranking_score"] = 0.65 * summary["topk_expensive_recall"] + 0.35 * summary["topk_cheap_recall"]
    summary["selected_as_deterministic_winner"] = False
    summary["selected_as_hour_ranking_winner"] = False
    summary = summary.sort_values(["rmae", "mae", "rmse", "abs_bias", "candidate_label"]).reset_index(drop=True)
    return summary


def select_scenario_candidates(selection_summary: pd.DataFrame) -> dict[str, Any]:
    if selection_summary.empty:
        raise ValueError("Candidate selection summary is empty.")

    deterministic_rank = selection_summary.sort_values(["rmae", "mae", "rmse", "abs_bias", "candidate_label"]).reset_index(drop=True)
    ranking_rank = selection_summary.sort_values(
        ["ranking_score", "risk_weighted_ranking_score", "rmae", "mae", "candidate_label"],
        ascending=[False, False, True, True, True],
    ).reset_index(drop=True)

    deterministic_key = str(deterministic_rank.iloc[0]["candidate_key"])
    ranking_key = str(ranking_rank.iloc[0]["candidate_key"])
    runner_up_ranking_key = str(ranking_rank.iloc[1]["candidate_key"]) if ranking_rank.shape[0] > 1 else None

    annotated = selection_summary.copy()
    annotated["selected_as_deterministic_winner"] = annotated["candidate_key"].astype(str) == deterministic_key
    annotated["selected_as_hour_ranking_winner"] = annotated["candidate_key"].astype(str) == ranking_key

    selected_keys = [deterministic_key]
    if ranking_key not in selected_keys:
        selected_keys.append(ranking_key)

    roles: list[dict[str, Any]] = []
    if deterministic_key == ranking_key:
        roles.append({"candidate_key": deterministic_key, "selection_role": "both"})
    else:
        roles.append({"candidate_key": deterministic_key, "selection_role": "deterministic_winner"})
        roles.append({"candidate_key": ranking_key, "selection_role": "hour_ranking_winner"})

    return {
        "selection_summary": annotated,
        "selected_candidate_keys": selected_keys,
        "deterministic_candidate_key": deterministic_key,
        "ranking_candidate_key": ranking_key,
        "ranking_runner_up_key": runner_up_ranking_key,
        "role_rows": pd.DataFrame(roles),
    }


def _calendar_lookup_frame(target_timestamps_utc: pd.Series, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    unique_targets = pd.Index(pd.to_datetime(target_timestamps_utc, utc=True)).drop_duplicates().sort_values()
    calendar = build_calendar_features(pd.DatetimeIndex(unique_targets), config)
    calendar = calendar.rename(columns={"hour_of_day": "target_local_hour", "day_of_week": "target_local_dayofweek"})
    return calendar.drop_duplicates(subset=["target_timestamp_utc"]).reset_index(drop=True)


def _forecast_bucket_labels() -> list[str]:
    return ["very_low", "low", "medium", "high", "very_high"]


def build_residual_period_table(
    predictions: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
    lead_day: int = 0,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for split_name in sorted(predictions["dataset_split"].astype(str).unique().tolist()):
        split_frame = _slice_predictions_for_lead_day(predictions, split_name=split_name, lead_day=lead_day)
        if split_frame.empty:
            continue
        frames.append(split_frame)
    if not frames:
        return pd.DataFrame()

    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame["y_true"].notna() & frame["y_pred"].notna()].copy()
    if frame.empty:
        return frame
    frame = normalize_prediction_schema(frame, config=config)
    calendar = _calendar_lookup_frame(frame["target_timestamp_utc"], config)
    frame = frame.drop(columns=[column for column in ["target_local_hour", "target_local_dayofweek"] if column in frame.columns])
    frame = frame.merge(calendar, on="target_timestamp_utc", how="left")
    frame["delivery_day"] = frame["target_local_date"].astype(str)
    frame["month"] = pd.Series(frame["target_timestamp_local"]).dt.month.astype(int)
    frame["season"] = frame["month"].map(SEASON_MAP).astype(str)
    frame["day_type"] = np.where(frame["target_local_dayofweek"].isin([5, 6]), "weekend", "weekday")
    frame["period_index"] = (
        frame.sort_values(["candidate_key", "dataset_split", "target_local_date", "target_timestamp_local"])
        .groupby(["candidate_key", "dataset_split", "target_local_date"], dropna=False)
        .cumcount()
        .add(1)
    )
    frame["hours_in_day"] = frame.groupby(["candidate_key", "dataset_split", "target_local_date"], dropna=False)["target_timestamp_utc"].transform("size")
    frame["residual"] = frame["y_true"] - frame["y_pred"]
    frame["underestimation_component"] = frame["residual"].clip(lower=0.0)
    frame["overestimation_component"] = (-frame["residual"]).clip(lower=0.0)

    frame["forecast_price_level_bucket"] = "unassigned"
    for candidate_key, candidate_group in frame.groupby("candidate_key", dropna=False):
        calibration = candidate_group[candidate_group["dataset_split"].astype(str) == "validation"]["y_pred"].dropna()
        if calibration.shape[0] < 5:
            calibration = candidate_group["y_pred"].dropna()
        labels = _forecast_bucket_labels()
        if calibration.empty or calibration.nunique() < 2:
            mask = frame["candidate_key"].astype(str) == str(candidate_key)
            frame.loc[mask, "forecast_price_level_bucket"] = "all_levels"
            continue
        try:
            bins = pd.qcut(calibration, q=min(5, calibration.nunique()), duplicates="drop")
            intervals = bins.cat.categories
            bucket_count = len(intervals)
            use_labels = labels[:bucket_count]
            mask = frame["candidate_key"].astype(str) == str(candidate_key)
            frame.loc[mask, "forecast_price_level_bucket"] = pd.cut(
                frame.loc[mask, "y_pred"],
                bins=[interval.left for interval in intervals] + [intervals[-1].right],
                labels=use_labels,
                include_lowest=True,
                duplicates="drop",
            ).astype(str)
        except ValueError:
            mask = frame["candidate_key"].astype(str) == str(candidate_key)
            frame.loc[mask, "forecast_price_level_bucket"] = "all_levels"

    return frame.sort_values(
        ["candidate_key", "dataset_split", "target_local_date", "period_index"]
    ).reset_index(drop=True)


def build_residual_daily_profiles(period_residuals: pd.DataFrame) -> pd.DataFrame:
    if period_residuals.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label", "target_local_date"]
    for keys, group in period_residuals.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        ordered = group.sort_values("period_index").copy()
        actual_expensive = ordered.sort_values(["y_true", "target_timestamp_utc"], ascending=[False, True]).head(3)
        row.update(
            {
                "delivery_day": str(ordered["delivery_day"].iloc[0]),
                "source_residual_day_start_utc": pd.Timestamp(ordered["target_timestamp_utc"].min()),
                "source_residual_day_end_utc": pd.Timestamp(ordered["target_timestamp_utc"].max()),
                "model_family": str(ordered["model_family"].iloc[0]),
                "fs_level": str(ordered["fs_level"].iloc[0]),
                "source_run_id": str(ordered["source_run_id"].iloc[0]),
                "season": str(ordered["season"].iloc[0]),
                "day_type": str(ordered["day_type"].iloc[0]),
                "month": int(ordered["month"].iloc[0]),
                "day_of_week": int(ordered["target_local_dayofweek"].iloc[0]),
                "hours_in_day": int(ordered["hours_in_day"].iloc[0]),
                "realised_daily_mean": float(ordered["y_true"].mean()),
                "realised_daily_max": float(ordered["y_true"].max()),
                "realised_daily_min": float(ordered["y_true"].min()),
                "realised_daily_spread": float(ordered["y_true"].max() - ordered["y_true"].min()),
                "forecast_daily_mean": float(ordered["y_pred"].mean()),
                "forecast_daily_max": float(ordered["y_pred"].max()),
                "forecast_daily_min": float(ordered["y_pred"].min()),
                "forecast_daily_spread": float(ordered["y_pred"].max() - ordered["y_pred"].min()),
                "residual_daily_mean": float(ordered["residual"].mean()),
                "mean_positive_residual": float(ordered["underestimation_component"].mean()),
                "mean_negative_residual": float(ordered["residual"].where(ordered["residual"] < 0.0).mean()),
                "max_positive_residual": float(ordered["residual"].max()),
                "max_negative_residual": float(ordered["residual"].min()),
                "daily_residual_spread": float(ordered["residual"].max() - ordered["residual"].min()),
                "positive_residual_severity": float(ordered["underestimation_component"].mean()),
                "overestimation_severity": float(ordered["overestimation_component"].mean()),
                "evening_peak_underestimation": float(
                    ordered.loc[ordered["target_local_hour"].isin([17, 18, 19, 20, 21]), "underestimation_component"].mean()
                ),
                "daily_max_price_miss": float(
                    ordered.loc[ordered["y_true"].idxmax(), "residual"]
                ),
                "top3_expensive_underestimation": float(actual_expensive["underestimation_component"].mean()) if not actual_expensive.empty else np.nan,
            }
        )
        rows.append(row)

    daily = pd.DataFrame(rows).sort_values(["candidate_key", "dataset_split", "target_local_date"]).reset_index(drop=True)
    if daily.empty:
        return daily

    daily["high_volatility_flag"] = False
    for candidate_key, split_name in daily[["candidate_key", "dataset_split"]].drop_duplicates().itertuples(index=False):
        mask = (daily["candidate_key"].astype(str) == str(candidate_key)) & (daily["dataset_split"].astype(str) == str(split_name))
        actual_threshold = daily.loc[mask, "realised_daily_spread"].quantile(0.90)
        residual_threshold = daily.loc[mask, "daily_residual_spread"].quantile(0.90)
        daily.loc[mask, "high_volatility_flag"] = (
            (daily.loc[mask, "realised_daily_spread"] >= actual_threshold)
            | (daily.loc[mask, "daily_residual_spread"] >= residual_threshold)
        )

    for candidate_key, dataset_split, hours_in_day in daily[["candidate_key", "dataset_split", "hours_in_day"]].drop_duplicates().itertuples(index=False):
        mask = (
            (daily["candidate_key"].astype(str) == str(candidate_key))
            & (daily["dataset_split"].astype(str) == str(dataset_split))
            & (daily["hours_in_day"].astype(int) == int(hours_in_day))
        )
        if mask.sum() == 0:
            continue
        positive_values = daily.loc[mask, "positive_residual_severity"]
        over_values = daily.loc[mask, "overestimation_severity"]
        daily.loc[mask, "positive_tail_top25_flag"] = positive_values >= positive_values.quantile(0.75)
        daily.loc[mask, "positive_tail_top05_flag"] = positive_values >= positive_values.quantile(0.95)
        daily.loc[mask, "negative_tail_top25_flag"] = over_values >= over_values.quantile(0.75)

    return daily


def build_bank_availability_summary(daily_profiles: pd.DataFrame, *, calibration_split: str) -> pd.DataFrame:
    if daily_profiles.empty:
        return pd.DataFrame()
    calibration = daily_profiles[daily_profiles["dataset_split"].astype(str) == str(calibration_split)].copy()
    if calibration.empty:
        return pd.DataFrame()
    return (
        calibration.groupby(
            ["candidate_key", "candidate_label", "season", "day_type", "lead_day_label", "hours_in_day"],
            dropna=False,
        )
        .size()
        .rename("available_days")
        .reset_index()
        .sort_values(["candidate_label", "hours_in_day", "season", "day_type"])
        .reset_index(drop=True)
    )


def build_tail_day_catalog(
    daily_profiles: pd.DataFrame,
    *,
    calibration_split: str,
    selected_candidate_keys: list[str],
    top_n: int = 10,
) -> pd.DataFrame:
    if daily_profiles.empty:
        return pd.DataFrame()
    calibration = daily_profiles[
        (daily_profiles["dataset_split"].astype(str) == str(calibration_split))
        & (daily_profiles["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys]))
    ].copy()
    if calibration.empty:
        return pd.DataFrame()
    positive = (
        calibration.sort_values(["candidate_label", "positive_residual_severity", "delivery_day"], ascending=[True, False, True])
        .groupby("candidate_key", dropna=False)
        .head(int(top_n))
        .assign(tail_side="positive_tail")
    )
    negative = (
        calibration.sort_values(["candidate_label", "overestimation_severity", "delivery_day"], ascending=[True, False, True])
        .groupby("candidate_key", dropna=False)
        .head(int(top_n))
        .assign(tail_side="negative_tail")
    )
    return pd.concat([positive, negative], ignore_index=True).reset_index(drop=True)


def build_stress_scenario_catalog(
    daily_profiles: pd.DataFrame,
    *,
    calibration_split: str,
    selected_candidate_keys: list[str],
) -> pd.DataFrame:
    if daily_profiles.empty:
        return pd.DataFrame()
    calibration = daily_profiles[
        (daily_profiles["dataset_split"].astype(str) == str(calibration_split))
        & (daily_profiles["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys]))
    ].copy()
    if calibration.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    rule_specs = [
        ("worst_daily_underestimation", "positive_residual_severity"),
        ("worst_evening_peak_miss", "evening_peak_underestimation"),
        ("worst_daily_max_price_miss", "daily_max_price_miss"),
        ("worst_top3_expensive_hour_miss", "top3_expensive_underestimation"),
        ("representative_high_volatility_day", "realised_daily_spread"),
        ("strongest_overestimation_profile", "overestimation_severity"),
    ]
    for candidate_key, candidate_group in calibration.groupby("candidate_key", dropna=False):
        for stress_type, metric_column in rule_specs:
            ordered = candidate_group.sort_values([metric_column, "delivery_day"], ascending=[False, True]).reset_index(drop=True)
            if ordered.empty:
                continue
            best = ordered.iloc[0]
            rows.append(
                {
                    "candidate_key": str(candidate_key),
                    "candidate_label": str(best["candidate_label"]),
                    "stress_type": stress_type,
                    "metric_column": metric_column,
                    "source_day": str(best["delivery_day"]),
                    "metric_value": float(best[metric_column]),
                    "selection_rule": f"selected_by_{metric_column}",
                }
            )
    return pd.DataFrame(rows).sort_values(["candidate_label", "stress_type"]).reset_index(drop=True)


def build_conditional_bias_summary(period_residuals: pd.DataFrame) -> pd.DataFrame:
    if period_residuals.empty:
        return pd.DataFrame()
    summary = (
        period_residuals.groupby(
            ["candidate_key", "candidate_label", "dataset_split", "season", "day_type", "target_local_hour", "forecast_price_level_bucket"],
            dropna=False,
        )["residual"]
        .agg(["count", "mean", "median"])
        .reset_index()
        .rename(columns={"count": "observations", "mean": "mean_residual", "median": "median_residual"})
        .sort_values(["candidate_label", "dataset_split", "season", "day_type", "target_local_hour", "forecast_price_level_bucket"])
        .reset_index(drop=True)
    )
    return summary


def build_bias_correction_maps_from_frame(
    calibration: pd.DataFrame,
    *,
    statistic: str = "mean",
) -> dict[str, pd.DataFrame]:
    if calibration.empty:
        raise ValueError("Calibration residual frame is empty for bias-correction estimation.")
    if str(statistic) not in {"mean", "median"}:
        raise ValueError(f"Unsupported bias-correction statistic: {statistic}")

    def _aggregate(group_cols: tuple[str, ...]) -> pd.DataFrame:
        group = calibration.groupby(list(group_cols), dropna=False)["residual"]
        return group.agg(correction_value=str(statistic), observations="size").reset_index()

    return {
        level_name: _aggregate(group_cols)
        for level_name, group_cols in BIAS_CORRECTION_LEVEL_SPECS.items()
    }


def build_bias_correction_maps(period_residuals: pd.DataFrame, *, calibration_split: str = "validation") -> dict[str, pd.DataFrame]:
    calibration = period_residuals[period_residuals["dataset_split"].astype(str) == str(calibration_split)].copy()
    if calibration.empty:
        raise ValueError("Calibration split residuals are empty for bias-correction estimation.")
    return build_bias_correction_maps_from_frame(calibration, statistic="mean")


def _lookup_bias_correction(row: pd.Series, correction_maps: dict[str, pd.DataFrame], min_observations: int) -> tuple[float, str, int]:
    candidate_key = str(row["candidate_key"])
    season = str(row["season"])
    day_type = str(row["day_type"])
    target_local_hour = int(row["target_local_hour"])

    lookups = (
        (
            "season_day_type_hour",
            correction_maps["season_day_type_hour"],
            {
                "candidate_key": candidate_key,
                "season": season,
                "day_type": day_type,
                "target_local_hour": target_local_hour,
            },
        ),
        (
            "season_hour",
            correction_maps["season_hour"],
            {
                "candidate_key": candidate_key,
                "season": season,
                "target_local_hour": target_local_hour,
            },
        ),
        (
            "day_type_hour",
            correction_maps["day_type_hour"],
            {
                "candidate_key": candidate_key,
                "day_type": day_type,
                "target_local_hour": target_local_hour,
            },
        ),
        (
            "hour",
            correction_maps["hour"],
            {
                "candidate_key": candidate_key,
                "target_local_hour": target_local_hour,
            },
        ),
        (
            "global",
            correction_maps["global"],
            {
                "candidate_key": candidate_key,
            },
        ),
    )

    for level_name, lookup_frame, filters in lookups:
        mask = pd.Series(True, index=lookup_frame.index)
        for column, value in filters.items():
            mask &= lookup_frame[column].astype(str) == str(value) if column != "target_local_hour" else lookup_frame[column].astype(int) == int(value)
        matched = lookup_frame[mask].head(1)
        if matched.empty:
            continue
        matched_row = matched.iloc[0]
        observations = int(matched_row["observations"])
        if observations >= int(min_observations) or level_name == "global":
            return float(matched_row["correction_value"]), level_name, observations
    return 0.0, "none", 0


def apply_bias_correction(
    period_residuals: pd.DataFrame,
    correction_maps: dict[str, pd.DataFrame],
    *,
    min_observations: int = 20,
    level_priority: tuple[str, ...] | list[str] | None = None,
    shrinkage: float = 1.0,
    cap_abs: float | None = None,
    setting_id: str = "default",
    statistic_label: str = "mean",
) -> pd.DataFrame:
    if period_residuals.empty:
        return pd.DataFrame()
    level_priority = tuple(level_priority or BIAS_CORRECTION_LEVEL_PROFILES["sdth_sh_dh_h_global"])
    frame = period_residuals.copy()
    frame = frame.merge(
        correction_maps["season_day_type_hour"].rename(
            columns={"correction_value": "corr_sdth", "observations": "obs_sdth"}
        ),
        on=["candidate_key", "season", "day_type", "target_local_hour"],
        how="left",
    )
    frame = frame.merge(
        correction_maps["season_hour"].rename(columns={"correction_value": "corr_sh", "observations": "obs_sh"}),
        on=["candidate_key", "season", "target_local_hour"],
        how="left",
    )
    frame = frame.merge(
        correction_maps["day_type_hour"].rename(columns={"correction_value": "corr_dh", "observations": "obs_dh"}),
        on=["candidate_key", "day_type", "target_local_hour"],
        how="left",
    )
    frame = frame.merge(
        correction_maps["hour"].rename(columns={"correction_value": "corr_h", "observations": "obs_h"}),
        on=["candidate_key", "target_local_hour"],
        how="left",
    )
    frame = frame.merge(
        correction_maps["global"].rename(columns={"correction_value": "corr_g", "observations": "obs_g"}),
        on=["candidate_key"],
        how="left",
    )

    correction_column_map = {
        "season_day_type_hour": ("corr_sdth", "obs_sdth"),
        "season_hour": ("corr_sh", "obs_sh"),
        "day_type_hour": ("corr_dh", "obs_dh"),
        "hour": ("corr_h", "obs_h"),
        "global": ("corr_g", "obs_g"),
    }
    correction_value = pd.Series(0.0, index=frame.index, dtype=float)
    correction_level = pd.Series("global", index=frame.index, dtype=object)
    correction_observations = pd.Series(frame["obs_g"].fillna(0).astype(int), index=frame.index, dtype=int)
    assigned = pd.Series(False, index=frame.index)

    for level_name in level_priority:
        corr_col, obs_col = correction_column_map[str(level_name)]
        if str(level_name) == "global":
            eligible = ~assigned
        else:
            eligible = (~assigned) & (frame[obs_col].fillna(0).astype(int) >= int(min_observations))
        if not eligible.any():
            continue
        correction_value.loc[eligible] = frame.loc[eligible, corr_col].fillna(0.0).astype(float)
        correction_level.loc[eligible] = str(level_name)
        correction_observations.loc[eligible] = frame.loc[eligible, obs_col].fillna(0).astype(int)
        assigned.loc[eligible] = True

    correction_value = correction_value.astype(float) * float(shrinkage)
    if cap_abs is not None and not pd.isna(cap_abs):
        correction_value = correction_value.clip(lower=-abs(float(cap_abs)), upper=abs(float(cap_abs)))

    frame["bias_correction"] = correction_value.astype(float)
    frame["bias_correction_level"] = correction_level.astype(str)
    frame["bias_correction_observations"] = correction_observations.astype(int)
    frame["bias_correction_setting_id"] = str(setting_id)
    frame["bias_correction_statistic"] = str(statistic_label)
    frame["bias_correction_shrinkage"] = float(shrinkage)
    frame["bias_correction_cap_abs"] = np.nan if cap_abs is None else float(cap_abs)
    frame["bias_correction_level_profile"] = "|".join(level_priority)
    frame["bias_corrected_forecast"] = frame["y_pred"].astype(float) + frame["bias_correction"].astype(float)
    frame["bias_corrected_residual"] = frame["y_true"].astype(float) - frame["bias_corrected_forecast"].astype(float)
    return frame.drop(columns=["corr_sdth", "obs_sdth", "corr_sh", "obs_sh", "corr_dh", "obs_dh", "corr_h", "obs_h", "corr_g", "obs_g"])


def _tail_window_by_delivery_day(frame: pd.DataFrame, window_days: int | None) -> pd.DataFrame:
    if frame.empty or window_days is None or pd.isna(window_days):
        return frame.copy()
    delivery_day = pd.to_datetime(frame["delivery_day"], errors="coerce")
    cutoff = delivery_day.max() - pd.Timedelta(days=int(window_days) - 1)
    return frame[delivery_day >= cutoff].copy()


def apply_bias_correction_candidate_settings(
    period_residuals: pd.DataFrame,
    candidate_settings: pd.DataFrame,
    *,
    calibration_split: str = "validation",
) -> pd.DataFrame:
    if period_residuals.empty:
        return pd.DataFrame()
    if candidate_settings.empty:
        frame = period_residuals.copy()
        frame["bias_correction"] = 0.0
        frame["bias_correction_level"] = "none"
        frame["bias_correction_observations"] = 0
        frame["bias_correction_setting_id"] = "none"
        frame["bias_correction_statistic"] = "none"
        frame["bias_correction_shrinkage"] = 0.0
        frame["bias_correction_cap_abs"] = np.nan
        frame["bias_correction_level_profile"] = "none"
        frame["bias_corrected_forecast"] = frame["y_pred"].astype(float)
        frame["bias_corrected_residual"] = frame["y_true"].astype(float) - frame["bias_corrected_forecast"].astype(float)
        return frame

    rows: list[pd.DataFrame] = []
    settings = candidate_settings.copy()
    settings["candidate_key"] = settings["candidate_key"].astype(str)
    for setting in settings.to_dict(orient="records"):
        candidate_key = str(setting["candidate_key"])
        candidate_frame = period_residuals[period_residuals["candidate_key"].astype(str) == candidate_key].copy()
        if candidate_frame.empty:
            continue
        statistic = str(setting.get("statistic", "mean"))
        if statistic == "none" or str(setting.get("setting_id", "none")) == "none":
            candidate_frame["bias_correction"] = 0.0
            candidate_frame["bias_correction_level"] = "none"
            candidate_frame["bias_correction_observations"] = 0
            candidate_frame["bias_correction_setting_id"] = "none"
            candidate_frame["bias_correction_statistic"] = "none"
            candidate_frame["bias_correction_shrinkage"] = 0.0
            candidate_frame["bias_correction_cap_abs"] = np.nan
            candidate_frame["bias_correction_level_profile"] = "none"
            candidate_frame["bias_corrected_forecast"] = candidate_frame["y_pred"].astype(float)
            candidate_frame["bias_corrected_residual"] = candidate_frame["y_true"].astype(float) - candidate_frame["bias_corrected_forecast"].astype(float)
            rows.append(candidate_frame)
            continue

        calibration_frame = candidate_frame[candidate_frame["dataset_split"].astype(str) == str(calibration_split)].copy()
        calibration_frame = _tail_window_by_delivery_day(calibration_frame, setting.get("window_days"))
        maps = build_bias_correction_maps_from_frame(calibration_frame, statistic=statistic)
        level_profile_name = str(setting.get("level_profile_name", "sdth_sh_dh_h_global"))
        level_priority = BIAS_CORRECTION_LEVEL_PROFILES[level_profile_name]
        corrected = apply_bias_correction(
            candidate_frame,
            maps,
            min_observations=int(setting.get("min_observations", 20)),
            level_priority=level_priority,
            shrinkage=float(setting.get("shrinkage", 1.0)),
            cap_abs=None if pd.isna(setting.get("cap_abs")) else float(setting.get("cap_abs")),
            setting_id=str(setting.get("setting_id", f"{candidate_key}_option_c")),
            statistic_label=statistic,
        )
        rows.append(corrected)

    untouched_keys = set(period_residuals["candidate_key"].astype(str).tolist()) - set(settings["candidate_key"].astype(str).tolist())
    for candidate_key in untouched_keys:
        candidate_frame = period_residuals[period_residuals["candidate_key"].astype(str) == str(candidate_key)].copy()
        if candidate_frame.empty:
            continue
        candidate_frame["bias_correction"] = 0.0
        candidate_frame["bias_correction_level"] = "none"
        candidate_frame["bias_correction_observations"] = 0
        candidate_frame["bias_correction_setting_id"] = "none"
        candidate_frame["bias_correction_statistic"] = "none"
        candidate_frame["bias_correction_shrinkage"] = 0.0
        candidate_frame["bias_correction_cap_abs"] = np.nan
        candidate_frame["bias_correction_level_profile"] = "none"
        candidate_frame["bias_corrected_forecast"] = candidate_frame["y_pred"].astype(float)
        candidate_frame["bias_corrected_residual"] = candidate_frame["y_true"].astype(float) - candidate_frame["bias_corrected_forecast"].astype(float)
        rows.append(candidate_frame)

    return pd.concat(rows, ignore_index=True).sort_values(
        ["candidate_key", "dataset_split", "target_timestamp_utc"]
    ).reset_index(drop=True)


def summarize_bias_correction_impact(corrected_periods: pd.DataFrame) -> pd.DataFrame:
    if corrected_periods.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for keys, group in corrected_periods.groupby(["candidate_key", "candidate_label", "dataset_split"], dropna=False):
        candidate_key, candidate_label, dataset_split = keys
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
        if valid.empty:
            continue
        raw_error = valid["y_pred"] - valid["y_true"]
        corrected_error = valid["bias_corrected_forecast"] - valid["y_true"]
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "dataset_split": str(dataset_split),
                "raw_bias": float(raw_error.mean()),
                "corrected_bias": float(corrected_error.mean()),
                "raw_mae": float(raw_error.abs().mean()),
                "corrected_mae": float(corrected_error.abs().mean()),
                "raw_rmse": float(np.sqrt((raw_error**2).mean())),
                "corrected_rmse": float(np.sqrt((corrected_error**2).mean())),
                "bias_change": float(corrected_error.mean() - raw_error.mean()),
                "mae_change": float(corrected_error.abs().mean() - raw_error.abs().mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["candidate_label", "dataset_split"]).reset_index(drop=True)


def build_variant_plan(
    *,
    use_option_a_tail_enrichment: bool,
    use_option_b_stress_scenarios: bool,
    use_option_c_bias_correction: bool,
) -> pd.DataFrame:
    rows = [{"scenario_variant": "base", "use_option_a": False, "use_option_b": False, "use_option_c": False}]
    if use_option_a_tail_enrichment:
        rows.append({"scenario_variant": "base_plus_a", "use_option_a": True, "use_option_b": False, "use_option_c": False})
    if use_option_b_stress_scenarios:
        rows.append({"scenario_variant": "base_plus_b", "use_option_a": False, "use_option_b": True, "use_option_c": False})
    if use_option_c_bias_correction:
        rows.append({"scenario_variant": "base_plus_c", "use_option_a": False, "use_option_b": False, "use_option_c": True})
    if use_option_a_tail_enrichment and use_option_b_stress_scenarios:
        rows.append({"scenario_variant": "base_plus_a_plus_b", "use_option_a": True, "use_option_b": True, "use_option_c": False})
    if use_option_a_tail_enrichment and use_option_b_stress_scenarios and use_option_c_bias_correction:
        rows.append({"scenario_variant": "base_plus_a_plus_b_plus_c", "use_option_a": True, "use_option_b": True, "use_option_c": True})
    plan = pd.DataFrame(rows).drop_duplicates(subset=["scenario_variant"]).reset_index(drop=True)
    plan["complexity_rank"] = plan["scenario_variant"].map(VARIANT_COMPLEXITY).fillna(99).astype(int)
    return plan


def _sorted_periods_for_day(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["period_index", "target_timestamp_utc"]).reset_index(drop=True)


def _scenario_bank_hierarchy(target_day_row: pd.Series) -> tuple[tuple[str, dict[str, Any]], ...]:
    base_filters = {"hours_in_day": int(target_day_row["hours_in_day"])}
    return (
        (
            "same_season_day_type_lead",
            {
                **base_filters,
                "season": str(target_day_row["season"]),
                "day_type": str(target_day_row["day_type"]),
                "lead_day_label": str(target_day_row["lead_day_label"]),
            },
        ),
        (
            "same_season_day_type",
            {
                **base_filters,
                "season": str(target_day_row["season"]),
                "day_type": str(target_day_row["day_type"]),
            },
        ),
        (
            "same_season",
            {
                **base_filters,
                "season": str(target_day_row["season"]),
            },
        ),
        (
            "same_day_type",
            {
                **base_filters,
                "day_type": str(target_day_row["day_type"]),
            },
        ),
        (
            "all_residual_days",
            base_filters,
        ),
    )


def _filter_daily_bank(daily_profiles: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    bank = daily_profiles.copy()
    for column, value in filters.items():
        if column == "hours_in_day":
            bank = bank[bank[column].astype(int) == int(value)]
        else:
            bank = bank[bank[column].astype(str) == str(value)]
    return bank


def _choose_bank_for_target_day(daily_profiles: pd.DataFrame, target_day_row: pd.Series) -> tuple[pd.DataFrame, str]:
    for bank_level, filters in _scenario_bank_hierarchy(target_day_row):
        bank = _filter_daily_bank(daily_profiles, filters)
        if not bank.empty:
            return bank, bank_level
    return daily_profiles.copy(), "fallback_all_days"


def _build_profile_lookup(period_residuals: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    lookup: dict[tuple[str, str], pd.DataFrame] = {}
    for (candidate_key, delivery_day), group in period_residuals.groupby(["candidate_key", "delivery_day"], dropna=False):
        lookup[(str(candidate_key), str(delivery_day))] = _sorted_periods_for_day(group)
    return lookup


def _reconstruct_forecast_origin_utc_from_target_day(
    target_day_frame: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
) -> pd.Timestamp:
    if target_day_frame.empty:
        return pd.NaT
    target_local = pd.to_datetime(target_day_frame["target_timestamp_local"], errors="coerce")
    if target_local.notna().any():
        target_day_start_local = target_local.min().floor("D")
    else:
        target_utc = pd.to_datetime(target_day_frame["target_timestamp_utc"], utc=True, errors="coerce")
        if target_utc.notna().any():
            target_local_fallback = target_utc.dt.tz_convert(config.resolved_business_timezone())
            target_day_start_local = target_local_fallback.min().floor("D")
        else:
            return pd.NaT
    forecast_origin_local = (target_day_start_local - pd.Timedelta(days=1)).replace(
        hour=int(config.forecast_origin_local_hour),
        minute=int(config.forecast_origin_local_minute),
        second=0,
        microsecond=0,
    )
    if forecast_origin_local.tzinfo is None:
        forecast_origin_local = forecast_origin_local.tz_localize(config.resolved_business_timezone())
    return forecast_origin_local.tz_convert("UTC")


def _resolve_target_forecast_origin_utc(
    target_day_frame: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
) -> tuple[pd.Timestamp, bool]:
    if "forecast_origin_utc" in target_day_frame.columns:
        origin_series = pd.to_datetime(target_day_frame["forecast_origin_utc"], utc=True, errors="coerce").dropna()
    else:
        origin_series = pd.Series(dtype="datetime64[ns, UTC]")
    if not origin_series.empty:
        return pd.Timestamp(origin_series.max()), False
    return _reconstruct_forecast_origin_utc_from_target_day(target_day_frame, config=config), True


def _apply_causal_source_filter(
    bank: pd.DataFrame,
    *,
    forecast_origin_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    if bank.empty:
        return bank.copy(), 0
    if "source_residual_day_end_utc" not in bank.columns:
        raise ValueError("Causal filter requires source_residual_day_end_utc in residual daily profiles.")
    source_end = pd.to_datetime(bank["source_residual_day_end_utc"], utc=True, errors="coerce")
    valid = bank[source_end.notna()].copy()
    if valid.empty:
        return valid, 0
    keep_mask = pd.to_datetime(valid["source_residual_day_end_utc"], utc=True, errors="coerce") < pd.Timestamp(forecast_origin_utc)
    violation_count = int((~keep_mask).sum())
    return valid[keep_mask].copy(), violation_count


def _sample_source_days(
    bank: pd.DataFrame,
    *,
    n_samples: int,
    rng: np.random.Generator,
    use_option_a: bool,
    normal_share: float,
    positive_tail_share: float,
    negative_tail_share: float,
) -> list[dict[str, Any]]:
    if bank.empty or n_samples <= 0:
        return []

    if not use_option_a:
        sampled = bank.sample(n=n_samples, replace=True, random_state=int(rng.integers(0, 1_000_000_000)))
        return [
            {"source_day": str(row["delivery_day"]), "scenario_type": "stochastic_base", "selection_rule": "uniform_bank_sampling"}
            for row in sampled.to_dict(orient="records")
        ]

    shares = np.array([normal_share, positive_tail_share, negative_tail_share], dtype=float)
    shares = np.where(shares < 0.0, 0.0, shares)
    if shares.sum() <= 0.0:
        shares = np.array([1.0, 0.0, 0.0], dtype=float)
    shares = shares / shares.sum()

    positive_bank = bank[bank["positive_tail_top25_flag"].astype("boolean").fillna(False)].copy()
    negative_bank = bank[bank["negative_tail_top25_flag"].astype("boolean").fillna(False)].copy()
    normal_bank = bank.copy()

    counts = np.floor(shares * n_samples).astype(int)
    counts[0] += int(n_samples - counts.sum())
    sources: list[dict[str, Any]] = []
    bank_specs = [
        ("stochastic_base", normal_bank, counts[0], "uniform_bank_sampling"),
        ("positive_tail", positive_bank if not positive_bank.empty else normal_bank, counts[1], "positive_tail_sampling"),
        ("negative_tail", negative_bank if not negative_bank.empty else normal_bank, counts[2], "negative_tail_sampling"),
    ]
    for scenario_type, source_bank, count, selection_rule in bank_specs:
        if count <= 0 or source_bank.empty:
            continue
        sampled = source_bank.sample(n=count, replace=True, random_state=int(rng.integers(0, 1_000_000_000)))
        for row in sampled.to_dict(orient="records"):
            sources.append(
                {
                    "source_day": str(row["delivery_day"]),
                    "scenario_type": scenario_type,
                    "selection_rule": selection_rule,
                }
            )
    return sources


def _select_stress_scenarios(
    bank: pd.DataFrame,
    fallback_bank: pd.DataFrame,
) -> list[dict[str, Any]]:
    source = bank.copy() if not bank.empty else fallback_bank.copy()
    if source.empty:
        return []

    def _best_row(metric_column: str, *, ascending: bool = False) -> pd.Series | None:
        ordered = source.sort_values([metric_column, "delivery_day"], ascending=[ascending, True]).reset_index(drop=True)
        return ordered.iloc[0] if not ordered.empty else None

    candidates = [
        ("worst_daily_underestimation", "positive_residual_severity", False),
        ("worst_evening_peak_miss", "evening_peak_underestimation", False),
        ("worst_daily_max_price_miss", "daily_max_price_miss", False),
        ("worst_top3_expensive_hour_miss", "top3_expensive_underestimation", False),
        ("representative_high_volatility_day", "realised_daily_spread", False),
        ("strongest_overestimation_profile", "overestimation_severity", False),
    ]
    results: list[dict[str, Any]] = []
    for stress_type, metric_column, ascending in candidates:
        best = _best_row(metric_column, ascending=ascending)
        if best is None:
            continue
        results.append(
            {
                "source_day": str(best["delivery_day"]),
                "scenario_type": "stress",
                "stress_type": stress_type,
                "protected": True,
                "selection_rule": f"selected_by_{metric_column}",
            }
        )
    return results


def _assemble_scenario_rows_for_day(
    *,
    scenario_run_id: str,
    candidate_key: str,
    candidate_label: str,
    scenario_variant: str,
    dataset_split: str,
    target_day_frame: pd.DataFrame,
    sampled_sources: list[dict[str, Any]],
    profile_lookup: dict[tuple[str, str], pd.DataFrame],
    use_option_c: bool,
    stress_share: float,
    residual_scale_factor: float,
    residual_scaling_profile: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not sampled_sources:
        return pd.DataFrame(), pd.DataFrame()

    stochastic_sources = [row for row in sampled_sources if row.get("scenario_type") != "stress"]
    stress_sources = [row for row in sampled_sources if row.get("scenario_type") == "stress"]
    stochastic_probability = 1.0 - float(stress_share) if stress_sources else 1.0
    stress_probability = float(stress_share) if stress_sources else 0.0

    scenario_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    delivery_day = str(target_day_frame["delivery_day"].iloc[0])

    def _resolve_residual_scale(value: float) -> float:
        if not residual_scaling_profile:
            return float(residual_scale_factor)
        lower_scale = float(residual_scaling_profile.get("lower_tail_scale", residual_scale_factor))
        upper_scale = float(residual_scaling_profile.get("upper_tail_scale", residual_scale_factor))
        central_scale = float(residual_scaling_profile.get("central_scale", residual_scale_factor))
        central_threshold = float(residual_scaling_profile.get("central_abs_residual_threshold", 0.0))
        if abs(float(value)) <= central_threshold:
            return central_scale
        return upper_scale if float(value) > 0.0 else lower_scale

    for scenario_index, source in enumerate(sampled_sources, start=1):
        scenario_id = f"{scenario_variant}__{delivery_day}__s{scenario_index:03d}"
        source_day = str(source["source_day"])
        profile = profile_lookup[(candidate_key, source_day)]
        residual_column = "bias_corrected_residual" if use_option_c else "residual"
        central_column = "bias_corrected_forecast" if use_option_c else "y_pred"
        ordered_profile = _sorted_periods_for_day(profile)
        ordered_target = _sorted_periods_for_day(target_day_frame)
        scenario_type = str(source.get("scenario_type", "stochastic_base"))
        protected = bool(source.get("protected", False))
        notes = str(source.get("selection_rule", ""))
        probability = (
            stress_probability / len(stress_sources)
            if protected and stress_sources
            else stochastic_probability / max(len(stochastic_sources), 1)
        )
        target_records = ordered_target.to_dict(orient="records")
        if ordered_profile.shape[0] == ordered_target.shape[0]:
            residual_values = ordered_profile[residual_column].astype(float).to_numpy()
        else:
            source_values = ordered_profile[residual_column].astype(float).to_numpy()
            source_positions = np.arange(source_values.shape[0], dtype=float)
            target_positions = np.linspace(0.0, max(float(source_values.shape[0] - 1), 0.0), num=ordered_target.shape[0])
            residual_values = np.interp(target_positions, source_positions, source_values)
            notes = notes + "|resized_profile" if notes else "resized_profile"

        for target_row, residual_value in zip(target_records, residual_values, strict=True):
            central_forecast = float(target_row[central_column])
            applied_scale = _resolve_residual_scale(float(residual_value))
            scaled_residual = float(residual_value) * float(applied_scale)
            scenario_price = central_forecast + scaled_residual
            scenario_rows.append(
                {
                    "scenario_run_id": scenario_run_id,
                    "candidate_key": candidate_key,
                    "candidate_label": candidate_label,
                    "scenario_variant": scenario_variant,
                    "scenario_id": scenario_id,
                    "dataset_split": dataset_split,
                    "delivery_day": delivery_day,
                    "forecast_origin_utc": pd.Timestamp(target_row["forecast_origin_utc"]) if "forecast_origin_utc" in target_row else pd.NaT,
                    "period_timestamp": pd.Timestamp(target_row["target_timestamp_utc"]),
                    "period_index": int(target_row["period_index"]),
                    "scenario_price": scenario_price,
                    "central_forecast_price": central_forecast,
                    "original_forecast_price": float(target_row["y_pred"]),
                    "scaled_residual_value": scaled_residual,
                    "residual_scale_factor": float(applied_scale),
                    "actual_price": float(target_row["y_true"]),
                    "probability": probability,
                    "scenario_type": scenario_type,
                    "source_residual_day": source_day,
                    "protected": protected,
                    "notes": notes,
                    "selection_rule": notes,
                }
            )
        metadata_rows.append(
            {
                "scenario_run_id": scenario_run_id,
                "candidate_key": candidate_key,
                "candidate_label": candidate_label,
                "scenario_variant": scenario_variant,
                "scenario_id": scenario_id,
                "dataset_split": dataset_split,
                "delivery_day": delivery_day,
                "scenario_type": scenario_type,
                "probability": probability,
                "protected": protected,
                "source_day": source_day,
                "source_condition": str(ordered_profile["season"].iloc[0]) + "|" + str(ordered_profile["day_type"].iloc[0]),
                "stress_rule": str(source.get("stress_type", "")),
                "selection_rule": notes,
                "source_residual_day_start_utc": pd.Timestamp(ordered_profile["source_residual_day_start_utc"].iloc[0])
                if "source_residual_day_start_utc" in ordered_profile.columns
                else pd.NaT,
                "source_residual_day_end_utc": pd.Timestamp(ordered_profile["source_residual_day_end_utc"].iloc[0])
                if "source_residual_day_end_utc" in ordered_profile.columns
                else pd.NaT,
                "residual_scale_factor": float(residual_scale_factor) if not residual_scaling_profile else np.nan,
                "residual_scaling_profile_json": json.dumps(residual_scaling_profile, sort_keys=True) if residual_scaling_profile else "",
                "target_forecast_origin_utc": pd.Timestamp(ordered_target["forecast_origin_utc"].dropna().max())
                if "forecast_origin_utc" in ordered_target.columns and ordered_target["forecast_origin_utc"].notna().any()
                else pd.NaT,
            }
        )
    return pd.DataFrame(scenario_rows), pd.DataFrame(metadata_rows)


def _fallback_reduce_unprotected_paths(
    scenario_metadata: pd.DataFrame,
    scenario_paths: dict[str, np.ndarray],
    *,
    keep_count: int,
) -> tuple[list[str], dict[str, float]]:
    if keep_count <= 0 or scenario_metadata.empty:
        return [], {}
    work = scenario_metadata.copy()
    work["daily_mean"] = work["scenario_id"].map(lambda value: float(np.mean(scenario_paths[str(value)])))
    work["daily_max"] = work["scenario_id"].map(lambda value: float(np.max(scenario_paths[str(value)])))
    work["daily_spread"] = work["scenario_id"].map(lambda value: float(np.ptp(scenario_paths[str(value)])))
    work = work.sort_values(["daily_mean", "daily_max", "daily_spread", "scenario_id"]).reset_index(drop=True)
    selected_positions = sorted(set(int(position) for position in np.linspace(0, max(work.shape[0] - 1, 0), num=min(keep_count, work.shape[0]), dtype=int)))
    selected = work.iloc[selected_positions]["scenario_id"].astype(str).tolist()
    if not selected:
        return [], {}

    selected_position_map = {
        int(position): str(work.iloc[int(position)]["scenario_id"])
        for position in selected_positions
    }
    aggregated_probabilities: dict[str, float] = {scenario_id: 0.0 for scenario_id in selected}
    for row_index, row in enumerate(work.to_dict(orient="records")):
        nearest_position = min(selected_positions, key=lambda position: abs(int(position) - int(row_index)))
        representative_id = selected_position_map[int(nearest_position)]
        aggregated_probabilities[representative_id] += float(row["probability"])
    return selected, aggregated_probabilities


def _max_consecutive_true(mask: np.ndarray) -> int:
    max_run = 0
    run = 0
    for flag in mask.tolist():
        if bool(flag):
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return int(max_run)


def _tail_thresholds_from_raw_day(scenario_prices: pd.DataFrame) -> dict[str, float]:
    actual = pd.to_numeric(scenario_prices["actual_price"], errors="coerce").dropna()
    residual = pd.to_numeric(scenario_prices["scenario_price"], errors="coerce") - pd.to_numeric(
        scenario_prices["central_forecast_price"], errors="coerce"
    )
    central = pd.to_numeric(scenario_prices["central_forecast_price"], errors="coerce")
    if actual.empty:
        high_price_threshold = float(central.quantile(0.95)) if central.notna().any() else 0.0
        low_price_threshold = float(central.quantile(0.05)) if central.notna().any() else 0.0
    else:
        high_price_threshold = float(actual.quantile(0.95))
        low_price_threshold = float(actual.quantile(0.05))
    ramp_series = pd.Series(pd.to_numeric(scenario_prices["actual_price"], errors="coerce")).diff().abs().dropna()
    ramp_threshold = float(ramp_series.quantile(0.95)) if not ramp_series.empty else 0.0
    positive_residual_threshold = float(residual.quantile(0.95)) if residual.notna().any() else 0.0
    negative_residual_threshold = float(residual.quantile(0.05)) if residual.notna().any() else 0.0
    return {
        "high_price_threshold": high_price_threshold,
        "low_price_threshold": low_price_threshold,
        "ramp_threshold": ramp_threshold,
        "positive_residual_threshold": positive_residual_threshold,
        "negative_residual_threshold": negative_residual_threshold,
    }


def _build_tail_scores_for_raw_day(
    scenario_prices: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
) -> pd.DataFrame:
    if scenario_prices.empty or scenario_metadata.empty:
        return pd.DataFrame()
    thresholds = _tail_thresholds_from_raw_day(scenario_prices)
    rows: list[dict[str, Any]] = []
    for scenario_id, group in scenario_prices.groupby("scenario_id", dropna=False):
        ordered = group.sort_values(["period_index", "period_timestamp"]).copy()
        prices = pd.to_numeric(ordered["scenario_price"], errors="coerce")
        central = pd.to_numeric(ordered["central_forecast_price"], errors="coerce")
        actual = pd.to_numeric(ordered["actual_price"], errors="coerce")
        residual = prices - central
        ramp = prices.diff().abs().dropna()
        high_mask = prices >= float(thresholds["high_price_threshold"])
        low_mask = prices <= float(thresholds["low_price_threshold"])
        neg_mask = prices < 0.0
        sustained_high = _max_consecutive_true(high_mask.to_numpy(dtype=bool))
        sustained_low = _max_consecutive_true((low_mask | neg_mask).to_numpy(dtype=bool))
        underestimation_score = float(np.maximum(residual, 0.0).mean()) if residual.notna().any() else 0.0
        pos_tail_score = float(np.maximum(residual - float(thresholds["positive_residual_threshold"]), 0.0).sum())
        neg_tail_score = float(np.maximum(float(thresholds["negative_residual_threshold"]) - residual, 0.0).sum())
        # Placeholder proxy: high-price weighted average scenario level.
        hydrogen_proxy = float(prices.where(high_mask, other=np.nan).mean()) if high_mask.any() else float(prices.mean())
        rows.append(
            {
                "scenario_id": str(scenario_id),
                "max_price": float(prices.max()),
                "p95_price": float(prices.quantile(0.95)),
                "min_price": float(prices.min()),
                "p05_price": float(prices.quantile(0.05)),
                "daily_spread": float(prices.max() - prices.min()),
                "max_abs_ramp": float(ramp.max()) if not ramp.empty else 0.0,
                "sustained_high_price_hours": int(sustained_high),
                "sustained_low_or_negative_price_hours": int(sustained_low),
                "positive_residual_tail_score": pos_tail_score,
                "negative_residual_tail_score": neg_tail_score,
                "forecast_underestimation_score": underestimation_score,
                "hydrogen_net_cost_proxy_score": float(hydrogen_proxy),
                "historically_extreme_residual_block_score": float(residual.abs().max()) if residual.notna().any() else 0.0,
            }
        )
    scores = pd.DataFrame(rows)
    if scores.empty:
        return scores
    meta = scenario_metadata.drop_duplicates(subset=["scenario_id"])[["scenario_id", "source_day", "probability"]].copy()
    scores = scores.merge(meta, on="scenario_id", how="left")
    scores["source_day"] = scores["source_day"].astype(str)
    scores["raw_scenario_probability"] = pd.to_numeric(scores["probability"], errors="coerce")
    return scores


def _select_protected_tail_scenarios(
    tail_scores: pd.DataFrame,
    *,
    protected_count: int,
) -> pd.DataFrame:
    if tail_scores.empty or protected_count <= 0:
        return pd.DataFrame(columns=["scenario_id", "tail_categories"])
    category_specs: list[tuple[str, str, bool]] = [
        ("high_sustained_price", "sustained_high_price_hours", False),
        ("high_max_or_p95_price", "p95_price", False),
        ("high_daily_spread", "daily_spread", False),
        ("high_ramp", "max_abs_ramp", False),
        ("positive_underestimation_residual", "forecast_underestimation_score", False),
        ("low_or_negative_price", "sustained_low_or_negative_price_hours", False),
        ("historically_extreme_residual_block", "historically_extreme_residual_block_score", False),
    ]
    selected_rows: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    categories_map: dict[str, set[str]] = {}
    for category, metric, ascending in category_specs:
        ordered = tail_scores.sort_values([metric, "scenario_id"], ascending=[ascending, True]).reset_index(drop=True)
        if ordered.empty:
            continue
        row = ordered.iloc[0]
        scenario_id = str(row["scenario_id"])
        selected_ids.add(scenario_id)
        categories_map.setdefault(scenario_id, set()).add(category)
    if len(selected_ids) < int(protected_count):
        ranking = tail_scores.copy()
        ranking["combined_tail_rank_score"] = (
            ranking["p95_price"].rank(method="average", ascending=False)
            + ranking["daily_spread"].rank(method="average", ascending=False)
            + ranking["max_abs_ramp"].rank(method="average", ascending=False)
            + ranking["forecast_underestimation_score"].rank(method="average", ascending=False)
            + ranking["sustained_high_price_hours"].rank(method="average", ascending=False)
        )
        for _, row in ranking.sort_values(["combined_tail_rank_score", "scenario_id"], ascending=[True, True]).iterrows():
            scenario_id = str(row["scenario_id"])
            if scenario_id in selected_ids:
                continue
            selected_ids.add(scenario_id)
            categories_map.setdefault(scenario_id, set()).add("composite_tail_rank_fill")
            if len(selected_ids) >= int(protected_count):
                break
    for scenario_id in sorted(selected_ids):
        selected_rows.append(
            {
                "scenario_id": scenario_id,
                "tail_categories": ",".join(sorted(categories_map.get(scenario_id, set()))),
            }
        )
    selected = pd.DataFrame(selected_rows)
    if selected.shape[0] > int(protected_count):
        selected = selected.head(int(protected_count)).copy()
    return selected.reset_index(drop=True)


def reduce_daily_scenarios(
    scenario_prices: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    *,
    n_final_scenarios: int,
    random_seed: int,
    protected_tail_share: float = 0.20,
    reduction_method: str = "tail_protected_representative_v1",
    probability_policy: str = "empirical_cluster_mass",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if scenario_prices.empty or scenario_metadata.empty:
        return scenario_prices.copy(), scenario_metadata.copy()

    metadata = scenario_metadata.copy().drop_duplicates(subset=["scenario_id"]).reset_index(drop=True)
    tail_scores = _build_tail_scores_for_raw_day(scenario_prices, metadata)
    protected_tail_count_target = max(int(round(float(n_final_scenarios) * float(protected_tail_share))), 0)
    protected_tail_selected = _select_protected_tail_scenarios(tail_scores, protected_count=protected_tail_count_target)
    protected_ids = protected_tail_selected["scenario_id"].astype(str).tolist() if not protected_tail_selected.empty else []
    protected_count = len(protected_ids)
    remaining_slots = max(int(n_final_scenarios) - protected_count, 0)

    path_lookup: dict[str, np.ndarray] = {}
    for scenario_id, group in scenario_prices.groupby("scenario_id", dropna=False):
        ordered = group.sort_values(["period_index", "period_timestamp"])
        path_lookup[str(scenario_id)] = ordered["scenario_price"].to_numpy(dtype=float)

    unprotected_metadata = metadata[~metadata["scenario_id"].astype(str).isin(protected_ids)].copy()
    if remaining_slots <= 0:
        keep_ids = protected_ids[: int(n_final_scenarios)]
        reduced_prices = scenario_prices[scenario_prices["scenario_id"].astype(str).isin(keep_ids)].copy()
        reduced_metadata = metadata[metadata["scenario_id"].astype(str).isin(keep_ids)].copy()
    elif unprotected_metadata.shape[0] <= remaining_slots:
        keep_ids = protected_ids + unprotected_metadata["scenario_id"].astype(str).tolist()
        reduced_prices = scenario_prices[scenario_prices["scenario_id"].astype(str).isin(keep_ids)].copy()
        reduced_metadata = metadata[metadata["scenario_id"].astype(str).isin(keep_ids)].copy()
    else:
        probability_map = metadata.groupby("scenario_id", dropna=False)["probability"].sum().to_dict()
        unprotected_ids = unprotected_metadata["scenario_id"].astype(str).tolist()
        selected_unprotected, cluster_probability = _fallback_reduce_unprotected_paths(
            unprotected_metadata,
            path_lookup,
            keep_count=remaining_slots,
        )

        keep_ids = protected_ids + selected_unprotected
        reduced_prices = scenario_prices[scenario_prices["scenario_id"].astype(str).isin(keep_ids)].copy()
        reduced_metadata = metadata[metadata["scenario_id"].astype(str).isin(keep_ids)].copy()
        if cluster_probability:
            reduced_metadata["probability"] = reduced_metadata["scenario_id"].map(
                lambda value: cluster_probability.get(str(value), probability_map.get(str(value), 0.0))
            )

    if reduced_metadata.empty:
        return reduced_prices, reduced_metadata

    total_probability = float(reduced_metadata["probability"].sum())
    if total_probability > 0.0:
        reduced_metadata["probability"] = reduced_metadata["probability"] / total_probability
    probability_lookup = reduced_metadata.set_index("scenario_id")["probability"].to_dict()
    reduced_prices["probability"] = reduced_prices["scenario_id"].map(probability_lookup).astype(float)

    tail_category_map = (
        protected_tail_selected.set_index("scenario_id")["tail_categories"].to_dict() if not protected_tail_selected.empty else {}
    )
    raw_probability_map = metadata.set_index("scenario_id")["probability"].to_dict()
    reduced_metadata["tail_protection_flag"] = reduced_metadata["scenario_id"].astype(str).isin(set(protected_ids))
    reduced_metadata["tail_categories"] = reduced_metadata["scenario_id"].astype(str).map(
        lambda sid: tail_category_map.get(str(sid), "")
    )
    reduced_metadata["scenario_type"] = np.where(
        reduced_metadata["tail_protection_flag"].fillna(False),
        "protected_tail",
        "representative",
    )
    reduced_metadata["raw_scenario_id"] = reduced_metadata["scenario_id"].astype(str)
    reduced_metadata["raw_scenario_probability"] = reduced_metadata["scenario_id"].astype(str).map(
        lambda sid: float(raw_probability_map.get(str(sid), 0.0))
    )
    reduced_metadata["reduced_scenario_probability"] = pd.to_numeric(reduced_metadata["probability"], errors="coerce")
    reduced_metadata["reduction_method"] = str(reduction_method)
    reduced_metadata["probability_policy"] = str(probability_policy)
    reduced_metadata["raw_scenario_count"] = int(metadata["scenario_id"].nunique())
    reduced_metadata["reduced_scenario_count"] = int(reduced_metadata["scenario_id"].nunique())
    reduced_metadata["protected_tail_count"] = int(protected_count)
    protected_mass = float(
        reduced_metadata.loc[reduced_metadata["tail_protection_flag"].fillna(False), "reduced_scenario_probability"].sum()
    )
    reduced_metadata["protected_tail_probability_mass"] = float(protected_mass)

    reduced_prices["raw_scenario_id"] = reduced_prices["scenario_id"].astype(str)
    if "scenario_type" in reduced_prices.columns:
        reduced_prices = reduced_prices.drop(columns=["scenario_type"])
    reduced_prices = reduced_prices.merge(
        reduced_metadata[
            [
                "scenario_id",
                "scenario_type",
                "tail_protection_flag",
                "tail_categories",
                "raw_scenario_probability",
                "reduced_scenario_probability",
                "reduction_method",
                "probability_policy",
                "raw_scenario_count",
                "reduced_scenario_count",
                "protected_tail_count",
                "protected_tail_probability_mass",
            ]
        ],
        on="scenario_id",
        how="left",
    )
    reduced_prices["probability"] = pd.to_numeric(reduced_prices["reduced_scenario_probability"], errors="coerce")
    return reduced_prices.reset_index(drop=True), reduced_metadata.reset_index(drop=True)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if values.size == 0:
        return np.nan
    if values.size == 1:
        return float(values[0])
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    if cumulative[-1] <= 0.0:
        return np.nan
    cumulative = cumulative / cumulative[-1]
    return float(np.interp(float(quantile), cumulative, sorted_values))


def _distribution_summary(values: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    return {
        "distribution_min": float(np.min(values)) if values.size else np.nan,
        "distribution_max": float(np.max(values)) if values.size else np.nan,
        "p05": _weighted_quantile(values, weights, 0.05),
        "p10": _weighted_quantile(values, weights, 0.10),
        "p50": _weighted_quantile(values, weights, 0.50),
        "p90": _weighted_quantile(values, weights, 0.90),
        "p95": _weighted_quantile(values, weights, 0.95),
        "weighted_mean": float(np.average(values, weights=weights)) if values.size and weights.sum() > 0.0 else np.nan,
    }


def compute_scenario_quantile_frame(scenario_prices: pd.DataFrame) -> pd.DataFrame:
    if scenario_prices.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_key", "candidate_label", "scenario_variant", "dataset_split", "delivery_day", "period_timestamp", "period_index"]
    for keys, group in scenario_prices.groupby(group_cols, dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split, delivery_day, period_timestamp, period_index = keys
        values = group["scenario_price"].to_numpy(dtype=float)
        weights = group["probability"].to_numpy(dtype=float)
        summary = _distribution_summary(values, weights)
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "scenario_variant": str(scenario_variant),
                "dataset_split": str(dataset_split),
                "delivery_day": str(delivery_day),
                "period_timestamp": pd.Timestamp(period_timestamp),
                "period_index": int(period_index),
                "actual_price": float(group["actual_price"].iloc[0]),
                "central_forecast_price": float(group["central_forecast_price"].iloc[0]),
                **summary,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["candidate_label", "scenario_variant", "delivery_day", "period_index"]
    ).reset_index(drop=True)


def _daily_metric_distribution(scenario_prices: pd.DataFrame, metric_name: str) -> pd.DataFrame:
    if scenario_prices.empty:
        return pd.DataFrame()
    work = scenario_prices.copy()
    grouped = (
        work.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split", "delivery_day", "scenario_id"], dropna=False)
        .agg(
            probability=("probability", "first"),
            actual_daily_mean=("actual_price", "mean"),
            actual_daily_max=("actual_price", "max"),
            actual_daily_min=("actual_price", "min"),
            actual_daily_spread=("actual_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
            scenario_daily_mean=("scenario_price", "mean"),
            scenario_daily_max=("scenario_price", "max"),
            scenario_daily_min=("scenario_price", "min"),
            scenario_daily_spread=("scenario_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
        )
        .reset_index()
    )
    actual_col = f"actual_daily_{metric_name}"
    scenario_col = f"scenario_daily_{metric_name}"
    rows: list[dict[str, Any]] = []
    for keys, group in grouped.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split", "delivery_day"], dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split, delivery_day = keys
        values = group[scenario_col].to_numpy(dtype=float)
        weights = group["probability"].to_numpy(dtype=float)
        distribution = _distribution_summary(values, weights)
        actual_value = float(group[actual_col].iloc[0])
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "scenario_variant": str(scenario_variant),
                "dataset_split": str(dataset_split),
                "delivery_day": str(delivery_day),
                "actual_value": actual_value,
                **distribution,
                "abs_error_weighted_mean": abs(float(distribution["weighted_mean"]) - actual_value),
                "coverage_minmax": float(distribution["distribution_min"] <= actual_value <= distribution["distribution_max"]),
                "coverage_p10_p90": float(distribution["p10"] <= actual_value <= distribution["p90"]),
                "coverage_p05_p95": float(distribution["p05"] <= actual_value <= distribution["p95"]),
            }
        )
    return pd.DataFrame(rows)


def _construct_p50_prediction_frame(period_quantiles: pd.DataFrame, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    if period_quantiles.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for record in period_quantiles.to_dict(orient="records"):
        target_timestamp_utc = pd.Timestamp(record["period_timestamp"])
        target_local = target_timestamp_utc.tz_convert(config.resolved_business_timezone())
        forecast_origin_local = (target_local.floor("D") - pd.Timedelta(days=1)).replace(
            hour=config.forecast_origin_local_hour,
            minute=config.forecast_origin_local_minute,
            second=0,
            microsecond=0,
        )
        rows.append(
            {
                "candidate_key": str(record["candidate_key"]),
                "candidate_label": str(record["candidate_label"]),
                "candidate_context": "scenario_validation",
                "variant": str(record["scenario_variant"]),
                "display_group": "scenario_validation",
                "internal_model": str(record["candidate_key"]),
                "model_family": "",
                "fs_level": "",
                "source_run_id": "",
                "source_run_label": "",
                "dataset_split": str(record["dataset_split"]),
                "forecast_origin_utc": forecast_origin_local.tz_convert("UTC"),
                "target_timestamp_utc": target_timestamp_utc,
                "lead_day": 0,
                "lead_day_label": "D",
                "y_true": float(record["actual_price"]),
                "y_pred": float(record["p50"]),
            }
        )
    return normalize_prediction_schema(pd.DataFrame(rows), config=config)


def _compute_variant_topk_summary(period_quantiles: pd.DataFrame, *, k_top_hours: int = 3) -> pd.DataFrame:
    if period_quantiles.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_key", "candidate_label", "scenario_variant", "dataset_split", "delivery_day"]
    for keys, group in period_quantiles.groupby(group_cols, dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split, delivery_day = keys
        ordered = group.sort_values(["period_timestamp", "period_index"]).copy()
        if ordered.shape[0] < int(k_top_hours):
            expensive_recall = np.nan
            cheap_recall = np.nan
        else:
            actual_expensive = set(
                ordered.sort_values(["actual_price", "period_timestamp"], ascending=[False, True]).head(int(k_top_hours))["period_timestamp"].tolist()
            )
            actual_cheap = set(
                ordered.sort_values(["actual_price", "period_timestamp"], ascending=[True, True]).head(int(k_top_hours))["period_timestamp"].tolist()
            )
            predicted_expensive = set(
                ordered.sort_values(["p50", "period_timestamp"], ascending=[False, True]).head(int(k_top_hours))["period_timestamp"].tolist()
            )
            predicted_cheap = set(
                ordered.sort_values(["p50", "period_timestamp"], ascending=[True, True]).head(int(k_top_hours))["period_timestamp"].tolist()
            )
            expensive_recall = float(len(actual_expensive & predicted_expensive) / int(k_top_hours))
            cheap_recall = float(len(actual_cheap & predicted_cheap) / int(k_top_hours))
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "scenario_variant": str(scenario_variant),
                "dataset_split": str(dataset_split),
                "delivery_day": str(delivery_day),
                "scenario_top3_expensive_recall_daily": expensive_recall,
                "scenario_top3_cheap_recall_daily": cheap_recall,
            }
        )
    daily = pd.DataFrame(rows)
    return (
        daily.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split"], dropna=False)[
            ["scenario_top3_expensive_recall_daily", "scenario_top3_cheap_recall_daily"]
        ]
        .mean()
        .reset_index()
        .rename(
            columns={
                "scenario_top3_expensive_recall_daily": "scenario_top3_expensive_recall",
                "scenario_top3_cheap_recall_daily": "scenario_top3_cheap_recall",
            }
        )
    )


def validate_scenario_set(scenario_prices: pd.DataFrame, *, config: HourlyDAPipelineConfig) -> dict[str, pd.DataFrame]:
    if scenario_prices.empty:
        return {
            "period_quantiles": pd.DataFrame(),
            "period_validation": pd.DataFrame(),
            "daily_mean_validation": pd.DataFrame(),
            "daily_max_validation": pd.DataFrame(),
            "daily_min_validation": pd.DataFrame(),
            "daily_spread_validation": pd.DataFrame(),
            "summary": pd.DataFrame(),
        }

    period_quantiles = compute_scenario_quantile_frame(scenario_prices)
    period_validation = period_quantiles.copy()
    period_validation["coverage_minmax"] = (
        (period_validation["distribution_min"] <= period_validation["actual_price"])
        & (period_validation["actual_price"] <= period_validation["distribution_max"])
    ).astype(float)
    period_validation["coverage_p10_p90"] = (
        (period_validation["p10"] <= period_validation["actual_price"])
        & (period_validation["actual_price"] <= period_validation["p90"])
    ).astype(float)
    period_validation["coverage_p05_p95"] = (
        (period_validation["p05"] <= period_validation["actual_price"])
        & (period_validation["actual_price"] <= period_validation["p95"])
    ).astype(float)
    period_validation["high_tail_miss"] = (period_validation["actual_price"] > period_validation["p95"]).astype(float)
    period_validation["low_tail_miss"] = (period_validation["actual_price"] < period_validation["p05"]).astype(float)
    period_validation["width_p10_p90"] = period_validation["p90"] - period_validation["p10"]
    period_validation["width_p05_p95"] = period_validation["p95"] - period_validation["p05"]

    daily_mean_validation = _daily_metric_distribution(scenario_prices, "mean")
    daily_max_validation = _daily_metric_distribution(scenario_prices, "max")
    daily_min_validation = _daily_metric_distribution(scenario_prices, "min")
    daily_spread_validation = _daily_metric_distribution(scenario_prices, "spread")

    topk_summary = _compute_variant_topk_summary(period_quantiles, k_top_hours=3)

    rows: list[dict[str, Any]] = []
    for keys, group in period_validation.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split"], dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split = keys
        row = {
            "candidate_key": str(candidate_key),
            "candidate_label": str(candidate_label),
            "scenario_variant": str(scenario_variant),
            "dataset_split": str(dataset_split),
            "minmax_coverage": float(group["coverage_minmax"].mean()),
            "p10_p90_coverage": float(group["coverage_p10_p90"].mean()),
            "p05_p95_coverage": float(group["coverage_p05_p95"].mean()),
            "high_tail_miss_rate": float(group["high_tail_miss"].mean()),
            "low_tail_miss_rate": float(group["low_tail_miss"].mean()),
            "average_p10_p90_width": float(group["width_p10_p90"].mean()),
            "average_p05_p95_width": float(group["width_p05_p95"].mean()),
        }
        for metric_name, validation_frame in [
            ("daily_mean", daily_mean_validation),
            ("daily_max", daily_max_validation),
            ("daily_min", daily_min_validation),
            ("daily_spread", daily_spread_validation),
        ]:
            subset = validation_frame[
                (validation_frame["candidate_key"].astype(str) == str(candidate_key))
                & (validation_frame["scenario_variant"].astype(str) == str(scenario_variant))
                & (validation_frame["dataset_split"].astype(str) == str(dataset_split))
            ].copy()
            row[f"{metric_name}_coverage_p10_p90"] = float(subset["coverage_p10_p90"].mean()) if not subset.empty else np.nan
            row[f"{metric_name}_coverage_p05_p95"] = float(subset["coverage_p05_p95"].mean()) if not subset.empty else np.nan
            row[f"{metric_name}_coverage_minmax"] = float(subset["coverage_minmax"].mean()) if not subset.empty else np.nan
            row[f"{metric_name}_abs_error"] = float(subset["abs_error_weighted_mean"].mean()) if not subset.empty else np.nan
        rows.append(row)

    summary = pd.DataFrame(rows).merge(
        topk_summary[
            [
                "candidate_key",
                "candidate_label",
                "scenario_variant",
                "dataset_split",
                "scenario_top3_expensive_recall",
                "scenario_top3_cheap_recall",
            ]
        ],
        on=["candidate_key", "candidate_label", "scenario_variant", "dataset_split"],
        how="left",
    )
    return {
        "period_quantiles": period_quantiles,
        "period_validation": period_validation,
        "daily_mean_validation": daily_mean_validation,
        "daily_max_validation": daily_max_validation,
        "daily_min_validation": daily_min_validation,
        "daily_spread_validation": daily_spread_validation,
        "summary": summary.sort_values(["dataset_split", "candidate_label", "scenario_variant"]).reset_index(drop=True),
    }


def score_scenario_variants(validation_summary: pd.DataFrame) -> pd.DataFrame:
    if validation_summary.empty:
        return pd.DataFrame()
    frame = validation_summary.copy()
    actual_width_scale = max(float(frame["average_p10_p90_width"].median()), 1.0)
    frame["sharpness_score"] = 1.0 / (1.0 + frame["average_p10_p90_width"] / actual_width_scale)
    frame["coverage_score"] = 0.5 * frame["p10_p90_coverage"] + 0.5 * frame["p05_p95_coverage"]
    frame["scenario_score"] = (
        0.35 * (1.0 - frame["high_tail_miss_rate"])
        + 0.10 * (1.0 - frame["low_tail_miss_rate"])
        + 0.20 * frame["coverage_score"]
        + 0.10 * frame["sharpness_score"]
        + 0.15 * frame["scenario_top3_expensive_recall"].fillna(0.0)
        + 0.05 * frame["scenario_top3_cheap_recall"].fillna(0.0)
        + 0.05 * frame["daily_max_coverage_p10_p90"].fillna(0.0)
    )
    frame["scenario_score"] = frame["scenario_score"] - 0.01 * frame["scenario_variant"].map(VARIANT_COMPLEXITY).fillna(0.0)
    frame["selected_as_default_variant"] = False
    best_rows: list[int] = []
    for (candidate_key, dataset_split), group in frame.groupby(["candidate_key", "dataset_split"], dropna=False):
        ordered = group.sort_values(["scenario_score", "high_tail_miss_rate", "average_p10_p90_width", "scenario_variant"], ascending=[False, True, True, True])
        best_rows.append(int(ordered.index[0]))
    frame.loc[best_rows, "selected_as_default_variant"] = True
    return frame.sort_values(["dataset_split", "candidate_label", "scenario_score"], ascending=[True, True, False]).reset_index(drop=True)


def build_final_recommendation(
    candidate_comparison: pd.DataFrame,
    scenario_variant_scores: pd.DataFrame,
) -> dict[str, Any]:
    if candidate_comparison.empty or scenario_variant_scores.empty:
        return {
            "default_candidate": None,
            "default_scenario_variant": None,
            "robustness_candidate": None,
            "robustness_scenario_variant": None,
            "main_reason": "No complete candidate and scenario comparison data were available.",
            "main_caveat": "Scenario generation could not be compared end to end.",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    best_variants = scenario_variant_scores[scenario_variant_scores["selected_as_default_variant"]].copy()
    default_row = best_variants.sort_values(
        ["scenario_score", "high_tail_miss_rate", "average_p10_p90_width", "candidate_label"],
        ascending=[False, True, True, True],
    ).iloc[0]

    other_candidates = best_variants[best_variants["candidate_key"].astype(str) != str(default_row["candidate_key"])].copy()
    if other_candidates.empty:
        robustness_row = best_variants.sort_values(
            ["scenario_score", "high_tail_miss_rate", "average_p10_p90_width", "candidate_label"],
            ascending=[False, True, True, True],
        ).iloc[min(1, best_variants.shape[0] - 1)]
    else:
        robustness_row = other_candidates.sort_values(
            ["scenario_score", "high_tail_miss_rate", "average_p10_p90_width", "candidate_label"],
            ascending=[False, True, True, True],
        ).iloc[0]

    return {
        "default_candidate": str(default_row["candidate_label"]),
        "default_scenario_variant": str(default_row["scenario_variant"]),
        "robustness_candidate": str(robustness_row["candidate_label"]),
        "robustness_scenario_variant": str(robustness_row["scenario_variant"]),
        "main_reason": (
            f"{default_row['candidate_label']} with {default_row['scenario_variant']} achieved the strongest scenario score "
            "under the notebook's coverage-versus-sharpness rule."
        ),
        "main_caveat": (
            "This recommendation only covers scenario calibration quality. The final bidding choice still needs toy MILP "
            "and full DA MILP/CVaR testing."
        ),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _rank_rows_by_centroid_distance(
    candidates: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...] | list[str],
    tie_break_cols: tuple[str, ...] | list[str],
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    values = candidates[list(feature_columns)].astype(float)
    means = values.mean(axis=0)
    stds = values.std(axis=0, ddof=0).replace(0.0, 1.0)
    z_scores = (values - means) / stds
    ranked = candidates.copy()
    ranked["selection_metric_value"] = np.sqrt((z_scores**2).sum(axis=1))
    ranked = ranked.sort_values(["selection_metric_value", *list(tie_break_cols)]).reset_index(drop=True)
    ranked["candidate_rank"] = ranked.index + 1
    return ranked


def _rank_rows_by_sort(
    candidates: pd.DataFrame,
    *,
    sort_cols: tuple[str, ...] | list[str],
    ascending: tuple[bool, ...] | list[bool],
    selection_metric_name: str,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    ranked = candidates.sort_values(list(sort_cols), ascending=list(ascending)).reset_index(drop=True).copy()
    ranked["selection_metric_value"] = pd.to_numeric(ranked[selection_metric_name], errors="coerce")
    ranked["candidate_rank"] = ranked.index + 1
    return ranked


def _select_distinct_category_rows(
    ranked_specs: list[tuple[dict[str, Any], pd.DataFrame]],
) -> pd.DataFrame:
    selected_frames: list[pd.DataFrame] = []
    used_days: set[str] = set()
    for metadata, ranked in ranked_specs:
        if ranked.empty:
            continue
        distinct = ranked[~ranked["delivery_day"].astype(str).isin(used_days)].copy()
        chosen = distinct.head(1) if not distinct.empty else ranked.head(1)
        if chosen.empty:
            continue
        chosen = chosen.copy()
        for key, value in metadata.items():
            chosen[key] = value
        chosen["used_duplicate_fallback"] = bool(distinct.empty)
        selected_frames.append(chosen)
        used_days.update(chosen["delivery_day"].astype(str).tolist())
    if not selected_frames:
        return pd.DataFrame()
    return pd.concat(selected_frames, ignore_index=True).drop_duplicates(subset=["day_category"]).reset_index(drop=True)


def select_representative_days(
    period_residuals: pd.DataFrame,
    *,
    candidate_key: str,
    dataset_split: str,
) -> pd.DataFrame:
    candidate_days = period_residuals[
        (period_residuals["candidate_key"].astype(str) == str(candidate_key))
        & (period_residuals["dataset_split"].astype(str) == str(dataset_split))
    ].copy()
    if candidate_days.empty:
        return pd.DataFrame()

    daily = (
        candidate_days.groupby(["target_local_date", "delivery_day"], dropna=False)
        .agg(
            season=("season", "first"),
            actual_daily_spread=("y_true", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
            actual_daily_mean=("y_true", "mean"),
            actual_daily_min=("y_true", "min"),
            actual_daily_max=("y_true", "max"),
            mean_positive_residual=("underestimation_component", "mean"),
            overestimation_severity=("overestimation_component", "mean"),
            abs_daily_bias=("residual", lambda values: float(abs(pd.Series(values).mean()))),
            negative_hours_share=("y_true", lambda values: float((pd.Series(values) < 0.0).mean())),
            negative_hours_count=("y_true", lambda values: int((pd.Series(values) < 0.0).sum())),
        )
        .reset_index()
    )
    if daily.empty:
        return daily

    winter_ranked = _rank_rows_by_centroid_distance(
        daily[daily["season"].astype(str) == "winter"].copy(),
        feature_columns=DAILY_PROFILE_CENTROID_COLUMNS,
        tie_break_cols=("delivery_day",),
    )
    summer_ranked = _rank_rows_by_centroid_distance(
        daily[daily["season"].astype(str) == "summer"].copy(),
        feature_columns=DAILY_PROFILE_CENTROID_COLUMNS,
        tie_break_cols=("delivery_day",),
    )
    high_vol_threshold = float(daily["actual_daily_spread"].quantile(0.90))
    high_vol_candidates = daily[daily["actual_daily_spread"] >= high_vol_threshold].copy()
    if high_vol_candidates.empty:
        high_vol_candidates = daily.copy()
    high_vol_ranked = _rank_rows_by_sort(
        high_vol_candidates,
        sort_cols=("actual_daily_spread", "delivery_day"),
        ascending=(False, True),
        selection_metric_name="actual_daily_spread",
    )
    low_price_ranked = _rank_rows_by_sort(
        daily.copy(),
        sort_cols=("actual_daily_mean", "negative_hours_share", "actual_daily_min", "delivery_day"),
        ascending=(True, False, True, True),
        selection_metric_name="actual_daily_mean",
    )
    return _select_distinct_category_rows(
        [
            (
                {
                    "day_category": "typical_winter_day",
                    "plot_title": "Typical Winter Day",
                    "day_reason": "Winter day closest to the winter centroid across level, spread, bias, and negative-price share.",
                    "selection_metric_name": "centroid_distance",
                },
                winter_ranked,
            ),
            (
                {
                    "day_category": "typical_summer_day",
                    "plot_title": "Typical Summer Day",
                    "day_reason": "Summer day closest to the summer centroid across level, spread, bias, and negative-price share.",
                    "selection_metric_name": "centroid_distance",
                },
                summer_ranked,
            ),
            (
                {
                    "day_category": "high_volatility_day",
                    "plot_title": "High-Volatility Day",
                    "day_reason": "Day selected from the top decile of realised daily spread, preferring an unused day when possible.",
                    "selection_metric_name": "actual_daily_spread",
                },
                high_vol_ranked,
            ),
            (
                {
                    "day_category": "low_price_day",
                    "plot_title": "Low-Price Day",
                    "day_reason": "Day with the lowest realised daily mean price, using negative-hour share and the daily minimum as tie-breakers.",
                    "selection_metric_name": "actual_daily_mean",
                },
                low_price_ranked,
            ),
        ]
    )


def select_stress_diagnostic_days(
    daily_profiles: pd.DataFrame,
    *,
    candidate_key: str,
    dataset_split: str,
) -> pd.DataFrame:
    candidate_days = daily_profiles[
        (daily_profiles["candidate_key"].astype(str) == str(candidate_key))
        & (daily_profiles["dataset_split"].astype(str) == str(dataset_split))
    ].copy()
    if candidate_days.empty:
        return pd.DataFrame()

    rule_specs = [
        (
            "worst_daily_underestimation",
            "mean_positive_residual",
            "Worst Daily Underestimation",
            "Largest average positive residual across the day.",
        ),
        (
            "worst_evening_peak_miss",
            "evening_peak_underestimation",
            "Worst Evening Peak Miss",
            "Largest mean underestimation during local peak hours 17:00 to 21:00.",
        ),
        (
            "worst_daily_max_price_miss",
            "daily_max_price_miss",
            "Worst Daily Max-Price Miss",
            "Largest underestimation at the realised daily maximum price hour.",
        ),
        (
            "worst_top3_expensive_hour_miss",
            "top3_expensive_underestimation",
            "Worst Top-3 Expensive-Hour Miss",
            "Largest mean underestimation across the realised top-3 expensive hours.",
        ),
        (
            "representative_high_volatility_day",
            "realised_daily_spread",
            "Highest-Spread Day",
            "Largest realised daily spread in the evaluation sample.",
        ),
        (
            "strongest_overestimation_profile",
            "overestimation_severity",
            "Strongest Overestimation Profile",
            "Largest average negative-residual severity across the day.",
        ),
    ]

    ranked_specs: list[tuple[dict[str, Any], pd.DataFrame]] = []
    for day_category, metric_column, plot_title, day_reason in rule_specs:
        ranked = _rank_rows_by_sort(
            candidate_days.copy(),
            sort_cols=(metric_column, "delivery_day"),
            ascending=(False, True),
            selection_metric_name=metric_column,
        )
        ranked_specs.append(
            (
                {
                    "day_category": day_category,
                    "plot_title": plot_title,
                    "day_reason": day_reason,
                    "selection_metric_name": metric_column,
                },
                ranked,
            )
        )
    return _select_distinct_category_rows(ranked_specs)


def select_plot_weeks_from_period_residuals(
    period_residuals: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
    categories: tuple[str, ...] | list[str] = SCENARIO_PLOT_WEEK_CATEGORIES,
) -> pd.DataFrame:
    if period_residuals.empty:
        return pd.DataFrame()

    canonical = (
        period_residuals[["target_timestamp_utc", "y_true", "is_observed_target"]]
        .rename(columns={"target_timestamp_utc": config.timestamp_col, "y_true": config.target_col})
        .drop_duplicates(subset=[config.timestamp_col], keep="last")
        .sort_values(config.timestamp_col)
        .reset_index(drop=True)
    )
    weekly_features = build_weekly_feature_table(canonical, config)
    if weekly_features.empty:
        return pd.DataFrame()

    eligible = weekly_features[weekly_features["observed_coverage_pct"] >= config.visual_week_min_observed_coverage_pct].copy()
    if eligible.empty:
        return pd.DataFrame()

    winter_ranked = _rank_rows_by_centroid_distance(
        eligible[eligible["season"].astype(str) == "winter"].copy(),
        feature_columns=WEEKLY_FEATURE_COLUMNS,
        tie_break_cols=("week_start_local_date",),
    ).rename(columns={"iso_week_id": "delivery_day"})
    summer_ranked = _rank_rows_by_centroid_distance(
        eligible[eligible["season"].astype(str) == "summer"].copy(),
        feature_columns=WEEKLY_FEATURE_COLUMNS,
        tie_break_cols=("week_start_local_date",),
    ).rename(columns={"iso_week_id": "delivery_day"})
    volatility_ranked = _rank_rows_by_sort(
        eligible.copy(),
        sort_cols=("weekly_std_price", "week_start_local_date"),
        ascending=(False, True),
        selection_metric_name="weekly_std_price",
    ).rename(columns={"iso_week_id": "delivery_day"})
    low_price_ranked = _rank_rows_by_sort(
        eligible.copy(),
        sort_cols=("weekly_mean_price", "negative_hours_share", "week_start_local_date"),
        ascending=(True, False, True),
        selection_metric_name="weekly_mean_price",
    ).rename(columns={"iso_week_id": "delivery_day"})

    selected = _select_distinct_category_rows(
        [
            (
                {
                    "day_category": "typical_winter",
                    "plot_title": "Typical Winter Week",
                    "day_reason": "Winter week closest to the winter centroid across the repo's weekly feature set.",
                    "selection_metric_name": "centroid_distance",
                },
                winter_ranked,
            ),
            (
                {
                    "day_category": "typical_summer",
                    "plot_title": "Typical Summer Week",
                    "day_reason": "Summer week closest to the summer centroid across the repo's weekly feature set.",
                    "selection_metric_name": "centroid_distance",
                },
                summer_ranked,
            ),
            (
                {
                    "day_category": "high_volatility",
                    "plot_title": "High-Volatility Week",
                    "day_reason": "Week with the highest weekly standard deviation, preferring an unused week when possible.",
                    "selection_metric_name": "weekly_std_price",
                },
                volatility_ranked,
            ),
            (
                {
                    "day_category": "low_price",
                    "plot_title": "Low-Price Week",
                    "day_reason": "Week with the lowest weekly mean price, using negative-hour share as a tie-breaker.",
                    "selection_metric_name": "weekly_mean_price",
                },
                low_price_ranked,
            ),
        ]
    )
    if selected.empty:
        return selected
    selected = selected.rename(columns={"day_category": "category"}).drop(columns=["delivery_day"])
    category_order = {str(category): idx for idx, category in enumerate([str(value) for value in categories])}
    selected["category_order"] = selected["category"].astype(str).map(category_order)
    selected = selected[selected["category_order"].notna()].copy()
    if selected.empty:
        return selected
    if "iso_week_id" not in selected.columns and {"iso_year", "iso_week"}.issubset(selected.columns):
        selected["iso_week_id"] = selected.apply(
            lambda row: f"{int(row['iso_year'])}-W{int(row['iso_week']):02d}",
            axis=1,
        )
    return selected.sort_values(["category_order", "week_start_local_date"]).drop(columns=["category_order"]).reset_index(drop=True)


def plot_scenario_grid(
    scenario_prices_long: pd.DataFrame,
    scenario_metadata: pd.DataFrame,
    period_quantiles: pd.DataFrame,
    *,
    candidate_variant_rows: list[dict[str, str]],
    representative_days: list[dict[str, Any]] | pd.DataFrame,
    title: str,
    output_path: Path | None = None,
    show: bool = True,
    max_columns: int = 3,
) -> list[Path]:
    if isinstance(representative_days, pd.DataFrame):
        day_rows = representative_days.to_dict(orient="records")
    else:
        day_rows = representative_days
    if not candidate_variant_rows or not day_rows:
        return []
    max_columns = max(int(max_columns), 1)
    saved_paths: list[Path] = []
    day_chunks = [day_rows[start : start + max_columns] for start in range(0, len(day_rows), max_columns)]

    for chunk_idx, day_chunk in enumerate(day_chunks, start=1):
        n_rows = len(candidate_variant_rows)
        n_cols = len(day_chunk)
        fig, axes = plt.subplots(
            n_rows,
            n_cols,
            figsize=(5.2 * n_cols, 3.8 * n_rows),
            sharey="row",
            squeeze=False,
        )

        for row_idx, candidate_row in enumerate(candidate_variant_rows):
            candidate_key = str(candidate_row["candidate_key"])
            candidate_label = str(candidate_row["candidate_label"])
            scenario_variant = str(candidate_row["scenario_variant"])
            for col_idx, day_row in enumerate(day_chunk):
                delivery_day = str(day_row["delivery_day"])
                ax = axes[row_idx][col_idx]
                subset = scenario_prices_long[
                    (scenario_prices_long["candidate_key"].astype(str) == candidate_key)
                    & (scenario_prices_long["scenario_variant"].astype(str) == scenario_variant)
                    & (scenario_prices_long["delivery_day"].astype(str) == delivery_day)
                ].copy()
                quantiles = period_quantiles[
                    (period_quantiles["candidate_key"].astype(str) == candidate_key)
                    & (period_quantiles["scenario_variant"].astype(str) == scenario_variant)
                    & (period_quantiles["delivery_day"].astype(str) == delivery_day)
                ].copy()
                protected_ids = set(
                    scenario_metadata[
                        (scenario_metadata["candidate_key"].astype(str) == candidate_key)
                        & (scenario_metadata["scenario_variant"].astype(str) == scenario_variant)
                        & (scenario_metadata["delivery_day"].astype(str) == delivery_day)
                        & (scenario_metadata["protected"].fillna(False))
                    ]["scenario_id"].astype(str).tolist()
                )

                for scenario_id, scenario_group in subset.groupby("scenario_id", dropna=False):
                    ordered = scenario_group.sort_values(["period_index", "period_timestamp"])
                    is_protected = str(scenario_id) in protected_ids
                    ax.plot(
                        ordered["period_timestamp"],
                        ordered["scenario_price"],
                        color="#d95f02" if is_protected else "#4c78a8",
                        linewidth=1.35 if is_protected else 0.5,
                        alpha=0.72 if is_protected else 0.08,
                        linestyle="--" if is_protected else "-",
                        zorder=2 if is_protected else 1,
                    )

                if not quantiles.empty:
                    quantiles = quantiles.sort_values(["period_index", "period_timestamp"])
                    ax.fill_between(
                        quantiles["period_timestamp"],
                        quantiles["p10"],
                        quantiles["p90"],
                        color="#9ecae1",
                        alpha=0.28,
                        zorder=3,
                    )
                    ax.plot(quantiles["period_timestamp"], quantiles["p50"], color="#08519c", linewidth=1.8, zorder=4)
                    ax.plot(quantiles["period_timestamp"], quantiles["central_forecast_price"], color="#6a3d9a", linewidth=1.5, zorder=4)
                    ax.plot(quantiles["period_timestamp"], quantiles["actual_price"], color="#111111", linewidth=2.0, zorder=5)

                if row_idx == 0:
                    plot_title = str(day_row.get("plot_title") or str(day_row.get("day_category", "")).replace("_", " ").title()).strip()
                    ax.set_title(f"{plot_title}\n{delivery_day}", fontsize=10.5, fontweight="bold")
                if col_idx == 0:
                    ax.set_ylabel(f"{candidate_label}\nEUR/MWh")
                else:
                    ax.set_ylabel("")
                if row_idx == n_rows - 1:
                    ax.set_xlabel("UTC time")
                else:
                    ax.set_xlabel("")

                annotation_parts: list[str] = []
                if pd.notna(day_row.get("actual_daily_mean")):
                    annotation_parts.append(f"mean={float(day_row['actual_daily_mean']):.1f}")
                if pd.notna(day_row.get("actual_daily_spread")):
                    annotation_parts.append(f"spread={float(day_row['actual_daily_spread']):.1f}")
                if pd.notna(day_row.get("selection_metric_value")):
                    metric_name = str(day_row.get("selection_metric_name", "metric")).replace("_", " ")
                    annotation_parts.append(f"{metric_name}={float(day_row['selection_metric_value']):.1f}")
                if annotation_parts:
                    ax.text(
                        0.01,
                        0.98,
                        " | ".join(annotation_parts),
                        transform=ax.transAxes,
                        ha="left",
                        va="top",
                        fontsize=8.2,
                        bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none", "alpha": 0.75},
                    )
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                ax.grid(alpha=0.22)
                ax.tick_params(axis="x", labelrotation=0)

        legend_handles = [
            Line2D([0], [0], color="#4c78a8", lw=1.1, alpha=0.20, label="Stochastic scenarios"),
            Line2D([0], [0], color="#d95f02", lw=1.5, linestyle="--", alpha=0.80, label="Protected stress scenarios"),
            Patch(facecolor="#9ecae1", alpha=0.28, label="p10-p90 envelope"),
            Line2D([0], [0], color="#08519c", lw=1.8, label="Scenario p50"),
            Line2D([0], [0], color="#6a3d9a", lw=1.5, label="Central forecast"),
            Line2D([0], [0], color="#111111", lw=2.0, label="Actual price"),
        ]
        fig.legend(handles=legend_handles, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.02))
        page_title = title if len(day_chunks) == 1 else f"{title} ({chunk_idx}/{len(day_chunks)})"
        fig.suptitle(page_title, x=0.01, ha="left", fontsize=13, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save_path = None
        if output_path is not None:
            save_path = (
                output_path
                if len(day_chunks) == 1
                else output_path.with_name(f"{output_path.stem}_part{chunk_idx:02d}_of{len(day_chunks):02d}{output_path.suffix}")
            )
            save_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(save_path, dpi=180, bbox_inches="tight")
            saved_paths.append(save_path)
        if show:
            plt.show()
        else:
            plt.close(fig)
    return saved_paths


def _best_scenario_score_for_run(run_dir: Path) -> float | None:
    comparison_path = run_dir / "final_scenario_model_comparison.csv"
    validation_path = run_dir / "scenario_validation_summary.csv"
    try:
        if comparison_path.exists():
            comparison = pd.read_csv(comparison_path)
            if "scenario_score" in comparison.columns and not comparison.empty:
                return float(pd.to_numeric(comparison["scenario_score"], errors="coerce").max())
        if validation_path.exists():
            validation = pd.read_csv(validation_path)
            if "scenario_score" in validation.columns and not validation.empty:
                return float(pd.to_numeric(validation["scenario_score"], errors="coerce").max())
    except (OSError, pd.errors.EmptyDataError, ValueError, TypeError):
        return None
    return None


def apply_notebook_artifact_retention(
    artifact_root: Path,
    *,
    current_run_dir: Path | None = None,
    keep_latest_n: int = 1,
    keep_best_n: int = 1,
) -> dict[str, Any]:
    root = Path(artifact_root)
    if not root.exists():
        return {
            "artifact_root": str(root),
            "latest_kept_runs": [],
            "best_kept_runs": [],
            "full_data_kept_runs": [],
            "pruned_runs": [],
            "pruned_items": [],
        }

    run_dirs = sorted([candidate for candidate in root.iterdir() if candidate.is_dir()], key=lambda path: path.name, reverse=True)
    latest_dirs = run_dirs[: max(int(keep_latest_n), 0)]

    scored_runs: list[tuple[Path, float]] = []
    for run_dir in run_dirs:
        score = _best_scenario_score_for_run(run_dir)
        if score is not None and not pd.isna(score):
            scored_runs.append((run_dir, float(score)))
    best_dirs = [run_dir for run_dir, _ in sorted(scored_runs, key=lambda item: (item[1], item[0].name), reverse=True)[: max(int(keep_best_n), 0)]]

    keep_full: set[Path] = set(latest_dirs) | set(best_dirs)
    if current_run_dir is not None:
        keep_full.add(Path(current_run_dir))

    pruned_runs: list[str] = []
    pruned_items: list[str] = []
    for run_dir in run_dirs:
        if run_dir in keep_full:
            continue
        run_pruned = False
        for artifact_name in PRUNABLE_NOTEBOOK_ARTIFACTS:
            target = run_dir / artifact_name
            if not target.exists():
                continue
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            pruned_items.append(str(target))
            run_pruned = True
        if run_pruned:
            pruned_runs.append(str(run_dir))

    return {
        "artifact_root": str(root),
        "latest_kept_runs": [str(path) for path in latest_dirs],
        "best_kept_runs": [str(path) for path in best_dirs],
        "full_data_kept_runs": [str(path) for path in sorted(keep_full, key=lambda path: path.name)],
        "pruned_runs": pruned_runs,
        "pruned_items": pruned_items,
        "essential_files_retained_in_all_runs": list(ESSENTIAL_NOTEBOOK_ARTIFACTS),
        "prunable_files_removed_from_older_runs": list(PRUNABLE_NOTEBOOK_ARTIFACTS),
    }


def _read_csv_with_optional_dates(path: Path, *, parse_dates: tuple[str, ...] = ()) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0)
    available_date_cols = [column for column in parse_dates if column in header.columns]
    return pd.read_csv(path, parse_dates=available_date_cols)


def find_latest_scenario_artifact_run(output_root: Path, notebook_slug: str) -> Path | None:
    artifact_root = Path(output_root) / "notebook_artifacts" / str(notebook_slug)
    if not artifact_root.exists():
        return None
    run_dirs = sorted(
        [
            path
            for path in artifact_root.iterdir()
            if path.is_dir() and (path / "scenario_generation_run_summary.json").exists()
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    return run_dirs[0] if run_dirs else None


def load_saved_scenario_artifacts(
    run_dir: Path,
    *,
    config: HourlyDAPipelineConfig,
) -> dict[str, Any]:
    artifact_dir = Path(run_dir)
    if not artifact_dir.exists():
        raise FileNotFoundError(f"Saved scenario artifact directory does not exist: {artifact_dir}")

    scenario_prices_long = _read_csv_with_optional_dates(
        artifact_dir / "scenario_prices_long.csv",
        parse_dates=("period_timestamp",),
    )
    scenario_metadata = _read_csv_with_optional_dates(artifact_dir / "scenario_metadata.csv")
    residual_periods = _read_csv_with_optional_dates(
        artifact_dir / "residual_period_table.csv",
        parse_dates=("forecast_origin_utc", "target_timestamp_utc", "forecast_origin_local", "target_timestamp_local"),
    )
    residual_daily_profiles = _read_csv_with_optional_dates(artifact_dir / "residual_daily_profiles.csv")
    scenario_validation_summary = _read_csv_with_optional_dates(artifact_dir / "scenario_validation_summary.csv")
    period_quantiles_path = artifact_dir / "scenario_period_quantiles.csv"
    period_quantiles = _read_csv_with_optional_dates(period_quantiles_path, parse_dates=("period_timestamp",))
    if period_quantiles.empty and not scenario_prices_long.empty:
        period_quantiles = validate_scenario_set(scenario_prices_long, config=config)["period_quantiles"]
        if not period_quantiles.empty:
            period_quantiles.to_csv(period_quantiles_path, index=False)

    run_summary = load_json(artifact_dir, "scenario_generation_run_summary.json")
    bundle: dict[str, Any] = {
        "output_dir": artifact_dir,
        "scenario_prices_long": scenario_prices_long,
        "scenario_metadata": scenario_metadata,
        "residual_periods": residual_periods,
        "residual_daily_profiles": residual_daily_profiles,
        "scenario_validation_summary": scenario_validation_summary,
        "period_quantiles": period_quantiles,
        "target_split": str(run_summary.get("target_split_used_for_scenario_evaluation", "validation")),
        "calibration_split": str(run_summary.get("data_split_used_for_residual_calibration", "validation")),
    }
    for filename, key, parse_dates in [
        ("seasonal_regime_days.csv", "seasonal_regime_days", ()),
        ("stress_diagnostic_days.csv", "stress_diagnostic_days", ()),
        ("selected_plot_weeks.csv", "selected_plot_weeks", ()),
    ]:
        bundle[key] = _read_csv_with_optional_dates(artifact_dir / filename, parse_dates=parse_dates)
    return bundle


def create_scenario_output_paths(output_root: Path, notebook_slug: str) -> ScenarioOutputPaths:
    scenario_run_id = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{notebook_slug}"
    timestamp_tokens = scenario_run_id.split("_", 2)
    run_dir_name = "_".join(timestamp_tokens[:2]) if len(timestamp_tokens) >= 2 else scenario_run_id
    output_dir = Path(output_root) / "notebook_artifacts" / notebook_slug / run_dir_name
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    return ScenarioOutputPaths(scenario_run_id=scenario_run_id, output_dir=output_dir, plots_dir=plots_dir)


def generate_scenario_bundle(
    corrected_periods: pd.DataFrame,
    daily_profiles: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
    horizon_spec: ScenarioHorizonSpec | None = None,
    calibration_split: str,
    target_split: str,
    selected_candidate_keys: list[str],
    variant_plan: pd.DataFrame,
    scenario_run_id: str,
    random_seed: int,
    n_raw_scenarios: int,
    n_final_scenarios: int,
    normal_share: float,
    positive_tail_share: float,
    negative_tail_share: float,
    stress_share: float,
    protected_tail_share: float = 0.20,
    probability_policy: str = "empirical_cluster_mass",
    reduction_method: str = "tail_protected_representative_v1",
    residual_scale_factor: float = 1.0,
    residual_scaling_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_horizon_spec = horizon_spec or resolve_scenario_horizon_spec(horizon_mode="D_ONLY", granularity="hourly")
    calibration_periods = corrected_periods[
        (corrected_periods["dataset_split"].astype(str) == str(calibration_split))
        & (corrected_periods["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys]))
    ].copy()
    target_periods = corrected_periods[
        (corrected_periods["dataset_split"].astype(str) == str(target_split))
        & (corrected_periods["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys]))
    ].copy()
    if calibration_periods.empty or target_periods.empty:
        return {
            "raw_scenarios": pd.DataFrame(),
            "raw_metadata": pd.DataFrame(),
            "final_scenarios": pd.DataFrame(),
            "final_metadata": pd.DataFrame(),
            "bank_logs": pd.DataFrame(),
            "reduction_summary": pd.DataFrame(),
        }

    profile_lookup = _build_profile_lookup(calibration_periods)
    rng = np.random.default_rng(int(random_seed))
    raw_scenarios: list[pd.DataFrame] = []
    raw_metadata: list[pd.DataFrame] = []
    final_scenarios: list[pd.DataFrame] = []
    final_metadata: list[pd.DataFrame] = []
    bank_logs: list[dict[str, Any]] = []
    reduction_rows: list[dict[str, Any]] = []
    causal_filter_violations = 0
    causal_filter_rows_dropped = 0
    used_reconstructed_forecast_origin = False

    target_days = (
        target_periods.groupby(["candidate_key", "candidate_label", "dataset_split", "target_local_date"], dropna=False)
        .size()
        .rename("rows")
        .reset_index()
        .sort_values(["candidate_label", "dataset_split", "target_local_date"])
        .reset_index(drop=True)
    )

    for variant_row in variant_plan.to_dict(orient="records"):
        variant_name = str(variant_row["scenario_variant"])
        use_option_a = bool(variant_row["use_option_a"])
        use_option_b = bool(variant_row["use_option_b"])
        use_option_c = bool(variant_row["use_option_c"])

        for target_day_record in target_days.to_dict(orient="records"):
            candidate_key = str(target_day_record["candidate_key"])
            day_mask = (
                (target_periods["candidate_key"].astype(str) == candidate_key)
                & (target_periods["dataset_split"].astype(str) == str(target_day_record["dataset_split"]))
                & (target_periods["target_local_date"] == target_day_record["target_local_date"])
            )
            target_day_frame = _sorted_periods_for_day(target_periods[day_mask].copy())
            if target_day_frame.empty:
                continue

            candidate_daily = daily_profiles[
                (daily_profiles["candidate_key"].astype(str) == candidate_key)
                & (daily_profiles["dataset_split"].astype(str) == str(calibration_split))
            ].copy()
            target_day_summary = (
                target_day_frame[
                    [
                        "candidate_key",
                        "candidate_label",
                        "dataset_split",
                        "delivery_day",
                        "season",
                        "day_type",
                        "lead_day_label",
                        "hours_in_day",
                    ]
                ]
                .drop_duplicates()
                .iloc[0]
            )
            target_forecast_origin_utc, origin_reconstructed = _resolve_target_forecast_origin_utc(
                target_day_frame,
                config=config,
            )
            used_reconstructed_forecast_origin = used_reconstructed_forecast_origin or bool(origin_reconstructed)
            if pd.isna(target_forecast_origin_utc):
                bank_logs.append(
                    {
                        "candidate_key": candidate_key,
                        "candidate_label": str(target_day_summary["candidate_label"]),
                        "scenario_variant": variant_name,
                        "dataset_split": str(target_day_record["dataset_split"]),
                        "delivery_day": str(target_day_summary["delivery_day"]),
                        "bank_level": "missing_forecast_origin",
                        "available_residual_days": 0,
                        "available_after_causal_filter": 0,
                        "hours_in_day": int(target_day_summary["hours_in_day"]),
                        "warning_small_bank": True,
                        "causal_source_filter_applied": True,
                        "causal_source_filter_violations": 0,
                        "causal_rows_dropped": 0,
                        "target_forecast_origin_utc": None,
                        "forecast_origin_reconstructed": bool(origin_reconstructed),
                    }
                )
                continue

            bank, bank_level = _choose_bank_for_target_day(candidate_daily, target_day_summary)
            available_before_filter = int(bank.shape[0])
            bank, day_violations = _apply_causal_source_filter(bank, forecast_origin_utc=pd.Timestamp(target_forecast_origin_utc))
            available_after_filter = int(bank.shape[0])
            dropped_rows = max(available_before_filter - available_after_filter, 0)
            causal_filter_rows_dropped += int(dropped_rows)
            if bank.empty:
                bank_logs.append(
                    {
                        "candidate_key": candidate_key,
                        "candidate_label": str(target_day_summary["candidate_label"]),
                        "scenario_variant": variant_name,
                        "dataset_split": str(target_day_record["dataset_split"]),
                        "delivery_day": str(target_day_summary["delivery_day"]),
                        "bank_level": f"{bank_level}|causal_filter_empty",
                        "available_residual_days": available_before_filter,
                        "available_after_causal_filter": available_after_filter,
                        "hours_in_day": int(target_day_summary["hours_in_day"]),
                        "warning_small_bank": True,
                        "causal_source_filter_applied": True,
                        "causal_source_filter_violations": int(day_violations),
                        "causal_rows_dropped": int(dropped_rows),
                        "target_forecast_origin_utc": str(pd.Timestamp(target_forecast_origin_utc)),
                        "forecast_origin_reconstructed": bool(origin_reconstructed),
                    }
                )
                continue
            bank_logs.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": str(target_day_summary["candidate_label"]),
                    "scenario_variant": variant_name,
                    "dataset_split": str(target_day_record["dataset_split"]),
                    "delivery_day": str(target_day_summary["delivery_day"]),
                    "bank_level": bank_level,
                    "available_residual_days": available_before_filter,
                    "available_after_causal_filter": available_after_filter,
                    "hours_in_day": int(target_day_summary["hours_in_day"]),
                    "warning_small_bank": bool(available_after_filter < 10),
                    "causal_source_filter_applied": True,
                    "causal_source_filter_violations": int(day_violations),
                    "causal_rows_dropped": int(dropped_rows),
                    "target_forecast_origin_utc": str(pd.Timestamp(target_forecast_origin_utc)),
                    "forecast_origin_reconstructed": bool(origin_reconstructed),
                }
            )

            stress_scenarios = _select_stress_scenarios(bank, candidate_daily) if use_option_b else []
            stochastic_count = max(int(n_raw_scenarios) - len(stress_scenarios), 1)
            sampled_sources = _sample_source_days(
                bank,
                n_samples=stochastic_count,
                rng=rng,
                use_option_a=use_option_a,
                normal_share=float(normal_share),
                positive_tail_share=float(positive_tail_share),
                negative_tail_share=float(negative_tail_share),
            )
            sampled_sources.extend(stress_scenarios)
            day_raw_scenarios, day_raw_metadata = _assemble_scenario_rows_for_day(
                scenario_run_id=scenario_run_id,
                candidate_key=candidate_key,
                candidate_label=str(target_day_summary["candidate_label"]),
                scenario_variant=variant_name,
                dataset_split=str(target_day_record["dataset_split"]),
                target_day_frame=target_day_frame,
                sampled_sources=sampled_sources,
                profile_lookup=profile_lookup,
                use_option_c=use_option_c,
                stress_share=float(stress_share) if use_option_b else 0.0,
                residual_scale_factor=float(residual_scale_factor),
                residual_scaling_profile=residual_scaling_profile,
            )
            if day_raw_scenarios.empty or day_raw_metadata.empty:
                continue
            if {"source_residual_day_end_utc", "target_forecast_origin_utc"}.issubset(set(day_raw_metadata.columns)):
                source_end = pd.to_datetime(day_raw_metadata["source_residual_day_end_utc"], utc=True, errors="coerce")
                target_origin = pd.to_datetime(day_raw_metadata["target_forecast_origin_utc"], utc=True, errors="coerce")
                causal_filter_violations += int((source_end >= target_origin).sum())
            day_final_scenarios, day_final_metadata = reduce_daily_scenarios(
                day_raw_scenarios,
                day_raw_metadata,
                n_final_scenarios=int(n_final_scenarios),
                random_seed=int(rng.integers(0, 1_000_000_000)),
                protected_tail_share=float(protected_tail_share),
                reduction_method=str(reduction_method),
                probability_policy=str(probability_policy),
            )
            if not day_final_scenarios.empty:
                day_final_scenarios["horizon_mode"] = str(resolved_horizon_spec.horizon_mode)
                day_final_scenarios["horizon_days"] = int(resolved_horizon_spec.horizon_days)
                day_final_scenarios["granularity"] = str(resolved_horizon_spec.granularity)
                day_final_scenarios["block_length"] = int(resolved_horizon_spec.block_length)
                day_final_scenarios["cross_day_coherence"] = bool(resolved_horizon_spec.horizon_days > 1)
                day_final_scenarios["source_residual_block_id"] = day_final_scenarios["source_residual_day"].astype(str)
                day_final_scenarios["source_residual_start_utc"] = pd.NaT
                day_final_scenarios["source_residual_end_utc"] = pd.NaT
            if not day_final_metadata.empty:
                day_final_metadata["horizon_mode"] = str(resolved_horizon_spec.horizon_mode)
                day_final_metadata["horizon_days"] = int(resolved_horizon_spec.horizon_days)
                day_final_metadata["granularity"] = str(resolved_horizon_spec.granularity)
                day_final_metadata["block_length"] = int(resolved_horizon_spec.block_length)
                day_final_metadata["cross_day_coherence"] = bool(resolved_horizon_spec.horizon_days > 1)
                day_final_metadata["source_residual_block_id"] = day_final_metadata["source_day"].astype(str)
                day_final_metadata["source_residual_start_utc"] = day_final_metadata.get("source_residual_day_start_utc", pd.NaT)
                day_final_metadata["source_residual_end_utc"] = day_final_metadata.get("source_residual_day_end_utc", pd.NaT)
                source_start_map = day_final_metadata.set_index("scenario_id")["source_residual_start_utc"].to_dict()
                source_end_map = day_final_metadata.set_index("scenario_id")["source_residual_end_utc"].to_dict()
                day_final_scenarios["source_residual_start_utc"] = day_final_scenarios["scenario_id"].map(source_start_map)
                day_final_scenarios["source_residual_end_utc"] = day_final_scenarios["scenario_id"].map(source_end_map)
            raw_scenarios.append(day_raw_scenarios)
            raw_metadata.append(day_raw_metadata)
            final_scenarios.append(day_final_scenarios)
            final_metadata.append(day_final_metadata)
            reduction_rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": str(target_day_summary["candidate_label"]),
                    "scenario_variant": variant_name,
                    "dataset_split": str(target_day_record["dataset_split"]),
                    "delivery_day": str(target_day_summary["delivery_day"]),
                    "raw_scenario_count": int(day_raw_metadata["scenario_id"].nunique()),
                    "final_scenario_count": int(day_final_metadata["scenario_id"].nunique()),
                    "protected_retained": int(day_final_metadata["protected"].fillna(False).sum()),
                    "protected_tail_count": int(day_final_metadata.get("tail_protection_flag", pd.Series(dtype=bool)).fillna(False).sum())
                    if not day_final_metadata.empty
                    else 0,
                    "protected_tail_probability_mass": float(
                        day_final_metadata.loc[
                            day_final_metadata.get("tail_protection_flag", pd.Series(dtype=bool)).fillna(False),
                            "reduced_scenario_probability",
                        ].sum()
                    )
                    if {"tail_protection_flag", "reduced_scenario_probability"}.issubset(set(day_final_metadata.columns))
                    else np.nan,
                    "probability_policy": str(probability_policy),
                    "reduction_method": str(reduction_method),
                }
            )

    return {
        "raw_scenarios": pd.concat(raw_scenarios, ignore_index=True) if raw_scenarios else pd.DataFrame(),
        "raw_metadata": pd.concat(raw_metadata, ignore_index=True) if raw_metadata else pd.DataFrame(),
        "final_scenarios": pd.concat(final_scenarios, ignore_index=True) if final_scenarios else pd.DataFrame(),
        "final_metadata": pd.concat(final_metadata, ignore_index=True) if final_metadata else pd.DataFrame(),
        "bank_logs": pd.DataFrame(bank_logs).reset_index(drop=True),
        "reduction_summary": pd.DataFrame(reduction_rows).reset_index(drop=True),
        "causal_source_filter_applied": True,
        "causal_source_filter_violations": int(causal_filter_violations),
        "causal_source_filter_rows_dropped": int(causal_filter_rows_dropped),
        "forecast_origin_reconstruction_used": bool(used_reconstructed_forecast_origin),
    }
