from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_bf_price_series_interface import (
    PriceSeriesInterfaceError,
    build_rolling_price_slice,
    load_price_series_contract,
)


def test_flat_price_series_is_hourly_aligned_and_replan_safe() -> None:
    rows = build_rolling_price_slice(
        price_series_id="flat_central_reference_v1",
        replan_index=3,
        planning_horizon_hours=168,
        execution_block_hours=24,
    )
    assert len(rows) == 168
    assert {row["price_eur_per_mwh_e"] for row in rows} == {80.0}
    assert [row["model_hour"] for row in rows] == list(range(168))
    replan = datetime.fromisoformat(rows[0]["replan_timestamp_utc"])
    assert all(
        datetime.fromisoformat(row["information_available_timestamp_utc"]) <= replan
        for row in rows
    )


def test_synthetic_series_changes_prices_but_never_uses_realised_future() -> None:
    rows = build_rolling_price_slice(
        price_series_id="synthetic_indexing_test_v1",
        replan_index=2,
        planning_horizon_hours=168,
        execution_block_hours=24,
    )
    assert {row["price_eur_per_mwh_e"] for row in rows} == {60.0, 80.0, 100.0}
    assert all(
        "realised" not in row["forecast_realised_classification"].lower()
        for row in rows
    )
    assert all(row["settlement_status"] == "interface_only_no_settlement" for row in rows)


def test_contract_fails_closed_on_unknown_series() -> None:
    assert set(load_price_series_contract()) == {
        "flat_central_reference_v1",
        "synthetic_indexing_test_v1",
        "synthetic_vn25_break_even_step_v1",
        "hourly_da_dplus4_point_forecast",
    }
    with pytest.raises(PriceSeriesInterfaceError, match="Unknown"):
        build_rolling_price_slice(
            price_series_id="unknown",
            replan_index=0,
            planning_horizon_hours=168,
            execution_block_hours=24,
        )


def test_vn25_step_series_straddles_governed_ng_break_even_without_future_leakage() -> None:
    rows = build_rolling_price_slice(
        price_series_id="synthetic_vn25_break_even_step_v1",
        replan_index=4,
        planning_horizon_hours=168,
        execution_block_hours=24,
    )
    break_even = 55.0 / 0.345
    assert {row["price_eur_per_mwh_e"] for row in rows} == {100.0, 220.0}
    assert any(row["price_eur_per_mwh_e"] < break_even for row in rows)
    assert any(row["price_eur_per_mwh_e"] > break_even for row in rows)
    assert all(
        datetime.fromisoformat(row["information_available_timestamp_utc"])
        <= datetime.fromisoformat(row["replan_timestamp_utc"])
        for row in rows
    )
