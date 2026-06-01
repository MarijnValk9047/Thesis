from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_standard_cvar_policy_test_report import build_notebook_payload  # noqa: E402
from hydrogen.selected_test_week_cvar_policy_eval import (  # noqa: E402
    run_selected_test_week_cvar_policy_eval,
)


class SelectedTestWeekCvarPolicyEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_e1_tests_"))
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
                    "selection_reason": "high_volatility",
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
        support_rows = []
        for date in pd.date_range("2024-12-09", periods=7, freq="D"):
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
            '  - label: test_high_volatility_week\n'
            '    start_local_date: "2024-12-09"\n'
            '    end_local_date: "2024-12-15"\n'
            '    notes: diagnostic_reporting\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_runner_rejects_wrong_gamma_grid_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires gamma grid exactly"):
            run_selected_test_week_cvar_policy_eval(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_id="test_high_volatility_week",
                artifact_ids=[],
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.10],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=True,
                run_slug="phase_e1_invalid",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_runner_rejects_wrong_alpha_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires alpha 0.95"):
            run_selected_test_week_cvar_policy_eval(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_id="test_high_volatility_week",
                artifact_ids=[],
                cvar_alpha=0.90,
                gamma_values=[0.0, 0.05, 0.25],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=True,
                run_slug="phase_e1_invalid_alpha",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_notebook_payload_targets_saved_outputs_only(self) -> None:
        run_dir = self.tempdir / "fake_run"
        (run_dir / "notebook_inputs").mkdir(parents=True)
        (run_dir / "figures").mkdir(parents=True)
        payload = build_notebook_payload(run_dir)
        source = "".join("".join(cell.get("source", [])) for cell in payload["cells"])
        self.assertIn("RUN_DIR =", source)
        self.assertIn("required_files", source)
        self.assertNotIn("run_selected_test_week_cvar_policy_eval(", source)


if __name__ == "__main__":
    unittest.main()
