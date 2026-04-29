from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from .config import HourlyDAPipelineConfig


def localize_naive_timestamp(naive_value: datetime, timezone: str) -> pd.Timestamp:
    return pd.Timestamp(naive_value).tz_localize(timezone, ambiguous="raise", nonexistent="raise")


def local_date_start_utc(local_value: date, timezone: str) -> pd.Timestamp:
    start_local = localize_naive_timestamp(datetime.combine(local_value, time.min), timezone)
    return start_local.tz_convert("UTC")


def local_date_to_utc_bounds(local_value: date, timezone: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_utc = local_date_start_utc(local_value, timezone)
    end_utc = local_date_start_utc(local_value.fromordinal(local_value.toordinal() + 1), timezone)
    return start_utc, end_utc


def known_at_utc_for_delivery_date(local_value: date, config: HourlyDAPipelineConfig) -> pd.Timestamp:
    known_local = localize_naive_timestamp(
        datetime.combine(local_value, time(hour=config.da_known_local_hour, minute=config.da_known_local_minute)),
        config.resolved_business_timezone(),
    )
    return known_local.tz_convert("UTC")


def delivery_local_date_for_timestamp(timestamp_utc: pd.Timestamp, timezone: str) -> date:
    return timestamp_utc.tz_convert(timezone).date()
