from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.selected_week_smoke import (  # noqa: E402
    _build_phase_c_validation_checks,
    load_and_validate_phase_c_week,
    run_selected_week_risk_neutral_smoke,
)
from hydrogen.selected_week_suite import SelectedWeekSuiteResult  # noqa: E402


class SelectedWeekRiskNeutralSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_c_smoke_tests_"))
        self.registry_path = self.tempdir / "selected_week_registry_common_support.csv"
        self.support_path = self.tempdir / "common_support_three_model_hourly.csv"
        self.selected_weeks_yaml = self.tempdir / "selected_weeks_common_support.yaml"

        registry = pd.DataFrame(
            [
                {
                    "week_id": "test_20241209_20241215",
                    "period_type": "test",
                    "week_label": "test_high_volatility_week",
                    "delivery_start_date": "2024-12-09",
                    "delivery_end_date": "2024-12-15",
                    "number_of_delivery_days": 7,
                    "selection_reason": "diagnostic smoke week",
                    "complete_for_lear_strict": True,
                    "complete_for_lear_fs3": True,
                    "complete_for_xgboost_fs3": True,
                    "complete_actual_prices": True,
                    "support_status": "common_complete_support_selected",
                    "methodological_use": "diagnostic_reporting",
                }
            ]
        )
        registry.to_csv(self.registry_path, index=False)

        support_days = pd.DataFrame(
            {
                "delivery_date": pd.date_range("2024-12-09", "2024-12-15", freq="D"),
                "period_type": ["test"] * 7,
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
        support_days.to_csv(self.support_path, index=False)
        self.selected_weeks_yaml.write_text(
            'selected_weeks:\n'
            '  - label: test_high_volatility_week\n'
            '    start_local_date: "2024-12-09"\n'
            '    end_local_date: "2024-12-15"\n'
            '    notes: diagnostic_reporting\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_selected_week_loading_succeeds_for_phase_c_target(self) -> None:
        week, support = load_and_validate_phase_c_week(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_id="test_high_volatility_week",
            selected_week_split="test",
        )
        self.assertEqual(str(week["week_label"]), "test_high_volatility_week")
        self.assertEqual(str(week["delivery_start_date"]), "2024-12-09")
        self.assertEqual(str(week["delivery_end_date"]), "2024-12-15")
        self.assertEqual(int(support.shape[0]), 7)

    def test_selected_week_loading_fails_when_support_day_is_incomplete(self) -> None:
        support = pd.read_csv(self.support_path)
        support.loc[3, "common_complete_support"] = False
        support.to_csv(self.support_path, index=False)
        with self.assertRaisesRegex(ValueError, "not exact common complete support"):
            load_and_validate_phase_c_week(
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
                week_id="test_high_volatility_week",
                selected_week_split="test",
            )

    def test_runner_rejects_non_risk_neutral_mode_before_any_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "risk_neutral only"):
            run_selected_week_risk_neutral_smoke(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_id="test_high_volatility_week",
                artifact_ids=[],
                run_slug="phase_c_invalid",
                risk_mode="cvar",
                include_price_insensitive_benchmark=True,
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_suite_level_validation_detects_energy_balance_failure(self) -> None:
        week, support = load_and_validate_phase_c_week(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_id="test_high_volatility_week",
            selected_week_split="test",
        )
        existing_checks = pd.DataFrame(
            columns=["check_name", "status", "severity", "details", "artifact_id", "model_label", "week_id", "week_label", "delivery_day", "forecast_origin_utc"]
        )
        daily_metrics = pd.DataFrame(
            [
                {
                    "artifact_id": "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
                    "model_label": "LEAR FS3 pruned candidate",
                    "scenario_probability_check": True,
                    "solver_status": "Optimal",
                    "delivery_day": "2024-12-09",
                }
            ]
        )
        weekly_metrics = pd.DataFrame(
            [
                {
                    "artifact_id": "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
                    "model_label": "LEAR FS3 pruned candidate",
                    "period_type": "test",
                }
            ]
        )
        actual_clearing = pd.DataFrame(
            [
                {
                    "granularity": "hourly",
                    "timestep_hours": 1.0,
                    "horizon": "D_only",
                }
            ]
        )
        actual_redispatch_timeseries = pd.DataFrame(
            [
                {
                    "artifact_id": "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
                    "model_label": "LEAR FS3 pruned candidate",
                    "delivery_day": "2024-12-09",
                    "used_energy_mwh": 10.0,
                    "unused_cleared_energy_mwh": 1.0,
                    "cleared_energy_mwh": 15.0,
                }
            ]
        )
        scenario_settlement_results = pd.DataFrame(
            [
                {
                    "risk_measure": "risk_neutral",
                    "cvar_gamma": 0.0,
                }
            ]
        )
        benchmark_metrics = pd.DataFrame(
            [
                {
                    "aggregation_level": "weekly",
                    "period_type": "test",
                }
            ]
        )
        suite_result = SelectedWeekSuiteResult(
            suite_dir=self.tempdir,
            selected_week_registry=pd.DataFrame([week.to_dict()]),
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            weekly_metrics_by_model=pd.DataFrame(),
            benchmark_comparison_daily=pd.DataFrame(),
            benchmark_comparison_weekly=pd.DataFrame(),
            validation_checks_all_runs=existing_checks,
            model_stats_daily=pd.DataFrame(),
            day_run_dirs=pd.DataFrame(),
            submitted_bids=pd.DataFrame(),
            scenario_clearing=pd.DataFrame(),
            actual_clearing=pd.DataFrame(),
            actual_clearing_by_hour=pd.DataFrame(),
            actual_redispatch_timeseries=pd.DataFrame(),
            scenario_settlement_results=pd.DataFrame(),
            actual_settlement_results=pd.DataFrame(),
            benchmark_comparison=pd.DataFrame(),
            scenario_fan_inputs=pd.DataFrame(),
            suite_runtime_profile=pd.DataFrame(),
            execution_audit=pd.DataFrame(),
            slice_audit=pd.DataFrame(),
            scenario_manifests=[],
            input_manifests=[],
        )
        checks = _build_phase_c_validation_checks(
            existing_checks=existing_checks,
            selected_week=week,
            support_days=support,
            artifact_ids=["hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate"],
            expected_gamma_values=[0.0],
            include_price_insensitive_benchmark=True,
            benchmark_scope="per_model",
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            actual_clearing=actual_clearing,
            actual_redispatch_timeseries=actual_redispatch_timeseries,
            scenario_settlement_results=scenario_settlement_results,
            benchmark_metrics=benchmark_metrics,
            suite_result=suite_result,
            requested_week_id="test_high_volatility_week",
        )
        status_by_check = checks.set_index("check_name")["status"].astype(str)
        self.assertEqual(status_by_check["used_cleared_energy_plus_unused_equals_cleared_weekly"], "fail")

    def test_suite_level_validation_uses_dynamic_expected_counts(self) -> None:
        week, support = load_and_validate_phase_c_week(
            week_registry_path=self.registry_path,
            support_csv_path=self.support_path,
            selected_weeks_yaml_path=self.selected_weeks_yaml,
            week_id="test_high_volatility_week",
            selected_week_split="test",
        )
        existing_checks = pd.DataFrame(
            columns=["check_name", "status", "severity", "details", "artifact_id", "model_label", "week_id", "week_label", "delivery_day", "forecast_origin_utc"]
        )
        artifact_ids = [
            "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
            "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support",
        ]
        support_days = support.copy()
        delivery_days = support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist()
        daily_metrics = pd.DataFrame(
            [
                {
                    "artifact_id": artifact_id,
                    "model_label": artifact_id,
                    "scenario_probability_check": True,
                    "solver_status": "Optimal",
                    "delivery_day": delivery_day,
                }
                for artifact_id in artifact_ids
                for delivery_day in delivery_days
            ]
        )
        weekly_metrics = pd.DataFrame(
            [
                {"artifact_id": artifact_id, "model_label": artifact_id, "period_type": "test"}
                for artifact_id in artifact_ids
            ]
        )
        actual_clearing = pd.DataFrame(
            [{"granularity": "hourly", "timestep_hours": 1.0, "horizon": "D_only"}]
        )
        actual_redispatch_timeseries = pd.DataFrame(
            [
                {
                    "artifact_id": artifact_id,
                    "model_label": artifact_id,
                    "delivery_day": delivery_day,
                    "used_energy_mwh": 10.0,
                    "unused_cleared_energy_mwh": 0.0,
                    "cleared_energy_mwh": 10.0,
                }
                for artifact_id in artifact_ids
                for delivery_day in delivery_days
            ]
        )
        scenario_settlement_results = pd.DataFrame(
            [{"risk_measure": "risk_neutral", "cvar_gamma": 0.0}]
        )
        benchmark_metrics = pd.DataFrame(
            [
                {
                    "aggregation_level": level,
                    "period_type": "test",
                    "artifact_id": artifact_id,
                }
                for level in ["daily", "weekly"]
                for artifact_id in artifact_ids
                for _ in (delivery_days if level == "daily" else [None])
            ]
        )
        suite_result = SelectedWeekSuiteResult(
            suite_dir=self.tempdir,
            selected_week_registry=pd.DataFrame([week.to_dict()]),
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            weekly_metrics_by_model=pd.DataFrame(),
            benchmark_comparison_daily=pd.DataFrame(),
            benchmark_comparison_weekly=pd.DataFrame(),
            validation_checks_all_runs=existing_checks,
            model_stats_daily=pd.DataFrame(),
            day_run_dirs=pd.DataFrame(),
            submitted_bids=pd.DataFrame(),
            scenario_clearing=pd.DataFrame(),
            actual_clearing=pd.DataFrame(),
            actual_clearing_by_hour=pd.DataFrame(),
            actual_redispatch_timeseries=pd.DataFrame(),
            scenario_settlement_results=pd.DataFrame(),
            actual_settlement_results=pd.DataFrame(),
            benchmark_comparison=pd.DataFrame(),
            scenario_fan_inputs=pd.DataFrame(),
            suite_runtime_profile=pd.DataFrame(),
            execution_audit=pd.DataFrame(),
            slice_audit=pd.DataFrame(),
            scenario_manifests=[],
            input_manifests=[],
        )
        checks = _build_phase_c_validation_checks(
            existing_checks=existing_checks,
            selected_week=week,
            support_days=support,
            artifact_ids=artifact_ids,
            expected_gamma_values=[0.0],
            include_price_insensitive_benchmark=True,
            benchmark_scope="per_model",
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            actual_clearing=actual_clearing,
            actual_redispatch_timeseries=actual_redispatch_timeseries,
            scenario_settlement_results=scenario_settlement_results,
            benchmark_metrics=benchmark_metrics,
            suite_result=suite_result,
            requested_week_id="test_high_volatility_week",
        )
        status_by_check = checks.set_index("check_name")["status"].astype(str)
        self.assertEqual(status_by_check["stochastic_milp_run_count_matches_expected_matrix"], "pass")
        self.assertEqual(status_by_check["benchmark_run_count_matches_configured_policy"], "pass")
        self.assertEqual(status_by_check["benchmark_artifact_support_matches_requested_models"], "pass")


if __name__ == "__main__":
    unittest.main()
