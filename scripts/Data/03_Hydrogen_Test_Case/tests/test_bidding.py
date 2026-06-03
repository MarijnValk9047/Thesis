from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd
from pandas import DatetimeTZDtype

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding import (  # noqa: E402
    DEFAULT_BID_PRICE_GRID_EUR_PER_MWH,
    build_bid_curve_dataframe,
    build_bid_price_grid,
    validate_bid_price_grid,
)


class BidPriceGridTests(unittest.TestCase):
    def test_validate_bid_price_grid_accepts_strictly_increasing_numeric_values(self) -> None:
        grid = validate_bid_price_grid([100, 200, 300])
        self.assertEqual(grid, [100.0, 200.0, 300.0])

    def test_validate_bid_price_grid_rejects_invalid_values(self) -> None:
        for grid in ([100, 100, 300], [100, float("nan"), 300], [200, 100, 300], [100, "bad", 300]):
            with self.assertRaises(ValueError):
                validate_bid_price_grid(grid)

    def test_build_bid_price_grid_reads_configured_grid_from_yaml(self) -> None:
        config = {"bidding": {"bid_price_grid_eur_per_mwh": [10, 20, 30]}}
        self.assertEqual(build_bid_price_grid(config), [10.0, 20.0, 30.0])

    def test_build_bid_price_grid_uses_default_when_not_configured(self) -> None:
        self.assertEqual(build_bid_price_grid({}), list(DEFAULT_BID_PRICE_GRID_EUR_PER_MWH))


class BidCurveBuilderTests(unittest.TestCase):
    def test_build_bid_curve_dataframe_builds_stable_schema(self) -> None:
        bid_curve = build_bid_curve_dataframe(
            run_id="toy_run",
            strategy="toy_strategy",
            delivery_start_utc=[
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "2025-01-01T02:00:00Z",
            ],
            bid_quantities_mw=[
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
            ],
            forecast_origin_utc="2024-12-31T07:00:00Z",
            granularity="hourly",
            horizon="D_only",
            timestep_hours=1.0,
            bid_price_grid=[100, 200, 300],
            forecast_model="toy_forecast",
            max_total_quantity_mw=30.0,
        )
        self.assertEqual(
            list(bid_curve.columns),
            [
                "run_id",
                "strategy",
                "forecast_model",
                "scenario_model",
                "granularity",
                "horizon",
                "forecast_origin_utc",
                "delivery_start_utc",
                "bid_block",
                "bid_price_eur_per_mwh",
                "bid_quantity_mw",
                "timestep_hours",
            ],
        )
        self.assertEqual(bid_curve.shape[0], 9)
        self.assertEqual(bid_curve["delivery_start_utc"].nunique(), 3)
        self.assertEqual(bid_curve["bid_block"].nunique(), 3)

    def test_build_bid_curve_dataframe_rejects_negative_quantities(self) -> None:
        with self.assertRaises(ValueError):
            build_bid_curve_dataframe(
                run_id="toy_run",
                strategy="toy_strategy",
                delivery_start_utc=["2025-01-01T00:00:00Z"],
                bid_quantities_mw=[-1.0, 2.0, 3.0],
                forecast_origin_utc="2024-12-31T07:00:00Z",
                granularity="hourly",
                horizon="D_only",
                timestep_hours=1.0,
                bid_price_grid=[100, 200, 300],
            )

    def test_build_bid_curve_dataframe_clips_solver_noise_scale_negative_quantities(self) -> None:
        bid_curve = build_bid_curve_dataframe(
            run_id="toy_run",
            strategy="toy_strategy",
            delivery_start_utc=["2025-01-01T00:00:00Z"],
            bid_quantities_mw=[-2.5e-13, 2.0, 3.0],
            forecast_origin_utc="2024-12-31T07:00:00Z",
            granularity="hourly",
            horizon="D_only",
            timestep_hours=1.0,
            bid_price_grid=[100, 200, 300],
        )
        self.assertEqual(bid_curve["bid_quantity_mw"].tolist(), [0.0, 2.0, 3.0])

    def test_build_bid_curve_dataframe_rejects_duplicate_delivery_timestamps(self) -> None:
        with self.assertRaises(ValueError):
            build_bid_curve_dataframe(
                run_id="toy_run",
                strategy="toy_strategy",
                delivery_start_utc=[
                    "2025-01-01T00:00:00Z",
                    "2025-01-01T00:00:00Z",
                ],
                bid_quantities_mw=[
                    [1.0, 2.0, 3.0],
                    [1.0, 2.0, 3.0],
                ],
                forecast_origin_utc="2024-12-31T07:00:00Z",
                granularity="hourly",
                horizon="D_only",
                timestep_hours=1.0,
                bid_price_grid=[100, 200, 300],
            )

    def test_build_bid_curve_dataframe_checks_hourly_capacity_when_provided(self) -> None:
        with self.assertRaises(ValueError):
            build_bid_curve_dataframe(
                run_id="toy_run",
                strategy="toy_strategy",
                delivery_start_utc=["2025-01-01T00:00:00Z"],
                bid_quantities_mw=[4.0, 5.0, 6.0],
                forecast_origin_utc="2024-12-31T07:00:00Z",
                granularity="hourly",
                horizon="D_only",
                timestep_hours=1.0,
                bid_price_grid=[100, 200, 300],
                max_total_quantity_mw=10.0,
            )

    def test_build_bid_curve_dataframe_supports_single_hour_vector_input(self) -> None:
        bid_curve = build_bid_curve_dataframe(
            run_id="toy_run",
            strategy="toy_strategy",
            delivery_start_utc=["2025-01-01T00:00:00Z"],
            bid_quantities_mw=[1.0, 2.0, 3.0],
            forecast_origin_utc="2024-12-31T07:00:00Z",
            granularity="hourly",
            horizon="D_only",
            timestep_hours=1.0,
            bid_price_grid=[100, 200, 300],
        )
        self.assertEqual(bid_curve["bid_quantity_mw"].tolist(), [1.0, 2.0, 3.0])
        self.assertIsInstance(bid_curve["delivery_start_utc"].dtype, DatetimeTZDtype)


if __name__ == "__main__":
    unittest.main()
