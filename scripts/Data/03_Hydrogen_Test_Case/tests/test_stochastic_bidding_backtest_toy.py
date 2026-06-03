from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding_backtest import run_toy_stochastic_bidding_backtest  # noqa: E402
from hydrogen.bidding_model import build_phase4a_toy_config  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")


class ToyStochasticBiddingBacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.mkdtemp(prefix="phase4b_toy_")
        config = build_phase4a_toy_config(load_hydrogen_config(CONFIG_PATH))
        cls.result = run_toy_stochastic_bidding_backtest(
            config=config,
            toy_case="mixed_clearing",
            bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0, 3000.0],
            output_root=Path(cls.tempdir),
            write_outputs=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def test_submitted_bid_curve_has_no_scenario_id_column(self) -> None:
        self.assertNotIn("scenario_id", self.result.optimisation_result.submitted_bids.columns)

    def test_actual_clearing_uses_bid_price_greater_equal_actual_price(self) -> None:
        for row in self.result.actual_clearing.to_dict(orient="records"):
            expected = float(row["bid_price_eur_per_mwh"]) >= float(row["actual_price_eur_per_mwh"])
            self.assertEqual(bool(row["accepted"]), expected)

    def test_actual_clearing_cost_uses_actual_price_not_bid_price(self) -> None:
        for actual_path_id, cleared in self.result.actual_clearing.groupby("actual_path_id", sort=True):
            realised_cost = float((cleared["actual_price_eur_per_mwh"] * cleared["cleared_energy_mwh"]).sum())
            bid_price_cost = float((cleared["bid_price_eur_per_mwh"] * cleared["cleared_energy_mwh"]).sum())
            summary_row = self.result.actual_settlement_results.loc[
                self.result.actual_settlement_results["actual_path_id"] == actual_path_id
            ].iloc[0]
            self.assertAlmostEqual(realised_cost, float(summary_row["realised_DA_settlement_cost_eur"]), places=5)
            self.assertNotAlmostEqual(realised_cost, bid_price_cost, places=3)

    def test_deterministic_redispatch_cannot_consume_uncleared_electricity(self) -> None:
        frame = self.result.actual_redispatch_timeseries
        self.assertTrue((frame["used_energy_mwh"] <= frame["cleared_energy_mwh"] + 1e-6).all())

    def test_used_plus_unused_equals_cleared(self) -> None:
        frame = self.result.actual_redispatch_timeseries
        residual = frame["used_energy_mwh"] + frame["unused_cleared_energy_mwh"] - frame["cleared_energy_mwh"]
        self.assertTrue((residual.abs() <= 1e-6).all())

    def test_realised_low_clears_at_least_as_much_as_realised_high(self) -> None:
        summary = self.result.stochastic_vs_realised_summary.set_index("actual_path_id")
        self.assertGreaterEqual(
            float(summary.loc["realised_low", "cleared_energy_mwh"]),
            float(summary.loc["realised_high", "cleared_energy_mwh"]),
        )

    def test_realised_high_has_lower_or_equal_cleared_energy_than_realised_low(self) -> None:
        summary = self.result.stochastic_vs_realised_summary.set_index("actual_path_id")
        self.assertLessEqual(
            float(summary.loc["realised_high", "cleared_energy_mwh"]),
            float(summary.loc["realised_low", "cleared_energy_mwh"]),
        )

    def test_regularisation_term_is_reported_and_small(self) -> None:
        summary = self.result.stochastic_vs_realised_summary
        self.assertIn("regularisation_term", summary.columns)
        self.assertIn("regularisation_weight", summary.columns)
        self.assertTrue((summary["regularisation_term"].astype(float) > 0.0).all())
        self.assertTrue((summary["regularisation_term"].astype(float) < 1.0).all())

    def test_no_production_cap_is_introduced(self) -> None:
        settlement = self.result.actual_settlement_results
        self.assertTrue((settlement["target_fulfilment_ratio_capped_for_reliability"].astype(float) <= 1.0 + 1e-9).all())
        self.assertGreater(float(settlement["production_to_target_ratio_uncapped"].max()), 1.0)

    def test_above_target_hydrogen_is_reported_separately(self) -> None:
        settlement = self.result.actual_settlement_results
        self.assertIn("hydrogen_above_target_kg", settlement.columns)
        self.assertGreater(float(settlement["hydrogen_above_target_kg"].max()), 0.0)

    def test_output_files_are_created(self) -> None:
        run_dir = self.result.run_dir
        assert run_dir is not None
        expected_files = [
            "stochastic_submitted_bids.parquet",
            "actual_clearing.parquet",
            "actual_clearing_by_hour.parquet",
            "actual_redispatch_timeseries.parquet",
            "actual_settlement_results.csv",
            "stochastic_vs_realised_summary.csv",
            "scenario_objective_summary.csv",
            "model_stats.json",
            "README_stochastic_bidding_backtest_toy.md",
        ]
        for name in expected_files:
            self.assertTrue((run_dir / name).exists(), msg=name)


if __name__ == "__main__":
    unittest.main()
