from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import HourlyDAPipelineConfig
from .metrics import add_rmae_column


WEEKLY_FEATURE_COLUMNS = [
    "weekly_mean_price",
    "weekly_std_price",
    "weekly_min_price",
    "weekly_max_price",
    "weekly_range",
    "negative_hours_count",
    "negative_hours_share",
    "mean_abs_hourly_change",
    "p95_abs_hourly_change",
    "very_high_price_hours_count",
]


def prepare_test_actuals(canonical_frame: pd.DataFrame, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    actuals = canonical_frame[[config.timestamp_col, config.target_col, "is_observed_target"]].copy()
    actuals[config.timestamp_col] = pd.to_datetime(actuals[config.timestamp_col], utc=True)
    actuals["timestamp_local"] = actuals[config.timestamp_col].dt.tz_convert(config.resolved_business_timezone())
    actuals["local_delivery_date"] = actuals["timestamp_local"].dt.date
    actuals["dataset_split"] = actuals["local_delivery_date"].map(config.split_for_local_date)
    actuals = actuals[actuals["dataset_split"] == "test"].copy()
    return actuals.reset_index(drop=True)


def build_weekly_feature_table(canonical_frame: pd.DataFrame, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    actuals = prepare_test_actuals(canonical_frame, config)
    iso = actuals["timestamp_local"].dt.isocalendar()
    actuals["iso_year"] = iso["year"].astype(int)
    actuals["iso_week"] = iso["week"].astype(int)
    actuals["iso_day"] = iso["day"].astype(int)

    rows: list[dict[str, object]] = []
    for (iso_year, iso_week), group in actuals.groupby(["iso_year", "iso_week"], dropna=False):
        week_start_local_date = date.fromisocalendar(int(iso_year), int(iso_week), 1)
        week_end_local_date = week_start_local_date + timedelta(days=6)
        if week_start_local_date < config.test_start_local or week_end_local_date > config.test_end_local:
            continue

        values = group[config.target_col].astype(float)
        observed = values.dropna()
        abs_changes = values.diff().abs().dropna()
        midpoint_date = week_start_local_date + timedelta(days=3)
        midpoint_month = midpoint_date.month
        if midpoint_month in (12, 1, 2):
            season = "winter"
        elif midpoint_month in (6, 7, 8):
            season = "summer"
        else:
            season = "shoulder"

        rows.append(
            {
                "iso_year": int(iso_year),
                "iso_week": int(iso_week),
                "iso_week_id": f"{int(iso_year)}-W{int(iso_week):02d}",
                "week_start_local_date": week_start_local_date.isoformat(),
                "week_end_local_date": week_end_local_date.isoformat(),
                "week_midpoint_local_date": midpoint_date.isoformat(),
                "season": season,
                "expected_hours": int(group.shape[0]),
                "observed_hours": int(observed.shape[0]),
                "observed_coverage_pct": float(observed.shape[0] / group.shape[0] * 100.0),
                "weekly_mean_price": float(observed.mean()) if not observed.empty else np.nan,
                "weekly_std_price": float(observed.std(ddof=0)) if not observed.empty else np.nan,
                "weekly_min_price": float(observed.min()) if not observed.empty else np.nan,
                "weekly_max_price": float(observed.max()) if not observed.empty else np.nan,
                "weekly_range": float(observed.max() - observed.min()) if not observed.empty else np.nan,
                "negative_hours_count": int((observed < 0.0).sum()),
                "negative_hours_share": float((observed < 0.0).mean()) if not observed.empty else np.nan,
                "mean_abs_hourly_change": float(abs_changes.mean()) if not abs_changes.empty else np.nan,
                "p95_abs_hourly_change": float(abs_changes.quantile(0.95)) if not abs_changes.empty else np.nan,
                "very_high_price_hours_count": int((observed >= config.visual_week_high_price_threshold).sum()),
            }
        )

    weekly = pd.DataFrame(rows)
    if weekly.empty:
        return weekly
    return weekly.sort_values(["week_start_local_date"]).reset_index(drop=True)


def _rank_by_centroid_distance(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()

    values = candidates[WEEKLY_FEATURE_COLUMNS].astype(float)
    means = values.mean(axis=0)
    stds = values.std(axis=0, ddof=0).replace(0.0, 1.0)
    z_scores = (values - means) / stds
    ranked = candidates.copy()
    ranked["selection_score"] = np.sqrt((z_scores**2).sum(axis=1))
    ranked = ranked.sort_values(["selection_score", "week_start_local_date"]).reset_index(drop=True)
    ranked["candidate_rank"] = ranked.index + 1
    return ranked


def _rank_by_sort(
    candidates: pd.DataFrame,
    sort_cols: list[str],
    ascending: list[bool],
    selection_score_col: str,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    ranked = candidates.sort_values(sort_cols, ascending=ascending).reset_index(drop=True).copy()
    ranked["selection_score"] = ranked[selection_score_col].astype(float)
    ranked["candidate_rank"] = ranked.index + 1
    return ranked


def select_case_weeks(weekly_features: pd.DataFrame, config: HourlyDAPipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if weekly_features.empty:
        return pd.DataFrame(), pd.DataFrame()

    eligible = weekly_features[weekly_features["observed_coverage_pct"] >= config.visual_week_min_observed_coverage_pct].copy()
    candidate_frames: list[pd.DataFrame] = []
    selected_frames: list[pd.DataFrame] = []
    selected_week_ids: set[str] = set()

    def _append_category(category: str, ranked: pd.DataFrame) -> None:
        nonlocal candidate_frames, selected_frames, selected_week_ids
        if ranked.empty:
            return
        ranked = ranked.copy()
        ranked["category"] = category
        candidate_frames.append(ranked.head(5))
        distinct = ranked[~ranked["iso_week_id"].isin(selected_week_ids)].copy()
        chosen = distinct.head(1) if not distinct.empty else ranked.head(1)
        if not chosen.empty:
            selected_frames.append(chosen)
            selected_week_ids.update(chosen["iso_week_id"].astype(str).tolist())

    winter_ranked = _rank_by_centroid_distance(eligible[eligible["season"] == "winter"].copy())
    _append_category("typical_winter", winter_ranked)

    summer_ranked = _rank_by_centroid_distance(eligible[eligible["season"] == "summer"].copy())
    _append_category("typical_summer", summer_ranked)

    volatility_ranked = _rank_by_sort(
        eligible.copy(),
        sort_cols=["weekly_std_price", "week_start_local_date"],
        ascending=[False, True],
        selection_score_col="weekly_std_price",
    )
    _append_category("high_volatility", volatility_ranked)

    high_price_ranked = _rank_by_sort(
        eligible.copy(),
        sort_cols=["weekly_mean_price", "very_high_price_hours_count", "week_start_local_date"],
        ascending=[False, False, True],
        selection_score_col="weekly_mean_price",
    )
    _append_category("high_price", high_price_ranked)

    low_price_ranked = _rank_by_sort(
        eligible.copy(),
        sort_cols=["weekly_mean_price", "negative_hours_share", "week_start_local_date"],
        ascending=[True, False, True],
        selection_score_col="weekly_mean_price",
    )
    _append_category("low_price", low_price_ranked)

    negative_price_ranked = _rank_by_sort(
        eligible[eligible["negative_hours_count"] > 0].copy(),
        sort_cols=["negative_hours_share", "negative_hours_count", "weekly_mean_price", "week_start_local_date"],
        ascending=[False, False, True, True],
        selection_score_col="negative_hours_share",
    )
    _append_category("negative_price", negative_price_ranked)

    candidates = (
        pd.concat(candidate_frames, ignore_index=True).sort_values(["category", "candidate_rank"]).reset_index(drop=True)
        if candidate_frames
        else pd.DataFrame()
    )
    selected = (
        pd.concat(selected_frames, ignore_index=True).sort_values(["category"]).reset_index(drop=True)
        if selected_frames
        else pd.DataFrame()
    )
    return candidates, selected


def build_stitched_day_ahead_predictions(predictions: pd.DataFrame, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    stitched = predictions[(predictions["dataset_split"] == "test") & (predictions["lead_day"] == 0)].copy()
    if stitched.empty:
        return stitched

    stitched["target_timestamp_utc"] = pd.to_datetime(stitched["target_timestamp_utc"], utc=True)
    stitched["forecast_origin_utc"] = pd.to_datetime(stitched["forecast_origin_utc"], utc=True)
    stitched["target_timestamp_local"] = stitched["target_timestamp_utc"].dt.tz_convert(config.resolved_business_timezone())
    stitched["target_local_date"] = stitched["target_timestamp_local"].dt.date
    stitched = stitched.sort_values(["model", "target_timestamp_utc", "forecast_origin_utc"]).drop_duplicates(
        subset=["model", "target_timestamp_utc"], keep="last"
    )
    return stitched.reset_index(drop=True)


def filter_week_window(
    frame: pd.DataFrame,
    week_start_local_date: str,
    week_end_local_date: str,
    timestamp_col: str,
) -> pd.DataFrame:
    start_date = pd.Timestamp(week_start_local_date).date()
    end_date = pd.Timestamp(week_end_local_date).date()
    series = frame[timestamp_col]
    if not pd.api.types.is_datetime64_any_dtype(series):
        series = pd.to_datetime(series)
    local_dates = series.dt.date
    return frame[(local_dates >= start_date) & (local_dates <= end_date)].copy()


def summarize_week_metrics(
    stitched_predictions: pd.DataFrame,
    selected_weeks: pd.DataFrame,
    model_order: list[str] | None = None,
    benchmark_model: str | None = None,
) -> pd.DataFrame:
    empty_columns = [
        "category",
        "iso_week_id",
        "week_start_local_date",
        "week_end_local_date",
        "model",
        "observations_total",
        "observations_scored",
        "coverage_pct",
        "mae",
        "rmse",
        "bias",
        "rmae_vs_official_naive",
        "rmae",
        "max_abs_error",
        "mae_rank",
        "rmse_rank",
        "abs_bias_rank",
        "max_abs_error_rank",
    ]
    if stitched_predictions.empty or selected_weeks.empty:
        return pd.DataFrame(columns=empty_columns)

    rows: list[dict[str, object]] = []
    for week_row in selected_weeks.to_dict(orient="records"):
        week_predictions = filter_week_window(
            stitched_predictions,
            week_start_local_date=str(week_row["week_start_local_date"]),
            week_end_local_date=str(week_row["week_end_local_date"]),
            timestamp_col="target_timestamp_local",
        )
        for model_name, group in week_predictions.groupby("model", dropna=False):
            valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
            if valid.empty:
                mae = np.nan
                rmse = np.nan
                bias = np.nan
                max_abs_error = np.nan
                scored = 0
            else:
                errors = valid["y_pred"] - valid["y_true"]
                mae = float(errors.abs().mean())
                rmse = float(np.sqrt((errors**2).mean()))
                bias = float(errors.mean())
                max_abs_error = float(errors.abs().max())
                scored = int(valid.shape[0])

            rows.append(
                {
                    "category": week_row["category"],
                    "iso_week_id": week_row["iso_week_id"],
                    "week_start_local_date": week_row["week_start_local_date"],
                    "week_end_local_date": week_row["week_end_local_date"],
                    "model": model_name,
                    "observations_total": int(group.shape[0]),
                    "observations_scored": scored,
                    "coverage_pct": float(scored / group.shape[0] * 100.0) if group.shape[0] else 0.0,
                    "mae": mae,
                    "rmse": rmse,
                    "bias": bias,
                    "max_abs_error": max_abs_error,
                }
            )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return pd.DataFrame(columns=empty_columns)

    week_group_cols = [
        "category",
        "iso_week_id",
        "week_start_local_date",
        "week_end_local_date",
    ]
    if benchmark_model:
        summary = add_rmae_column(
            summary,
            benchmark_model=str(benchmark_model),
            group_keys=week_group_cols,
        )
    else:
        summary["rmae_vs_official_naive"] = np.nan
        summary["rmae"] = np.nan

    summary["mae_rank"] = summary.groupby(week_group_cols, dropna=False)["mae"].rank(method="dense", ascending=True)
    summary["rmse_rank"] = summary.groupby(week_group_cols, dropna=False)["rmse"].rank(method="dense", ascending=True)
    summary["abs_bias_rank"] = (
        summary.assign(_abs_bias=summary["bias"].abs())
        .groupby(week_group_cols, dropna=False)["_abs_bias"]
        .rank(method="dense", ascending=True)
    )
    summary["max_abs_error_rank"] = summary.groupby(week_group_cols, dropna=False)["max_abs_error"].rank(
        method="dense",
        ascending=True,
    )
    for column in ["mae_rank", "rmse_rank", "abs_bias_rank", "max_abs_error_rank"]:
        summary[column] = summary[column].astype("Int64")

    if model_order:
        order_map = {model_name: position for position, model_name in enumerate(model_order)}
        return (
            summary.assign(_model_order=lambda frame: frame["model"].map(order_map).fillna(len(order_map)))
            .sort_values(["category", "_model_order", "model"])
            .drop(columns=["_model_order"])
            .reset_index(drop=True)
        )
    return summary.sort_values(["category", "model"]).reset_index(drop=True)


def build_week_winner_summary(
    week_metrics: pd.DataFrame,
    model_order: list[str] | None = None,
) -> pd.DataFrame:
    empty_columns = [
        "category",
        "iso_week_id",
        "week_start_local_date",
        "week_end_local_date",
        "best_mae_model",
        "best_mae",
        "best_rmse_model",
        "best_rmse",
        "lowest_abs_bias_model",
        "lowest_abs_bias",
        "lowest_max_abs_error_model",
        "lowest_max_abs_error",
    ]
    if week_metrics.empty:
        return pd.DataFrame(columns=empty_columns)

    work = week_metrics.copy()
    order_map = {model_name: position for position, model_name in enumerate(model_order or [])}
    work["_model_order"] = work["model"].map(order_map).fillna(len(order_map))
    work["_abs_bias"] = work["bias"].abs()

    group_cols = [
        "category",
        "iso_week_id",
        "week_start_local_date",
        "week_end_local_date",
    ]

    def _pick_best(group: pd.DataFrame, value_col: str) -> tuple[str | None, float]:
        valid = group[group[value_col].notna()].copy()
        if valid.empty:
            return None, np.nan
        chosen = valid.sort_values([value_col, "_model_order", "model"]).iloc[0]
        return str(chosen["model"]), float(chosen[value_col])

    rows: list[dict[str, object]] = []
    for keys, group in work.groupby(group_cols, dropna=False):
        best_mae_model, best_mae = _pick_best(group, "mae")
        best_rmse_model, best_rmse = _pick_best(group, "rmse")
        lowest_abs_bias_model, lowest_abs_bias = _pick_best(group, "_abs_bias")
        lowest_max_abs_error_model, lowest_max_abs_error = _pick_best(group, "max_abs_error")
        row = dict(zip(group_cols, keys, strict=True))
        row.update(
            {
                "best_mae_model": best_mae_model,
                "best_mae": best_mae,
                "best_rmse_model": best_rmse_model,
                "best_rmse": best_rmse,
                "lowest_abs_bias_model": lowest_abs_bias_model,
                "lowest_abs_bias": lowest_abs_bias,
                "lowest_max_abs_error_model": lowest_max_abs_error_model,
                "lowest_max_abs_error": lowest_max_abs_error,
            }
        )
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["category"]).reset_index(drop=True)
