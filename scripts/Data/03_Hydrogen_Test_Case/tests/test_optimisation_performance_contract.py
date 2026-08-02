from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyomo.environ as pyo
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[4]
CASE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, CASE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.optimisation_performance import (  # noqa: E402
    RUNTIME_COLUMNS,
    StructuralSignature,
    StructuralTemplateCache,
    dst_shape_for_steps,
    runtime_record,
)
from hydrogen.bidding_model import (  # noqa: E402
    HydrogenWarmStartSnapshot,
    _apply_hydrogen_warm_start,
    _scenario_dispatch_from_pyomo,
)
from hydrogen.rolling_horizon import RollingHydrogenState  # noqa: E402


def _signature(*, steps: int = 120, scenarios: int = 30) -> StructuralSignature:
    return StructuralSignature(
        model_type="hydrogen_stochastic_da_D-D+4",
        granularity="hourly",
        timestep_count=steps,
        scenario_count=scenarios,
        bid_grid=(0.0, 100.0, 3000.0),
        dst_shape=dst_shape_for_steps("hourly", steps),
        physical_config_hash="physical",
        quota_structure="weekly",
    )


def test_structural_signature_is_stable_and_invalidates_on_structure_change() -> None:
    assert _signature().digest == _signature().digest
    assert _signature().digest != _signature(scenarios=10).digest
    assert _signature().digest != _signature(steps=119).digest


def test_template_cache_reports_hit_only_for_exact_signature() -> None:
    cache = StructuralTemplateCache()
    assert cache.register(_signature(), {"safe": True})[0] == "miss_registered"
    assert cache.register(_signature(), {"safe": True})[0] == "hit"
    assert cache.register(_signature(scenarios=10), {"safe": True})[0] == "miss_registered"


def test_dst_template_shapes_cover_hourly_and_quarter_hour_days() -> None:
    assert "23steps" in dst_shape_for_steps("hourly", 23, 1)
    assert "25steps" in dst_shape_for_steps("hourly", 25, 1)
    assert "92steps" in dst_shape_for_steps("quarter_hour", 92, 1)
    assert "100steps" in dst_shape_for_steps("quarter_hour", 100, 1)


def test_warm_start_requires_structure_and_source_block_identity() -> None:
    model = pyo.ConcreteModel()
    model.T = pyo.RangeSet(0, 0)
    model.B = pyo.RangeSet(0, 0)
    model.S = pyo.Set(initialize=["S1"])
    model.q = pyo.Var(model.T, model.B)
    model.P_el = pyo.Var(model.S, model.T)
    timestamp = pd.Timestamp("2026-04-06T00:00:00Z")
    snapshot = HydrogenWarmStartSnapshot(
        q_by_timestamp_block={(timestamp.isoformat(), 0): 12.0},
        scenario_values={("P_el", "S1", "BLOCK_A", timestamp.isoformat()): 8.0},
        scenario_source_blocks={"S1": "BLOCK_A"},
        structural_signature="same",
    )
    status, applied = _apply_hydrogen_warm_start(
        model,
        snapshot=snapshot,
        timestamps=pd.DatetimeIndex([timestamp]),
        scenario_ids=["S1"],
        source_blocks={"S1": "BLOCK_A"},
        structural_signature="same",
    )
    assert status == "applied"
    assert applied == 2
    assert pyo.value(model.q[0, 0]) == 12.0
    assert pyo.value(model.P_el["S1", 0]) == 8.0

    rejected, rejected_count = _apply_hydrogen_warm_start(
        model,
        snapshot=snapshot,
        timestamps=pd.DatetimeIndex([timestamp]),
        scenario_ids=["S1"],
        source_blocks={"S1": "BLOCK_B"},
        structural_signature="different",
    )
    assert rejected == "rejected_structural_signature"
    assert rejected_count == 0


def test_hydrogen_and_steel_runtime_records_share_exact_schema() -> None:
    hydrogen = runtime_record(system="hydrogen", model_type="bidding")
    steel = runtime_record(system="steel", model_type="deterministic_rolling")
    assert tuple(hydrogen) == RUNTIME_COLUMNS
    assert tuple(steel) == RUNTIME_COLUMNS


def test_optimisation_frame_contract_excludes_actuals() -> None:
    optimization_columns = {
        "forecast_origin_utc", "delivery_start_utc", "scenario_id",
        "scenario_probability", "scenario_price_eur_per_mwh",
    }
    forbidden = {"actual_price_eur_per_mwh", "error", "realised_price"}
    assert optimization_columns.isdisjoint(forbidden)


def test_lazy_extraction_keeps_executed_step_and_audit_reconstructs_future() -> None:
    model = pyo.ConcreteModel()
    model.S = pyo.Set(initialize=["S1"])
    model.T = pyo.RangeSet(0, 1)
    model.used_energy = pyo.Var(model.S, model.T, initialize=1.0)
    model.unused_cleared_energy = pyo.Var(model.S, model.T, initialize=0.0)
    model.P_el = pyo.Var(model.S, model.T, initialize=1.0)
    model.u_el = pyo.Var(model.S, model.T, initialize=1.0)
    model.H_prod = pyo.Var(model.S, model.T, initialize=18.0)
    model.P_comp = pyo.Var(model.S, model.T, initialize=0.1)
    model.H_comp = pyo.Var(model.S, model.T, initialize=10.0)
    model.H_buf = pyo.Var(model.S, model.T, initialize=100.0)
    model.shortfall = pyo.Var(model.S, initialize=0.0)
    timestamps = pd.date_range("2026-04-06T00:00:00Z", periods=2, freq="h")
    kwargs = {
        "strategy": "fixture", "scenario_model": "fixture",
        "timestamps": timestamps, "scenario_ids": ["S1"],
        "probabilities": {"S1": 1.0},
        "price_lookup": {("S1", 0): 50.0, ("S1", 1): 60.0},
        "acceptance_lookup": {("S1", 0, 0): 1, ("S1", 1, 0): 1},
        "q_matrix": np.asarray([[1.0], [1.0]]),
        "bid_price_grid_eur_per_mwh": [100.0], "run_id": "fixture",
        "forecast_origin_utc": pd.Timestamp("2026-04-05T06:00:00Z"),
        "timestep_hours": 1.0, "daily_target_kg": 19_000.0,
    }
    lazy_dispatch, lazy_clearing = _scenario_dispatch_from_pyomo(
        model, extraction_time_indices=[0], **kwargs
    )
    audit_dispatch, audit_clearing = _scenario_dispatch_from_pyomo(model, **kwargs)
    assert len(lazy_dispatch) == 1
    assert len(lazy_clearing) == 1
    assert len(audit_dispatch) == 2
    assert len(audit_clearing) == 2
    assert lazy_dispatch["delivery_start_utc"].tolist() == [timestamps[0]]


def test_episode_gap_requires_fresh_state_object() -> None:
    secondary = RollingHydrogenState(episode_id="secondary", storage_inventory_kg=7_500.0)
    primary = RollingHydrogenState(episode_id="primary", storage_inventory_kg=5_000.0)
    assert secondary.episode_id != primary.episode_id
    assert primary.storage_inventory_kg == 5_000.0
    assert primary.realised_compression_by_week_kg == {}
