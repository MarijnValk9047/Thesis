from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.common_support import run_common_support_audit  # noqa: E402


CONFIG_PATH = "scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml"
ARTIFACT_KEYS = [
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support",
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate",
]


class CommonSupportSelectedWeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_common_support_audit(
            config=CONFIG_PATH,
            artifact_keys=ARTIFACT_KEYS,
        )

    def test_exact_common_support_bounds_are_stable_for_current_artifacts(self) -> None:
        self.assertEqual(self.result.metadata["validation_support_start"], "2023-10-12")
        self.assertEqual(self.result.metadata["validation_support_end"], "2024-09-26")
        self.assertEqual(self.result.metadata["validation_support_day_count"], 188)
        self.assertEqual(self.result.metadata["test_support_start"], "2024-10-02")
        self.assertEqual(self.result.metadata["test_support_end"], "2025-09-17")
        self.assertEqual(self.result.metadata["test_support_day_count"], 177)

    def test_candidate_week_counts_match_exact_common_support(self) -> None:
        self.assertEqual(self.result.metadata["eligible_validation_weeks"], 6)
        self.assertEqual(self.result.metadata["eligible_test_weeks"], 9)

    def test_selected_validation_weeks_are_complete_and_inside_validation_support(self) -> None:
        selected = self.result.selected_weeks.loc[self.result.selected_weeks["period_type"] == "validation"].copy()
        support = self.result.common_support_days.set_index("delivery_date_str")
        for row in selected.to_dict(orient="records"):
            self.assertEqual(int(row["number_of_delivery_days"]), 7)
            week_days = pd.date_range(row["delivery_start_date"], row["delivery_end_date"], freq="D").strftime("%Y-%m-%d")
            self.assertEqual(len(week_days), 7)
            period_types = support.loc[list(week_days), "period_type"]
            self.assertTrue(period_types.eq("validation").all())
            self.assertTrue(support.loc[list(week_days), "common_complete_support"].all())
            self.assertTrue(support.loc[list(week_days), "complete_actual_prices"].all())

    def test_selected_test_weeks_are_complete_and_inside_test_support(self) -> None:
        selected = self.result.selected_weeks.loc[self.result.selected_weeks["period_type"] == "test"].copy()
        support = self.result.common_support_days.set_index("delivery_date_str")
        for row in selected.to_dict(orient="records"):
            self.assertEqual(int(row["number_of_delivery_days"]), 7)
            week_days = pd.date_range(row["delivery_start_date"], row["delivery_end_date"], freq="D").strftime("%Y-%m-%d")
            self.assertEqual(len(week_days), 7)
            period_types = support.loc[list(week_days), "period_type"]
            self.assertTrue(period_types.eq("test").all())
            self.assertTrue(support.loc[list(week_days), "common_complete_support"].all())
            self.assertTrue(support.loc[list(week_days), "complete_actual_prices"].all())

    def test_selected_weeks_are_distinct_and_match_expected_labels(self) -> None:
        selected = self.result.selected_weeks.copy()
        self.assertEqual(int(selected["week_id"].nunique()), int(selected.shape[0]))
        self.assertEqual(
            set(selected["week_label"].astype(str)),
            {
                "validation_high_price_week",
                "validation_high_volatility_week",
                "validation_typical_summer_week",
                "validation_winter_proxy_week",
                "test_high_price_week",
                "test_high_volatility_week",
                "test_typical_summer_week",
                "test_typical_winter_week",
            },
        )

    def test_probability_checks_pass_for_selected_weeks(self) -> None:
        checks = self.result.selected_week_checks.copy()
        failing = checks.loc[checks["status"] != "pass"]
        self.assertTrue(failing.empty, msg=failing.to_string(index=False))


if __name__ == "__main__":
    unittest.main()
