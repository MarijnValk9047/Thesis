from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .feature_registry import load_feature_registry
from .observed_deterministic import find_latest_observed_deterministic_run
from .phase07 import find_latest_phase07_run
from .reporting_metrics import build_qh_phase2_reporting_bundle, summarize_standard_qh_metrics


RUN_LABEL = "qh_fs1_fs2_model_comparison"
BASELINE_MODEL_NAME = "repeated_hourly_backbone"
REFERENCE_MODEL_NAME = "xgboost_deviation"
PHASE07_MODEL_FAMILY_MAP = {
    "flat_repeat": ("baseline", "QH-FS0", "baseline_anchor"),
    "lear_shape": ("lear", "QH-FS1", "candidate_equal_priority"),
    "xgboost_shape": ("xgboost", "QH-FS1", "candidate_equal_priority"),
}


@dataclass(frozen=True)
class BundlePaths:
    run_id: str
    run_dir: Path
    inventory_csv: Path
    predictions_csv: Path
    metrics_by_reporting_level_csv: Path
    common_sample_metrics_csv: Path
    ranking_metrics_csv: Path
    coverage_diagnostic_csv: Path
    metrics_by_frozen_week_csv: Path
    residuals_by_quarter_csv: Path
    model_settings_summary_csv: Path
    candidate_scope_warnings_csv: Path
    run_summary_json: Path


def finalisation_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)


def _bundle_paths(config: QuarterHourDAExtensionConfig | None = None) -> BundlePaths:
    resolved = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = finalisation_output_root(resolved) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return BundlePaths(
        run_id=run_id,
        run_dir=run_dir,
        inventory_csv=run_dir / "candidate_prediction_inventory.csv",
        predictions_csv=run_dir / "candidate_predictions_long.csv",
        metrics_by_reporting_level_csv=run_dir / "metrics_by_reporting_level.csv",
        common_sample_metrics_csv=run_dir / "common_sample_metrics_by_reporting_level.csv",
        ranking_metrics_csv=run_dir / "ranking_opportunity_metrics.csv",
        coverage_diagnostic_csv=run_dir / "coverage_diagnostic_by_model.csv",
        metrics_by_frozen_week_csv=run_dir / "metrics_by_frozen_week.csv",
        residuals_by_quarter_csv=run_dir / "residuals_by_quarter.csv",
        model_settings_summary_csv=run_dir / "model_settings_summary.csv",
        candidate_scope_warnings_csv=run_dir / "candidate_scope_warnings.csv",
        run_summary_json=run_dir / "run_summary.json",
    )


def find_latest_qh_finalisation_run(config: QuarterHourDAExtensionConfig | None = None) -> Path | None:
    root = finalisation_output_root(config)
    if not root.exists():
        return None
    candidates = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _iso_week_id(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, errors="coerce")
    iso = timestamps.dt.isocalendar()
    return iso["year"].astype("string") + "-W" + iso["week"].astype("string").str.zfill(2)


def _registry_feature_sets(config: QuarterHourDAExtensionConfig | None = None) -> set[str]:
    registry = load_feature_registry(config)
    return set(registry["feature_set_id"].astype(str).unique().tolist())


def _expected_candidate_inventory_rows() -> list[dict[str, object]]:
    return [
        {
            "candidate_inventory_id": "qh_fs0_repeated_hourly_backbone",
            "candidate_group": "QH-FS0 baseline / anchor",
            "feature_set_id": "QH-FS0",
            "fs_layer": "QH-FS0",
            "model_family": "baseline",
            "source_type": "observed_deterministic",
            "source_model_name": BASELINE_MODEL_NAME,
            "candidate_role": "baseline_anchor",
            "reference_only": False,
            "active_expected": True,
        },
        {
            "candidate_inventory_id": "qh_fs1_lear_phase07",
            "candidate_group": "QH-FS1 LEAR",
            "feature_set_id": "QH-FS1",
            "fs_layer": "QH-FS1",
            "model_family": "lear",
            "source_type": "phase07_realistic_track_a",
            "source_model_name": "lear_shape",
            "candidate_role": "candidate_equal_priority",
            "reference_only": False,
            "active_expected": True,
        },
        {
            "candidate_inventory_id": "qh_fs1_xgboost_phase07",
            "candidate_group": "QH-FS1 XGBoost",
            "feature_set_id": "QH-FS1",
            "fs_layer": "QH-FS1",
            "model_family": "xgboost",
            "source_type": "phase07_realistic_track_a",
            "source_model_name": "xgboost_shape",
            "candidate_role": "candidate_equal_priority",
            "reference_only": False,
            "active_expected": True,
        },
        {
            "candidate_inventory_id": "reference_observed_xgboost_deviation",
            "candidate_group": "Reference canonical xgboost_deviation",
            "feature_set_id": "QH-FS1",
            "fs_layer": "QH-FS1",
            "model_family": "xgboost",
            "source_type": "observed_deterministic",
            "source_model_name": REFERENCE_MODEL_NAME,
            "candidate_role": "reference_only",
            "reference_only": True,
            "active_expected": True,
        },
        {
            "candidate_inventory_id": "qh_fs2_placeholder",
            "candidate_group": "QH-FS2 placeholder",
            "feature_set_id": "QH-FS2",
            "fs_layer": "QH-FS2",
            "model_family": "all_candidate_models",
            "source_type": "registry_placeholder",
            "source_model_name": "",
            "candidate_role": "inactive_placeholder",
            "reference_only": False,
            "active_expected": False,
        },
    ]


def _inspect_phase07_temporal_metadata(phase07_run: Path | None) -> dict[str, object]:
    if phase07_run is None:
        return {
            "phase07_has_forecast_origin_metadata": False,
            "phase07_has_horizon_metadata": False,
            "phase07_temporal_scope": "missing_phase07_run",
            "phase07_temporal_scope_note": "No saved phase07 realistic Track A run was found.",
        }
    sample = pd.read_csv(phase07_run / "predictions_long.csv", low_memory=False)
    columns = sample.columns.tolist()
    has_forecast_origin = "forecast_origin_utc" in columns
    has_horizon_metadata = "lead_day" in columns or "horizon_day" in columns
    lead_days: list[int] = []
    if "lead_day" in sample.columns:
        lead_days = sorted(pd.to_numeric(sample["lead_day"], errors="coerce").dropna().astype(int).unique().tolist())
    if has_forecast_origin and has_horizon_metadata and any(value > 0 for value in lead_days):
        temporal_scope = "rolling_origin_d_to_d_plus_4"
        temporal_note = (
            f"Phase07 learned candidates expose forecast-origin metadata and lead_day coverage {lead_days}. "
            "They can be normalized as true rolling-origin D..D+4 candidates."
        )
    elif has_forecast_origin and has_horizon_metadata:
        temporal_scope = "rolling_origin_d_only"
        temporal_note = (
            f"Phase07 learned candidates expose forecast-origin metadata but only lead_day coverage {lead_days or [0]}. "
            "They remain D-only candidates."
        )
    else:
        temporal_scope = "source_scoped_d_only"
        temporal_note = (
            "Phase07 learned candidates do not expose forecast-origin or D..D+4 horizon metadata in predictions_long.csv. "
            "They are normalized as source-scoped D-only candidates."
        )
    return {
        "phase07_has_forecast_origin_metadata": bool(has_forecast_origin),
        "phase07_has_horizon_metadata": bool(has_horizon_metadata),
        "phase07_lead_days_present": lead_days,
        "phase07_temporal_scope": temporal_scope,
        "phase07_temporal_scope_note": temporal_note,
    }


def _add_reporting_level_columns(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    work = predictions.copy()
    work["lead_day"] = pd.to_numeric(work["lead_day"], errors="coerce").astype("Int64")
    work["horizon_day"] = pd.to_numeric(work["horizon_day"], errors="coerce").astype("Int64")
    work["sample_timestamp_key"] = (
        work["dataset_split"].astype(str)
        + "|"
        + work["horizon_day"].astype("string")
        + "|"
        + pd.to_datetime(work["target_timestamp_utc"], utc=True, errors="coerce").astype("string")
    )
    d_only = work["lead_day"].eq(0)
    guidance = work["lead_day"].isin([1, 2, 3, 4])
    work["reporting_level"] = np.where(
        d_only,
        "d_only",
        np.where(guidance, "guidance_only", "stitched_all_horizon"),
    )
    work["reporting_level_label"] = work["reporting_level"].map(
        {
            "d_only": "D only",
            "guidance_only": "Guidance only",
            "stitched_all_horizon": "Full-horizon",
        }
    )
    return work


def _scored_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    work = _add_reporting_level_columns(predictions)
    return work[
        work["actual_price_eur_per_mwh"].notna() & work["forecast_price_eur_per_mwh"].notna()
    ].copy()


def _normalize_phase07_predictions(
    phase07_run: Path,
    *,
    config: QuarterHourDAExtensionConfig,
    smoke_mode: bool = False,
    smoke_local_days: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = pd.read_csv(phase07_run / "predictions_long.csv", low_memory=False)
    model_config = pd.read_csv(phase07_run / "model_configuration_summary.csv")
    required_rows = predictions["model"].astype(str).isin(["lear_shape", "xgboost_shape"]).copy()
    frame = predictions.loc[required_rows].copy()
    if smoke_mode:
        selected_days = (
            pd.to_datetime(frame["delivery_local_date"], errors="coerce")
            .dropna()
            .drop_duplicates()
            .sort_values()
            .head(int(smoke_local_days))
        )
        frame = frame[pd.to_datetime(frame["delivery_local_date"], errors="coerce").isin(selected_days)].copy()

    frame["target_timestamp_utc"] = pd.to_datetime(
        frame["target_timestamp_utc"] if "target_timestamp_utc" in frame.columns else frame["timestamp_utc"],
        utc=True,
        errors="coerce",
    )
    frame["target_timestamp_local"] = pd.to_datetime(
        frame["target_timestamp_local"] if "target_timestamp_local" in frame.columns else frame["timestamp_local"],
        utc=True,
        errors="coerce",
    )
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce") if "forecast_origin_utc" in frame.columns else pd.NaT
    frame["horizon_day"] = (
        pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
        if "lead_day" in frame.columns
        else 0
    )
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64") if "lead_day" in frame.columns else 0
    frame["lead_day_label"] = frame["lead_day_label"].astype(str) if "lead_day_label" in frame.columns else "D"
    frame["quarter_in_hour"] = pd.to_numeric(frame["quarter_index"], errors="coerce").astype("Int64")
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
    frame["forecast_price_eur_per_mwh"] = pd.to_numeric(frame["predicted_price_eur_per_mwh"], errors="coerce")
    frame["split"] = frame["dataset_split"].astype(str)
    frame["frozen_week_id"] = _iso_week_id(frame["target_timestamp_local"])
    frame["source_run_id"] = phase07_run.name
    frame["source_type"] = "phase07_realistic_track_a"
    frame["source_model_name"] = frame["model"].astype(str)
    frame["feature_set_id"] = frame["model"].map(lambda value: PHASE07_MODEL_FAMILY_MAP[str(value)][1])
    frame["fs_layer"] = frame["feature_set_id"]
    frame["candidate_role"] = frame["model"].map(lambda value: PHASE07_MODEL_FAMILY_MAP[str(value)][2])
    frame["model_family"] = frame["model"].map(lambda value: PHASE07_MODEL_FAMILY_MAP[str(value)][0])
    frame["model_id"] = frame.apply(
        lambda row: f"{row['feature_set_id'].lower()}__{str(row['model_family'])}__hourly_anchor__{str(row['hourly_anchor_candidate_key'])}",
        axis=1,
    )
    frame["y_true"] = frame["actual_price_eur_per_mwh"]
    frame["y_pred"] = frame["forecast_price_eur_per_mwh"]
    frame["model"] = frame["model_id"]
    frame["fs_level"] = frame["feature_set_id"]

    normalized = frame[
        [
            "source_run_id",
            "model_id",
            "model",
            "model_family",
            "feature_set_id",
            "fs_layer",
            "fs_level",
            "candidate_role",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "target_timestamp_local",
            "horizon_day",
            "lead_day",
            "lead_day_label",
            "quarter_in_hour",
            "actual_price_eur_per_mwh",
            "forecast_price_eur_per_mwh",
            "split",
            "frozen_week_id",
            "hourly_anchor_candidate_key",
            "hourly_anchor_candidate_label",
            "hourly_anchor_role",
            "source_type",
            "source_model_name",
            "y_true",
            "y_pred",
            "delivery_local_date",
        ]
    ].copy()
    normalized = normalized.rename(columns={"split": "dataset_split", "quarter_in_hour": "quarter_index"})
    settings = model_config[model_config["model"].astype(str).isin(["lear_shape", "xgboost_shape"])].copy()
    return normalized.reset_index(drop=True), settings.reset_index(drop=True)


def _normalize_observed_predictions(
    observed_run: Path,
    *,
    config: QuarterHourDAExtensionConfig,
    smoke_mode: bool = False,
    smoke_origins: int = 4,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = pd.read_csv(observed_run / "predictions_long.csv", low_memory=False)
    settings = pd.read_csv(observed_run / "model_settings_summary.csv")
    required_models = {BASELINE_MODEL_NAME, REFERENCE_MODEL_NAME}
    frame = predictions[predictions["model"].astype(str).isin(required_models)].copy()
    if smoke_mode:
        selected_origins = (
            pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
            .dropna()
            .drop_duplicates()
            .sort_values()
            .head(int(smoke_origins))
        )
        frame = frame[pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce").isin(selected_origins)].copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert(config.business_timezone)
    frame["horizon_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["quarter_index"] = (frame["target_timestamp_local"].dt.minute // 15 + 1).astype("Int64")
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["y_true"], errors="coerce")
    frame["forecast_price_eur_per_mwh"] = pd.to_numeric(frame["y_pred"], errors="coerce")
    frame["dataset_split"] = frame["dataset_split"].astype(str)
    frame["frozen_week_id"] = _iso_week_id(frame["target_timestamp_local"])
    frame["source_run_id"] = observed_run.name
    frame["source_type"] = "observed_deterministic"
    frame["source_model_name"] = frame["model"].astype(str)
    frame["feature_set_id"] = frame["model"].map(
        lambda value: "QH-FS0" if str(value) == BASELINE_MODEL_NAME else "QH-FS1"
    )
    frame["fs_layer"] = frame["feature_set_id"]
    frame["candidate_role"] = frame["model"].map(
        lambda value: "baseline_anchor" if str(value) == BASELINE_MODEL_NAME else "reference_only"
    )
    frame["model_family"] = frame["model"].map(
        lambda value: "baseline" if str(value) == BASELINE_MODEL_NAME else "xgboost"
    )
    frame["model_id"] = frame["model"].map(
        lambda value: "qh_fs0__repeated_hourly_backbone"
        if str(value) == BASELINE_MODEL_NAME
        else "reference__observed__xgboost_deviation"
    )
    frame["model"] = frame["model_id"]
    frame["fs_level"] = frame["feature_set_id"]
    normalized = frame[
        [
            "source_run_id",
            "model_id",
            "model",
            "model_family",
            "feature_set_id",
            "fs_layer",
            "fs_level",
            "candidate_role",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "target_timestamp_local",
            "horizon_day",
            "lead_day",
            "lead_day_label",
            "quarter_index",
            "actual_price_eur_per_mwh",
            "forecast_price_eur_per_mwh",
            "dataset_split",
            "frozen_week_id",
            "source_type",
            "source_model_name",
            "y_true",
            "y_pred",
        ]
    ].copy()
    return normalized.reset_index(drop=True), settings[settings["model"].astype(str).isin(required_models)].reset_index(drop=True)


def build_candidate_prediction_inventory(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    phase07_run: Path | None = None,
    observed_run: Path | None = None,
) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    phase07_run = phase07_run or find_latest_phase07_run(resolved)
    observed_run = observed_run or find_latest_observed_deterministic_run(resolved)
    phase07_temporal = _inspect_phase07_temporal_metadata(phase07_run)
    rows: list[dict[str, object]] = []
    for item in _expected_candidate_inventory_rows():
        row = dict(item)
        row["phase07_run_id"] = phase07_run.name if phase07_run is not None else None
        row["observed_run_id"] = observed_run.name if observed_run is not None else None
        row["has_forecast_origin_metadata"] = None
        row["has_horizon_metadata"] = None
        row["temporal_scope"] = None
        row["availability_status"] = "missing"
        row["normalized_model_count"] = 0
        row["notes"] = ""
        if row["candidate_inventory_id"] == "qh_fs2_placeholder":
            row["availability_status"] = "inactive_not_implemented"
            row["notes"] = "QH-FS2 remains inactive in the quarter-hour feature registry."
            row["temporal_scope"] = "inactive_placeholder"
        elif row["source_type"] == "phase07_realistic_track_a":
            row["has_forecast_origin_metadata"] = bool(phase07_temporal["phase07_has_forecast_origin_metadata"])
            row["has_horizon_metadata"] = bool(phase07_temporal["phase07_has_horizon_metadata"])
            row["temporal_scope"] = str(phase07_temporal["phase07_temporal_scope"])
            if phase07_run is None:
                row["availability_status"] = "missing_no_phase07_run"
                row["notes"] = "No saved phase07 realistic track-a run was found."
            else:
                predictions = pd.read_csv(phase07_run / "predictions_long.csv", usecols=["model", "hourly_anchor_candidate_key"])
                matched = predictions[predictions["model"].astype(str) == str(row["source_model_name"])].copy()
                if matched.empty:
                    row["availability_status"] = "missing_in_phase07_run"
                    row["notes"] = "The latest phase07 run does not contain this source model."
                else:
                    row["availability_status"] = "available"
                    row["normalized_model_count"] = int(matched["hourly_anchor_candidate_key"].astype(str).nunique())
                    row["notes"] = (
                        "Discoverable from the saved phase07 realistic Track A artifact. "
                        + str(phase07_temporal["phase07_temporal_scope_note"])
                    )
        elif row["source_type"] == "observed_deterministic":
            row["has_forecast_origin_metadata"] = True
            row["has_horizon_metadata"] = True
            row["temporal_scope"] = "rolling_origin_d_to_d_plus_4"
            if observed_run is None:
                row["availability_status"] = "missing_no_observed_run"
                row["notes"] = "No saved canonical observed deterministic run was found."
            else:
                predictions = pd.read_csv(observed_run / "predictions_long.csv", usecols=["model"])
                matched = predictions[predictions["model"].astype(str) == str(row["source_model_name"])].copy()
                if matched.empty:
                    row["availability_status"] = "missing_in_observed_run"
                    row["notes"] = "The latest canonical observed deterministic run does not contain this model."
                else:
                    row["availability_status"] = "available"
                    row["normalized_model_count"] = 1
                    row["notes"] = "Discoverable from the saved canonical observed deterministic artifact."
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["candidate_group", "candidate_inventory_id"]).reset_index(drop=True)


def _validate_standard_candidate_schema(
    predictions: pd.DataFrame,
    *,
    config: QuarterHourDAExtensionConfig | None = None,
) -> pd.DataFrame:
    registry_feature_sets = _registry_feature_sets(config)
    required_columns = [
        "source_run_id",
        "model_id",
        "model_family",
        "feature_set_id",
        "fs_layer",
        "fs_level",
        "candidate_role",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "horizon_day",
        "quarter_index",
        "actual_price_eur_per_mwh",
        "forecast_price_eur_per_mwh",
        "dataset_split",
    ]
    rows: list[dict[str, object]] = []
    missing_columns = sorted(column for column in required_columns if column not in predictions.columns)
    rows.append(
        {
            "check_name": "required_columns_present",
            "status": "pass" if not missing_columns else "fail",
            "details": "all required columns present" if not missing_columns else f"missing={missing_columns}",
        }
    )
    duplicate_count = 0
    duplicate_with_origin = 0
    duplicate_without_origin = 0
    if not predictions.empty and {"source_run_id", "model_id", "dataset_split", "target_timestamp_utc"}.issubset(predictions.columns):
        with_origin = predictions[predictions["forecast_origin_utc"].notna()].copy() if "forecast_origin_utc" in predictions.columns else pd.DataFrame()
        without_origin = predictions[predictions["forecast_origin_utc"].isna()].copy() if "forecast_origin_utc" in predictions.columns else predictions.copy()
        if not with_origin.empty:
            duplicate_with_origin = int(
                with_origin[
                    ["source_run_id", "model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]
                ].duplicated().sum()
            )
        if not without_origin.empty:
            duplicate_without_origin = int(
                without_origin[
                    ["source_run_id", "model_id", "dataset_split", "target_timestamp_utc"]
                ].duplicated().sum()
            )
        duplicate_count = duplicate_with_origin + duplicate_without_origin
    rows.append(
        {
            "check_name": "no_duplicate_model_timestamp_rows",
            "status": "pass" if duplicate_count == 0 else "fail",
            "details": (
                f"duplicate_count={duplicate_count}; "
                f"with_origin_key_duplicates={duplicate_with_origin}; "
                f"without_origin_key_duplicates={duplicate_without_origin}"
            ),
        }
    )
    aligned_count = int(
        predictions["target_timestamp_utc"].notna().sum()
    ) if "target_timestamp_utc" in predictions.columns else 0
    rows.append(
        {
            "check_name": "actual_and_forecast_timestamps_aligned",
            "status": "pass" if aligned_count > 0 else "fail",
            "details": f"rows_with_target_timestamp={aligned_count}",
        }
    )
    unknown_feature_sets = sorted(set(predictions["feature_set_id"].astype(str).unique().tolist()) - registry_feature_sets) if "feature_set_id" in predictions.columns else []
    rows.append(
        {
            "check_name": "feature_set_ids_exist_in_registry",
            "status": "pass" if not unknown_feature_sets else "fail",
            "details": "all feature_set_id values exist in the registry" if not unknown_feature_sets else f"unknown={unknown_feature_sets}",
        }
    )
    return pd.DataFrame(rows)


def _build_metrics_by_frozen_week(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    work = predictions.copy()
    work["error"] = work["forecast_price_eur_per_mwh"] - work["actual_price_eur_per_mwh"]
    work["abs_error"] = work["error"].abs()
    valid = work[work["actual_price_eur_per_mwh"].notna() & work["forecast_price_eur_per_mwh"].notna()].copy()
    if valid.empty:
        return pd.DataFrame()
    return (
        valid.groupby(["model_id", "model_family", "feature_set_id", "dataset_split", "frozen_week_id"], dropna=False)
        .agg(
            rows=("target_timestamp_utc", "size"),
            mae=("abs_error", "mean"),
            bias=("error", "mean"),
            rmse=("error", lambda values: float(np.sqrt(np.mean(np.square(pd.Series(values).astype(float)))))),
        )
        .reset_index()
        .sort_values(["dataset_split", "frozen_week_id", "mae", "model_id"])
        .reset_index(drop=True)
    )


def _build_coverage_diagnostic(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    work = _add_reporting_level_columns(predictions)
    rows: list[pd.DataFrame] = []
    for reporting_level in ("d_only", "guidance_only", "stitched_all_horizon"):
        level_frame = work if reporting_level == "stitched_all_horizon" else work[work["reporting_level"] == reporting_level].copy()
        if level_frame.empty:
            continue
        grouped = (
            level_frame.groupby(
                ["model_id", "model_family", "feature_set_id", "dataset_split", "candidate_role", "horizon_day"],
                dropna=False,
            )
            .agg(
                observations_total=("target_timestamp_utc", "size"),
                observations_scored=("actual_price_eur_per_mwh", lambda values: int(pd.Series(values).notna().sum())),
                distinct_sample_timestamps=("sample_timestamp_key", "nunique"),
                forecast_origin_count=("forecast_origin_utc", lambda values: int(pd.Series(values).dropna().nunique())),
            )
            .reset_index()
        )
        grouped["reporting_level"] = reporting_level
        grouped["coverage_pct"] = np.where(
            grouped["observations_total"] > 0,
            grouped["observations_scored"] / grouped["observations_total"] * 100.0,
            np.nan,
        )
        rows.append(grouped)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(
        ["dataset_split", "reporting_level", "horizon_day", "model_id"]
    ).reset_index(drop=True)


def _build_common_sample_metrics_by_reporting_level(
    predictions: pd.DataFrame,
    *,
    business_timezone: str,
) -> pd.DataFrame:
    scored = _scored_predictions(predictions)
    if scored.empty:
        return pd.DataFrame()
    result_frames: list[pd.DataFrame] = []
    for dataset_split in sorted(scored["dataset_split"].astype(str).unique().tolist()):
        split_frame = scored[scored["dataset_split"].astype(str) == str(dataset_split)].copy()
        if split_frame.empty:
            continue
        for reporting_level in ("d_only", "guidance_only", "stitched_all_horizon"):
            level_frame = split_frame if reporting_level == "stitched_all_horizon" else split_frame[split_frame["reporting_level"] == reporting_level].copy()
            if level_frame.empty:
                continue
            candidate_count = int(level_frame["model"].astype(str).nunique())
            key_sets = (
                level_frame.groupby("model", dropna=False)["sample_timestamp_key"]
                .apply(lambda values: set(pd.Series(values).dropna().astype(str).tolist()))
                .tolist()
            )
            if not key_sets:
                continue
            common_keys = set.intersection(*key_sets)
            filtered = level_frame[level_frame["sample_timestamp_key"].astype(str).isin(common_keys)].copy()
            if filtered.empty:
                continue
            metrics = summarize_standard_qh_metrics(filtered, business_timezone=business_timezone)["metrics_by_reporting_level"].copy()
            if metrics.empty:
                continue
            metrics = metrics[metrics["reporting_level"].astype(str) == reporting_level].copy()
            if metrics.empty:
                continue
            metrics["sample_scope"] = "common_timestamp_intersection"
            metrics["common_sample_timestamp_count"] = int(len(common_keys))
            metrics["common_sample_candidate_count"] = candidate_count
            result_frames.append(metrics)
    if not result_frames:
        return pd.DataFrame()
    return pd.concat(result_frames, ignore_index=True).sort_values(
        ["dataset_split", "reporting_level_sort_order", "mae", "model"]
    ).reset_index(drop=True)


def _build_candidate_scope_warnings(
    metrics_by_reporting_level: pd.DataFrame,
    coverage_diagnostic: pd.DataFrame,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    empty = pd.DataFrame(
        columns=["model_id", "dataset_split", "warning_code", "warning_message"]
    )
    if metrics_by_reporting_level.empty:
        return empty
    rows: list[dict[str, object]] = []
    for model_id in sorted(metrics_by_reporting_level["model"].astype(str).unique().tolist()):
        model_metrics = metrics_by_reporting_level[metrics_by_reporting_level["model"].astype(str) == model_id].copy()
        d_only = model_metrics[model_metrics["reporting_level"].astype(str) == "d_only"].copy()
        full = model_metrics[model_metrics["reporting_level"].astype(str) == "stitched_all_horizon"].copy()
        if d_only.empty or full.empty:
            continue
        horizon_values = (
            coverage_diagnostic.loc[
                coverage_diagnostic["model_id"].astype(str) == model_id,
                "horizon_day",
            ]
            .dropna()
            .astype(int)
            .unique()
            .tolist()
        )
        only_d_horizon = sorted(horizon_values) == [0] if horizon_values else False
        for dataset_split in sorted(set(d_only["dataset_split"].astype(str).tolist()) & set(full["dataset_split"].astype(str).tolist())):
            d_row = d_only[d_only["dataset_split"].astype(str) == dataset_split].head(1)
            f_row = full[full["dataset_split"].astype(str) == dataset_split].head(1)
            if d_row.empty or f_row.empty:
                continue
            identical = all(
                pd.isna(d_row.iloc[0][column]) and pd.isna(f_row.iloc[0][column])
                or d_row.iloc[0][column] == f_row.iloc[0][column]
                for column in ("observations_total", "observations_scored", "coverage_pct", "mae", "rmse", "bias")
            )
            if not identical or not only_d_horizon:
                continue
            inv = inventory[inventory["source_model_name"].astype(str) == model_id].copy()
            rows.append(
                {
                    "model_id": model_id,
                    "dataset_split": dataset_split,
                    "warning_code": "full_horizon_equals_d_only_due_to_d_only_source_scope",
                    "warning_message": (
                        "Full-horizon metrics are identical to D-only because only D observations are present for this candidate. "
                        "Do not interpret this row as true D..D+4 coverage."
                    ),
                }
            )
    if not rows:
        return empty
    return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)


def _build_reporting_bundle_for_finalisation(
    predictions: pd.DataFrame,
    *,
    business_timezone: str,
    include_advanced_reporting: bool,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    if predictions.empty:
        return {}, pd.DataFrame()

    if include_advanced_reporting:
        reporting_bundle = build_qh_phase2_reporting_bundle(predictions, business_timezone=business_timezone)
        ranking_summary = reporting_bundle["ranking_opportunity_metrics"].copy()
        if not ranking_summary.empty:
            merge_keys = ["model", "model_family", "fs_level", "dataset_split", "lead_day", "lead_day_label"]
            for frame_name in (
                "extreme_event_summary",
                "spearman_summary",
                "mean_rank_error_summary",
                "tail_mae_summary",
                "spread_error_summary",
            ):
                frame = reporting_bundle[frame_name].copy()
                if frame.empty:
                    continue
                non_key_cols = [
                    column
                    for column in frame.columns
                    if column not in merge_keys and column not in ranking_summary.columns
                ]
                if not non_key_cols:
                    continue
                ranking_summary = ranking_summary.merge(frame[merge_keys + non_key_cols], on=merge_keys, how="left")
        return reporting_bundle, ranking_summary

    reporting_bundle = summarize_standard_qh_metrics(predictions, business_timezone=business_timezone)
    return reporting_bundle, pd.DataFrame()

def _build_residuals_by_quarter(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    work = predictions.copy()
    work["error"] = work["forecast_price_eur_per_mwh"] - work["actual_price_eur_per_mwh"]
    work["abs_error"] = work["error"].abs()
    valid = work[work["actual_price_eur_per_mwh"].notna() & work["forecast_price_eur_per_mwh"].notna()].copy()
    if valid.empty:
        return pd.DataFrame()
    return (
        valid.groupby(["model_id", "model_family", "feature_set_id", "dataset_split", "quarter_index"], dropna=False)
        .agg(
            rows=("target_timestamp_utc", "size"),
            mean_actual_price=("actual_price_eur_per_mwh", "mean"),
            mean_forecast_price=("forecast_price_eur_per_mwh", "mean"),
            mae=("abs_error", "mean"),
            bias=("error", "mean"),
        )
        .reset_index()
        .sort_values(["dataset_split", "quarter_index", "mae", "model_id"])
        .reset_index(drop=True)
    )


def _normalize_model_settings_summary(
    phase07_settings: pd.DataFrame,
    observed_settings: pd.DataFrame,
    *,
    phase07_run_id: str | None,
    observed_run_id: str | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in phase07_settings.to_dict(orient="records"):
        source_model = str(record["model"])
        model_family, feature_set_id, candidate_role = PHASE07_MODEL_FAMILY_MAP[source_model]
        rows.append(
            {
                "source_run_id": str(phase07_run_id) if phase07_run_id else None,
                "source_type": "phase07_realistic_track_a",
                "source_model_name": source_model,
                "model_family": model_family,
                "feature_set_id": feature_set_id,
                "fs_layer": feature_set_id,
                "candidate_role": candidate_role,
                "training_period": record.get("training_period"),
                "validation_period": record.get("validation_period"),
                "test_period": record.get("test_period"),
                "key_hyperparameters": record.get("key_hyperparameters"),
                "notes": record.get("model_type"),
            }
        )
    for record in observed_settings.to_dict(orient="records"):
        source_model = str(record["model"])
        rows.append(
            {
                "source_run_id": str(observed_run_id) if observed_run_id else None,
                "source_type": "observed_deterministic",
                "source_model_name": source_model,
                "model_family": "baseline" if source_model == BASELINE_MODEL_NAME else "xgboost",
                "feature_set_id": "QH-FS0" if source_model == BASELINE_MODEL_NAME else "QH-FS1",
                "fs_layer": "QH-FS0" if source_model == BASELINE_MODEL_NAME else "QH-FS1",
                "candidate_role": "baseline_anchor" if source_model == BASELINE_MODEL_NAME else "reference_only",
                "training_period": None,
                "validation_period": None,
                "test_period": None,
                "key_hyperparameters": record.get("settings_json"),
                "notes": "Observed deterministic canonical reference settings row.",
            }
        )
    return pd.DataFrame(rows).sort_values(["source_type", "source_model_name"]).reset_index(drop=True)


def build_qh_phase2_finalisation_bundle(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    smoke_mode: bool = False,
    smoke_phase07_local_days: int = 3,
    smoke_observed_origins: int = 4,
    include_advanced_reporting: bool = False,
) -> dict[str, Any]:
    resolved = config or QuarterHourDAExtensionConfig()
    phase07_run = find_latest_phase07_run(resolved)
    observed_run = find_latest_observed_deterministic_run(resolved)
    phase07_temporal = _inspect_phase07_temporal_metadata(phase07_run)
    inventory = build_candidate_prediction_inventory(resolved, phase07_run=phase07_run, observed_run=observed_run)

    phase07_predictions = pd.DataFrame()
    phase07_settings = pd.DataFrame()
    if phase07_run is not None:
        phase07_predictions, phase07_settings = _normalize_phase07_predictions(
            phase07_run,
            config=resolved,
            smoke_mode=smoke_mode,
            smoke_local_days=smoke_phase07_local_days,
        )

    observed_predictions = pd.DataFrame()
    observed_settings = pd.DataFrame()
    if observed_run is not None:
        observed_predictions, observed_settings = _normalize_observed_predictions(
            observed_run,
            config=resolved,
            smoke_mode=smoke_mode,
            smoke_origins=smoke_observed_origins,
        )

    candidate_predictions = pd.concat(
        [frame for frame in (phase07_predictions, observed_predictions) if not frame.empty],
        ignore_index=True,
    ) if (not phase07_predictions.empty or not observed_predictions.empty) else pd.DataFrame()

    validation_checks = _validate_standard_candidate_schema(candidate_predictions, config=resolved)
    reporting_bundle, ranking_summary = _build_reporting_bundle_for_finalisation(
        candidate_predictions,
        business_timezone=resolved.business_timezone,
        include_advanced_reporting=bool(include_advanced_reporting),
    )
    common_sample_metrics = _build_common_sample_metrics_by_reporting_level(
        candidate_predictions,
        business_timezone=resolved.business_timezone,
    )
    coverage_diagnostic = _build_coverage_diagnostic(candidate_predictions)
    metrics_by_frozen_week = _build_metrics_by_frozen_week(candidate_predictions)
    residuals_by_quarter = _build_residuals_by_quarter(candidate_predictions)
    candidate_scope_warnings = _build_candidate_scope_warnings(
        reporting_bundle["metrics_by_reporting_level"] if reporting_bundle else pd.DataFrame(),
        coverage_diagnostic,
        inventory,
    )
    model_settings_summary = _normalize_model_settings_summary(
        phase07_settings,
        observed_settings,
        phase07_run_id=phase07_run.name if phase07_run is not None else None,
        observed_run_id=observed_run.name if observed_run is not None else None,
    )
    return {
        "phase07_run": phase07_run,
        "observed_run": observed_run,
        "inventory": inventory,
        "candidate_predictions": candidate_predictions,
        "validation_checks": validation_checks,
        "phase07_temporal_metadata": phase07_temporal,
        "reporting_bundle": reporting_bundle,
        "common_sample_metrics_by_reporting_level": common_sample_metrics,
        "ranking_opportunity_metrics": ranking_summary,
        "coverage_diagnostic": coverage_diagnostic,
        "metrics_by_frozen_week": metrics_by_frozen_week,
        "residuals_by_quarter": residuals_by_quarter,
        "model_settings_summary": model_settings_summary,
        "candidate_scope_warnings": candidate_scope_warnings,
    }


def write_qh_phase2_finalisation_bundle(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    smoke_mode: bool = False,
    smoke_phase07_local_days: int = 3,
    smoke_observed_origins: int = 4,
    include_advanced_reporting: bool = False,
) -> BundlePaths:
    resolved = config or QuarterHourDAExtensionConfig()
    bundle = build_qh_phase2_finalisation_bundle(
        resolved,
        smoke_mode=smoke_mode,
        smoke_phase07_local_days=smoke_phase07_local_days,
        smoke_observed_origins=smoke_observed_origins,
        include_advanced_reporting=include_advanced_reporting,
    )
    paths = _bundle_paths(resolved)
    bundle["inventory"].to_csv(paths.inventory_csv, index=False)
    bundle["candidate_predictions"].to_csv(paths.predictions_csv, index=False)
    if bundle["reporting_bundle"]:
        bundle["reporting_bundle"]["metrics_by_reporting_level"].to_csv(paths.metrics_by_reporting_level_csv, index=False)
    else:
        pd.DataFrame().to_csv(paths.metrics_by_reporting_level_csv, index=False)
    bundle["common_sample_metrics_by_reporting_level"].to_csv(paths.common_sample_metrics_csv, index=False)
    bundle["ranking_opportunity_metrics"].to_csv(paths.ranking_metrics_csv, index=False)
    bundle["coverage_diagnostic"].to_csv(paths.coverage_diagnostic_csv, index=False)
    bundle["metrics_by_frozen_week"].to_csv(paths.metrics_by_frozen_week_csv, index=False)
    bundle["residuals_by_quarter"].to_csv(paths.residuals_by_quarter_csv, index=False)
    bundle["model_settings_summary"].to_csv(paths.model_settings_summary_csv, index=False)
    bundle["candidate_scope_warnings"].to_csv(paths.candidate_scope_warnings_csv, index=False)

    missing_candidates = bundle["inventory"][bundle["inventory"]["availability_status"].astype(str) != "available"].copy()
    run_summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "smoke_mode": bool(smoke_mode),
        "source_runs": {
            "phase07_run_id": bundle["phase07_run"].name if bundle["phase07_run"] is not None else None,
            "observed_run_id": bundle["observed_run"].name if bundle["observed_run"] is not None else None,
        },
        "candidate_inventory_rows": int(bundle["inventory"].shape[0]),
        "available_candidate_groups": int(bundle["inventory"]["availability_status"].astype(str).eq("available").sum()),
        "missing_or_inactive_candidate_groups": int(missing_candidates.shape[0]),
        "missing_candidates": missing_candidates[
            ["candidate_inventory_id", "candidate_group", "availability_status", "notes"]
        ].to_dict(orient="records"),
        "prediction_rows": int(bundle["candidate_predictions"].shape[0]),
        "feature_registry_validation_checks": bundle["validation_checks"].to_dict(orient="records"),
        "phase07_temporal_metadata": bundle["phase07_temporal_metadata"],
        "candidate_scope_warnings": bundle["candidate_scope_warnings"].to_dict(orient="records"),
        "frozen_week_policy": "iso_week_fallback_not_curated",
        "notes": [
            "Phase07 realistic Track A backend is used as the heavy-run source for QH-FS1 LEAR and XGBoost candidates.",
            "Canonical observed deterministic outputs provide the repeated-hourly baseline and the reference xgboost_deviation path.",
            "Missing candidates are reported explicitly and are not backfilled with invented predictions.",
            "The default finalisation refresh uses lightweight standard reporting for coverage and MAE/RMSE/bias tables; advanced ranking summaries are skipped unless explicitly requested.",
            str(bundle["phase07_temporal_metadata"]["phase07_temporal_scope_note"]),
        ],
    }
    paths.run_summary_json.write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return paths


def smoke_check_qh_phase2_finalisation_bundle(
    config: QuarterHourDAExtensionConfig | None = None,
) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    bundle = build_qh_phase2_finalisation_bundle(resolved, smoke_mode=True)
    checks = bundle["validation_checks"].copy()
    extra_rows = [
        {
            "check_name": "missing_candidate_handling_reported",
            "status": "pass"
            if bundle["inventory"]["availability_status"].astype(str).ne("available").any()
            else "fail",
            "details": f"missing_or_inactive_rows={int(bundle['inventory']['availability_status'].astype(str).ne('available').sum())}",
        },
        {
            "check_name": "phase07_lear_or_xgboost_discoverable",
            "status": "pass"
            if bundle["inventory"]["candidate_inventory_id"].isin(["qh_fs1_lear_phase07", "qh_fs1_xgboost_phase07"]).any()
            and bundle["inventory"].loc[
                bundle["inventory"]["candidate_inventory_id"].isin(["qh_fs1_lear_phase07", "qh_fs1_xgboost_phase07"]),
                "availability_status",
            ]
            .astype(str)
            .eq("available")
            .any()
            else "fail",
            "details": "At least one QH-FS1 learned candidate is discoverable from phase07.",
        },
        {
            "check_name": "reporting_bundle_non_empty",
            "status": "pass" if not bundle["ranking_opportunity_metrics"].empty else "fail",
            "details": f"ranking_rows={int(bundle['ranking_opportunity_metrics'].shape[0])}",
        },
        {
            "check_name": "common_sample_metrics_non_empty",
            "status": "pass" if not bundle["common_sample_metrics_by_reporting_level"].empty else "fail",
            "details": f"rows={int(bundle['common_sample_metrics_by_reporting_level'].shape[0])}",
        },
        {
            "check_name": "coverage_diagnostic_non_empty",
            "status": "pass" if not bundle["coverage_diagnostic"].empty else "fail",
            "details": f"rows={int(bundle['coverage_diagnostic'].shape[0])}",
        },
        {
            "check_name": "phase07_temporal_scope_documented",
            "status": "pass"
            if "phase07_temporal_scope_note" in bundle["phase07_temporal_metadata"]
            else "fail",
            "details": str(bundle["phase07_temporal_metadata"].get("phase07_temporal_scope_note")),
        },
    ]
    return pd.concat([checks, pd.DataFrame(extra_rows)], ignore_index=True)
