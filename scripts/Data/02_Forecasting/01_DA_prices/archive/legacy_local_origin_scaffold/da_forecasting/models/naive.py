from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ForecastModel


def _seasonal_recursive_predict(
    history_series: pd.Series,
    target_index_utc: pd.DatetimeIndex,
    seasonal_lag_hours: int,
) -> pd.Series:
    known = history_series.copy()
    forecasts: list[float] = []
    lag = pd.Timedelta(hours=seasonal_lag_hours)
    history_end = pd.Timestamp(known.index.max())
    target_index_utc = target_index_utc.sort_values()

    bridge_start = history_end + pd.Timedelta(hours=1)
    bridge_end = pd.Timestamp(target_index_utc.min()) - pd.Timedelta(hours=1)
    if bridge_end >= bridge_start:
        bridge_index = pd.date_range(bridge_start, bridge_end, freq="h")
        forecast_index = bridge_index.append(target_index_utc)
    else:
        forecast_index = target_index_utc

    for timestamp in forecast_index:
        source_timestamp = timestamp - lag
        value = known.get(source_timestamp, pd.NA)
        known.loc[timestamp] = value
        if timestamp in target_index_utc:
            forecasts.append(float(value) if pd.notna(value) else np.nan)

    return pd.Series(forecasts, index=target_index_utc)


class NaivePreviousDayModel(ForecastModel):
    name = "naive_1d"

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        timestamp_col: str,
        target_col: str,
    ) -> pd.Series:
        history_series = history.set_index(timestamp_col)[target_col]
        preds = _seasonal_recursive_predict(history_series, target_index_utc, seasonal_lag_hours=24)
        preds.name = self.name
        return preds


class NaivePreviousWeekModel(ForecastModel):
    name = "naive_7d"

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        timestamp_col: str,
        target_col: str,
    ) -> pd.Series:
        history_series = history.set_index(timestamp_col)[target_col]
        preds = _seasonal_recursive_predict(history_series, target_index_utc, seasonal_lag_hours=24 * 7)
        preds.name = self.name
        return preds
