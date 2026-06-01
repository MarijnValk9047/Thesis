from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from hourly_da.core.metrics import add_error_columns, summarize_metrics_by_lead_day, summarize_metrics_by_reporting_level, summarize_overall_metrics


DEFAULT_TOPK_VALUES: tuple[int, ...] = (4, 8, 16)


def _require_columns(frame: pd.DataFrame, required: Iterable[str]) -> None:
    missing = sorted(column for column in required if column not in frame.columns)
    if missing:
        raise ValueError(f"Quarter-hour reporting frame is missing required columns: {missing}")


def _coerce_prediction_frame(
    predictions: pd.DataFrame,
    *,
    business_timezone: str = "Europe/Amsterdam",
) -> pd.DataFrame:
    _require_columns(
        predictions,
        (
            "model",
            "model_family",
            "fs_level",
            "dataset_split",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "y_true",
            "y_pred",
        ),
    )
    working = predictions.copy()
    working["forecast_origin_utc"] = pd.to_datetime(working["forecast_origin_utc"], utc=True, errors="coerce")
    working["target_timestamp_utc"] = pd.to_datetime(working["target_timestamp_utc"], utc=True, errors="coerce")
    if "lead_day" in working.columns:
        working["lead_day"] = pd.to_numeric(working["lead_day"], errors="coerce").astype("Int64")
    if "lead_day_label" not in working.columns and "lead_day" in working.columns:
        working["lead_day_label"] = working["lead_day"].map(lambda value: "D" if value == 0 else f"D+{int(value)}" if pd.notna(value) else None)
    working["y_true"] = pd.to_numeric(working["y_true"], errors="coerce")
    working["y_pred"] = pd.to_numeric(working["y_pred"], errors="coerce")
    working["target_timestamp_local"] = working["target_timestamp_utc"].dt.tz_convert(business_timezone)
    if "target_local_date" not in working.columns:
        working["target_local_date"] = working["target_timestamp_local"].dt.date
    else:
        working["target_local_date"] = pd.to_datetime(working["target_local_date"], errors="coerce").dt.date
    if "hour_of_day" not in working.columns:
        working["hour_of_day"] = working["target_timestamp_local"].dt.hour.astype("Int64")
    if "quarter_in_hour" not in working.columns:
        working["quarter_in_hour"] = (working["target_timestamp_local"].dt.minute // 15 + 1).astype("Int64")
    if "is_observed_target" not in working.columns:
        working["is_observed_target"] = working["y_true"].notna()
    else:
        working["is_observed_target"] = working["is_observed_target"].fillna(False).astype(bool)
    return working


def _daily_group_columns(predictions: pd.DataFrame) -> list[str]:
    group_cols = ["model", "model_family", "fs_level", "dataset_split", "target_local_date"]
    if "lead_day" in predictions.columns:
        group_cols.extend(["lead_day", "lead_day_label"])
    return group_cols


def summarize_standard_qh_metrics(
    predictions: pd.DataFrame,
    *,
    business_timezone: str = "Europe/Amsterdam",
) -> dict[str, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    scored = add_error_columns(working)
    return {
        "metrics_overall": summarize_overall_metrics(scored),
        "metrics_by_lead_day": summarize_metrics_by_lead_day(scored) if "lead_day" in scored.columns else pd.DataFrame(),
        "metrics_by_reporting_level": summarize_metrics_by_reporting_level(scored) if "lead_day" in scored.columns else pd.DataFrame(),
    }


def compute_topk_hit_rate_metrics(
    predictions: pd.DataFrame,
    *,
    ks: tuple[int, ...] = DEFAULT_TOPK_VALUES,
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["quarters_scored"] = int(valid.shape[0])
        for k in ks:
            if valid.shape[0] < int(k):
                row[f"top{k}_high_hit_rate"] = np.nan
                row[f"top{k}_high_miss_rate"] = np.nan
                row[f"top{k}_low_hit_rate"] = np.nan
                row[f"top{k}_low_miss_rate"] = np.nan
                continue
            actual_high = set(pd.to_datetime(valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[False, True]).head(k)["target_timestamp_utc"], utc=True).tolist())
            pred_high = set(pd.to_datetime(valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[False, True]).head(k)["target_timestamp_utc"], utc=True).tolist())
            actual_low = set(pd.to_datetime(valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[True, True]).head(k)["target_timestamp_utc"], utc=True).tolist())
            pred_low = set(pd.to_datetime(valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[True, True]).head(k)["target_timestamp_utc"], utc=True).tolist())
            high_hit = float(len(actual_high & pred_high) / int(k))
            low_hit = float(len(actual_low & pred_low) / int(k))
            row[f"top{k}_high_hit_rate"] = high_hit
            row[f"top{k}_high_miss_rate"] = 1.0 - high_hit
            row[f"top{k}_low_hit_rate"] = low_hit
            row[f"top{k}_low_miss_rate"] = 1.0 - low_hit
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    agg_map: dict[str, tuple[str, object]] = {"days": ("target_local_date", "nunique")}
    for k in ks:
        for prefix in ("high", "low"):
            agg_map[f"valid_top{k}_{prefix}_days"] = (f"top{k}_{prefix}_hit_rate", lambda values: int(pd.Series(values).notna().sum()))
            agg_map[f"mean_top{k}_{prefix}_hit_rate"] = (f"top{k}_{prefix}_hit_rate", "mean")
            agg_map[f"mean_top{k}_{prefix}_miss_rate"] = (f"top{k}_{prefix}_miss_rate", "mean")
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(**agg_map)
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_extreme_event_metrics(
    predictions: pd.DataFrame,
    *,
    upper_quantiles: tuple[float, ...] = (0.90, 0.95),
    lower_quantiles: tuple[float, ...] = (0.10, 0.05),
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        base_row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        base_row["quarters_scored"] = int(valid.shape[0])
        if valid.empty:
            rows.append(base_row)
            continue
        for q in upper_quantiles:
            actual_threshold = float(valid["y_true"].quantile(float(q)))
            forecast_threshold = float(valid["y_pred"].quantile(float(q)))
            actual_event = valid["y_true"] >= actual_threshold
            forecast_event = valid["y_pred"] >= forecast_threshold
            tp = int((actual_event & forecast_event).sum())
            fp = int((~actual_event & forecast_event).sum())
            fn = int((actual_event & ~forecast_event).sum())
            precision = float(tp / (tp + fp)) if (tp + fp) > 0 else np.nan
            recall = float(tp / (tp + fn)) if (tp + fn) > 0 else np.nan
            f1 = float(2 * precision * recall / (precision + recall)) if pd.notna(precision) and pd.notna(recall) and (precision + recall) > 0 else np.nan
            label = f"q{int(q * 100)}"
            base_row[f"high_{label}_precision"] = precision
            base_row[f"high_{label}_recall"] = recall
            base_row[f"high_{label}_f1"] = f1
        for q in lower_quantiles:
            actual_threshold = float(valid["y_true"].quantile(float(q)))
            forecast_threshold = float(valid["y_pred"].quantile(float(q)))
            actual_event = valid["y_true"] <= actual_threshold
            forecast_event = valid["y_pred"] <= forecast_threshold
            tp = int((actual_event & forecast_event).sum())
            fp = int((~actual_event & forecast_event).sum())
            fn = int((actual_event & ~forecast_event).sum())
            precision = float(tp / (tp + fp)) if (tp + fp) > 0 else np.nan
            recall = float(tp / (tp + fn)) if (tp + fn) > 0 else np.nan
            f1 = float(2 * precision * recall / (precision + recall)) if pd.notna(precision) and pd.notna(recall) and (precision + recall) > 0 else np.nan
            label = f"q{int(q * 100)}"
            base_row[f"low_{label}_precision"] = precision
            base_row[f"low_{label}_recall"] = recall
            base_row[f"low_{label}_f1"] = f1
        rows.append(base_row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    numeric_cols = [column for column in daily.columns if any(token in column for token in ("_precision", "_recall", "_f1"))]
    agg_map = {"days": ("target_local_date", "nunique")}
    agg_map.update({f"mean_{column}": (column, "mean") for column in numeric_cols})
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(**agg_map)
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_rank_correlation_metrics(
    predictions: pd.DataFrame,
    *,
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["quarters_scored"] = int(valid.shape[0])
        if valid.shape[0] < 2:
            row["spearman_rank_corr"] = np.nan
        else:
            predicted_std = float(valid["y_pred"].std(ddof=0))
            actual_std = float(valid["y_true"].std(ddof=0))
            row["spearman_rank_corr"] = (
                float(valid["y_true"].corr(valid["y_pred"], method="spearman"))
                if actual_std > 1e-12 and predicted_std > 1e-12
                else np.nan
            )
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(
            days=("target_local_date", "nunique"),
            valid_spearman_days=("spearman_rank_corr", lambda values: int(pd.Series(values).notna().sum())),
            mean_spearman_rank_corr=("spearman_rank_corr", "mean"),
        )
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_mean_rank_error_of_actual_extremes(
    predictions: pd.DataFrame,
    *,
    ks: tuple[int, ...] = DEFAULT_TOPK_VALUES,
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["quarters_scored"] = int(valid.shape[0])
        if valid.empty:
            rows.append(row)
            continue
        predicted_desc = valid["y_pred"].rank(method="first", ascending=False)
        predicted_asc = valid["y_pred"].rank(method="first", ascending=True)
        actual_desc = valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[False, True]).reset_index()
        actual_asc = valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[True, True]).reset_index()
        for k in ks:
            if valid.shape[0] < int(k):
                row[f"top{k}_actual_high_mean_forecast_rank"] = np.nan
                row[f"top{k}_actual_low_mean_forecast_rank"] = np.nan
                continue
            high_idx = actual_desc.head(k)["index"].tolist()
            low_idx = actual_asc.head(k)["index"].tolist()
            row[f"top{k}_actual_high_mean_forecast_rank"] = float(predicted_desc.loc[high_idx].mean())
            row[f"top{k}_actual_low_mean_forecast_rank"] = float(predicted_asc.loc[low_idx].mean())
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    agg_map = {"days": ("target_local_date", "nunique")}
    for k in ks:
        agg_map[f"mean_top{k}_actual_high_mean_forecast_rank"] = (f"top{k}_actual_high_mean_forecast_rank", "mean")
        agg_map[f"mean_top{k}_actual_low_mean_forecast_rank"] = (f"top{k}_actual_low_mean_forecast_rank", "mean")
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(**agg_map)
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_tail_mae_metrics(
    predictions: pd.DataFrame,
    *,
    lower_quantile: float = 0.10,
    upper_quantile: float = 0.90,
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = add_error_columns(_coerce_prediction_frame(predictions, business_timezone=business_timezone))
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["quarters_scored"] = int(valid.shape[0])
        if valid.empty:
            rows.append(row)
            continue
        low_threshold = float(valid["y_true"].quantile(float(lower_quantile)))
        high_threshold = float(valid["y_true"].quantile(float(upper_quantile)))
        low_mask = valid["y_true"] <= low_threshold
        high_mask = valid["y_true"] >= high_threshold
        middle_mask = (~low_mask) & (~high_mask)
        row["tail_mae_top_10pct"] = float(valid.loc[high_mask, "abs_error"].mean()) if high_mask.any() else np.nan
        row["tail_mae_bottom_10pct"] = float(valid.loc[low_mask, "abs_error"].mean()) if low_mask.any() else np.nan
        row["tail_mae_middle_80pct"] = float(valid.loc[middle_mask, "abs_error"].mean()) if middle_mask.any() else np.nan
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(
            days=("target_local_date", "nunique"),
            mean_tail_mae_top_10pct=("tail_mae_top_10pct", "mean"),
            mean_tail_mae_bottom_10pct=("tail_mae_bottom_10pct", "mean"),
            mean_tail_mae_middle_80pct=("tail_mae_middle_80pct", "mean"),
        )
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_high_low_spread_error_metrics(
    predictions: pd.DataFrame,
    *,
    ks: tuple[int, ...] = DEFAULT_TOPK_VALUES,
    business_timezone: str = "Europe/Amsterdam",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = _coerce_prediction_frame(predictions, business_timezone=business_timezone)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(_daily_group_columns(working), dropna=False):
        row = dict(zip(_daily_group_columns(working), keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["quarters_scored"] = int(valid.shape[0])
        for k in ks:
            if valid.shape[0] < int(k):
                row[f"top{k}_actual_spread"] = np.nan
                row[f"top{k}_forecast_spread"] = np.nan
                row[f"top{k}_spread_error"] = np.nan
                continue
            actual_high_mean = float(valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[False, True]).head(k)["y_true"].mean())
            actual_low_mean = float(valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[True, True]).head(k)["y_true"].mean())
            pred_high_mean = float(valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[False, True]).head(k)["y_pred"].mean())
            pred_low_mean = float(valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[True, True]).head(k)["y_pred"].mean())
            actual_spread = actual_high_mean - actual_low_mean
            forecast_spread = pred_high_mean - pred_low_mean
            row[f"top{k}_actual_spread"] = actual_spread
            row[f"top{k}_forecast_spread"] = forecast_spread
            row[f"top{k}_spread_error"] = forecast_spread - actual_spread
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["dataset_split", "target_local_date", "model"]).reset_index(drop=True) if rows else pd.DataFrame()
    if daily.empty:
        return daily, pd.DataFrame()
    agg_map = {"days": ("target_local_date", "nunique")}
    for k in ks:
        agg_map[f"mean_top{k}_actual_spread"] = (f"top{k}_actual_spread", "mean")
        agg_map[f"mean_top{k}_forecast_spread"] = (f"top{k}_forecast_spread", "mean")
        agg_map[f"mean_top{k}_spread_error"] = (f"top{k}_spread_error", "mean")
        agg_map[f"mean_abs_top{k}_spread_error"] = (f"top{k}_spread_error", lambda values: float(pd.Series(values).abs().mean()))
    summary = (
        daily.groupby([column for column in _daily_group_columns(working) if column != "target_local_date"], dropna=False)
        .agg(**agg_map)
        .reset_index()
        .sort_values(["dataset_split", "model"])
        .reset_index(drop=True)
    )
    return daily, summary


def build_qh_phase2_reporting_bundle(
    predictions: pd.DataFrame,
    *,
    business_timezone: str = "Europe/Amsterdam",
    ks: tuple[int, ...] = DEFAULT_TOPK_VALUES,
) -> dict[str, pd.DataFrame]:
    standard = summarize_standard_qh_metrics(predictions, business_timezone=business_timezone)
    topk_daily, topk_summary = compute_topk_hit_rate_metrics(predictions, ks=ks, business_timezone=business_timezone)
    extreme_daily, extreme_summary = compute_extreme_event_metrics(predictions, business_timezone=business_timezone)
    spearman_daily, spearman_summary = compute_rank_correlation_metrics(predictions, business_timezone=business_timezone)
    rank_error_daily, rank_error_summary = compute_mean_rank_error_of_actual_extremes(predictions, ks=ks, business_timezone=business_timezone)
    tail_daily, tail_summary = compute_tail_mae_metrics(predictions, business_timezone=business_timezone)
    spread_daily, spread_summary = compute_high_low_spread_error_metrics(predictions, ks=ks, business_timezone=business_timezone)
    return {
        **standard,
        "topk_daily_metrics": topk_daily,
        "ranking_opportunity_metrics": topk_summary,
        "extreme_event_daily_metrics": extreme_daily,
        "extreme_event_summary": extreme_summary,
        "spearman_daily_metrics": spearman_daily,
        "spearman_summary": spearman_summary,
        "mean_rank_error_daily_metrics": rank_error_daily,
        "mean_rank_error_summary": rank_error_summary,
        "tail_mae_daily_metrics": tail_daily,
        "tail_mae_summary": tail_summary,
        "spread_error_daily_metrics": spread_daily,
        "spread_error_summary": spread_summary,
    }


def smoke_check_qh_phase2_reporting(
    predictions: pd.DataFrame,
    *,
    business_timezone: str = "Europe/Amsterdam",
) -> pd.DataFrame:
    bundle = build_qh_phase2_reporting_bundle(predictions, business_timezone=business_timezone)
    checks = [
        {
            "check_name": "standard_metrics_non_empty",
            "status": "pass" if not bundle["metrics_overall"].empty else "fail",
            "details": f"rows={int(bundle['metrics_overall'].shape[0])}",
        },
        {
            "check_name": "ranking_metrics_non_empty",
            "status": "pass" if not bundle["ranking_opportunity_metrics"].empty else "fail",
            "details": f"rows={int(bundle['ranking_opportunity_metrics'].shape[0])}",
        },
        {
            "check_name": "spearman_summary_non_empty",
            "status": "pass" if not bundle["spearman_summary"].empty else "fail",
            "details": f"rows={int(bundle['spearman_summary'].shape[0])}",
        },
        {
            "check_name": "tail_mae_summary_non_empty",
            "status": "pass" if not bundle["tail_mae_summary"].empty else "fail",
            "details": f"rows={int(bundle['tail_mae_summary'].shape[0])}",
        },
        {
            "check_name": "spread_error_summary_non_empty",
            "status": "pass" if not bundle["spread_error_summary"].empty else "fail",
            "details": f"rows={int(bundle['spread_error_summary'].shape[0])}",
        },
    ]
    return pd.DataFrame(checks)
