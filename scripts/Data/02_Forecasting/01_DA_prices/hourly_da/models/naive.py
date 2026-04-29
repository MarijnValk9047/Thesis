from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.config import HourlyDAPipelineConfig
from .base import ForecastModel


_LOCAL_LOOKUP_CACHE_STATE: dict[str, object] = {
    "timezone": None,
    "first_timestamp": None,
    "history_length": 0,
    "last_timestamp": None,
    "exact_value_lookup": {},
    "fallback_value_lookup": {},
}


def _utc_offset_seconds(index_local: pd.DatetimeIndex) -> np.ndarray:
    return np.fromiter(
        (
            int(timestamp.utcoffset().total_seconds()) if timestamp.utcoffset() is not None else 0
            for timestamp in index_local
        ),
        dtype=np.int32,
        count=len(index_local),
    )


def _prepare_local_lookup(
    history: pd.DataFrame,
    config: HourlyDAPipelineConfig,
) -> tuple[dict[tuple[pd.Timestamp, int], float], dict[pd.Timestamp, float]]:
    global _LOCAL_LOOKUP_CACHE_STATE

    history_index_utc = pd.DatetimeIndex(history[config.timestamp_col])
    timezone = config.resolved_business_timezone()

    cache_timezone = _LOCAL_LOOKUP_CACHE_STATE.get("timezone")
    cache_first = _LOCAL_LOOKUP_CACHE_STATE.get("first_timestamp")
    cache_length = int(_LOCAL_LOOKUP_CACHE_STATE.get("history_length", 0))
    cache_last = _LOCAL_LOOKUP_CACHE_STATE.get("last_timestamp")
    can_extend = (
        cache_timezone == timezone
        and not history_index_utc.empty
        and cache_first == history_index_utc[0]
        and len(history_index_utc) >= cache_length
        and (cache_length == 0 or history_index_utc[cache_length - 1] == cache_last)
    )

    if not can_extend:
        _LOCAL_LOOKUP_CACHE_STATE = {
            "timezone": timezone,
            "first_timestamp": history_index_utc[0] if not history_index_utc.empty else None,
            "history_length": 0,
            "last_timestamp": None,
            "exact_value_lookup": {},
            "fallback_value_lookup": {},
        }
        cache_length = 0

    exact_value_lookup = _LOCAL_LOOKUP_CACHE_STATE["exact_value_lookup"]
    fallback_value_lookup = _LOCAL_LOOKUP_CACHE_STATE["fallback_value_lookup"]
    if cache_length >= len(history_index_utc):
        return exact_value_lookup, fallback_value_lookup

    new_index_utc = history_index_utc[cache_length:]
    new_values = pd.to_numeric(history[config.target_col].iloc[cache_length:], errors="coerce").to_numpy(dtype=float)
    new_local = new_index_utc.tz_convert(timezone)
    new_local_naive = pd.DatetimeIndex(new_local.tz_localize(None))
    new_offset_seconds = _utc_offset_seconds(new_local)

    for local_naive, offset_seconds, value in zip(new_local_naive, new_offset_seconds, new_values, strict=True):
        local_key = pd.Timestamp(local_naive)
        mapped_value = float(value) if pd.notna(value) else np.nan
        exact_value_lookup[(local_key, int(offset_seconds))] = mapped_value
        fallback_value_lookup.setdefault(local_key, mapped_value)

    _LOCAL_LOOKUP_CACHE_STATE["timezone"] = timezone
    _LOCAL_LOOKUP_CACHE_STATE["first_timestamp"] = history_index_utc[0] if not history_index_utc.empty else None
    _LOCAL_LOOKUP_CACHE_STATE["history_length"] = int(len(history_index_utc))
    _LOCAL_LOOKUP_CACHE_STATE["last_timestamp"] = history_index_utc[-1] if not history_index_utc.empty else None
    return exact_value_lookup, fallback_value_lookup


def _local_recursive_naive(
    target_index_utc: pd.DatetimeIndex,
    config: HourlyDAPipelineConfig,
    offset: pd.DateOffset,
    lookup_payload: tuple[dict[tuple[pd.Timestamp, int], float], dict[pd.Timestamp, float]],
) -> pd.Series:
    exact_lookup, fallback_lookup = lookup_payload
    timezone = config.resolved_business_timezone()
    target_index_utc = pd.DatetimeIndex(target_index_utc).sort_values()
    target_local = target_index_utc.tz_convert(timezone)
    target_local_naive = pd.DatetimeIndex(target_local.tz_localize(None))
    source_local_naive = pd.DatetimeIndex(target_local_naive - offset)
    target_offset_seconds = _utc_offset_seconds(target_local)

    forecasts: list[float] = []
    for source_local_value, offset_seconds in zip(source_local_naive, target_offset_seconds, strict=True):
        local_key = pd.Timestamp(source_local_value)
        value = exact_lookup.get((local_key, int(offset_seconds)))
        if value is None:
            value = fallback_lookup.get(local_key, np.nan)
        forecasts.append(float(value) if pd.notna(value) else np.nan)
    return pd.Series(forecasts, index=target_index_utc)


class PreviousWeekNaiveModel(ForecastModel):
    def __init__(self):
        super().__init__(name="naive_previous_week", family="naive", fs_level="FS0")
        self._lookup_payload = None

    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        self._lookup_payload = _prepare_local_lookup(history, config)
        self._set_runtime_info({"strategy": "local_previous_week", "fit_failed": False})

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        return _local_recursive_naive(
            target_index_utc=target_index_utc,
            config=config,
            offset=pd.DateOffset(days=7),
            lookup_payload=self._lookup_payload,
        )


class PreviousYearNaiveModel(ForecastModel):
    def __init__(self):
        super().__init__(name="naive_previous_year", family="naive", fs_level="FS0")
        self._lookup_payload = None

    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        self._lookup_payload = _prepare_local_lookup(history, config)
        self._set_runtime_info({"strategy": "local_previous_year", "fit_failed": False})

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        return _local_recursive_naive(
            target_index_utc=target_index_utc,
            config=config,
            offset=pd.DateOffset(years=1),
            lookup_payload=self._lookup_payload,
        )
