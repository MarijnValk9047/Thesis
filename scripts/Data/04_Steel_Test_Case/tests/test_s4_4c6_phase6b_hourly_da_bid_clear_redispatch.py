from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from uuid import uuid4

import pandas as pd
import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STEEL_ROOT.parents[2]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    CONFIGURATIONS,
    ENERGY_TOLERANCE_MWH,
    GRID_CANONICAL_ID,
    POLICIES,
    STEEL_BID_GRID,
    Phase6BError,
    SteelActualPriceBundle,
    SteelClearingResult,
    SteelRedispatchResult,
    SteelRollingState,
    advance_steel_state,
    clear_hourly_da_bids,
    episode_planning_horizon_hours,
    expected_origin_utc,
    grid_sha256,
    load_hourly_actual_prices,
    load_hourly_oracle_prices,
    load_hourly_price_information,
    load_phase6b_config,
    prepare_physical_context,
    validate_scenario_probabilities,
    validate_bid_monotonicity,
)


CONFIG_PATH = STEEL_ROOT / "configs" / "steel_c6_phase6b_hourly_da_bid_clear_redispatch.yaml"


def test_phase6b_scope_and_grid_are_frozen() -> None:
    config = load_phase6b_config(CONFIG_PATH)
    phase = config["phase6b"]
    assert tuple(phase["policies"]) == POLICIES
    assert tuple(float(item) for item in phase["bid_grid_eur_per_mwh"]) == STEEL_BID_GRID
    assert phase["bid_grid_id"] == GRID_CANONICAL_ID
    assert phase["week_terminal_target_selection_policy"] == "price_insensitive_reference"
    assert phase["terminal_band_fraction"] == 0.01
    assert phase["terminal_inventory_horizon_policy"] == (
        "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    )
    assert len(grid_sha256()) == 64
    assert phase["forbidden_scope"] == {
        "qh": True,
        "cvar": True,
        "mfrr": True,
        "export": True,
        "ets": True,
        "product_revenue": True,
        "emergency_import": True,
        "imbalance_market": True,
    }


def test_frozen_april_fixture_has_complete_actual_free_s10_support() -> None:
    config = load_phase6b_config(CONFIG_PATH)
    bundle = load_hourly_price_information(
        config["phase6b"]["forecast_root"], date(2026, 4, 27), 10
    )
    assert bundle.forecast_origin_utc == expected_origin_utc(date(2026, 4, 27))
    assert len(bundle.timestamps_utc) == 120
    assert len(bundle.scenario_prices) == 10
    assert abs(sum(bundle.scenario_probabilities.values()) - 1.0) <= 1e-10
    assert set(bundle.scenario_source_blocks) == set(bundle.scenario_prices)
    assert not any("actual" in key or "error" in key for key in bundle.__dict__)
    oracle = load_hourly_oracle_prices(config["phase6b"]["forecast_root"], bundle)
    assert oracle.timestamps_utc == bundle.timestamps_utc
    assert len(oracle.prices) == 120


def test_phase5k_physics_and_cost_contract_are_reused() -> None:
    context = prepare_physical_context(load_phase6b_config(CONFIG_PATH))
    assert context.plan.planning_horizon_hours == 120
    assert context.plan.execution_block_hours == 24
    assert set(context.site_background_by_configuration) == set(CONFIGURATIONS)
    assert any(flow["flow_id"] == "C0_NG_GENERATOR" for flow in context.cost_flows)
    assert any(flow["price_id"] == "grid_electricity_flat_nl" for flow in context.cost_flows)


def test_campaign_endpoint_uses_frozen_complete_day_horizon_truncation() -> None:
    assert [
        episode_planning_horizon_hours(
            fixture_id="rolling_week", day_index=index, day_count=7
        )
        for index in range(7)
    ] == [120, 120, 120, 96, 72, 48, 24]
    assert episode_planning_horizon_hours(
        fixture_id="normal_day", day_index=0, day_count=1
    ) == 120


def test_clearing_uses_bid_price_greater_than_or_equal_to_actual() -> None:
    timestamp = pd.Timestamp("2026-04-26T22:00:00Z")
    rows = [
        {
            "policy": "H-S10",
            "configuration_id": CONFIGURATIONS[0],
            "target_timestamp_utc": timestamp.isoformat(),
            "bid_price_eur_per_mwh": -5.0,
            "incremental_bid_volume_mwh": 2.0,
        },
        {
            "policy": "H-S10",
            "configuration_id": CONFIGURATIONS[0],
            "target_timestamp_utc": timestamp.isoformat(),
            "bid_price_eur_per_mwh": 80.0,
            "incremental_bid_volume_mwh": 3.0,
        },
        {
            "policy": "H-S10",
            "configuration_id": CONFIGURATIONS[0],
            "target_timestamp_utc": timestamp.isoformat(),
            "bid_price_eur_per_mwh": 3000.0,
            "incremental_bid_volume_mwh": 4.0,
        },
    ]
    actuals = SteelActualPriceBundle(date(2026, 4, 27), (timestamp,), (80.0,))
    result = clear_hourly_da_bids(rows, actuals)
    assert result.hourly[0]["cleared_energy_mwh"] == 7.0
    assert result.settlement_cost_eur == 560.0
    assert validate_bid_monotonicity(rows, (-10.0, 80.0, 100.0))


@pytest.mark.parametrize("hours,day", [(23, "2026-03-29"), (24, "2026-04-27"), (25, "2026-10-25")])
def test_actual_loader_accepts_dst_day_shapes(
    hours: int, day: str
) -> None:
    fixture_root = (
        REPO_ROOT / "tmp" / "phase6b_dst_contract_fixtures_v2"
        / f"hours_{hours}_{uuid4().hex}"
    )
    fixture_root.mkdir(parents=True, exist_ok=True)
    local_day = pd.Timestamp(day, tz="Europe/Amsterdam")
    start = local_day.tz_convert("UTC")
    end = (local_day + pd.DateOffset(days=1)).tz_convert("UTC")
    timestamps = pd.date_range(start, end, inclusive="left", freq="h")
    assert len(timestamps) == hours
    rows = []
    for lead in (0, 1):
        for index, timestamp in enumerate(timestamps):
            rows.append({
                "granularity": "hourly",
                "forecast_origin_utc": start - pd.Timedelta(days=1),
                "target_timestamp_utc": timestamp,
                "lead_day": lead,
                "actual_price": 50.0 + index,
            })
    pd.DataFrame(rows).to_parquet(fixture_root / "evaluation_actuals.parquet", index=False)
    result = load_hourly_actual_prices(fixture_root, date.fromisoformat(day))
    assert len(result.timestamps_utc) == hours


def test_state_handoff_is_exact_and_rejects_episode_gap() -> None:
    timestamp = "2026-04-26T22:00:00+00:00"
    base = SteelRollingState("week", CONFIGURATIONS[0])
    clearing = SteelClearingResult("H-point", CONFIGURATIONS[0], date(2026, 4, 27), [], 0.0)
    result = SteelRedispatchResult(
        "H-point", CONFIGURATIONS[0], date(2026, 4, 27),
        [{"target_timestamp_utc": timestamp}],
        {"coke_store_initial_t": 10.0}, 100.0, 0.0, {},
        executed_route_progress_t={"C0_BOF_crude_steel_output_t": 120.0},
    )
    next_state = advance_steel_state(base, result)
    assert next_state.inventory_overrides == {"coke_store_initial_t": 10.0}
    assert next_state.cumulative_production_t == 100.0
    assert next_state.executed_hours == 1
    assert next_state.cumulative_route_progress_t == {
        "C0_BOF_crude_steel_output_t": 120.0
    }

    gap_result = SteelRedispatchResult(
        "H-point", CONFIGURATIONS[0], date(2026, 4, 29),
        [{"target_timestamp_utc": "2026-04-28T22:00:00+00:00"}],
        {"coke_store_initial_t": 10.0}, 1.0, 0.0, {},
    )
    with pytest.raises(Phase6BError, match="support gap"):
        advance_steel_state(next_state, gap_result)


def test_non_summing_probability_fixture_is_rejected() -> None:
    source = load_phase6b_config(CONFIG_PATH)["phase6b"]["forecast_root"]
    bundle = load_hourly_price_information(source, date(2026, 4, 27), 10)
    probabilities = dict(bundle.scenario_probabilities)
    probabilities[next(iter(probabilities))] += 0.1
    with pytest.raises(Phase6BError, match="sum to one"):
        validate_scenario_probabilities(probabilities)
