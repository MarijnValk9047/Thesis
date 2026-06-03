from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.validation_cvar_sweep import (  # noqa: E402
    _build_cvar_validation_checks,
    _load_and_validate_phase_d_week,
    run_validation_week_cvar_smoke_sweep,
)


class ValidationCvarSmokeSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_d_tests_"))
        self.registry_path = self.tempdir / "selected_week_registry_common_support.csv"
        self.support_path = self.tempdir / "common_support_three_model_hourly.csv"
        self.selected_weeks_yaml = self.tempdir / "selected_weeks_common_support.yaml"
        registry = pd.DataFrame(
            [
                {
                    "week_id": "validation_20231016_20231022",
                    "period_type": "validation",
                    "week_label": "validation_high_price_week",
                    "regime_label": "high_price",
                    "delivery_start_date": "2023-10-16",
                    "delivery_end_date": "2023-10-22",
                    "number_of_delivery_days": 7,
                    "selection_reason": "validation high price week",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "cvar_selection",
                }
            ]
        )
        registry.to_csv(self.registry_path, index=False)
        support = pd.DataFrame(
            {
                "delivery_date": pd.date_range("2023-10-16", "2023-10-22", freq="D"),
                "period_type": ["validation"] * 7,
                "complete_actual_prices": [True] * 7,
                "n_hours_actual": [24] * 7,
                "complete_for_lear_strict": [True] * 7,
                "n_hours_lear_strict": [24] * 7,
                "n_scenarios_per_origin_lear_strict": [75] * 7,
                "complete_for_lear_fs3": [True] * 7,
                "n_hours_lear_fs3": [24] * 7,
                "n_scenarios_per_origin_lear_fs3": [75] * 7,
                "complete_for_xgboost_fs3": [True] * 7,
                "n_hours_xgboost_fs3": [24] * 7,
                "n_scenarios_per_origin_xgboost_fs3": [75] * 7,
                "common_complete_support": [True] * 7,
            }
        )
        support.to_csv(self.support_path, index=False)
        self.selected_weeks_yaml.write_text(
            'selected_weeks:\n'
            '  - label: high_price\n'
            '    week_label: validation_high_price_week\n'
            '    week_id: validation_20231016_20231022\n'
            '    regime_label: high_price\n'
            '    start_local_date: "2023-10-16"\n'
            '    end_local_date: "2023-10-22"\n'
            '    notes: cvar_selection\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_validation_week_loading_succeeds(self) -> None:
        week, support = _load_and_validate_phase_d_week(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_id="high_price",
        )
        self.assertEqual(str(week["week_label"]), "validation_high_price_week")
        self.assertEqual(str(week["methodological_use"]), "cvar_selection")
        self.assertEqual(int(support.shape[0]), 7)

    def test_validation_week_loading_fails_if_test_week_is_presented(self) -> None:
        registry = pd.read_csv(self.registry_path)
        registry.loc[0, "period_type"] = "test"
        registry.to_csv(self.registry_path, index=False)
        with self.assertRaisesRegex(ValueError, "Expected exactly one registry row|expected validation"):
            _load_and_validate_phase_d_week(
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
                week_id="high_price",
            )

    def test_runner_rejects_wrong_gamma_grid_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires gamma grid exactly"):
            run_validation_week_cvar_smoke_sweep(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_id="high_price",
                artifact_ids=[],
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.10],
                include_price_insensitive_benchmark=True,
                run_slug="phase_d_invalid",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_cvar_validation_checks_detect_inconsistent_values(self) -> None:
        daily = pd.DataFrame(
            [
                {
                    "cvar_alpha": 0.95,
                    "cvar_gamma": 0.0,
                    "risk_mode": "risk_neutral",
                    "var_loss": 10.0,
                    "cvar_loss": 9.0,
                    "cvar_reconstruction_error": 0.1,
                    "worst_scenario_loss": 8.0,
                    "model_label": "LEAR Strict",
                    "weighted_average_bid_price": 150.0,
                    "expected_adjusted_profit": 100.0,
                },
                {
                    "cvar_alpha": 0.95,
                    "cvar_gamma": 0.05,
                    "risk_mode": "cvar",
                    "var_loss": 12.0,
                    "cvar_loss": 13.0,
                    "cvar_reconstruction_error": 0.0,
                    "worst_scenario_loss": 14.0,
                    "model_label": "LEAR Strict",
                    "weighted_average_bid_price": 150.0,
                    "expected_adjusted_profit": 100.0,
                },
                {
                    "cvar_alpha": 0.95,
                    "cvar_gamma": 0.25,
                    "risk_mode": "cvar",
                    "var_loss": 12.0,
                    "cvar_loss": 13.0,
                    "cvar_reconstruction_error": 0.0,
                    "worst_scenario_loss": 14.0,
                    "model_label": "LEAR Strict",
                    "weighted_average_bid_price": 150.0,
                    "expected_adjusted_profit": 100.0,
                },
            ]
        )
        weekly = daily.copy()
        scenario_results = pd.DataFrame(
            [
                {"artifact_id": "a", "delivery_day": "2023-10-16", "cvar_gamma": 0.0, "scenario_probability": 0.5, "xi_loss_excess_eur": -0.1},
                {"artifact_id": "a", "delivery_day": "2023-10-16", "cvar_gamma": 0.0, "scenario_probability": 0.4, "xi_loss_excess_eur": 0.0},
            ]
        )
        checks = _build_cvar_validation_checks(
            daily_metrics=daily,
            weekly_metrics=weekly,
            scenario_settlement_results=scenario_results,
            gamma_values=[0.0, 0.05, 0.25],
            cvar_alpha=0.95,
        )
        status_by_check = checks.set_index("check_name")["status"].astype(str)
        self.assertEqual(status_by_check["excess_loss_variables_nonnegative"], "fail")
        self.assertEqual(status_by_check["cvar_loss_ge_var_loss"], "fail")
        self.assertEqual(status_by_check["reconstructed_cvar_matches_reported"], "fail")
        self.assertEqual(status_by_check["scenario_probabilities_sum_to_one_per_origin"], "fail")


if __name__ == "__main__":
    unittest.main()
