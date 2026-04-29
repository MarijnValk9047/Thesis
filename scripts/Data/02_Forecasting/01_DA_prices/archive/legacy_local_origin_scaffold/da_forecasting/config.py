from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ForecastSetup:
    input_csv: Path = Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv")
    output_root: Path = Path("data/02_Forecasting/01_DA_prices")
    market_area: str = "NL"
    timestamp_col: str = "timestamp_utc"
    target_col: str = "price_eur_per_mwh"
    local_timezone: str = "Europe/Amsterdam"
    origin_hour_local: int = 0
    origin_step_days: int = 1
    horizon_days: int = 5
    train_start: date = date(2022, 1, 1)
    train_end: date = date(2023, 9, 30)
    validation_start: date = date(2023, 10, 1)
    validation_end: date = date(2024, 9, 30)
    test_start: date = date(2024, 10, 1)
    test_end: date = date(2025, 9, 30)

    def split_boundaries(self) -> dict[str, tuple[date, date]]:
        return {
            "train": (self.train_start, self.train_end),
            "validation": (self.validation_start, self.validation_end),
            "test": (self.test_start, self.test_end),
        }

    def split_for_local_date(self, value: date) -> str | None:
        for split_name, (start, end) in self.split_boundaries().items():
            if start <= value <= end:
                return split_name
        return None

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["input_csv"] = str(self.input_csv)
        payload["output_root"] = str(self.output_root)
        for key in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        ):
            payload[key] = payload[key].isoformat()
        return payload
