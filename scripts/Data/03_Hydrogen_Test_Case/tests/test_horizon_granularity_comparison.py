from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


CASE_ROOT = Path(__file__).resolve().parents[1]
if str(CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(CASE_ROOT))

from hydrogen.horizon_granularity_comparison import (
    _accepted_status,
    _perfect_foresight_path,
    _weighted_ev,
    build_comparison_tables,
    build_policy_scenarios,
    circular_moving_block_bootstrap,
)
from hydrogen.production_target import build_weekly_quota_deadline_plan, build_weekly_quota_deadlines
from hydrogen.rolling_horizon import RollingHydrogenState


class _HydrogenFixture:
    electrolyser_nominal_mw = 55.0
    h2_efficiency_kg_per_mwh = 18.0
    compressor_max_mw = 3.0
    compressor_specific_mwh_per_kg = 0.002


def test_partial_week_quota_is_prorated_and_not_carried_between_weeks() -> None:
    days = ["2026-04-06", "2026-04-07", "2026-04-13"]
    deadlines = build_weekly_quota_deadlines(
        episode_id="fixture", included_delivery_days=days, daily_target_kg=19_000.0
    )
    assert [item.required_quantity_kg for item in deadlines] == [38_000.0, 19_000.0]
    assert deadlines[0].due_date == "2026-04-07"
    assert deadlines[1].due_date == "2026-04-13"


def test_weekly_plan_uses_only_same_week_realised_credit() -> None:
    timestamps = pd.date_range("2026-04-12T22:00:00Z", periods=24, freq="h", tz="UTC")
    deadlines = build_weekly_quota_deadlines(
        episode_id="fixture", included_delivery_days=["2026-04-13"], daily_target_kg=19_000.0
    )
    plan = build_weekly_quota_deadline_plan(
        episode_id="fixture",
        included_delivery_days=["2026-04-13"],
        timestamps_utc=timestamps,
        realised_compression_by_week_kg={"week_20260406_20260412": 99_999.0},
        hydrogen=_HydrogenFixture(),
        daily_target_kg=19_000.0,
        delta_t_hours=1.0,
    )
    assert len(plan.constraints) == 1
    assert plan.constraints[0].week_id == deadlines[0].week_id
    assert plan.constraints[0].realised_before_horizon_kg == 0.0
    assert plan.constraints[0].minimum_horizon_compression_kg == 19_000.0


def test_weighted_ev_and_true_pf_keep_one_nonanticipative_path() -> None:
    origin = pd.Timestamp("2026-04-05T06:00:00Z")
    timestamp = pd.Timestamp("2026-04-05T22:00:00Z")
    scenarios = pd.DataFrame(
        {
            "forecast_origin_utc": [origin, origin],
            "delivery_start_utc": [timestamp, timestamp],
            "scenario_id": ["A", "B"],
            "scenario_probability": [0.25, 0.75],
            "scenario_price_eur_per_mwh": [20.0, 100.0],
        }
    )
    ev = _weighted_ev(scenarios)
    assert ev.loc[0, "scenario_price_eur_per_mwh"] == 80.0
    assert ev.loc[0, "scenario_probability"] == 1.0
    actual = pd.DataFrame(
        {
            "forecast_origin_utc": [origin],
            "delivery_start_utc": [timestamp],
            "actual_price_eur_per_mwh": [75.0],
        }
    )
    pf = _perfect_foresight_path(scenarios, actual)
    assert pf.loc[0, "scenario_id"] == "TRUE_PF"
    assert pf.loc[0, "scenario_price_eur_per_mwh"] == 75.0
    scenarios["actual_price_eur_per_mwh"] = 75.0
    optimisation, _ = build_policy_scenarios(
        policy="stochastic_30", scenario_30=scenarios, scenario_10=scenarios, actuals=actual
    )
    assert "actual_price_eur_per_mwh" not in optimisation.columns


def test_state_copy_is_independent_between_policies_and_episodes() -> None:
    state = RollingHydrogenState(
        episode_id="primary", storage_inventory_kg=5000.0, realised_compression_by_week_kg={"w": 10.0}
    )
    copied = state.copy()
    copied.realised_compression_by_week_kg["w"] = 20.0
    assert state.realised_compression_by_week_kg["w"] == 10.0


def test_moving_block_bootstrap_is_deterministic_and_paired() -> None:
    values = np.arange(1.0, 106.0)
    first = circular_moving_block_bootstrap(values, draws=250, block_length=7, seed=42)
    second = circular_moving_block_bootstrap(values, draws=250, block_length=7, seed=42)
    assert first == second
    assert first["mean"] == float(values.mean())
    assert first["ci_low"] < first["ci_high"]


def test_solver_acceptance_rejects_nonoptimal_text_and_excess_gap() -> None:
    assert _accepted_status("ok", "optimal", 0.001, 0.001)
    assert not _accepted_status("not optimal", "optimal", 0.0, 0.001)
    assert not _accepted_status("ok", "maxTimeLimit", 0.0, 0.001)
    assert not _accepted_status("ok", "optimal", 0.002, 0.001)


def test_dst_delivery_days_have_real_hour_and_quarter_counts() -> None:
    for delivery_day, hourly_count in (("2026-03-29", 23), ("2026-10-25", 25)):
        start = pd.Timestamp(delivery_day, tz="Europe/Amsterdam")
        end = start + pd.DateOffset(days=1)
        hourly = pd.date_range(start, end, freq="h", inclusive="left").tz_convert("UTC")
        quarter_hourly = pd.date_range(start, end, freq="15min", inclusive="left").tz_convert("UTC")
        assert len(hourly) == hourly_count
        assert len(quarter_hourly) == hourly_count * 4


def test_attribution_control_does_not_require_duplicated_benchmarks() -> None:
    policies = ["stochastic_30", "price_insensitive", "true_pf"]
    daily = pd.DataFrame(
        [
            {
                "episode_id": "primary",
                "configuration": "H-D4",
                "policy": policy,
                "delivery_day": "2026-04-06",
                "realised_adjusted_profit_ex_terminal_eur": value,
                "da_cost_eur": 1.0,
                "hydrogen_produced_kg": 19_000.0,
                "hydrogen_compressed_kg": 19_000.0,
                "shortfall_kg": 0.0,
                "emergency_import_mwh": 0.0,
                "emergency_import_cost_eur": 0.0,
                "high_price_energy_share": 0.1,
                "low_price_energy_share": 0.4,
                "wall_time_seconds": 1.0,
            }
            for policy, value in zip(policies, [12.0, 10.0, 15.0])
        ]
        + [
            {
                "episode_id": "primary",
                "configuration": "H-D4|D",
                "policy": "stochastic_30",
                "delivery_day": "2026-04-06",
                "realised_adjusted_profit_ex_terminal_eur": 11.0,
                "da_cost_eur": 1.0,
                "hydrogen_produced_kg": 19_000.0,
                "hydrogen_compressed_kg": 19_000.0,
                "shortfall_kg": 0.0,
                "emergency_import_mwh": 0.0,
                "emergency_import_cost_eur": 0.0,
                "high_price_energy_share": 0.1,
                "low_price_energy_share": 0.4,
                "wall_time_seconds": 1.0,
            }
        ]
    )
    metadata = daily[["episode_id", "configuration", "policy"]].drop_duplicates().assign(
        episode_terminal_inventory_correction_eur=0.0
    )
    aggregate, _ = build_comparison_tables(
        daily,
        metadata,
        {
            "draws": 10,
            "seed": 42,
            "primary_block_length_days": 7,
            "sensitivity_block_lengths_days": [3, 14],
        },
    )
    control = aggregate.loc[aggregate["configuration"].eq("H-D4|D")].iloc[0]
    assert np.isnan(control["uplift_vs_price_insensitive_eur"])
    assert np.isnan(control["oracle_regret_eur"])
    assert np.isnan(control["value_captured"])
