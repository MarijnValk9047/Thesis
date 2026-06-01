from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .lago_lear_config import LagoLearBenchmarkConfig


PRICE_VALUE_COL = "price_eur_per_mwh"
EXOG_VALUE_COL = "value_mw"
EXPECTED_D_ONLY_FEATURE_COUNT = 247


@dataclass(frozen=True)
class LagoDailyFeatureMatrix:
    X: pd.DataFrame
    Y: pd.DataFrame
    metadata: pd.DataFrame
    feature_schema: dict[str, Any]
    skipped_rows: pd.DataFrame
    known_at_violations: pd.DataFrame
    missing_feature_summary: pd.DataFrame
    dropped_rows_by_reason: pd.DataFrame
    variant_feature_counts: pd.DataFrame


@dataclass(frozen=True)
class LagoDirectFeatureMatrix:
    X_long: pd.DataFrame
    y_long: pd.DataFrame
    metadata_long: pd.DataFrame
    feature_schema: dict[str, Any]
    skipped_rows: pd.DataFrame
    known_at_violations: pd.DataFrame
    unavailable_exogenous_by_lead_day: pd.DataFrame
    missing_feature_summary: pd.DataFrame


def _ensure_local_columns(frame: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "timestamp_utc" not in out.columns:
        return pd.DataFrame(columns=["timestamp_utc", "timestamp_local", "target_delivery_local_date", "target_hour_local", "known_at_utc", EXOG_VALUE_COL])
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp_utc"]).copy()
    # Source families currently mix hour conventions (0..23 and 1..24).
    # Recompute local delivery date/hour from UTC timestamp for consistency.
    out["timestamp_local"] = out["timestamp_utc"].dt.tz_convert(config.local_timezone)
    out["target_delivery_local_date"] = out["timestamp_local"].dt.date
    out["target_hour_local"] = out["timestamp_local"].dt.hour.astype("Int64")
    if "known_at_utc" in out.columns:
        out["known_at_utc"] = pd.to_datetime(out["known_at_utc"], utc=True, errors="coerce")
        if "known_at_rule" in out.columns:
            rule = out["known_at_rule"].fillna("").astype(str)

            def _local_08_to_utc(target_day: date, day_offset: int) -> pd.Timestamp:
                known_local = pd.Timestamp(datetime.combine(target_day - timedelta(days=day_offset), time(hour=8, minute=0))).tz_localize(
                    config.local_timezone,
                    ambiguous="raise",
                    nonexistent="raise",
                )
                return known_local.tz_convert("UTC")

            day_ahead_mask = rule.str.contains("day_ahead_local_08", case=False, regex=False)
            week_ahead_mask = rule.str.contains("week_ahead_local_08", case=False, regex=False)
            if day_ahead_mask.any():
                out.loc[day_ahead_mask, "known_at_utc"] = out.loc[day_ahead_mask, "target_delivery_local_date"].map(
                    lambda value: _local_08_to_utc(value, day_offset=1)
                )
            if week_ahead_mask.any():
                out.loc[week_ahead_mask, "known_at_utc"] = out.loc[week_ahead_mask, "target_delivery_local_date"].map(
                    lambda value: _local_08_to_utc(value, day_offset=7)
                )
    return out.sort_values("timestamp_utc").reset_index(drop=True)


def _day_slice(frame: pd.DataFrame, local_day: date) -> pd.DataFrame:
    return frame[frame["target_delivery_local_date"] == local_day].copy()


def _is_complete_24h_day(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    valid_hours = frame["target_hour_local"].dropna().astype(int).tolist()
    if len(valid_hours) != 24:
        return False
    return sorted(valid_hours) == list(range(24))


def _vector_by_hour(frame: pd.DataFrame, value_col: str) -> list[float] | None:
    if frame.empty:
        return None
    ordered = frame.sort_values(["target_hour_local", "timestamp_utc"]).copy()
    ordered = ordered.drop_duplicates(subset=["target_hour_local"], keep="last")
    if ordered["target_hour_local"].isna().any():
        return None
    hours = ordered["target_hour_local"].astype(int).tolist()
    if sorted(hours) != list(range(24)):
        return None
    values = pd.to_numeric(ordered[value_col], errors="coerce")
    if values.isna().any():
        return None
    return [float(value) for value in values.tolist()]


def _vector_by_hour_allow_missing(frame: pd.DataFrame, value_col: str) -> list[float] | None:
    if frame.empty:
        return None
    ordered = frame.sort_values(["target_hour_local", "timestamp_utc"]).copy()
    ordered = ordered.drop_duplicates(subset=["target_hour_local"], keep="last")
    if ordered["target_hour_local"].isna().any():
        return None
    hours = ordered["target_hour_local"].astype(int).tolist()
    if sorted(hours) != list(range(24)):
        return None
    values = pd.to_numeric(ordered[value_col], errors="coerce")
    return [float(value) if pd.notna(value) else np.nan for value in values.tolist()]


def _feature_family_from_name(name: str) -> str:
    if name.startswith("price_"):
        return "price_lag"
    if name.startswith("x1_"):
        return "x1_load"
    if name.startswith("x2_"):
        return "x2_res"
    if name.startswith("dow_"):
        return "weekday"
    if name.startswith("lead_day_") or name == "lead_day_numeric":
        return "lead_day"
    if name == "target_hour_local_numeric":
        return "target_hour"
    return "other"


def _latest_known_snapshot(
    frame: pd.DataFrame,
    origin_utc: pd.Timestamp,
    *,
    allow_missing_known_at: bool,
) -> pd.DataFrame:
    work = frame.copy()
    if "known_at_utc" not in work.columns:
        if allow_missing_known_at:
            work["known_at_utc"] = pd.Timestamp.min.tz_localize("UTC")
        else:
            raise ValueError("known_at_utc is required for strict no-leakage mode.")
    work["known_at_utc"] = pd.to_datetime(work["known_at_utc"], utc=True, errors="coerce")
    if work["known_at_utc"].isna().any() and not allow_missing_known_at:
        raise ValueError("known_at_utc has missing values and allow_missing_known_at=False.")
    if allow_missing_known_at:
        work["known_at_utc"] = work["known_at_utc"].fillna(pd.Timestamp.min.tz_localize("UTC"))
    work = work[work["known_at_utc"] <= origin_utc].copy()
    if work.empty:
        return work
    return (
        work.sort_values(["timestamp_utc", "known_at_utc"])
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )


def _weekday_dummies(local_day: date) -> dict[str, int]:
    dow = int(pd.Timestamp(local_day).dayofweek)
    return {f"dow_{idx}": int(idx == dow) for idx in range(7)}


def _hour_feature_name(prefix: str, hour_zero_based: int) -> str:
    return f"{prefix}_h{hour_zero_based + 1:02d}"


def _append_hour_vector(features: dict[str, float], prefix: str, vector_24: list[float]) -> None:
    for hour in range(24):
        features[_hour_feature_name(prefix, hour)] = float(vector_24[hour])


def _expected_d_only_feature_names() -> list[str]:
    names: list[str] = []
    for prefix in ("price_d_minus_1", "price_d_minus_2", "price_d_minus_3", "price_d_minus_7"):
        names.extend([_hour_feature_name(prefix, hour) for hour in range(24)])
    for prefix in ("x1_load_fcst_d", "x2_gen_fcst_d"):
        names.extend([_hour_feature_name(prefix, hour) for hour in range(24)])
    for prefix in ("x1_load_fcst_d_minus_1", "x1_load_fcst_d_minus_7", "x2_gen_fcst_d_minus_1", "x2_gen_fcst_d_minus_7"):
        names.extend([_hour_feature_name(prefix, hour) for hour in range(24)])
    names.extend([f"dow_{idx}" for idx in range(7)])
    return names


def _resolve_x2_for_day(
    x2_res_snapshot: pd.DataFrame,
    x2_agg_snapshot: pd.DataFrame,
    local_day: date,
    *,
    x2_policy: str,
    allow_aggregate_fallback: bool,
    x2_missing_policy: str = "impute_training_median",
) -> tuple[list[float] | None, str]:
    if x2_policy == "no_x2":
        return [np.nan] * 24, "x2_disabled"

    if x2_policy in {"res_a69_psr_sum", "res_forecast_if_available"}:
        x2_res_day = _day_slice(x2_res_snapshot, local_day)
        vector = _vector_by_hour_allow_missing(x2_res_day, EXOG_VALUE_COL)
        if vector is not None:
            return vector, "x2_res_a69_psr_sum"
        if allow_aggregate_fallback:
            x2_agg_day = _day_slice(x2_agg_snapshot, local_day)
            agg_vector = _vector_by_hour_allow_missing(x2_agg_day, EXOG_VALUE_COL)
            if agg_vector is not None:
                return agg_vector, "x2_aggregate_fallback"
        if str(x2_missing_policy) == "impute_training_median":
            return [np.nan] * 24, "x2_missing_imputed_later"
        return None, "x2_unavailable_res"

    if x2_policy in {"aggregate_generation", "da_aggregate_generation_forecast_when_available"}:
        x2_agg_day = _day_slice(x2_agg_snapshot, local_day)
        agg_vector = _vector_by_hour_allow_missing(x2_agg_day, EXOG_VALUE_COL)
        if agg_vector is not None:
            return agg_vector, "x2_aggregate_generation"
        if str(x2_missing_policy) == "impute_training_median":
            return [np.nan] * 24, "x2_missing_imputed_later"
        return None, "x2_unavailable_aggregate"

    raise ValueError(f"Unsupported x2_policy: {x2_policy}")


def _build_feature_schema_d_only(feature_names: list[str], x2_source_note: str) -> dict[str, Any]:
    schema_rows: list[dict[str, Any]] = []
    price_lag_count = 0
    current_exogenous_count = 0
    lagged_exogenous_count = 0
    weekday_count = 0
    for name in feature_names:
        relative_day: int | None = None
        hour_index: int | None = None
        lago_mapping = ""
        if name.startswith("price_d_minus_"):
            family = "price_lag"
            source_dataset = "da_price_actual_observed"
            known_at_rule = "day_ahead_local_08_assumption"
            price_lag_count += 1
            lago_mapping = "p_lag"
            if "_d_minus_1_" in name:
                relative_day = -1
            elif "_d_minus_2_" in name:
                relative_day = -2
            elif "_d_minus_3_" in name:
                relative_day = -3
            elif "_d_minus_7_" in name:
                relative_day = -7
        elif name.startswith("x1_load_fcst_"):
            family = "x1_load"
            source_dataset = "da_total_load_forecast"
            known_at_rule = "day_ahead_local_08"
            lago_mapping = "x1"
            if "_d_h" in name:
                relative_day = 0
                current_exogenous_count += 1
            elif "_d_minus_1_" in name:
                relative_day = -1
                lagged_exogenous_count += 1
            elif "_d_minus_7_" in name:
                relative_day = -7
                lagged_exogenous_count += 1
        elif name.startswith("x2_gen_fcst_"):
            family = "x2_generation"
            source_dataset = x2_source_note
            known_at_rule = "day_ahead_local_08_assumption_a69_psr"
            lago_mapping = "x2"
            if "_d_h" in name:
                relative_day = 0
                current_exogenous_count += 1
            elif "_d_minus_1_" in name:
                relative_day = -1
                lagged_exogenous_count += 1
            elif "_d_minus_7_" in name:
                relative_day = -7
                lagged_exogenous_count += 1
        elif name.startswith("dow_"):
            family = "weekday"
            source_dataset = "calendar"
            known_at_rule = "always_known"
            weekday_count += 1
            lago_mapping = "z_d"
        else:
            family = "other"
            source_dataset = "unknown"
            known_at_rule = "unknown"
        if "_h" in name:
            try:
                hour_index = int(name.rsplit("_h", maxsplit=1)[-1])
            except ValueError:
                hour_index = None
        schema_rows.append(
            {
                "feature_name": name,
                "family": family,
                "source_dataset": source_dataset,
                "relative_day": relative_day,
                "hour_index": hour_index,
                "known_at_rule": known_at_rule,
                "lago_mapping": lago_mapping,
            }
        )
    return {
        "total_feature_count": int(len(feature_names)),
        "expected_total_feature_count": int(EXPECTED_D_ONLY_FEATURE_COUNT),
        "price_lag_count": int(price_lag_count),
        "current_exogenous_count": int(current_exogenous_count),
        "lagged_exogenous_count": int(lagged_exogenous_count),
        "weekday_count": int(weekday_count),
        "x2_source": x2_source_note,
        "x2_components": "B16 + B18 + B19",
        "x2_aggregation": "sum_by_timestamp",
        "known_at_rule_x2": "day_ahead_local_08_assumption_a69_psr",
        "rows": schema_rows,
    }


def build_lago_d_only_daily_matrix(
    price_df: pd.DataFrame,
    load_forecast_df: pd.DataFrame,
    generation_forecast_df: pd.DataFrame,
    config: LagoLearBenchmarkConfig,
    generation_forecast_fallback_df: pd.DataFrame | None = None,
) -> LagoDailyFeatureMatrix:
    price = _ensure_local_columns(price_df, config)
    x1 = _ensure_local_columns(load_forecast_df, config)
    x2_candidate = _ensure_local_columns(generation_forecast_df, config)

    # Optional aggregate fallback frame from existing cleaned aggregate DA generation family.
    if generation_forecast_fallback_df is not None and not generation_forecast_fallback_df.empty:
        x2_agg = _ensure_local_columns(generation_forecast_fallback_df, config)
    else:
        x2_agg = pd.DataFrame(columns=x2_candidate.columns)
        if "source_family" in x2_candidate.columns and (x2_candidate["source_family"] == "da_generation_forecast").any():
            x2_agg = x2_candidate.copy()
        elif "family" in x2_candidate.columns and (x2_candidate["family"] == "da_generation_forecast").any():
            x2_agg = x2_candidate.copy()

    rows_x: list[dict[str, float]] = []
    rows_y: list[dict[str, float]] = []
    rows_meta: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    dropped_rows_by_reason: list[dict[str, Any]] = []
    known_at_violations: list[dict[str, Any]] = []
    x2_source_note = "A69 day-ahead wind/solar generation forecast by PSR (B16+B18+B19)"

    for delivery_day in config.benchmark_delivery_days():
        if config.dst_policy == "skip_non_24h_local_days" and config.expected_hours_for_local_day(delivery_day) != 24:
            skipped_rows.append(
                {
                    "delivery_local_date": delivery_day.isoformat(),
                    "reason": "dst_non_24h_day",
                }
            )
            continue

        origin_utc = config.forecast_origin_utc_for_delivery_day(delivery_day)

        try:
            x1_snapshot = _latest_known_snapshot(x1, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_snapshot = _latest_known_snapshot(x2_candidate, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_agg_snapshot = _latest_known_snapshot(x2_agg, origin_utc, allow_missing_known_at=True) if not x2_agg.empty else pd.DataFrame()
        except ValueError as exc:
            skipped_rows.append(
                {
                    "delivery_local_date": delivery_day.isoformat(),
                    "reason": f"known_at_error::{exc}",
                }
            )
            continue

        lag_days = {
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_2": delivery_day - timedelta(days=2),
            "d_minus_3": delivery_day - timedelta(days=3),
            "d_minus_7": delivery_day - timedelta(days=7),
        }
        target_day_slice = _day_slice(price, delivery_day)
        if not _is_complete_24h_day(target_day_slice):
            skipped_rows.append(
                {
                    "delivery_local_date": delivery_day.isoformat(),
                    "reason": "target_day_not_complete_24h_observed",
                }
            )
            continue
        target_vector = _vector_by_hour(target_day_slice, PRICE_VALUE_COL)
        if target_vector is None:
            skipped_rows.append(
                {
                    "delivery_local_date": delivery_day.isoformat(),
                    "reason": "target_vector_missing",
                }
            )
            continue

        price_vectors: dict[str, list[float]] = {}
        missing_price_lag = False
        for lag_label, lag_day in lag_days.items():
            lag_slice = _day_slice(price, lag_day)
            if not _is_complete_24h_day(lag_slice):
                missing_price_lag = True
                skipped_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "reason": f"missing_price_{lag_label}",
                    }
                )
                break
            lag_vector = _vector_by_hour(lag_slice, PRICE_VALUE_COL)
            if lag_vector is None:
                missing_price_lag = True
                skipped_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "reason": f"missing_price_vector_{lag_label}",
                    }
                )
                break
            price_vectors[lag_label] = lag_vector
        if missing_price_lag:
            continue

        x1_vectors: dict[str, list[float]] = {}
        x1_days = {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }
        for x1_label, x1_day in x1_days.items():
            x1_slice_day = _day_slice(x1_snapshot, x1_day)
            x1_vector = _vector_by_hour_allow_missing(x1_slice_day, EXOG_VALUE_COL)
            if x1_vector is None:
                skipped_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "reason": f"missing_x1_{x1_label}",
                    }
                )
                dropped_rows_by_reason.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "reason": f"missing_x1_{x1_label}",
                        "missing_price_lag": False,
                        "missing_target": False,
                        "known_at_violation": False,
                        "non_24h_dst_day": False,
                        "missing_x2": False,
                        "other": True,
                    }
                )
                break
            x1_vectors[x1_label] = x1_vector
        if len(x1_vectors) != len(x1_days):
            continue

        x2_vectors: dict[str, list[float]] = {}
        x2_days = {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }
        for x2_label, x2_day in x2_days.items():
            x2_vector, x2_source = _resolve_x2_for_day(
                x2_snapshot,
                x2_agg_snapshot,
                x2_day,
                x2_policy=config.x2_policy,
                allow_aggregate_fallback=config.allow_x2_aggregate_fallback,
                x2_missing_policy=config.x2_missing_policy,
            )
            if x2_vector is None:
                skipped_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "reason": f"missing_x2_{x2_label}",
                    }
                )
                dropped_rows_by_reason.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "reason": f"missing_x2_{x2_label}",
                        "missing_price_lag": False,
                        "missing_target": False,
                        "known_at_violation": False,
                        "non_24h_dst_day": False,
                        "missing_x2": True,
                        "other": False,
                    }
                )
                break
            if x2_source == "x2_aggregate_fallback":
                x2_source_note = "aggregate DA generation forecast fallback (A69 unavailable)"
            x2_vectors[x2_label] = x2_vector
        if len(x2_vectors) != len(x2_days):
            continue

        for frame_name, snapshot in (("x1", x1_snapshot), ("x2", x2_snapshot)):
            if snapshot.empty or "known_at_utc" not in snapshot.columns:
                continue
            viol = snapshot[snapshot["known_at_utc"] > origin_utc]
            if not viol.empty:
                known_at_violations.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "frame": frame_name,
                        "violation_count": int(viol.shape[0]),
                    }
                )

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

        features.update({key: float(value) for key, value in _weekday_dummies(delivery_day).items()})

        row_y = {f"y_h{hour + 1:02d}": float(target_vector[hour]) for hour in range(24)}
        rows_x.append(features)
        rows_y.append(row_y)
        rows_meta.append(
            {
                "delivery_local_date": delivery_day.isoformat(),
                "forecast_origin_local": config.localized_forecast_origin_for_delivery_day(delivery_day).isoformat(),
                "forecast_origin_utc": origin_utc.isoformat(),
                "target_start_utc": target_day_slice["timestamp_utc"].min().isoformat(),
                "target_end_utc": target_day_slice["timestamp_utc"].max().isoformat(),
                "x2_source_used": x2_source_note,
            }
        )

    expected_feature_names = _expected_d_only_feature_names()
    X = pd.DataFrame(rows_x)
    if X.empty:
        X = pd.DataFrame(columns=expected_feature_names)
    else:
        for col in expected_feature_names:
            if col not in X.columns:
                X[col] = np.nan
        X = X[expected_feature_names]
    Y = pd.DataFrame(rows_y)
    if Y.empty:
        Y = pd.DataFrame(columns=[f"y_h{hour:02d}" for hour in range(1, 25)])
    metadata = pd.DataFrame(rows_meta)
    skipped = pd.DataFrame(skipped_rows)
    violations = pd.DataFrame(known_at_violations)
    dropped = pd.DataFrame(dropped_rows_by_reason)
    if not skipped.empty:
        skipped_norm = skipped.copy()
        skipped_norm["reason"] = skipped_norm.get("reason", pd.Series(dtype=str)).astype(str)
        skipped_norm["delivery_local_date"] = skipped_norm.get("delivery_local_date", pd.Series(dtype=str)).astype(str)
        skipped_norm["forecast_origin_utc"] = skipped_norm["delivery_local_date"].map(
            lambda value: config.forecast_origin_utc_for_delivery_day(pd.Timestamp(value).date()).isoformat() if value and value != "nan" else None
        )
        skipped_norm = skipped_norm.assign(
            missing_price_lag=skipped_norm["reason"].str.contains("missing_price", na=False),
            missing_target=skipped_norm["reason"].str.contains("target", na=False),
            known_at_violation=skipped_norm["reason"].str.contains("known_at", na=False),
            non_24h_dst_day=skipped_norm["reason"].str.contains("dst_non_24h_day", na=False),
            missing_x2=skipped_norm["reason"].str.contains("missing_x2", na=False),
        )
        skipped_norm["other"] = ~(
            skipped_norm["missing_price_lag"]
            | skipped_norm["missing_target"]
            | skipped_norm["known_at_violation"]
            | skipped_norm["non_24h_dst_day"]
            | skipped_norm["missing_x2"]
        )
        keep_cols = [
            "delivery_local_date",
            "forecast_origin_utc",
            "reason",
            "missing_price_lag",
            "missing_target",
            "known_at_violation",
            "non_24h_dst_day",
            "missing_x2",
            "other",
        ]
        dropped = pd.concat([dropped, skipped_norm[keep_cols]], ignore_index=True).drop_duplicates()

    feature_names = list(X.columns)
    if len(feature_names) != EXPECTED_D_ONLY_FEATURE_COUNT:
        raise RuntimeError(
            f"D-only Lago feature count mismatch: got {len(feature_names)}, expected {EXPECTED_D_ONLY_FEATURE_COUNT}."
        )
    if any(name.startswith("y_h") for name in feature_names):
        raise RuntimeError("Leakage validation failed: feature set contains target columns.")

    schema = _build_feature_schema_d_only(feature_names, x2_source_note)
    missing_rows: list[dict[str, Any]] = []
    if not X.empty:
        for name in X.columns:
            feature_family = _feature_family_from_name(name)
            series = pd.to_numeric(X[name], errors="coerce")
            missing_rows.append(
                {
                    "feature_name": name,
                    "feature_family": feature_family,
                    "total_rows": int(series.shape[0]),
                    "missing_count": int(series.isna().sum()),
                    "missing_share": float(series.isna().mean()),
                    "split": "all",
                    "lead_day": "D",
                }
            )
    missing_summary = pd.DataFrame(missing_rows)
    variant_feature_counts = pd.DataFrame(
        [
            {
                "model_variant": "LEAR_LAGO_247_IMPUTED_X2",
                "feature_count": int(len(feature_names)),
                "price_lag_feature_count": int(sum(str(col).startswith("price_") for col in feature_names)),
                "x1_feature_count": int(sum(str(col).startswith("x1_") for col in feature_names)),
                "x2_feature_count": int(sum(str(col).startswith("x2_") for col in feature_names)),
                "weekday_feature_count": int(sum(str(col).startswith("dow_") for col in feature_names)),
                "imputation_enabled": True,
            }
        ]
    )
    return LagoDailyFeatureMatrix(
        X=X,
        Y=Y,
        metadata=metadata,
        feature_schema=schema,
        skipped_rows=skipped,
        known_at_violations=violations,
        missing_feature_summary=missing_summary,
        dropped_rows_by_reason=dropped,
        variant_feature_counts=variant_feature_counts,
    )


def _build_dplus4_schema(feature_names: list[str], x2_policy: str) -> dict[str, Any]:
    return {
        "total_feature_count": int(len(feature_names)),
        "x2_policy": str(x2_policy),
        "known_at_policy": "strict_known_at",
        "note": "D+4 is a Lago-style no-leakage adaptation, not exact Lago replication.",
        "features": [{"feature_name": name} for name in feature_names],
    }


def build_lago_dplus4_direct_matrix(
    price_df: pd.DataFrame,
    load_forecast_df: pd.DataFrame,
    week_ahead_load_forecast_df: pd.DataFrame,
    generation_forecast_df: pd.DataFrame,
    config: LagoLearBenchmarkConfig,
) -> LagoDirectFeatureMatrix:
    price = _ensure_local_columns(price_df, config)
    x1_da = _ensure_local_columns(load_forecast_df, config)
    x1_wa = _ensure_local_columns(week_ahead_load_forecast_df, config)
    x2 = _ensure_local_columns(generation_forecast_df, config)

    rows_x: list[dict[str, float]] = []
    rows_y: list[dict[str, float]] = []
    rows_meta: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    known_at_violations: list[dict[str, Any]] = []
    unavailable_exog: list[dict[str, Any]] = []

    for delivery_start_day in config.benchmark_delivery_days():
        origin_utc = config.forecast_origin_utc_for_delivery_day(delivery_start_day)
        try:
            x1_da_snapshot = _latest_known_snapshot(x1_da, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x1_wa_snapshot = _latest_known_snapshot(x1_wa, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_snapshot = _latest_known_snapshot(x2, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
        except ValueError as exc:
            skipped_rows.append(
                {
                    "delivery_start_local_date": delivery_start_day.isoformat(),
                    "lead_day": None,
                    "reason": f"known_at_error::{exc}",
                }
            )
            continue

        # Origin-relative known price vectors (safe for all leads).
        origin_price_vectors: dict[str, list[float]] = {}
        for lag_days, label in ((1, "origin_minus_1day"), (2, "origin_minus_2day"), (3, "origin_minus_3day"), (7, "origin_minus_7day")):
            lag_day = delivery_start_day - timedelta(days=lag_days)
            lag_slice = _day_slice(price, lag_day)
            if config.dst_policy == "skip_non_24h_local_days" and not _is_complete_24h_day(lag_slice):
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": None,
                        "reason": f"missing_origin_price_{label}",
                    }
                )
                origin_price_vectors = {}
                break
            lag_vector = _vector_by_hour(lag_slice, PRICE_VALUE_COL)
            if lag_vector is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": None,
                        "reason": f"missing_origin_price_vector_{label}",
                    }
                )
                origin_price_vectors = {}
                break
            origin_price_vectors[label] = lag_vector
        if not origin_price_vectors:
            continue

        for lead_day in config.lead_days:
            target_day = delivery_start_day + timedelta(days=int(lead_day))
            target_slice = _day_slice(price, target_day)
            if target_slice.empty:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_target_day_prices",
                    }
                )
                continue
            # D+4 matrix supports DST-safe schedule, so we keep all hours available in target day.
            target_slice = target_slice.sort_values(["target_hour_local", "timestamp_utc"]).copy()
            target_slice["target_hour_local"] = pd.to_numeric(target_slice["target_hour_local"], errors="coerce").astype("Int64")

            # Build target exogenous vectors with known-at-safe logic.
            x1_target_vector: list[float] | None = None
            x1_source = "none"
            if int(lead_day) == 0:
                x1_target_vector = _vector_by_hour(_day_slice(x1_da_snapshot, target_day), EXOG_VALUE_COL)
                x1_source = "da_load"
            if x1_target_vector is None:
                x1_target_vector = _vector_by_hour(_day_slice(x1_wa_snapshot, target_day), EXOG_VALUE_COL)
                if x1_target_vector is not None:
                    x1_source = "week_ahead_load"

            if x1_target_vector is None:
                unavailable_exog.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "variable": "x1_target",
                        "policy": config.x1_policy,
                        "status": "unavailable",
                    }
                )
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_x1_target_vector",
                    }
                )
                continue

            x2_target_vector = _vector_by_hour_allow_missing(_day_slice(x2_snapshot, target_day), EXOG_VALUE_COL)
            if int(lead_day) > 0 and config.dplus4_x2_policy == "strict_no_future_x2":
                x2_target_vector = [np.nan] * 24
                unavailable_exog.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "variable": "x2_target",
                        "policy": "strict_no_future_x2",
                        "status": "omitted",
                    }
                )
            elif x2_target_vector is None and config.dplus4_x2_policy == "persistence_proxy" and config.allow_x2_persistence_proxy:
                x2_target_vector = _vector_by_hour_allow_missing(_day_slice(x2_snapshot, delivery_start_day), EXOG_VALUE_COL)
                unavailable_exog.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "variable": "x2_target",
                        "policy": "persistence_proxy",
                        "status": "persistence_used" if x2_target_vector is not None else "persistence_missing",
                    }
                )
            elif x2_target_vector is None:
                unavailable_exog.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "variable": "x2_target",
                        "policy": config.dplus4_x2_policy,
                        "status": "unavailable",
                    }
                )
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_x2_target_vector",
                    }
                )
                continue

            x1_lag_d1 = _vector_by_hour_allow_missing(_day_slice(x1_da_snapshot, target_day - timedelta(days=1)), EXOG_VALUE_COL)
            x1_lag_d7 = _vector_by_hour_allow_missing(_day_slice(x1_da_snapshot, target_day - timedelta(days=7)), EXOG_VALUE_COL)
            if x1_lag_d1 is None or x1_lag_d7 is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_x1_lag_vectors",
                    }
                )
                continue

            x2_lag_d1 = _vector_by_hour_allow_missing(_day_slice(x2_snapshot, target_day - timedelta(days=1)), EXOG_VALUE_COL)
            x2_lag_d7 = _vector_by_hour_allow_missing(_day_slice(x2_snapshot, target_day - timedelta(days=7)), EXOG_VALUE_COL)
            if x2_lag_d1 is None or x2_lag_d7 is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": delivery_start_day.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_x2_lag_vectors",
                    }
                )
                continue

            if "known_at_utc" in x1_da_snapshot.columns:
                viol = x1_da_snapshot[x1_da_snapshot["known_at_utc"] > origin_utc]
                if not viol.empty:
                    known_at_violations.append(
                        {
                            "delivery_start_local_date": delivery_start_day.isoformat(),
                            "lead_day": int(lead_day),
                            "frame": "x1_da",
                            "violation_count": int(viol.shape[0]),
                        }
                    )

            base_features: dict[str, float] = {}
            _append_hour_vector(base_features, "price_origin_minus_1day", origin_price_vectors["origin_minus_1day"])
            _append_hour_vector(base_features, "price_origin_minus_2day", origin_price_vectors["origin_minus_2day"])
            _append_hour_vector(base_features, "price_origin_minus_3day", origin_price_vectors["origin_minus_3day"])
            _append_hour_vector(base_features, "price_origin_minus_7day", origin_price_vectors["origin_minus_7day"])
            _append_hour_vector(base_features, "x1_load_forecast_for_target", x1_target_vector)
            _append_hour_vector(base_features, "x2_generation_forecast_for_target", x2_target_vector)
            _append_hour_vector(base_features, "x1_load_forecast_target_minus_1", x1_lag_d1)
            _append_hour_vector(base_features, "x1_load_forecast_target_minus_7", x1_lag_d7)
            _append_hour_vector(base_features, "x2_generation_forecast_target_minus_1", x2_lag_d1)
            _append_hour_vector(base_features, "x2_generation_forecast_target_minus_7", x2_lag_d7)
            base_features.update({key: float(value) for key, value in _weekday_dummies(target_day).items()})
            for idx in config.lead_days:
                base_features[f"lead_day_{int(idx)}"] = float(int(idx == lead_day))
            base_features["lead_day_numeric"] = float(lead_day)

            for row in target_slice.to_dict(orient="records"):
                y_true = row.get(PRICE_VALUE_COL)
                if pd.isna(y_true):
                    continue
                target_hour = int(row["target_hour_local"]) if pd.notna(row["target_hour_local"]) else None
                if target_hour is None:
                    continue
                feature_row = dict(base_features)
                feature_row["target_hour_local_numeric"] = float(target_hour)
                rows_x.append(feature_row)
                rows_y.append({"y_true": float(y_true)})
                rows_meta.append(
                    {
                        "forecast_origin_utc": origin_utc,
                        "forecast_origin_local": config.localized_forecast_origin_for_delivery_day(delivery_start_day),
                        "target_timestamp_utc": pd.Timestamp(row["timestamp_utc"]),
                        "target_delivery_local_date": target_day,
                        "target_hour_local": int(target_hour),
                        "lead_day": int(lead_day),
                        "lead_day_label": "D" if int(lead_day) == 0 else f"D+{int(lead_day)}",
                        "horizon_index": int((int(lead_day) * 24) + target_hour + 1),
                        "is_observed_target": True,
                        "x1_source": x1_source,
                    }
                )

    X_long = pd.DataFrame(rows_x)
    y_long = pd.DataFrame(rows_y)
    metadata_long = pd.DataFrame(rows_meta)
    skipped = pd.DataFrame(skipped_rows)
    violations = pd.DataFrame(known_at_violations)
    unavailable = pd.DataFrame(unavailable_exog)

    feature_names = list(X_long.columns) if not X_long.empty else []
    schema = _build_dplus4_schema(feature_names, config.dplus4_x2_policy)
    missing_rows: list[dict[str, Any]] = []
    if not X_long.empty:
        for name in X_long.columns:
            series = pd.to_numeric(X_long[name], errors="coerce")
            missing_rows.append(
                {
                    "feature_name": name,
                    "feature_family": _feature_family_from_name(name),
                    "total_rows": int(series.shape[0]),
                    "missing_count": int(series.isna().sum()),
                    "missing_share": float(series.isna().mean()),
                    "split": "all",
                    "lead_day": "D..D+4",
                }
            )
    missing_summary = pd.DataFrame(missing_rows)
    return LagoDirectFeatureMatrix(
        X_long=X_long,
        y_long=y_long,
        metadata_long=metadata_long,
        feature_schema=schema,
        skipped_rows=skipped,
        known_at_violations=violations,
        unavailable_exogenous_by_lead_day=unavailable,
        missing_feature_summary=missing_summary,
    )
