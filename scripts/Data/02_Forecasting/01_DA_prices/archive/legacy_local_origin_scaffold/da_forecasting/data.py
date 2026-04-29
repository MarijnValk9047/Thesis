from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ForecastSetup


def load_target_frame(setup: ForecastSetup) -> pd.DataFrame:
    input_path = Path(setup.input_csv)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    required_cols = {"region", setup.timestamp_col, setup.target_col}
    frame = pd.read_csv(input_path)
    missing_cols = sorted(required_cols - set(frame.columns))
    if missing_cols:
        raise ValueError(f"Missing required columns in input data: {missing_cols}")

    frame = frame[frame["region"] == setup.market_area].copy()
    if frame.empty:
        raise ValueError(f"No rows found for region '{setup.market_area}'.")

    frame[setup.timestamp_col] = pd.to_datetime(frame[setup.timestamp_col], utc=True, errors="coerce")
    frame[setup.target_col] = pd.to_numeric(frame[setup.target_col], errors="coerce")
    frame = frame.dropna(subset=[setup.timestamp_col, setup.target_col]).copy()
    frame = frame.sort_values(setup.timestamp_col).reset_index(drop=True)

    if frame[setup.timestamp_col].duplicated().any():
        dupes = int(frame[setup.timestamp_col].duplicated().sum())
        raise ValueError(f"Found duplicate timestamps in target series: {dupes}")

    frame["timestamp_local"] = frame[setup.timestamp_col].dt.tz_convert(setup.local_timezone)
    frame["local_date"] = frame["timestamp_local"].dt.date
    frame["local_hour"] = frame["timestamp_local"].dt.hour
    return frame
