from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding import (  # noqa: E402
    HIGH_PRICE_BID_EUR_PER_MWH,
    REFERENCE_PRICE_BID_EUR_PER_MWH,
    dispatch_schedule_to_one_block_bid_curve,
)
from hydrogen.benchmarks import run_price_insensitive  # noqa: E402
from hydrogen.bidding_metrics import compute_bridge_clearing_metrics  # noqa: E402
from hydrogen.clearing import aggregate_cleared_energy, clear_hourly_bids  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")


def _toy_dispatch() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "delivery_start_utc": [
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "2025-01-01T02:00:00Z",
            ],
            "forecast_origin_utc": [
                "2024-12-31T07:00:00Z",
                "2024-12-31T07:00:00Z",
                "2024-12-31T07:00:00Z",
            ],
            "P_el_mw": [10.0, 10.0, 0.0],
            "P_comp_mw": [2.0, 2.0, 0.0],
            "strategy": ["stochastic_risk_neutral"] * 3,
            "model_id": ["toy_model"] * 3,
        }
    )


def _toy_actual_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "delivery_start_utc": [
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "2025-01-01T02:00:00Z",
            ],
            "actual_price_eur_per_mwh": [100.0, 200.0, 250.0],
        }
    )


def _toy_day_frame(actual_prices: list[float], point_prices: list[float]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx, ts in enumerate(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
        ]
    ):
        rows.append(
            {
                "scenario_id": "deterministic",
                "scenario_probability": 1.0,
                "delivery_start_utc": ts,
                "scenario_price_eur_per_mwh": float(actual_prices[idx]),
                "actual_price_eur_per_mwh": float(actual_prices[idx]),
                "point_forecast_eur_per_mwh": float(point_prices[idx]),
                "forecast_origin_utc": "2024-12-31T07:00:00Z",
                "lead_day": 0,
            }
        )
    return pd.DataFrame(rows)


class ScheduleToBidBridgeTests(unittest.TestCase):
    def test_dispatch_schedule_to_one_block_bid_curve_builds_required_columns(self) -> None:
        bid_curve = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="reference_price_bid",
            bid_price_eur_per_mwh=REFERENCE_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        self.assertEqual(
            list(bid_curve.columns),
            [
                "run_id",
                "strategy",
                "source_strategy",
                "bridge_strategy",
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
        self.assertEqual(bid_curve["bid_quantity_mw"].tolist(), [12.0, 12.0, 0.0])
        self.assertTrue((bid_curve["bid_block"] == 0).all())

    def test_reference_price_bid_rejects_hours_above_reference_threshold(self) -> None:
        bid_curve = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="reference_price_bid",
            bid_price_eur_per_mwh=REFERENCE_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        cleared = clear_hourly_bids(bid_curve, _toy_actual_prices())
        self.assertEqual(cleared["accepted"].tolist(), [True, False, False])
        self.assertEqual(cleared["cleared_quantity_mw"].tolist(), [12.0, 0.0, 0.0])

    def test_high_price_bid_clears_all_hours_below_3000_eur_per_mwh(self) -> None:
        bid_curve = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="high_price_bid",
            bid_price_eur_per_mwh=HIGH_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        cleared = clear_hourly_bids(bid_curve, _toy_actual_prices())
        self.assertEqual(cleared["accepted"].tolist(), [True, True, True])
        self.assertEqual(cleared["cleared_quantity_mw"].tolist(), [12.0, 12.0, 0.0])

    def test_zero_scheduled_load_does_not_create_false_rejected_energy(self) -> None:
        bid_curve = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="reference_price_bid",
            bid_price_eur_per_mwh=REFERENCE_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        aggregated = aggregate_cleared_energy(clear_hourly_bids(bid_curve, _toy_actual_prices()))
        last_row = aggregated.sort_values("delivery_start_utc").iloc[-1]
        self.assertEqual(last_row["submitted_energy_mwh"], 0.0)
        self.assertEqual(last_row["cleared_energy_mwh"], 0.0)
        self.assertEqual(last_row["rejected_energy_mwh"], 0.0)
        self.assertEqual(last_row["clearing_ratio"], 0.0)

    def test_bridge_metrics_return_expected_energy_split(self) -> None:
        reference_bids = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="reference_price_bid",
            bid_price_eur_per_mwh=REFERENCE_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        high_bids = dispatch_schedule_to_one_block_bid_curve(
            _toy_dispatch(),
            run_id="phase0_run",
            source_strategy="stochastic_risk_neutral",
            bridge_strategy="high_price_bid",
            bid_price_eur_per_mwh=HIGH_PRICE_BID_EUR_PER_MWH,
            granularity="hourly",
            horizon="D_only",
            scenario_model="toy_model",
        )
        clearing = clear_hourly_bids(pd.concat([reference_bids, high_bids], ignore_index=True), _toy_actual_prices())
        metrics = compute_bridge_clearing_metrics(clearing)
        self.assertEqual(set(metrics["bridge_strategy"]), {"reference_price_bid", "high_price_bid"})

        reference = metrics.loc[metrics["bridge_strategy"] == "reference_price_bid"].iloc[0]
        self.assertEqual(reference["submitted_energy_mwh"], 24.0)
        self.assertEqual(reference["cleared_energy_mwh"], 12.0)
        self.assertEqual(reference["rejected_energy_mwh"], 12.0)
        self.assertEqual(reference["number_of_rejected_bid_rows"], 2)
        self.assertEqual(reference["number_of_hours_with_zero_clearing"], 2)

        high = metrics.loc[metrics["bridge_strategy"] == "high_price_bid"].iloc[0]
        self.assertEqual(high["submitted_energy_mwh"], 24.0)
        self.assertEqual(high["cleared_energy_mwh"], 24.0)
        self.assertEqual(high["rejected_energy_mwh"], 0.0)
        self.assertEqual(high["number_of_rejected_bid_rows"], 0)
        self.assertEqual(high["number_of_hours_with_zero_clearing"], 1)

    def test_price_insensitive_planning_is_invariant_to_da_price_vectors(self) -> None:
        config = load_hydrogen_config(CONFIG_PATH)
        low_price_day = _toy_day_frame([10.0, 20.0, 30.0], [15.0, 25.0, 35.0])
        high_price_day = _toy_day_frame([300.0, 250.0, 200.0], [280.0, 240.0, 220.0])

        low_result = run_price_insensitive(
            day_frame=low_price_day,
            config=config,
            inventory_start_kg=config.hydrogen_system.storage_initial_kg,
            reserve_kg=config.hydrogen_system.reserve_kg,
            apply_terminal_value=True,
            terminal_reference_start_kg=config.hydrogen_system.storage_initial_kg,
            solver_log_path=None,
        )
        high_result = run_price_insensitive(
            day_frame=high_price_day,
            config=config,
            inventory_start_kg=config.hydrogen_system.storage_initial_kg,
            reserve_kg=config.hydrogen_system.reserve_kg,
            apply_terminal_value=True,
            terminal_reference_start_kg=config.hydrogen_system.storage_initial_kg,
            solver_log_path=None,
        )

        pd.testing.assert_frame_equal(
            low_result.dispatch[["P_el_mw", "P_comp_mw", "H_prod_kg", "H_comp_kg", "H_buf_kg", "shortfall_kg"]].reset_index(drop=True),
            high_result.dispatch[["P_el_mw", "P_comp_mw", "H_prod_kg", "H_comp_kg", "H_buf_kg", "shortfall_kg"]].reset_index(drop=True),
            check_exact=False,
            atol=1e-6,
            rtol=0.0,
        )
        self.assertNotEqual(low_price_day["actual_price_eur_per_mwh"].tolist(), high_price_day["actual_price_eur_per_mwh"].tolist())
        self.assertEqual(low_result.solver_status, "Optimal")
        self.assertEqual(high_result.solver_status, "Optimal")
        self.assertIn("planning_objective=minimise_shortfall_then_maximise_hydrogen_output", low_result.warnings)


if __name__ == "__main__":
    unittest.main()
