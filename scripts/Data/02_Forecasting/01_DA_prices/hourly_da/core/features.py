from __future__ import annotations

from dataclasses import dataclass

import holidays
import pandas as pd

from .config import HourlyDAPipelineConfig
from .methodology import FEATURE_STAGE_POLICIES


PRICE_LAG_RATIONALE = (
    "The explicit endogenous foundation stays compact on purpose: raw lags capture short-memory persistence and daily "
    "or weekly anchors, lag differences capture momentum and regime shifts, and rolling or block summaries capture "
    "recent volatility, spread, and negative-price behaviour."
)


@dataclass(frozen=True)
class FeatureSetDefinition:
    fs_level: str
    description: str


FEATURE_SET_DEFINITIONS = (
    *(
        FeatureSetDefinition(policy.fs_level, policy.feature_scope)
        for policy in FEATURE_STAGE_POLICIES
    ),
)


def build_calendar_features(target_index_utc: pd.DatetimeIndex, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    target_local = target_index_utc.tz_convert(config.resolved_business_timezone())
    nl_holidays = holidays.country_holidays(config.resolved_holiday_country())
    local_dates = pd.Series(target_local.date)
    return pd.DataFrame(
        {
            "target_timestamp_utc": target_index_utc,
            "hour_of_day": target_local.hour.astype(int),
            "day_of_week": target_local.dayofweek.astype(int),
            "is_weekend": target_local.dayofweek.isin([5, 6]).astype(int),
            "month": target_local.month.astype(int),
            "is_dutch_holiday": local_dates.map(lambda value: int(value in nl_holidays)).astype(int),
        }
    )
