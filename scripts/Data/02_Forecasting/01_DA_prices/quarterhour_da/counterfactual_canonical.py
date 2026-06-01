from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import discover_final_candidate_runs, load_candidate_predictions
from hourly_da.core.metrics import diebold_mariano_test
from hourly_da.core.reporting import find_latest_run
from hourly_da.core.storage import create_run_directory, write_csv, write_json

from .canonical_actual import (
    DEFAULT_CANONICAL_VERSION,
    build_thesis_grade_frozen_actual_metadata,
    load_frozen_actual_manifest,
    load_frozen_actual_path,
)
from .config import QuarterHourDAExtensionConfig
from .observed_deterministic import (
    BENCHMARK_REPEATED_HOURLY,
    MODEL_MEAN_SHAPE,
    MODEL_XGBOOST,
    XGBOOST_MIN_TRAIN_ROWS,
    _apply_zero_mean_correction_to_eval_frame,
    _build_observed_hourly_training_table,
    load_and_build_canonical_quarterhour_frame,
)
from .phase04 import _build_feature_frame, _fit_mean_shape, _fit_xgboost, _predict_mean_shape
from .phase05 import _enrich_hourly_anchor_frame, _expand_hourly_to_quarters, _load_hourly_actuals


RUN_LABEL = "canonical_v1_counterfactual_full_year_evaluation"
COUNTERFACTUAL_SPLIT = "counterfactual_test"
EXPECTED_NORMAL_QUARTERS_PER_DAY = 96
EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN = 5 * EXPECTED_NORMAL_QUARTERS_PER_DAY
CANONICAL_RECONCILIATION_TOLERANCE = 1e-8
FIXED_BACKBONE_CANDIDATE_KEYS = (
    "lear_fs3_pruned_candidate",
    "xgboost_fs3_pruned_candidate",
)


def find_latest_canonical_counterfactual_run(config: QuarterHourDAExtensionConfig | None = None) -> Path | None:
    config = config or QuarterHourDAExtensionConfig()
    try:
        return find_latest_run(config.output_root, RUN_LABEL)
    except FileNotFoundError:
        return None


def _timestamped_now_utc() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _origin_target_count_status(actual_target_count: int) -> str:
    if actual_target_count == EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN:
        return "normal_480"
    if actual_target_count < EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN:
        return "short_dst_or_boundary_window"
    return "long_dst_window"


def _load_canonical_truth(
    config: QuarterHourDAExtensionConfig,
    *,
    version_id: str,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    manifest = load_frozen_actual_manifest(config, version_id=version_id, verify_hash=True)
    for forbidden_flag in ("forecast_outputs_used", "optimisation_outputs_used", "economic_results_used_for_selection"):
        if bool(manifest.get(forbidden_flag)):
            raise ValueError(
                f"Frozen canonical manifest '{version_id}' is not valid for counterfactual forecast evaluation because "
                f"'{forbidden_flag}' is true."
            )
    metadata = build_thesis_grade_frozen_actual_metadata(config, version_id=version_id, verify_hash=False)
    frame = load_frozen_actual_path(config, version_id=version_id, verify_hash=True, thesis_grade=True).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["hour_start_utc"] = pd.to_datetime(frame["hour_start_utc"], utc=True, errors="coerce")
    frame["timestamp_local"] = pd.to_datetime(frame["timestamp_local"], utc=True, errors="coerce").dt.tz_convert(config.business_timezone)
    frame["hour_start_local"] = pd.to_datetime(frame["hour_start_local"], utc=True, errors="coerce").dt.tz_convert(config.business_timezone)
    frame["delivery_local_date"] = pd.to_datetime(frame["delivery_local_date"], errors="coerce").dt.date
    frame["counterfactual_actual_price_eur_per_mwh"] = pd.to_numeric(
        frame["counterfactual_actual_price_eur_per_mwh"],
        errors="coerce",
    )
    frame["observed_hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(
        frame["observed_hourly_anchor_price_eur_per_mwh"],
        errors="coerce",
    )
    source_summary = {
        "truth_source_type": "canonical_v1_counterfactual",
        "canonical_version_id": str(version_id),
        "canonical_variant": str(manifest.get("canonical_variant") or ""),
        "row_count": int(frame.shape[0]),
        "start_timestamp_utc": str(frame["timestamp_utc"].min()),
        "end_timestamp_utc": str(frame["timestamp_utc"].max()),
        "start_delivery_local_date": str(frame["delivery_local_date"].min()),
        "end_delivery_local_date": str(frame["delivery_local_date"].max()),
    }
    return frame.sort_values("timestamp_utc").reset_index(drop=True), manifest, {**metadata, **source_summary}


def _build_canonical_hourly_reconciliation(
    canonical_frame: pd.DataFrame,
    *,
    config: QuarterHourDAExtensionConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    canonical_hourly = (
        canonical_frame.groupby("hour_start_utc", as_index=False)
        .agg(
            canonical_hourly_mean_eur_per_mwh=("counterfactual_actual_price_eur_per_mwh", "mean"),
            embedded_hourly_anchor_eur_per_mwh=("observed_hourly_anchor_price_eur_per_mwh", "first"),
            quarter_count=("timestamp_utc", "size"),
        )
        .sort_values("hour_start_utc")
        .reset_index(drop=True)
    )
    canonical_hourly["embedded_anchor_abs_error"] = (
        canonical_hourly["canonical_hourly_mean_eur_per_mwh"] - canonical_hourly["embedded_hourly_anchor_eur_per_mwh"]
    ).abs()

    hourly_actuals = _load_hourly_actuals(config)[["hour_start_utc", "hourly_anchor_price_eur_per_mwh"]].copy()
    hourly_actuals = hourly_actuals.rename(columns={"hourly_anchor_price_eur_per_mwh": "shared_hourly_actual_eur_per_mwh"})
    merged = canonical_hourly.merge(hourly_actuals, on="hour_start_utc", how="left")
    merged["shared_hourly_actual_abs_error"] = (
        merged["canonical_hourly_mean_eur_per_mwh"] - merged["shared_hourly_actual_eur_per_mwh"]
    ).abs()
    summary = {
        "hours_checked": int(merged.shape[0]),
        "max_embedded_anchor_abs_error": float(merged["embedded_anchor_abs_error"].max()),
        "mean_embedded_anchor_abs_error": float(merged["embedded_anchor_abs_error"].mean()),
        "max_shared_hourly_actual_abs_error": float(merged["shared_hourly_actual_abs_error"].max()),
        "mean_shared_hourly_actual_abs_error": float(merged["shared_hourly_actual_abs_error"].mean()),
        "tolerance": CANONICAL_RECONCILIATION_TOLERANCE,
        "passes_tolerance": bool(
            merged["embedded_anchor_abs_error"].max() <= CANONICAL_RECONCILIATION_TOLERANCE
            and merged["shared_hourly_actual_abs_error"].max() <= CANONICAL_RECONCILIATION_TOLERANCE
        ),
    }
    if not summary["passes_tolerance"]:
        raise ValueError(
            "Canonical_v1 hourly reconciliation check failed. The aggregated quarter-hour means no longer match the hourly anchor series."
        )
    return merged, summary


def _resolve_frozen_backbone_candidates(config: QuarterHourDAExtensionConfig) -> pd.DataFrame:
    discovery = discover_final_candidate_runs(config.hourly_da_output_root)
    candidates = discovery["candidates"].copy()
    frozen = candidates[
        candidates["candidate_key"].astype(str).isin(FIXED_BACKBONE_CANDIDATE_KEYS)
        & candidates["prediction_available"].fillna(False).astype(bool)
    ].copy()
    if frozen.empty:
        raise FileNotFoundError("No frozen hourly backbone candidates were available for canonical_v1 counterfactual evaluation.")
    frozen["selection_rule"] = (
        "Fixed upstream hourly thesis candidate set by candidate_key. No quarter-hour observed-period or canonical_v1 performance selection was used."
    )
    frozen = frozen.sort_values(["candidate_key"]).reset_index(drop=True)
    missing = sorted(set(FIXED_BACKBONE_CANDIDATE_KEYS) - set(frozen["candidate_key"].astype(str)))
    if missing:
        raise FileNotFoundError(f"Missing required frozen hourly backbone candidates: {missing}")
    return frozen


def _load_hourly_backbone_predictions(
    config: QuarterHourDAExtensionConfig,
    *,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    hourly_config = HourlyDAPipelineConfig(output_root=config.hourly_da_output_root)
    predictions = load_candidate_predictions(candidate_frame=candidates, config=hourly_config)
    predictions = predictions[predictions["dataset_split"].astype(str) == "test"].copy()
    if predictions.empty:
        raise ValueError("Frozen hourly backbone candidate predictions did not contain any official hourly test rows.")
    for column in ("forecast_origin_utc", "target_timestamp_utc", "target_known_at_utc"):
        predictions[column] = pd.to_datetime(predictions[column], utc=True, errors="coerce")
    for column in ("forecast_origin_local", "target_timestamp_local"):
        predictions[column] = pd.to_datetime(predictions[column], utc=True, errors="coerce").dt.tz_convert(config.business_timezone)
    predictions["target_local_date"] = pd.to_datetime(predictions["target_local_date"], errors="coerce").dt.date
    predictions["target_local_hour"] = pd.to_numeric(predictions["target_local_hour"], errors="coerce").astype("Int64")
    predictions["source_hourly_dataset_split"] = predictions["dataset_split"].astype(str)
    predictions["dataset_split"] = COUNTERFACTUAL_SPLIT
    predictions = predictions.sort_values(["candidate_key", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    return predictions


def _build_canonical_lookup(
    canonical_frame: pd.DataFrame,
    *,
    config: QuarterHourDAExtensionConfig,
) -> pd.DataFrame:
    lookup = canonical_frame[
        [
            "timestamp_utc",
            "timestamp_local",
            "delivery_local_date",
            "hour_start_utc",
            "local_hour_of_day",
            "local_minute",
            "quarter_index",
            "counterfactual_actual_price_eur_per_mwh",
            "observed_hourly_anchor_price_eur_per_mwh",
            "actual_path_version",
            "actual_path_variant",
        ]
    ].copy()
    lookup = lookup.rename(
        columns={
            "timestamp_utc": "target_timestamp_utc",
            "timestamp_local": "target_timestamp_local",
            "delivery_local_date": "target_date_local",
            "local_hour_of_day": "hour_of_day",
            "quarter_index": "quarter_in_hour",
        }
    )
    lookup["target_timestamp_utc"] = pd.to_datetime(lookup["target_timestamp_utc"], utc=True, errors="coerce")
    lookup["target_timestamp_local"] = pd.to_datetime(lookup["target_timestamp_local"], utc=True, errors="coerce").dt.tz_convert(
        config.business_timezone
    )
    return lookup.drop_duplicates(subset=["target_timestamp_utc"]).reset_index(drop=True)


def _prepare_hourly_backbone_frame(predictions: pd.DataFrame, *, config: QuarterHourDAExtensionConfig) -> pd.DataFrame:
    hourly_frame = predictions[
        [
            "candidate_key",
            "candidate_label",
            "candidate_context",
            "variant",
            "display_group",
            "source_run_id",
            "source_run_label",
            "model",
            "model_family",
            "fs_level",
            "forecast_origin_utc",
            "forecast_origin_local",
            "dataset_split",
            "source_hourly_dataset_split",
            "lead_day",
            "lead_day_label",
            "horizon_index",
            "target_timestamp_utc",
            "target_timestamp_local",
            "target_local_date",
            "target_local_hour",
            "fit_time_sec",
            "predict_time_sec",
            "y_pred",
        ]
    ].copy()
    hourly_frame = hourly_frame.rename(
        columns={
            "target_timestamp_utc": "hour_start_utc",
            "target_timestamp_local": "hour_start_local",
            "target_local_date": "delivery_local_date",
            "target_local_hour": "local_hour_of_day",
            "y_pred": "hourly_anchor_price_eur_per_mwh",
            "model": "hourly_backbone_model",
            "model_family": "hourly_backbone_model_family",
            "fs_level": "hourly_backbone_fs_level",
        }
    )
    hourly_frame["local_hour_of_day"] = pd.to_numeric(hourly_frame["local_hour_of_day"], errors="coerce").astype(int)
    hourly_frame["hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(hourly_frame["hourly_anchor_price_eur_per_mwh"], errors="coerce")
    hourly_frame["delivery_start_local_date"] = (
        pd.to_datetime(hourly_frame["forecast_origin_local"])
        .dt.tz_localize(None)
        .dt.normalize()
        .add(pd.Timedelta(days=1))
        .dt.date
    )
    hourly_frame["hour_start_utc"] = pd.to_datetime(hourly_frame["hour_start_utc"], utc=True, errors="coerce")
    hourly_frame["hour_start_local"] = pd.to_datetime(hourly_frame["hour_start_local"], utc=True, errors="coerce").dt.tz_convert(
        config.business_timezone
    )
    return _enrich_hourly_anchor_frame(hourly_frame)


def _attach_canonical_truth(
    frame: pd.DataFrame,
    *,
    canonical_lookup: pd.DataFrame,
) -> pd.DataFrame:
    joined = frame.merge(canonical_lookup, on="target_timestamp_utc", how="left", suffixes=("", "_truth"))
    joined["counterfactual_truth_row_found"] = joined["actual_path_version"].notna()
    if (~joined["counterfactual_truth_row_found"]).any():
        missing = int((~joined["counterfactual_truth_row_found"]).sum())
        raise ValueError(f"Canonical truth join left {missing} quarter-hour rows without counterfactual truth.")

    joined["target_timestamp_local"] = pd.to_datetime(joined["target_timestamp_local"], utc=True, errors="coerce").dt.tz_convert(
        "Europe/Amsterdam"
    )
    joined["target_date_local"] = pd.to_datetime(joined["target_date_local"], errors="coerce").dt.date
    joined["hour_of_day"] = pd.to_numeric(joined["hour_of_day"], errors="coerce").astype(int)
    joined["quarter_in_hour"] = pd.to_numeric(joined["quarter_in_hour"], errors="coerce").astype(int)
    joined = joined.sort_values(["candidate_key", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    joined["lead_quarter_index"] = joined.groupby(["candidate_key", "forecast_origin_utc"], dropna=False).cumcount() + 1
    joined["quarter_of_day"] = joined.groupby(["candidate_key", "forecast_origin_utc", "target_date_local"], dropna=False).cumcount() + 1

    origin_counts = (
        joined.groupby(["candidate_key", "forecast_origin_utc"], as_index=False)
        .agg(
            actual_target_count_per_origin=("target_timestamp_utc", "size"),
            counterfactual_target_count_per_origin=("counterfactual_actual_price_eur_per_mwh", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        )
        .sort_values(["candidate_key", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    origin_counts["expected_normal_target_count_per_origin"] = EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN
    origin_counts["target_count_status"] = origin_counts["actual_target_count_per_origin"].map(_origin_target_count_status)
    origin_counts["availability_status"] = np.where(
        origin_counts["counterfactual_target_count_per_origin"].eq(origin_counts["actual_target_count_per_origin"]),
        "counterfactual_full_truth_available",
        np.where(
            origin_counts["counterfactual_target_count_per_origin"].gt(0),
            "counterfactual_partial_truth_available",
            "counterfactual_no_truth_available",
        ),
    )
    joined = joined.merge(origin_counts, on=["candidate_key", "forecast_origin_utc"], how="left")
    joined["observed_target_count_per_origin"] = 0
    joined["truth_source"] = "canonical_v1_counterfactual"
    joined["is_observed_target"] = False
    joined["is_counterfactual_target"] = True
    joined["y_true"] = pd.to_numeric(joined["counterfactual_actual_price_eur_per_mwh"], errors="coerce")
    return joined


def _build_repeated_hourly_predictions(
    hourly_predictions: pd.DataFrame,
    *,
    canonical_lookup: pd.DataFrame,
) -> pd.DataFrame:
    expanded = _expand_hourly_to_quarters(
        hourly_predictions,
        source_type="counterfactual_hourly_backbone",
        shape_method="hourly_backbone_repeat",
        scenario_variant="counterfactual_canonical_v1",
    )
    expanded = expanded.rename(
        columns={
            "timestamp_utc": "target_timestamp_utc",
            "timestamp_local": "target_timestamp_local_backbone",
            "delivery_local_date": "target_date_local_backbone",
        }
    )
    expanded = _attach_canonical_truth(expanded, canonical_lookup=canonical_lookup)
    expanded["y_pred"] = pd.to_numeric(expanded["hourly_anchor_price_eur_per_mwh"], errors="coerce")
    expanded["model"] = BENCHMARK_REPEATED_HOURLY
    expanded["model_label"] = expanded["candidate_key"].astype(str) + "__" + BENCHMARK_REPEATED_HOURLY
    expanded["model_family"] = "benchmark"
    expanded["fs_level"] = "FS0"
    expanded["prediction_available"] = expanded["y_pred"].notna()
    expanded["unavailable_reason"] = np.where(expanded["prediction_available"], "", "prediction_missing")
    expanded["source_timestamp_utc"] = expanded["hour_start_utc"]
    expanded["source_local_date"] = pd.to_datetime(expanded["hour_start_local"]).dt.date
    expanded["fallback_step"] = "repeat_hourly_backbone"
    return expanded


def _build_single_mixed_extension(
    base_frame: pd.DataFrame,
    *,
    backbone_model_name: str,
    extension_model: str,
    delta_pred_raw: np.ndarray | None,
    fit_time_sec: float,
    predict_time_sec: float,
    prediction_available: bool,
    unavailable_reason: str,
) -> pd.DataFrame:
    frame = base_frame.copy().reset_index(drop=True)
    if prediction_available and delta_pred_raw is not None:
        frame = _apply_zero_mean_correction_to_eval_frame(frame, delta_pred_raw)
    else:
        frame["y_pred"] = np.nan
        frame["delta_pred_adjusted"] = np.nan
        frame["predicted_delta_zero_mean_abs"] = np.nan
    frame["model"] = extension_model
    frame["model_label"] = frame["candidate_key"].astype(str) + "__" + extension_model
    frame["model_family"] = "mixed_frequency"
    frame["fs_level"] = "FS0" if extension_model == MODEL_MEAN_SHAPE else "FS1"
    frame["prediction_available"] = bool(prediction_available)
    frame["unavailable_reason"] = str(unavailable_reason)
    frame["fit_time_sec"] = float(fit_time_sec)
    frame["predict_time_sec"] = float(predict_time_sec)
    frame["source_timestamp_utc"] = pd.NaT
    frame["source_local_date"] = pd.NaT
    frame["fallback_step"] = "mixed_frequency_deviation"
    return frame


def _build_mixed_frequency_predictions(
    repeated_hourly: pd.DataFrame,
    *,
    training_table: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if training_table.empty:
        return pd.DataFrame(), pd.DataFrame(), {"mixed_frequency_models_enabled": False, "reason": "no_observed_training_rows"}

    feature_schema: dict[str, Any] = {"training_rows": int(training_table.shape[0]), "models": {}}
    timing_rows: list[dict[str, Any]] = []
    prediction_frames: list[pd.DataFrame] = []

    mean_fit_started = time.perf_counter()
    mean_state = _fit_mean_shape(training_table.reset_index(drop=True))
    mean_fit_time_sec = time.perf_counter() - mean_fit_started
    feature_schema["models"][MODEL_MEAN_SHAPE] = {
        "fit_mode": "full_observed_quarterhour_library",
        "grouping": ["local_hour_of_day", "quarter_index", "weekend_flag"],
        "zero_mean_correction": True,
    }

    xgb_available = int(training_table.shape[0]) >= XGBOOST_MIN_TRAIN_ROWS
    xgb_feature_columns: list[str] = []
    xgb_feature_summary_records: list[dict[str, Any]] = []
    xgb_fit_time_sec = 0.0
    learner = None
    xgb_params = {
        "n_estimators": 200,
        "max_depth": 4,
        "learning_rate": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
    }
    if xgb_available:
        xgb_fit_started = time.perf_counter()
        train_X, xgb_feature_columns, xgb_feature_summary = _build_feature_frame(training_table.reset_index(drop=True))
        train_y = pd.to_numeric(training_table["delta_eur_per_mwh"], errors="coerce")
        learner = _fit_xgboost(train_X, train_y, params=xgb_params)
        xgb_fit_time_sec = time.perf_counter() - xgb_fit_started
        xgb_feature_summary_records = xgb_feature_summary.to_dict(orient="records")
        feature_schema["models"][MODEL_XGBOOST] = {
            "fit_mode": "full_observed_quarterhour_library",
            "feature_columns": list(xgb_feature_columns),
            "feature_count": int(len(xgb_feature_columns)),
            "hyperparameters": xgb_params,
            "zero_mean_correction": True,
        }
        feature_schema["models"][f"{MODEL_XGBOOST}_feature_summary"] = xgb_feature_summary_records

    for candidate_key, group in repeated_hourly.groupby("candidate_key", dropna=False):
        base_frame = group.copy().reset_index(drop=True)
        base_frame["hourly_backbone_forecast_eur_per_mwh"] = pd.to_numeric(base_frame["hourly_anchor_price_eur_per_mwh"], errors="coerce")

        mean_predict_started = time.perf_counter()
        mean_delta_pred = _predict_mean_shape(mean_state, base_frame)
        mean_predict_time_sec = time.perf_counter() - mean_predict_started
        mean_frame = _build_single_mixed_extension(
            base_frame,
            backbone_model_name=str(candidate_key),
            extension_model=MODEL_MEAN_SHAPE,
            delta_pred_raw=mean_delta_pred,
            fit_time_sec=mean_fit_time_sec,
            predict_time_sec=mean_predict_time_sec,
            prediction_available=True,
            unavailable_reason="",
        )
        prediction_frames.append(mean_frame)
        timing_rows.append(
            {
                "candidate_key": str(candidate_key),
                "model": MODEL_MEAN_SHAPE,
                "fit_time_sec": mean_fit_time_sec,
                "predict_time_sec": mean_predict_time_sec,
                "train_rows": int(training_table.shape[0]),
                "prediction_available": True,
                "unavailable_reason": "",
            }
        )

        if xgb_available and learner is not None:
            xgb_predict_started = time.perf_counter()
            eval_X, _, _ = _build_feature_frame(base_frame)
            eval_X = eval_X.reindex(columns=xgb_feature_columns, fill_value=0.0)
            xgb_delta_pred = learner.predict(eval_X)
            xgb_predict_time_sec = time.perf_counter() - xgb_predict_started
            xgb_frame = _build_single_mixed_extension(
                base_frame,
                backbone_model_name=str(candidate_key),
                extension_model=MODEL_XGBOOST,
                delta_pred_raw=xgb_delta_pred,
                fit_time_sec=xgb_fit_time_sec,
                predict_time_sec=xgb_predict_time_sec,
                prediction_available=True,
                unavailable_reason="",
            )
            prediction_frames.append(xgb_frame)
            timing_rows.append(
                {
                    "candidate_key": str(candidate_key),
                    "model": MODEL_XGBOOST,
                    "fit_time_sec": xgb_fit_time_sec,
                    "predict_time_sec": xgb_predict_time_sec,
                    "train_rows": int(training_table.shape[0]),
                    "prediction_available": True,
                    "unavailable_reason": "",
                    "feature_count": int(len(xgb_feature_columns)),
                }
            )
        else:
            xgb_frame = _build_single_mixed_extension(
                base_frame,
                backbone_model_name=str(candidate_key),
                extension_model=MODEL_XGBOOST,
                delta_pred_raw=None,
                fit_time_sec=0.0,
                predict_time_sec=0.0,
                prediction_available=False,
                unavailable_reason=f"train_rows_below_threshold_{XGBOOST_MIN_TRAIN_ROWS}",
            )
            prediction_frames.append(xgb_frame)
            timing_rows.append(
                {
                    "candidate_key": str(candidate_key),
                    "model": MODEL_XGBOOST,
                    "fit_time_sec": 0.0,
                    "predict_time_sec": 0.0,
                    "train_rows": int(training_table.shape[0]),
                    "prediction_available": False,
                    "unavailable_reason": f"train_rows_below_threshold_{XGBOOST_MIN_TRAIN_ROWS}",
                    "feature_count": 0,
                }
            )

    predictions = pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["candidate_key", "model", "forecast_origin_utc", "target_timestamp_utc"]
    ).reset_index(drop=True)
    return predictions, pd.DataFrame(timing_rows), feature_schema


def _build_prediction_contract(predictions: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
    working = predictions.copy()
    working["run_id"] = run_id
    working["backbone_candidate_key"] = working["candidate_key"].astype(str)
    working["backbone_candidate_label"] = working["candidate_label"].astype(str)
    working["backbone_candidate_context"] = working["candidate_context"].astype(str)
    working["backbone_variant"] = working["variant"].astype(str)
    working["backbone_display_group"] = working["display_group"].astype(str)
    working["backbone_run_id"] = working["source_run_id"].astype(str)
    working["backbone_run_label"] = working["source_run_label"].astype(str)
    working["hourly_backbone_run_id"] = working["source_run_id"].astype(str)
    working["hourly_backbone_model"] = working["hourly_backbone_model"].astype(str)
    working["backbone_model_family"] = working["hourly_backbone_model_family"].astype(str)
    working["backbone_fs_level"] = working["hourly_backbone_fs_level"].astype(str)
    working["scored_target_kind"] = "counterfactual_canonical_v1"
    working["target_truth_is_observed_market"] = False
    required = [
        "run_id",
        "backbone_candidate_key",
        "backbone_candidate_label",
        "backbone_candidate_context",
        "backbone_variant",
        "backbone_display_group",
        "backbone_run_id",
        "backbone_run_label",
        "hourly_backbone_run_id",
        "hourly_backbone_model",
        "backbone_model_family",
        "backbone_fs_level",
        "model",
        "model_label",
        "model_family",
        "fs_level",
        "dataset_split",
        "source_hourly_dataset_split",
        "forecast_origin_utc",
        "forecast_origin_local",
        "delivery_start_local_date",
        "target_timestamp_utc",
        "target_timestamp_local",
        "target_date_local",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "lead_quarter_index",
        "quarter_of_day",
        "hour_of_day",
        "quarter_in_hour",
        "y_true",
        "y_pred",
        "is_observed_target",
        "is_counterfactual_target",
        "truth_source",
        "prediction_available",
        "unavailable_reason",
        "fit_time_sec",
        "predict_time_sec",
        "expected_normal_target_count_per_origin",
        "actual_target_count_per_origin",
        "observed_target_count_per_origin",
        "counterfactual_target_count_per_origin",
        "target_count_status",
        "availability_status",
        "source_timestamp_utc",
        "source_local_date",
        "fallback_step",
        "target_truth_is_observed_market",
        "scored_target_kind",
        "actual_path_version",
        "actual_path_variant",
    ]
    for column in required:
        if column not in working.columns:
            working[column] = pd.NA
    return working[required].copy()


def _counterfactual_metric_row(group: pd.DataFrame) -> dict[str, Any]:
    truth_mask = group["y_true"].notna()
    paired_mask = truth_mask & group["y_pred"].notna()
    truth = group.loc[truth_mask].copy()
    paired = group.loc[paired_mask].copy()
    errors = pd.to_numeric(paired["y_pred"], errors="coerce") - pd.to_numeric(paired["y_true"], errors="coerce")
    abs_error = errors.abs()
    total_rows = int(group.shape[0])
    truth_target_count = int(truth.shape[0])
    scored_count = int(paired.shape[0])
    return {
        "observations_total": total_rows,
        "counterfactual_target_count": truth_target_count,
        "excluded_no_truth_rows": int(total_rows - truth_target_count),
        "observations_scored": scored_count,
        "truth_target_coverage_pct": float(truth_target_count / total_rows * 100.0) if total_rows else 0.0,
        "prediction_availability_pct": float(scored_count / truth_target_count * 100.0) if truth_target_count else 0.0,
        "mae": float(abs_error.mean()) if not paired.empty else np.nan,
        "rmse": float(np.sqrt(np.mean(np.square(errors)))) if not paired.empty else np.nan,
        "bias": float(errors.mean()) if not paired.empty else np.nan,
        "median_ae": float(abs_error.median()) if not paired.empty else np.nan,
        "p90_ae": float(abs_error.quantile(0.90)) if not paired.empty else np.nan,
        "p95_ae": float(abs_error.quantile(0.95)) if not paired.empty else np.nan,
    }


SUMMARY_GROUP_COLS = [
    "backbone_candidate_key",
    "backbone_candidate_label",
    "backbone_model_family",
    "backbone_fs_level",
    "hourly_backbone_model",
    "backbone_run_id",
    "model",
    "model_label",
    "model_family",
    "fs_level",
    "dataset_split",
]


def _summarize_overall_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(SUMMARY_GROUP_COLS, dropna=False):
        row = dict(zip(SUMMARY_GROUP_COLS, keys, strict=True))
        row.update(_counterfactual_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "mae", "model_label"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_by_lead_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = SUMMARY_GROUP_COLS + ["lead_day", "lead_day_label"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_counterfactual_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "lead_day", "mae", "model_label"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_by_hour_of_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = SUMMARY_GROUP_COLS + ["hour_of_day"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_counterfactual_metric_row(group))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "hour_of_day", "mae", "model_label"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_by_quarter_of_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = SUMMARY_GROUP_COLS + ["quarter_of_day"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_counterfactual_metric_row(group))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "quarter_of_day", "mae", "model_label"]).reset_index(drop=True) if rows else pd.DataFrame()


def _build_backbone_comparison(overall_metrics: pd.DataFrame) -> pd.DataFrame:
    metric_cols = ["mae", "rmse", "bias", "prediction_availability_pct"]
    subset = overall_metrics[overall_metrics["dataset_split"].astype(str) == COUNTERFACTUAL_SPLIT].copy()
    rows: list[dict[str, Any]] = []
    for model_name, group in subset.groupby("model", dropna=False):
        pivot = group.set_index("backbone_candidate_key")
        if not set(FIXED_BACKBONE_CANDIDATE_KEYS).issubset(set(pivot.index.astype(str))):
            continue
        row = {"model": str(model_name), "dataset_split": COUNTERFACTUAL_SPLIT}
        for metric in metric_cols:
            row[f"lear_fs3_pruned_candidate__{metric}"] = float(pivot.loc["lear_fs3_pruned_candidate", metric])
            row[f"xgboost_fs3_pruned_candidate__{metric}"] = float(pivot.loc["xgboost_fs3_pruned_candidate", metric])
            row[f"xgboost_minus_lear__{metric}"] = (
                row[f"xgboost_fs3_pruned_candidate__{metric}"] - row[f"lear_fs3_pruned_candidate__{metric}"]
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("model").reset_index(drop=True) if rows else pd.DataFrame()


def _build_extension_comparison(overall_metrics: pd.DataFrame) -> pd.DataFrame:
    subset = overall_metrics[overall_metrics["dataset_split"].astype(str) == COUNTERFACTUAL_SPLIT].copy()
    rows: list[dict[str, Any]] = []
    for backbone_key, group in subset.groupby("backbone_candidate_key", dropna=False):
        pivot = group.set_index("model")
        if BENCHMARK_REPEATED_HOURLY not in set(pivot.index.astype(str)):
            continue
        repeated_mae = float(pivot.loc[BENCHMARK_REPEATED_HOURLY, "mae"])
        repeated_rmse = float(pivot.loc[BENCHMARK_REPEATED_HOURLY, "rmse"])
        repeated_availability = float(pivot.loc[BENCHMARK_REPEATED_HOURLY, "prediction_availability_pct"])
        for model_name in [MODEL_MEAN_SHAPE, MODEL_XGBOOST]:
            if model_name not in set(pivot.index.astype(str)):
                continue
            rows.append(
                {
                    "backbone_candidate_key": str(backbone_key),
                    "dataset_split": COUNTERFACTUAL_SPLIT,
                    "benchmark_model": BENCHMARK_REPEATED_HOURLY,
                    "challenger_model": str(model_name),
                    "benchmark_mae": repeated_mae,
                    "challenger_mae": float(pivot.loc[model_name, "mae"]),
                    "mae_delta_challenger_minus_benchmark": float(pivot.loc[model_name, "mae"] - repeated_mae),
                    "benchmark_rmse": repeated_rmse,
                    "challenger_rmse": float(pivot.loc[model_name, "rmse"]),
                    "rmse_delta_challenger_minus_benchmark": float(pivot.loc[model_name, "rmse"] - repeated_rmse),
                    "benchmark_prediction_availability_pct": repeated_availability,
                    "challenger_prediction_availability_pct": float(pivot.loc[model_name, "prediction_availability_pct"]),
                }
            )
    return pd.DataFrame(rows).sort_values(["backbone_candidate_key", "challenger_model"]).reset_index(drop=True) if rows else pd.DataFrame()


def _paired_dm_results(
    predictions: pd.DataFrame,
    *,
    challenger_model_label: str,
    benchmark_model_label: str,
    comparison_family: str,
    comparison_note: str,
    hac_lag: int = 24,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_cols = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]
    challenger = predictions[predictions["model_label"].astype(str) == str(challenger_model_label)][base_cols].rename(
        columns={"y_pred": "y_pred_challenger"}
    )
    benchmark = predictions[predictions["model_label"].astype(str) == str(benchmark_model_label)][base_cols].rename(
        columns={"y_pred": "y_pred_benchmark"}
    )
    merged = challenger.merge(
        benchmark,
        on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"],
        how="inner",
    )
    merged = merged[merged["y_true"].notna() & merged["y_pred_challenger"].notna() & merged["y_pred_benchmark"].notna()].copy()
    if merged.empty:
        return pd.DataFrame()

    for split_name, split_group in merged.groupby("dataset_split", dropna=False):
        overall = diebold_mariano_test(
            actual=split_group["y_true"],
            forecast_a=split_group["y_pred_challenger"],
            forecast_b=split_group["y_pred_benchmark"],
            loss="absolute",
            hac_lag=hac_lag,
        )
        overall.update(
            {
                "dataset_split": str(split_name),
                "challenger_model_label": str(challenger_model_label),
                "benchmark_model_label": str(benchmark_model_label),
                "comparison_family": str(comparison_family),
                "comparison_scope": "overall",
                "lead_day": "overall",
                "limitations_note": str(comparison_note),
            }
        )
        rows.append(overall)
        for lead_day, lead_group in split_group.groupby("lead_day", dropna=False):
            result = diebold_mariano_test(
                actual=lead_group["y_true"],
                forecast_a=lead_group["y_pred_challenger"],
                forecast_b=lead_group["y_pred_benchmark"],
                loss="absolute",
                hac_lag=hac_lag,
            )
            result.update(
                {
                    "dataset_split": str(split_name),
                    "challenger_model_label": str(challenger_model_label),
                    "benchmark_model_label": str(benchmark_model_label),
                    "comparison_family": str(comparison_family),
                    "comparison_scope": "lead_day",
                    "lead_day": int(lead_day),
                    "limitations_note": str(comparison_note),
                }
            )
            rows.append(result)
    return pd.DataFrame(rows).sort_values(["comparison_family", "comparison_scope", "lead_day"]).reset_index(drop=True) if rows else pd.DataFrame()


def _build_dm_suite(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for backbone_key in FIXED_BACKBONE_CANDIDATE_KEYS:
        repeated_label = f"{backbone_key}__{BENCHMARK_REPEATED_HOURLY}"
        mean_label = f"{backbone_key}__{MODEL_MEAN_SHAPE}"
        xgb_label = f"{backbone_key}__{MODEL_XGBOOST}"
        rows.append(
            _paired_dm_results(
                predictions,
                challenger_model_label=mean_label,
                benchmark_model_label=repeated_label,
                comparison_family="extension_vs_repeated_hourly",
                comparison_note="Paired canonical_v1 counterfactual rows only. This is a synthetic full-year benchmark, not observed-market accuracy.",
            )
        )
        rows.append(
            _paired_dm_results(
                predictions,
                challenger_model_label=xgb_label,
                benchmark_model_label=repeated_label,
                comparison_family="extension_vs_repeated_hourly",
                comparison_note="Paired canonical_v1 counterfactual rows only. This is a synthetic full-year benchmark, not observed-market accuracy.",
            )
        )

    for model_name in [BENCHMARK_REPEATED_HOURLY, MODEL_MEAN_SHAPE, MODEL_XGBOOST]:
        rows.append(
            _paired_dm_results(
                predictions,
                challenger_model_label=f"xgboost_fs3_pruned_candidate__{model_name}",
                benchmark_model_label=f"lear_fs3_pruned_candidate__{model_name}",
                comparison_family="xgboost_backbone_vs_lear_backbone",
                comparison_note="Paired canonical_v1 counterfactual rows only. This compares frozen hourly backbone candidates under the same synthetic full-year quarter-hour truth.",
            )
        )
    usable = [frame for frame in rows if frame is not None and not frame.empty]
    return pd.concat(usable, ignore_index=True) if usable else pd.DataFrame()


def _build_model_settings_summary(backbone_candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for backbone_row in backbone_candidates.to_dict(orient="records"):
        for model_name, model_family, fs_level, settings in [
            (BENCHMARK_REPEATED_HOURLY, "benchmark", "FS0", {"strategy": "repeat_hourly_backbone"}),
            (
                MODEL_MEAN_SHAPE,
                "mixed_frequency",
                "FS0",
                {"grouping": ["local_hour_of_day", "quarter_index", "weekend_flag"], "zero_mean_correction": True},
            ),
            (
                MODEL_XGBOOST,
                "mixed_frequency",
                "FS1",
                {
                    "n_estimators": 200,
                    "max_depth": 4,
                    "learning_rate": 0.05,
                    "subsample": 0.9,
                    "colsample_bytree": 0.9,
                    "reg_alpha": 0.0,
                    "reg_lambda": 1.0,
                    "zero_mean_correction": True,
                    "min_train_rows": XGBOOST_MIN_TRAIN_ROWS,
                },
            ),
        ]:
            rows.append(
                {
                    "backbone_candidate_key": str(backbone_row["candidate_key"]),
                    "backbone_candidate_label": str(backbone_row["candidate_label"]),
                    "backbone_run_id": str(backbone_row["selected_run_id"]),
                    "hourly_backbone_model": str(backbone_row["selected_model"]),
                    "backbone_model_family": str(backbone_row["model_family"]),
                    "backbone_fs_level": str(backbone_row["fs_level"]),
                    "model": str(model_name),
                    "model_family": str(model_family),
                    "fs_level": str(fs_level),
                    "settings_json": json.dumps(settings, sort_keys=True),
                }
            )
    return pd.DataFrame(rows).sort_values(["backbone_candidate_key", "model"]).reset_index(drop=True)


def _build_counterfactual_truth_coverage_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    reference = predictions[predictions["model"].astype(str) == BENCHMARK_REPEATED_HOURLY].copy()
    if reference.empty:
        return pd.DataFrame()
    summary = (
        reference.groupby(["backbone_candidate_key", "dataset_split"], as_index=False)
        .agg(
            origins=("forecast_origin_utc", "nunique"),
            target_rows=("target_timestamp_utc", "size"),
            counterfactual_target_count=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        )
        .sort_values(["dataset_split", "backbone_candidate_key"])
        .reset_index(drop=True)
    )
    summary["excluded_counterfactual_truth_rows"] = summary["target_rows"] - summary["counterfactual_target_count"]
    summary["truth_target_coverage_pct"] = summary["counterfactual_target_count"] / summary["target_rows"] * 100.0
    return summary


def run_canonical_v1_counterfactual_evaluation(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id, run_dir = create_run_directory(config.output_root, RUN_LABEL)

    canonical_frame, canonical_manifest, canonical_source_metadata = _load_canonical_truth(config, version_id=version_id)
    reconciliation_frame, reconciliation_summary = _build_canonical_hourly_reconciliation(canonical_frame, config=config)
    frozen_candidates = _resolve_frozen_backbone_candidates(config)
    hourly_predictions = _load_hourly_backbone_predictions(config, candidates=frozen_candidates)
    canonical_lookup = _build_canonical_lookup(canonical_frame, config=config)

    observed_frame, _, observed_source_summary = load_and_build_canonical_quarterhour_frame(config)
    training_table = _build_observed_hourly_training_table(observed_frame)

    hourly_backbone_frame = _prepare_hourly_backbone_frame(hourly_predictions, config=config)
    repeated_hourly = _build_repeated_hourly_predictions(hourly_backbone_frame, canonical_lookup=canonical_lookup)
    mixed_predictions, timing_summary, feature_schema = _build_mixed_frequency_predictions(
        repeated_hourly,
        training_table=training_table,
    )

    predictions = pd.concat([repeated_hourly, mixed_predictions], ignore_index=True)
    predictions = _build_prediction_contract(predictions, run_id=run_id)

    overall_metrics = _summarize_overall_metrics(predictions)
    lead_day_metrics = _summarize_by_lead_day(predictions)
    hour_of_day_metrics = _summarize_by_hour_of_day(predictions)
    quarter_of_day_metrics = _summarize_by_quarter_of_day(predictions)
    backbone_comparison = _build_backbone_comparison(overall_metrics)
    extension_comparison = _build_extension_comparison(overall_metrics)
    dm_results = _build_dm_suite(predictions)
    model_settings_summary = _build_model_settings_summary(frozen_candidates)
    counterfactual_truth_coverage_summary = _build_counterfactual_truth_coverage_summary(predictions)

    write_csv(run_dir / "hourly_backbone_candidates_frozen.csv", frozen_candidates)
    write_csv(run_dir / "hourly_backbone_predictions_test.csv", hourly_predictions)
    write_csv(run_dir / "canonical_hourly_reconciliation_check.csv", reconciliation_frame)
    write_json(run_dir / "canonical_hourly_reconciliation_summary.json", reconciliation_summary)
    write_json(run_dir / "canonical_truth_source_manifest.json", canonical_manifest)
    write_json(run_dir / "canonical_truth_source_metadata.json", canonical_source_metadata)
    write_csv(run_dir / "observed_shape_training_source_summary.csv", pd.DataFrame([observed_source_summary]))
    write_csv(run_dir / "shape_training_table_summary.csv", pd.DataFrame([{"training_rows": int(training_table.shape[0])}]))
    write_csv(run_dir / "predictions_long.csv", predictions)
    write_csv(run_dir / "metrics_overall.csv", overall_metrics)
    write_csv(run_dir / "metrics_by_lead_day.csv", lead_day_metrics)
    write_csv(run_dir / "metrics_by_hour_of_day.csv", hour_of_day_metrics)
    write_csv(run_dir / "metrics_by_quarter_of_day.csv", quarter_of_day_metrics)
    write_csv(run_dir / "backbone_comparison_metrics.csv", backbone_comparison)
    write_csv(run_dir / "extension_comparison_metrics.csv", extension_comparison)
    write_csv(run_dir / "dm_test_results.csv", dm_results)
    write_csv(run_dir / "model_settings_summary.csv", model_settings_summary)
    write_csv(run_dir / "timing_summary.csv", timing_summary)
    write_csv(run_dir / "counterfactual_truth_coverage_summary.csv", counterfactual_truth_coverage_summary)
    write_json(run_dir / "feature_schema.json", feature_schema)
    write_json(
        run_dir / "suite_models.json",
        {
            "models": [
                {
                    "backbone_candidate_key": str(row["backbone_candidate_key"]),
                    "model": str(row["model"]),
                    "model_label": f"{row['backbone_candidate_key']}__{row['model']}",
                    "model_family": str(row["model_family"]),
                    "fs_level": str(row["fs_level"]),
                }
                for row in model_settings_summary.to_dict(orient="records")
            ]
        },
    )

    run_summary = {
        "run_id": run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "evaluation_mode": "canonical_v1_counterfactual_full_year",
        "market": "DA",
        "resolution": "15min",
        "truth_source_type": "frozen_counterfactual_actual_market_path",
        "truth_source_is_observed_market": False,
        "canonical_version_id": str(version_id),
        "canonical_variant": str(canonical_manifest.get("canonical_variant") or ""),
        "counterfactual_interpretation": "Full-year counterfactual scenario-readiness benchmark, not observed-market quarter-hour accuracy.",
        "forecast_origin_policy": "Inherited from the frozen hourly D..D+4 candidate predictions.",
        "hourly_backbone_candidate_keys": list(FIXED_BACKBONE_CANDIDATE_KEYS),
        "hourly_backbone_selection_rule": "Fixed upstream hourly thesis candidates by candidate_key. No quarter-hour observed-period or canonical_v1 performance selection was used.",
        "frozen_hourly_candidates": frozen_candidates[
            ["candidate_key", "candidate_label", "selected_run_id", "selected_model", "model_family", "fs_level"]
        ].to_dict(orient="records"),
        "canonical_truth_manifest_flags": {
            "forecast_outputs_used": bool(canonical_manifest.get("forecast_outputs_used", False)),
            "optimisation_outputs_used": bool(canonical_manifest.get("optimisation_outputs_used", False)),
            "economic_results_used_for_selection": bool(canonical_manifest.get("economic_results_used_for_selection", False)),
        },
        "canonical_hourly_reconciliation_summary": reconciliation_summary,
        "shape_training_source": {
            "type": "observed_quarterhour_library",
            "authoritative_quarterhour_path": observed_source_summary["authoritative_quarterhour_path"],
            "observed_start_delivery_local_date": observed_source_summary["start_delivery_local_date"],
            "observed_end_delivery_local_date": observed_source_summary["end_delivery_local_date"],
            "training_rows": int(training_table.shape[0]),
        },
        "counterfactual_truth_coverage_summary": counterfactual_truth_coverage_summary.to_dict(orient="records"),
        "required_reporting_distinction": {
            "observed_market_15min": "empirical observed-market accuracy",
            "canonical_v1_counterfactual": "synthetic full-year scenario-readiness benchmark",
        },
        "limitations": [
            "canonical_v1 is a frozen synthetic 15-minute market environment, not realized historical 15-minute DA truth for the hourly test year.",
            "The quarter-hour shape extensions are trained on the observed post-transition Dutch 15-minute shape library and projected onto the earlier hourly test year.",
            "Counterfactual LEAR versus XGBoost backbone results should be interpreted as scenario-readiness comparisons, not as empirical observed-market quarter-hour accuracy.",
        ],
        "mFRR_in_scope": False,
        "created_at_utc": _timestamped_now_utc(),
    }
    write_json(run_dir / "run_summary.json", run_summary)
    return run_dir
