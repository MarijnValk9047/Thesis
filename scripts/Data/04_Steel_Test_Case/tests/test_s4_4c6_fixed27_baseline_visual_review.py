from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_fixed27_baseline_visual_review import (  # noqa: E402
    ALLOWED_REVIEW_STATUSES,
    _market_grid_import_identity_residual,
    _synthetic_mirror_checks,
    build_abc_cost_summary,
    load_visual_review_config,
    preflight_fixed27_visual_review,
)


def _solver(case_id: str, lower: float, upper: float) -> dict[str, object]:
    certificate = {
        "economic_optimality_class": "epsilon_optimal",
        "economic_objective_lower_bound_eur": lower,
        "economic_objective_upper_bound_eur": upper,
        "economic_absolute_objective_band_eur": upper - lower,
        "economic_certified_relative_gap": (upper - lower) / upper,
    }
    return {
        "case_id": case_id,
        "planning": certificate,
        "redispatch": certificate,
    }


def test_visual_review_config_is_fixed27_donly_s10() -> None:
    config = load_visual_review_config()
    fixed = config["fixed_contract"]
    assert fixed["daily_eaf_heat_starts"] == 27
    assert fixed["daily_eaf_heat_taps"] == 27
    assert fixed["daily_eaf_liquid_steel_t"] == 8775.0
    assert fixed["scenario_count"] == 10
    assert fixed["economic_horizon_hours"] == 24
    assert fixed["variable_daily_heat_counts"] is False
    assert fixed["full_four_week_matrix_authorized"] is False


def test_preflight_reuses_pass_sources_without_interval_dispatch() -> None:
    result = preflight_fixed27_visual_review()
    assert result["decision"] == "PASS"
    assert result["accepted_source_count"] == 7
    assert result["sources_with_interval_dispatch"] == 0
    assert result["diagnostic_rerun_required"] is True
    assert result["final_test_periods_read_or_solved"] is False


def test_synthetic_mirror_requires_one_shifted_heat_and_equal_total() -> None:
    rows: list[dict[str, object]] = []
    starts_s1 = np.zeros(96)
    starts_s2 = np.zeros(96)
    starts_s1[:81:3] = 1.0
    starts_s2[15:96:3] = 1.0
    for case_id, starts, reverse in (
        ("S1_C1_responsive", starts_s1, False),
        ("S2_C1_responsive", starts_s2, True),
    ):
        for interval in range(96):
            rows.append(
                {
                    "case_id": case_id,
                    "physical_interval_index": interval,
                    "eaf_heat_start": starts[interval],
                    "eaf_liquid_steel_output_t": 325.0 if starts[interval] else 0.0,
                    "realised_price_eur_per_mwh": (
                        float(95 - interval) if reverse else float(interval)
                    ),
                }
            )
    checks = _synthetic_mirror_checks(pd.DataFrame(rows))
    assert all(row["status"] == "pass" for row in checks)


def test_hourly_import_identity_is_reconstructed_on_market_grid() -> None:
    physical = [10.0, 20.0, 30.0, 40.0, 12.0, 22.0, 32.0, 42.0]
    dispatch = pd.DataFrame(
        {
            "market_interval_index": [0] * 4 + [1] * 4,
            "redispatched_net_grid_import_mwh": physical,
            "cleared_e_program_allocated_mwh": [25.0] * 4 + [27.0] * 4,
            "net_imbalance_mwh": [0.0] * 8,
        }
    )
    assert _market_grid_import_identity_residual(dispatch) <= 1e-12


def test_abc_cost_summary_uses_frozen_savings_sign_and_bounds() -> None:
    cases = [
        ("a", "A_hourly", 100.0),
        ("b", "B_qh_flat", 90.0),
        ("c", "C_qh_shape", 85.0),
    ]
    results = pd.DataFrame(
        [
            {
                "case_id": case_id,
                "profile_id": "high_volatility",
                "configuration": "C1",
                "policy": "responsive",
                "arm": arm,
                "realised_total_represented_cost_eur": cost,
                "expected_objective_eur": cost + 1.0,
            }
            for case_id, arm, cost in cases
        ]
    )
    solvers = [
        _solver(case_id, cost, cost + 2.0) for case_id, _, cost in cases
    ]
    summary = build_abc_cost_summary(results, solvers)
    assert summary["delta_qh_market_eur"].iloc[0] == 10.0
    assert summary["delta_shape_eur"].iloc[0] == 5.0
    assert summary["delta_total_eur"].iloc[0] == 15.0
    assert summary.set_index("arm").loc[
        "B_qh_flat", "expected_lower_bound_eur"
    ] == 90.0


def test_review_status_vocabulary_is_closed() -> None:
    assert ALLOWED_REVIEW_STATUSES == {
        "PASS",
        "PLAUSIBLE_BUT_NOT_PROVEN",
        "NOT_APPLICABLE",
        "FAIL",
    }
