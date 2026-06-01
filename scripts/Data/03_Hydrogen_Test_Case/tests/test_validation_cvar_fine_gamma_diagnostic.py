from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_fine_gamma_lear_fs3_diagnostic_notebook import build_notebook_payload  # noqa: E402
from hydrogen.validation_cvar_fine_gamma_diagnostic import (  # noqa: E402
    DEFAULT_ARTIFACT_ID,
    _compute_bid_difference_by_gamma,
    _compute_tail_scenario_diagnostics,
    run_validation_cvar_fine_gamma_diagnostic,
)


class ValidationCvarFineGammaDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="phase_d3_tests_"))
        self.registry_path = self.tempdir / "selected_week_registry_common_support.csv"
        self.support_path = self.tempdir / "common_support_three_model_hourly.csv"
        self.selected_weeks_yaml = self.tempdir / "selected_weeks_common_support.yaml"
        registry = pd.DataFrame(
            [
                {
                    "week_id": "validation_20231016_20231022",
                    "period_type": "validation",
                    "week_label": "validation_tail_week",
                    "delivery_start_date": "2023-10-16",
                    "delivery_end_date": "2023-10-22",
                    "number_of_delivery_days": 7,
                    "selection_reason": "tail",
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
                    "week_label": "validation_stable_week",
                    "delivery_start_date": "2023-11-06",
                    "delivery_end_date": "2023-11-12",
                    "number_of_delivery_days": 7,
                    "selection_reason": "stable",
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
            ]
        )
        registry.to_csv(self.registry_path, index=False)
        support_rows = []
        for start in ["2023-10-16", "2023-11-06", "2024-06-10"]:
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
            '  - label: validation_tail_week\n'
            '    start_local_date: "2023-10-16"\n'
            '    end_local_date: "2023-10-22"\n'
            '    notes: cvar_selection\n'
            '  - label: validation_stable_week\n'
            '    start_local_date: "2023-11-06"\n'
            '    end_local_date: "2023-11-12"\n'
            '    notes: cvar_selection\n'
            '  - label: validation_high_volatility_week\n'
            '    start_local_date: "2024-06-10"\n'
            '    end_local_date: "2024-06-16"\n'
            '    notes: cvar_selection\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_runner_rejects_wrong_gamma_grid_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires gamma grid exactly"):
            run_validation_cvar_fine_gamma_diagnostic(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_ids=["validation_tail_week", "validation_stable_week", "validation_high_volatility_week"],
                artifact_id=DEFAULT_ARTIFACT_ID,
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.01],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=False,
                run_slug="phase_d3_invalid",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_runner_rejects_wrong_artifact_before_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires artifact"):
            run_validation_cvar_fine_gamma_diagnostic(
                config="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
                week_ids=["validation_tail_week", "validation_stable_week", "validation_high_volatility_week"],
                artifact_id="wrong_artifact",
                cvar_alpha=0.95,
                gamma_values=[0.0, 0.001, 0.0025, 0.005, 0.01, 0.015, 0.02, 0.025, 0.05],
                include_price_insensitive_benchmark=True,
                include_perfect_foresight_benchmark=False,
                run_slug="phase_d3_invalid_artifact",
                week_registry_path=self.registry_path,
                support_csv_path=self.support_path,
                selected_weeks_yaml_path=self.selected_weeks_yaml,
            )

    def test_bid_difference_detects_identical_and_changed_gamma(self) -> None:
        frame = pd.DataFrame(
            [
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "delivery_start_utc": "2023-10-15T22:00:00Z", "bid_block": 0, "bid_price_eur_per_mwh": 100.0, "bid_quantity_mw": 10.0},
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.001, "delivery_start_utc": "2023-10-15T22:00:00Z", "bid_block": 0, "bid_price_eur_per_mwh": 100.0, "bid_quantity_mw": 10.0},
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.005, "delivery_start_utc": "2023-10-15T22:00:00Z", "bid_block": 0, "bid_price_eur_per_mwh": 100.0, "bid_quantity_mw": 12.0},
            ]
        )
        diff = _compute_bid_difference_by_gamma(frame, gamma_values=[0.0, 0.001, 0.005], timestep_hours=1.0)
        row_001 = diff.loc[diff["cvar_gamma"].astype(float).eq(0.001)].iloc[0]
        row_005 = diff.loc[diff["cvar_gamma"].astype(float).eq(0.005)].iloc[0]
        self.assertTrue(bool(row_001["identical_to_gamma0_within_tolerance"]))
        self.assertAlmostEqual(float(row_005["total_abs_bid_quantity_difference_mwh_vs_gamma0"]), 2.0)

    def test_tail_scenario_diagnostics_detect_tail_set_change(self) -> None:
        frame = pd.DataFrame(
            [
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "scenario_id": "s1", "adjusted_profit_eur": 10.0, "scenario_probability": 0.5, "loss_minus_zeta_eur": -1.0},
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.0, "scenario_id": "s2", "adjusted_profit_eur": 5.0, "scenario_probability": 0.5, "loss_minus_zeta_eur": 0.0},
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.001, "scenario_id": "s1", "adjusted_profit_eur": 10.0, "scenario_probability": 0.5, "loss_minus_zeta_eur": 0.0},
                {"artifact_id": DEFAULT_ARTIFACT_ID, "model_label": "LEAR FS3 pruned candidate", "week_id": "w1", "week_label": "validation_tail_week", "regime_label": "tail", "delivery_day": "2023-10-16", "forecast_origin_utc": "2023-10-15T06:00:00Z", "cvar_alpha": 0.95, "cvar_gamma": 0.001, "scenario_id": "s2", "adjusted_profit_eur": 5.0, "scenario_probability": 0.5, "loss_minus_zeta_eur": 0.0},
            ]
        )
        diag = _compute_tail_scenario_diagnostics(frame, gamma_values=[0.0, 0.001])
        row = diag.loc[diag["cvar_gamma"].astype(float).eq(0.001)].iloc[0]
        self.assertTrue(bool(row["whether_tail_scenarios_change_vs_previous_gamma"]))

    def test_notebook_payload_targets_saved_outputs_only(self) -> None:
        run_dir = self.tempdir / "fake_run"
        (run_dir / "notebook_inputs").mkdir(parents=True)
        (run_dir / "figures").mkdir(parents=True)
        payload = build_notebook_payload(run_dir)
        source = "".join("".join(cell.get("source", [])) for cell in payload["cells"])
        self.assertIn("NOTEBOOK_INPUTS", source)
        self.assertNotIn("run_validation_cvar_fine_gamma_diagnostic(", source)


if __name__ == "__main__":
    unittest.main()
