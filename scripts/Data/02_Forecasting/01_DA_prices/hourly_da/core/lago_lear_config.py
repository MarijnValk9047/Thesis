from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LagoLearBenchmarkConfig:
    benchmark_start_local_date: date = date(2019, 10, 1)
    benchmark_end_exclusive_local_date: date = date(2025, 10, 1)
    local_timezone: str = "Europe/Amsterdam"

    forecast_origin_hour_local: int = 8
    forecast_origin_minute_local: int = 0
    lead_days: tuple[int, ...] = (0, 1, 2, 3, 4)

    lago_windows_days: tuple[int, ...] = (56, 84, 1092, 1456)
    min_training_days_by_window: dict[int, int] = field(
        default_factory=lambda: {
            56: 42,
            84: 56,
            1092: 365,
            1456: 730,
        }
    )

    target_region: str = "NL"
    x1_policy: str = "da_load_forecast_for_d_else_week_ahead_if_needed"
    x2_policy: str = "res_a69_psr_sum"
    x2_missing_policy: str = "impute_training_median"
    dplus4_x2_policy: str = "strict_no_future_x2"
    strict_known_at: bool = True
    exclude_interpolated_targets: bool = True
    dst_policy: str = "skip_non_24h_local_days"
    allow_missing_known_at: bool = False

    run_heavy_default: bool = False
    smoke_test_max_origins: int = 5

    output_root: Path = Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear")
    staged_raw_root: Path = Path("data/00_raw_lago_lear_six_year")
    staged_cleaned_root: Path = Path("data/01_cleaned_lago_lear_six_year")
    official_cleaned_root: Path = Path("data/01_cleaned")

    notebook_path: Path = Path(
        "notebooks/Data/02_Forecasting/01_DA_prices/25_lago_lear_six_year_benchmark.ipynb"
    )

    allow_official_cleaned_fallback: bool = False
    allow_x2_aggregate_fallback: bool = False
    allow_x2_persistence_proxy: bool = False

    price_hourly_input_name: str = "da_prices_NL_hourly.csv"
    max_timestamp_utc: str = "2026-01-01T00:00:00Z"

    # Existing official candidate runs for aligned comparison.
    fs_candidate_run_paths: tuple[Path, ...] = (
        Path(
            "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260424_111158_model_comparison_fs2_pruned_candidate"
        ),
        Path(
            "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_151547_lear_fs3_combo_pruned_candidate_benchmark"
        ),
        Path(
            "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark"
        ),
    )

    def benchmark_end_inclusive_local_date(self) -> date:
        return self.benchmark_end_exclusive_local_date - timedelta(days=1)

    def benchmark_delivery_days(self) -> list[date]:
        days: list[date] = []
        cursor = self.benchmark_start_local_date
        end_inclusive = self.benchmark_end_inclusive_local_date()
        while cursor <= end_inclusive:
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def localized_forecast_origin_for_delivery_day(self, delivery_day_local: date) -> pd.Timestamp:
        origin_day = delivery_day_local - timedelta(days=1)
        naive_dt = datetime.combine(
            origin_day,
            time(
                hour=self.forecast_origin_hour_local,
                minute=self.forecast_origin_minute_local,
            ),
        )
        return pd.Timestamp(naive_dt).tz_localize(self.local_timezone, ambiguous="raise", nonexistent="raise")

    def forecast_origin_utc_for_delivery_day(self, delivery_day_local: date) -> pd.Timestamp:
        return self.localized_forecast_origin_for_delivery_day(delivery_day_local).tz_convert("UTC")

    def local_day_utc_bounds(self, local_day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
        start_local = pd.Timestamp(datetime.combine(local_day, time.min)).tz_localize(
            self.local_timezone,
            ambiguous="raise",
            nonexistent="raise",
        )
        end_local = pd.Timestamp(datetime.combine(local_day + timedelta(days=1), time.min)).tz_localize(
            self.local_timezone,
            ambiguous="raise",
            nonexistent="raise",
        )
        return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")

    def expected_hours_for_local_day(self, local_day: date) -> int:
        start_utc, end_utc = self.local_day_utc_bounds(local_day)
        return int((end_utc - start_utc) / pd.Timedelta(hours=1))

    def resolve_cleaned_root(self, allow_official_fallback: bool | None = None) -> Path:
        if self.staged_cleaned_root.exists():
            return self.staged_cleaned_root
        allow = self.allow_official_cleaned_fallback if allow_official_fallback is None else allow_official_fallback
        if allow:
            return self.official_cleaned_root
        return self.staged_cleaned_root

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "benchmark_start_local_date",
            "benchmark_end_exclusive_local_date",
        ):
            payload[key] = payload[key].isoformat()
        for key in (
            "output_root",
            "staged_raw_root",
            "staged_cleaned_root",
            "official_cleaned_root",
            "notebook_path",
        ):
            payload[key] = str(payload[key])
        payload["fs_candidate_run_paths"] = [str(path) for path in self.fs_candidate_run_paths]
        payload["benchmark_end_inclusive_local_date"] = self.benchmark_end_inclusive_local_date().isoformat()
        return payload
