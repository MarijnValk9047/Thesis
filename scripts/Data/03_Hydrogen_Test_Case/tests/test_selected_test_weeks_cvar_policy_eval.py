from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_standard_cvar_policy_test_report import build_notebook_payload  # noqa: E402
from hydrogen.selected_test_weeks_cvar_policy_eval import (  # noqa: E402
    _build_model_selection_evidence_summary,
    _load_and_validate_phase_e2_weeks,
    run_selected_test_weeks_cvar_policy_eval,
)


class SelectedTestWeeksCvarPolicyEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_e2_tests_"))
        self.registry_path = self.tempdir / "selected_week_registry_common_support.csv"
        self.support_path = self.tempdir / "common_support_three_model_hourly.csv"
        self.selected_weeks_yaml = self.tempdir / "selected_weeks_common_support.yaml"
        registry = pd.DataFrame(
            [
                {"week_id": "test_20241209_20241215", "period_type": "test", "week_label": "test_high_volatility_week", "regime_label": "high_volatility", "delivery_start_date": "2024-12-09", "delivery_end_date": "2024-12-15", "number_of_delivery_days": 7, "selection_reason": "high_vol", "complete_for_lear_strict": True, "complete_for_lear_fs3": True, "complete_for_xgboost_fs3": True, "complete_actual_prices": True, "support_status": "common_complete_support_selected", "methodological_use": "diagnostic_reporting"},
                {"week_id": "test_20250120_20250126", "period_type": "test", "week_label": "test_high_price_week", "regime_label": "high_price", "delivery_start_date": "2025-01-20", "delivery_end_date": "2025-01-26", "number_of_delivery_days": 7, "selection_reason": "high_price", "complete_for_lear_strict": True, "complete_for_lear_fs3": True, "complete_for_xgboost_fs3": True, "complete_actual_prices": True, "support_status": "common_complete_support_selected", "methodological_use": "diagnostic_reporting"},
                {"week_id": "test_20250113_20250119", "period_type": "test", "week_label": "test_typical_winter_week", "regime_label": "typical_winter", "delivery_start_date": "2025-01-13", "delivery_end_date": "2025-01-19", "number_of_delivery_days": 7, "selection_reason": "typical_winter", "complete_for_lear_strict": True, "complete_for_lear_fs3": True, "complete_for_xgboost_fs3": True, "complete_actual_prices": True, "support_status": "common_complete_support_selected", "methodological_use": "diagnostic_reporting"},
                {"week_id": "test_20250721_20250727", "period_type": "test", "week_label": "test_typical_summer_week", "regime_label": "typical_summer", "delivery_start_date": "2025-07-21", "delivery_end_date": "2025-07-27", "number_of_delivery_days": 7, "selection_reason": "typical_summer", "complete_for_lear_strict": True, "complete_for_lear_fs3": True, "complete_for_xgboost_fs3": True, "complete_actual_prices": True, "support_status": "common_complete_support_selected", "methodological_use": "diagnostic_reporting"},
            ]
        )
        registry.to_csv(self.registry_path, index=False)
        support_rows = []
        for start in ["2024-12-09", "2025-01-20", "2025-01-13", "2025-07-21"]:
            for date in pd.date_range(start, periods=7, freq="D"):
                support_rows.append(
                    {
                        "delivery_date": date.strftime("%Y-%m-%d"),
                        "period_type": "test",
                        "complete_actual_prices": True,
                        "n_hours_actual": 24,
                        "complete_for_lear_strict": True,
                        "n_hours_lear_strict": 24,
                        "n_scenarios_per_origin_lear_strict": 75,
                        "complete_for_lear_fs3": True,
                        "n_hours_lear_fs3": 24,
                        "n_scenarios_per_origin_lear_fs3": 75,
                        "complete_for_xgboost_fs3": True,
                        "n_hours_xgboost_fs3": 24,
                        "n_scenarios_per_origin_xgboost_fs3": 75,
                        "common_complete_support": True,
                        "expected_hours_local_day": 24,
                        "missing_reason": "",
                    }
                )
        pd.DataFrame(support_rows).to_csv(self.support_path, index=False)
        self.selected_weeks_yaml.write_text(
            'selected_weeks:\n'
            '  - label: high_volatility\n'
            '    week_label: test_high_volatility_week\n'
            '    week_id: test_20241209_20241215\n'
            '    regime_label: high_volatility\n'
            '    start_local_date: "2024-12-09"\n'
            '    end_local_date: "2024-12-15"\n'
            '  - label: high_price\n'
            '    week_label: test_high_price_week\n'
            '    week_id: test_20250120_20250126\n'
            '    regime_label: high_price\n'
            '    start_local_date: "2025-01-20"\n'
            '    end_local_date: "2025-01-26"\n'
            '  - label: typical_winter\n'
            '    week_label: test_typical_winter_week\n'
            '    week_id: test_20250113_20250119\n'
            '    regime_label: typical_winter\n'
            '    start_local_date: "2025-01-13"\n'
            '    end_local_date: "2025-01-19"\n'
            '  - label: typical_summer\n'
            '    week_label: test_typical_summer_week\n'
            '    week_id: test_20250721_20250727\n'
            '    regime_label: typical_summer\n'
            '    start_local_date: "2025-07-21"\n'
            '    end_local_date: "2025-07-27"\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_selected_test_week_loading_succeeds(self) -> None:
        weeks, support = _load_and_validate_phase_e2_weeks(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_ids=[
                "high_volatility",
                "high_price",
                "typical_winter",
                "typical_summer",
            ],
        )
        self.assertEqual(int(weeks.shape[0]), 4)
        self.assertEqual(int(support.shape[0]), 28)

    def test_runner_rejects_wrong_gamma_grid_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires gamma grid exactly"):
            run_selected_test_weeks_cvar_policy_eval(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_ids=["high_volatility"],
                artifact_ids=[],
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.10],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=True,
                run_slug="phase_e2_invalid",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_model_selection_summary_contains_model_rows(self) -> None:
        frontier = pd.DataFrame(
            [
                {"artifact_id": "a1", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "validation_week_count": 5, "mean_expected_adjusted_profit": 10.0, "mean_realised_adjusted_profit": 9.0, "median_realised_adjusted_profit": 9.0, "worst_week_realised_adjusted_profit": 6.0, "mean_cvar_loss": -5.0, "mean_cvar_tail_profit": 5.0, "worst_scenario_profit": 1.0, "mean_clearing_ratio": 0.8, "mean_rejected_energy": 10.0, "mean_shortfall": 1.0, "mean_unused_cleared_energy": 2.0, "mean_high_bid_share": 0.2, "mean_uplift_vs_price_insensitive": 3.0, "mean_value_captured_vs_perfect_foresight": 0.5, "mean_regret_vs_perfect_foresight": 4.0, "mean_solve_time_seconds": 1.0},
                {"artifact_id": "a1", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.25, "validation_week_count": 5, "mean_expected_adjusted_profit": 10.0, "mean_realised_adjusted_profit": 11.0, "median_realised_adjusted_profit": 11.0, "worst_week_realised_adjusted_profit": 8.0, "mean_cvar_loss": -7.0, "mean_cvar_tail_profit": 7.0, "worst_scenario_profit": 3.0, "mean_clearing_ratio": 0.82, "mean_rejected_energy": 8.0, "mean_shortfall": 0.0, "mean_unused_cleared_energy": 1.0, "mean_high_bid_share": 0.3, "mean_uplift_vs_price_insensitive": 4.0, "mean_value_captured_vs_perfect_foresight": 0.6, "mean_regret_vs_perfect_foresight": 3.0, "mean_solve_time_seconds": 1.2},
            ]
        )
        weekly = pd.DataFrame(
            [
                {"artifact_id": "a1", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "realised_adjusted_profit": 9.0, "rejected_energy_mwh": 10.0, "unused_cleared_energy_mwh": 2.0, "shortfall_kg": 1.0, "value_captured_vs_perfect_foresight": 0.5, "average_actual_price_paid": 100.0},
                {"artifact_id": "a1", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.25, "realised_adjusted_profit": 11.0, "rejected_energy_mwh": 8.0, "unused_cleared_energy_mwh": 1.0, "shortfall_kg": 0.0, "value_captured_vs_perfect_foresight": 0.6, "average_actual_price_paid": 99.0},
            ]
        )
        summary = _build_model_selection_evidence_summary(frontier, weekly)
        self.assertIn("model_summary", summary["row_type"].astype(str).tolist())

    def test_notebook_payload_supports_multiweek_run(self) -> None:
        run_dir = self.tempdir / "fake_run"
        (run_dir / "notebook_inputs").mkdir(parents=True)
        (run_dir / "figures").mkdir(parents=True)
        payload = build_notebook_payload(run_dir)
        source = "".join("".join(cell.get("source", [])) for cell in payload["cells"])
        self.assertIn("selected_weeks_manifest_table.csv", source)
        self.assertIn("is_multi_week", source)
        self.assertNotIn("run_selected_test_weeks_cvar_policy_eval(", source)


if __name__ == "__main__":
    unittest.main()
