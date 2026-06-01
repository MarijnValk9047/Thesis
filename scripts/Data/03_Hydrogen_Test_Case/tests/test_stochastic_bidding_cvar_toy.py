from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding_backtest import run_toy_cvar_stochastic_bidding_sweep  # noqa: E402
from hydrogen.bidding_model import (  # noqa: E402
    build_phase4a_toy_config,
    build_phase5a_toy_config,
    build_toy_hourly_scenario_set,
    solve_stochastic_hourly_bidding,
    validate_toy_scenario_probabilities,
)
from hydrogen.cvar import compute_weighted_cvar_from_frame  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")


class ToyStochasticBiddingCvarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.mkdtemp(prefix="phase5a_toy_")
        cls.scenarios = build_toy_hourly_scenario_set("cvar_stress")
        cls.config = build_phase5a_toy_config(load_hydrogen_config(CONFIG_PATH))
        cls.bid_grid = [0.0, 100.0, 158.0, 250.0, 3000.0]

        cls.risk_neutral_result = solve_stochastic_hourly_bidding(
            scenarios=cls.scenarios,
            config=cls.config,
            run_id="phase5a_risk_neutral",
            bid_price_grid_eur_per_mwh=cls.bid_grid,
            toy_case="cvar_stress",
            risk_measure="risk_neutral",
            cvar_alpha=0.95,
            cvar_gamma=0.0,
        )
        cls.gamma_zero_cvar_result = solve_stochastic_hourly_bidding(
            scenarios=cls.scenarios,
            config=cls.config,
            run_id="phase5a_gamma_zero_cvar",
            bid_price_grid_eur_per_mwh=cls.bid_grid,
            toy_case="cvar_stress",
            risk_measure="cvar",
            cvar_alpha=0.95,
            cvar_gamma=0.0,
        )
        cls.risk_averse_result = solve_stochastic_hourly_bidding(
            scenarios=cls.scenarios,
            config=cls.config,
            run_id="phase5a_gamma_one",
            bid_price_grid_eur_per_mwh=cls.bid_grid,
            toy_case="cvar_stress",
            risk_measure="cvar",
            cvar_alpha=0.95,
            cvar_gamma=1.0,
        )
        cls.sweep_result = run_toy_cvar_stochastic_bidding_sweep(
            config=cls.config,
            toy_case="cvar_stress",
            bid_price_grid_eur_per_mwh=cls.bid_grid,
            output_root=Path(cls.tempdir),
            write_outputs=True,
        )

        low_target_config = replace(
            build_phase4a_toy_config(load_hydrogen_config(CONFIG_PATH)),
            economics=replace(cls.config.economics, daily_target_kg=1000.0),
        )
        cls.above_target_result = solve_stochastic_hourly_bidding(
            scenarios=build_toy_hourly_scenario_set("full_clearing"),
            config=low_target_config,
            run_id="phase5a_above_target",
            bid_price_grid_eur_per_mwh=[3000.0],
            toy_case="full_clearing",
            risk_measure="risk_neutral",
            cvar_alpha=0.95,
            cvar_gamma=0.0,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def test_gamma_zero_reproduces_risk_neutral_solution_within_tolerance(self) -> None:
        neutral_bids = self.risk_neutral_result.submitted_bids[["delivery_start_utc", "bid_block", "bid_quantity_mw"]].copy()
        gamma_zero_bids = self.gamma_zero_cvar_result.submitted_bids[["delivery_start_utc", "bid_block", "bid_quantity_mw"]].copy()
        neutral_bids = neutral_bids.sort_values(["delivery_start_utc", "bid_block"]).reset_index(drop=True)
        gamma_zero_bids = gamma_zero_bids.sort_values(["delivery_start_utc", "bid_block"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(neutral_bids, gamma_zero_bids, check_exact=False, atol=1e-6, rtol=0.0)
        self.assertAlmostEqual(
            float(self.risk_neutral_result.summary["expected_adjusted_profit_eur"].iloc[0]),
            float(self.gamma_zero_cvar_result.summary["expected_adjusted_profit_eur"].iloc[0]),
            places=6,
        )

    def test_scenario_probabilities_sum_to_one_before_cvar_solve(self) -> None:
        self.assertAlmostEqual(validate_toy_scenario_probabilities(self.scenarios), 1.0, places=9)

    def test_xi_is_greater_equal_loss_minus_zeta(self) -> None:
        details = self.risk_averse_result.cvar_details.copy()
        residual = details["xi_loss_excess_eur"].astype(float) - (
            details["loss_eur"].astype(float) - details["zeta_loss_eur"].astype(float)
        )
        self.assertTrue((residual >= -1e-6).all())

    def test_xi_is_nonnegative(self) -> None:
        self.assertTrue((self.risk_averse_result.cvar_details["xi_loss_excess_eur"].astype(float) >= -1e-9).all())

    def test_cvar_expression_uses_probabilities(self) -> None:
        scenario_economics = self.risk_averse_result.scenario_economics.copy()
        expected_cvar = compute_weighted_cvar_from_frame(
            scenario_economics,
            loss_column="loss_eur",
            probability_column="scenario_probability",
            alpha=0.95,
        )
        summary_cvar = float(self.risk_averse_result.summary["CVaR_loss"].iloc[0])
        self.assertAlmostEqual(summary_cvar, float(expected_cvar.cvar), places=5)

    def test_objective_sign_penalises_cvar_loss(self) -> None:
        summary = self.risk_averse_result.summary.iloc[0]
        expected_objective = (
            float(summary["expected_adjusted_profit_without_regularisation"])
            - float(summary["cvar_gamma"]) * float(summary["CVaR_loss"])
            - float(summary["regularisation_term"])
        )
        self.assertAlmostEqual(float(summary["objective_with_regularisation"]), expected_objective, places=5)

    def test_cvar_outputs_include_zeta_and_xi(self) -> None:
        self.assertIsNotNone(self.risk_averse_result.zeta_loss_eur)
        self.assertIsNotNone(self.risk_averse_result.cvar_loss_eur)
        self.assertIn("zeta_loss_eur", self.risk_averse_result.cvar_details.columns)
        self.assertIn("xi_loss_excess_eur", self.risk_averse_result.cvar_details.columns)

    def test_bid_price_is_still_not_used_as_paid_electricity_price(self) -> None:
        weighted_bid_price_cost = float(
            (
                self.risk_averse_result.scenario_clearing["bid_price_eur_per_mwh"]
                * self.risk_averse_result.scenario_clearing["cleared_energy_mwh"]
            ).sum()
        )
        weighted_market_price_cost = float(self.risk_averse_result.scenario_economics["settlement_cost_eur"].sum())
        self.assertNotAlmostEqual(weighted_bid_price_cost, weighted_market_price_cost, places=3)

    def test_q_remains_nonanticipative(self) -> None:
        self.assertNotIn("scenario_id", self.risk_averse_result.submitted_bids.columns)
        repeated = (
            self.risk_averse_result.scenario_clearing.groupby(["delivery_start_utc", "bid_block"])["bid_quantity_mw"]
            .nunique()
            .max()
        )
        self.assertEqual(int(repeated), 1)

    def test_no_production_cap_is_introduced(self) -> None:
        above_target = float(self.above_target_result.scenario_economics["hydrogen_above_target_kg"].max())
        self.assertGreater(above_target, 0.0)

    def test_above_target_hydrogen_remains_reported_separately(self) -> None:
        self.assertIn("hydrogen_above_target_kg", self.above_target_result.scenario_economics.columns)
        self.assertIn("expected_hydrogen_above_target_kg", self.above_target_result.summary.columns)
        self.assertGreater(float(self.above_target_result.summary["expected_hydrogen_above_target_kg"].iloc[0]), 0.0)

    def test_sweep_outputs_are_created(self) -> None:
        run_dir = self.sweep_result.run_dir
        assert run_dir is not None
        expected_files = [
            "cvar_sweep_summary.csv",
            "cvar_scenario_results.csv",
            "cvar_submitted_bids.parquet",
            "cvar_scenario_clearing.parquet",
            "cvar_scenario_dispatch.parquet",
            "cvar_backtest_results.csv",
            "model_stats_by_gamma.csv",
            "README_cvar_stochastic_bidding_toy.md",
        ]
        for name in expected_files:
            self.assertTrue((run_dir / name).exists(), msg=name)


if __name__ == "__main__":
    unittest.main()
