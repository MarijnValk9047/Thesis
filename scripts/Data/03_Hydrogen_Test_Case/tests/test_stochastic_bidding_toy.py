from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding_model import (  # noqa: E402
    build_phase4a_toy_config,
    build_scenario_acceptance_table,
    build_toy_hourly_scenario_set,
    solve_stochastic_hourly_bidding,
    validate_toy_scenario_probabilities,
    write_stochastic_bidding_toy_run,
)
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")


def _base_config():
    return build_phase4a_toy_config(load_hydrogen_config(CONFIG_PATH))


class ToyStochasticBiddingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mixed_config = _base_config()
        cls.mixed_scenarios = build_toy_hourly_scenario_set("mixed_clearing")
        cls.mixed_result = solve_stochastic_hourly_bidding(
            scenarios=cls.mixed_scenarios,
            config=cls.mixed_config,
            run_id="mixed_toy",
            bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0, 3000.0],
            toy_case="mixed_clearing",
        )

        cls.no_clearing_result = solve_stochastic_hourly_bidding(
            scenarios=build_toy_hourly_scenario_set("no_clearing"),
            config=cls.mixed_config,
            run_id="no_clear_toy",
            bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0],
            toy_case="no_clearing",
        )

        low_target_config = replace(
            cls.mixed_config,
            economics=replace(cls.mixed_config.economics, daily_target_kg=1000.0),
        )
        cls.market_cap_result = solve_stochastic_hourly_bidding(
            scenarios=build_toy_hourly_scenario_set("full_clearing"),
            config=low_target_config,
            run_id="market_cap_toy",
            bid_price_grid_eur_per_mwh=[3000.0],
            toy_case="full_clearing",
        )

    def test_bid_quantities_are_first_stage_and_not_scenario_indexed(self) -> None:
        self.assertNotIn("scenario_id", self.mixed_result.submitted_bids.columns)
        repeated = (
            self.mixed_result.scenario_clearing.groupby(["delivery_start_utc", "bid_block"])["bid_quantity_mw"]
            .nunique()
            .max()
        )
        self.assertEqual(int(repeated), 1)

    def test_acceptance_indicator_matches_bid_threshold_rule(self) -> None:
        acceptance = build_scenario_acceptance_table(self.mixed_scenarios, [0.0, 100.0, 158.0, 250.0, 3000.0])
        for row in acceptance.to_dict(orient="records"):
            expected = int(float(row["bid_price_eur_per_mwh"]) >= float(row["scenario_price_eur_per_mwh"]))
            self.assertEqual(int(row["acceptance_indicator"]), expected)

    def test_cleared_energy_equals_sum_of_accepted_bid_blocks(self) -> None:
        block_sum = (
            self.mixed_result.scenario_clearing.groupby(["scenario_id", "delivery_start_utc"], as_index=False)["cleared_energy_mwh"]
            .sum()
            .sort_values(["scenario_id", "delivery_start_utc"])
            .reset_index(drop=True)
        )
        dispatch = (
            self.mixed_result.scenario_dispatch[["scenario_id", "delivery_start_utc", "cleared_energy_mwh"]]
            .sort_values(["scenario_id", "delivery_start_utc"])
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(block_sum, dispatch, check_exact=False, atol=1e-6, rtol=0.0)

    def test_used_plus_unused_equals_cleared_per_scenario_hour(self) -> None:
        dispatch = self.mixed_result.scenario_dispatch.copy()
        residual = dispatch["used_energy_mwh"] + dispatch["unused_cleared_energy_mwh"] - dispatch["cleared_energy_mwh"]
        self.assertTrue((residual.abs() <= 1e-6).all())

    def test_model_cannot_consume_uncleared_electricity(self) -> None:
        dispatch = self.mixed_result.scenario_dispatch.copy()
        self.assertTrue((dispatch["used_energy_mwh"] <= dispatch["cleared_energy_mwh"] + 1e-6).all())

    def test_scenario_probabilities_sum_to_one(self) -> None:
        total_probability = validate_toy_scenario_probabilities(self.mixed_scenarios)
        self.assertAlmostEqual(total_probability, 1.0, places=9)

    def test_expected_objective_uses_probabilities(self) -> None:
        scenario_economics = self.mixed_result.scenario_economics.copy()
        expected_profit = float(
            (scenario_economics["scenario_probability"] * scenario_economics["adjusted_profit_eur"]).sum()
        )
        summary_value = float(self.mixed_result.summary["expected_adjusted_profit_eur"].iloc[0])
        self.assertAlmostEqual(summary_value, expected_profit, places=5)

    def test_bid_price_is_not_used_as_paid_price(self) -> None:
        weighted_bid_price_cost = float(
            (
                self.mixed_result.scenario_clearing["bid_price_eur_per_mwh"]
                * self.mixed_result.scenario_clearing["cleared_energy_mwh"]
            ).sum()
        )
        weighted_market_price_cost = float(self.mixed_result.scenario_economics["settlement_cost_eur"].sum())
        self.assertNotAlmostEqual(weighted_bid_price_cost, weighted_market_price_cost, places=3)

    def test_all_bid_prices_below_all_scenario_prices_produces_zero_clearing(self) -> None:
        self.assertTrue((self.no_clearing_result.scenario_dispatch["cleared_energy_mwh"].abs() <= 1e-9).all())

    def test_market_cap_bid_clears_when_prices_are_below_cap(self) -> None:
        self.assertTrue(self.market_cap_result.scenario_clearing["accepted"].all())
        self.assertGreater(float(self.market_cap_result.scenario_dispatch["cleared_energy_mwh"].sum()), 0.0)

    def test_no_production_cap_is_introduced(self) -> None:
        above_target = float(self.market_cap_result.scenario_economics["hydrogen_above_target_kg"].max())
        self.assertGreater(above_target, 0.0)

    def test_above_target_hydrogen_is_reported_separately(self) -> None:
        self.assertIn("hydrogen_above_target_kg", self.market_cap_result.scenario_economics.columns)
        self.assertIn("expected_hydrogen_above_target_kg", self.market_cap_result.summary.columns)
        self.assertGreater(float(self.market_cap_result.summary["expected_hydrogen_above_target_kg"].iloc[0]), 0.0)

    def test_solver_status_model_size_objective_and_outputs_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir, result = write_stochastic_bidding_toy_run(
                config=self.mixed_config,
                toy_case="mixed_clearing",
                output_root=Path(tmpdir),
                bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0, 3000.0],
            )
            self.assertTrue((run_dir / "submitted_bids.parquet").exists())
            self.assertTrue((run_dir / "scenario_clearing.parquet").exists())
            self.assertTrue((run_dir / "scenario_dispatch.parquet").exists())
            self.assertTrue((run_dir / "scenario_settlement_results.csv").exists())
            self.assertTrue((run_dir / "stochastic_bidding_toy_summary.csv").exists())
            self.assertTrue((run_dir / "model_stats.json").exists())
            self.assertTrue((run_dir / "README_stochastic_bidding_toy.md").exists())
            self.assertEqual(str(result.solver.status), "Optimal")
            self.assertGreater(int(result.model_stats.variable_count), 0)
            self.assertIsNotNone(result.solver.objective_value)


if __name__ == "__main__":
    unittest.main()
