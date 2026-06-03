from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402
from hydrogen.redispatch import solve_actual_redispatch_from_cleared_energy  # noqa: E402


CONFIG_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml")
PHASE2_RUN = Path("scripts/Data/03_Hydrogen_Test_Case/runs/20260515_131723_hydrogen_phase2_schedule_to_bid_bridge")


def _config():
    return load_hydrogen_config(CONFIG_PATH)


def _toy_profile(cleared_energy: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "delivery_start_utc": [
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "2025-01-01T02:00:00Z",
            ],
            "cleared_energy_mwh": cleared_energy,
            "actual_price_eur_per_mwh": [100.0, 110.0, 120.0],
            "timestep_hours": [1.0, 1.0, 1.0],
            "run_id": ["toy"] * 3,
            "strategy": ["toy_case"] * 3,
            "source_strategy": ["toy_case"] * 3,
            "bridge_strategy": ["toy_case"] * 3,
            "granularity": ["hourly"] * 3,
            "horizon": ["D_only"] * 3,
            "forecast_origin_utc": ["2024-12-31T07:00:00Z"] * 3,
        }
    )


class RedispatchTests(unittest.TestCase):
    def test_zero_cleared_energy_forces_zero_use(self) -> None:
        result = solve_actual_redispatch_from_cleared_energy(_toy_profile([0.0, 0.0, 0.0]), config=_config())
        self.assertTrue((result.timeseries["used_energy_mwh"] == 0.0).all())
        self.assertTrue((result.timeseries["unused_cleared_energy_mwh"] == 0.0).all())
        self.assertGreater(float(result.summary["shortfall_kg"].iloc[0]), 0.0)
        self.assertTrue((result.validation_checks["status"] != "fail").all())

    def test_scarce_cleared_energy_keeps_use_within_procurement_and_causes_shortfall(self) -> None:
        result = solve_actual_redispatch_from_cleared_energy(_toy_profile([10.0, 10.0, 10.0]), config=_config())
        self.assertTrue((result.timeseries["used_energy_mwh"] <= result.timeseries["cleared_energy_mwh"] + 1e-6).all())
        self.assertGreater(float(result.summary["shortfall_kg"].iloc[0]), 0.0)
        self.assertLessEqual(float(result.summary["storage_min_kg"].iloc[0]), _config().hydrogen_system.storage_initial_kg)

    def test_abundant_cleared_energy_creates_unused_energy_when_plant_cannot_use_all(self) -> None:
        result = solve_actual_redispatch_from_cleared_energy(
            _toy_profile([80.0, 80.0, 80.0]),
            config=_config(),
            target_hydrogen_kg=1000.0,
        )
        self.assertGreater(float(result.summary["unused_cleared_energy_mwh"].iloc[0]), 0.0)
        self.assertTrue((result.timeseries["unused_cleared_energy_mwh"] >= -1e-9).all())
        self.assertGreater(float(result.summary["hydrogen_above_target_kg"].iloc[0]), 0.0)
        self.assertLessEqual(float(result.summary["target_fulfilment_ratio_capped_for_reliability"].iloc[0]), 1.0)
        self.assertGreater(float(result.summary["production_to_target_ratio_uncapped"].iloc[0]), 1.0)
        self.assertTrue((result.timeseries["P_el_mw"] >= _config().hydrogen_system.electrolyser_nominal_mw - 1e-6).all())
        self.assertIn(
            "electrolyser",
            str(result.summary["unused_energy_physical_reason"].iloc[0]),
        )

    def test_redispatch_objective_excludes_sunk_settlement_cost(self) -> None:
        result = solve_actual_redispatch_from_cleared_energy(_toy_profile([10.0, 10.0, 10.0]), config=_config())
        summary = result.summary.iloc[0]
        recomputed = (
            float(summary["hydrogen_revenue_eur"])
            - float(summary["unused_energy_penalty_eur"])
            - float(summary["shortfall_penalty_eur"])
            + float(summary["terminal_inventory_correction_eur"])
        )
        self.assertAlmostEqual(float(summary["objective_value"]), recomputed, places=4)
        self.assertAlmostEqual(
            float(summary["realised_adjusted_profit_eur"]),
            recomputed - float(summary["realised_DA_settlement_cost_eur"]),
            places=4,
        )

    def test_badarinath_style_run_warns_when_unused_energy_penalty_is_zero(self) -> None:
        zero_penalty_config = replace(
            _config(),
            economics=replace(_config().economics, unused_energy_penalty_eur_per_mwh=0.0),
        )
        profile = _toy_profile([10.0, 10.0, 10.0])
        profile["bridge_strategy"] = "price_insensitive_plan_first_market_cap"
        result = solve_actual_redispatch_from_cleared_energy(profile, config=zero_penalty_config)
        warning_row = result.validation_checks.loc[
            result.validation_checks["check_name"] == "badarinath_unused_energy_penalty_nonzero"
        ]
        self.assertFalse(warning_row.empty)
        self.assertEqual(str(warning_row.iloc[0]["status"]), "warn")

    def test_phase2_bridge_high_price_profile_can_be_redispatched(self) -> None:
        bridge_path = PHASE2_RUN / "bridge_clearing_by_hour.parquet"
        if not bridge_path.exists():
            self.skipTest(f"Phase 2 bridge file not found: {bridge_path}")
        bridge = pd.read_parquet(bridge_path)
        profile = bridge[
            (bridge["source_strategy"] == "stochastic_risk_neutral")
            & (bridge["bridge_strategy"] == "high_price_bid")
        ].copy()
        profile["timestep_hours"] = 1.0
        result = solve_actual_redispatch_from_cleared_energy(profile, config=_config())
        self.assertFalse(result.summary.empty)
        self.assertEqual(result.summary["solver_status"].iloc[0], "Optimal")
        recomputed = float((result.timeseries["actual_price_eur_per_mwh"] * result.timeseries["cleared_energy_mwh"]).sum())
        self.assertAlmostEqual(float(result.summary["realised_DA_settlement_cost_eur"].iloc[0]), recomputed, places=4)
        self.assertLessEqual(float(result.summary["target_fulfilment_ratio_capped_for_reliability"].iloc[0]), 1.0)


if __name__ == "__main__":
    unittest.main()
