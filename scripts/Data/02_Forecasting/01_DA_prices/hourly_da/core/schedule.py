from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from .config import HourlyDAPipelineConfig
from .time_utils import known_at_utc_for_delivery_date, local_date_to_utc_bounds, localize_naive_timestamp


def horizon_end_local_date(config: HourlyDAPipelineConfig, delivery_start_local_date: date) -> date:
    return delivery_start_local_date + timedelta(days=config.forecast_horizon_days - 1)


def expected_target_hours_for_origin(config: HourlyDAPipelineConfig, delivery_start_local_date: date) -> int:
    timezone = config.resolved_business_timezone()
    expected_hours = 0
    for lead_day in range(config.forecast_horizon_days):
        target_local_date = delivery_start_local_date + timedelta(days=lead_day)
        day_start_utc, day_end_utc = local_date_to_utc_bounds(target_local_date, timezone)
        expected_hours += int((day_end_utc - day_start_utc) / pd.Timedelta(hours=1))
    return expected_hours


def build_split_summary(config: HourlyDAPipelineConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    timezone = config.resolved_business_timezone()
    for split_name, (start_local, end_local) in config.split_boundaries_local().items():
        start_utc, _ = local_date_to_utc_bounds(start_local, timezone)
        _, end_utc_exclusive = local_date_to_utc_bounds(end_local, timezone)
        days_in_split = int((end_local - start_local).days + 1)
        last_full_horizon_start = end_local - timedelta(days=config.forecast_horizon_days - 1)
        eligible_origins = max((last_full_horizon_start - start_local).days + 1, 0)
        removed_split_end_origins = max(days_in_split - eligible_origins, 0)
        rows.append(
            {
                "dataset_split": split_name,
                "start_local_date": start_local.isoformat(),
                "end_local_date": end_local.isoformat(),
                "start_utc_inclusive": start_utc.isoformat(),
                "end_utc_exclusive": end_utc_exclusive.isoformat(),
                "days_in_split": days_in_split,
                "last_full_horizon_start_local_date": last_full_horizon_start.isoformat(),
                "eligible_forecast_origins": int(eligible_origins),
                "removed_split_end_origins": int(removed_split_end_origins),
            }
        )
    return pd.DataFrame(rows)


def generate_forecast_origins(config: HourlyDAPipelineConfig, split_name: str) -> pd.DataFrame:
    if split_name not in config.split_boundaries_local():
        raise ValueError(f"Unknown split: {split_name}")

    split_start_local, split_end_local = config.split_boundaries_local()[split_name]
    timezone = config.resolved_business_timezone()
    last_full_horizon_start = split_end_local - timedelta(days=config.forecast_horizon_days - 1)
    if last_full_horizon_start < split_start_local:
        return pd.DataFrame(
            columns=[
                "dataset_split",
                "delivery_start_local_date",
                "horizon_end_local_date",
                "forecast_origin_local",
                "forecast_origin_utc",
                "expected_target_hours",
            ]
        )

    delivery_dates = pd.date_range(start=split_start_local, end=last_full_horizon_start, freq=f"{config.origin_step_days}D")
    origin_rows: list[dict[str, object]] = []
    for delivery_start_ts in delivery_dates:
        delivery_start_local = delivery_start_ts.date()
        delivery_end_local = horizon_end_local_date(config, delivery_start_local)
        origin_local_day = delivery_start_local - timedelta(days=1)
        origin_local = localize_naive_timestamp(
            datetime.combine(
                origin_local_day,
                time(hour=config.forecast_origin_local_hour, minute=config.forecast_origin_local_minute),
            ),
            timezone,
        )
        origin_rows.append(
            {
                "dataset_split": split_name,
                "delivery_start_local_date": delivery_start_local.isoformat(),
                "horizon_end_local_date": delivery_end_local.isoformat(),
                "forecast_origin_local": origin_local.isoformat(),
                "forecast_origin_utc": origin_local.tz_convert("UTC").isoformat(),
                "expected_target_hours": int(expected_target_hours_for_origin(config, delivery_start_local)),
            }
        )

    return pd.DataFrame(origin_rows)


def build_target_schedule_for_origin(
    config: HourlyDAPipelineConfig,
    delivery_start_local_date: date,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    horizon_index = 1
    timezone = config.resolved_business_timezone()
    for lead_day in range(config.forecast_horizon_days):
        target_local_date = delivery_start_local_date + timedelta(days=lead_day)
        day_start_utc, day_end_utc = local_date_to_utc_bounds(target_local_date, timezone)
        target_known_at_utc = known_at_utc_for_delivery_date(target_local_date, config)
        # A market-faithful local-day horizon is usually 24 hours per day, but DST days can yield 23 or 25 UTC hours.
        target_index = pd.date_range(start=day_start_utc, end=day_end_utc, freq="h", inclusive="left", tz="UTC")
        for target_timestamp_utc in target_index:
            target_local = target_timestamp_utc.tz_convert(timezone)
            rows.append(
                {
                    "target_timestamp_utc": target_timestamp_utc,
                    "target_delivery_local_date": target_local_date,
                    "target_hour_local": int(target_local.hour),
                    "target_known_at_utc": target_known_at_utc,
                    "lead_day": int(lead_day),
                    "lead_day_label": config.lead_day_label(lead_day),
                    "horizon_index": int(horizon_index),
                    "dataset_split": config.split_for_local_date(target_local_date),
                }
            )
            horizon_index += 1

    return pd.DataFrame(rows)
