from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class QuarterHourDAExtensionConfig:
    repo_root: Path = Path(__file__).resolve().parents[5]
    market_area: str = "NL"
    business_timezone: str = "Europe/Amsterdam"
    cleaning_cutoff_local_date: date = date(2025, 10, 1)
    latest_full_day_lag_days: int = 1

    @property
    def shared_raw_root(self) -> Path:
        return self.repo_root / "data" / "00_Raw" / "DA_Prices"

    @property
    def shared_nl_raw_a01_root(self) -> Path:
        return self.shared_raw_root / "DA_prices_NL" / "A01_Day_Ahead_Market"

    @property
    def shared_clean_root(self) -> Path:
        return self.repo_root / "data" / "01_cleaned" / "Day_ahead_prices"

    @property
    def shared_hourly_csv(self) -> Path:
        return self.shared_clean_root / "DA_prices" / "hourly" / "da_prices_NL_hourly.csv"

    @property
    def shared_all_regions_hourly_csv(self) -> Path:
        return self.shared_clean_root / "DA_prices" / "hourly" / "da_prices_all_regions_hourly.csv"

    @property
    def shared_all_regions_aggregated_csv(self) -> Path:
        return self.shared_clean_root / "DA_prices" / "aggregated" / "da_prices_all_regions_all.csv"

    @property
    def shared_quarterly_csv(self) -> Path:
        return self.shared_clean_root / "DA_prices" / "quarterly" / "da_prices_NL_quarterly.csv"

    @property
    def dedicated_quarterly_raw_root(self) -> Path:
        return self.repo_root / "data" / "00_Raw" / "DA_Prices_quarterly" / "NL" / "A01_Day_Ahead_Market"

    @property
    def dedicated_quarterly_output_root(self) -> Path:
        return self.repo_root / "data" / "01_cleaned" / "Day_ahead_prices_quarterly" / "NL"

    @property
    def dedicated_quarterly_csv(self) -> Path:
        return self.dedicated_quarterly_output_root / "quarterly" / "da_prices_NL_quarterly.csv"

    @property
    def output_root(self) -> Path:
        return self.repo_root / "data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da"

    @property
    def phase01_runs_root(self) -> Path:
        return self.output_root / "phase01_runs"

    @property
    def phase02_runs_root(self) -> Path:
        return self.output_root / "phase02_runs"

    @property
    def phase03_runs_root(self) -> Path:
        return self.output_root / "phase03_runs"

    @property
    def phase04_runs_root(self) -> Path:
        return self.output_root / "phase04_runs"

    @property
    def phase05_runs_root(self) -> Path:
        return self.output_root / "phase05_runs"

    @property
    def phase06_runs_root(self) -> Path:
        return self.output_root / "phase06_runs"

    @property
    def phase07_runs_root(self) -> Path:
        return self.output_root / "phase07_runs"

    @property
    def phase07_upstream_refresh_runs_root(self) -> Path:
        return self.output_root / "phase07_upstream_refresh_runs"

    @property
    def canonical_actual_runs_root(self) -> Path:
        return self.output_root / "canonical_actual_runs"

    @property
    def frozen_actual_root(self) -> Path:
        return self.output_root / "frozen_actual_paths"

    def frozen_actual_version_dir(self, version_id: str) -> Path:
        return self.frozen_actual_root / str(version_id)

    @property
    def notebook_root(self) -> Path:
        return self.repo_root / "notebooks" / "Data" / "02_Forecasting" / "01_DA_prices" / "15min_extension"

    @property
    def hourly_package_root(self) -> Path:
        return self.repo_root / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"

    @property
    def hourly_da_output_root(self) -> Path:
        return self.repo_root / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da"

    def latest_full_local_day(self) -> date:
        now_local = pd.Timestamp.now(tz=self.business_timezone)
        return (now_local - pd.Timedelta(days=self.latest_full_day_lag_days)).date()

    def end_timestamp_inclusive_for_local_day(self, local_day: date, *, step_minutes: int) -> pd.Timestamp:
        if step_minutes <= 0:
            raise ValueError("step_minutes must be positive.")
        end_local = pd.Timestamp(datetime.combine(local_day + timedelta(days=1), datetime.min.time()))
        end_local = end_local.tz_localize(self.business_timezone)
        return end_local.tz_convert("UTC") - pd.Timedelta(minutes=step_minutes)
