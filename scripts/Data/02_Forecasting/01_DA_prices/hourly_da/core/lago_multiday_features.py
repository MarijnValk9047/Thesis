from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .lago_lear_config import LagoLearBenchmarkConfig

PRICE_VALUE_COL = "price_eur_per_mwh"
EXOG_VALUE_COL = "value_mw"


@dataclass(frozen=True)
class LagoMultidayFeatureMatrix:
    X_long: pd.DataFrame
    y_long: pd.DataFrame
    metadata_long: pd.DataFrame
    feature_schema: dict[str, Any]
    skipped_rows: pd.DataFrame
    known_at_violations: pd.DataFrame
    unavailable_exogenous_by_lead_day: pd.DataFrame
    missing_feature_summary: pd.DataFrame
    disallowed_feature_attempts: pd.DataFrame
    forbidden_columns_audit: pd.DataFrame
    feature_availability_by_horizon: pd.DataFrame


@dataclass(frozen=True)
class HorizonPolicy:
    source_csv: str
    allowed_tokens_by_horizon: dict[int, set[str]]
    disallowed_tokens_by_horizon: dict[int, set[str]]


def _ensure_local_columns(frame: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "timestamp_utc" not in out.columns:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "timestamp_local",
                "target_delivery_local_date",
                "target_hour_local",
                "known_at_utc",
                EXOG_VALUE_COL,
            ]
        )
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp_utc"]).copy()
    out["timestamp_local"] = out["timestamp_utc"].dt.tz_convert(config.local_timezone)
    out["target_delivery_local_date"] = out["timestamp_local"].dt.date
    out["target_hour_local"] = out["timestamp_local"].dt.hour.astype("Int64")
    if "known_at_utc" in out.columns:
        out["known_at_utc"] = pd.to_datetime(out["known_at_utc"], utc=True, errors="coerce")
        # Keep strict D+4 known_at semantics aligned with the approved D-only builder.
        # Current cleaned ENTSO-E forecast files expose known_at_rule tokens and a
        # delivery-day timestamp that needs normalization to forecast-origin semantics.
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
    if frame["target_hour_local"].isna().any():
        return False
    hours = sorted(frame["target_hour_local"].astype(int).tolist())
    return len(hours) == 24 and hours == list(range(24))


def _vector_by_hour(frame: pd.DataFrame, value_col: str) -> list[float] | None:
    if frame.empty:
        return None
    ordered = frame.sort_values(["target_hour_local", "timestamp_utc"]).drop_duplicates(subset=["target_hour_local"], keep="last")
    if ordered["target_hour_local"].isna().any():
        return None
    hours = ordered["target_hour_local"].astype(int).tolist()
    if sorted(hours) != list(range(24)):
        return None
    values = pd.to_numeric(ordered[value_col], errors="coerce")
    if values.isna().any():
        return None
    return [float(v) for v in values.tolist()]


def _vector_by_hour_allow_missing(frame: pd.DataFrame, value_col: str) -> list[float] | None:
    if frame.empty:
        return None
    ordered = frame.sort_values(["target_hour_local", "timestamp_utc"]).drop_duplicates(subset=["target_hour_local"], keep="last")
    if ordered["target_hour_local"].isna().any():
        return None
    hours = ordered["target_hour_local"].astype(int).tolist()
    if sorted(hours) != list(range(24)):
        return None
    values = pd.to_numeric(ordered[value_col], errors="coerce")
    return [float(v) if pd.notna(v) else np.nan for v in values.tolist()]


def _latest_known_snapshot(frame: pd.DataFrame, origin_utc: pd.Timestamp, *, allow_missing_known_at: bool) -> pd.DataFrame:
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


def _append_hour_vector(features: dict[str, float], prefix: str, vector_24: list[float]) -> None:
    for hour in range(24):
        features[f"{prefix}_h{hour + 1:02d}"] = float(vector_24[hour])


def _known_at_proxy_for_price(local_day: date, tz_name: str) -> pd.Timestamp:
    publish_local = pd.Timestamp(datetime.combine(local_day, time(hour=12, minute=0))).tz_localize(
        tz_name,
        ambiguous="raise",
        nonexistent="raise",
    )
    return publish_local.tz_convert("UTC")


def _feature_family(name: str) -> str:
    if name.startswith("p_base_"):
        return "price_base_origin_relative"
    if name.startswith("p_target_d_minus_"):
        return "price_target_relative"
    if name.startswith("x1_load_base_"):
        return "x1_base_origin_relative"
    if name.startswith("x2_res_base_"):
        return "x2_base_origin_relative"
    if name.startswith("x1_load_target_d_minus_"):
        return "x1_target_relative"
    if name.startswith("x2_res_target_d_minus_"):
        return "x2_target_relative"
    if name.startswith("dow_") or name in {"target_weekend_flag", "target_month"}:
        return "calendar"
    if name.startswith("lead_day_") or name == "horizon_day":
        return "horizon"
    return "other"


def _policy_token(name: str) -> str | None:
    if name.startswith("p_target_d_minus_1_"):
        return "p_target-1"
    if name.startswith("p_target_d_minus_2_"):
        return "p_target-2"
    if name.startswith("p_target_d_minus_3_"):
        return "p_target-3"
    if name.startswith("p_target_d_minus_7_"):
        return "p_target-7"
    if name.startswith("x1_load_target_d_h"):
        return "x1_load_target"
    if name.startswith("x1_load_target_d_minus_1_"):
        return "x1_load_target-1"
    if name.startswith("x1_load_target_d_minus_7_"):
        return "x1_load_target-7"
    if name.startswith("x2_res_target_d_h"):
        return "x2_res_target"
    if name.startswith("x2_res_target_d_minus_1_"):
        return "x2_res_target-1"
    if name.startswith("x2_res_target_d_minus_7_"):
        return "x2_res_target-7"
    if name.startswith("p_base_d_minus_"):
        if "_minus_1_" in name:
            return "price_origin_minus_1day"
        if "_minus_2_" in name:
            return "price_origin_minus_2day"
        if "_minus_3_" in name:
            return "price_origin_minus_3day"
        if "_minus_7_" in name:
            return "price_origin_minus_7day"
    if name.startswith("dow_") or name in {"target_weekend_flag", "target_month"}:
        return "weekday_dummies"
    if name.startswith("lead_day_") or name == "horizon_day":
        return "lead_day_index"
    return None


def _is_forbidden_feature_col(name: str) -> bool:
    value = str(name).lower()
    if value.startswith("y_"):
        return True
    forbidden_tokens = ("target_timestamp", "forecast_origin", "known_at", "provenance", "audit", "is_observed_target")
    return any(token in value for token in forbidden_tokens)


def _load_horizon_policy(path: Path | None) -> HorizonPolicy:
    if path is None or not path.exists():
        return HorizonPolicy(source_csv="", allowed_tokens_by_horizon={}, disallowed_tokens_by_horizon={})
    frame = pd.read_csv(path)
    allowed: dict[int, set[str]] = {}
    disallowed: dict[int, set[str]] = {}
    for row in frame.to_dict(orient="records"):
        h = int(row["horizon_day"])
        allowed_values = str(row.get("allowed_features", "")).strip()
        disallowed_values = str(row.get("disallowed_features", "")).strip()
        allowed[h] = {item.strip() for item in allowed_values.split(";") if item.strip()}
        disallowed[h] = {item.strip() for item in disallowed_values.split(";") if item.strip()}
    return HorizonPolicy(
        source_csv=str(path),
        allowed_tokens_by_horizon=allowed,
        disallowed_tokens_by_horizon=disallowed,
    )


def _policy_allows_feature(*, policy: HorizonPolicy, horizon_day: int, feature_name: str) -> tuple[bool, str]:
    token = _policy_token(feature_name)
    if token is None:
        return True, "token_unmapped_policy_not_applicable"
    disallowed = policy.disallowed_tokens_by_horizon.get(int(horizon_day), set())
    if token in disallowed:
        return False, f"policy_disallowed_token={token}"
    return True, "policy_allowed_or_unlisted"


def _expected_dplus4_feature_names(config: LagoLearBenchmarkConfig) -> list[str]:
    names: list[str] = []
    for prefix in ("p_base_d_minus_1", "p_base_d_minus_2", "p_base_d_minus_3", "p_base_d_minus_7"):
        names.extend([f"{prefix}_h{hour + 1:02d}" for hour in range(24)])
    for prefix in (
        "x1_load_base_d",
        "x2_res_base_d",
        "x1_load_base_d_minus_1",
        "x1_load_base_d_minus_7",
        "x2_res_base_d_minus_1",
        "x2_res_base_d_minus_7",
    ):
        names.extend([f"{prefix}_h{hour + 1:02d}" for hour in range(24)])
    for prefix in ("p_target_d_minus_7", "x1_load_target_d_minus_7", "x2_res_target_d_minus_7"):
        names.extend([f"{prefix}_h{hour + 1:02d}" for hour in range(24)])
    names.extend([f"dow_{idx}" for idx in range(7)])
    names.append("target_weekend_flag")
    names.append("target_month")
    names.append("horizon_day")
    names.extend([f"lead_day_{int(idx)}" for idx in config.lead_days])
    return names


def _safe_feature_vector(
    *,
    snapshot: pd.DataFrame,
    local_day: date,
    allow_missing_values: bool,
    value_col: str,
) -> tuple[list[float] | None, pd.Timestamp | None]:
    frame = _day_slice(snapshot, local_day)
    if frame.empty:
        return None, None
    vector = _vector_by_hour_allow_missing(frame, value_col) if allow_missing_values else _vector_by_hour(frame, value_col)
    if vector is None:
        return None, None
    known_at_max = None
    if "known_at_utc" in frame.columns and frame["known_at_utc"].notna().any():
        known_at_max = pd.to_datetime(frame["known_at_utc"], utc=True, errors="coerce").max()
    return vector, known_at_max


def build_lago_dplus4_direct_matrix_strict_no_future(
    *,
    price_df: pd.DataFrame,
    load_forecast_df: pd.DataFrame,
    week_ahead_load_forecast_df: pd.DataFrame,
    generation_forecast_df: pd.DataFrame,
    config: LagoLearBenchmarkConfig,
    horizon_policy_csv: Path | None = None,
    hard_fail_on_policy_violation: bool = True,
) -> LagoMultidayFeatureMatrix:
    price = _ensure_local_columns(price_df, config)
    x1_da = _ensure_local_columns(load_forecast_df, config)
    x1_wa = _ensure_local_columns(week_ahead_load_forecast_df, config)
    x2 = _ensure_local_columns(generation_forecast_df, config)
    policy = _load_horizon_policy(horizon_policy_csv)

    rows_x: list[dict[str, float]] = []
    rows_y: list[dict[str, float]] = []
    rows_meta: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    known_at_violations: list[dict[str, Any]] = []
    unavailable_exog: list[dict[str, Any]] = []
    disallowed_attempts: list[dict[str, Any]] = []
    availability_rows: list[dict[str, Any]] = []

    for base_d in config.benchmark_delivery_days():
        origin_utc = config.forecast_origin_utc_for_delivery_day(base_d)
        try:
            x1_da_snapshot = _latest_known_snapshot(x1_da, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x1_wa_snapshot = _latest_known_snapshot(x1_wa, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_snapshot = _latest_known_snapshot(x2, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
        except ValueError as exc:
            skipped_rows.append(
                {
                    "delivery_start_local_date": base_d.isoformat(),
                    "lead_day": None,
                    "reason": f"known_at_error::{exc}",
                }
            )
            continue

        base_price_vectors: dict[str, list[float]] = {}
        for lag in (1, 2, 3, 7):
            lag_day = base_d - timedelta(days=lag)
            lag_slice = _day_slice(price, lag_day)
            vec = _vector_by_hour(lag_slice, PRICE_VALUE_COL)
            if vec is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": None,
                        "reason": f"missing_p_base_d_minus_{lag}",
                    }
                )
                base_price_vectors = {}
                break
            base_price_vectors[f"p_base_d_minus_{lag}"] = vec
        if not base_price_vectors:
            continue

        # Origin-relative known exogenous vectors
        x1_base_vectors: dict[str, list[float]] = {}
        for label, day in (("x1_load_base_d", base_d), ("x1_load_base_d_minus_1", base_d - timedelta(days=1)), ("x1_load_base_d_minus_7", base_d - timedelta(days=7))):
            vec, known_at_max = _safe_feature_vector(snapshot=x1_da_snapshot, local_day=day, allow_missing_values=False, value_col=EXOG_VALUE_COL)
            source_used = "da"
            if vec is None:
                vec, known_at_max = _safe_feature_vector(snapshot=x1_wa_snapshot, local_day=day, allow_missing_values=False, value_col=EXOG_VALUE_COL)
                source_used = "week_ahead"
            if vec is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": None,
                        "reason": f"missing_{label}",
                    }
                )
                x1_base_vectors = {}
                break
            if known_at_max is not None and known_at_max > origin_utc:
                known_at_violations.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": None,
                        "feature_name": label,
                        "known_at_utc": known_at_max.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                    }
                )
            x1_base_vectors[label] = vec
            availability_rows.append(
                {
                    "delivery_start_local_date": base_d.isoformat(),
                    "horizon_day": "all",
                    "feature_name": label,
                    "known_at_utc_max": known_at_max.isoformat() if known_at_max is not None else None,
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "known_at_le_origin": bool(known_at_max is None or known_at_max <= origin_utc),
                    "source_used": source_used,
                }
            )
        if not x1_base_vectors:
            continue

        x2_base_vectors: dict[str, list[float]] = {}
        for label, day in (("x2_res_base_d", base_d), ("x2_res_base_d_minus_1", base_d - timedelta(days=1)), ("x2_res_base_d_minus_7", base_d - timedelta(days=7))):
            vec, known_at_max = _safe_feature_vector(snapshot=x2_snapshot, local_day=day, allow_missing_values=True, value_col=EXOG_VALUE_COL)
            if vec is None:
                if str(config.x2_missing_policy) == "impute_training_median":
                    vec = [np.nan] * 24
                    unavailable_exog.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "lead_day": None,
                            "variable": label,
                            "policy": "impute_training_median",
                            "status": "missing_impute_later",
                        }
                    )
                else:
                    skipped_rows.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "lead_day": None,
                            "reason": f"missing_{label}",
                        }
                    )
                    x2_base_vectors = {}
                    break
            if known_at_max is not None and known_at_max > origin_utc:
                known_at_violations.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": None,
                        "feature_name": label,
                        "known_at_utc": known_at_max.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                    }
                )
            x2_base_vectors[label] = vec
            availability_rows.append(
                {
                    "delivery_start_local_date": base_d.isoformat(),
                    "horizon_day": "all",
                    "feature_name": label,
                    "known_at_utc_max": known_at_max.isoformat() if known_at_max is not None else None,
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "known_at_le_origin": bool(known_at_max is None or known_at_max <= origin_utc),
                    "source_used": "da_res",
                }
            )
        if not x2_base_vectors:
            continue

        for lead_day in config.lead_days:
            target_day = base_d + timedelta(days=int(lead_day))
            target_slice = _day_slice(price, target_day)
            target_slice = target_slice.sort_values(["target_hour_local", "timestamp_utc"]).copy()
            if target_slice.empty:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_target_day_prices",
                    }
                )
                continue

            # Target-aligned weekly history features (always past at D-1 08:00 for D..D+4)
            p_target_d7 = _vector_by_hour(_day_slice(price, target_day - timedelta(days=7)), PRICE_VALUE_COL)
            if p_target_d7 is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_p_target_d_minus_7",
                    }
                )
                continue
            p_target_known = _known_at_proxy_for_price(target_day - timedelta(days=6), config.local_timezone)
            if p_target_known > origin_utc:
                known_at_violations.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "feature_name": "p_target_d_minus_7",
                        "known_at_utc": p_target_known.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                    }
                )

            x1_target_d7, x1_target_d7_known = _safe_feature_vector(
                snapshot=x1_da_snapshot,
                local_day=target_day - timedelta(days=7),
                allow_missing_values=False,
                value_col=EXOG_VALUE_COL,
            )
            if x1_target_d7 is None:
                x1_target_d7, x1_target_d7_known = _safe_feature_vector(
                    snapshot=x1_wa_snapshot,
                    local_day=target_day - timedelta(days=7),
                    allow_missing_values=False,
                    value_col=EXOG_VALUE_COL,
                )
            if x1_target_d7 is None:
                skipped_rows.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "reason": "missing_x1_load_target_d_minus_7",
                    }
                )
                continue
            if x1_target_d7_known is not None and x1_target_d7_known > origin_utc:
                known_at_violations.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "feature_name": "x1_load_target_d_minus_7",
                        "known_at_utc": x1_target_d7_known.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                    }
                )

            x2_target_d7, x2_target_d7_known = _safe_feature_vector(
                snapshot=x2_snapshot,
                local_day=target_day - timedelta(days=7),
                allow_missing_values=True,
                value_col=EXOG_VALUE_COL,
            )
            if x2_target_d7 is None:
                if str(config.x2_missing_policy) == "impute_training_median":
                    x2_target_d7 = [np.nan] * 24
                    unavailable_exog.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "lead_day": int(lead_day),
                            "variable": "x2_res_target_d_minus_7",
                            "policy": "impute_training_median",
                            "status": "missing_impute_later",
                        }
                    )
                else:
                    skipped_rows.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "lead_day": int(lead_day),
                            "reason": "missing_x2_res_target_d_minus_7",
                        }
                    )
                    continue
            if x2_target_d7_known is not None and x2_target_d7_known > origin_utc:
                known_at_violations.append(
                    {
                        "delivery_start_local_date": base_d.isoformat(),
                        "lead_day": int(lead_day),
                        "feature_name": "x2_res_target_d_minus_7",
                        "known_at_utc": x2_target_d7_known.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                    }
                )

            features: dict[str, float] = {}
            _append_hour_vector(features, "p_base_d_minus_1", base_price_vectors["p_base_d_minus_1"])
            _append_hour_vector(features, "p_base_d_minus_2", base_price_vectors["p_base_d_minus_2"])
            _append_hour_vector(features, "p_base_d_minus_3", base_price_vectors["p_base_d_minus_3"])
            _append_hour_vector(features, "p_base_d_minus_7", base_price_vectors["p_base_d_minus_7"])

            _append_hour_vector(features, "x1_load_base_d", x1_base_vectors["x1_load_base_d"])
            _append_hour_vector(features, "x2_res_base_d", x2_base_vectors["x2_res_base_d"])
            _append_hour_vector(features, "x1_load_base_d_minus_1", x1_base_vectors["x1_load_base_d_minus_1"])
            _append_hour_vector(features, "x1_load_base_d_minus_7", x1_base_vectors["x1_load_base_d_minus_7"])
            _append_hour_vector(features, "x2_res_base_d_minus_1", x2_base_vectors["x2_res_base_d_minus_1"])
            _append_hour_vector(features, "x2_res_base_d_minus_7", x2_base_vectors["x2_res_base_d_minus_7"])

            _append_hour_vector(features, "p_target_d_minus_7", p_target_d7)
            _append_hour_vector(features, "x1_load_target_d_minus_7", x1_target_d7)
            _append_hour_vector(features, "x2_res_target_d_minus_7", x2_target_d7)

            features.update({key: float(value) for key, value in _weekday_dummies(target_day).items()})
            features["target_weekend_flag"] = float(pd.Timestamp(target_day).dayofweek >= 5)
            features["target_month"] = float(pd.Timestamp(target_day).month)
            features["horizon_day"] = float(lead_day)
            for idx in config.lead_days:
                features[f"lead_day_{int(idx)}"] = float(int(idx == lead_day))

            # Hard feature gate against horizon policy and forbidden columns.
            for feat_name in features.keys():
                ok_policy, policy_reason = _policy_allows_feature(
                    policy=policy,
                    horizon_day=int(lead_day),
                    feature_name=str(feat_name),
                )
                if not ok_policy:
                    disallowed_attempts.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "target_delivery_local_date": target_day.isoformat(),
                            "forecast_origin_utc": origin_utc.isoformat(),
                            "horizon_day": int(lead_day),
                            "feature_name": feat_name,
                            "feature_family": _feature_family(feat_name),
                            "reason": policy_reason,
                            "policy_source_csv": policy.source_csv,
                        }
                    )

            forbidden_cols = [name for name in features.keys() if _is_forbidden_feature_col(name)]
            if forbidden_cols:
                for bad_col in forbidden_cols:
                    disallowed_attempts.append(
                        {
                            "delivery_start_local_date": base_d.isoformat(),
                            "target_delivery_local_date": target_day.isoformat(),
                            "forecast_origin_utc": origin_utc.isoformat(),
                            "horizon_day": int(lead_day),
                            "feature_name": bad_col,
                            "feature_family": _feature_family(bad_col),
                            "reason": "forbidden_column_name",
                            "policy_source_csv": policy.source_csv,
                        }
                    )

            for row in target_slice.to_dict(orient="records"):
                y_true = row.get(PRICE_VALUE_COL)
                if pd.isna(y_true):
                    continue
                target_hour = int(row["target_hour_local"]) if pd.notna(row["target_hour_local"]) else None
                if target_hour is None:
                    continue
                rows_x.append(dict(features))
                rows_y.append({"y_true": float(y_true)})
                rows_meta.append(
                    {
                        "forecast_origin_utc": origin_utc,
                        "forecast_origin_local": config.localized_forecast_origin_for_delivery_day(base_d),
                        "target_timestamp_utc": pd.Timestamp(row["timestamp_utc"]),
                        "target_delivery_local_date": target_day,
                        "target_hour_local": int(target_hour),
                        "lead_day": int(lead_day),
                        "lead_day_label": "D" if int(lead_day) == 0 else f"D+{int(lead_day)}",
                        "horizon_index": int((int(lead_day) * 24) + target_hour + 1),
                        "is_observed_target": True,
                    }
                )

    X_long = pd.DataFrame(rows_x)
    y_long = pd.DataFrame(rows_y)
    metadata_long = pd.DataFrame(rows_meta)
    skipped = pd.DataFrame(skipped_rows)
    violations = pd.DataFrame(known_at_violations)
    unavailable = pd.DataFrame(unavailable_exog)
    disallowed_df = pd.DataFrame(disallowed_attempts)

    forbidden_rows = []
    for col in X_long.columns if not X_long.empty else []:
        forbidden_rows.append(
            {
                "feature_name": col,
                "is_forbidden": bool(_is_forbidden_feature_col(col)),
            }
        )
    forbidden_df = pd.DataFrame(forbidden_rows)

    expected_feature_names = _expected_dplus4_feature_names(config)
    feature_names = list(X_long.columns) if not X_long.empty else expected_feature_names
    schema = {
        "model_variant": "LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE",
        "total_feature_count": int(len(feature_names)),
        "expected_feature_count": int(len(expected_feature_names)),
        "note": "D..D+4 direct no-future thesis extension; not exact Lago replication.",
        "feature_names": feature_names,
        "expected_feature_names": expected_feature_names,
        "horizon_policy_source_csv": policy.source_csv,
    }

    missing_rows: list[dict[str, Any]] = []
    if not X_long.empty and not metadata_long.empty:
        tmp = X_long.join(metadata_long[["lead_day"]])
        for lead_day, group in tmp.groupby("lead_day", dropna=False):
            for col in X_long.columns:
                s = pd.to_numeric(group[col], errors="coerce")
                missing_rows.append(
                    {
                        "lead_day": int(lead_day) if pd.notna(lead_day) else None,
                        "feature_name": col,
                        "feature_family": _feature_family(col),
                        "total_rows": int(s.shape[0]),
                        "missing_count": int(s.isna().sum()),
                        "missing_share": float(s.isna().mean()),
                    }
                )
    missing_summary = pd.DataFrame(missing_rows)
    availability_df = pd.DataFrame(availability_rows)

    if hard_fail_on_policy_violation and not disallowed_df.empty:
        sample = disallowed_df.head(5).to_dict(orient="records")
        raise RuntimeError(f"Strict horizon feature gate violation detected: {sample}")
    if hard_fail_on_policy_violation and not violations.empty:
        sample = violations.head(5).to_dict(orient="records")
        raise RuntimeError(f"known_at leakage violation detected in multiday feature build: {sample}")
    if hard_fail_on_policy_violation and not forbidden_df.empty and forbidden_df["is_forbidden"].any():
        bad = forbidden_df[forbidden_df["is_forbidden"]]["feature_name"].tolist()[:10]
        raise RuntimeError(f"Forbidden columns detected in multiday X_model: {bad}")

    return LagoMultidayFeatureMatrix(
        X_long=X_long,
        y_long=y_long,
        metadata_long=metadata_long,
        feature_schema=schema,
        skipped_rows=skipped,
        known_at_violations=violations,
        unavailable_exogenous_by_lead_day=unavailable,
        missing_feature_summary=missing_summary,
        disallowed_feature_attempts=disallowed_df,
        forbidden_columns_audit=forbidden_df,
        feature_availability_by_horizon=availability_df,
    )
