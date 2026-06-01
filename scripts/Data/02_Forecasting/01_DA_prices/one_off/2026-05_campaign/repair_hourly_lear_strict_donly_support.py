from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[6]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.lago_benchmark_data import audit_lago_data_coverage, load_lago_price_frame
from hourly_da.core.lago_benchmark_features import (
    EXOG_VALUE_COL,
    _append_hour_vector,
    _day_slice,
    _ensure_local_columns,
    _latest_known_snapshot,
    _resolve_x2_for_day,
    _vector_by_hour_allow_missing,
    _weekday_dummies,
)
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_lear_model import LagoLearModel, _subset_last_n_days, _target_timestamp_utc
from hourly_da.core.lago_splits import LagoSplitConfig, build_split_days
from hourly_da.core.scenario_generation import (
    apply_bias_correction_candidate_settings,
    build_residual_daily_profiles,
    build_residual_period_table,
    generate_scenario_bundle,
    resolve_scenario_horizon_spec,
    score_scenario_variants,
    validate_scenario_set,
)


FROZEN_RUN_DIR = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/frozen_results/"
    "d_only_lago_lear_20260507/run_outputs/20260507_161622_lago_lear_six_year_benchmark"
)
SELECTED_MODEL = "lago_lear_247_imputed_x2_1092"
MODEL_LABEL = "LEAR Strict D-only 1092 repaired anchor"
MODEL_ID = "lear_strict_donly_1092_repaired_anchor"
SCENARIO_ARTIFACT_ID = "hourly_lear_strict_donly_1092_repaired_support_tail_calibrated_v1"
SCENARIO_GENERATION_VERSION = "lear_strict_donly_support_repair_v1"
OUTPUT_ROOT = REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da/repair_runs"


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair hourly D-only LEAR Strict support and generate optimisation-ready scenarios.")
    parser.add_argument("--frozen-run-dir", type=Path, default=FROZEN_RUN_DIR)
    parser.add_argument("--resume-run-dir", type=Path, default=None)
    parser.add_argument("--support-start-local-date", type=str, default="2023-10-01")
    parser.add_argument("--support-end-local-date", type=str, default="2025-09-30")
    parser.add_argument("--n-raw", type=int, default=400)
    parser.add_argument("--n-final", type=int, default=75)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def _default_hourly_config() -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(
        input_csv=Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv"),
        raw_root=Path("data/00_Raw/DA_Prices"),
        cleaned_feature_root=Path("data/01_cleaned"),
        output_root=Path("data/02_Forecasting/01_DA_prices/hourly_da"),
    )


def _load_frozen_predictions(pred_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(pred_path, low_memory=False)
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["target_delivery_local_date"] = pd.to_datetime(frame["target_delivery_local_date"], errors="coerce").dt.date
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["y_true"] = pd.to_numeric(frame["y_true"], errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame["y_pred"], errors="coerce")
    return frame


def _load_frozen_observed_matrix(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features_dir = run_dir / "features"
    x = pd.read_parquet(features_dir / "d_only_X.parquet")
    y = pd.read_parquet(features_dir / "d_only_Y.parquet")
    metadata = pd.read_parquet(features_dir / "d_only_metadata.parquet")
    metadata["delivery_local_date"] = pd.to_datetime(metadata["delivery_local_date"], errors="coerce").dt.date
    metadata["forecast_origin_utc"] = pd.to_datetime(metadata["forecast_origin_utc"], utc=True, errors="coerce")
    metadata["forecast_origin_local"] = pd.to_datetime(metadata["forecast_origin_local"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
    return x, y, metadata


def _build_split_lookup() -> dict[date, str]:
    split_cfg = LagoSplitConfig(split_policy="thesis_official")
    config = replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=split_cfg.thesis_official_train_start_local,
        benchmark_end_exclusive_local_date=split_cfg.thesis_official_test_end_local + timedelta(days=1),
    )
    split_days = build_split_days(config=config, split_config=split_cfg)
    split_days["delivery_local_date"] = pd.to_datetime(split_days["delivery_local_date"], errors="coerce").dt.date
    return {
        local_day: str(dataset_split)
        for local_day, dataset_split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
        if pd.notna(local_day) and pd.notna(dataset_split)
    }


def _expected_hours_for_local_day(config: LagoLearBenchmarkConfig, local_day: date) -> int:
    return int(config.expected_hours_for_local_day(local_day))


def _with_price_local_cols(frame: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    work = frame.copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp_utc"]).copy()
    work["timestamp_local"] = work["timestamp_utc"].dt.tz_convert(config.local_timezone)
    work["target_delivery_local_date"] = work["timestamp_local"].dt.date
    work["target_hour_local"] = work["timestamp_local"].dt.hour.astype("Int64")
    return work.sort_values(["timestamp_utc"]).reset_index(drop=True)


def _coerce_price_day_to_24(frame: pd.DataFrame, local_day: date) -> tuple[list[float] | None, dict[str, Any]]:
    day_frame = frame[frame["target_delivery_local_date"] == local_day].copy()
    if day_frame.empty:
        return None, {
            "delivery_local_date": local_day.isoformat(),
            "raw_row_count": 0,
            "distinct_hour_count": 0,
            "null_value_count_before": 24,
            "null_value_count_after": 24,
            "expected_hours_in_local_day": None,
            "coercion_rule": "missing_day",
            "coercion_status": "missing",
        }
    day_frame = day_frame.sort_values(["target_hour_local", "timestamp_utc"]).drop_duplicates(
        subset=["target_hour_local"],
        keep="last",
    )
    template = pd.DataFrame({"target_hour_local": pd.Series(range(24), dtype="Int64")})
    merged = template.merge(
        day_frame[["target_hour_local", "price_eur_per_mwh"]],
        on="target_hour_local",
        how="left",
    )
    values = pd.to_numeric(merged["price_eur_per_mwh"], errors="coerce")
    before_nulls = int(values.isna().sum())
    if values.notna().any():
        values = values.interpolate(limit_direction="both")
    if values.isna().any():
        fallback = float(values.dropna().median()) if values.notna().any() else 0.0
        values = values.fillna(fallback)
    after_nulls = int(values.isna().sum())
    return (
        [float(value) for value in values.tolist()],
        {
            "delivery_local_date": local_day.isoformat(),
            "raw_row_count": int(day_frame.shape[0]),
            "distinct_hour_count": int(day_frame["target_hour_local"].nunique()),
            "null_value_count_before": before_nulls,
            "null_value_count_after": after_nulls,
            "expected_hours_in_local_day": int(day_frame["timestamp_local"].dt.floor("D").shape[0]),
            "coercion_rule": "deduplicate_local_hour_then_interpolate_and_median_fill",
            "coercion_status": "coerced" if before_nulls > 0 or int(day_frame["target_hour_local"].nunique()) != 24 else "native_24h",
        },
    )


def _coerce_day_frame_to_24(frame: pd.DataFrame, local_day: date, value_col: str) -> list[float] | None:
    day_frame = frame[frame["target_delivery_local_date"] == local_day].copy()
    if day_frame.empty:
        return None
    day_frame = day_frame.sort_values(["target_hour_local", "timestamp_utc"]).drop_duplicates(
        subset=["target_hour_local"],
        keep="last",
    )
    template = pd.DataFrame({"target_hour_local": pd.Series(range(24), dtype="Int64")})
    merged = template.merge(day_frame[["target_hour_local", value_col]], on="target_hour_local", how="left")
    values = pd.to_numeric(merged[value_col], errors="coerce")
    if values.notna().any():
        values = values.interpolate(limit_direction="both")
    if values.isna().all():
        return None
    if values.isna().any():
        values = values.fillna(float(values.dropna().median()))
    return [float(value) for value in values.tolist()]


def _source_inventory(predictions: pd.DataFrame, output_path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    models = sorted(predictions["model"].dropna().astype(str).unique().tolist())
    for model_name in models:
        part = predictions[predictions["model"].astype(str) == model_name].copy()
        local_day = part["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam").dt.date
        day_counts = part.groupby(local_day)["target_timestamp_utc"].nunique() if not part.empty else pd.Series(dtype=int)
        complete_origins = (
            part.groupby("forecast_origin_utc")["target_timestamp_utc"].nunique().eq(24).sum()
            if not part.empty
            else 0
        )
        rows.append(
            {
                "model": model_name,
                "model_family": part["model_family"].dropna().astype(str).mode().iloc[0] if "model_family" in part.columns and not part["model_family"].dropna().empty else "",
                "window_days": int(pd.to_numeric(part.get("window_days", pd.Series(dtype=float)), errors="coerce").dropna().mode().iloc[0]) if "window_days" in part.columns and not pd.to_numeric(part["window_days"], errors="coerce").dropna().empty else pd.NA,
                "dataset_splits": "|".join(sorted(part["dataset_split"].dropna().astype(str).unique().tolist())),
                "lead_days": "|".join(str(int(value)) for value in sorted(part["lead_day"].dropna().astype(int).unique().tolist())),
                "forecast_origin_min_utc": part["forecast_origin_utc"].min().isoformat() if not part.empty else "",
                "forecast_origin_max_utc": part["forecast_origin_utc"].max().isoformat() if not part.empty else "",
                "delivery_start_min_utc": part["target_timestamp_utc"].min().isoformat() if not part.empty else "",
                "delivery_start_max_utc": part["target_timestamp_utc"].max().isoformat() if not part.empty else "",
                "rows": int(part.shape[0]),
                "complete_donly_forecast_origins": int(complete_origins),
                "complete_delivery_days": int((day_counts == 24).sum()) if not day_counts.empty else 0,
                "actual_nonnull_rows": int(part["y_true"].notna().sum()) if "y_true" in part.columns else 0,
                "duplicate_keys": int(part.duplicated(["forecast_origin_utc", "target_timestamp_utc"]).sum()) if not part.empty else 0,
                "missing_timestamp_rows": int(part["forecast_origin_utc"].isna().sum() + part["target_timestamp_utc"].isna().sum()) if not part.empty else 0,
                "recommended_strict_variant": bool(model_name == SELECTED_MODEL),
            }
        )
    out = pd.DataFrame(rows).sort_values(["recommended_strict_variant", "model"], ascending=[False, True]).reset_index(drop=True)
    out.to_csv(output_path, index=False)
    return out


def _build_actual_long(
    *,
    price_frame: pd.DataFrame,
    support_start: date,
    support_end: date,
    split_lookup: dict[date, str],
    config: LagoLearBenchmarkConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for delivery_day in pd.date_range(support_start, support_end, freq="D").date:
        dataset_split = split_lookup.get(delivery_day)
        if dataset_split not in {"validation", "test"}:
            continue
        expected_hours = _expected_hours_for_local_day(config, delivery_day)
        vector, diag = _coerce_price_day_to_24(price_frame, delivery_day)
        diag["dataset_split"] = dataset_split
        diag["expected_hours_in_local_day"] = expected_hours
        if expected_hours != 24:
            diag["coercion_status"] = "dst_target_day_excluded"
            diagnostics.append(diag)
            continue
        if vector is None:
            diagnostics.append(diag)
            continue
        diagnostics.append(diag)
        forecast_origin_utc = config.forecast_origin_utc_for_delivery_day(delivery_day)
        for hour_zero_based, price_value in enumerate(vector):
            rows.append(
                {
                    "forecast_origin_utc": forecast_origin_utc,
                    "delivery_start_utc": _target_timestamp_utc(delivery_day, hour_zero_based, config.local_timezone),
                    "delivery_day": delivery_day.isoformat(),
                    "lead_day": 0,
                    "actual_price_eur_per_mwh": float(price_value),
                    "dataset_split": dataset_split,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(diagnostics)


def _build_inference_features(
    *,
    config: LagoLearBenchmarkConfig,
    support_start: date,
    support_end: date,
    existing_days: set[date],
    feature_columns: list[str],
    price_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bundle = audit_lago_data_coverage(config)
    x1 = _ensure_local_columns(bundle.exogenous_frames["da_total_load_forecast"], config)
    x2_candidate = _ensure_local_columns(bundle.exogenous_frames["da_res_generation_forecast_by_psr"], config)
    x2_agg = _ensure_local_columns(bundle.exogenous_frames["da_generation_forecast"], config)

    x_rows: list[dict[str, Any]] = []
    y_rows: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []

    for delivery_day in pd.date_range(support_start, support_end, freq="D").date:
        if delivery_day in existing_days:
            continue
        if config.expected_hours_for_local_day(delivery_day) != 24:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": "dst_non_24h_target_day"})
            continue
        origin_utc = config.forecast_origin_utc_for_delivery_day(delivery_day)
        try:
            x1_snapshot = _latest_known_snapshot(x1, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_snapshot = _latest_known_snapshot(x2_candidate, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_agg_snapshot = _latest_known_snapshot(x2_agg, origin_utc, allow_missing_known_at=True) if not x2_agg.empty else pd.DataFrame()
        except ValueError as exc:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": f"known_at_error::{exc}"})
            continue

        price_vectors: dict[str, list[float]] = {}
        skip_reason: str | None = None
        for lag_label, lag_day in {
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_2": delivery_day - timedelta(days=2),
            "d_minus_3": delivery_day - timedelta(days=3),
            "d_minus_7": delivery_day - timedelta(days=7),
        }.items():
            lag_vector, _ = _coerce_price_day_to_24(price_frame, lag_day)
            if lag_vector is None:
                skip_reason = f"missing_price_{lag_label}"
                break
            price_vectors[lag_label] = lag_vector
        if skip_reason is not None:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        x1_vectors: dict[str, list[float]] = {}
        for x1_label, x1_day in {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }.items():
            x1_vector = _coerce_day_frame_to_24(x1_snapshot, x1_day, EXOG_VALUE_COL)
            if x1_vector is None:
                skip_reason = f"missing_x1_{x1_label}"
                break
            x1_vectors[x1_label] = x1_vector
        if skip_reason is not None:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        x2_vectors: dict[str, list[float]] = {}
        for x2_label, x2_day in {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }.items():
            x2_vector = _coerce_day_frame_to_24(x2_snapshot, x2_day, EXOG_VALUE_COL)
            if x2_vector is None and not x2_agg_snapshot.empty:
                x2_vector = _coerce_day_frame_to_24(x2_agg_snapshot, x2_day, EXOG_VALUE_COL)
            if x2_vector is None and str(config.x2_missing_policy) == "impute_training_median":
                x2_vector = [np.nan] * 24
            if x2_vector is None:
                skip_reason = f"missing_x2_{x2_label}"
                break
            x2_vectors[x2_label] = x2_vector
        if skip_reason is not None:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        features: dict[str, float] = {}
        _append_hour_vector(features, "price_d_minus_1", price_vectors["d_minus_1"])
        _append_hour_vector(features, "price_d_minus_2", price_vectors["d_minus_2"])
        _append_hour_vector(features, "price_d_minus_3", price_vectors["d_minus_3"])
        _append_hour_vector(features, "price_d_minus_7", price_vectors["d_minus_7"])
        _append_hour_vector(features, "x1_load_fcst_d", x1_vectors["d"])
        _append_hour_vector(features, "x2_gen_fcst_d", x2_vectors["d"])
        _append_hour_vector(features, "x1_load_fcst_d_minus_1", x1_vectors["d_minus_1"])
        _append_hour_vector(features, "x1_load_fcst_d_minus_7", x1_vectors["d_minus_7"])
        _append_hour_vector(features, "x2_gen_fcst_d_minus_1", x2_vectors["d_minus_1"])
        _append_hour_vector(features, "x2_gen_fcst_d_minus_7", x2_vectors["d_minus_7"])
        features.update(_weekday_dummies(delivery_day))

        x_rows.append({column: features.get(column, pd.NA) for column in feature_columns})
        y_rows.append({f"y_h{hour:02d}": pd.NA for hour in range(1, 25)})
        meta_rows.append(
            {
                "delivery_local_date": delivery_day,
                "forecast_origin_utc": origin_utc,
                "forecast_origin_local": origin_utc.tz_convert(config.local_timezone),
            }
        )
    return pd.DataFrame(x_rows), pd.DataFrame(y_rows), pd.DataFrame(meta_rows), pd.DataFrame(skip_rows)


def _predict_missing_days(
    *,
    observed_x: pd.DataFrame,
    observed_y: pd.DataFrame,
    observed_metadata: pd.DataFrame,
    candidate_x: pd.DataFrame,
    candidate_metadata: pd.DataFrame,
    split_lookup: dict[date, str],
    config: LagoLearBenchmarkConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidate_x.empty or candidate_metadata.empty:
        return pd.DataFrame(), pd.DataFrame()
    observed_matrix = pd.concat(
        [observed_metadata.reset_index(drop=True), observed_x.reset_index(drop=True), observed_y.reset_index(drop=True)],
        axis=1,
    )
    y_cols = [f"y_h{hour:02d}" for hour in range(1, 25)]
    pred_rows: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []
    candidate_frame = pd.concat([candidate_metadata.reset_index(drop=True), candidate_x.reset_index(drop=True)], axis=1)
    candidate_frame = candidate_frame.sort_values("delivery_local_date").reset_index(drop=True)
    for row in candidate_frame.to_dict(orient="records"):
        delivery_day = row["delivery_local_date"]
        dataset_split = split_lookup.get(delivery_day)
        if dataset_split not in {"validation", "test"}:
            continue
        train = _subset_last_n_days(observed_matrix, "delivery_local_date", delivery_day, 1092)
        train_day_count = int(train["delivery_local_date"].nunique())
        if train_day_count < 365:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(), "reason": "insufficient_training_days<365"})
            continue
        x_test = pd.DataFrame([{column: row[column] for column in observed_x.columns}])
        preds_for_window: list[float] = []
        fit_failed = False
        for hour_idx, y_col in enumerate(y_cols, start=1):
            y_train = pd.to_numeric(train[y_col], errors="coerce")
            valid = y_train.notna()
            x_train = train.loc[valid, observed_x.columns]
            y_train = y_train.loc[valid]
            if x_train.shape[0] < 365:
                skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(), "reason": f"insufficient_rows_hour_{hour_idx:02d}"})
                fit_failed = True
                break
            model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
            model.fit(x_train, y_train)
            if model.pipeline is None:
                skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(), "reason": model.fit_warning or f"model_fit_failed_hour_{hour_idx:02d}"})
                fit_failed = True
                break
            preds_for_window.append(float(model.predict(x_test)[0]))
        if fit_failed or len(preds_for_window) != 24:
            continue
        origin_utc = pd.Timestamp(row["forecast_origin_utc"])
        if origin_utc.tzinfo is None:
            origin_utc = origin_utc.tz_localize("UTC")
        else:
            origin_utc = origin_utc.tz_convert("UTC")
        for hour_zero_based in range(24):
            pred_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "delivery_start_utc": _target_timestamp_utc(delivery_day, hour_zero_based, config.local_timezone),
                    "lead_day": 0,
                    "point_forecast_eur_per_mwh": float(preds_for_window[hour_zero_based]),
                    "model": SELECTED_MODEL,
                    "model_family": "LEAR",
                    "dataset_split": dataset_split,
                    "delivery_day": delivery_day.isoformat(),
                }
            )
    return pd.DataFrame(pred_rows), pd.DataFrame(skip_rows)


def _build_anchor_support_audit(
    anchor: pd.DataFrame,
    *,
    start_day: date,
    end_day: date,
    label: str,
    config: LagoLearBenchmarkConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = anchor.copy()
    work["delivery_day"] = pd.to_datetime(work["delivery_day"], errors="coerce").dt.date
    work["forecast_origin_utc"] = pd.to_datetime(work["forecast_origin_utc"], utc=True, errors="coerce")
    work["delivery_start_utc"] = pd.to_datetime(work["delivery_start_utc"], utc=True, errors="coerce")
    dup_count = int(work.duplicated(["forecast_origin_utc", "delivery_start_utc"]).sum())
    rows: list[dict[str, Any]] = []
    missing_days: list[dict[str, Any]] = []
    missing_hours: list[dict[str, Any]] = []
    for delivery_day in pd.date_range(start_day, end_day, freq="D").date:
        expected_hours = _expected_hours_for_local_day(config, delivery_day)
        subset = work[work["delivery_day"] == delivery_day].copy()
        row = {
            "audit_label": label,
            "delivery_day": delivery_day.isoformat(),
            "expected_hours_in_local_day": expected_hours,
            "row_count": int(subset.shape[0]),
            "forecast_origin_count": int(subset["forecast_origin_utc"].nunique()) if not subset.empty else 0,
            "delivery_hour_count": int(subset["delivery_start_utc"].nunique()) if not subset.empty else 0,
            "actual_missing_rows": int(subset["actual_price_eur_per_mwh"].isna().sum()) if not subset.empty else 0,
            "is_dst_non_24h_day": bool(expected_hours != 24),
            "is_complete_24h_policy": bool(expected_hours == 24 and subset["delivery_start_utc"].nunique() == 24 and subset["actual_price_eur_per_mwh"].notna().all()),
        }
        rows.append(row)
        if expected_hours == 24 and not row["is_complete_24h_policy"]:
            missing_days.append({"audit_label": label, "delivery_day": delivery_day.isoformat(), "reason": "missing_or_incomplete_24h_support"})
            present = set(subset["delivery_start_utc"].dt.tz_convert(config.local_timezone).dt.hour.astype(int).tolist()) if not subset.empty else set()
            for hour in range(24):
                if hour not in present:
                    missing_hours.append({"audit_label": label, "delivery_day": delivery_day.isoformat(), "local_hour": hour, "reason": "missing_delivery_hour"})
    daily = pd.DataFrame(rows)
    summary = pd.DataFrame(
        [
            {
                "audit_label": label,
                "support_start": daily.loc[daily["is_complete_24h_policy"], "delivery_day"].min() if not daily.empty else "",
                "support_end": daily.loc[daily["is_complete_24h_policy"], "delivery_day"].max() if not daily.empty else "",
                "complete_forecast_origins": int(daily.loc[daily["is_complete_24h_policy"], "forecast_origin_count"].eq(1).sum()),
                "complete_delivery_days": int(daily["is_complete_24h_policy"].sum()),
                "dst_target_days": int(daily["is_dst_non_24h_day"].sum()),
                "missing_days_24h_policy": int(((daily["expected_hours_in_local_day"] == 24) & (~daily["is_complete_24h_policy"])).sum()),
                "missing_hours_24h_policy": int(len(missing_hours)),
                "actual_price_complete_24h_policy": bool(daily.loc[daily["expected_hours_in_local_day"] == 24, "actual_missing_rows"].sum() == 0),
                "duplicate_rows": int(dup_count),
                "eligible_for_period_24h_policy": bool(
                    ((daily["expected_hours_in_local_day"] == 24) & (~daily["is_complete_24h_policy"])).sum() == 0
                    and dup_count == 0
                ),
                "eligible_for_calendar_period": bool(
                    daily["is_complete_24h_policy"].sum() == daily.shape[0] and dup_count == 0
                ),
            }
        ]
    )
    return daily, summary, pd.DataFrame(missing_days), pd.DataFrame(missing_hours)


def _prepare_candidate_predictions(anchor: pd.DataFrame) -> pd.DataFrame:
    frame = anchor.copy()
    frame["candidate_key"] = MODEL_ID
    frame["candidate_label"] = MODEL_LABEL
    frame["candidate_context"] = "repaired_hourly_donly_anchor"
    frame["variant"] = "external"
    frame["display_group"] = "external"
    frame["internal_model"] = MODEL_ID
    frame["model_family"] = "lear"
    frame["fs_level"] = "FS3"
    frame["source_run_id"] = "repair_hourly_lear_strict_donly_support"
    frame["source_run_label"] = "repair_hourly_lear_strict_donly_support"
    frame["target_timestamp_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="coerce")
    frame["y_true"] = pd.to_numeric(frame["actual_price_eur_per_mwh"], errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame["point_forecast_eur_per_mwh"], errors="coerce")
    return frame[
        [
            "candidate_key",
            "candidate_label",
            "candidate_context",
            "variant",
            "display_group",
            "internal_model",
            "model_family",
            "fs_level",
            "source_run_id",
            "source_run_label",
            "dataset_split",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "lead_day",
            "y_true",
            "y_pred",
        ]
    ].copy()


def _bias_setting(candidate_key: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "candidate_key": candidate_key,
                "setting_id": f"{candidate_key}_option_c_hour_global_mean",
                "statistic": "mean",
                "level_profile_name": "hour_global",
                "min_observations": 20,
                "shrinkage": 1.0,
                "cap_abs": np.nan,
                "window_days": np.nan,
            }
        ]
    )


def _probability_check(scenarios: pd.DataFrame) -> pd.DataFrame:
    dedup = scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]].drop_duplicates()
    out = (
        dedup.groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
        .sort_values("forecast_origin_utc")
        .reset_index(drop=True)
    )
    out["probability_sum_valid"] = out["probability_sum"].between(0.999999, 1.000001)
    out["scenario_count_valid"] = out["scenario_count"].astype(int).eq(75)
    return out


def _scenario_temporal_coherence_check(scenarios: pd.DataFrame) -> bool:
    counts = (
        scenarios.groupby(["forecast_origin_utc", "scenario_id"], as_index=False)["delivery_start_utc"]
        .nunique()
        .rename(columns={"delivery_start_utc": "hour_count"})
    )
    return bool(counts["hour_count"].astype(int).eq(24).all()) if not counts.empty else False


def _validation_metrics_row(
    *,
    setting_id: str,
    family: str,
    lower_tail_scale: float | None,
    upper_tail_scale: float | None,
    central_scale: float | None,
    use_option_a: bool,
    use_option_c: bool,
    scenario_prices: pd.DataFrame,
) -> dict[str, Any]:
    validation_bundle = validate_scenario_set(scenario_prices, config=_default_hourly_config())
    summary = score_scenario_variants(validation_bundle["summary"])
    if summary.empty:
        raise ValueError(f"No validation summary produced for setting {setting_id}.")
    row = summary.iloc[0].to_dict()
    probability_checks = _probability_check(scenario_prices.rename(columns={"probability": "scenario_probability", "period_timestamp": "delivery_start_utc"}))
    row.update(
        {
            "setting_id": setting_id,
            "setting_family": family,
            "use_option_a": bool(use_option_a),
            "use_option_c": bool(use_option_c),
            "lower_tail_scale": lower_tail_scale,
            "upper_tail_scale": upper_tail_scale,
            "central_scale": central_scale,
            "actual_inside_minmax_share": float(row.get("minmax_coverage", np.nan)),
            "above_p95_exceedance": float(row.get("high_tail_miss_rate", np.nan)),
            "below_p95_exceedance": float(row.get("low_tail_miss_rate", np.nan)),
            "upper_tail_coverage": float(1.0 - float(row.get("high_tail_miss_rate", np.nan))) if pd.notna(row.get("high_tail_miss_rate", np.nan)) else np.nan,
            "lower_tail_coverage": float(1.0 - float(row.get("low_tail_miss_rate", np.nan))) if pd.notna(row.get("low_tail_miss_rate", np.nan)) else np.nan,
            "p95_p05_interval_width": float(row.get("average_p05_p95_width", np.nan)),
            "scenario_probability_blocks": int(probability_checks.shape[0]),
            "scenario_probability_failures": int((~probability_checks["probability_sum_valid"]).sum()),
            "scenario_count_failures": int((~probability_checks["scenario_count_valid"]).sum()),
            "temporal_coherence_ok": bool(_scenario_temporal_coherence_check(scenario_prices.rename(columns={"period_timestamp": "delivery_start_utc"}))),
            "crps": np.nan,
        }
    )
    return row


def _selection_score(frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    width_median = max(float(scored["p95_p05_interval_width"].median()), 1.0)
    scored["width_ratio"] = scored["p95_p05_interval_width"] / width_median
    scored["coverage_gap"] = (scored["p05_p95_coverage"] - 0.875).abs()
    scored["upper_tail_penalty"] = np.maximum(scored["above_p95_exceedance"] - 0.075, 0.0)
    scored["lower_tail_penalty"] = np.maximum(scored["low_tail_miss_rate"] - 0.075, 0.0)
    scored["overwide_penalty"] = np.maximum(scored["width_ratio"] - 1.20, 0.0)
    scored["invalidity_penalty"] = (
        scored["scenario_probability_failures"].astype(float) * 100.0
        + scored["scenario_count_failures"].astype(float) * 100.0
        + (~scored["temporal_coherence_ok"]).astype(int) * 100.0
    )
    scored["selection_score"] = (
        5.0 * scored["upper_tail_penalty"]
        + 2.5 * scored["coverage_gap"]
        + 1.5 * scored["lower_tail_penalty"]
        + 0.5 * scored["overwide_penalty"]
        + scored["invalidity_penalty"]
    )
    return scored.sort_values(
        ["selection_score", "above_p95_exceedance", "coverage_gap", "p95_p05_interval_width", "setting_id"],
        ascending=[True, True, True, True, True],
    ).reset_index(drop=True)


def _normalize_final_scenarios(
    scenarios: pd.DataFrame,
    *,
    selected_setting: dict[str, Any],
) -> pd.DataFrame:
    frame = scenarios.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["period_timestamp"], utc=True, errors="coerce")
    frame["delivery_start_local"] = frame["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam").dt.strftime("%Y-%m-%d %H:%M:%S")
    frame["scenario_probability"] = pd.to_numeric(frame["probability"], errors="coerce")
    frame["scenario_price_eur_per_mwh"] = pd.to_numeric(frame["scenario_price"], errors="coerce")
    frame["point_forecast_eur_per_mwh"] = pd.to_numeric(frame["central_forecast_price"], errors="coerce")
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["actual_price"], errors="coerce")
    frame["model_id"] = MODEL_ID
    frame["model_label"] = MODEL_LABEL
    frame["granularity"] = "hourly"
    frame["horizon"] = "D-only"
    frame["lead_day"] = 0
    frame["scenario_generation_version"] = SCENARIO_GENERATION_VERSION
    frame["calibration_setting_id"] = str(selected_setting["setting_id"])
    frame["calibration_settings_json"] = json.dumps(selected_setting, sort_keys=True, default=str)
    frame["scenario_generation_run_id"] = frame["scenario_run_id"].astype(str)
    return frame


def _coverage_by_period(period_validation: pd.DataFrame, *, freq: str) -> pd.DataFrame:
    work = period_validation.copy()
    work["delivery_start_utc"] = pd.to_datetime(work["period_timestamp"], utc=True, errors="coerce")
    work["delivery_local"] = work["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam")
    if freq == "week":
        work["period_label"] = work["delivery_local"].dt.strftime("%G-W%V")
    elif freq == "month":
        work["period_label"] = work["delivery_local"].dt.strftime("%Y-%m")
    else:
        raise ValueError(freq)
    return (
        work.groupby(["dataset_split", "period_label"], as_index=False)
        .agg(
            p05_p95_coverage=("coverage_p05_p95", "mean"),
            minmax_coverage=("coverage_minmax", "mean"),
            above_p95_exceedance=("high_tail_miss", "mean"),
            below_p05_exceedance=("low_tail_miss", "mean"),
            average_p95_p05_width=("width_p05_p95", "mean"),
            row_count=("period_timestamp", "size"),
        )
        .sort_values(["dataset_split", "period_label"])
        .reset_index(drop=True)
    )


def _write_markdown(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    support_start = pd.Timestamp(args.support_start_local_date).date()
    support_end = pd.Timestamp(args.support_end_local_date).date()
    if args.resume_run_dir is not None:
        run_dir = args.resume_run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = OUTPUT_ROOT / f"{_now_id()}_lear_strict_donly_support_repair"
        run_dir.mkdir(parents=True, exist_ok=True)

    frozen_run_dir = args.frozen_run_dir.resolve()
    anchor_parquet = run_dir / "hourly_lear_strict_donly_1092_full_support_anchor.parquet"
    anchor_csv = run_dir / "hourly_lear_strict_donly_1092_full_support_anchor.csv"
    split_lookup = _build_split_lookup()
    feature_config = replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=min(split_lookup.keys()),
        benchmark_end_exclusive_local_date=max(split_lookup.keys()) + timedelta(days=1),
        x2_policy="res_forecast_if_available",
        x2_missing_policy="impute_training_median",
        allow_official_cleaned_fallback=True,
    )
    if anchor_parquet.exists():
        anchor = pd.read_parquet(anchor_parquet)
    elif anchor_csv.exists():
        anchor = pd.read_csv(anchor_csv, low_memory=False)
    else:
        pred_path = frozen_run_dir / "predictions" / "predictions_long.csv"
        inventory_path = run_dir / "lear_strict_source_inventory.csv"
        predictions = _load_frozen_predictions(pred_path)
        _source_inventory(predictions, inventory_path)

        observed_x, observed_y, observed_metadata = _load_frozen_observed_matrix(frozen_run_dir)
        official_days = {day for day, split in split_lookup.items() if split in {"validation", "test"} and support_start <= day <= support_end}
        source_filtered = predictions[
            (predictions["model"].astype(str) == SELECTED_MODEL)
            & (predictions["lead_day"].astype(int) == 0)
            & (predictions["target_delivery_local_date"].isin(sorted(official_days)))
        ].copy()
        source_filtered["dataset_split"] = source_filtered["target_delivery_local_date"].map(split_lookup)
        source_filtered = source_filtered[source_filtered["dataset_split"].isin(["validation", "test"])].copy()
        raw_price = load_lago_price_frame(feature_config)
        raw_price = raw_price[raw_price["region"].astype(str) == feature_config.target_region].copy() if "region" in raw_price.columns else raw_price
        raw_price = _with_price_local_cols(raw_price, feature_config)
        actual_long, actual_diag = _build_actual_long(
            price_frame=raw_price,
            support_start=support_start,
            support_end=support_end,
            split_lookup=split_lookup,
            config=feature_config,
        )
        actual_long.to_csv(run_dir / "actual_price_support_long.csv", index=False)
        actual_diag.to_csv(run_dir / "actual_price_coercion_diagnostics.csv", index=False)

        existing = source_filtered.rename(columns={"target_timestamp_utc": "delivery_start_utc", "y_pred": "point_forecast_eur_per_mwh"}).copy()
        existing = existing[
            [
                "forecast_origin_utc",
                "delivery_start_utc",
                "lead_day",
                "point_forecast_eur_per_mwh",
                "model",
                "model_family",
                "dataset_split",
                "target_delivery_local_date",
            ]
        ].rename(columns={"target_delivery_local_date": "delivery_day"})
        existing["delivery_day"] = pd.to_datetime(existing["delivery_day"], errors="coerce").dt.date.astype(str)
        existing_days = set(pd.to_datetime(existing["delivery_day"], errors="coerce").dt.date.dropna().tolist())

        candidate_x, _, candidate_meta, candidate_skips = _build_inference_features(
            config=feature_config,
            support_start=support_start,
            support_end=support_end,
            existing_days=existing_days,
            feature_columns=observed_x.columns.tolist(),
            price_frame=raw_price,
        )
        generated, generation_skips = _predict_missing_days(
            observed_x=observed_x,
            observed_y=observed_y,
            observed_metadata=observed_metadata,
            candidate_x=candidate_x,
            candidate_metadata=candidate_meta,
            split_lookup=split_lookup,
            config=feature_config,
        )
        candidate_skips.to_csv(run_dir / "candidate_skip_rows.csv", index=False)
        generation_skips.to_csv(run_dir / "generation_skip_rows.csv", index=False)

        anchor = pd.concat(
            [
                existing[["forecast_origin_utc", "delivery_start_utc", "lead_day", "point_forecast_eur_per_mwh", "dataset_split", "delivery_day"]].copy(),
                generated[["forecast_origin_utc", "delivery_start_utc", "lead_day", "point_forecast_eur_per_mwh", "dataset_split", "delivery_day"]].copy(),
            ],
            ignore_index=True,
        )
        anchor["forecast_origin_utc"] = pd.to_datetime(anchor["forecast_origin_utc"], utc=True, errors="coerce")
        anchor["delivery_start_utc"] = pd.to_datetime(anchor["delivery_start_utc"], utc=True, errors="coerce")
        anchor["lead_day"] = pd.to_numeric(anchor["lead_day"], errors="coerce").fillna(0).astype(int)
        anchor["delivery_day"] = pd.to_datetime(anchor["delivery_day"], errors="coerce").dt.date.astype(str)
        anchor = anchor.drop_duplicates(["forecast_origin_utc", "delivery_start_utc"], keep="last")
        anchor = anchor.merge(
            actual_long,
            on=["forecast_origin_utc", "delivery_start_utc", "delivery_day", "lead_day", "dataset_split"],
            how="left",
        )
        anchor["model_id"] = MODEL_ID
        anchor["model_label"] = MODEL_LABEL
        anchor["granularity"] = "hourly"
        anchor["horizon"] = "D-only"
        anchor["actual_price_source_policy"] = "hourly_cleaned_nonnull_with_dst_lag_coercion_v1"
        anchor = anchor.sort_values(["dataset_split", "forecast_origin_utc", "delivery_start_utc"]).reset_index(drop=True)
        anchor.to_parquet(anchor_parquet, index=False)
        anchor.to_csv(anchor_csv, index=False)

    validation_daily, validation_summary, validation_missing_days, validation_missing_hours = _build_anchor_support_audit(
        anchor[anchor["dataset_split"].astype(str) == "validation"].copy(),
        start_day=pd.Timestamp("2023-10-01").date(),
        end_day=pd.Timestamp("2024-09-30").date(),
        label="validation",
        config=feature_config,
    )
    test_daily, test_summary, test_missing_days, test_missing_hours = _build_anchor_support_audit(
        anchor[anchor["dataset_split"].astype(str) == "test"].copy(),
        start_day=pd.Timestamp("2024-10-01").date(),
        end_day=pd.Timestamp("2025-09-30").date(),
        label="test",
        config=feature_config,
    )
    support_audit = pd.concat([validation_summary, test_summary], ignore_index=True)
    support_audit.to_csv(run_dir / "hourly_lear_strict_donly_1092_anchor_support_audit.csv", index=False)
    validation_daily.to_csv(run_dir / "anchor_support_daily_validation.csv", index=False)
    test_daily.to_csv(run_dir / "anchor_support_daily_test.csv", index=False)

    missing_days = pd.concat([validation_missing_days, test_missing_days], ignore_index=True)
    missing_hours = pd.concat([validation_missing_hours, test_missing_hours], ignore_index=True)
    missing_days.to_csv(run_dir / "missing_origins.csv", index=False)
    missing_hours.to_csv(run_dir / "missing_delivery_hours.csv", index=False)

    blocker_lines = [
        "# LEAR Strict Support Blockers",
        "",
        f"- selected_model_variant: `{SELECTED_MODEL}`",
        f"- repair_anchor_path: `{anchor_csv}`",
        "",
        "## Findings",
        "",
        f"- validation_complete_days_24h_policy: {int(validation_summary['complete_delivery_days'].iloc[0])}",
        f"- validation_missing_days_24h_policy: {int(validation_summary['missing_days_24h_policy'].iloc[0])}",
        f"- validation_dst_target_days: {int(validation_summary['dst_target_days'].iloc[0])}",
        f"- test_complete_days_24h_policy: {int(test_summary['complete_delivery_days'].iloc[0])}",
        f"- test_missing_days_24h_policy: {int(test_summary['missing_days_24h_policy'].iloc[0])}",
        f"- test_dst_target_days: {int(test_summary['dst_target_days'].iloc[0])}",
        "",
        "## Interpretation",
        "",
        "- The preserved frozen 1092 predictions do not cover the thesis split end to end.",
        "- The repaired anchor recovers missing non-DST support by rebuilding lag vectors from the cleaned hourly price source and generating missing 1092-window forecasts without using the QH bridge.",
        "- Remaining unsupported calendar days are DST target days if the downstream hourly optimisation and scenario pipeline remains fixed at 24 periods per delivery day.",
        "- Missing non-DST support after repair indicates a genuine remaining blocker in the repaired hourly source path.",
    ]
    _write_markdown(run_dir / "lear_strict_support_blockers.md", "\n".join(blocker_lines))

    candidate_predictions = _prepare_candidate_predictions(anchor.dropna(subset=["actual_price_eur_per_mwh", "point_forecast_eur_per_mwh"]))
    residual_periods_raw = build_residual_period_table(candidate_predictions, config=_default_hourly_config(), lead_day=0)
    residual_daily_profiles_raw = build_residual_daily_profiles(residual_periods_raw)
    residual_daily_profiles_raw.to_csv(run_dir / "residual_daily_profiles_raw.csv", index=False)

    sweep_rows: list[dict[str, Any]] = []
    sweep_artifacts: dict[str, dict[str, Any]] = {}
    selected_key = MODEL_ID
    validation_only_split = "validation"
    variant_counter = 0
    sweep_n_raw = min(int(args.n_raw), 200)

    setting_specs: list[dict[str, Any]] = [
        {"family": "baseline_current", "setting_id": "baseline_current", "use_option_a": False, "use_option_c": False, "candidate_settings": pd.DataFrame(), "scaling_profile": None},
        {"family": "option_a", "setting_id": "option_a", "use_option_a": True, "use_option_c": False, "candidate_settings": pd.DataFrame(), "scaling_profile": None},
        {"family": "option_a_plus_c", "setting_id": "option_a_plus_c", "use_option_a": True, "use_option_c": True, "candidate_settings": _bias_setting(selected_key), "scaling_profile": None},
    ]
    for lower_scale, upper_scale, central_scale in [
        (1.0, 1.10, 1.0),
        (1.0, 1.25, 1.0),
        (1.1, 1.25, 1.0),
        (1.1, 1.40, 1.1),
        (1.2, 1.40, 1.1),
    ]:
        setting_specs.append(
            {
                "family": "option_a_plus_c_plus_asym",
                "setting_id": f"option_a_plus_c_plus_asym_l{str(lower_scale).replace('.', '')}_u{str(upper_scale).replace('.', '')}_c{str(central_scale).replace('.', '')}",
                "use_option_a": True,
                "use_option_c": True,
                "candidate_settings": _bias_setting(selected_key),
                "asym_lower": lower_scale,
                "asym_upper": upper_scale,
                "asym_central": central_scale,
            }
        )

    for spec in setting_specs:
        corrected_periods = apply_bias_correction_candidate_settings(
            residual_periods_raw,
            candidate_settings=spec["candidate_settings"],
            calibration_split=validation_only_split,
        )
        residual_daily_profiles = build_residual_daily_profiles(corrected_periods)
        scaling_profile = spec.get("scaling_profile")
        if spec.get("family") == "option_a_plus_c_plus_asym":
            residual_col = "bias_corrected_residual"
            val_abs = corrected_periods.loc[
                (corrected_periods["candidate_key"].astype(str) == selected_key)
                & (corrected_periods["dataset_split"].astype(str) == validation_only_split),
                residual_col,
            ].abs()
            threshold = float(val_abs.quantile(0.50)) if not val_abs.empty else 0.0
            scaling_profile = {
                "lower_tail_scale": float(spec["asym_lower"]),
                "upper_tail_scale": float(spec["asym_upper"]),
                "central_scale": float(spec["asym_central"]),
                "central_abs_residual_threshold": float(threshold),
            }
        variant_counter += 1
        scenario_variant = f"{spec['setting_id']}__v{variant_counter:02d}"
        bundle = generate_scenario_bundle(
            corrected_periods,
            residual_daily_profiles,
            config=_default_hourly_config(),
            horizon_spec=resolve_scenario_horizon_spec(horizon_mode="D_ONLY", granularity="hourly"),
            calibration_split=validation_only_split,
            target_split=validation_only_split,
            selected_candidate_keys=[selected_key],
            variant_plan=pd.DataFrame(
                [
                    {
                        "scenario_variant": scenario_variant,
                        "use_option_a": bool(spec["use_option_a"]),
                        "use_option_b": False,
                        "use_option_c": bool(spec["use_option_c"]),
                    }
                ]
            ),
            scenario_run_id=f"{_now_id()}_{SCENARIO_GENERATION_VERSION}",
            random_seed=int(args.random_seed),
            n_raw_scenarios=int(sweep_n_raw),
            n_final_scenarios=int(args.n_final),
            normal_share=0.60,
            positive_tail_share=0.30,
            negative_tail_share=0.10,
            stress_share=0.0,
            protected_tail_share=0.20,
            probability_policy="empirical_cluster_mass",
            reduction_method="tail_protected_representative_v1",
            residual_scale_factor=1.0,
            residual_scaling_profile=scaling_profile,
        )
        final_scenarios = bundle["final_scenarios"].copy()
        if final_scenarios.empty:
            continue
        metrics = _validation_metrics_row(
            setting_id=spec["setting_id"],
            family=spec["family"],
            lower_tail_scale=spec.get("asym_lower"),
            upper_tail_scale=spec.get("asym_upper"),
            central_scale=spec.get("asym_central"),
            use_option_a=bool(spec["use_option_a"]),
            use_option_c=bool(spec["use_option_c"]),
            scenario_prices=final_scenarios,
        )
        sweep_rows.append(metrics)
        pd.DataFrame(sweep_rows).to_csv(run_dir / "lear_strict_scenario_calibration_sweep_validation.csv", index=False)
        sweep_artifacts[spec["setting_id"]] = {
            "spec": spec,
            "corrected_periods": corrected_periods,
            "residual_daily_profiles": residual_daily_profiles,
            "scaling_profile": scaling_profile,
        }

    sweep = _selection_score(pd.DataFrame(sweep_rows))
    sweep.to_csv(run_dir / "lear_strict_scenario_calibration_sweep_validation.csv", index=False)
    if sweep.empty:
        raise RuntimeError("Calibration sweep produced no valid settings.")
    selected_setting = sweep.iloc[0].to_dict()
    (run_dir / "lear_strict_scenario_calibration_selected_settings.json").write_text(
        json.dumps(selected_setting, indent=2, default=str),
        encoding="utf-8",
    )
    _write_markdown(
        run_dir / "lear_strict_scenario_calibration_report.md",
        "\n".join(
            [
                "# LEAR Strict Scenario Calibration",
                "",
                f"- selected_setting_id: `{selected_setting['setting_id']}`",
                f"- sweep_n_raw_scenarios: {int(sweep_n_raw)}",
                f"- final_n_raw_scenarios: {int(args.n_raw)}",
                f"- selected_family: `{selected_setting['setting_family']}`",
                f"- p05_p95_coverage: {selected_setting['p05_p95_coverage']:.6f}",
                f"- above_p95_exceedance: {selected_setting['above_p95_exceedance']:.6f}",
                f"- below_p05_exceedance: {selected_setting['below_p95_exceedance']:.6f}",
                f"- average_p95_p05_width: {selected_setting['p95_p05_interval_width']:.6f}",
                "",
                "Selection used validation metrics only. Test results were not used to choose the scenario setting.",
            ]
        ),
    )

    chosen = sweep_artifacts[str(selected_setting["setting_id"])]
    final_bundle_parts: list[dict[str, Any]] = []
    for split_name in ["validation", "test"]:
        final_bundle_parts.append(
            generate_scenario_bundle(
                chosen["corrected_periods"],
                chosen["residual_daily_profiles"],
                config=_default_hourly_config(),
                horizon_spec=resolve_scenario_horizon_spec(horizon_mode="D_ONLY", granularity="hourly"),
                calibration_split="validation",
                target_split=split_name,
                selected_candidate_keys=[selected_key],
                variant_plan=pd.DataFrame(
                    [
                        {
                            "scenario_variant": str(selected_setting["setting_id"]),
                            "use_option_a": bool(selected_setting["use_option_a"]),
                            "use_option_b": False,
                            "use_option_c": bool(selected_setting["use_option_c"]),
                        }
                    ]
                ),
                scenario_run_id=f"{_now_id()}_{SCENARIO_GENERATION_VERSION}",
                random_seed=int(args.random_seed),
                n_raw_scenarios=int(args.n_raw),
                n_final_scenarios=int(args.n_final),
                normal_share=0.60,
                positive_tail_share=0.30,
                negative_tail_share=0.10,
                stress_share=0.0,
                protected_tail_share=0.20,
                probability_policy="empirical_cluster_mass",
                reduction_method="tail_protected_representative_v1",
                residual_scale_factor=1.0,
                residual_scaling_profile=chosen["scaling_profile"],
            )
        )

    final_scenarios = pd.concat([part["final_scenarios"] for part in final_bundle_parts if not part["final_scenarios"].empty], ignore_index=True)
    final_metadata = pd.concat([part["final_metadata"] for part in final_bundle_parts if not part["final_metadata"].empty], ignore_index=True)
    normalized_final = _normalize_final_scenarios(final_scenarios, selected_setting=selected_setting)
    artifact_dir = run_dir / SCENARIO_ARTIFACT_ID
    artifact_dir.mkdir(parents=True, exist_ok=True)
    scenario_path_csv = artifact_dir / "scenario_prices_long.csv"
    scenario_path_parquet = artifact_dir / "scenario_prices_long.parquet"
    normalized_final.to_csv(scenario_path_csv, index=False)
    normalized_final.to_parquet(scenario_path_parquet, index=False)
    final_metadata.to_csv(artifact_dir / "scenario_metadata.csv", index=False)

    final_validation = validate_scenario_set(final_scenarios, config=_default_hourly_config())
    final_summary = score_scenario_variants(final_validation["summary"])
    final_summary.to_csv(artifact_dir / "scenario_calibration_summary.csv", index=False)
    _coverage_by_period(final_validation["period_validation"], freq="week").to_csv(artifact_dir / "scenario_coverage_by_week.csv", index=False)
    _coverage_by_period(final_validation["period_validation"], freq="month").to_csv(artifact_dir / "scenario_coverage_by_month.csv", index=False)
    probability_checks = _probability_check(normalized_final)
    probability_checks.to_csv(artifact_dir / "scenario_probability_checks.csv", index=False)

    manifest = {
        "artifact_id": SCENARIO_ARTIFACT_ID,
        "scenario_file_csv": str(scenario_path_csv.relative_to(REPO_ROOT)),
        "scenario_file_parquet": str(scenario_path_parquet.relative_to(REPO_ROOT)),
        "anchor_file": str(anchor_parquet.relative_to(REPO_ROOT)),
        "model_id": MODEL_ID,
        "model_label": MODEL_LABEL,
        "granularity": "hourly",
        "horizon": "D-only",
        "lead_day": 0,
        "scenario_count": 75,
        "probability_convention": "empirical_cluster_mass_post_reduction",
        "selected_validation_setting": selected_setting,
        "support_start": str(pd.to_datetime(normalized_final["delivery_day"], errors="coerce").min().date()) if not normalized_final.empty else "",
        "support_end": str(pd.to_datetime(normalized_final["delivery_day"], errors="coerce").max().date()) if not normalized_final.empty else "",
        "known_limitations": [
            "Hourly D-only scenario generation remains fixed to 24-period delivery days.",
            "DST target days are excluded from the repaired hourly support set until the downstream hourly optimiser and scenario pipeline support 23/25-hour days natively.",
            "Historical lag-price support uses cleaned hourly price rows with day-level coercion for missing/null hours.",
        ],
    }
    (artifact_dir / "scenario_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    readiness = {
        "artifact_id": SCENARIO_ARTIFACT_ID,
        "eligible_for_full_year_milp_run": bool(test_summary["eligible_for_period_24h_policy"].iloc[0]),
        "validation_complete_support": bool(validation_summary["eligible_for_period_24h_policy"].iloc[0]),
        "test_complete_support": bool(test_summary["eligible_for_period_24h_policy"].iloc[0]),
        "number_of_complete_test_days": int(test_summary["complete_delivery_days"].iloc[0]),
        "missing_test_days": int(test_summary["missing_days_24h_policy"].iloc[0]),
        "missing_test_hours": int(test_summary["missing_hours_24h_policy"].iloc[0]),
        "all_origins_have_75_scenarios": bool(probability_checks["scenario_count_valid"].all()),
        "probability_sums_valid": bool(probability_checks["probability_sum_valid"].all()),
        "actual_prices_complete": bool(normalized_final["actual_price_eur_per_mwh"].notna().all()),
        "scenario_containment_summary": final_summary[["dataset_split", "p05_p95_coverage", "minmax_coverage", "high_tail_miss_rate", "low_tail_miss_rate", "average_p05_p95_width"]].to_dict(orient="records"),
        "remaining_warnings": "DST target days remain excluded from the 24h-only hourly pipeline.",
    }
    pd.DataFrame([readiness]).to_csv(run_dir / "lear_strict_optimisation_readiness_audit.csv", index=False)
    _write_markdown(
        run_dir / "README_lear_strict_full_support_repair.md",
        "\n".join(
            [
                "# LEAR Strict D-only Support Repair",
                "",
                f"- artifact_id: `{SCENARIO_ARTIFACT_ID}`",
                f"- selected_model_variant: `{SELECTED_MODEL}`",
                f"- anchor_path: `{anchor_csv.relative_to(REPO_ROOT)}`",
                f"- scenario_path: `{scenario_path_csv.relative_to(REPO_ROOT)}`",
                "",
                "This repair phase rebuilds hourly D-only LEAR Strict support from the preserved frozen 1092 source and extends it with missing-day predictions generated directly from hourly source data. The QH bridge is not used.",
                "",
                "Scenario calibration is selected on validation only. Test metrics are reported for holdout diagnostics only.",
            ]
        ),
    )

    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "artifact_id": SCENARIO_ARTIFACT_ID,
                "anchor_path": str(anchor_csv),
                "scenario_path": str(scenario_path_csv),
                "validation_complete_support": bool(validation_summary["eligible_for_period_24h_policy"].iloc[0]),
                "test_complete_support": bool(test_summary["eligible_for_period_24h_policy"].iloc[0]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
