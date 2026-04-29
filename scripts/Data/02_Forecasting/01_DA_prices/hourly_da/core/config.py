from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


MARKET_TIMEZONES = {
    "BE": "Europe/Brussels",
    "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam",
}

MARKET_HOLIDAY_COUNTRIES = {
    "BE": "BE",
    "DE": "DE",
    "NL": "NL",
}

DA_PRICE_DOMAIN_CODES = {
    "BE": "10YBE----------2",
    "DE": "10Y1001A1001A82H",
    "NL": "10YNL----------L",
}

BIDDING_ZONE_DOMAIN_CODES = {
    "BE": "10YBE----------2",
    "DE": "10Y1001A1001A83F",
    "NL": "10YNL----------L",
}


@dataclass(frozen=True)
class MonitoringConfig:
    fit_time_absolute_threshold_sec: float = 30.0
    fit_time_relative_factor: float = 3.0
    fit_time_recent_window: int = 14
    fit_time_min_history: int = 5

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class HourlyDAPipelineConfig:
    input_csv: Path = Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv")
    raw_root: Path = Path("data/00_Raw/DA_Prices")
    cleaned_feature_root: Path = Path("data/01_cleaned")
    output_root: Path = Path("data/02_Forecasting/01_DA_prices/hourly_da")
    market_area: str = "NL"
    timestamp_col: str = "timestamp_utc"
    target_col: str = "price_eur_per_mwh"
    feature_source_col: str = "price_feature_source_eur_per_mwh"
    known_at_col: str = "known_at_utc"
    business_timezone: str = "Europe/Amsterdam"
    holiday_country: str = "NL"
    forecast_origin_local_hour: int = 8
    forecast_origin_local_minute: int = 0
    da_known_local_hour: int = 8
    da_known_local_minute: int = 0
    forecast_horizon_days: int = 5
    origin_step_days: int = 1
    train_start_local: date = date(2022, 1, 1)
    train_end_local: date = date(2023, 9, 30)
    validation_start_local: date = date(2023, 10, 1)
    validation_end_local: date = date(2024, 9, 30)
    test_start_local: date = date(2024, 10, 1)
    test_end_local: date = date(2025, 9, 30)
    price_lags_hours: tuple[int, ...] = (1, 2, 24, 25, 168, 169)
    endogenous_max_lookback_hours: int = 336
    exogenous_safe_lags_hours: tuple[int, ...] = (168, 336)
    feature_gap_fill_method: str = "same_hour_previous_day_then_previous_week_then_last_available"
    visual_week_min_observed_coverage_pct: float = 95.0
    visual_week_high_price_threshold: float = 200.0
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    def split_boundaries_local(self) -> dict[str, tuple[date, date]]:
        return {
            "train": (self.train_start_local, self.train_end_local),
            "validation": (self.validation_start_local, self.validation_end_local),
            "test": (self.test_start_local, self.test_end_local),
        }

    def evaluation_splits(self) -> tuple[str, ...]:
        return ("validation", "test")

    def split_for_local_date(self, value: date) -> str | None:
        for split_name, (start_local, end_local) in self.split_boundaries_local().items():
            if start_local <= value <= end_local:
                return split_name
        return None

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["input_csv"] = str(self.input_csv)
        payload["raw_root"] = str(self.raw_root)
        payload["cleaned_feature_root"] = str(self.cleaned_feature_root)
        payload["output_root"] = str(self.output_root)
        payload["price_lags_hours"] = list(self.price_lags_hours)
        payload["endogenous_max_lookback_hours"] = int(self.endogenous_max_lookback_hours)
        payload["exogenous_safe_lags_hours"] = list(self.exogenous_safe_lags_hours)
        payload["monitoring"] = self.monitoring.to_dict()
        for key in (
            "train_start_local",
            "train_end_local",
            "validation_start_local",
            "validation_end_local",
            "test_start_local",
            "test_end_local",
        ):
            payload[key] = payload[key].isoformat()
        return payload

    @staticmethod
    def lead_day_label(lead_day: int) -> str:
        return "D" if lead_day == 0 else f"D+{lead_day}"

    def resolved_business_timezone(self) -> str:
        return MARKET_TIMEZONES.get(self.market_area, self.business_timezone)

    def resolved_holiday_country(self) -> str:
        return MARKET_HOLIDAY_COUNTRIES.get(self.market_area, self.holiday_country)

    def market_domain_codes(self) -> dict[str, str | None]:
        return {
            "price_domain": DA_PRICE_DOMAIN_CODES.get(self.market_area),
            "bidding_zone_domain": BIDDING_ZONE_DOMAIN_CODES.get(self.market_area),
        }
