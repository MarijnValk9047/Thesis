from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_cvar_validation_sensitivity_notebook import build_notebook_payload  # noqa: E402
from hydrogen.validation_cvar_expanded_sweep import (  # noqa: E402
    _aggregate_perfect_foresight_metrics,
    _build_gamma_policy_candidate_summary,
    _build_cvar_frontier_aggregated,
    _load_and_validate_phase_d2_weeks,
    run_validation_cvar_expanded_sweep,
)


class ValidationCvarExpandedSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_d2_tests_"))
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
                    "selection_reason": "high_price",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "cvar_selection",
                },
                {
                    "week_id": "validation_20231106_20231112",
                    "period_type": "validation",
                    "week_label": "validation_winter_proxy_week",
                    "regime_label": "winter_proxy",
                    "delivery_start_date": "2023-11-06",
                    "delivery_end_date": "2023-11-12",
                    "number_of_delivery_days": 7,
                    "selection_reason": "winter_proxy_backup",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "cvar_selection",
                },
                {
                    "week_id": "validation_20240610_20240616",
                    "period_type": "validation",
                    "week_label": "validation_high_volatility_week",
                    "regime_label": "high_volatility",
                    "delivery_start_date": "2024-06-10",
                    "delivery_end_date": "2024-06-16",
                    "number_of_delivery_days": 7,
                    "selection_reason": "high_volatility",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "cvar_selection",
                },
                {
                    "week_id": "validation_20240617_20240623",
                    "period_type": "validation",
                    "week_label": "validation_typical_summer_week",
                    "regime_label": "typical_summer",
                    "delivery_start_date": "2024-06-17",
                    "delivery_end_date": "2024-06-23",
                    "number_of_delivery_days": 7,
                    "selection_reason": "typical_summer",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "cvar_selection",
                },
            ]
        )
        registry.to_csv(self.registry_path, index=False)
        support_rows = []
        for week_label, start in [
            ("validation_high_price_week", "2023-10-16"),
            ("validation_winter_proxy_week", "2023-11-06"),
            ("validation_high_volatility_week", "2024-06-10"),
            ("validation_typical_summer_week", "2024-06-17"),
        ]:
            for date in pd.date_range(start, periods=7, freq="D"):
                support_rows.append(
                    {
                        "delivery_date": date.strftime("%Y-%m-%d"),
                        "period_type": "validation",
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
            '  - label: high_price\n'
            '    week_label: validation_high_price_week\n'
            '    week_id: validation_20231016_20231022\n'
            '    regime_label: high_price\n'
            '    start_local_date: "2023-10-16"\n'
            '    end_local_date: "2023-10-22"\n'
            '    notes: cvar_selection\n'
            '  - label: winter_proxy\n'
            '    week_label: validation_winter_proxy_week\n'
            '    week_id: validation_20231106_20231112\n'
            '    regime_label: winter_proxy\n'
            '    start_local_date: "2023-11-06"\n'
            '    end_local_date: "2023-11-12"\n'
            '    notes: cvar_selection\n'
            '  - label: high_volatility\n'
            '    week_label: validation_high_volatility_week\n'
            '    week_id: validation_20240610_20240616\n'
            '    regime_label: high_volatility\n'
            '    start_local_date: "2024-06-10"\n'
            '    end_local_date: "2024-06-16"\n'
            '    notes: cvar_selection\n'
            '  - label: typical_summer\n'
            '    week_label: validation_typical_summer_week\n'
            '    week_id: validation_20240617_20240623\n'
            '    regime_label: typical_summer\n'
            '    start_local_date: "2024-06-17"\n'
            '    end_local_date: "2024-06-23"\n'
            '    notes: cvar_selection\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_expanded_validation_week_loading_succeeds(self) -> None:
        weeks, support = _load_and_validate_phase_d2_weeks(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_ids=["high_price", "winter_proxy", "high_volatility", "typical_summer"],
        )
        self.assertEqual(int(weeks.shape[0]), 4)
        self.assertEqual(int(support.shape[0]), 28)
        self.assertTrue(weeks["methodological_use"].astype(str).eq("cvar_selection").all())

    def test_expanded_validation_week_loading_fails_if_test_week_leaks_in(self) -> None:
        registry = pd.read_csv(self.registry_path)
        registry.loc[0, "period_type"] = "test"
        registry.to_csv(self.registry_path, index=False)
        with self.assertRaisesRegex(ValueError, "Expected exactly one registry row|Phase D2 selected-week validation failed"):
            _load_and_validate_phase_d2_weeks(
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
                week_ids=["high_price", "winter_proxy", "high_volatility", "typical_summer"],
            )

    def test_runner_rejects_wrong_gamma_grid_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires gamma grid exactly"):
            run_validation_cvar_expanded_sweep(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_ids=["high_price", "winter_proxy", "high_volatility", "typical_summer"],
                artifact_ids=[],
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.10],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=False,
                run_slug="phase_d2_invalid",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_gamma_policy_summary_marks_dominated_gamma(self) -> None:
        weekly = pd.DataFrame(
            [
                {"artifact_id": "a", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "week_id": "w1", "expected_adjusted_profit": 100.0, "realised_adjusted_profit": 90.0, "cvar_loss": -40.0, "worst_scenario_profit": 40.0, "clearing_ratio": 0.8, "rejected_energy_mwh": 10.0, "shortfall_kg": 5.0, "unused_cleared_energy_mwh": 3.0, "high_bid_share": 0.2, "stochastic_minus_benchmark_profit": 5.0, "value_captured_vs_perfect_foresight": 0.5, "regret_vs_perfect_foresight": 10.0, "solve_time_seconds": 1.0},
                {"artifact_id": "a", "model_label": "LEAR Strict", "cvar_alpha": 0.95, "cvar_gamma": 0.1, "week_id": "w1", "expected_adjusted_profit": 101.0, "realised_adjusted_profit": 95.0, "cvar_loss": -45.0, "worst_scenario_profit": 42.0, "clearing_ratio": 0.85, "rejected_energy_mwh": 9.0, "shortfall_kg": 4.0, "unused_cleared_energy_mwh": 2.0, "high_bid_share": 0.21, "stochastic_minus_benchmark_profit": 6.0, "value_captured_vs_perfect_foresight": 0.55, "regret_vs_perfect_foresight": 9.0, "solve_time_seconds": 1.0},
            ]
        )
        agg = _build_cvar_frontier_aggregated(weekly)
        summary = _build_gamma_policy_candidate_summary(agg)
        gamma0 = summary.loc[summary["gamma"].astype(float).eq(0.0)].iloc[0]
        self.assertTrue(bool(gamma0["dominated_flag"]))

    def test_perfect_foresight_aggregation_builds_weekly_rows(self) -> None:
        pf_daily = pd.DataFrame(
            [
                {"run_id": "r1", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "period_type": "validation", "aggregation_level": "daily", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "strategy": "perfect_foresight_oracle_market_cap", "realised_adjusted_profit": 100.0, "cleared_energy_mwh": 10.0, "used_energy_mwh": 10.0, "unused_cleared_energy_mwh": 0.0, "hydrogen_sold_or_compressed_kg": 1000.0, "shortfall_kg": 0.0, "da_settlement_cost": 50.0, "hydrogen_revenue": 200.0, "unused_energy_penalty": 0.0, "shortfall_penalty": 0.0, "terminal_inventory_correction": 0.0, "average_actual_price_paid": 5.0, "solver_status": "Optimal", "solve_time_seconds": 1.0},
                {"run_id": "r1", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "period_type": "validation", "aggregation_level": "daily", "delivery_day": "2023-10-17", "forecast_origin_utc": "2023-10-16T06:00:00Z", "strategy": "perfect_foresight_oracle_market_cap", "realised_adjusted_profit": 120.0, "cleared_energy_mwh": 11.0, "used_energy_mwh": 11.0, "unused_cleared_energy_mwh": 0.0, "hydrogen_sold_or_compressed_kg": 1100.0, "shortfall_kg": 0.0, "da_settlement_cost": 55.0, "hydrogen_revenue": 220.0, "unused_energy_penalty": 0.0, "shortfall_penalty": 0.0, "terminal_inventory_correction": 0.0, "average_actual_price_paid": 5.0, "solver_status": "Optimal", "solve_time_seconds": 1.5},
            ]
        )
        metrics = _aggregate_perfect_foresight_metrics(pf_daily)
        self.assertIn("weekly", metrics["aggregation_level"].astype(str).tolist())
        weekly = metrics.loc[metrics["aggregation_level"].astype(str).eq("weekly")].iloc[0]
        self.assertEqual(float(weekly["realised_adjusted_profit"]), 220.0)

    def test_notebook_payload_targets_saved_outputs_only(self) -> None:
        run_dir = self.tempdir / "fake_run"
        (run_dir / "notebook_inputs").mkdir(parents=True)
        (run_dir / "figures").mkdir(parents=True)
        payload = build_notebook_payload(run_dir)
        source = "".join("".join(cell.get("source", [])) for cell in payload["cells"])
        self.assertIn("RUN_DIR", source)
        self.assertIn("NOTEBOOK_INPUTS", source)
        self.assertNotIn("run_validation_cvar_expanded_sweep(", source)


if __name__ == "__main__":
    unittest.main()
