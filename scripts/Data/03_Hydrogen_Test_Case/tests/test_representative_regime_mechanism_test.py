from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
H2_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, H2_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hydrogen.representative_regime_mechanism_test import (
    _benchmark_comparisons,
    _economic_comparisons,
    _repeat_hourly_scenarios_to_qh,
    load_mechanism_config,
)


def test_mechanism_config_is_strictly_d_only_s10() -> None:
    config = load_mechanism_config()
    assert config["horizon_lead_days"] == [0]
    assert config["scenario_count"] == 10
    assert config["horizon_sweep"] is False
    assert config["scenario_count_sweep"] is False
    assert config["cvar_gamma"] == 0.0


def test_hourly_flat_repeat_creates_four_equal_quarters() -> None:
    hourly = pd.DataFrame(
        {
            "forecast_origin_utc": [pd.Timestamp("2026-05-17T06:00:00Z")],
            "delivery_start_utc": [pd.Timestamp("2026-05-17T22:00:00Z")],
            "scenario_id": ["S10_01"],
            "scenario_price_eur_per_mwh": [80.0],
        }
    )
    qh = _repeat_hourly_scenarios_to_qh(hourly)
    assert len(qh) == 4
    assert qh["scenario_price_eur_per_mwh"].eq(80.0).all()
    assert qh["delivery_start_utc"].diff().dropna().eq(pd.Timedelta(minutes=15)).all()


def test_economic_and_benchmark_differences_keep_declared_signs() -> None:
    rows = []
    values = {
        "A_hourly": {"stochastic_10": 100.0, "price_insensitive": 80.0, "true_pf": 120.0},
        "B_qh_flat": {"stochastic_10": 90.0, "price_insensitive": 80.0, "true_pf": 120.0},
        "C_qh_shape": {"stochastic_10": 95.0, "price_insensitive": 80.0, "true_pf": 120.0},
    }
    for arm, policies in values.items():
        for policy, profit in policies.items():
            rows.append(
                {
                    "case_id": "case",
                    "arm": arm,
                    "policy": policy,
                    "realised_adjusted_profit_ex_terminal_eur": profit,
                }
            )
    daily = pd.DataFrame(rows)
    economic = _economic_comparisons(daily).set_index("policy")
    assert economic.loc["stochastic_10", "delta_qh_market_profit_eur"] == -10.0
    assert economic.loc["stochastic_10", "delta_shape_profit_eur"] == 5.0
    benchmark = _benchmark_comparisons(daily).set_index("arm")
    assert benchmark.loc["A_hourly", "uplift_vs_price_insensitive_eur"] == 20.0
    assert benchmark.loc["A_hourly", "perfect_foresight_regret_eur"] == 20.0

