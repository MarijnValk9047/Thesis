from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from uuid import uuid4

import pandas as pd
import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    _build_physical_model,
    _read_gzip_json,
    _scale_interval_rate_fields,
    _write_gzip_json_atomic,
    load_hourly_price_information,
)
from steel.s4_4c6_phase6c_qh_da_bid_clear_redispatch import (
    CONFIGURATIONS,
    QH_GRID_CANONICAL_ID,
    QH_MODEL_ID,
    QH_POLICIES,
    Phase6BError,
    SteelActualPriceBundle,
    SteelRedispatchResult,
    SteelRollingState,
    advance_steel_state,
    load_phase6c_config,
    load_qh_actual_prices,
    load_qh_oracle_prices,
    load_qh_price_information,
    prepare_physical_context,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    ModelTimeGrid,
    S44CModelBuilderError,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c0_model,
    _build_c1_inputs,
    _load_tables,
    scale_c0_inputs_to_time_grid,
    scale_c1_inputs_to_time_grid,
)


CONFIG_PATH = STEEL_ROOT / "configs" / "steel_c6_phase6c_qh_da_bid_clear_redispatch.yaml"


def test_phase6c_scope_time_grid_and_hourly_reference_are_frozen() -> None:
    config = load_phase6c_config(CONFIG_PATH)
    phase = config["phase6c"]
    assert phase["model_id"] == QH_MODEL_ID
    assert tuple(phase["policies"]) == QH_POLICIES
    assert phase["bid_grid_id"] == QH_GRID_CANONICAL_ID
    assert phase["time_step_hours"] == 0.25
    context = prepare_physical_context(config)
    assert context.time_grid.horizon_hours == 120
    assert context.time_grid.horizon_steps == 480
    assert context.time_grid.execution_steps == 96
    assert context.grid_id == QH_GRID_CANONICAL_ID
    assert set(context.terminal_inventory_band) == set(CONFIGURATIONS)


def test_qh_frozen_origin_has_complete_actual_free_coupled_s10_support() -> None:
    phase = load_phase6c_config(CONFIG_PATH)["phase6c"]
    delivery_day = date(2026, 4, 27)
    qh = load_qh_price_information(phase["forecast_root"], delivery_day, 10)
    hourly = load_hourly_price_information(phase["forecast_root"], delivery_day, 10)
    assert len(qh.timestamps_utc) == 480
    assert len(qh.scenario_prices) == 10
    assert qh.model_id == QH_MODEL_ID
    assert not any("actual" in key or "error" in key for key in qh.__dict__)
    assert qh.scenario_probabilities == hourly.scenario_probabilities
    assert qh.scenario_source_blocks == hourly.scenario_source_blocks
    qh_index = pd.DatetimeIndex(qh.timestamps_utc)
    point_means = pd.Series(qh.point_prices, index=qh_index).groupby(qh_index.floor("h")).mean()
    hourly_point = pd.Series(hourly.point_prices, index=pd.DatetimeIndex(hourly.timestamps_utc))
    assert (point_means - hourly_point).abs().max() <= 1e-9
    for scenario_id, prices in qh.scenario_prices.items():
        means = pd.Series(prices, index=qh_index).groupby(qh_index.floor("h")).mean()
        anchor = pd.Series(
            hourly.scenario_prices[scenario_id],
            index=pd.DatetimeIndex(hourly.timestamps_utc),
        )
        assert (means - anchor).abs().max() <= 1e-9
    oracle = load_qh_oracle_prices(phase["forecast_root"], qh)
    assert oracle.timestamps_utc == qh.timestamps_utc


def test_interval_quantity_scaling_and_ramp_contract() -> None:
    tables = _load_tables(S44B_INPUT_DIR)
    grid = ModelTimeGrid(horizon_hours=120, execution_hours=24, time_step_hours=0.25)
    c0_hourly = _build_c0_inputs(tables, horizon_hours_override=120)
    c0_qh = scale_c0_inputs_to_time_grid(c0_hourly, grid)
    assert c0_qh.horizon_hours == 480
    for process, hourly_bounds in c0_hourly.process_limits.items():
        assert c0_qh.process_limits[process] == pytest.approx(
            tuple(value * 0.25 for value in hourly_bounds)
        )
        assert 4.0 * c0_qh.process_limits[process][1] == pytest.approx(hourly_bounds[1])
    assert 4.0 * c0_qh.boiler_wag_cap_mwh_h == pytest.approx(
        c0_hourly.boiler_wag_cap_mwh_h
    )

    c1_hourly = _build_c1_inputs(
        tables, horizon_hours_override=120, include_retained_bf_bof=True
    )
    c1_qh = scale_c1_inputs_to_time_grid(c1_hourly, grid)
    assert c1_qh.horizon_hours == 480
    assert c1_qh.drp_capacity_t_pellets_h == pytest.approx(
        0.25 * c1_hourly.drp_capacity_t_pellets_h
    )
    assert c1_qh.drp_ramp_t_pellets_h == pytest.approx(
        c1_hourly.drp_ramp_t_pellets_h * 0.25**2
    )
    nested = _scale_interval_rate_fields(
        {
            "electricity_mwh_h": 40.0,
            "steam_t_h": 12.0,
            "co2_t_h": 8.0,
            "annual_total_t": 99.0,
        },
        0.25,
    )
    assert nested == {
        "electricity_mwh_h": 10.0,
        "steam_t_h": 3.0,
        "co2_t_h": 2.0,
        "annual_total_t": 99.0,
    }


def test_qh_builder_uses_96_step_days_and_rejects_fixed_hour_calendar() -> None:
    context = prepare_physical_context(load_phase6c_config(CONFIG_PATH))
    state = SteelRollingState("qh_builder", CONFIGURATIONS[0])
    model = _build_physical_model(
        context,
        CONFIGURATIONS[0],
        state,
        terminal_day=False,
        planning_horizon_hours=24,
    )
    assert len(model.TIME) == 96
    assert model.time_step_hours == 0.25
    assert model.physical_horizon_hours == 24.0
    assert model.hsm_source_mix_block_hours == 96
    assert model.rolling_production_progress_execution_hours == 96
    assert len(model.COMMITMENT_DAY) == 1

    hourly = _build_c0_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=24)
    qh = scale_c0_inputs_to_time_grid(
        hourly, ModelTimeGrid(24, 24, 0.25)
    )
    with pytest.raises(S44CModelBuilderError, match="fixed-hour"):
        _build_c0_model(qh, time_step_hours=0.25, fix_binary_schedule=True)


@pytest.mark.parametrize(
    "intervals,day", [(92, "2026-03-29"), (96, "2026-04-27"), (100, "2026-10-25")]
)
def test_qh_actual_loader_accepts_dst_day_shapes(
    intervals: int, day: str
) -> None:
    fixture_root = (
        STEEL_ROOT.parents[2] / "tmp" / "phase6c_dst_contract_fixtures"
        / f"intervals_{intervals}_{uuid4().hex}"
    )
    fixture_root.mkdir(parents=True, exist_ok=True)
    local_day = pd.Timestamp(day, tz="Europe/Amsterdam")
    start = local_day.tz_convert("UTC")
    end = (local_day + pd.DateOffset(days=1)).tz_convert("UTC")
    timestamps = pd.date_range(start, end, inclusive="left", freq="15min")
    assert len(timestamps) == intervals
    rows = [
        {
            "granularity": "quarterhour",
            "forecast_origin_utc": start - pd.Timedelta(days=1),
            "target_timestamp_utc": timestamp,
            "lead_day": lead,
            "actual_price": 50.0 + index,
        }
        for lead in (0, 1)
        for index, timestamp in enumerate(timestamps)
    ]
    pd.DataFrame(rows).to_parquet(fixture_root / "evaluation_actuals.parquet", index=False)
    result = load_qh_actual_prices(fixture_root, date.fromisoformat(day))
    assert len(result.timestamps_utc) == intervals


def test_qh_state_handoff_advances_24_hours_and_96_intervals() -> None:
    timestamps = pd.date_range("2026-04-26T22:00:00Z", periods=96, freq="15min")
    base = SteelRollingState("week", CONFIGURATIONS[0])
    redispatch = SteelRedispatchResult(
        policy="QH-point",
        configuration_id=CONFIGURATIONS[0],
        delivery_day=date(2026, 4, 27),
        hourly=[{"target_timestamp_utc": timestamp.isoformat()} for timestamp in timestamps],
        next_inventory_overrides={"coke_store_initial_t": 10.0},
        produced_t=100.0,
        other_represented_cost_eur=0.0,
        solver={},
        time_step_hours=0.25,
    )
    state = advance_steel_state(base, redispatch)
    assert state.executed_hours == 24
    assert state.executed_intervals == 96
    assert state.last_executed_timestamp_utc == "2026-04-27T21:45:00+00:00"

    gap = SteelRedispatchResult(
        policy="QH-point",
        configuration_id=CONFIGURATIONS[0],
        delivery_day=date(2026, 4, 28),
        hourly=[{"target_timestamp_utc": "2026-04-27T22:15:00+00:00"}],
        next_inventory_overrides={},
        produced_t=0.0,
        other_represented_cost_eur=0.0,
        solver={},
        time_step_hours=0.25,
    )
    with pytest.raises(Phase6BError, match="support gap"):
        advance_steel_state(state, gap)


def test_qh_checkpoint_is_atomic_compressed_json() -> None:
    root = (
        STEEL_ROOT.parents[2] / "tmp" / "phase6c_checkpoint_contract_fixtures"
        / uuid4().hex
    )
    target = root / "c0__qh_point.json.gz"
    payload = {"fingerprint_sha256": "a" * 64, "trajectory": {"states": [1, 2, 3]}}
    _write_gzip_json_atomic(target, payload)
    assert target.exists()
    assert not target.with_name(f".{target.name}.tmp").exists()
    assert _read_gzip_json(target) == payload
