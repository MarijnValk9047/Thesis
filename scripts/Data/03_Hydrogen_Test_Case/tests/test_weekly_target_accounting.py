from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.weekly_hard_band_target import (  # noqa: E402
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON,
    build_included_day_prorated_weekly_accounting,
    build_weekly_hard_band_settings,
    compute_weekly_target_day_bounds_for_variant,
)


class WeeklyTargetAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.daily_target_kg = 100.0
        self.band_on_settings = build_weekly_hard_band_settings(
            daily_target_kg=self.daily_target_kg,
            daily_min_fraction=0.8,
            daily_max_fraction=1.2,
        )
        self.band_off_settings = build_weekly_hard_band_settings(
            daily_target_kg=self.daily_target_kg,
            daily_min_fraction=0.0,
            daily_max_fraction=2.5,
        )

    def test_complete_week_uses_full_target(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=[
                "2025-01-06",
                "2025-01-07",
                "2025-01-08",
                "2025-01-09",
                "2025-01-10",
                "2025-01-11",
                "2025-01-12",
            ],
            daily_target_kg=self.daily_target_kg,
        )
        self.assertEqual(int(accounting["included_days_in_week"].iloc[0]), 7)
        self.assertTrue((accounting["weekly_target_kg"] == 700.0).all())
        self.assertFalse(accounting["is_boundary_week"].any())

    def test_final_two_day_week_is_prorated(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-09-29", "2025-09-30"],
            daily_target_kg=self.daily_target_kg,
        )
        self.assertEqual(int(accounting["included_days_in_week"].iloc[0]), 2)
        self.assertTrue((accounting["weekly_target_kg"] == 200.0).all())
        self.assertTrue(accounting["is_boundary_week"].all())

    def test_five_day_selected_period_is_prorated(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-02-03", "2025-02-04", "2025-02-05", "2025-02-06", "2025-02-07"],
            daily_target_kg=self.daily_target_kg,
        )
        self.assertEqual(int(accounting["included_days_in_week"].iloc[0]), 5)
        self.assertTrue((accounting["weekly_target_kg"] == 500.0).all())

    def test_midweek_to_midweek_two_week_period_prorates_boundary_weeks(self) -> None:
        included_days = [day.strftime("%Y-%m-%d") for day in pd.date_range("2025-01-08", "2025-01-21", freq="D")]
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=included_days,
            daily_target_kg=self.daily_target_kg,
        )
        summary = accounting.groupby("accounting_week_id", as_index=False).agg(
            included_days_in_week=("included_days_in_week", "first"),
            weekly_target_kg=("weekly_target_kg", "first"),
            is_boundary_week=("is_boundary_week", "first"),
        )
        self.assertEqual(summary["included_days_in_week"].tolist(), [5, 7, 2])
        self.assertEqual(summary["weekly_target_kg"].tolist(), [500.0, 700.0, 200.0])
        self.assertEqual(summary["is_boundary_week"].tolist(), [True, False, True])

    def test_dst_exclusions_are_not_counted_and_are_logged(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-03-24", "2025-03-25", "2025-03-26", "2025-03-27", "2025-03-28", "2025-03-29"],
            daily_target_kg=self.daily_target_kg,
            excluded_day_reasons={"2025-03-30": "dst_excluded"},
        )
        self.assertEqual(int(accounting["included_days_in_week"].iloc[0]), 6)
        self.assertTrue((accounting["weekly_target_kg"] == 600.0).all())
        excluded = accounting["excluded_days_in_calendar_week"].iloc[0]
        reasons = accounting["exclusion_reason"].iloc[0]
        self.assertIn("2025-03-30", excluded)
        self.assertIn("2025-03-30:dst_excluded", reasons)

    def test_non_contiguous_selected_periods_prorate_per_week(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-01-06", "2025-01-07", "2025-01-16", "2025-01-17"],
            daily_target_kg=self.daily_target_kg,
        )
        summary = accounting.groupby("accounting_week_id", as_index=False).agg(
            included_days_in_week=("included_days_in_week", "first"),
            weekly_target_kg=("weekly_target_kg", "first"),
        )
        self.assertEqual(summary["included_days_in_week"].tolist(), [2, 2])
        self.assertEqual(summary["weekly_target_kg"].tolist(), [200.0, 200.0])

    def test_band_off_final_included_day_forces_remaining_target(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-09-29", "2025-09-30"],
            daily_target_kg=self.daily_target_kg,
        )
        final_day = accounting.loc[accounting["delivery_day"] == "2025-09-30"].iloc[0]
        bounds = compute_weekly_target_day_bounds_for_variant(
            settings=self.band_off_settings,
            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            cumulative_realised_h2_kg_before_today=70.0,
            physical_daily_max_kg=250.0,
            accounting_day=final_day,
        )
        self.assertTrue(bounds.tracker_feasible)
        self.assertEqual(bounds.remaining_target_before_today_kg, 130.0)
        self.assertEqual(bounds.daily_lower_bound_kg, 130.0)
        self.assertEqual(bounds.daily_upper_bound_kg, 130.0)

    def test_band_off_final_included_day_clamps_to_zero_when_target_already_met(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-09-29", "2025-09-30"],
            daily_target_kg=self.daily_target_kg,
        )
        final_day = accounting.loc[accounting["delivery_day"] == "2025-09-30"].iloc[0]
        bounds = compute_weekly_target_day_bounds_for_variant(
            settings=self.band_off_settings,
            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
            cumulative_realised_h2_kg_before_today=220.0,
            physical_daily_max_kg=250.0,
            accounting_day=final_day,
        )
        self.assertTrue(bounds.tracker_feasible)
        self.assertEqual(bounds.remaining_target_before_today_kg, -20.0)
        self.assertEqual(bounds.daily_lower_bound_kg, 0.0)
        self.assertEqual(bounds.daily_upper_bound_kg, 0.0)

    def test_band_on_reports_infeasibility_explicitly_when_remaining_target_exceeds_band(self) -> None:
        accounting = build_included_day_prorated_weekly_accounting(
            included_delivery_days=["2025-09-29", "2025-09-30"],
            daily_target_kg=self.daily_target_kg,
        )
        final_day = accounting.loc[accounting["delivery_day"] == "2025-09-30"].iloc[0]
        bounds = compute_weekly_target_day_bounds_for_variant(
            settings=self.band_on_settings,
            production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON,
            cumulative_realised_h2_kg_before_today=0.0,
            accounting_day=final_day,
            physical_daily_max_kg=250.0,
        )
        self.assertFalse(bounds.tracker_feasible)
        self.assertEqual(bounds.daily_lower_bound_kg, 200.0)
        self.assertEqual(bounds.daily_upper_bound_kg, 120.0)


if __name__ == "__main__":
    unittest.main()
