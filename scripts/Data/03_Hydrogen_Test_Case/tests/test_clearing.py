from __future__ import annotations

from pathlib import Path
import sys
import unittest

import math
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding import build_bid_curve_dataframe  # noqa: E402
from hydrogen.clearing import (  # noqa: E402
    aggregate_cleared_energy,
    clear_hourly_bids,
    compute_acceptance_matrix,
    compute_clearing_metrics,
)


def _toy_bid_curve() -> pd.DataFrame:
    return build_bid_curve_dataframe(
        run_id="toy_run",
        strategy="toy_strategy",
        delivery_start_utc=[
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
        ],
        bid_quantities_mw=[
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ],
        forecast_origin_utc="2024-12-31T07:00:00Z",
        granularity="hourly",
        horizon="D_only",
        timestep_hours=1.0,
        bid_price_grid=[100, 200, 300],
        forecast_model="toy_forecast",
    )


def _toy_actual_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "delivery_start_utc": [
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "2025-01-01T02:00:00Z",
            ],
            "actual_price_eur_per_mwh": [50.0, 150.0, 250.0],
        }
    )


class ClearingPrimitiveTests(unittest.TestCase):
    def test_compute_acceptance_matrix_matches_expected_toy_pattern(self) -> None:
        acceptance = compute_acceptance_matrix(_toy_actual_prices(), [100, 200, 300])
        self.assertEqual(acceptance.iloc[0].tolist(), [True, True, True])
        self.assertEqual(acceptance.iloc[1].tolist(), [False, True, True])
        self.assertEqual(acceptance.iloc[2].tolist(), [False, False, True])

    def test_clear_hourly_bids_applies_demand_bid_acceptance_rule(self) -> None:
        cleared = clear_hourly_bids(_toy_bid_curve(), _toy_actual_prices())
        accepted_map = {
            ("2025-01-01 00:00:00+00:00", 0): True,
            ("2025-01-01 00:00:00+00:00", 1): True,
            ("2025-01-01 00:00:00+00:00", 2): True,
            ("2025-01-01 01:00:00+00:00", 0): False,
            ("2025-01-01 01:00:00+00:00", 1): True,
            ("2025-01-01 01:00:00+00:00", 2): True,
            ("2025-01-01 02:00:00+00:00", 0): False,
            ("2025-01-01 02:00:00+00:00", 1): False,
            ("2025-01-01 02:00:00+00:00", 2): True,
        }
        for row in cleared.to_dict(orient="records"):
            key = (str(row["delivery_start_utc"]), int(row["bid_block"]))
            expected = accepted_map[key]
            self.assertIs(bool(row["accepted"]), expected)
            if expected:
                self.assertEqual(row["cleared_quantity_mw"], row["bid_quantity_mw"])
            else:
                self.assertEqual(row["cleared_quantity_mw"], 0.0)
            self.assertEqual(row["cleared_energy_mwh"], row["cleared_quantity_mw"] * row["timestep_hours"])
            self.assertIn(row["actual_price_eur_per_mwh"], {50.0, 150.0, 250.0})

    def test_clear_hourly_bids_rejects_timestamp_mismatch(self) -> None:
        actual_prices = _toy_actual_prices().iloc[:2].copy()
        with self.assertRaises(ValueError):
            clear_hourly_bids(_toy_bid_curve(), actual_prices)

    def test_aggregate_cleared_energy_returns_expected_hourly_summary(self) -> None:
        aggregated = aggregate_cleared_energy(clear_hourly_bids(_toy_bid_curve(), _toy_actual_prices()))
        self.assertEqual(aggregated["submitted_quantity_mw"].tolist(), [3.0, 3.0, 3.0])
        self.assertEqual(aggregated["cleared_quantity_mw"].tolist(), [3.0, 2.0, 1.0])
        self.assertEqual(aggregated["submitted_energy_mwh"].tolist(), [3.0, 3.0, 3.0])
        self.assertEqual(aggregated["cleared_energy_mwh"].tolist(), [3.0, 2.0, 1.0])
        self.assertEqual(aggregated["rejected_energy_mwh"].tolist(), [0.0, 1.0, 2.0])
        self.assertEqual(aggregated["clearing_ratio"].tolist(), [1.0, 2.0 / 3.0, 1.0 / 3.0])
        self.assertTrue(aggregated["clearing_ratio"].between(0.0, 1.0).all())

    def test_compute_clearing_metrics_returns_expected_toy_metrics(self) -> None:
        metrics = compute_clearing_metrics(clear_hourly_bids(_toy_bid_curve(), _toy_actual_prices()))
        self.assertEqual(metrics["total_submitted_energy_mwh"], 9.0)
        self.assertEqual(metrics["total_cleared_energy_mwh"], 6.0)
        self.assertEqual(metrics["rejected_energy_mwh"], 3.0)
        self.assertTrue(math.isclose(metrics["clearing_ratio"], 6.0 / 9.0))
        self.assertEqual(metrics["rejected_bid_rows"], 3)
        self.assertEqual(metrics["hours_with_zero_clearing"], 0)
        self.assertEqual(metrics["hours_with_partial_clearing"], 2)
        self.assertEqual(metrics["average_actual_price_in_cleared_hours"], 150.0)
        self.assertTrue(math.isnan(metrics["average_actual_price_in_rejected_hours"]))

    def test_clear_hourly_bids_detects_duplicate_bid_rows(self) -> None:
        bid_curve = pd.concat([_toy_bid_curve(), _toy_bid_curve().iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            clear_hourly_bids(bid_curve, _toy_actual_prices())

    def test_pay_as_cleared_is_reflected_in_output_price_column(self) -> None:
        cleared = clear_hourly_bids(_toy_bid_curve(), _toy_actual_prices())
        accepted = cleared[cleared["accepted"]].copy()
        self.assertEqual(set(accepted["actual_price_eur_per_mwh"].tolist()), {50.0, 150.0, 250.0})
        self.assertEqual(set(accepted["bid_price_eur_per_mwh"].tolist()), {100.0, 200.0, 300.0})


if __name__ == "__main__":
    unittest.main()
