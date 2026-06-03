from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.external_features import build_feature_context_for_origin, load_external_feature_store
from hourly_da.core.feature_value import instantiate_model_from_parent_context
from hourly_da.core.forecast_evaluation import discover_final_candidate_runs
from hourly_da.core.metrics import diebold_mariano_test
from hourly_da.core.reporting import ReportingLevelSpec, find_latest_run, load_csv, reporting_level_specs
from hourly_da.core.storage import create_run_directory, write_csv, write_json
from hourly_da.core.time_utils import known_at_utc_for_delivery_date, local_date_to_utc_bounds, localize_naive_timestamp

from .config import QuarterHourDAExtensionConfig
from .phase02 import _read_phase01_authority
from .phase04 import _build_feature_frame, _fit_mean_shape, _fit_xgboost, _predict_mean_shape
from .phase05 import _enrich_hourly_anchor_frame, _expand_hourly_to_quarters
from .phase07 import _load_selected_model_payload


RUN_LABEL = "observed_market_deterministic_forecast"
EXPECTED_NORMAL_QUARTERS_PER_DAY = 96
EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN = 5 * EXPECTED_NORMAL_QUARTERS_PER_DAY
MIN_TRAIN_ORIGINS_PREFERRED = 28
MIN_VALIDATION_ORIGINS_PREFERRED = 14
MIN_TEST_ORIGINS_PREFERRED = 14
MIN_OFFICIAL_NAIVE_COVERAGE_PCT = 95.0
XGBOOST_MIN_TRAIN_ROWS = 28 * EXPECTED_NORMAL_QUARTERS_PER_DAY

BENCHMARK_PREVIOUS_AVAILABLE = "naive_previous_available_same_quarter"
BENCHMARK_PREVIOUS_WEEK = "naive_previous_week_same_quarter"
BENCHMARK_LAST_FULL_DAY = "naive_last_full_day_profile"
BENCHMARK_REPEATED_HOURLY = "repeated_hourly_backbone"
MODEL_MEAN_SHAPE = "mean_shape_deviation"
MODEL_XGBOOST = "xgboost_deviation"


@dataclass(frozen=True)
class SplitWindow:
    split: str
    start_delivery_local_date: date
    end_delivery_local_date: date
    notes: str


def find_latest_observed_deterministic_run(config: QuarterHourDAExtensionConfig | None = None) -> Path | None:
    config = config or QuarterHourDAExtensionConfig()
    try:
        return find_latest_run(config.output_root, RUN_LABEL)
    except FileNotFoundError:
        return None


def _timestamped_now_utc() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat()


def _build_hourly_market_config(config: QuarterHourDAExtensionConfig) -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(
        market_area=config.market_area,
        business_timezone=config.business_timezone,
        output_root=config.hourly_da_output_root,
    )


def _build_required_origin_columns() -> list[str]:
    return [
        "dataset_split",
        "delivery_start_local_date",
        "forecast_origin_local",
        "forecast_origin_utc",
        "expected_normal_target_count_per_origin",
        "actual_target_count_per_origin",
        "observed_target_count_per_origin",
        "observed_target_coverage_pct",
        "target_count_status",
        "availability_status",
        "split_policy",
    ]


def _resolve_authoritative_quarterhour_source(config: QuarterHourDAExtensionConfig) -> tuple[Path, dict[str, Any]]:
    authority = _read_phase01_authority(config)
    source_path = Path(authority["authoritative_quarterhour_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"Authoritative quarter-hour source not found: {source_path}")
    return source_path, authority


def _resolve_duplicate_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    ordered = frame.copy().sort_values(["timestamp_utc"]).reset_index(drop=True)
    if not ordered["timestamp_utc"].duplicated().any():
        return ordered
    ordered["_source_row_number"] = np.arange(ordered.shape[0], dtype=int)
    deduped = (
        ordered.sort_values(["timestamp_utc", "_source_row_number"])
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .drop(columns=["_source_row_number"])
        .reset_index(drop=True)
    )
    return deduped


def _quarterhour_feature_source_from_causal_imputation(observed_series: pd.Series) -> tuple[pd.Series, pd.Series]:
    values = observed_series.astype(float).to_numpy(copy=True)
    methods = np.full(shape=values.shape[0], fill_value="observed", dtype=object)
    last_available_value = np.nan

    for index, value in enumerate(values):
        if not np.isnan(value):
            last_available_value = value
            continue

        if index >= 96 and not np.isnan(values[index - 96]):
            values[index] = values[index - 96]
            methods[index] = "same_quarter_previous_day"
        elif index >= 96 * 7 and not np.isnan(values[index - 96 * 7]):
            values[index] = values[index - 96 * 7]
            methods[index] = "same_quarter_previous_week"
        elif not np.isnan(last_available_value):
            values[index] = last_available_value
            methods[index] = "last_available_observation"
        else:
            methods[index] = "unfilled"

        if not np.isnan(values[index]):
            last_available_value = values[index]

    return (
        pd.Series(values, index=observed_series.index, dtype=float),
        pd.Series(methods, index=observed_series.index, dtype="object"),
    )


def load_and_build_canonical_quarterhour_frame(
    config: QuarterHourDAExtensionConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = config or QuarterHourDAExtensionConfig()
    source_path, authority = _resolve_authoritative_quarterhour_source(config)
    frame = pd.read_csv(source_path)
    if frame.empty:
        raise ValueError(f"Quarter-hour source file is empty: {source_path}")

    required_cols = {
        "timestamp_utc",
        "region",
        "price_eur_per_mwh",
        "resolution_minutes",
        "gap_fix_action",
        "is_interpolated_value",
        "is_flagged_missing_value",
        "missing_datapoint_source",
    }
    missing_cols = sorted(required_cols - set(frame.columns))
    if missing_cols:
        raise ValueError(f"Quarter-hour source file is missing required columns: {missing_cols}")

    frame = frame[frame["region"].astype(str) == str(config.market_area)].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
    frame["price_eur_per_mwh_original"] = pd.to_numeric(frame.get("price_eur_per_mwh_original"), errors="coerce")
    frame["resolution_minutes"] = pd.to_numeric(frame["resolution_minutes"], errors="coerce")
    frame["is_interpolated_value"] = frame["is_interpolated_value"].fillna(False).astype(bool)
    frame["is_flagged_missing_value"] = frame["is_flagged_missing_value"].fillna(False).astype(bool)
    frame = frame.dropna(subset=["timestamp_utc"]).copy()
    frame = frame[frame["resolution_minutes"].eq(15)].copy()
    frame = _resolve_duplicate_rows(frame)

    start_utc = pd.Timestamp(frame["timestamp_utc"].min())
    end_utc = pd.Timestamp(frame["timestamp_utc"].max())
    canonical_index = pd.date_range(start=start_utc, end=end_utc, freq="15min", tz="UTC")
    canonical = pd.DataFrame({"timestamp_utc": canonical_index})
    observed_cols = [column for column in frame.columns if column != "timestamp_utc"]
    merged = canonical.merge(frame[["timestamp_utc"] + observed_cols], on="timestamp_utc", how="left", sort=True)

    merged["region"] = merged["region"].fillna(config.market_area)
    merged["resolution"] = merged.get("resolution", pd.Series(dtype="object")).fillna("PT15M")
    merged["resolution_minutes"] = pd.to_numeric(merged["resolution_minutes"], errors="coerce").fillna(15).astype("Int64")
    merged["gap_fix_action"] = merged["gap_fix_action"].fillna("canonical_missing")
    merged["missing_datapoint_source"] = merged["missing_datapoint_source"].fillna("canonical_missing")
    merged["is_interpolated_value"] = merged["is_interpolated_value"].fillna(False).astype(bool)
    merged["is_flagged_missing_value"] = merged["is_flagged_missing_value"].fillna(False).astype(bool)

    merged["is_missing_timestamp"] = merged["document_id"].isna() if "document_id" in merged.columns else merged["price_eur_per_mwh"].isna()
    merged["is_missing_target_value"] = (~merged["is_missing_timestamp"]) & merged["price_eur_per_mwh"].isna()
    merged["is_missing_observation"] = merged["price_eur_per_mwh"].isna()
    observed_target_mask = ~merged["is_missing_observation"]
    observed_target_mask &= ~merged["is_interpolated_value"]
    observed_target_mask &= ~merged["is_flagged_missing_value"]
    merged["is_observed_target"] = observed_target_mask

    local_ts = merged["timestamp_utc"].dt.tz_convert(config.business_timezone)
    merged["target_timestamp_local"] = local_ts
    merged["delivery_local_date"] = local_ts.dt.date
    merged["hour_of_day"] = local_ts.dt.hour.astype(int)
    merged["local_minute"] = local_ts.dt.minute.astype(int)
    merged["quarter_in_hour"] = (local_ts.dt.minute // 15 + 1).astype(int)
    merged["quarter_of_day"] = merged.groupby("delivery_local_date", dropna=False).cumcount() + 1
    merged["hour_start_utc"] = merged["timestamp_utc"].dt.floor("h")
    merged["hour_start_local"] = merged["hour_start_utc"].dt.tz_convert(config.business_timezone)
    merged["known_at_utc"] = [
        known_at_utc_for_delivery_date(value, _build_hourly_market_config(config))
        for value in merged["delivery_local_date"].tolist()
    ]

    feature_source, feature_methods = _quarterhour_feature_source_from_causal_imputation(merged["price_eur_per_mwh"])
    merged["price_feature_source_eur_per_mwh"] = feature_source.to_numpy(dtype=float)
    merged["feature_source_imputation_method"] = feature_methods.astype(str)
    merged["is_imputed_feature_source"] = merged["is_missing_observation"] & merged["price_feature_source_eur_per_mwh"].notna()

    hourly_summary = (
        merged.groupby("hour_start_utc", as_index=False)
        .agg(
            delivery_local_date=("delivery_local_date", "first"),
            hour_of_day=("hour_of_day", "first"),
            observed_quarter_count=("is_observed_target", "sum"),
            raw_quarter_count=("timestamp_utc", "size"),
            missing_quarter_count=("is_missing_observation", "sum"),
            interpolated_quarter_count=("is_interpolated_value", "sum"),
            flagged_missing_quarter_count=("is_flagged_missing_value", "sum"),
            observed_hourly_mean_eur_per_mwh=("price_eur_per_mwh", lambda s: float(pd.to_numeric(s, errors="coerce").mean()) if s.notna().any() else np.nan),
        )
        .sort_values("hour_start_utc")
        .reset_index(drop=True)
    )
    hourly_summary["is_full_observed_hour"] = hourly_summary["observed_quarter_count"].eq(4)
    hourly_summary["is_full_raw_hour"] = hourly_summary["raw_quarter_count"].eq(4)

    source_summary = {
        "authoritative_quarterhour_path": str(source_path),
        "phase01_run_dir": authority.get("phase01_run_dir"),
        "companion_quarterhour_path": str(authority.get("companion_quarterhour_path")),
        "canonical_row_count": int(merged.shape[0]),
        "observed_target_count": int(merged["is_observed_target"].sum()),
        "excluded_non_observed_target_count": int((~merged["is_observed_target"]).sum()),
        "interpolated_point_count": int(merged["is_interpolated_value"].sum()),
        "flagged_missing_point_count": int(merged["is_flagged_missing_value"].sum()),
        "start_timestamp_utc": str(merged["timestamp_utc"].min()),
        "end_timestamp_utc": str(merged["timestamp_utc"].max()),
        "start_delivery_local_date": str(min(merged["delivery_local_date"])),
        "end_delivery_local_date": str(max(merged["delivery_local_date"])),
    }
    return merged, hourly_summary, source_summary


def _origin_target_count_status(actual_target_count: int) -> str:
    if actual_target_count == EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN:
        return "normal_480"
    if actual_target_count < EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN:
        return f"dst_short_{actual_target_count}"
    return f"dst_long_{actual_target_count}"


def _origin_availability_status(observed_target_count: int, actual_target_count: int) -> str:
    if observed_target_count <= 0:
        return "no_observed_targets"
    if observed_target_count == actual_target_count:
        return "full_observed"
    coverage_pct = float(observed_target_count / actual_target_count * 100.0) if actual_target_count else 0.0
    if coverage_pct < 25.0:
        return "low_observed_coverage"
    return "partial_observed"


def build_quarterhour_target_schedule_for_origin(
    config: QuarterHourDAExtensionConfig,
    *,
    delivery_start_local_date: date,
    split_name: str,
    forecast_origin_utc: pd.Timestamp,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    horizon_index = 1
    for lead_day in range(5):
        target_local_date = delivery_start_local_date + timedelta(days=lead_day)
        start_utc, end_utc_exclusive = local_date_to_utc_bounds(target_local_date, config.business_timezone)
        target_known_at = known_at_utc_for_delivery_date(target_local_date, _build_hourly_market_config(config))
        target_index = pd.date_range(start=start_utc, end=end_utc_exclusive, freq="15min", inclusive="left", tz="UTC")
        for lead_quarter_index, target_timestamp_utc in enumerate(target_index, start=1):
            target_local = target_timestamp_utc.tz_convert(config.business_timezone)
            rows.append(
                {
                    "dataset_split": str(split_name),
                    "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                    "forecast_origin_local": pd.Timestamp(forecast_origin_utc).tz_convert(config.business_timezone),
                    "delivery_start_local_date": delivery_start_local_date,
                    "target_timestamp_utc": target_timestamp_utc,
                    "target_timestamp_local": target_local,
                    "target_date_local": target_local_date,
                    "target_known_at_utc": target_known_at,
                    "lead_day": int(lead_day),
                    "lead_day_label": "D" if lead_day == 0 else f"D+{lead_day}",
                    "horizon_index": int(horizon_index),
                    "lead_quarter_index": int(lead_quarter_index),
                    "quarter_of_day": int(lead_quarter_index),
                    "hour_of_day": int(target_local.hour),
                    "quarter_in_hour": int(target_local.minute // 15 + 1),
                }
            )
            horizon_index += 1
    return pd.DataFrame(rows)


def _standard_split_windows(
    eligible_origins: pd.DataFrame,
) -> tuple[list[SplitWindow], str]:
    sorted_origins = eligible_origins.sort_values("forecast_origin_utc").reset_index(drop=True)
    n_origins = int(sorted_origins.shape[0])
    train_count = max(int(np.floor(n_origins * 0.60)), 1)
    validation_count = max(int(np.floor(n_origins * 0.20)), 1)
    test_count = n_origins - train_count - validation_count
    if test_count <= 0:
        test_count = 1
        train_count = max(train_count - 1, 1)

    if (
        train_count >= MIN_TRAIN_ORIGINS_PREFERRED
        and validation_count >= MIN_VALIDATION_ORIGINS_PREFERRED
        and test_count >= MIN_TEST_ORIGINS_PREFERRED
    ):
        train_start = pd.Timestamp(sorted_origins.iloc[0]["delivery_start_local_date"]).date()
        train_end = pd.Timestamp(sorted_origins.iloc[train_count - 1]["delivery_start_local_date"]).date()
        validation_start = pd.Timestamp(sorted_origins.iloc[train_count]["delivery_start_local_date"]).date()
        validation_end = pd.Timestamp(sorted_origins.iloc[train_count + validation_count - 1]["delivery_start_local_date"]).date()
        test_start = pd.Timestamp(sorted_origins.iloc[train_count + validation_count]["delivery_start_local_date"]).date()
        test_end = pd.Timestamp(sorted_origins.iloc[-1]["delivery_start_local_date"]).date()
        return (
            [
                SplitWindow("train", train_start, train_end, "First 60% of eligible origins by origin timestamp."),
                SplitWindow("validation", validation_start, validation_end, "Next 20% of eligible origins by origin timestamp."),
                SplitWindow("test", test_start, test_end, "Final 20% of eligible origins by origin timestamp."),
            ],
            "standard_origin_ratio_60_20_20",
        )

    if n_origins >= (MIN_TRAIN_ORIGINS_PREFERRED + MIN_VALIDATION_ORIGINS_PREFERRED + MIN_TEST_ORIGINS_PREFERRED):
        train_count = n_origins - (MIN_VALIDATION_ORIGINS_PREFERRED + MIN_TEST_ORIGINS_PREFERRED)
        validation_count = MIN_VALIDATION_ORIGINS_PREFERRED
        test_count = MIN_TEST_ORIGINS_PREFERRED
        train_start = pd.Timestamp(sorted_origins.iloc[0]["delivery_start_local_date"]).date()
        train_end = pd.Timestamp(sorted_origins.iloc[train_count - 1]["delivery_start_local_date"]).date()
        validation_start = pd.Timestamp(sorted_origins.iloc[train_count]["delivery_start_local_date"]).date()
        validation_end = pd.Timestamp(sorted_origins.iloc[train_count + validation_count - 1]["delivery_start_local_date"]).date()
        test_start = pd.Timestamp(sorted_origins.iloc[train_count + validation_count]["delivery_start_local_date"]).date()
        test_end = pd.Timestamp(sorted_origins.iloc[train_count + validation_count + test_count - 1]["delivery_start_local_date"]).date()
        return (
            [
                SplitWindow("train", train_start, train_end, "Limited-sample fallback train window."),
                SplitWindow("validation", validation_start, validation_end, "Fixed minimum validation holdout."),
                SplitWindow("test", test_start, test_end, "Fixed minimum test holdout."),
            ],
            "limited_sample_fixed_min_holdout",
        )

    if n_origins >= (MIN_TRAIN_ORIGINS_PREFERRED + MIN_TEST_ORIGINS_PREFERRED):
        train_count = n_origins - MIN_TEST_ORIGINS_PREFERRED
        train_start = pd.Timestamp(sorted_origins.iloc[0]["delivery_start_local_date"]).date()
        train_end = pd.Timestamp(sorted_origins.iloc[train_count - 1]["delivery_start_local_date"]).date()
        test_start = pd.Timestamp(sorted_origins.iloc[train_count]["delivery_start_local_date"]).date()
        test_end = pd.Timestamp(sorted_origins.iloc[-1]["delivery_start_local_date"]).date()
        return (
            [
                SplitWindow("train", train_start, train_end, "Limited-sample train window."),
                SplitWindow("test", test_start, test_end, "Limited-sample holdout test window."),
            ],
            "limited_sample_train_test_only",
        )

    return (
        [
            SplitWindow(
                "smoke_only",
                pd.Timestamp(sorted_origins.iloc[0]["delivery_start_local_date"]).date(),
                pd.Timestamp(sorted_origins.iloc[-1]["delivery_start_local_date"]).date(),
                "Observed 15-minute period is too short for defensible model comparison. Benchmarks and smoke checks only.",
            )
        ],
        "smoke_only_insufficient_origins",
    )


def build_origin_schedule_and_split_policy(
    canonical_frame: pd.DataFrame,
    config: QuarterHourDAExtensionConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    config = config or QuarterHourDAExtensionConfig()
    observed_start = pd.Timestamp(min(canonical_frame["delivery_local_date"])).date()
    observed_end = pd.Timestamp(max(canonical_frame["delivery_local_date"])).date()
    earliest_delivery_start = observed_start - timedelta(days=4)
    delivery_start_dates = pd.date_range(start=earliest_delivery_start, end=observed_end, freq="D")

    target_lookup = canonical_frame[
        [
            "timestamp_utc",
            "price_eur_per_mwh",
            "is_observed_target",
            "gap_fix_action",
            "is_interpolated_value",
            "is_flagged_missing_value",
        ]
    ].rename(columns={"timestamp_utc": "target_timestamp_utc"})

    origin_rows: list[dict[str, Any]] = []
    target_frames: list[pd.DataFrame] = []
    for delivery_start_ts in delivery_start_dates:
        delivery_start_local_date = delivery_start_ts.date()
        origin_local = localize_naive_timestamp(
            datetime.combine(delivery_start_local_date - timedelta(days=1), dt_time(hour=8, minute=0)),
            config.business_timezone,
        )
        target_frame = build_quarterhour_target_schedule_for_origin(
            config,
            delivery_start_local_date=delivery_start_local_date,
            split_name="unassigned",
            forecast_origin_utc=origin_local.tz_convert("UTC"),
        ).merge(target_lookup, on="target_timestamp_utc", how="left")
        actual_target_count = int(target_frame.shape[0])
        observed_target_count = int(target_frame["is_observed_target"].astype("boolean").fillna(False).astype(bool).sum())
        if observed_target_count <= 0:
            continue
        coverage_pct = float(observed_target_count / actual_target_count * 100.0) if actual_target_count else 0.0
        origin_rows.append(
            {
                "delivery_start_local_date": delivery_start_local_date,
                "forecast_origin_local": origin_local.isoformat(),
                "forecast_origin_utc": origin_local.tz_convert("UTC").isoformat(),
                "expected_normal_target_count_per_origin": EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN,
                "actual_target_count_per_origin": actual_target_count,
                "observed_target_count_per_origin": observed_target_count,
                "observed_target_coverage_pct": coverage_pct,
                "target_count_status": _origin_target_count_status(actual_target_count),
                "availability_status": _origin_availability_status(observed_target_count, actual_target_count),
            }
        )
        target_frames.append(target_frame.assign(delivery_start_local_date=delivery_start_local_date))

    if not origin_rows:
        raise ValueError("No eligible quarter-hour origins overlapped the observed 15-minute target period.")

    origins = pd.DataFrame(origin_rows).sort_values("forecast_origin_utc").reset_index(drop=True)
    split_windows, split_policy = _standard_split_windows(origins)

    def _resolve_split(local_date: date) -> str:
        for window in split_windows:
            if window.start_delivery_local_date <= local_date <= window.end_delivery_local_date:
                return window.split
        return "outside_defined_window"

    origins["dataset_split"] = origins["delivery_start_local_date"].map(_resolve_split)
    origins["split_policy"] = split_policy
    origins = origins[_build_required_origin_columns()].copy()

    target_template = pd.concat(target_frames, ignore_index=True) if target_frames else pd.DataFrame()
    drop_conflicting = [
        column
        for column in ["dataset_split", "forecast_origin_utc", "forecast_origin_local"]
        if column in target_template.columns
    ]
    if drop_conflicting:
        target_template = target_template.drop(columns=drop_conflicting)
    target_template = target_template.merge(
        origins[
            [
                "delivery_start_local_date",
                "dataset_split",
                "forecast_origin_utc",
                "forecast_origin_local",
                "expected_normal_target_count_per_origin",
                "actual_target_count_per_origin",
                "observed_target_count_per_origin",
                "observed_target_coverage_pct",
                "target_count_status",
                "availability_status",
            ]
        ],
        on="delivery_start_local_date",
        how="inner",
    )
    target_template["forecast_origin_utc"] = pd.to_datetime(target_template["forecast_origin_utc"], utc=True, errors="coerce")
    target_template["forecast_origin_local"] = pd.to_datetime(target_template["forecast_origin_local"], utc=True, errors="coerce")
    target_template["target_timestamp_utc"] = pd.to_datetime(target_template["target_timestamp_utc"], utc=True, errors="coerce")
    target_template["target_timestamp_local"] = pd.to_datetime(target_template["target_timestamp_local"], utc=True, errors="coerce")
    target_template["is_observed_target"] = target_template["is_observed_target"].fillna(False).astype(bool)
    target_template["y_true"] = pd.to_numeric(target_template["price_eur_per_mwh"], errors="coerce").where(target_template["is_observed_target"])
    target_template = target_template.sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)

    split_summary_rows: list[dict[str, Any]] = []
    for window in split_windows:
        split_origins = origins[origins["dataset_split"].astype(str) == str(window.split)].copy()
        split_targets = target_template[target_template["dataset_split"].astype(str) == str(window.split)].copy()
        split_summary_rows.append(
            {
                "dataset_split": window.split,
                "split_policy": split_policy,
                "start_delivery_local_date": window.start_delivery_local_date.isoformat(),
                "end_delivery_local_date": window.end_delivery_local_date.isoformat(),
                "notes": window.notes,
                "origin_count": int(split_origins.shape[0]),
                "target_row_count": int(split_targets.shape[0]),
                "observed_target_row_count": int(split_targets["is_observed_target"].sum()),
                "mean_observed_target_coverage_pct": float(split_origins["observed_target_coverage_pct"].mean()) if not split_origins.empty else np.nan,
            }
        )
    split_summary = pd.DataFrame(split_summary_rows)
    split_metadata = {
        "split_policy": split_policy,
        "observed_start_delivery_local_date": observed_start.isoformat(),
        "observed_end_delivery_local_date": observed_end.isoformat(),
        "eligible_origin_count": int(origins.shape[0]),
        "split_dates": {
            row["dataset_split"]: {
                "start_delivery_local_date": row["start_delivery_local_date"],
                "end_delivery_local_date": row["end_delivery_local_date"],
            }
            for row in split_summary.to_dict(orient="records")
        },
        "split_origin_counts": {
            row["dataset_split"]: int(row["origin_count"])
            for row in split_summary.to_dict(orient="records")
        },
        "split_observed_target_counts": {
            row["dataset_split"]: int(row["observed_target_row_count"])
            for row in split_summary.to_dict(orient="records")
        },
    }
    return origins, target_template, split_summary, split_metadata


def _build_hourly_bridge_from_quarterhour(
    canonical_quarterhour_frame: pd.DataFrame,
    *,
    config: QuarterHourDAExtensionConfig,
    run_dir: Path,
) -> tuple[Path, pd.DataFrame]:
    pre_cutoff_hourly = pd.read_csv(config.shared_hourly_csv)
    pre_cutoff_hourly = pre_cutoff_hourly[pre_cutoff_hourly["region"].astype(str) == str(config.market_area)].copy()
    pre_cutoff_hourly["timestamp_utc"] = pd.to_datetime(pre_cutoff_hourly["timestamp_utc"], utc=True, errors="coerce")
    pre_cutoff_hourly["price_eur_per_mwh"] = pd.to_numeric(pre_cutoff_hourly["price_eur_per_mwh"], errors="coerce")
    pre_cutoff_hourly["is_interpolated_value"] = pre_cutoff_hourly.get("is_interpolated_value", False)
    pre_cutoff_hourly["is_flagged_missing_value"] = pre_cutoff_hourly.get("is_flagged_missing_value", False)
    pre_cutoff_hourly["gap_fix_action"] = pre_cutoff_hourly.get("gap_fix_action", "observed")
    pre_cutoff_hourly["missing_datapoint_source"] = pre_cutoff_hourly.get("missing_datapoint_source", "observed")

    grouped = canonical_quarterhour_frame.groupby("hour_start_utc", as_index=False).agg(
        region=("region", "first"),
        price_eur_per_mwh=("price_eur_per_mwh", lambda s: float(pd.to_numeric(s, errors="coerce").mean()) if s.notna().any() else np.nan),
        quarter_count=("timestamp_utc", "size"),
        observed_quarter_count=("is_observed_target", "sum"),
        interpolated_quarter_count=("is_interpolated_value", "sum"),
        flagged_missing_quarter_count=("is_flagged_missing_value", "sum"),
        missing_quarter_count=("is_missing_observation", "sum"),
    )
    derived_post_cutoff = grouped.rename(columns={"hour_start_utc": "timestamp_utc"}).copy()
    derived_post_cutoff["resolution"] = "PT60M"
    derived_post_cutoff["resolution_minutes"] = 60
    derived_post_cutoff["gap_fix_action"] = np.where(
        derived_post_cutoff["observed_quarter_count"].eq(4),
        "observed_hourly_from_observed_15min",
        "derived_hourly_from_partial_or_nonobserved_15min",
    )
    derived_post_cutoff["is_interpolated_value"] = (
        derived_post_cutoff["observed_quarter_count"].ne(4)
        | derived_post_cutoff["interpolated_quarter_count"].gt(0)
    )
    derived_post_cutoff["is_flagged_missing_value"] = (
        derived_post_cutoff["flagged_missing_quarter_count"].gt(0)
        | derived_post_cutoff["missing_quarter_count"].gt(0)
    )
    derived_post_cutoff["missing_datapoint_source"] = np.where(
        derived_post_cutoff["observed_quarter_count"].eq(4),
        "observed_15min_complete_hour",
        "derived_from_partial_15min_hour",
    )

    bridge_frame = pd.concat(
        [
            pre_cutoff_hourly[
                [
                    "timestamp_utc",
                    "region",
                    "price_eur_per_mwh",
                    "resolution",
                    "resolution_minutes",
                    "gap_fix_action",
                    "is_interpolated_value",
                    "is_flagged_missing_value",
                    "missing_datapoint_source",
                ]
            ].copy(),
            derived_post_cutoff[
                [
                    "timestamp_utc",
                    "region",
                    "price_eur_per_mwh",
                    "resolution",
                    "resolution_minutes",
                    "gap_fix_action",
                    "is_interpolated_value",
                    "is_flagged_missing_value",
                    "missing_datapoint_source",
                ]
            ].copy(),
        ],
        ignore_index=True,
    )
    bridge_frame["timestamp_utc"] = pd.to_datetime(bridge_frame["timestamp_utc"], utc=True, errors="coerce")
    bridge_frame = (
        bridge_frame.sort_values(["timestamp_utc", "region"])
        .drop_duplicates(subset=["timestamp_utc", "region"], keep="last")
        .reset_index(drop=True)
    )
    bridge_csv = run_dir / "hourly_backbone_bridge_input.csv"
    bridge_frame.to_csv(bridge_csv, index=False)

    bridge_summary = pd.DataFrame(
        [
            {
                "dataset": "pre_cutoff_hourly_market",
                "start_timestamp_utc": pre_cutoff_hourly["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": pre_cutoff_hourly["timestamp_utc"].max().isoformat(),
                "rows": int(pre_cutoff_hourly.shape[0]),
                "notes": "Canonical cleaned hourly NL DA series before the quarter-hour transition.",
            },
            {
                "dataset": "post_cutoff_hourly_bridge_from_15min",
                "start_timestamp_utc": derived_post_cutoff["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": derived_post_cutoff["timestamp_utc"].max().isoformat(),
                "rows": int(derived_post_cutoff.shape[0]),
                "fully_observed_hours": int(derived_post_cutoff["observed_quarter_count"].eq(4).sum()),
                "non_observed_hours": int(derived_post_cutoff["observed_quarter_count"].ne(4).sum()),
                "notes": "Observed hourly means derived from quarter-hour rows; non-fully-observed hours stay flagged as non-observed truth.",
            },
            {
                "dataset": "combined_hourly_bridge_input",
                "start_timestamp_utc": bridge_frame["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": bridge_frame["timestamp_utc"].max().isoformat(),
                "rows": int(bridge_frame.shape[0]),
                "notes": "Bridge input used to extend the audited hourly deterministic forecast framework through the observed 15-minute period.",
            },
        ]
    )
    return bridge_csv, bridge_summary


def _build_hourly_extension_config(
    config: QuarterHourDAExtensionConfig,
    *,
    bridge_csv: Path,
    split_summary: pd.DataFrame,
) -> HourlyDAPipelineConfig:
    split_lookup = {str(row["dataset_split"]): row for row in split_summary.to_dict(orient="records")}
    return HourlyDAPipelineConfig(
        input_csv=bridge_csv,
        market_area=config.market_area,
        business_timezone=config.business_timezone,
        train_start_local=pd.Timestamp(split_lookup["train"]["start_delivery_local_date"]).date() if "train" in split_lookup else date(2025, 10, 1),
        train_end_local=pd.Timestamp(split_lookup["train"]["end_delivery_local_date"]).date() if "train" in split_lookup else date(2025, 12, 31),
        validation_start_local=pd.Timestamp(split_lookup.get("validation", split_lookup["train"])["start_delivery_local_date"]).date(),
        validation_end_local=pd.Timestamp(split_lookup.get("validation", split_lookup["train"])["end_delivery_local_date"]).date(),
        test_start_local=pd.Timestamp(split_lookup.get("test", split_lookup["train"])["start_delivery_local_date"]).date(),
        test_end_local=pd.Timestamp(split_lookup.get("test", split_lookup["train"])["end_delivery_local_date"]).date(),
        output_root=config.hourly_da_output_root,
    )


def _candidate_metric_row(run_dir: Path, *, model_name: str) -> dict[str, Any] | None:
    metrics = load_csv(run_dir, "metrics_by_reporting_level.csv")
    target = metrics[
        (metrics["model"].astype(str) == str(model_name))
        & (metrics["dataset_split"].astype(str) == "validation")
        & (metrics["reporting_level"].astype(str) == "stitched_all_horizon")
    ].copy()
    if target.empty:
        return None
    row = target.iloc[0].to_dict()
    return {
        "validation_mae": float(row["mae"]),
        "validation_rmse": float(row["rmse"]),
        "validation_bias": float(row["bias"]),
        "validation_rmae": float(row.get("rmae") if pd.notna(row.get("rmae")) else row.get("rmae_vs_official_naive")),
        "validation_coverage_pct": float(row["coverage_pct"]),
        "validation_reporting_level": str(row["reporting_level"]),
    }


def _build_hourly_backbone_candidate_table(
    config: QuarterHourDAExtensionConfig,
    *,
    hourly_config: HourlyDAPipelineConfig,
    target_template: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    discovery = discover_final_candidate_runs(config.hourly_da_output_root)
    candidate_frame = discovery["candidates"].copy()
    candidate_frame = candidate_frame[
        candidate_frame["prediction_available"].fillna(False).astype(bool)
        & ~candidate_frame["candidate_key"].astype(str).eq("official_naive_benchmark")
        & ~candidate_frame["model_family"].astype(str).eq("naive")
    ].copy()
    if candidate_frame.empty:
        raise FileNotFoundError("No complete hourly backbone candidates were available for observed 15-minute extension.")

    store = load_external_feature_store(hourly_config)
    values = store.values.copy()
    values["timestamp_utc"] = pd.to_datetime(values["timestamp_utc"], utc=True, errors="coerce")
    split_target_end_dates = {
        split_name: pd.Timestamp(group["target_date_local"].max()).date()
        for split_name, group in target_template.groupby("dataset_split", dropna=False)
        if str(split_name) in {"train", "validation", "test"}
    }

    rows: list[dict[str, Any]] = []
    for row in candidate_frame.to_dict(orient="records"):
        run_dir = Path(str(row["selected_run_dir"]))
        metric_row = _candidate_metric_row(run_dir, model_name=str(row["selected_model"]))
        if metric_row is None:
            continue
        selected_meta = pd.DataFrame(
            [
                {
                    "candidate_key": str(row["candidate_key"]),
                    "candidate_label": str(row["candidate_label"]),
                    "role": "hourly_backbone_candidate",
                    "role_description": "validation_full_horizon_candidate",
                    "source_run_dir": str(row["selected_run_dir"]),
                    "source_run_id": str(row["selected_run_id"]),
                    "source_run_label": str(row["run_label"]),
                    "model_family": str(row["model_family"]),
                    "fs_level": str(row["fs_level"]),
                    "internal_model_name": str(row["selected_model"]),
                    "selected_run_dir": str(row["selected_run_dir"]),
                }
            ]
        )
        payload = _load_selected_model_payload(selected_meta.iloc[0].to_dict())
        settings_payload = payload["settings_payload"]
        direct_columns = tuple(str(value) for value in dict(settings_payload.get("fs3_experiment") or {}).get("direct_columns", ()) or ())
        missing_direct_columns = [column for column in direct_columns if column not in values.columns]
        direct_max_local_dates: list[date] = []
        for column in direct_columns:
            if column not in values.columns:
                continue
            observed = values.loc[values[column].notna(), "timestamp_utc"]
            if observed.empty:
                continue
            direct_max_local_dates.append(pd.Timestamp(observed.max()).tz_convert(config.business_timezone).date())
        has_direct_dependencies = bool(direct_columns)
        feasible_end_local_date = min(direct_max_local_dates) if direct_max_local_dates else None
        if not has_direct_dependencies:
            covers_validation = True
            covers_test = True
        else:
            covers_validation = bool(
                "validation" not in split_target_end_dates
                or (feasible_end_local_date is not None and feasible_end_local_date >= split_target_end_dates["validation"])
            )
            covers_test = bool(
                "test" not in split_target_end_dates
                or (feasible_end_local_date is not None and feasible_end_local_date >= split_target_end_dates["test"])
            )
        rows.append(
            {
                "candidate_key": str(row["candidate_key"]),
                "candidate_label": str(row["candidate_label"]),
                "model_family": str(row["model_family"]),
                "fs_level": str(row["fs_level"]),
                "selected_run_id": str(row["selected_run_id"]),
                "selected_run_dir": str(row["selected_run_dir"]),
                "selected_model": str(row["selected_model"]),
                "has_direct_dependencies": bool(has_direct_dependencies),
                "direct_feature_count": int(len(direct_columns)),
                "missing_direct_columns_count": int(len(missing_direct_columns)),
                "missing_direct_columns": ",".join(missing_direct_columns),
                "feasible_end_local_date": feasible_end_local_date.isoformat() if feasible_end_local_date is not None else None,
                "covers_validation": bool(covers_validation),
                "covers_test": bool(covers_test),
                **metric_row,
            }
        )
    candidate_scores = pd.DataFrame(rows)
    if candidate_scores.empty:
        raise ValueError("No hourly backbone candidate rows survived metric and feasibility extraction.")
    candidate_scores["feasible_for_observed_extension"] = (
        candidate_scores["missing_direct_columns_count"].eq(0)
        & candidate_scores["covers_validation"].astype(bool)
        & candidate_scores["covers_test"].astype(bool)
    )
    candidate_scores = candidate_scores.sort_values(
        [
            "feasible_for_observed_extension",
            "validation_coverage_pct",
            "validation_rmae",
            "validation_mae",
            "candidate_label",
        ],
        ascending=[False, False, True, True, True],
    ).reset_index(drop=True)
    selected = candidate_scores[candidate_scores["feasible_for_observed_extension"]].copy()
    selection_summary = pd.DataFrame(
        [
            {
                "selection_rule": (
                    "Validation-only stitched-all-horizon hourly backbone selection from the fixed final-candidate set, "
                    "with feasibility for the observed 15-minute extension required before selection."
                ),
                "candidate_count_scored": int(candidate_scores.shape[0]),
                "feasible_candidate_count": int(selected.shape[0]),
                "selected_candidate_key": str(selected.iloc[0]["candidate_key"]) if not selected.empty else None,
                "selected_run_id": str(selected.iloc[0]["selected_run_id"]) if not selected.empty else None,
                "selected_model": str(selected.iloc[0]["selected_model"]) if not selected.empty else None,
            }
        ]
    )
    return candidate_scores, selection_summary


def _build_hourly_extension_target_schedule(
    delivery_start_local_date: date,
    *,
    split_name: str,
    forecast_origin_utc: pd.Timestamp,
    hourly_config: HourlyDAPipelineConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    horizon_index = 1
    timezone = hourly_config.resolved_business_timezone()
    for lead_day in range(hourly_config.forecast_horizon_days):
        target_local_date = delivery_start_local_date + timedelta(days=lead_day)
        start_utc, end_utc_exclusive = local_date_to_utc_bounds(target_local_date, timezone)
        target_known_at = known_at_utc_for_delivery_date(target_local_date, hourly_config)
        target_index = pd.date_range(start=start_utc, end=end_utc_exclusive, freq="h", inclusive="left", tz="UTC")
        for target_timestamp_utc in target_index:
            target_local = target_timestamp_utc.tz_convert(timezone)
            rows.append(
                {
                    "dataset_split": str(split_name),
                    "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                    "delivery_start_local_date": delivery_start_local_date,
                    "target_timestamp_utc": target_timestamp_utc,
                    "target_delivery_local_date": target_local_date,
                    "target_hour_local": int(target_local.hour),
                    "target_known_at_utc": target_known_at,
                    "lead_day": int(lead_day),
                    "lead_day_label": "D" if lead_day == 0 else f"D+{lead_day}",
                    "horizon_index": int(horizon_index),
                }
            )
            horizon_index += 1
    return pd.DataFrame(rows)


def _run_hourly_backbone_extension(
    *,
    config: QuarterHourDAExtensionConfig,
    hourly_config: HourlyDAPipelineConfig,
    canonical_hourly_frame: pd.DataFrame,
    origins: pd.DataFrame,
    selected_candidate_row: dict[str, Any],
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    payload = _load_selected_model_payload(
        {
            "candidate_key": str(selected_candidate_row["candidate_key"]),
            "candidate_label": str(selected_candidate_row["candidate_label"]),
            "source_run_id": str(selected_candidate_row["selected_run_id"]),
            "source_run_label": str(selected_candidate_row["selected_run_id"]),
            "source_run_dir": str(selected_candidate_row["selected_run_dir"]),
            "model_family": str(selected_candidate_row["model_family"]),
            "fs_level": str(selected_candidate_row["fs_level"]),
        }
    )
    parent_like = SimpleNamespace(
        settings_payload=payload["settings_payload"],
        fs_level=payload["fs_level"],
        model_family=payload["model_family"],
        model_name=payload["model_name"],
    )
    model = instantiate_model_from_parent_context(parent_like, name_override=str(payload["model_name"]))
    external_feature_store = load_external_feature_store(hourly_config)
    target_lookup = canonical_hourly_frame[
        [hourly_config.timestamp_col, hourly_config.target_col, "is_observed_target"]
    ].rename(columns={hourly_config.timestamp_col: "target_timestamp_utc"})

    prediction_frames: list[pd.DataFrame] = []
    timing_rows: list[dict[str, Any]] = []
    for origin_row in origins.to_dict(orient="records"):
        split_name = str(origin_row["dataset_split"])
        delivery_start_local_date = pd.Timestamp(origin_row["delivery_start_local_date"]).date()
        forecast_origin_utc = pd.Timestamp(origin_row["forecast_origin_utc"])
        history = canonical_hourly_frame[canonical_hourly_frame[hourly_config.known_at_col] <= forecast_origin_utc].copy()
        if history.empty:
            continue
        target_schedule = _build_hourly_extension_target_schedule(
            delivery_start_local_date,
            split_name=split_name,
            forecast_origin_utc=forecast_origin_utc,
            hourly_config=hourly_config,
        )
        target_frame = target_schedule.merge(target_lookup, on="target_timestamp_utc", how="left")
        target_index = pd.DatetimeIndex(target_frame["target_timestamp_utc"])
        feature_context = build_feature_context_for_origin(external_feature_store, forecast_origin_utc)

        fit_started = time.perf_counter()
        model.fit(history=history, target_index_utc=target_index, config=hourly_config, feature_context=feature_context)
        fit_time_sec = time.perf_counter() - fit_started
        predict_started = time.perf_counter()
        preds = model.predict(history=history, target_index_utc=target_index, config=hourly_config, feature_context=feature_context)
        predict_time_sec = time.perf_counter() - predict_started
        if not preds.index.equals(target_index):
            preds = preds.reindex(target_index)
        runtime_info = model.get_last_runtime_info()
        timing_rows.append(
            {
                "run_id": run_id,
                "model_scope": "hourly_backbone_extension",
                "model": str(model.name),
                "model_family": str(model.family),
                "fs_level": str(model.fs_level),
                "dataset_split": split_name,
                "forecast_origin_utc": forecast_origin_utc.isoformat(),
                "fit_time_sec": fit_time_sec,
                "predict_time_sec": predict_time_sec,
                "runtime_info_json": json.dumps(runtime_info, sort_keys=True, default=str),
            }
        )

        frame = target_frame.copy()
        frame["run_id"] = run_id
        frame["candidate_key"] = str(selected_candidate_row["candidate_key"])
        frame["candidate_label"] = str(selected_candidate_row["candidate_label"])
        frame["source_run_id"] = str(selected_candidate_row["selected_run_id"])
        frame["source_run_dir"] = str(selected_candidate_row["selected_run_dir"])
        frame["model"] = str(model.name)
        frame["model_family"] = str(model.family)
        frame["fs_level"] = str(model.fs_level)
        frame["y_true"] = pd.to_numeric(frame[hourly_config.target_col], errors="coerce").where(
            frame["is_observed_target"].fillna(False).astype(bool)
        )
        frame["y_pred"] = preds.to_numpy(dtype=float)
        frame["fit_time_sec"] = fit_time_sec
        frame["predict_time_sec"] = predict_time_sec
        prediction_frames.append(frame)

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        .sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
        if prediction_frames
        else pd.DataFrame()
    )
    timing = pd.DataFrame(timing_rows).sort_values(["dataset_split", "forecast_origin_utc"]).reset_index(drop=True) if timing_rows else pd.DataFrame()
    return predictions, timing


def _build_observed_hourly_training_table(
    canonical_quarterhour_frame: pd.DataFrame,
) -> pd.DataFrame:
    observed_rows = canonical_quarterhour_frame[canonical_quarterhour_frame["is_observed_target"].fillna(False).astype(bool)].copy()
    hour_table = (
        observed_rows.groupby("hour_start_utc", as_index=False)
        .agg(
            delivery_local_date=("delivery_local_date", "first"),
            local_hour_of_day=("hour_of_day", "first"),
            observed_quarter_count=("timestamp_utc", "size"),
            hourly_anchor_price_eur_per_mwh=("price_eur_per_mwh", "mean"),
            known_at_utc=("known_at_utc", "first"),
        )
        .sort_values("hour_start_utc")
        .reset_index(drop=True)
    )
    hour_table = hour_table[hour_table["observed_quarter_count"].eq(4)].copy()
    if hour_table.empty:
        return pd.DataFrame()
    hour_table["hour_start_local"] = pd.to_datetime(hour_table["hour_start_utc"], utc=True).dt.tz_convert("Europe/Amsterdam")
    hour_table["weekday"] = hour_table["hour_start_local"].dt.dayofweek.astype(int)
    hour_table["weekend_flag"] = hour_table["weekday"].isin([5, 6]).astype(int)
    hour_table["month"] = hour_table["hour_start_local"].dt.month.astype(int)
    hour_table["season"] = hour_table["month"].map(
        lambda month: "winter" if month in (12, 1, 2) else "spring" if month in (3, 4, 5) else "summer" if month in (6, 7, 8) else "autumn"
    )
    enriched = _enrich_hourly_anchor_frame(hour_table)
    expanded = _expand_hourly_to_quarters(
        enriched,
        source_type="observed_training_hourly_anchor",
        shape_method="observed_hourly_mean",
        scenario_variant="observed_market_training",
    )
    observed = observed_rows[
        [
            "timestamp_utc",
            "target_timestamp_local",
            "delivery_local_date",
            "hour_start_utc",
            "price_eur_per_mwh",
            "quarter_of_day",
            "known_at_utc",
        ]
    ].copy()
    merged = expanded.merge(
        observed,
        on=["timestamp_utc", "hour_start_utc", "delivery_local_date"],
        how="inner",
        suffixes=("_anchor", "_observed"),
    )
    if "known_at_utc_observed" in merged.columns:
        merged["known_at_utc"] = pd.to_datetime(merged["known_at_utc_observed"], utc=True, errors="coerce")
    elif "known_at_utc" in merged.columns:
        merged["known_at_utc"] = pd.to_datetime(merged["known_at_utc"], utc=True, errors="coerce")
    else:
        raise KeyError("Observed hourly training table could not resolve a known_at_utc column after merge.")
    merged["timestamp_local"] = pd.to_datetime(merged["timestamp_local"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
    merged["delta_eur_per_mwh"] = pd.to_numeric(merged["price_eur_per_mwh"], errors="coerce") - pd.to_numeric(
        merged["hourly_anchor_price_eur_per_mwh"], errors="coerce"
    )
    merged["hourly_mean_eur_per_mwh"] = pd.to_numeric(merged["hourly_anchor_price_eur_per_mwh"], errors="coerce")
    return merged.sort_values(["hour_start_utc", "quarter_index"]).reset_index(drop=True)


def _summarize_timing(timing_rows: pd.DataFrame) -> pd.DataFrame:
    if timing_rows.empty:
        return pd.DataFrame()
    return (
        timing_rows.groupby(["model_scope", "model", "model_family", "fs_level", "dataset_split"], as_index=False)
        .agg(
            origins=("forecast_origin_utc", "size"),
            fit_time_mean_sec=("fit_time_sec", "mean"),
            fit_time_median_sec=("fit_time_sec", "median"),
            fit_time_max_sec=("fit_time_sec", "max"),
            predict_time_mean_sec=("predict_time_sec", "mean"),
            predict_time_median_sec=("predict_time_sec", "median"),
        )
        .sort_values(["model_scope", "dataset_split", "model"])
        .reset_index(drop=True)
    )


def _prepare_profile_lookup(canonical_quarterhour_frame: pd.DataFrame) -> tuple[dict[tuple[date, int], dict[str, Any]], pd.DataFrame]:
    lookup_rows = canonical_quarterhour_frame[
        [
            "timestamp_utc",
            "delivery_local_date",
            "quarter_of_day",
            "price_feature_source_eur_per_mwh",
            "known_at_utc",
            "is_observed_target",
        ]
    ].copy()
    lookup_rows["lookup_key"] = list(zip(lookup_rows["delivery_local_date"], lookup_rows["quarter_of_day"]))
    lookup = {
        key: {
            "timestamp_utc": pd.Timestamp(row["timestamp_utc"]),
            "value": float(row["price_feature_source_eur_per_mwh"]) if pd.notna(row["price_feature_source_eur_per_mwh"]) else np.nan,
            "known_at_utc": pd.Timestamp(row["known_at_utc"]),
            "is_observed_target": bool(row["is_observed_target"]),
        }
        for key, row in zip(lookup_rows["lookup_key"], lookup_rows.to_dict(orient="records"), strict=True)
    }
    day_profiles = (
        lookup_rows.groupby("delivery_local_date", as_index=False)
        .agg(
            quarter_count=("quarter_of_day", "size"),
            max_quarter_of_day=("quarter_of_day", "max"),
            non_null_feature_source_count=("price_feature_source_eur_per_mwh", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            day_known_at_utc=("known_at_utc", "first"),
            observed_quarter_count=("is_observed_target", "sum"),
        )
        .sort_values("delivery_local_date")
        .reset_index(drop=True)
    )
    day_profiles["full_profile_available"] = day_profiles["non_null_feature_source_count"].eq(day_profiles["quarter_count"])
    return lookup, day_profiles


def _lookup_profile_value(
    *,
    lookup: dict[tuple[date, int], dict[str, Any]],
    source_day: date,
    quarter_of_day: int,
    forecast_origin_utc: pd.Timestamp,
) -> tuple[float | None, pd.Timestamp | None]:
    record = lookup.get((source_day, int(quarter_of_day)))
    if record is None:
        return None, None
    if pd.Timestamp(record["known_at_utc"]) > pd.Timestamp(forecast_origin_utc):
        return None, None
    value = record["value"]
    if pd.isna(value):
        return None, None
    return float(value), pd.Timestamp(record["timestamp_utc"])


def _build_repeated_hourly_benchmark(
    expanded_hourly: pd.DataFrame,
    target_template: pd.DataFrame,
    *,
    run_id: str,
    backbone_row: dict[str, Any],
) -> pd.DataFrame:
    benchmark = expanded_hourly.copy()
    benchmark["target_timestamp_utc"] = pd.to_datetime(benchmark["timestamp_utc"], utc=True, errors="coerce")
    benchmark = benchmark.merge(
        target_template[
            [
                "forecast_origin_utc",
                "target_timestamp_utc",
                "target_timestamp_local",
                "target_date_local",
                "dataset_split",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "lead_quarter_index",
                "quarter_of_day",
                "hour_of_day",
                "quarter_in_hour",
                "y_true",
                "is_observed_target",
                "expected_normal_target_count_per_origin",
                "actual_target_count_per_origin",
                "observed_target_count_per_origin",
                "target_count_status",
                "availability_status",
            ]
        ],
        on=["forecast_origin_utc", "target_timestamp_utc", "dataset_split"],
        how="inner",
        suffixes=("", "_target"),
    )
    benchmark["run_id"] = run_id
    benchmark["model"] = BENCHMARK_REPEATED_HOURLY
    benchmark["model_family"] = "benchmark"
    benchmark["fs_level"] = "FS0"
    benchmark["y_pred"] = pd.to_numeric(benchmark["hourly_anchor_price_eur_per_mwh"], errors="coerce")
    benchmark["hourly_backbone_run_id"] = str(backbone_row["selected_run_id"])
    benchmark["hourly_backbone_model"] = str(backbone_row["selected_model"])
    benchmark["source_timestamp_utc"] = benchmark["hour_start_utc"]
    benchmark["source_local_date"] = pd.to_datetime(benchmark["delivery_local_date"], errors="coerce").dt.date
    benchmark["fallback_step"] = "repeat_hourly_backbone"
    benchmark["prediction_available"] = benchmark["y_pred"].notna()
    benchmark["unavailable_reason"] = np.where(benchmark["prediction_available"], "", "missing_hourly_backbone_prediction")
    benchmark["fit_time_sec"] = 0.0
    benchmark["predict_time_sec"] = 0.0
    return benchmark


def _build_same_quarter_benchmarks(
    target_template: pd.DataFrame,
    canonical_quarterhour_frame: pd.DataFrame,
    *,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    lookup, day_profiles = _prepare_profile_lookup(canonical_quarterhour_frame)
    day_profile_map = {pd.Timestamp(row["delivery_local_date"]).date(): row for row in day_profiles.to_dict(orient="records")}
    rows_prev_available: list[dict[str, Any]] = []
    rows_prev_week: list[dict[str, Any]] = []
    rows_last_full_day: list[dict[str, Any]] = []

    targets = target_template.sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    for row in targets.to_dict(orient="records"):
        target_day = pd.Timestamp(row["target_date_local"]).date()
        quarter_of_day = int(row["quarter_of_day"])
        forecast_origin_utc = pd.Timestamp(row["forecast_origin_utc"])
        origin_local_day = forecast_origin_utc.tz_convert("Europe/Amsterdam").date()

        base_common = {
            "run_id": run_id,
            "forecast_origin_utc": forecast_origin_utc,
            "forecast_origin_local": pd.Timestamp(row["forecast_origin_local"]),
            "delivery_start_local_date": pd.Timestamp(row["delivery_start_local_date"]).date(),
            "dataset_split": str(row["dataset_split"]),
            "target_timestamp_utc": pd.Timestamp(row["target_timestamp_utc"]),
            "target_timestamp_local": pd.Timestamp(row["target_timestamp_local"]),
            "target_date_local": target_day,
            "lead_day": int(row["lead_day"]),
            "lead_day_label": str(row["lead_day_label"]),
            "horizon_index": int(row["horizon_index"]),
            "lead_quarter_index": int(row["lead_quarter_index"]),
            "quarter_of_day": quarter_of_day,
            "hour_of_day": int(row["hour_of_day"]),
            "quarter_in_hour": int(row["quarter_in_hour"]),
            "y_true": row["y_true"],
            "is_observed_target": bool(row["is_observed_target"]),
            "expected_normal_target_count_per_origin": int(row["expected_normal_target_count_per_origin"]),
            "actual_target_count_per_origin": int(row["actual_target_count_per_origin"]),
            "observed_target_count_per_origin": int(row["observed_target_count_per_origin"]),
            "target_count_status": str(row["target_count_status"]),
            "availability_status": str(row["availability_status"]),
            "fit_time_sec": 0.0,
            "predict_time_sec": 0.0,
        }

        # Previous available same-quarter with frozen fallback order.
        prev_value = None
        prev_ts = None
        prev_source_day = None
        prev_step = ""
        search_day = target_day - timedelta(days=1)
        while search_day >= min(day_profile_map):
            if search_day > origin_local_day:
                search_day -= timedelta(days=1)
                continue
            value, ts_utc = _lookup_profile_value(
                lookup=lookup,
                source_day=search_day,
                quarter_of_day=quarter_of_day,
                forecast_origin_utc=forecast_origin_utc,
            )
            if value is not None:
                prev_value = value
                prev_ts = ts_utc
                prev_source_day = search_day
                prev_step = "previous_local_day" if search_day == (target_day - timedelta(days=1)) else "most_recent_earlier_local_day"
                break
            search_day -= timedelta(days=1)
        if prev_value is None:
            week_source_day = target_day - timedelta(days=7)
            value, ts_utc = _lookup_profile_value(
                lookup=lookup,
                source_day=week_source_day,
                quarter_of_day=quarter_of_day,
                forecast_origin_utc=forecast_origin_utc,
            )
            if value is not None:
                prev_value = value
                prev_ts = ts_utc
                prev_source_day = week_source_day
                prev_step = "previous_week_same_quarter"
        if prev_value is None:
            last_full_candidates = day_profiles[
                day_profiles["full_profile_available"].fillna(False).astype(bool)
                & (pd.to_datetime(day_profiles["delivery_local_date"]).dt.date <= origin_local_day)
            ].copy()
            if not last_full_candidates.empty:
                source_day = pd.Timestamp(last_full_candidates.iloc[-1]["delivery_local_date"]).date()
                value, ts_utc = _lookup_profile_value(
                    lookup=lookup,
                    source_day=source_day,
                    quarter_of_day=quarter_of_day,
                    forecast_origin_utc=forecast_origin_utc,
                )
                if value is not None:
                    prev_value = value
                    prev_ts = ts_utc
                    prev_source_day = source_day
                    prev_step = "last_fully_available_daily_profile"

        rows_prev_available.append(
            {
                **base_common,
                "model": BENCHMARK_PREVIOUS_AVAILABLE,
                "model_family": "benchmark",
                "fs_level": "FS0",
                "y_pred": prev_value,
                "source_timestamp_utc": prev_ts,
                "source_local_date": prev_source_day,
                "fallback_step": prev_step if prev_step else "unavailable",
                "prediction_available": prev_value is not None,
                "unavailable_reason": "" if prev_value is not None else "no_causal_same_quarter_source",
            }
        )

        week_source_day = target_day - timedelta(days=7)
        week_value, week_ts = _lookup_profile_value(
            lookup=lookup,
            source_day=week_source_day,
            quarter_of_day=quarter_of_day,
            forecast_origin_utc=forecast_origin_utc,
        )
        rows_prev_week.append(
            {
                **base_common,
                "model": BENCHMARK_PREVIOUS_WEEK,
                "model_family": "benchmark",
                "fs_level": "FS0",
                "y_pred": week_value,
                "source_timestamp_utc": week_ts,
                "source_local_date": week_source_day if week_value is not None else None,
                "fallback_step": "previous_week_same_quarter" if week_value is not None else "unavailable",
                "prediction_available": week_value is not None,
                "unavailable_reason": "" if week_value is not None else "previous_week_same_quarter_unavailable",
            }
        )

        full_day_candidates = day_profiles[
            day_profiles["full_profile_available"].fillna(False).astype(bool)
            & (pd.to_datetime(day_profiles["delivery_local_date"]).dt.date <= origin_local_day)
        ].copy()
        day_value = None
        day_ts = None
        day_source = None
        if not full_day_candidates.empty:
            day_source = pd.Timestamp(full_day_candidates.iloc[-1]["delivery_local_date"]).date()
            day_value, day_ts = _lookup_profile_value(
                lookup=lookup,
                source_day=day_source,
                quarter_of_day=quarter_of_day,
                forecast_origin_utc=forecast_origin_utc,
            )
        rows_last_full_day.append(
            {
                **base_common,
                "model": BENCHMARK_LAST_FULL_DAY,
                "model_family": "benchmark",
                "fs_level": "FS0",
                "y_pred": day_value,
                "source_timestamp_utc": day_ts,
                "source_local_date": day_source if day_value is not None else None,
                "fallback_step": "last_fully_available_daily_profile" if day_value is not None else "unavailable",
                "prediction_available": day_value is not None,
                "unavailable_reason": "" if day_value is not None else "no_full_daily_profile_available",
            }
        )

    return pd.DataFrame(rows_prev_available), pd.DataFrame(rows_prev_week), pd.DataFrame(rows_last_full_day)


def _apply_zero_mean_correction_to_eval_frame(frame: pd.DataFrame, delta_pred_raw: np.ndarray) -> pd.DataFrame:
    working = frame.copy()
    working["delta_pred_raw"] = np.asarray(delta_pred_raw, dtype=float)
    hourly_means = working.groupby("hour_start_utc")["delta_pred_raw"].transform("mean")
    working["delta_pred_adjusted"] = working["delta_pred_raw"] - hourly_means
    working["predicted_delta_zero_mean_abs"] = (
        working.groupby("hour_start_utc")["delta_pred_adjusted"].transform("mean").abs()
    )
    working["y_pred"] = pd.to_numeric(working["hourly_backbone_forecast_eur_per_mwh"], errors="coerce") + working["delta_pred_adjusted"]
    return working


def _build_mixed_frequency_eval_frame(
    origin_quarter_frame: pd.DataFrame,
    *,
    run_id: str,
    model_name: str,
    model_family: str,
    fs_level: str,
    backbone_row: dict[str, Any],
    fit_time_sec: float,
    predict_time_sec: float,
    prediction_available: bool,
    unavailable_reason: str,
) -> pd.DataFrame:
    frame = origin_quarter_frame[
        [
            "forecast_origin_utc",
            "forecast_origin_local",
            "delivery_start_local_date",
            "dataset_split",
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
            "is_observed_target",
            "expected_normal_target_count_per_origin",
            "actual_target_count_per_origin",
            "observed_target_count_per_origin",
            "target_count_status",
            "availability_status",
            "hour_start_utc",
            "hourly_backbone_forecast_eur_per_mwh",
        ]
    ].copy()
    frame["run_id"] = run_id
    frame["model"] = model_name
    frame["model_family"] = model_family
    frame["fs_level"] = fs_level
    frame["hourly_backbone_run_id"] = str(backbone_row["selected_run_id"])
    frame["hourly_backbone_model"] = str(backbone_row["selected_model"])
    frame["fit_time_sec"] = fit_time_sec
    frame["predict_time_sec"] = predict_time_sec
    frame["prediction_available"] = bool(prediction_available)
    frame["unavailable_reason"] = str(unavailable_reason)
    frame["source_timestamp_utc"] = pd.NaT
    frame["source_local_date"] = pd.NaT
    frame["fallback_step"] = "mixed_frequency_deviation"
    return frame


def _run_mixed_frequency_models(
    *,
    target_template: pd.DataFrame,
    expanded_hourly_backbone: pd.DataFrame,
    training_table: pd.DataFrame,
    run_id: str,
    backbone_row: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if training_table.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "mixed_frequency_models_enabled": False,
            "reason": "No full-observed quarter-hour hours were available for mixed-frequency training.",
        }

    origin_frames: list[pd.DataFrame] = []
    for origin_key, group in expanded_hourly_backbone.groupby(["forecast_origin_utc", "dataset_split"], dropna=False):
        origin_frame = group.rename(
            columns={
                "target_timestamp_utc": "hour_anchor_timestamp_utc",
                "target_delivery_local_date": "hour_anchor_delivery_local_date",
                "target_hour_local": "hour_anchor_local_hour",
                "timestamp_utc": "target_timestamp_utc",
                "timestamp_local": "target_timestamp_local_backbone",
                "delivery_local_date": "target_date_local_backbone",
                "hourly_anchor_price_eur_per_mwh": "hourly_backbone_forecast_eur_per_mwh",
            }
        ).copy()
        duplicate_quarter_schedule_columns = [
            column
            for column in ("lead_day", "lead_day_label", "horizon_index")
            if column in origin_frame.columns
        ]
        if duplicate_quarter_schedule_columns:
            origin_frame = origin_frame.drop(columns=duplicate_quarter_schedule_columns)
        origin_frame = origin_frame.merge(
            target_template[
                [
                    "forecast_origin_utc",
                    "target_timestamp_utc",
                    "forecast_origin_local",
                    "delivery_start_local_date",
                    "target_timestamp_local",
                    "target_date_local",
                    "dataset_split",
                    "lead_day",
                    "lead_day_label",
                    "horizon_index",
                    "lead_quarter_index",
                    "quarter_of_day",
                    "hour_of_day",
                    "quarter_in_hour",
                    "y_true",
                    "is_observed_target",
                    "expected_normal_target_count_per_origin",
                    "actual_target_count_per_origin",
                    "observed_target_count_per_origin",
                    "target_count_status",
                    "availability_status",
                ]
            ],
            on=["forecast_origin_utc", "target_timestamp_utc", "dataset_split"],
            how="inner",
        )
        origin_frames.append(origin_frame)
    if not origin_frames:
        return pd.DataFrame(), pd.DataFrame(), {
            "mixed_frequency_models_enabled": False,
            "reason": "Expanded hourly backbone could not be aligned with the quarter-hour target schedule.",
        }
    modeling_table = pd.concat(origin_frames, ignore_index=True).sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)

    prediction_frames: list[pd.DataFrame] = []
    timing_rows: list[dict[str, Any]] = []
    feature_schema: dict[str, Any] = {"models": {}}

    for forecast_origin_utc, origin_frame in modeling_table.groupby("forecast_origin_utc", dropna=False):
        forecast_origin_utc = pd.Timestamp(forecast_origin_utc)
        origin_frame = origin_frame.reset_index(drop=True)
        train_rows = training_table[training_table["known_at_utc"] <= forecast_origin_utc].copy()
        train_rows = train_rows[pd.to_numeric(train_rows["delta_eur_per_mwh"], errors="coerce").notna()].reset_index(drop=True)

        # Mean-shape model.
        fit_started = time.perf_counter()
        mean_state = _fit_mean_shape(train_rows) if not train_rows.empty else None
        fit_time_sec = time.perf_counter() - fit_started
        predict_started = time.perf_counter()
        if mean_state is not None and not origin_frame.empty:
            delta_pred_raw = _predict_mean_shape(mean_state, origin_frame)
            mean_eval = _build_mixed_frequency_eval_frame(
                origin_frame,
                run_id=run_id,
                model_name=MODEL_MEAN_SHAPE,
                model_family="mixed_frequency",
                fs_level="FS0",
                backbone_row=backbone_row,
                fit_time_sec=fit_time_sec,
                predict_time_sec=0.0,
                prediction_available=True,
                unavailable_reason="",
            )
            mean_eval = _apply_zero_mean_correction_to_eval_frame(mean_eval, delta_pred_raw)
        else:
            mean_eval = _build_mixed_frequency_eval_frame(
                origin_frame,
                run_id=run_id,
                model_name=MODEL_MEAN_SHAPE,
                model_family="mixed_frequency",
                fs_level="FS0",
                backbone_row=backbone_row,
                fit_time_sec=fit_time_sec,
                predict_time_sec=0.0,
                prediction_available=False,
                unavailable_reason="no_train_rows_available",
            )
            mean_eval["y_pred"] = np.nan
            mean_eval["delta_pred_adjusted"] = np.nan
            mean_eval["predicted_delta_zero_mean_abs"] = np.nan
        predict_time_sec = time.perf_counter() - predict_started
        mean_eval["predict_time_sec"] = predict_time_sec
        prediction_frames.append(mean_eval)
        timing_rows.append(
            {
                "run_id": run_id,
                "model_scope": "quarterhour_mixed_frequency",
                "model": MODEL_MEAN_SHAPE,
                "model_family": "mixed_frequency",
                "fs_level": "FS0",
                "dataset_split": str(origin_frame["dataset_split"].iloc[0]),
                "forecast_origin_utc": forecast_origin_utc.isoformat(),
                "fit_time_sec": fit_time_sec,
                "predict_time_sec": predict_time_sec,
                "runtime_info_json": json.dumps({"train_rows": int(train_rows.shape[0])}, sort_keys=True),
            }
        )

        # XGBoost deviation model.
        xgb_fit_time_sec = 0.0
        xgb_predict_time_sec = 0.0
        xgb_prediction_available = False
        xgb_unavailable_reason = ""
        xgb_delta_pred_raw = np.full(shape=origin_frame.shape[0], fill_value=np.nan, dtype=float)
        feature_columns: list[str] = []
        if int(train_rows.shape[0]) >= XGBOOST_MIN_TRAIN_ROWS:
            xgb_fit_started = time.perf_counter()
            train_X, feature_columns, feature_summary = _build_feature_frame(train_rows)
            train_y = pd.to_numeric(train_rows["delta_eur_per_mwh"], errors="coerce")
            params = {
                "n_estimators": 200,
                "max_depth": 4,
                "learning_rate": 0.05,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
            }
            learner = _fit_xgboost(train_X, train_y, params=params)
            xgb_fit_time_sec = time.perf_counter() - xgb_fit_started
            xgb_predict_started = time.perf_counter()
            eval_X, _, _ = _build_feature_frame(origin_frame)
            eval_X = eval_X.reindex(columns=feature_columns, fill_value=0.0)
            xgb_delta_pred_raw = learner.predict(eval_X)
            xgb_predict_time_sec = time.perf_counter() - xgb_predict_started
            xgb_prediction_available = True
            if not feature_schema["models"].get(MODEL_XGBOOST):
                feature_schema["models"][MODEL_XGBOOST] = {
                    "feature_columns": list(feature_columns),
                    "feature_count": int(len(feature_columns)),
                    "hyperparameters": params,
                }
                feature_schema["models"][f"{MODEL_XGBOOST}_feature_summary"] = feature_summary.to_dict(orient="records")
        else:
            xgb_unavailable_reason = f"train_rows_below_threshold_{XGBOOST_MIN_TRAIN_ROWS}"

        xgb_eval = _build_mixed_frequency_eval_frame(
            origin_frame,
            run_id=run_id,
            model_name=MODEL_XGBOOST,
            model_family="mixed_frequency",
            fs_level="FS1",
            backbone_row=backbone_row,
            fit_time_sec=xgb_fit_time_sec,
            predict_time_sec=xgb_predict_time_sec,
            prediction_available=xgb_prediction_available,
            unavailable_reason=xgb_unavailable_reason,
        )
        if xgb_prediction_available:
            xgb_eval = _apply_zero_mean_correction_to_eval_frame(xgb_eval, xgb_delta_pred_raw)
        else:
            xgb_eval["y_pred"] = np.nan
            xgb_eval["delta_pred_adjusted"] = np.nan
            xgb_eval["predicted_delta_zero_mean_abs"] = np.nan
        prediction_frames.append(xgb_eval)
        timing_rows.append(
            {
                "run_id": run_id,
                "model_scope": "quarterhour_mixed_frequency",
                "model": MODEL_XGBOOST,
                "model_family": "mixed_frequency",
                "fs_level": "FS1",
                "dataset_split": str(origin_frame["dataset_split"].iloc[0]),
                "forecast_origin_utc": forecast_origin_utc.isoformat(),
                "fit_time_sec": xgb_fit_time_sec,
                "predict_time_sec": xgb_predict_time_sec,
                "runtime_info_json": json.dumps(
                    {
                        "train_rows": int(train_rows.shape[0]),
                        "feature_count": int(len(feature_columns)),
                        "prediction_available": bool(xgb_prediction_available),
                        "unavailable_reason": xgb_unavailable_reason,
                    },
                    sort_keys=True,
                ),
            }
        )

    return (
        pd.concat(prediction_frames, ignore_index=True).sort_values(["model", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True),
        pd.DataFrame(timing_rows).sort_values(["model", "dataset_split", "forecast_origin_utc"]).reset_index(drop=True),
        feature_schema,
    )


def _finalize_prediction_frame(
    frame: pd.DataFrame,
    *,
    run_id: str,
    model_name: str,
    model_family: str,
    fs_level: str,
) -> pd.DataFrame:
    working = frame.copy()
    working["run_id"] = run_id
    working["model"] = model_name
    working["model_family"] = model_family
    working["fs_level"] = fs_level
    if "prediction_available" not in working.columns:
        working["prediction_available"] = working["y_pred"].notna()
    if "unavailable_reason" not in working.columns:
        working["unavailable_reason"] = np.where(working["prediction_available"], "", "prediction_missing")
    required = [
        "run_id",
        "model",
        "model_family",
        "fs_level",
        "dataset_split",
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
        "prediction_available",
        "unavailable_reason",
        "fit_time_sec",
        "predict_time_sec",
        "expected_normal_target_count_per_origin",
        "actual_target_count_per_origin",
        "observed_target_count_per_origin",
        "target_count_status",
        "availability_status",
        "source_timestamp_utc",
        "source_local_date",
        "fallback_step",
        "hourly_backbone_run_id",
        "hourly_backbone_model",
    ]
    for column in required:
        if column not in working.columns:
            working[column] = pd.NA
    return working[required].copy()


def _metric_row(group: pd.DataFrame) -> dict[str, Any]:
    observed_mask = group["y_true"].notna()
    paired_mask = group["y_true"].notna() & group["y_pred"].notna()
    observed = group.loc[observed_mask].copy()
    paired = group.loc[paired_mask].copy()
    errors = pd.to_numeric(paired["y_pred"], errors="coerce") - pd.to_numeric(paired["y_true"], errors="coerce")
    abs_error = errors.abs()
    total_rows = int(group.shape[0])
    observed_target_count = int(observed.shape[0])
    excluded_non_observed_target_count = int(total_rows - observed_target_count)
    scored_count = int(paired.shape[0])
    prediction_availability_pct = float(scored_count / observed_target_count * 100.0) if observed_target_count else 0.0
    observed_target_coverage_pct = float(observed_target_count / total_rows * 100.0) if total_rows else 0.0
    return {
        "observations_total": total_rows,
        "observed_target_count": observed_target_count,
        "excluded_non_observed_target_count": excluded_non_observed_target_count,
        "observations_scored": scored_count,
        "observed_target_coverage_pct": observed_target_coverage_pct,
        "prediction_availability_pct": prediction_availability_pct,
        "mae": float(abs_error.mean()) if not paired.empty else np.nan,
        "rmse": float(np.sqrt(np.mean(np.square(errors)))) if not paired.empty else np.nan,
        "bias": float(errors.mean()) if not paired.empty else np.nan,
        "median_ae": float(abs_error.median()) if not paired.empty else np.nan,
        "p90_ae": float(abs_error.quantile(0.90)) if not paired.empty else np.nan,
        "p95_ae": float(abs_error.quantile(0.95)) if not paired.empty else np.nan,
    }


def _summarize_overall_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(["model", "model_family", "fs_level", "dataset_split"], dropna=False):
        row = dict(zip(["model", "model_family", "fs_level", "dataset_split"], keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "mae", "model"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_metrics_by_lead_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(
        ["model", "model_family", "fs_level", "dataset_split", "lead_day", "lead_day_label"],
        dropna=False,
    ):
        row = dict(zip(["model", "model_family", "fs_level", "dataset_split", "lead_day", "lead_day_label"], keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "lead_day", "mae", "model"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_metrics_by_reporting_level(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in reporting_level_specs():
        subset = predictions[predictions["lead_day"].isin(spec.lead_days)].copy()
        if subset.empty:
            continue
        reporting_cols = spec.to_columns()
        for keys, group in subset.groupby(["model", "model_family", "fs_level", "dataset_split"], dropna=False):
            row = dict(zip(["model", "model_family", "fs_level", "dataset_split"], keys, strict=True))
            row.update(_metric_row(group))
            row["origins"] = int(group["forecast_origin_utc"].nunique())
            row.update(reporting_cols)
            rows.append(row)
    return (
        pd.DataFrame(rows).sort_values(["dataset_split", "reporting_level_sort_order", "mae", "model"]).reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )


def _summarize_metrics_by_hour_of_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(["model", "dataset_split", "hour_of_day"], dropna=False):
        row = dict(zip(["model", "dataset_split", "hour_of_day"], keys, strict=True))
        row.update(_metric_row(group))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "hour_of_day", "model"]).reset_index(drop=True) if rows else pd.DataFrame()


def _summarize_metrics_by_quarter_of_day(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(["model", "dataset_split", "quarter_of_day"], dropna=False):
        row = dict(zip(["model", "dataset_split", "quarter_of_day"], keys, strict=True))
        row.update(_metric_row(group))
        rows.append(row)
    return (
        pd.DataFrame(rows).sort_values(["dataset_split", "quarter_of_day", "model"]).reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )


def _choose_official_naive_reference(overall_metrics: pd.DataFrame) -> dict[str, Any]:
    candidates = overall_metrics[
        (overall_metrics["dataset_split"].astype(str) == "validation")
        & (overall_metrics["model"].astype(str).isin([BENCHMARK_PREVIOUS_AVAILABLE, BENCHMARK_PREVIOUS_WEEK, BENCHMARK_LAST_FULL_DAY]))
    ].copy()
    if candidates.empty:
        raise ValueError("No quarter-hour naive benchmark candidates were available for official rMAE selection.")
    feasible = candidates[candidates["prediction_availability_pct"] >= MIN_OFFICIAL_NAIVE_COVERAGE_PCT].copy()
    if feasible.empty:
        feasible = candidates.sort_values(
            ["prediction_availability_pct", "mae", "model"],
            ascending=[False, True, True],
        ).copy()
        selected = feasible.iloc[0].to_dict()
        selected["selection_policy"] = "fallback_highest_prediction_availability_then_mae"
    else:
        selected = feasible.sort_values(["mae", "model"]).iloc[0].to_dict()
        selected["selection_policy"] = "minimum_prediction_availability_then_mae"
    selected["selection_split"] = "validation"
    selected["selection_metric"] = "mae"
    selected["minimum_prediction_availability_pct"] = MIN_OFFICIAL_NAIVE_COVERAGE_PCT
    selected["candidate_validation_scores"] = candidates.sort_values(["mae", "model"]).to_dict(orient="records")
    return selected


def _add_rmae_columns(
    metrics: pd.DataFrame,
    *,
    benchmark_model: str,
    group_keys: list[str],
) -> pd.DataFrame:
    if metrics.empty:
        return metrics.copy()
    benchmark = metrics[metrics["model"].astype(str) == str(benchmark_model)][group_keys + ["mae"]].rename(columns={"mae": "benchmark_mae"})
    merged = metrics.merge(benchmark, on=group_keys, how="left")
    merged["rmae_vs_official_naive"] = merged["mae"] / merged["benchmark_mae"]
    merged.loc[merged["benchmark_mae"].isna() | (merged["benchmark_mae"] == 0.0), "rmae_vs_official_naive"] = np.nan
    merged["rmae"] = merged["rmae_vs_official_naive"]
    return merged.drop(columns=["benchmark_mae"])


def _paired_dm_results(
    predictions: pd.DataFrame,
    *,
    challenger_model: str,
    benchmark_model: str,
    hac_lag: int = 24,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_cols = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]
    challenger = predictions[predictions["model"].astype(str) == str(challenger_model)][base_cols].rename(columns={"y_pred": "y_pred_challenger"})
    benchmark = predictions[predictions["model"].astype(str) == str(benchmark_model)][base_cols].rename(columns={"y_pred": "y_pred_benchmark"})
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
                "challenger_model": str(challenger_model),
                "benchmark_model": str(benchmark_model),
                "comparison_scope": "overall",
                "lead_day": "overall",
                "limitations_note": "Paired observed rows only. Interpret with care under short 15-minute history, serial dependence, and overlapping multi-day horizons.",
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
                    "challenger_model": str(challenger_model),
                    "benchmark_model": str(benchmark_model),
                    "comparison_scope": "lead_day",
                    "lead_day": int(lead_day),
                    "limitations_note": "Paired observed rows only. Interpret with care under short 15-minute history, serial dependence, and overlapping multi-day horizons.",
                }
            )
            rows.append(result)
        for spec in reporting_level_specs():
            reporting_subset = split_group[split_group["lead_day"].isin(spec.lead_days)].copy()
            if reporting_subset.empty:
                continue
            result = diebold_mariano_test(
                actual=reporting_subset["y_true"],
                forecast_a=reporting_subset["y_pred_challenger"],
                forecast_b=reporting_subset["y_pred_benchmark"],
                loss="absolute",
                hac_lag=hac_lag,
            )
            result.update(
                {
                    "dataset_split": str(split_name),
                    "challenger_model": str(challenger_model),
                    "benchmark_model": str(benchmark_model),
                    "comparison_scope": "reporting_level",
                    "lead_day": "overall",
                    **spec.to_columns(),
                    "limitations_note": "Paired observed rows only. Interpret with care under short 15-minute history, serial dependence, and overlapping multi-day horizons.",
                }
            )
            rows.append(result)
    return pd.DataFrame(rows).sort_values(["dataset_split", "challenger_model", "comparison_scope", "lead_day"]).reset_index(drop=True) if rows else pd.DataFrame()


def _build_observed_target_coverage_summary(target_template: pd.DataFrame) -> pd.DataFrame:
    per_origin = (
        target_template.groupby(["dataset_split", "forecast_origin_utc", "delivery_start_local_date"], as_index=False)
        .agg(
            actual_target_count_per_origin=("target_timestamp_utc", "size"),
            observed_target_count_per_origin=("is_observed_target", "sum"),
            target_rows_with_observed_truth=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            first_target_timestamp_utc=("target_timestamp_utc", "min"),
            last_target_timestamp_utc=("target_timestamp_utc", "max"),
            target_count_status=("target_count_status", "first"),
            availability_status=("availability_status", "first"),
        )
        .sort_values(["dataset_split", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    per_origin["observed_target_coverage_pct"] = (
        per_origin["observed_target_count_per_origin"] / per_origin["actual_target_count_per_origin"] * 100.0
    )
    return per_origin


def _build_model_settings_summary(backbone_row: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "model": BENCHMARK_REPEATED_HOURLY,
            "model_family": "benchmark",
            "fs_level": "FS0",
            "settings_json": json.dumps({"strategy": "repeat_hourly_backbone"}, sort_keys=True),
        },
        {
            "model": BENCHMARK_PREVIOUS_AVAILABLE,
            "model_family": "benchmark",
            "fs_level": "FS0",
            "settings_json": json.dumps(
                {
                    "strategy": "previous_available_same_quarter",
                    "fallback_order": [
                        "previous_local_day_if_known",
                        "most_recent_earlier_local_day_if_known",
                        "previous_week_same_quarter_if_known",
                        "last_fully_available_daily_profile",
                        "unavailable",
                    ],
                },
                sort_keys=True,
            ),
        },
        {
            "model": BENCHMARK_PREVIOUS_WEEK,
            "model_family": "benchmark",
            "fs_level": "FS0",
            "settings_json": json.dumps({"strategy": "previous_week_same_quarter"}, sort_keys=True),
        },
        {
            "model": BENCHMARK_LAST_FULL_DAY,
            "model_family": "benchmark",
            "fs_level": "FS0",
            "settings_json": json.dumps({"strategy": "last_fully_available_daily_profile"}, sort_keys=True),
        },
        {
            "model": MODEL_MEAN_SHAPE,
            "model_family": "mixed_frequency",
            "fs_level": "FS0",
            "settings_json": json.dumps(
                {"grouping": ["local_hour_of_day", "quarter_index", "weekend_flag"], "zero_mean_correction": True},
                sort_keys=True,
            ),
        },
        {
            "model": MODEL_XGBOOST,
            "model_family": "mixed_frequency",
            "fs_level": "FS1",
            "settings_json": json.dumps(
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
                sort_keys=True,
            ),
        },
    ]
    summary = pd.DataFrame(rows)
    summary["hourly_backbone_run_id"] = str(backbone_row["selected_run_id"])
    summary["hourly_backbone_model"] = str(backbone_row["selected_model"])
    return summary


def _scenario_generation_compatibility_payload(predictions: pd.DataFrame) -> dict[str, Any]:
    required_columns = {
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "y_true",
        "y_pred",
        "is_observed_target",
    }
    present_required_columns = required_columns.issubset(set(predictions.columns))
    unique_schedule = (
        predictions[
            [
                "dataset_split",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "y_true",
                "is_observed_target",
            ]
        ]
        .drop_duplicates(subset=["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
        if present_required_columns
        else pd.DataFrame(columns=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "y_true", "is_observed_target"])
    )
    split_counts = (
        unique_schedule.groupby("dataset_split", dropna=False)
        .agg(
            origins=("forecast_origin_utc", "nunique"),
            target_rows=("target_timestamp_utc", "size"),
            observed_target_rows=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        )
        .reset_index()
        .to_dict(orient="records")
        if not predictions.empty
        else []
    )
    return {
        "compatible": bool(present_required_columns),
        "required_columns_present": bool(present_required_columns),
        "normal_hourly_target_count": 120,
        "normal_quarterhour_target_count": EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN,
        "split_counts": split_counts,
        "notes": "Quarter-hour deterministic artifacts expose origin, horizon, observed-target, and prediction columns needed by downstream DA scenario generation.",
    }


def run_observed_market_deterministic_forecast(
    config: QuarterHourDAExtensionConfig | None = None,
) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id, run_dir = create_run_directory(config.output_root, RUN_LABEL)

    canonical_quarterhour_frame, hourly_training_summary, source_summary = load_and_build_canonical_quarterhour_frame(config)
    origins, target_template, split_summary, split_metadata = build_origin_schedule_and_split_policy(canonical_quarterhour_frame, config)
    bridge_csv, bridge_summary = _build_hourly_bridge_from_quarterhour(canonical_quarterhour_frame, config=config, run_dir=run_dir)
    hourly_config = _build_hourly_extension_config(config, bridge_csv=bridge_csv, split_summary=split_summary)

    candidate_scores, backbone_selection_summary = _build_hourly_backbone_candidate_table(
        config,
        hourly_config=hourly_config,
        target_template=target_template,
    )
    write_csv(run_dir / "hourly_backbone_candidate_scores.csv", candidate_scores)
    write_csv(run_dir / "hourly_backbone_selection_summary.csv", backbone_selection_summary)

    feasible_candidates = candidate_scores[candidate_scores["feasible_for_observed_extension"].fillna(False).astype(bool)].copy()
    foundation_status = "ready_for_model_comparison"
    blocker = ""
    if feasible_candidates.empty:
        foundation_status = "blocked_before_model_comparison"
        blocker = "No feasible hourly backbone candidate had validation-scored forecast quality and direct feature coverage through the observed 15-minute period."

    write_csv(run_dir / "origin_schedule.csv", origins)
    write_csv(run_dir / "split_summary.csv", split_summary)
    write_csv(run_dir / "targets_by_origin.csv", target_template)
    write_csv(run_dir / "observed_target_coverage_summary.csv", _build_observed_target_coverage_summary(target_template))
    write_csv(run_dir / "canonical_quarterhour_hourly_training_summary.csv", hourly_training_summary)
    write_csv(run_dir / "hourly_backbone_bridge_summary.csv", bridge_summary)
    canonical_quarterhour_frame.to_csv(run_dir / "canonical_quarterhour_frame.csv", index=False)

    if foundation_status != "ready_for_model_comparison":
        run_summary = {
            "run_id": run_id,
            "run_label": RUN_LABEL,
            "status": foundation_status,
            "market": "DA",
            "resolution": "15min",
            "horizon_days": 5,
            "normal_targets_per_origin": EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN,
            "actual_target_count_policy": "Store per-origin realized 5-day target count so DST windows may differ from 480.",
            "observed_target_policy": "Observed-only scoring. y_true is NaN for non-observed 15-minute targets.",
            "interpolated_target_policy": "Interpolated, synthetic, gap-filled, and flagged target values are excluded from scored truth.",
            "forecast_origin_policy": "08:00 on D-1 in Europe/Amsterdam, inherited from the audited hourly DA framework.",
            "availability_policy": "known_at_utc <= forecast_origin_utc under the conservative internal DA availability convention.",
            "known_at_assumption": "conservative internal convention, inherited from audited hourly framework",
            "quarter_hour_actual_source": source_summary["authoritative_quarterhour_path"],
            "observed_15min_split_policy": split_metadata["split_policy"],
            "split_dates": split_metadata["split_dates"],
            "split_origin_counts": split_metadata["split_origin_counts"],
            "split_observed_target_counts": split_metadata["split_observed_target_counts"],
            "hourly_backbone_selection_rule": backbone_selection_summary.to_dict(orient="records"),
            "scenario_generation_compatibility_status": "foundation_only",
            "limitations": [blocker],
            "mFRR_in_scope": False,
            "created_at_utc": _timestamped_now_utc(),
        }
        write_json(run_dir / "run_summary.json", run_summary)
        return run_dir

    backbone_row = feasible_candidates.iloc[0].to_dict()
    source_frame_hourly = pd.read_csv(bridge_csv)
    source_frame_hourly["timestamp_utc"] = pd.to_datetime(source_frame_hourly["timestamp_utc"], utc=True, errors="coerce")
    source_frame_hourly = source_frame_hourly.sort_values("timestamp_utc").reset_index(drop=True)

    # Reuse the audited hourly builder so the bridge inherits the same canonical/known_at handling.
    from hourly_da.core.data_loading import build_canonical_hourly_frame, load_hourly_price_frame

    canonical_hourly_frame = build_canonical_hourly_frame(load_hourly_price_frame(hourly_config), hourly_config)
    canonical_hourly_frame.to_csv(run_dir / "canonical_hourly_backbone_frame.csv", index=False)

    hourly_backbone_predictions, hourly_backbone_timing = _run_hourly_backbone_extension(
        config=config,
        hourly_config=hourly_config,
        canonical_hourly_frame=canonical_hourly_frame,
        origins=origins,
        selected_candidate_row=backbone_row,
        run_id=run_id,
    )
    write_csv(run_dir / "hourly_backbone_predictions_long.csv", hourly_backbone_predictions)
    write_csv(run_dir / "hourly_backbone_timing.csv", hourly_backbone_timing)

    hourly_frame = hourly_backbone_predictions[
        [
            "forecast_origin_utc",
            "dataset_split",
            "lead_day",
            "lead_day_label",
            "horizon_index",
            "target_timestamp_utc",
            "target_delivery_local_date",
            "target_hour_local",
            "y_pred",
        ]
    ].copy()
    hourly_frame["hour_start_utc"] = pd.to_datetime(hourly_frame["target_timestamp_utc"], utc=True, errors="coerce")
    hourly_frame["hour_start_local"] = hourly_frame["hour_start_utc"].dt.tz_convert(config.business_timezone)
    hourly_frame["delivery_local_date"] = pd.to_datetime(hourly_frame["target_delivery_local_date"], errors="coerce").dt.date
    hourly_frame["local_hour_of_day"] = pd.to_numeric(hourly_frame["target_hour_local"], errors="coerce").astype(int)
    hourly_frame["hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(hourly_frame["y_pred"], errors="coerce")
    hourly_frame = _enrich_hourly_anchor_frame(hourly_frame)
    expanded_hourly = _expand_hourly_to_quarters(
        hourly_frame,
        source_type="observed_market_hourly_backbone",
        shape_method="hourly_backbone_repeat",
        scenario_variant="observed_market_deterministic",
    )
    expanded_hourly["forecast_origin_utc"] = pd.to_datetime(expanded_hourly["forecast_origin_utc"], utc=True, errors="coerce")

    repeated_hourly = _build_repeated_hourly_benchmark(expanded_hourly, target_template, run_id=run_id, backbone_row=backbone_row)
    previous_available, previous_week, last_full_day = _build_same_quarter_benchmarks(target_template, canonical_quarterhour_frame, run_id=run_id)
    repeated_hourly = _finalize_prediction_frame(repeated_hourly, run_id=run_id, model_name=BENCHMARK_REPEATED_HOURLY, model_family="benchmark", fs_level="FS0")
    previous_available = _finalize_prediction_frame(previous_available, run_id=run_id, model_name=BENCHMARK_PREVIOUS_AVAILABLE, model_family="benchmark", fs_level="FS0")
    previous_week = _finalize_prediction_frame(previous_week, run_id=run_id, model_name=BENCHMARK_PREVIOUS_WEEK, model_family="benchmark", fs_level="FS0")
    last_full_day = _finalize_prediction_frame(last_full_day, run_id=run_id, model_name=BENCHMARK_LAST_FULL_DAY, model_family="benchmark", fs_level="FS0")

    training_table = _build_observed_hourly_training_table(canonical_quarterhour_frame)
    mixed_predictions, mixed_timing, feature_schema = _run_mixed_frequency_models(
        target_template=target_template,
        expanded_hourly_backbone=expanded_hourly,
        training_table=training_table,
        run_id=run_id,
        backbone_row=backbone_row,
    )
    if not mixed_predictions.empty:
        mixed_predictions = pd.concat(
            [
                _finalize_prediction_frame(
                    mixed_predictions[mixed_predictions["model"].astype(str) == model_name].copy(),
                    run_id=run_id,
                    model_name=model_name,
                    model_family="mixed_frequency",
                    fs_level="FS0" if model_name == MODEL_MEAN_SHAPE else "FS1",
                )
                for model_name in [MODEL_MEAN_SHAPE, MODEL_XGBOOST]
                if not mixed_predictions[mixed_predictions["model"].astype(str) == model_name].empty
            ],
            ignore_index=True,
        )

    predictions_long = pd.concat(
        [repeated_hourly, previous_available, previous_week, last_full_day, mixed_predictions],
        ignore_index=True,
    ).sort_values(["model", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)

    timing_rows = pd.concat([hourly_backbone_timing, mixed_timing], ignore_index=True) if not mixed_timing.empty else hourly_backbone_timing.copy()
    timing_summary = _summarize_timing(timing_rows)

    overall_metrics = _summarize_overall_metrics(predictions_long)
    official_naive = _choose_official_naive_reference(overall_metrics)
    overall_metrics = _add_rmae_columns(overall_metrics, benchmark_model=str(official_naive["model"]), group_keys=["dataset_split"])
    lead_day_metrics = _add_rmae_columns(
        _summarize_metrics_by_lead_day(predictions_long),
        benchmark_model=str(official_naive["model"]),
        group_keys=["dataset_split", "lead_day", "lead_day_label"],
    )
    reporting_level_metrics = _add_rmae_columns(
        _summarize_metrics_by_reporting_level(predictions_long),
        benchmark_model=str(official_naive["model"]),
        group_keys=["dataset_split", "reporting_level", "reporting_level_label", "reporting_level_sort_order"],
    )
    hour_of_day_metrics = _summarize_metrics_by_hour_of_day(predictions_long)
    quarter_of_day_metrics = _summarize_metrics_by_quarter_of_day(predictions_long)

    dm_frames = [
        _paired_dm_results(predictions_long, challenger_model=MODEL_XGBOOST, benchmark_model=BENCHMARK_REPEATED_HOURLY),
        _paired_dm_results(predictions_long, challenger_model=MODEL_XGBOOST, benchmark_model=BENCHMARK_PREVIOUS_AVAILABLE),
        _paired_dm_results(predictions_long, challenger_model=MODEL_XGBOOST, benchmark_model=BENCHMARK_PREVIOUS_WEEK),
    ]
    dm_test_results = pd.concat([frame for frame in dm_frames if not frame.empty], ignore_index=True) if any(not frame.empty for frame in dm_frames) else pd.DataFrame()

    model_settings_summary = _build_model_settings_summary(backbone_row)
    scenario_compatibility = _scenario_generation_compatibility_payload(predictions_long)

    write_csv(run_dir / "forecasts_by_origin.csv", predictions_long)
    write_csv(run_dir / "predictions_long.csv", predictions_long)
    write_csv(run_dir / "origin_timing.csv", timing_rows)
    write_csv(run_dir / "origin_timing_summary.csv", timing_summary)
    write_csv(run_dir / "metrics_overall.csv", overall_metrics)
    write_csv(run_dir / "metrics_by_reporting_level.csv", reporting_level_metrics)
    write_csv(run_dir / "metrics_by_lead_day.csv", lead_day_metrics)
    write_csv(run_dir / "metrics_by_hour_of_day.csv", hour_of_day_metrics)
    write_csv(run_dir / "metrics_by_quarter_of_day.csv", quarter_of_day_metrics)
    write_csv(run_dir / "model_settings_summary.csv", model_settings_summary)
    write_csv(run_dir / "dm_test_results.csv", dm_test_results)
    write_json(run_dir / "official_naive_reference.json", official_naive)
    write_json(run_dir / "feature_schema.json", feature_schema)
    write_json(run_dir / "scenario_generation_compatibility.json", scenario_compatibility)
    write_json(
        run_dir / "suite_models.json",
        {
            "models": [
                {"model": BENCHMARK_REPEATED_HOURLY, "model_family": "benchmark", "fs_level": "FS0"},
                {"model": BENCHMARK_PREVIOUS_AVAILABLE, "model_family": "benchmark", "fs_level": "FS0"},
                {"model": BENCHMARK_PREVIOUS_WEEK, "model_family": "benchmark", "fs_level": "FS0"},
                {"model": BENCHMARK_LAST_FULL_DAY, "model_family": "benchmark", "fs_level": "FS0"},
                {"model": MODEL_MEAN_SHAPE, "model_family": "mixed_frequency", "fs_level": "FS0"},
                {"model": MODEL_XGBOOST, "model_family": "mixed_frequency", "fs_level": "FS1"},
            ]
        },
    )

    run_summary = {
        "run_id": run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "market": "DA",
        "resolution": "15min",
        "horizon_days": 5,
        "normal_targets_per_origin": EXPECTED_NORMAL_TARGET_COUNT_PER_ORIGIN,
        "actual_target_count_policy": "Store actual per-origin 5-day quarter-hour target counts so DST windows may differ from 480.",
        "observed_target_policy": "is_observed_target is False for interpolated, synthetic, gap-filled, flagged, or otherwise non-observed cleaned target values.",
        "interpolated_target_policy": "Non-observed targets are retained in the schedule for provenance but excluded from scored truth with y_true = NaN.",
        "forecast_origin_policy": "08:00 on D-1 local time, inherited from the audited hourly D..D+4 framework.",
        "availability_policy": "Use the audited hourly conservative internal known_at convention and filter history with known_at_utc <= forecast_origin_utc.",
        "known_at_assumption": "conservative internal convention, inherited from audited hourly framework",
        "model_strategy": "hourly_backbone_plus_predicted_quarter_hour_deviation",
        "hourly_backbone_run_id": str(backbone_row["selected_run_id"]),
        "hourly_backbone_selection_rule": backbone_selection_summary.to_dict(orient="records"),
        "quarter_hour_actual_source": source_summary["authoritative_quarterhour_path"],
        "observed_15min_split_policy": split_metadata["split_policy"],
        "split_dates": split_metadata["split_dates"],
        "split_origin_counts": split_metadata["split_origin_counts"],
        "split_observed_target_counts": split_metadata["split_observed_target_counts"],
        "timezone_policy": "Store timestamps internally in UTC and convert to Europe/Amsterdam for reporting only.",
        "dst_policy": "Store actual target counts per origin because local-day quarter counts may be 92, 96, or 100.",
        "leakage_guard_summary": [
            "Hourly and quarter-hour history are filtered with known_at_utc <= forecast_origin_utc.",
            "Validation/test scoring uses observed targets only; non-observed rows have y_true = NaN.",
            "The repeated-hourly structural benchmark is not used silently as the official rMAE denominator.",
            "The hourly backbone candidate is selected on validation metrics only and must be feasible through the observed 15-minute period.",
            "The quarter-hour pipeline does not reuse the scenario-generation test-preferred slice selector for model or benchmark selection.",
        ],
        "benchmark_causality_summary": [
            "previous_available_same_quarter uses a frozen availability-checked fallback chain",
            "previous_week_same_quarter validates availability against forecast origin",
            "last_full_day_profile uses the latest fully known local day only",
            "repeated_hourly_backbone uses frozen hourly forecast values only",
        ],
        "previous_available_same_quarter_fallback_order": [
            "previous_local_day_if_known",
            "most_recent_earlier_local_day_if_known",
            "previous_week_same_quarter_if_known",
            "last_fully_available_daily_profile",
            "unavailable",
        ],
        "rmae_denominator_policy": official_naive,
        "scenario_generation_compatibility_status": scenario_compatibility,
        "limitations": [
            "The known_at rule is a conservative internal convention and not yet an externally validated DA publication-timing model.",
            "Observed quarter-hour evaluation is limited to the post-transition observed period available in the repository.",
            "DM test interpretation remains limited by short 15-minute history, serial dependence, and overlapping multi-day horizons.",
        ],
        "mFRR_in_scope": False,
        "created_at_utc": _timestamped_now_utc(),
    }
    write_json(run_dir / "run_summary.json", run_summary)
    return run_dir
