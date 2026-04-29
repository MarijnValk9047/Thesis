from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HourlyDAPipelineConfig


RAW_LAG_FEATURES = ("lag_1", "lag_2", "lag_24", "lag_25", "lag_168", "lag_169")
MOMENTUM_FEATURES = ("diff_1", "diff_24", "diff_168", "cross_season_diff")
ROLLING_FEATURES = ("roll_mean_24", "roll_std_24", "roll_mean_168", "roll_std_168")
DAY_BLOCK_FEATURES = ("day_min_24", "day_max_24", "day_range_24", "neg_share_24")
WEEK_BLOCK_FEATURES = ("week_min_block", "week_max_block", "week_range_block", "neg_share_week_block")
ENDOGENOUS_EXPLICIT_FEATURES = (
    *RAW_LAG_FEATURES,
    *MOMENTUM_FEATURES,
    *ROLLING_FEATURES,
    *DAY_BLOCK_FEATURES,
    *WEEK_BLOCK_FEATURES,
)
PREVIOUS_WEEK_BLOCK_START_LAG_HOURS = 168
PREVIOUS_WEEK_BLOCK_END_LAG_HOURS = 145
PREVIOUS_WEEK_BLOCK_SHIFT_HOURS = 145
PREVIOUS_WEEK_BLOCK_LENGTH_HOURS = 24
ENDOGENOUS_REQUIRED_HISTORY_HOURS = 336


@dataclass(frozen=True)
class EndogenousFeatureSummary:
    feature_catalog: pd.DataFrame
    missingness_table: pd.DataFrame
    row_loss_table: pd.DataFrame
    summary_statistics: pd.DataFrame
    feature_target_correlations: pd.DataFrame
    feature_correlation_matrix: pd.DataFrame
    metadata_summary: dict[str, object]


def endogenous_explicit_feature_names() -> list[str]:
    return list(ENDOGENOUS_EXPLICIT_FEATURES)


def endogenous_required_history_hours(config: HourlyDAPipelineConfig | None = None) -> int:
    if config is not None:
        return int(config.endogenous_max_lookback_hours)
    return ENDOGENOUS_REQUIRED_HISTORY_HOURS


def feature_catalog_frame() -> pd.DataFrame:
    rows = [
        {
            "feature_name": "lag_1",
            "role_group": "Short-memory persistence",
            "formula": "y[t-1]",
            "plain_language_meaning": "The most recent hourly DA price.",
            "time_window_used": "1 hour before t",
            "why_included": "Captures very short-run persistence.",
        },
        {
            "feature_name": "lag_2",
            "role_group": "Short-memory persistence",
            "formula": "y[t-2]",
            "plain_language_meaning": "The DA price two hours ago.",
            "time_window_used": "2 hours before t",
            "why_included": "Adds one more step of short-run memory without creating a large lag buffet.",
        },
        {
            "feature_name": "lag_24",
            "role_group": "Daily and weekly anchor structure",
            "formula": "y[t-24]",
            "plain_language_meaning": "The price at the same UTC hour one day earlier.",
            "time_window_used": "24 hours before t",
            "why_included": "Anchors the model to yesterday's hourly pattern.",
        },
        {
            "feature_name": "lag_25",
            "role_group": "Daily and weekly anchor structure",
            "formula": "y[t-25]",
            "plain_language_meaning": "The hour just before yesterday's same-hour anchor.",
            "time_window_used": "25 hours before t",
            "why_included": "Adds local context around the daily anchor without opening a very wide lag set.",
        },
        {
            "feature_name": "lag_168",
            "role_group": "Daily and weekly anchor structure",
            "formula": "y[t-168]",
            "plain_language_meaning": "The price at the same UTC hour one week earlier.",
            "time_window_used": "168 hours before t",
            "why_included": "Anchors the model to the comparable hour last week.",
        },
        {
            "feature_name": "lag_169",
            "role_group": "Daily and weekly anchor structure",
            "formula": "y[t-169]",
            "plain_language_meaning": "The hour just before last week's same-hour anchor.",
            "time_window_used": "169 hours before t",
            "why_included": "Adds context around the weekly anchor in a compact way.",
        },
        {
            "feature_name": "diff_1",
            "role_group": "Recent momentum and regime shifts",
            "formula": "y[t-1] - y[t-2]",
            "plain_language_meaning": "The most recent one-hour price change.",
            "time_window_used": "Hours t-2 to t-1",
            "why_included": "Captures immediate momentum or reversal.",
        },
        {
            "feature_name": "diff_24",
            "role_group": "Recent momentum and regime shifts",
            "formula": "y[t-24] - y[t-48]",
            "plain_language_meaning": "How yesterday's same-hour price compares with two days ago.",
            "time_window_used": "24 and 48 hours before t",
            "why_included": "Measures short seasonal acceleration across days.",
        },
        {
            "feature_name": "diff_168",
            "role_group": "Recent momentum and regime shifts",
            "formula": "y[t-168] - y[t-336]",
            "plain_language_meaning": "How last week's same-hour price compares with two weeks ago.",
            "time_window_used": "168 and 336 hours before t",
            "why_included": "Captures slower weekly regime drift.",
        },
        {
            "feature_name": "cross_season_diff",
            "role_group": "Daily and weekly anchor structure",
            "formula": "y[t-24] - y[t-168]",
            "plain_language_meaning": "The gap between yesterday's and last week's same-hour anchors.",
            "time_window_used": "24 and 168 hours before t",
            "why_included": "Shows whether the daily and weekly anchor structures currently disagree.",
        },
        {
            "feature_name": "roll_mean_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "mean(y[t-24], ..., y[t-1])",
            "plain_language_meaning": "Average price in the previous 24 hours, excluding t itself.",
            "time_window_used": "Strictly causal 24-hour window",
            "why_included": "Summarizes the recent daily level.",
        },
        {
            "feature_name": "roll_std_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "std(y[t-24], ..., y[t-1])",
            "plain_language_meaning": "Price dispersion in the previous 24 hours, excluding t itself.",
            "time_window_used": "Strictly causal 24-hour window",
            "why_included": "Measures short-run volatility.",
        },
        {
            "feature_name": "roll_mean_168",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "mean(y[t-168], ..., y[t-1])",
            "plain_language_meaning": "Average price in the previous 168 hours, excluding t itself.",
            "time_window_used": "Strictly causal 168-hour window",
            "why_included": "Summarizes the recent weekly regime level.",
        },
        {
            "feature_name": "roll_std_168",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "std(y[t-168], ..., y[t-1])",
            "plain_language_meaning": "Price dispersion in the previous 168 hours, excluding t itself.",
            "time_window_used": "Strictly causal 168-hour window",
            "why_included": "Measures broader recent volatility.",
        },
        {
            "feature_name": "day_min_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "min(y[t-24], ..., y[t-1])",
            "plain_language_meaning": "Minimum price over the previous 24 hours.",
            "time_window_used": "Previous-day block [t-24, t-1]",
            "why_included": "Summarizes the recent downside level.",
        },
        {
            "feature_name": "day_max_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "max(y[t-24], ..., y[t-1])",
            "plain_language_meaning": "Maximum price over the previous 24 hours.",
            "time_window_used": "Previous-day block [t-24, t-1]",
            "why_included": "Summarizes the recent upside level.",
        },
        {
            "feature_name": "day_range_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "max(y[t-24], ..., y[t-1]) - min(y[t-24], ..., y[t-1])",
            "plain_language_meaning": "Price range over the previous 24 hours.",
            "time_window_used": "Previous-day block [t-24, t-1]",
            "why_included": "Captures daily spread behaviour in one compact number.",
        },
        {
            "feature_name": "neg_share_24",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "share(y[t-24], ..., y[t-1] < 0)",
            "plain_language_meaning": "Fraction of negative prices over the previous 24 hours.",
            "time_window_used": "Previous-day block [t-24, t-1]",
            "why_included": "Tracks whether the market recently spent time in a negative-price regime.",
        },
        {
            "feature_name": "week_min_block",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "min(y[t-168], ..., y[t-145])",
            "plain_language_meaning": "Minimum price in the comparable 24-hour block one week earlier.",
            "time_window_used": "Previous-week comparable block [t-168, t-145]",
            "why_included": "Provides a weekly benchmark for recent daily extremes.",
        },
        {
            "feature_name": "week_max_block",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "max(y[t-168], ..., y[t-145])",
            "plain_language_meaning": "Maximum price in the comparable 24-hour block one week earlier.",
            "time_window_used": "Previous-week comparable block [t-168, t-145]",
            "why_included": "Provides a weekly benchmark for recent daily peaks.",
        },
        {
            "feature_name": "week_range_block",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "max(y[t-168], ..., y[t-145]) - min(y[t-168], ..., y[t-145])",
            "plain_language_meaning": "Range of prices in the comparable 24-hour block one week earlier.",
            "time_window_used": "Previous-week comparable block [t-168, t-145]",
            "why_included": "Lets us compare recent daily spread with the equivalent block last week.",
        },
        {
            "feature_name": "neg_share_week_block",
            "role_group": "Recent volatility and regime behaviour",
            "formula": "share(y[t-168], ..., y[t-145] < 0)",
            "plain_language_meaning": "Fraction of negative prices in the comparable 24-hour block one week earlier.",
            "time_window_used": "Previous-week comparable block [t-168, t-145]",
            "why_included": "Tracks how the negative-price regime compares with the same block last week.",
        },
    ]
    return pd.DataFrame(rows)


def _rolling_negative_share(series: pd.Series, shift_hours: int, window_hours: int) -> pd.Series:
    negative_indicator = series.lt(0.0).astype(float)
    return negative_indicator.shift(shift_hours).rolling(window_hours, min_periods=window_hours).mean()


def build_endogenous_explicit_features(
    frame: pd.DataFrame,
    config: HourlyDAPipelineConfig,
) -> pd.DataFrame:
    required_columns = {config.timestamp_col, config.feature_source_col}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Missing required columns for endogenous feature construction: {missing_columns}")

    work = frame.copy().sort_values(config.timestamp_col).reset_index(drop=True)
    source = work[config.feature_source_col].astype(float)

    work["lag_1"] = source.shift(1)
    work["lag_2"] = source.shift(2)
    work["lag_24"] = source.shift(24)
    work["lag_25"] = source.shift(25)
    work["lag_168"] = source.shift(168)
    work["lag_169"] = source.shift(169)

    work["diff_1"] = source.shift(1) - source.shift(2)
    work["diff_24"] = source.shift(24) - source.shift(48)
    work["diff_168"] = source.shift(168) - source.shift(336)
    work["cross_season_diff"] = source.shift(24) - source.shift(168)

    previous_24 = source.shift(1).rolling(window=24, min_periods=24)
    previous_168 = source.shift(1).rolling(window=168, min_periods=168)
    work["roll_mean_24"] = previous_24.mean()
    work["roll_std_24"] = previous_24.std(ddof=0)
    work["roll_mean_168"] = previous_168.mean()
    work["roll_std_168"] = previous_168.std(ddof=0)

    work["day_min_24"] = previous_24.min()
    work["day_max_24"] = previous_24.max()
    work["day_range_24"] = work["day_max_24"] - work["day_min_24"]
    work["neg_share_24"] = _rolling_negative_share(source, shift_hours=1, window_hours=24)

    previous_week_block = source.shift(PREVIOUS_WEEK_BLOCK_SHIFT_HOURS).rolling(
        window=PREVIOUS_WEEK_BLOCK_LENGTH_HOURS,
        min_periods=PREVIOUS_WEEK_BLOCK_LENGTH_HOURS,
    )
    work["week_min_block"] = previous_week_block.min()
    work["week_max_block"] = previous_week_block.max()
    work["week_range_block"] = work["week_max_block"] - work["week_min_block"]
    work["neg_share_week_block"] = _rolling_negative_share(
        source,
        shift_hours=PREVIOUS_WEEK_BLOCK_SHIFT_HOURS,
        window_hours=PREVIOUS_WEEK_BLOCK_LENGTH_HOURS,
    )

    feature_columns = endogenous_explicit_feature_names()
    work["has_all_endogenous_features"] = work[feature_columns].notna().all(axis=1)
    if config.target_col in work.columns:
        work["has_observed_target"] = work[config.target_col].notna()
        work["is_usable_for_supervised_learning"] = work["has_all_endogenous_features"] & work["has_observed_target"]
    else:
        work["is_usable_for_supervised_learning"] = work["has_all_endogenous_features"]

    if "target_delivery_local_date" in work.columns:
        work["dataset_split"] = work["target_delivery_local_date"].map(config.split_for_local_date)
    return work


def _window_values(
    working_series: pd.Series,
    *,
    timestamp_utc: pd.Timestamp,
    end_lag_hours: int,
    length_hours: int,
) -> pd.Series:
    end_timestamp = timestamp_utc - pd.Timedelta(hours=end_lag_hours)
    window_index = pd.date_range(end=end_timestamp, periods=length_hours, freq="h", tz="UTC")
    return working_series.reindex(window_index)


def build_endogenous_feature_row(
    timestamp_utc: pd.Timestamp,
    working_series: pd.Series,
) -> dict[str, float]:
    timestamp_utc = pd.Timestamp(timestamp_utc)
    if timestamp_utc.tzinfo is None:
        timestamp_utc = timestamp_utc.tz_localize("UTC")
    else:
        timestamp_utc = timestamp_utc.tz_convert("UTC")

    def lag_value(hours: int) -> float:
        value = working_series.get(timestamp_utc - pd.Timedelta(hours=hours), np.nan)
        return float(value) if pd.notna(value) else np.nan

    previous_day_window = _window_values(
        working_series,
        timestamp_utc=timestamp_utc,
        end_lag_hours=1,
        length_hours=24,
    )
    previous_week_window = _window_values(
        working_series,
        timestamp_utc=timestamp_utc,
        end_lag_hours=1,
        length_hours=168,
    )
    previous_week_block = _window_values(
        working_series,
        timestamp_utc=timestamp_utc,
        end_lag_hours=PREVIOUS_WEEK_BLOCK_END_LAG_HOURS,
        length_hours=PREVIOUS_WEEK_BLOCK_LENGTH_HOURS,
    )

    def strict_mean(values: pd.Series) -> float:
        return float(values.mean()) if values.notna().all() else np.nan

    def strict_std(values: pd.Series) -> float:
        return float(values.std(ddof=0)) if values.notna().all() else np.nan

    def strict_min(values: pd.Series) -> float:
        return float(values.min()) if values.notna().all() else np.nan

    def strict_max(values: pd.Series) -> float:
        return float(values.max()) if values.notna().all() else np.nan

    def strict_neg_share(values: pd.Series) -> float:
        return float(values.lt(0.0).mean()) if values.notna().all() else np.nan

    day_min = strict_min(previous_day_window)
    day_max = strict_max(previous_day_window)
    week_min = strict_min(previous_week_block)
    week_max = strict_max(previous_week_block)

    return {
        "lag_1": lag_value(1),
        "lag_2": lag_value(2),
        "lag_24": lag_value(24),
        "lag_25": lag_value(25),
        "lag_168": lag_value(168),
        "lag_169": lag_value(169),
        "diff_1": lag_value(1) - lag_value(2) if not np.isnan(lag_value(1)) and not np.isnan(lag_value(2)) else np.nan,
        "diff_24": lag_value(24) - lag_value(48) if not np.isnan(lag_value(24)) and not np.isnan(lag_value(48)) else np.nan,
        "diff_168": (
            lag_value(168) - lag_value(336)
            if not np.isnan(lag_value(168)) and not np.isnan(lag_value(336))
            else np.nan
        ),
        "cross_season_diff": (
            lag_value(24) - lag_value(168)
            if not np.isnan(lag_value(24)) and not np.isnan(lag_value(168))
            else np.nan
        ),
        "roll_mean_24": strict_mean(previous_day_window),
        "roll_std_24": strict_std(previous_day_window),
        "roll_mean_168": strict_mean(previous_week_window),
        "roll_std_168": strict_std(previous_week_window),
        "day_min_24": day_min,
        "day_max_24": day_max,
        "day_range_24": day_max - day_min if not np.isnan(day_min) and not np.isnan(day_max) else np.nan,
        "neg_share_24": strict_neg_share(previous_day_window),
        "week_min_block": week_min,
        "week_max_block": week_max,
        "week_range_block": week_max - week_min if not np.isnan(week_min) and not np.isnan(week_max) else np.nan,
        "neg_share_week_block": strict_neg_share(previous_week_block),
    }


def summarize_feature_matrix(
    feature_frame: pd.DataFrame,
    config: HourlyDAPipelineConfig,
) -> EndogenousFeatureSummary:
    feature_columns = endogenous_explicit_feature_names()
    missing_columns = sorted(set(feature_columns) - set(feature_frame.columns))
    if missing_columns:
        raise ValueError(f"Feature frame is missing engineered feature columns: {missing_columns}")

    theoretical_first_usable_timestamp = (
        pd.Timestamp(feature_frame[config.timestamp_col].min()) + pd.Timedelta(hours=endogenous_required_history_hours(config))
    )
    feature_complete_mask = feature_frame[feature_columns].notna().all(axis=1)
    target_observed_mask = (
        feature_frame[config.target_col].notna()
        if config.target_col in feature_frame.columns
        else pd.Series(True, index=feature_frame.index)
    )
    supervised_ready_mask = feature_complete_mask & target_observed_mask
    after_lookback_mask = feature_frame[config.timestamp_col] >= theoretical_first_usable_timestamp

    total_rows = int(feature_frame.shape[0])
    rows_after_lookback = int(after_lookback_mask.sum())
    rows_with_observed_target = int(target_observed_mask.sum())
    rows_with_complete_features = int(feature_complete_mask.sum())
    rows_usable_for_supervised_learning = int(supervised_ready_mask.sum())

    row_loss_table = pd.DataFrame(
        [
            {
                "stage": "rows_on_canonical_grid",
                "rows": total_rows,
                "share_of_total_pct": 100.0 if total_rows else 0.0,
            },
            {
                "stage": "rows_after_theoretical_lookback_requirement",
                "rows": rows_after_lookback,
                "share_of_total_pct": (rows_after_lookback / total_rows * 100.0) if total_rows else 0.0,
            },
            {
                "stage": "rows_with_observed_target",
                "rows": rows_with_observed_target,
                "share_of_total_pct": (rows_with_observed_target / total_rows * 100.0) if total_rows else 0.0,
            },
            {
                "stage": "rows_with_complete_endogenous_features",
                "rows": rows_with_complete_features,
                "share_of_total_pct": (rows_with_complete_features / total_rows * 100.0) if total_rows else 0.0,
            },
            {
                "stage": "rows_usable_for_supervised_learning",
                "rows": rows_usable_for_supervised_learning,
                "share_of_total_pct": (
                    rows_usable_for_supervised_learning / total_rows * 100.0 if total_rows else 0.0
                ),
            },
        ]
    )

    missingness_columns = [config.feature_source_col, config.target_col, *feature_columns]
    missingness_rows: list[dict[str, object]] = []
    for column in missingness_columns:
        if column not in feature_frame.columns:
            continue
        missing_count = int(feature_frame[column].isna().sum())
        missingness_rows.append(
            {
                "column_name": column,
                "missing_count": missing_count,
                "missing_share_pct": (missing_count / total_rows * 100.0) if total_rows else 0.0,
            }
        )
    missingness_table = pd.DataFrame(missingness_rows).sort_values(
        ["missing_count", "column_name"],
        ascending=[False, True],
    ).reset_index(drop=True)

    summary_statistics = (
        feature_frame[feature_columns]
        .agg(["mean", "std", "min", "median", "max"])
        .transpose()
        .reset_index()
        .rename(columns={"index": "feature_name"})
    )

    correlation_source = feature_frame[[config.target_col, *feature_columns]].dropna()
    if correlation_source.empty:
        feature_target_correlations = pd.DataFrame(columns=["feature_name", "correlation_with_target"])
        feature_correlation_matrix = pd.DataFrame(index=feature_columns, columns=feature_columns, dtype=float)
    else:
        correlations = correlation_source.corr(numeric_only=True)
        feature_target_correlations = (
            correlations[[config.target_col]]
            .drop(index=config.target_col)
            .reset_index()
            .rename(columns={"index": "feature_name", config.target_col: "correlation_with_target"})
            .sort_values("correlation_with_target", key=lambda values: values.abs(), ascending=False)
            .reset_index(drop=True)
        )
        feature_correlation_matrix = correlations.loc[feature_columns, feature_columns]

    metadata_summary: dict[str, object] = {
        "feature_count": len(feature_columns),
        "feature_names": feature_columns,
        "theoretical_first_usable_timestamp_utc": theoretical_first_usable_timestamp.isoformat(),
        "endogenous_required_history_hours": int(endogenous_required_history_hours(config)),
        "total_rows_on_canonical_grid": total_rows,
        "rows_after_theoretical_lookback": rows_after_lookback,
        "rows_with_observed_target": rows_with_observed_target,
        "rows_with_complete_endogenous_features": rows_with_complete_features,
        "rows_usable_for_supervised_learning": rows_usable_for_supervised_learning,
        "target_missing_rows": int(total_rows - rows_with_observed_target),
        "feature_incomplete_rows": int(total_rows - rows_with_complete_features),
    }
    if "dataset_split" in feature_frame.columns:
        split_counts = (
            feature_frame["dataset_split"]
            .fillna("outside_defined_splits")
            .value_counts()
            .sort_index()
            .to_dict()
        )
        metadata_summary["rows_by_dataset_split"] = {str(key): int(value) for key, value in split_counts.items()}

    return EndogenousFeatureSummary(
        feature_catalog=feature_catalog_frame(),
        missingness_table=missingness_table,
        row_loss_table=row_loss_table,
        summary_statistics=summary_statistics,
        feature_target_correlations=feature_target_correlations,
        feature_correlation_matrix=feature_correlation_matrix,
        metadata_summary=metadata_summary,
    )
