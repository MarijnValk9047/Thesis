from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding_backtest import run_toy_cvar_stochastic_bidding_sweep  # noqa: E402
from hydrogen.bidding_model import (  # noqa: E402
    build_toy_hourly_scenario_set,
    validate_toy_scenario_probabilities,
)
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")


class ToyStochasticBiddingCvarPhase5bTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.mkdtemp(prefix="phase5b_toy_")
        cls.high_exposure = run_toy_cvar_stochastic_bidding_sweep(
            config=load_hydrogen_config(CONFIG_PATH),
            toy_case="cvar_high_price_exposure",
            bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0, 3000.0],
            gamma_values=[0.0, 0.10, 1.0],
            selected_backtest_gammas=[0.0, 1.0],
            output_root=Path(cls.tempdir) / "high_exposure",
            write_outputs=True,
        )
        cls.overproc = run_toy_cvar_stochastic_bidding_sweep(
            config=load_hydrogen_config(CONFIG_PATH),
            toy_case="cvar_overprocurement_unused_energy",
            bid_price_grid_eur_per_mwh=[0.0, 100.0, 158.0, 250.0, 3000.0],
            gamma_values=[0.0, 0.10, 1.0],
            selected_backtest_gammas=[0.0, 1.0],
            output_root=Path(cls.tempdir) / "overproc",
            write_outputs=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def test_cvar_sign_convention_still_holds(self) -> None:
        row = self.high_exposure.sweep_summary.loc[self.high_exposure.sweep_summary["cvar_gamma"].astype(float) == 0.10].iloc[0]
        expected_objective = (
            float(row["expected_adjusted_profit_eur"])
            - float(row["cvar_gamma"]) * float(row["CVaR_loss"])
            - float(row["regularisation_term"])
        )
        self.assertAlmostEqual(float(row["objective_with_cvar"]), expected_objective, places=5)

    def test_q_remains_nonanticipative(self) -> None:
        self.assertNotIn("scenario_id", self.high_exposure.submitted_bids.columns)
        repeated = (
            self.high_exposure.scenario_clearing.groupby(["cvar_gamma", "delivery_start_utc", "bid_block"])["bid_quantity_mw"]
            .nunique()
            .max()
        )
        self.assertEqual(int(repeated), 1)

    def test_scenario_probabilities_sum_to_one(self) -> None:
        self.assertAlmostEqual(validate_toy_scenario_probabilities(build_toy_hourly_scenario_set("cvar_high_price_exposure")), 1.0, places=9)
        self.assertAlmostEqual(validate_toy_scenario_probabilities(build_toy_hourly_scenario_set("cvar_overprocurement_unused_energy")), 1.0, places=9)

    def test_at_least_one_case_shows_meaningful_change_across_gamma(self) -> None:
        high = self.high_exposure.sweep_summary.sort_values("cvar_gamma").reset_index(drop=True)
        changed = (
            (high["worst_scenario_profit"].astype(float).max() - high["worst_scenario_profit"].astype(float).min()) > 1e-6
            or (high["minimum_scenario_cleared_energy_mwh"].astype(float).max() - high["minimum_scenario_cleared_energy_mwh"].astype(float).min()) > 1e-6
            or (high["expected_shortfall_kg"].astype(float).max() - high["expected_shortfall_kg"].astype(float).min()) > 1e-6
            or (high["expected_unused_cleared_energy_mwh"].astype(float).max() - high["expected_unused_cleared_energy_mwh"].astype(float).min()) > 1e-6
        )
        self.assertTrue(changed)

    def test_bid_price_is_not_used_as_paid_price(self) -> None:
        clearing = self.high_exposure.scenario_clearing
        scenario_results = self.high_exposure.scenario_results
        gamma_zero = clearing.loc[clearing["cvar_gamma"].astype(float) == 0.0]
        weighted_bid_price_cost = float((gamma_zero["bid_price_eur_per_mwh"] * gamma_zero["cleared_energy_mwh"]).sum())
        weighted_market_price_cost = float(
            scenario_results.loc[scenario_results["cvar_gamma"].astype(float) == 0.0, "settlement_cost_eur"].sum()
        )
        self.assertNotAlmostEqual(weighted_bid_price_cost, weighted_market_price_cost, places=3)

    def test_no_production_cap_is_introduced(self) -> None:
        self.assertGreater(float(self.high_exposure.scenario_results["hydrogen_above_target_kg"].max()), 0.0)

    def test_overprocurement_case_activates_unused_energy(self) -> None:
        gamma_zero = self.overproc.sweep_summary.loc[self.overproc.sweep_summary["cvar_gamma"].astype(float) == 0.0].iloc[0]
        self.assertGreater(float(gamma_zero["expected_unused_cleared_energy_mwh"]), 0.0)
        self.assertGreater(float(gamma_zero["expected_unused_energy_penalty_eur"]), 0.0)


if __name__ == "__main__":
    unittest.main()
