from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .feature_registry import get_feature_columns_by_set, load_feature_family_map
from .finalisation_comparison import find_latest_qh_finalisation_run
from .phase04 import _build_feature_frame, _build_prediction_frame, _fit_lear, _fit_xgboost
from .reporting_metrics import (
    build_qh_phase2_reporting_bundle,
    summarize_standard_qh_metrics,
)


RUN_LABEL = "qh_fs1_endogenous_ablation"
REQUIRED_QH_FS1_FAMILIES = (
    "calendar",
    "anchor_level",
    "regime_flags",
    "ramp_shape_descriptors",
)
PARENT_MODEL_FAMILIES = ("lear", "xgboost")
PHASE2_FINALISATION_RUN_LABEL = "qh_fs1_fs2_model_comparison"
MAX_CHILD_DIR_NAME_LEN = 80
WINDOWS_SAFE_PATH_LIMIT = 240


@dataclass(frozen=True)
class Phase3BundlePaths:
    run_id: str
    run_dir: Path
    ablation_run_plan_csv: Path
    feature_family_parent_child_map_csv: Path
    feature_family_value_summary_csv: Path
    feature_family_value_by_model_csv: Path
    feature_family_value_by_reporting_level_csv: Path
    feature_family_value_by_horizon_csv: Path
    feature_family_value_by_frozen_week_csv: Path
    feature_family_value_ranking_metrics_csv: Path
    ablation_candidate_inventory_csv: Path
    ablation_model_settings_summary_csv: Path
    ablation_scope_warnings_csv: Path
    ablation_run_summary_json: Path


def phase3_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)


def _bundle_paths(config: QuarterHourDAExtensionConfig | None = None) -> Phase3BundlePaths:
    resolved = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = phase3_output_root(resolved) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return Phase3BundlePaths(
        run_id=run_id,
        run_dir=run_dir,
        ablation_run_plan_csv=run_dir / "ablation_run_plan.csv",
        feature_family_parent_child_map_csv=run_dir / "feature_family_parent_child_map.csv",
        feature_family_value_summary_csv=run_dir / "feature_family_value_summary.csv",
        feature_family_value_by_model_csv=run_dir / "feature_family_value_by_model.csv",
        feature_family_value_by_reporting_level_csv=run_dir / "feature_family_value_by_reporting_level.csv",
        feature_family_value_by_horizon_csv=run_dir / "feature_family_value_by_horizon.csv",
        feature_family_value_by_frozen_week_csv=run_dir / "feature_family_value_by_frozen_week.csv",
        feature_family_value_ranking_metrics_csv=run_dir / "feature_family_value_ranking_metrics.csv",
        ablation_candidate_inventory_csv=run_dir / "ablation_candidate_inventory.csv",
        ablation_model_settings_summary_csv=run_dir / "ablation_model_settings_summary.csv",
        ablation_scope_warnings_csv=run_dir / "ablation_scope_warnings.csv",
        ablation_run_summary_json=run_dir / "ablation_run_summary.json",
    )


def find_latest_qh_phase3_ablation_run(config: QuarterHourDAExtensionConfig | None = None) -> Path | None:
    root = phase3_output_root(config)
    if not root.exists():
        return None
    candidates = sorted(path for path in root.iterdir() if path.is_dir() and (path / "ablation_run_summary.json").exists())
    return candidates[-1] if candidates else None


def _active_qh_fs1_family_rows(config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    family_map = load_feature_family_map(config)
    rows = family_map[
        (family_map["feature_set_id"].astype(str) == "QH-FS1")
        & family_map["active_flag"].fillna(False).astype(bool)
        & (~family_map["feature_columns_csv"].fillna("").astype(str).str.strip().eq(""))
    ].copy()
    return rows.sort_values(["feature_family"]).reset_index(drop=True)


def _child_output_dir_slug(*, child_model_id: str, model_family: str, dropped_feature_family: str) -> str:
    family_short = "lear" if str(model_family) == "lear" else "xgb"
    family_drop = str(dropped_feature_family).lower().replace("-", "_").replace(" ", "_")
    hash8 = hashlib.sha1(str(child_model_id).encode("utf-8")).hexdigest()[:8]
    base = f"{family_short}_minus_{family_drop}_{hash8}"
    if len(base) <= MAX_CHILD_DIR_NAME_LEN:
        return base
    keep = max(8, MAX_CHILD_DIR_NAME_LEN - len(family_short) - len(hash8) - len("_minus__"))
    clipped = family_drop[:keep].rstrip("_")
    return f"{family_short}_minus_{clipped}_{hash8}"


def detect_active_qh_fs1_families(config: QuarterHourDAExtensionConfig | None = None) -> list[str]:
    rows = _active_qh_fs1_family_rows(config)
    return rows["feature_family"].astype(str).tolist()


def _load_phase2_parent_bundle(config: QuarterHourDAExtensionConfig | None = None) -> dict[str, Any]:
    resolved = config or QuarterHourDAExtensionConfig()
    latest = find_latest_qh_finalisation_run(resolved)
    if latest is None:
        raise FileNotFoundError("No saved Phase 2 finalisation bundle was found.")

    inventory = pd.read_csv(latest / "candidate_prediction_inventory.csv", low_memory=False)
    predictions = pd.read_csv(latest / "candidate_predictions_long.csv", low_memory=False)
    metrics_by_reporting_level = pd.read_csv(latest / "metrics_by_reporting_level.csv", low_memory=False)
    metrics_by_frozen_week = pd.read_csv(latest / "metrics_by_frozen_week.csv", low_memory=False)
    coverage = pd.read_csv(latest / "coverage_diagnostic_by_model.csv", low_memory=False)

    ranking_path = latest / "ranking_opportunity_metrics.csv"
    if ranking_path.exists():
        try:
            ranking = pd.read_csv(ranking_path, low_memory=False)
        except pd.errors.EmptyDataError:
            ranking = pd.DataFrame()
    else:
        ranking = pd.DataFrame()

    model_settings = pd.read_csv(latest / "model_settings_summary.csv", low_memory=False)
    run_summary = json.loads((latest / "run_summary.json").read_text(encoding="utf-8"))
    return {
        "run_dir": latest,
        "run_summary": run_summary,
        "inventory": inventory,
        "predictions": predictions,
        "metrics_by_reporting_level": metrics_by_reporting_level,
        "metrics_by_frozen_week": metrics_by_frozen_week,
        "coverage_diagnostic_by_model": coverage,
        "ranking_opportunity_metrics": ranking,
        "model_settings_summary": model_settings,
    }


def _extract_anchor_key_from_parent_model_id(parent_model_id: str) -> str:
    token = "__hourly_anchor__"
    text = str(parent_model_id)
    return text.split(token, 1)[1] if token in text else ""


def _load_parent_denominator_artifacts(config: QuarterHourDAExtensionConfig | None = None) -> dict[str, Any]:
    resolved = config or QuarterHourDAExtensionConfig()
    root = resolved.output_root / "finalisation_runs" / "qh_fs1_phase2_7_hourly_parity"
    if not root.exists():
        raise FileNotFoundError("Phase 2.7 parity bundle root was not found.")
    candidates = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    if not candidates:
        raise FileNotFoundError("No Phase 2.7 parity bundle run was found.")
    run_dir = candidates[-1]
    official = json.loads((run_dir / "official_naive_reference.json").read_text(encoding="utf-8"))
    denominator = pd.read_csv(run_dir / "official_naive_denominator_materialized.csv", low_memory=False)
    return {"run_dir": run_dir, "official_naive_reference": official, "denominator": denominator}


def _parent_candidates(bundle: dict[str, Any]) -> pd.DataFrame:
    preds = bundle["predictions"].copy()
    for column in ("forecast_origin_utc", "target_timestamp_utc"):
        preds[column] = pd.to_datetime(preds[column], utc=True, errors="coerce")
    preds["lead_day"] = pd.to_numeric(preds["lead_day"], errors="coerce").astype("Int64")

    learned = preds[
        preds["model_family"].astype(str).isin(PARENT_MODEL_FAMILIES)
        & preds["feature_set_id"].astype(str).eq("QH-FS1")
    ].copy()
    if "candidate_role" in learned.columns:
        learned = learned[learned["candidate_role"].astype(str).eq("candidate_equal_priority")].copy()
    if learned.empty:
        return pd.DataFrame()

    # Keep one canonical full parent per model family for fair LEAR/XGBoost parity.
    parent_keys = (
        learned[["model_family", "model"]]
        .drop_duplicates()
        .rename(columns={"model": "parent_model_id"})
        .copy()
    )
    parent_keys["parent_model_id"] = parent_keys["parent_model_id"].astype(str)
    parent_keys["model_family"] = parent_keys["model_family"].astype(str)
    if "hourly_anchor_candidate_key" in learned.columns:
        anchor_map = (
            learned[["model", "hourly_anchor_candidate_key"]]
            .drop_duplicates()
            .rename(columns={"model": "parent_model_id"})
        )
        parent_keys = parent_keys.merge(anchor_map, on="parent_model_id", how="left")
    else:
        parent_keys["hourly_anchor_candidate_key"] = ""

    def _priority(row: pd.Series) -> int:
        family = str(row["model_family"])
        parent_model_id = str(row["parent_model_id"])
        anchor_key = str(row.get("hourly_anchor_candidate_key", ""))
        score = 0
        if parent_model_id.startswith(f"qh-fs1__{family}__"):
            score += 10
        if family in anchor_key:
            score += 5
        return score

    parent_keys["selection_priority"] = parent_keys.apply(_priority, axis=1)
    canonical_parent_ids = (
        parent_keys.sort_values(
            ["model_family", "selection_priority", "parent_model_id"],
            ascending=[True, False, True],
        )
        .groupby("model_family", as_index=False)
        .head(1)["parent_model_id"]
        .astype(str)
        .tolist()
    )
    learned = learned[learned["model"].astype(str).isin(canonical_parent_ids)].copy()

    rows: list[dict[str, Any]] = []
    for model_id, group in learned.groupby("model", dropna=False):
        lead_days = sorted(pd.to_numeric(group["lead_day"], errors="coerce").dropna().astype(int).unique().tolist())
        rows.append(
            {
                "parent_model_id": str(model_id),
                "model_family": str(group["model_family"].iloc[0]),
                "feature_set_id": str(group["feature_set_id"].iloc[0]),
                "source_run_id": str(group["source_run_id"].iloc[0]),
                "source_type": str(group["source_type"].iloc[0]),
                "forecast_origin_count": int(group["forecast_origin_utc"].nunique()),
                "target_timestamp_count": int(group["target_timestamp_utc"].nunique()),
                "lead_days_present_csv": ",".join(str(value) for value in lead_days),
                "has_full_horizon": bool(lead_days == [0, 1, 2, 3, 4]),
                "parent_available": True,
            }
        )
    return pd.DataFrame(rows).sort_values(["model_family", "parent_model_id"]).reset_index(drop=True)


def build_ablation_run_plan(config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    families = detect_active_qh_fs1_families(resolved)
    active_family_rows = _active_qh_fs1_family_rows(resolved)
    feature_counts = {
        str(row["feature_family"]): int(row["feature_count_active_non_placeholder"])
        for row in active_family_rows.to_dict(orient="records")
    }
    total_features = int(len(get_feature_columns_by_set("QH-FS1", config=resolved)))

    parent_bundle = _load_phase2_parent_bundle(resolved)
    parents = _parent_candidates(parent_bundle)
    if parents.empty:
        return pd.DataFrame()

    run_root = phase3_output_root(resolved)
    rows: list[dict[str, Any]] = []
    for parent in parents.to_dict(orient="records"):
        for family in families:
            dropped_count = int(feature_counts.get(str(family), 0))
            child_model_id = f"{parent['parent_model_id']}__minus_{family}"
            child_output_dir = _child_output_dir_slug(
                child_model_id=child_model_id,
                model_family=str(parent["model_family"]),
                dropped_feature_family=str(family),
            )
            expected_child_path = run_root / "__latest__" / "children" / child_output_dir / "predictions_long.csv"
            rows.append(
                {
                    "parent_model_id": str(parent["parent_model_id"]),
                    "child_model_id": child_model_id,
                    "child_output_dir": child_output_dir,
                    "model_family": str(parent["model_family"]),
                    "feature_set_id": "QH-FS1",
                    "dropped_feature_family": str(family),
                    "retained_feature_count": int(total_features - dropped_count),
                    "dropped_feature_count": dropped_count,
                    "expected_output_path": str(expected_child_path),
                    "run_status": "pending_not_run",
                    "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                }
            )
    return pd.DataFrame(rows).sort_values(["model_family", "parent_model_id", "dropped_feature_family"]).reset_index(drop=True)


def _empty_with_columns(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _load_child_predictions(run_dir: Path, plan: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if plan.empty:
        return pd.DataFrame()
    for row in plan.to_dict(orient="records"):
        child_model_id = str(row["child_model_id"])
        child_output_dir = str(row.get("child_output_dir") or child_model_id)
        path = run_dir / "children" / child_output_dir / "predictions_long.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, low_memory=False)
        frame["model"] = child_model_id
        frame["ablation_parent_model_id"] = str(row["parent_model_id"])
        frame["dropped_feature_family"] = str(row["dropped_feature_family"])
        frame["source_type"] = "phase3_child_ablation"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_parent_hyperparameters(
    *,
    parent_model_id: str,
    phase07_model_configuration: pd.DataFrame,
) -> dict[str, Any]:
    model_family = "lear" if "__lear__" in str(parent_model_id) else "xgboost"
    source_model = "lear_shape" if model_family == "lear" else "xgboost_shape"
    anchor_key = _extract_anchor_key_from_parent_model_id(parent_model_id)
    rows = phase07_model_configuration[
        (phase07_model_configuration["candidate_key"].astype(str) == anchor_key)
        & (phase07_model_configuration["model"].astype(str) == source_model)
    ].copy()
    if rows.empty:
        raise RuntimeError(f"Missing parent settings row for parent '{parent_model_id}' in Phase07 model configuration.")
    payload = str(rows.iloc[0].get("key_hyperparameters", "{}") or "{}")
    return json.loads(payload)


def _train_child_predictions(
    *,
    parent_model_id: str,
    child_model_id: str,
    dropped_feature_family: str,
    modeling_table: pd.DataFrame,
    feature_family_map: pd.DataFrame,
    phase07_model_configuration: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    model_family = "lear" if "__lear__" in str(parent_model_id) else "xgboost"
    source_model = "lear_shape" if model_family == "lear" else "xgboost_shape"
    candidate_key = _extract_anchor_key_from_parent_model_id(parent_model_id)
    # Keep one canonical index basis for metadata, features, target, and split masks.
    base = modeling_table[modeling_table["candidate_key"].astype(str) == candidate_key].copy().reset_index(drop=True)
    if base.empty:
        raise RuntimeError(f"No realistic modeling rows were found for candidate_key '{candidate_key}'.")

    X_full, feature_columns, _ = _build_feature_frame(base)
    family_row = feature_family_map[
        (feature_family_map["feature_set_id"].astype(str) == "QH-FS1")
        & (feature_family_map["feature_family"].astype(str) == str(dropped_feature_family))
    ].copy()
    if family_row.empty:
        raise RuntimeError(f"Feature family '{dropped_feature_family}' is not present in active QH-FS1 family map.")
    drop_cols_raw = str(family_row.iloc[0].get("feature_columns_csv") or "")
    drop_columns = [value.strip() for value in drop_cols_raw.split(",") if value.strip()]
    retained = [column for column in feature_columns if column not in drop_columns]
    if not retained:
        raise RuntimeError(f"Child '{child_model_id}' has zero retained features after dropping family '{dropped_feature_family}'.")

    X = X_full[retained].copy()
    split = base["dataset_split"].astype(str)
    train_mask = split.eq("train")
    validation_mask = split.eq("validation")
    test_mask = split.eq("test")
    trainval_mask = train_mask | validation_mask
    if not X.index.equals(train_mask.index):
        raise AssertionError("Index mismatch: X and train_mask must align exactly before slicing.")
    if not X.index.equals(validation_mask.index):
        raise AssertionError("Index mismatch: X and validation_mask must align exactly before slicing.")
    if not X.index.equals(test_mask.index):
        raise AssertionError("Index mismatch: X and test_mask must align exactly before slicing.")
    train_table = base.loc[train_mask].reset_index(drop=True)
    validation_table = base.loc[validation_mask].reset_index(drop=True)
    test_table = base.loc[test_mask].reset_index(drop=True)
    X_train = X.loc[train_mask].reset_index(drop=True)
    X_validation = X.loc[validation_mask].reset_index(drop=True)
    X_test = X.loc[test_mask].reset_index(drop=True)
    X_trainval = X.loc[trainval_mask].reset_index(drop=True)
    y_train = train_table["delta_eur_per_mwh"].reset_index(drop=True)
    y_trainval = base.loc[trainval_mask, "delta_eur_per_mwh"].reset_index(drop=True)
    if len(validation_table) != len(X_validation) or len(test_table) != len(X_test):
        raise AssertionError("Metadata/predictor row alignment failed for validation/test splits.")

    params = _parse_parent_hyperparameters(
        parent_model_id=parent_model_id,
        phase07_model_configuration=phase07_model_configuration,
    )
    if source_model == "lear_shape":
        alpha = float(params.get("alpha", 0.01))
        model_validation = _fit_lear(X_train, y_train, alpha=alpha)
        model_test = _fit_lear(X_trainval, y_trainval, alpha=alpha)
    else:
        model_validation = _fit_xgboost(X_train, y_train, params)
        model_test = _fit_xgboost(X_trainval, y_trainval, params)

    validation_pred = _build_prediction_frame(
        validation_table,
        model_name=source_model,
        model_family=model_family,
        dataset_split="validation",
        delta_pred_raw=model_validation.predict(X_validation),
        feature_mode="minimal_realistic_anchor_features_v1_ablation",
        anchor_mode="realistic_forecast",
    )
    test_pred = _build_prediction_frame(
        test_table,
        model_name=source_model,
        model_family=model_family,
        dataset_split="test",
        delta_pred_raw=model_test.predict(X_test),
        feature_mode="minimal_realistic_anchor_features_v1_ablation",
        anchor_mode="realistic_forecast",
    )
    combined = pd.concat([validation_pred, test_pred], ignore_index=True)
    if combined.shape[0] != (validation_table.shape[0] + test_table.shape[0]):
        raise AssertionError("Prediction row count does not align with validation+test metadata rows.")
    combined["model"] = str(child_model_id)
    combined["model_family"] = str(model_family)
    combined["feature_set_id"] = "QH-FS1"
    combined["fs_level"] = "QH-FS1"
    combined["candidate_role"] = "ablation_child"
    combined["dropped_feature_family"] = str(dropped_feature_family)
    combined["ablation_parent_model_id"] = str(parent_model_id)
    combined["hourly_anchor_candidate_key"] = str(candidate_key)
    combined["source_type"] = "phase3_child_ablation"
    combined["source_model_name"] = source_model
    combined["y_true"] = pd.to_numeric(combined["price_eur_per_mwh"], errors="coerce")
    combined["y_pred"] = pd.to_numeric(combined["predicted_price_eur_per_mwh"], errors="coerce")
    if "target_timestamp_utc" not in combined.columns:
        combined["target_timestamp_utc"] = combined["timestamp_utc"]
    if "lead_day_label" not in combined.columns:
        combined["lead_day_label"] = pd.to_numeric(combined["lead_day"], errors="coerce").map(
            lambda v: "D" if pd.notna(v) and int(v) == 0 else (f"D+{int(v)}" if pd.notna(v) else None)
        )
    if "horizon_index" not in combined.columns:
        lead = pd.to_numeric(combined["lead_day"], errors="coerce")
        quarter = pd.to_numeric(combined["quarter_index"], errors="coerce")
        combined["horizon_index"] = lead * 96 + (quarter - 1)
    settings_meta = {
        "model_family": model_family,
        "source_model_name": source_model,
        "inherited_parent_model_id": str(parent_model_id),
        "inherited_hyperparameters": params,
        "retained_feature_count": int(len(retained)),
        "dropped_feature_count": int(len([column for column in drop_columns if column in feature_columns])),
    }
    return combined.reset_index(drop=True), settings_meta


def _derive_parent_child_metrics(
    parent_bundle: dict[str, Any],
    plan: pd.DataFrame,
    child_predictions: pd.DataFrame,
    *,
    denominator_table: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    if child_predictions.empty:
        return {
            "summary": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "dataset_split",
                    "reporting_level",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
            "by_model": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
            "by_reporting_level": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "dataset_split",
                    "reporting_level",
                    "reporting_lead_days",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
            "by_horizon": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "dataset_split",
                    "horizon_day",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
            "by_frozen_week": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "dataset_split",
                    "frozen_week_id",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
            "ranking": _empty_with_columns(
                [
                    "parent_model_id",
                    "child_model_id",
                    "model_family",
                    "feature_set_id",
                    "dropped_feature_family",
                    "dataset_split",
                    "reporting_level",
                    "metric_name",
                    "parent_value",
                    "child_value",
                    "delta_child_minus_parent",
                    "pct_change_vs_parent",
                ]
            ),
        }
    parent_predictions = parent_bundle["predictions"].copy()
    for frame in (parent_predictions, child_predictions):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
        frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
        frame["y_true"] = pd.to_numeric(frame["y_true"], errors="coerce")
        frame["y_pred"] = pd.to_numeric(frame["y_pred"], errors="coerce")
        frame["frozen_week_id"] = frame.get("frozen_week_id", pd.Series(index=frame.index, dtype=object))
    parent_map = {
        str(row["child_model_id"]): str(row["parent_model_id"])
        for row in plan.to_dict(orient="records")
    }
    family_map = {
        str(row["child_model_id"]): str(row["model_family"])
        for row in plan.to_dict(orient="records")
    }
    drop_map = {
        str(row["child_model_id"]): str(row["dropped_feature_family"])
        for row in plan.to_dict(orient="records")
    }
    rows_summary: list[dict[str, Any]] = []
    rows_model: list[dict[str, Any]] = []
    rows_reporting: list[dict[str, Any]] = []
    rows_horizon: list[dict[str, Any]] = []
    rows_week: list[dict[str, Any]] = []
    rows_rank: list[dict[str, Any]] = []

    den_overall = denominator_table[denominator_table["denominator_scope"].astype(str) == "overall"].copy()
    den_lead = denominator_table[denominator_table["denominator_scope"].astype(str) == "by_lead_day"].copy()
    den_reporting = denominator_table[denominator_table["denominator_scope"].astype(str) == "by_reporting_level"].copy()

    for child_model_id in sorted(child_predictions["model"].astype(str).unique().tolist()):
        parent_model_id = parent_map.get(child_model_id)
        if not parent_model_id:
            continue
        child = child_predictions[child_predictions["model"].astype(str) == child_model_id].copy()
        parent = parent_predictions[parent_predictions["model"].astype(str) == parent_model_id].copy()
        keys = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"]
        parent_n = parent[keys + ["y_true", "y_pred"]].rename(columns={"y_pred": "y_pred_parent"})
        child_n = child[keys + ["y_true", "y_pred"]].rename(columns={"y_pred": "y_pred_child"})
        paired = child_n.merge(parent_n, on=keys + ["y_true"], how="inner")
        paired = paired[paired["y_true"].notna() & paired["y_pred_child"].notna() & paired["y_pred_parent"].notna()].copy()
        if paired.empty:
            continue

        child_eval = paired[keys + ["y_true", "y_pred_child"]].rename(columns={"y_pred_child": "y_pred"})
        parent_eval = paired[keys + ["y_true", "y_pred_parent"]].rename(columns={"y_pred_parent": "y_pred"})
        child_eval["model"] = child_model_id
        parent_eval["model"] = parent_model_id
        child_eval["model_family"] = family_map[child_model_id]
        parent_eval["model_family"] = family_map[child_model_id]
        child_eval["fs_level"] = "QH-FS1"
        parent_eval["fs_level"] = "QH-FS1"
        child_eval["lead_day_label"] = child_eval["lead_day"].map(lambda v: "D" if pd.notna(v) and int(v) == 0 else f"D+{int(v)}")
        parent_eval["lead_day_label"] = parent_eval["lead_day"].map(lambda v: "D" if pd.notna(v) and int(v) == 0 else f"D+{int(v)}")

        child_metrics = summarize_standard_qh_metrics(child_eval)["metrics_by_reporting_level"].copy()
        parent_metrics = summarize_standard_qh_metrics(parent_eval)["metrics_by_reporting_level"].copy()
        if not child_metrics.empty:
            c = child_metrics.copy()
            c["dataset_split"] = c["dataset_split"].astype(str)
            c["reporting_level"] = c["reporting_level"].astype(str)
            d = den_reporting.copy()
            if not d.empty:
                d["dataset_split"] = d["dataset_split"].astype(str)
                d["reporting_level"] = d["reporting_level"].astype(str)
                d = d.rename(columns={"mae": "denom_mae"})
                c = c.merge(d[["dataset_split", "reporting_level", "denom_mae"]], on=["dataset_split", "reporting_level"], how="left")
                c["rmae"] = c["mae"] / c["denom_mae"]
            child_metrics = c
        if not parent_metrics.empty:
            p = parent_metrics.copy()
            p["dataset_split"] = p["dataset_split"].astype(str)
            p["reporting_level"] = p["reporting_level"].astype(str)
            d = den_reporting.copy()
            if not d.empty:
                d["dataset_split"] = d["dataset_split"].astype(str)
                d["reporting_level"] = d["reporting_level"].astype(str)
                d = d.rename(columns={"mae": "denom_mae"})
                p = p.merge(d[["dataset_split", "reporting_level", "denom_mae"]], on=["dataset_split", "reporting_level"], how="left")
                p["rmae"] = p["mae"] / p["denom_mae"]
            parent_metrics = p

        merged_reporting = child_metrics.merge(
            parent_metrics[["dataset_split", "reporting_level", "mae", "rmse", "bias", "rmae"]].rename(
                columns={"mae": "parent_mae", "rmse": "parent_rmse", "bias": "parent_bias", "rmae": "parent_rmae"}
            ),
            on=["dataset_split", "reporting_level"],
            how="inner",
        )
        for record in merged_reporting.to_dict(orient="records"):
            for metric in ("mae", "rmse", "bias", "rmae"):
                parent_val = float(record[f"parent_{metric}"]) if pd.notna(record.get(f"parent_{metric}")) else np.nan
                child_val = float(record[metric]) if pd.notna(record.get(metric)) else np.nan
                delta = child_val - parent_val if pd.notna(parent_val) and pd.notna(child_val) else np.nan
                pct = (delta / parent_val * 100.0) if pd.notna(delta) and pd.notna(parent_val) and parent_val != 0.0 else np.nan
                row = {
                    "parent_model_id": parent_model_id,
                    "child_model_id": child_model_id,
                    "model_family": family_map[child_model_id],
                    "feature_set_id": "QH-FS1",
                    "dropped_feature_family": drop_map[child_model_id],
                    "dataset_split": str(record["dataset_split"]),
                    "reporting_level": str(record["reporting_level"]),
                    "metric_name": metric,
                    "parent_value": parent_val,
                    "child_value": child_val,
                    "delta_child_minus_parent": delta,
                    "pct_change_vs_parent": pct,
                }
                rows_reporting.append(row)
                rows_summary.append(row)

        child_lead = summarize_standard_qh_metrics(child_eval)["metrics_by_lead_day"].copy()
        parent_lead = summarize_standard_qh_metrics(parent_eval)["metrics_by_lead_day"].copy()
        lead_join = child_lead.merge(
            parent_lead[["dataset_split", "lead_day", "mae", "rmse", "bias"]].rename(
                columns={"mae": "parent_mae", "rmse": "parent_rmse", "bias": "parent_bias"}
            ),
            on=["dataset_split", "lead_day"],
            how="inner",
        )
        for rec in lead_join.to_dict(orient="records"):
            for metric in ("mae", "rmse", "bias"):
                pval = float(rec[f"parent_{metric}"])
                cval = float(rec[metric])
                delta = cval - pval
                pct = (delta / pval * 100.0) if pval != 0.0 else np.nan
                rows_horizon.append(
                    {
                        "parent_model_id": parent_model_id,
                        "child_model_id": child_model_id,
                        "model_family": family_map[child_model_id],
                        "feature_set_id": "QH-FS1",
                        "dropped_feature_family": drop_map[child_model_id],
                        "dataset_split": str(rec["dataset_split"]),
                        "horizon_day": int(rec["lead_day"]),
                        "metric_name": metric,
                        "parent_value": pval,
                        "child_value": cval,
                        "delta_child_minus_parent": delta,
                        "pct_change_vs_parent": pct,
                    }
                )

        # ranking/opportunity deltas
        child_rank = build_qh_phase2_reporting_bundle(child_eval)["ranking_opportunity_metrics"].copy()
        parent_rank = build_qh_phase2_reporting_bundle(parent_eval)["ranking_opportunity_metrics"].copy()
        if not child_rank.empty and not parent_rank.empty:
            metric_cols = [col for col in child_rank.columns if col.startswith("mean_top")]
            join_cols = ["dataset_split", "lead_day", "lead_day_label"]
            merged_rank = child_rank.merge(parent_rank[join_cols + metric_cols], on=join_cols, how="inner", suffixes=("_child", "_parent"))
            for rec in merged_rank.to_dict(orient="records"):
                for metric in metric_cols:
                    cval = rec.get(f"{metric}_child")
                    pval = rec.get(f"{metric}_parent")
                    if pd.isna(cval) or pd.isna(pval):
                        continue
                    delta = float(cval) - float(pval)
                    pct = (delta / float(pval) * 100.0) if float(pval) != 0.0 else np.nan
                    rows_rank.append(
                        {
                            "parent_model_id": parent_model_id,
                            "child_model_id": child_model_id,
                            "model_family": family_map[child_model_id],
                            "feature_set_id": "QH-FS1",
                            "dropped_feature_family": drop_map[child_model_id],
                            "dataset_split": str(rec["dataset_split"]),
                            "reporting_level": str(rec.get("lead_day_label")),
                            "metric_name": metric,
                            "parent_value": float(pval),
                            "child_value": float(cval),
                            "delta_child_minus_parent": delta,
                            "pct_change_vs_parent": pct,
                        }
                    )

        for split_name in sorted(set(paired["dataset_split"].astype(str).tolist())):
            split_rows = paired[paired["dataset_split"].astype(str) == split_name].copy()
            split_rows["target_local"] = pd.to_datetime(split_rows["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
            split_rows["frozen_week_id"] = split_rows["target_local"].dt.isocalendar().year.astype(str) + "-W" + split_rows["target_local"].dt.isocalendar().week.astype(str).str.zfill(2)
            for week_id, week_group in split_rows.groupby("frozen_week_id", dropna=False):
                for metric in ("mae", "rmse", "bias"):
                    child_err = week_group["y_pred_child"] - week_group["y_true"]
                    parent_err = week_group["y_pred_parent"] - week_group["y_true"]
                    if metric == "mae":
                        cval = float(child_err.abs().mean())
                        pval = float(parent_err.abs().mean())
                    elif metric == "rmse":
                        cval = float(np.sqrt(np.square(child_err).mean()))
                        pval = float(np.sqrt(np.square(parent_err).mean()))
                    else:
                        cval = float(child_err.mean())
                        pval = float(parent_err.mean())
                    delta = cval - pval
                    pct = (delta / pval * 100.0) if pval != 0.0 else np.nan
                    rows_week.append(
                        {
                            "parent_model_id": parent_model_id,
                            "child_model_id": child_model_id,
                            "model_family": family_map[child_model_id],
                            "feature_set_id": "QH-FS1",
                            "dropped_feature_family": drop_map[child_model_id],
                            "dataset_split": split_name,
                            "frozen_week_id": str(week_id),
                            "metric_name": metric,
                            "parent_value": pval,
                            "child_value": cval,
                            "delta_child_minus_parent": delta,
                            "pct_change_vs_parent": pct,
                        }
                    )

        # by-model aggregate over test split stitched-all metric
        test_reporting = [row for row in rows_reporting if row["child_model_id"] == child_model_id and row["dataset_split"] == "test" and row["reporting_level"] == "stitched_all_horizon"]
        rows_model.extend(test_reporting)

    return {
        "summary": pd.DataFrame(rows_summary),
        "by_model": pd.DataFrame(rows_model),
        "by_reporting_level": pd.DataFrame(rows_reporting),
        "by_horizon": pd.DataFrame(rows_horizon),
        "by_frozen_week": pd.DataFrame(rows_week),
        "ranking": pd.DataFrame(rows_rank),
    }


def _scope_warnings(
    plan: pd.DataFrame,
    child_predictions: pd.DataFrame,
    families: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if plan.empty:
        rows.append(
            {
                "warning_code": "no_phase2_parent_models",
                "warning_message": "No QH-FS1 LEAR/XGBoost parent models were found in the latest Phase 2 bundle.",
                "model_id": None,
                "feature_family": None,
            }
        )
        return pd.DataFrame(rows)

    missing_children = 0
    for row in plan.to_dict(orient="records"):
        child_id = str(row["child_model_id"])
        if child_predictions.empty or not child_predictions["model"].astype(str).eq(child_id).any():
            missing_children += 1
            rows.append(
                {
                    "warning_code": "missing_child_prediction_artifact",
                    "warning_message": "Child ablation predictions are not available yet. Heavy ablation execution is still required.",
                    "model_id": child_id,
                    "feature_family": str(row["dropped_feature_family"]),
                }
            )
    if missing_children == 0:
        rows.append(
            {
                "warning_code": "none",
                "warning_message": "No ablation scope warnings.",
                "model_id": None,
                "feature_family": None,
            }
        )

    missing_required = sorted(set(REQUIRED_QH_FS1_FAMILIES) - set(families))
    if missing_required:
        rows.append(
            {
                "warning_code": "required_family_missing_from_registry",
                "warning_message": f"Required QH-FS1 families missing from registry: {missing_required}",
                "model_id": None,
                "feature_family": ",".join(missing_required),
            }
        )
    return pd.DataFrame(rows)


def _build_ablation_candidate_inventory(plan: pd.DataFrame, parent_candidates: pd.DataFrame) -> pd.DataFrame:
    if parent_candidates.empty:
        return _empty_with_columns(
            [
                "model_id",
                "record_type",
                "parent_model_id",
                "model_family",
                "feature_set_id",
                "dropped_feature_family",
                "availability_status",
                "notes",
            ]
        )

    rows: list[dict[str, Any]] = []
    for parent in parent_candidates.to_dict(orient="records"):
        rows.append(
            {
                "model_id": str(parent["parent_model_id"]),
                "record_type": "parent",
                "parent_model_id": str(parent["parent_model_id"]),
                "model_family": str(parent["model_family"]),
                "feature_set_id": "QH-FS1",
                "dropped_feature_family": "none",
                "child_output_dir": "",
                "availability_status": "available_from_phase2",
                "notes": "Full parent QH-FS1 candidate inherited from latest Phase 2 finalisation bundle.",
            }
        )
    for row in plan.to_dict(orient="records"):
        rows.append(
            {
                "model_id": str(row["child_model_id"]),
                "record_type": "child",
                "parent_model_id": str(row["parent_model_id"]),
                "model_family": str(row["model_family"]),
                "feature_set_id": str(row["feature_set_id"]),
                "dropped_feature_family": str(row["dropped_feature_family"]),
                "child_output_dir": str(row.get("child_output_dir") or ""),
                "availability_status": "pending_child_run",
                "notes": "Scaffolded child candidate. Predictions are expected only after heavy ablation execution.",
            }
        )
    return pd.DataFrame(rows).sort_values(["record_type", "model_family", "model_id"]).reset_index(drop=True)


def _build_ablation_model_settings_summary(plan: pd.DataFrame, phase2_settings: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if plan.empty:
        return _empty_with_columns(
            [
                "model_id",
                "parent_model_id",
                "record_type",
                "model_family",
                "feature_set_id",
                "dropped_feature_family",
                "settings_inheritance_policy",
                "settings_source",
                "settings_payload",
            ]
        )

    for parent_model_id in sorted(plan["parent_model_id"].astype(str).unique().tolist()):
        family = "lear" if "__lear__" in parent_model_id else "xgboost"
        matches = phase2_settings[
            (phase2_settings["source_type"].astype(str) == "phase07_realistic_track_a")
            & (phase2_settings["model_family"].astype(str) == family)
        ].copy()
        payload = matches["key_hyperparameters"].astype(str).iloc[0] if not matches.empty else "{}"
        rows.append(
            {
                "model_id": parent_model_id,
                "parent_model_id": parent_model_id,
                "record_type": "parent",
                "model_family": family,
                "feature_set_id": "QH-FS1",
                "dropped_feature_family": "none",
                "child_output_dir": "",
                "settings_inheritance_policy": "source_parent_phase2",
                "settings_source": "phase2_model_settings_summary",
                "settings_payload": payload,
            }
        )
    for item in plan.to_dict(orient="records"):
        rows.append(
            {
                "model_id": str(item["child_model_id"]),
                "parent_model_id": str(item["parent_model_id"]),
                "record_type": "child",
                "model_family": str(item["model_family"]),
                "feature_set_id": str(item["feature_set_id"]),
                "dropped_feature_family": str(item["dropped_feature_family"]),
                "child_output_dir": str(item.get("child_output_dir") or ""),
                "settings_inheritance_policy": "reuse_parent_stage_tuned_hyperparameters",
                "settings_source": "phase2_parent_model_id",
                "settings_payload": "inherit_parent",
            }
        )
    return pd.DataFrame(rows).sort_values(["record_type", "model_family", "model_id"]).reset_index(drop=True)


def _validate_parent_child_feature_sets(plan: pd.DataFrame, config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    total_features = int(len(get_feature_columns_by_set("QH-FS1", config=config)))
    rows: list[dict[str, Any]] = []
    for row in plan.to_dict(orient="records"):
        retained = int(row["retained_feature_count"])
        dropped = int(row["dropped_feature_count"])
        rows.append(
            {
                "child_model_id": str(row["child_model_id"]),
                "dropped_feature_family": str(row["dropped_feature_family"]),
                "status": "pass" if retained > 0 and (retained + dropped) == total_features else "fail",
                "details": f"retained={retained}, dropped={dropped}, total={total_features}",
            }
        )
    return pd.DataFrame(rows)


def _delta_table(
    parent_frame: pd.DataFrame,
    child_frame: pd.DataFrame,
    *,
    join_keys: list[str],
    metric_columns: list[str],
    parent_model_col: str = "parent_model_id",
    child_model_col: str = "child_model_id",
    model_family_col: str = "model_family",
    feature_set_col: str = "feature_set_id",
    dropped_col: str = "dropped_feature_family",
) -> pd.DataFrame:
    if parent_frame.empty or child_frame.empty:
        return pd.DataFrame(
            columns=[
                parent_model_col,
                child_model_col,
                model_family_col,
                feature_set_col,
                dropped_col,
                *join_keys,
                "metric_name",
                "parent_value",
                "child_value",
                "delta_child_minus_parent",
                "pct_change_vs_parent",
            ]
        )

    merged = child_frame.merge(
        parent_frame,
        on=[parent_model_col, model_family_col, feature_set_col, *join_keys],
        how="inner",
        suffixes=("_child", "_parent"),
    )
    rows: list[dict[str, Any]] = []
    for rec in merged.to_dict(orient="records"):
        for metric in metric_columns:
            child_value = rec.get(f"{metric}_child")
            parent_value = rec.get(f"{metric}_parent")
            if pd.isna(child_value) or pd.isna(parent_value):
                continue
            delta = float(child_value) - float(parent_value)
            pct_change = np.nan
            if float(parent_value) != 0.0:
                pct_change = float(delta / float(parent_value) * 100.0)
            out = {
                parent_model_col: rec[parent_model_col],
                child_model_col: rec[child_model_col],
                model_family_col: rec[model_family_col],
                feature_set_col: rec[feature_set_col],
                dropped_col: rec[dropped_col],
                "metric_name": metric,
                "parent_value": float(parent_value),
                "child_value": float(child_value),
                "delta_child_minus_parent": delta,
                "pct_change_vs_parent": pct_change,
            }
            for key in join_keys:
                out[key] = rec.get(key)
            rows.append(out)
    return pd.DataFrame(rows)


def build_phase3_qh_fs1_ablation_bundle(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    include_existing_child_predictions: bool = True,
    run_child_training: bool = False,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    resolved = config or QuarterHourDAExtensionConfig()
    families = detect_active_qh_fs1_families(resolved)
    phase2 = _load_phase2_parent_bundle(resolved)
    parents = _parent_candidates(phase2)
    plan = build_ablation_run_plan(resolved)
    feature_validation = _validate_parent_child_feature_sets(plan, resolved)
    denominator_bundle = _load_parent_denominator_artifacts(resolved)
    official_naive_reference = denominator_bundle["official_naive_reference"]
    denominator_table = denominator_bundle["denominator"]
    child_predictions = pd.DataFrame()
    child_logs: list[dict[str, Any]] = []
    phase07_cfg = pd.DataFrame()
    if run_child_training:
        phase07_run_id = phase2["run_summary"].get("source_runs", {}).get("phase07_run_id")
        phase07_run_dir = resolved.phase07_runs_root / str(phase07_run_id)
        if not phase07_run_dir.exists():
            raise FileNotFoundError(f"Phase07 run directory not found: {phase07_run_dir}")
        modeling_table = pd.read_csv(phase07_run_dir / "realistic_modeling_table.csv", low_memory=False)
        phase07_cfg = pd.read_csv(phase07_run_dir / "model_configuration_summary.csv", low_memory=False)
        family_map = _active_qh_fs1_family_rows(resolved)
        frames: list[pd.DataFrame] = []
        for row in plan.to_dict(orient="records"):
            child_frame, settings_meta = _train_child_predictions(
                parent_model_id=str(row["parent_model_id"]),
                child_model_id=str(row["child_model_id"]),
                dropped_feature_family=str(row["dropped_feature_family"]),
                modeling_table=modeling_table,
                feature_family_map=family_map,
                phase07_model_configuration=phase07_cfg,
            )
            frames.append(child_frame)
            child_logs.append(
                {
                    "child_model_id": str(row["child_model_id"]),
                    "parent_model_id": str(row["parent_model_id"]),
                    "dropped_feature_family": str(row["dropped_feature_family"]),
                    "rows_written": int(child_frame.shape[0]),
                    "settings": settings_meta,
                }
            )
        child_predictions = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    elif include_existing_child_predictions and run_dir is not None:
        child_predictions = _load_child_predictions(run_dir, plan)
    elif include_existing_child_predictions:
        child_predictions = _load_child_predictions(phase3_output_root(resolved), plan)

    delta_tables = _derive_parent_child_metrics(phase2, plan, child_predictions, denominator_table=denominator_table)
    inventory = _build_ablation_candidate_inventory(plan, parents)
    settings_summary = _build_ablation_model_settings_summary(plan, phase2["model_settings_summary"])
    warnings = _scope_warnings(plan, child_predictions, families)

    return {
        "phase2_parent_run_dir": phase2["run_dir"],
        "phase2_parent_run_summary": phase2["run_summary"],
        "families": families,
        "parent_candidates": parents,
        "ablation_run_plan": plan,
        "feature_validation": feature_validation,
        "child_predictions": child_predictions,
        "feature_family_value_summary": delta_tables["summary"],
        "feature_family_value_by_model": delta_tables["by_model"],
        "feature_family_value_by_reporting_level": delta_tables["by_reporting_level"],
        "feature_family_value_by_horizon": delta_tables["by_horizon"],
        "feature_family_value_by_frozen_week": delta_tables["by_frozen_week"],
        "feature_family_value_ranking_metrics": delta_tables["ranking"],
        "ablation_candidate_inventory": inventory,
        "ablation_model_settings_summary": settings_summary,
        "ablation_scope_warnings": warnings,
        "official_naive_reference": official_naive_reference,
        "official_naive_denominator_table": denominator_table,
        "child_training_logs": pd.DataFrame(child_logs),
        "phase07_model_configuration": phase07_cfg,
    }


def write_phase3_qh_fs1_ablation_bundle(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    include_existing_child_predictions: bool = True,
    run_child_training: bool = False,
) -> Phase3BundlePaths:
    resolved = config or QuarterHourDAExtensionConfig()
    paths = _bundle_paths(resolved)
    bundle = build_phase3_qh_fs1_ablation_bundle(
        resolved,
        include_existing_child_predictions=include_existing_child_predictions,
        run_child_training=run_child_training,
        run_dir=paths.run_dir,
    )

    if run_child_training and not bundle["child_predictions"].empty:
        children_root = paths.run_dir / "children"
        children_root.mkdir(parents=True, exist_ok=True)
        for row in bundle["ablation_run_plan"].to_dict(orient="records"):
            child_model_id = str(row["child_model_id"])
            child_output_dir = str(row.get("child_output_dir") or _child_output_dir_slug(
                child_model_id=child_model_id,
                model_family=str(row.get("model_family", "")),
                dropped_feature_family=str(row.get("dropped_feature_family", "")),
            ))
            child_dir = children_root / child_output_dir
            child_dir.mkdir(parents=True, exist_ok=True)
            scoped = bundle["child_predictions"][bundle["child_predictions"]["model"].astype(str) == child_model_id].copy()
            scoped.to_csv(child_dir / "predictions_long.csv", index=False)
        bundle["child_predictions"].to_csv(paths.run_dir / "child_predictions_long.csv", index=False)
    else:
        pd.DataFrame().to_csv(paths.run_dir / "child_predictions_long.csv", index=False)

    bundle["ablation_run_plan"].to_csv(paths.ablation_run_plan_csv, index=False)
    bundle["ablation_run_plan"].to_csv(paths.feature_family_parent_child_map_csv, index=False)
    bundle["feature_family_value_summary"].to_csv(paths.feature_family_value_summary_csv, index=False)
    bundle["feature_family_value_by_model"].to_csv(paths.feature_family_value_by_model_csv, index=False)
    bundle["feature_family_value_by_reporting_level"].to_csv(paths.feature_family_value_by_reporting_level_csv, index=False)
    bundle["feature_family_value_by_horizon"].to_csv(paths.feature_family_value_by_horizon_csv, index=False)
    bundle["feature_family_value_by_frozen_week"].to_csv(paths.feature_family_value_by_frozen_week_csv, index=False)
    bundle["feature_family_value_ranking_metrics"].to_csv(paths.feature_family_value_ranking_metrics_csv, index=False)
    bundle["ablation_candidate_inventory"].to_csv(paths.ablation_candidate_inventory_csv, index=False)
    bundle["ablation_model_settings_summary"].to_csv(paths.ablation_model_settings_summary_csv, index=False)
    bundle["ablation_scope_warnings"].to_csv(paths.ablation_scope_warnings_csv, index=False)
    bundle["official_naive_denominator_table"].to_csv(paths.run_dir / "official_naive_denominator_inherited.csv", index=False)
    (paths.run_dir / "official_naive_reference.json").write_text(
        json.dumps(bundle["official_naive_reference"], indent=2),
        encoding="utf-8",
    )
    bundle["child_training_logs"].to_csv(paths.run_dir / "child_training_log.csv", index=False)

    run_summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "status": "completed" if run_child_training else "scaffold_completed",
        "source_runs": {
            "phase2_finalisation_run_dir": str(bundle["phase2_parent_run_dir"]),
            "phase2_finalisation_run_id": str(bundle["phase2_parent_run_summary"].get("run_id")),
            "phase2_phase07_run_id": bundle["phase2_parent_run_summary"].get("source_runs", {}).get("phase07_run_id"),
            "phase2_observed_run_id": bundle["phase2_parent_run_summary"].get("source_runs", {}).get("observed_run_id"),
        },
        "scope": {
            "phase": "phase3",
            "feature_scope": "endogenous_only",
            "exogenous_included": False,
            "scenario_generation_included": False,
            "full_heavy_ablation_executed": bool(run_child_training),
        },
        "ablation_families": bundle["families"],
        "required_families": list(REQUIRED_QH_FS1_FAMILIES),
        "parent_model_count": int(bundle["parent_candidates"].shape[0]),
        "child_model_count": int(bundle["ablation_run_plan"].shape[0]),
        "child_prediction_rows_available": int(bundle["child_predictions"].shape[0]),
        "child_directory_mapping": (
            bundle["ablation_run_plan"][["child_model_id", "child_output_dir", "parent_model_id", "dropped_feature_family"]]
            .to_dict(orient="records")
            if not bundle["ablation_run_plan"].empty
            else []
        ),
        "official_naive_denominator_source": str(paths.run_dir / "official_naive_denominator_inherited.csv"),
        "official_naive_reference_source": str(paths.run_dir / "official_naive_reference.json"),
        "warnings": bundle["ablation_scope_warnings"].to_dict(orient="records"),
        "notes": [
            "Phase 3 heavy child ablation training was executed." if run_child_training else "Phase 3 scaffold only. No heavy child ablation training was executed in this run.",
            "Parent models are inherited from the latest validated Phase 2 full-horizon QH-FS1 bundle.",
            "Child models inherit parent settings by contract; no per-child retuning is executed in scaffold mode.",
            "Child-local naive reselection is blocked; rMAE denominator is inherited from Phase 2.7.",
        ],
    }
    paths.ablation_run_summary_json.write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return paths


def smoke_check_qh_phase3_endogenous_ablation(
    config: QuarterHourDAExtensionConfig | None = None,
) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    checks: list[dict[str, Any]] = []

    registry_families = detect_active_qh_fs1_families(resolved)
    checks.append(
        {
            "check_name": "registry_loads",
            "status": "pass" if bool(registry_families) else "fail",
            "details": f"families={registry_families}",
        }
    )
    missing_required = sorted(set(REQUIRED_QH_FS1_FAMILIES) - set(registry_families))
    checks.append(
        {
            "check_name": "required_qh_fs1_families_detected",
            "status": "pass" if not missing_required else "fail",
            "details": "all required families present" if not missing_required else f"missing={missing_required}",
        }
    )

    bundle = build_phase3_qh_fs1_ablation_bundle(resolved, include_existing_child_predictions=False)
    plan = bundle["ablation_run_plan"]
    checks.append(
        {
            "check_name": "ablation_run_plan_generated",
            "status": "pass" if not plan.empty else "fail",
            "details": f"rows={int(plan.shape[0])}",
        }
    )
    if not plan.empty and "child_output_dir" in plan.columns:
        unique_dir_count = int(plan["child_output_dir"].astype(str).nunique())
        checks.append(
            {
                "check_name": "child_output_dir_unique",
                "status": "pass" if unique_dir_count == int(plan.shape[0]) else "fail",
                "details": f"unique={unique_dir_count}, total={int(plan.shape[0])}",
            }
        )
        max_path_len = max(
            len(str(phase3_output_root(resolved) / "__latest__" / "children" / str(value) / "predictions_long.csv"))
            for value in plan["child_output_dir"].astype(str).tolist()
        )
        checks.append(
            {
                "check_name": "child_output_path_length_safe_windows",
                "status": "pass" if max_path_len < WINDOWS_SAFE_PATH_LIMIT else "fail",
                "details": f"max_path_length={max_path_len}, limit={WINDOWS_SAFE_PATH_LIMIT}",
            }
        )
        logical_ids_ok = bool(plan["child_model_id"].astype(str).str.contains("__minus_").all())
        checks.append(
            {
                "check_name": "logical_child_ids_preserved_in_plan",
                "status": "pass" if logical_ids_ok else "fail",
                "details": "child_model_id values remain full logical IDs",
            }
        )
    zero_feature_children = int(plan["retained_feature_count"].astype(int).le(0).sum()) if not plan.empty else 0
    checks.append(
        {
            "check_name": "no_zero_feature_child",
            "status": "pass" if zero_feature_children == 0 else "fail",
            "details": f"zero_feature_children={zero_feature_children}",
        }
    )

    feature_validation = bundle["feature_validation"]
    failed_feature_validation = int(feature_validation["status"].astype(str).eq("fail").sum()) if not feature_validation.empty else 0
    checks.append(
        {
            "check_name": "parent_child_feature_validation",
            "status": "pass" if failed_feature_validation == 0 else "fail",
            "details": f"failed_rows={failed_feature_validation}",
        }
    )

    # Synthetic delta check for writer correctness.
    synthetic_parent = pd.DataFrame(
        [
            {
                "parent_model_id": "parent_a",
                "model_family": "lear",
                "feature_set_id": "QH-FS1",
                "dataset_split": "validation",
                "reporting_level": "d_only",
                "mae": 10.0,
                "rmse": 20.0,
            }
        ]
    )
    synthetic_child = pd.DataFrame(
        [
            {
                "parent_model_id": "parent_a",
                "child_model_id": "parent_a__minus_calendar",
                "model_family": "lear",
                "feature_set_id": "QH-FS1",
                "dropped_feature_family": "calendar",
                "dataset_split": "validation",
                "reporting_level": "d_only",
                "mae": 12.0,
                "rmse": 21.0,
            }
        ]
    )
    synthetic_delta = _delta_table(
        synthetic_parent,
        synthetic_child,
        join_keys=["dataset_split", "reporting_level"],
        metric_columns=["mae", "rmse"],
    )
    checks.append(
        {
            "check_name": "metric_delta_writer_synthetic",
            "status": "pass" if not synthetic_delta.empty else "fail",
            "details": synthetic_delta.to_dict(orient="records")[0] if not synthetic_delta.empty else "no rows",
        }
    )
    try:
        phase2 = _load_phase2_parent_bundle(resolved)
        parents = _parent_candidates(phase2)
        lear_parent = parents[parents["model_family"].astype(str) == "lear"].head(1)
        if lear_parent.empty:
            checks.append(
                {
                    "check_name": "child_training_index_alignment_sample",
                    "status": "fail",
                    "details": "No LEAR parent candidate available for sample alignment check.",
                }
            )
        else:
            phase07_run_id = str(phase2["run_summary"].get("source_runs", {}).get("phase07_run_id"))
            phase07_dir = resolved.phase07_runs_root / phase07_run_id
            modeling = pd.read_csv(phase07_dir / "realistic_modeling_table.csv", low_memory=False)
            model_cfg = pd.read_csv(phase07_dir / "model_configuration_summary.csv", low_memory=False)
            parent_model_id = str(lear_parent.iloc[0]["parent_model_id"])
            anchor_key = _extract_anchor_key_from_parent_model_id(parent_model_id)
            scoped = modeling[modeling["candidate_key"].astype(str) == anchor_key].copy()
            sampled = pd.concat(
                [
                    scoped[scoped["dataset_split"].astype(str) == "train"].head(16),
                    scoped[scoped["dataset_split"].astype(str) == "validation"].head(8),
                    scoped[scoped["dataset_split"].astype(str) == "test"].head(8),
                ],
                ignore_index=True,
            )
            family_map = _active_qh_fs1_family_rows(resolved)
            child_preds, _ = _train_child_predictions(
                parent_model_id=parent_model_id,
                child_model_id=f"{parent_model_id}__minus_calendar__smoke",
                dropped_feature_family="calendar",
                modeling_table=sampled,
                feature_family_map=family_map,
                phase07_model_configuration=model_cfg,
            )
            required_cols = {
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "dataset_split",
            }
            checks.append(
                {
                    "check_name": "child_training_index_alignment_sample",
                    "status": "pass" if (not child_preds.empty and required_cols.issubset(set(child_preds.columns))) else "fail",
                    "details": f"rows={int(child_preds.shape[0])}, required_cols_present={required_cols.issubset(set(child_preds.columns))}",
                }
            )
    except Exception as exc:
        checks.append(
            {
                "check_name": "child_training_index_alignment_sample",
                "status": "fail",
                "details": str(exc),
            }
        )
    try:
        denom = _load_parent_denominator_artifacts(resolved)
        denom_ok = (denom["run_dir"] / "official_naive_reference.json").exists()
        checks.append(
            {
                "check_name": "inherited_denominator_path_exists",
                "status": "pass" if denom_ok else "fail",
                "details": str(denom["run_dir"] / "official_naive_reference.json"),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_name": "inherited_denominator_path_exists",
                "status": "fail",
                "details": str(exc),
            }
        )
    return pd.DataFrame(checks)
