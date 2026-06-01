from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.bidding_backtest import run_real_scenario_bidding_dry_run  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")
ARTIFACT_ID = "hourly_lear_fs3_promoted_base_plus_b_integration_candidate"


class RealScenarioBiddingDryRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.mkdtemp(prefix="phase6b_real_")
        cls.config = load_hydrogen_config(CONFIG_PATH)
        cls.result = run_real_scenario_bidding_dry_run(
            config=cls.config,
            artifact_id=ARTIFACT_ID,
            output_root=Path(cls.tempdir),
            strategy_name="stochastic_bid_risk_neutral",
            dry_run_label="integration_candidate",
            write_outputs=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def test_selected_origin_probability_sum_is_one(self) -> None:
        scenarios = self.result.scenarios
        probability_sum = float(
            scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
            .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])["scenario_probability"]
            .astype(float)
            .sum()
        )
        self.assertAlmostEqual(probability_sum, 1.0, places=9)

    def test_selected_origin_has_exactly_one_scenario_set(self) -> None:
        self.assertEqual(int(self.result.scenarios["forecast_origin_utc"].nunique()), 1)
        self.assertEqual(int(self.result.scenarios["scenario_id"].astype(str).nunique()), 15)

    def test_submitted_bids_have_no_scenario_id_column(self) -> None:
        self.assertNotIn("scenario_id", self.result.optimisation_result.submitted_bids.columns)

    def test_actual_clearing_uses_bid_price_threshold(self) -> None:
        clearing = self.result.actual_clearing
        expected = clearing["bid_price_eur_per_mwh"].astype(float) >= clearing["actual_price_eur_per_mwh"].astype(float)
        self.assertTrue(clearing["accepted"].astype(bool).eq(expected).all())

    def test_settlement_cost_uses_actual_price_times_cleared_energy(self) -> None:
        hourly = self.result.actual_clearing_by_hour
        expected_settlement = float((hourly["actual_price_eur_per_mwh"].astype(float) * hourly["cleared_energy_mwh"].astype(float)).sum())
        realised_settlement = float(self.result.actual_settlement_results["realised_DA_settlement_cost_eur"].iloc[0])
        self.assertAlmostEqual(expected_settlement, realised_settlement, places=6)

    def test_bid_price_is_not_used_as_paid_price(self) -> None:
        clearing = self.result.actual_clearing
        actual_cost = float((clearing["actual_price_eur_per_mwh"].astype(float) * clearing["cleared_energy_mwh"].astype(float)).sum())
        bid_price_cost = float((clearing["bid_price_eur_per_mwh"].astype(float) * clearing["cleared_energy_mwh"].astype(float)).sum())
        self.assertAlmostEqual(
            actual_cost,
            float(self.result.actual_settlement_results["realised_DA_settlement_cost_eur"].iloc[0]),
            places=6,
        )
        self.assertNotAlmostEqual(actual_cost, bid_price_cost, places=3)

    def test_redispatch_energy_balance_holds(self) -> None:
        timeseries = self.result.actual_redispatch_timeseries
        residual = (
            timeseries["used_energy_mwh"].astype(float)
            + timeseries["unused_cleared_energy_mwh"].astype(float)
            - timeseries["cleared_energy_mwh"].astype(float)
        )
        self.assertTrue((residual.abs() <= 1e-6).all())

    def test_redispatch_does_not_consume_uncleared_electricity(self) -> None:
        timeseries = self.result.actual_redispatch_timeseries
        self.assertTrue((timeseries["used_energy_mwh"].astype(float) <= timeseries["cleared_energy_mwh"].astype(float) + 1e-6).all())

    def test_benchmark_uses_same_delivery_day_and_actual_prices(self) -> None:
        run_dir = self.result.run_dir
        assert run_dir is not None
        benchmark_clearing = pd.read_parquet(run_dir / "benchmark_actual_clearing.parquet")
        actual_prices = self.result.actual_prices.copy()
        benchmark_hourly = (
            benchmark_clearing.groupby("delivery_start_utc", as_index=False)["actual_price_eur_per_mwh"]
            .first()
            .sort_values("delivery_start_utc")
            .reset_index(drop=True)
        )
        actual_prices = actual_prices.sort_values("delivery_start_utc").reset_index(drop=True)
        pd.testing.assert_series_equal(
            benchmark_hourly["delivery_start_utc"],
            actual_prices["delivery_start_utc"],
            check_names=False,
        )
        pd.testing.assert_series_equal(
            benchmark_hourly["actual_price_eur_per_mwh"].astype(float),
            actual_prices["actual_price_eur_per_mwh"].astype(float),
            check_names=False,
            check_exact=False,
            atol=1e-9,
            rtol=0.0,
        )

    def test_integration_candidate_warning_is_written_to_readme_and_validation(self) -> None:
        run_dir = self.result.run_dir
        assert run_dir is not None
        readme = (run_dir / "README_real_scenario_dry_run.md").read_text(encoding="utf-8")
        self.assertIn("integration_candidate", readme)
        self.assertIn("not thesis-grade", readme)
        validation = self.result.validation_checks.set_index("check_name")
        self.assertEqual(str(validation.loc["integration_candidate_warning", "status"]), "warn")
        self.assertEqual(str(validation.loc["forecast_origin_reconstructed_warning", "status"]), "warn")
        self.assertEqual(str(validation.loc["artifact_not_thesis_grade", "status"]), "warn")

    def test_validation_checks_include_hardened_rows(self) -> None:
        validation = self.result.validation_checks.set_index("check_name")
        expected_rows = {
            "actual_prices_complete_for_24_hours": "pass",
            "selected_origin_scenario_count_matches_expected": "pass",
            "selected_origin_probability_mass_equals_one": "pass",
            "q_nonanticipative_single_bid_curve": "pass",
            "pay_as_cleared_settlement": "pass",
            "used_plus_unused_equals_cleared": "pass",
            "benchmark_same_day_alignment": "pass",
            "benchmark_same_actual_prices": "pass",
        }
        for check_name, expected_status in expected_rows.items():
            self.assertIn(check_name, validation.index)
            self.assertEqual(str(validation.loc[check_name, "status"]), expected_status)

    def test_sanity_summary_is_saved_and_consistent(self) -> None:
        run_dir = self.result.run_dir
        assert run_dir is not None
        sanity_path = run_dir / "real_scenario_dry_run_sanity_summary.csv"
        self.assertTrue(sanity_path.exists())
        sanity = pd.read_csv(sanity_path)
        self.assertEqual(int(sanity["scenario_count"].iloc[0]), 15)
        self.assertAlmostEqual(float(sanity["probability_sum"].iloc[0]), 1.0, places=9)
        self.assertEqual(str(sanity["validation_status"].iloc[0]), "warn")
        self.assertFalse(bool(sanity["thesis_grade"].iloc[0]))


if __name__ == "__main__":
    unittest.main()
