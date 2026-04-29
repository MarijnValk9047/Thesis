from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .config import ForecastSetup


def label_splits(frame: pd.DataFrame, setup: ForecastSetup) -> pd.DataFrame:
    labeled = frame.copy()
    labeled["split"] = labeled["local_date"].map(setup.split_for_local_date).fillna("outside")
    return labeled


def generate_origins_for_split(setup: ForecastSetup, split_name: str) -> list[pd.Timestamp]:
    boundaries = setup.split_boundaries()
    if split_name not in boundaries:
        raise ValueError(f"Unknown split: {split_name}")

    split_start, split_end = boundaries[split_name]
    latest_origin_date = split_end - timedelta(days=setup.horizon_days)
    if latest_origin_date < split_start:
        return []

    origin_dates = pd.date_range(split_start, latest_origin_date, freq=f"{setup.origin_step_days}D")
    origins_local: list[pd.Timestamp] = []
    for origin_date in origin_dates:
        origin_local = origin_date.tz_localize(setup.local_timezone) + pd.Timedelta(hours=setup.origin_hour_local)
        origins_local.append(origin_local)
    return origins_local


def target_window_for_origin(
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    split_name: str,
    origin_local: pd.Timestamp,
) -> pd.DataFrame:
    start_date = (origin_local + pd.Timedelta(days=1)).date()
    end_exclusive = start_date + timedelta(days=setup.horizon_days)
    mask = (
        (labeled["split"] == split_name)
        & (labeled["local_date"] >= start_date)
        & (labeled["local_date"] < end_exclusive)
    )
    return labeled.loc[mask].sort_values(setup.timestamp_col).copy()


def build_split_summary(labeled: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for split_name in ("train", "validation", "test"):
        part = labeled[labeled["split"] == split_name]
        if part.empty:
            rows.append(
                {
                    "split": split_name,
                    "rows": 0,
                    "first_timestamp_utc": None,
                    "last_timestamp_utc": None,
                    "first_local_date": None,
                    "last_local_date": None,
                }
            )
            continue

        rows.append(
            {
                "split": split_name,
                "rows": int(len(part)),
                "first_timestamp_utc": part["timestamp_utc"].iloc[0].isoformat(),
                "last_timestamp_utc": part["timestamp_utc"].iloc[-1].isoformat(),
                "first_local_date": part["local_date"].iloc[0].isoformat(),
                "last_local_date": part["local_date"].iloc[-1].isoformat(),
            }
        )
    return pd.DataFrame(rows)
