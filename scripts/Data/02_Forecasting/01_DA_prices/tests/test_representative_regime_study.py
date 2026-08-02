from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.representative_regime_study import (
    POINT_COLUMNS,
    PUBLIC_MODEL_IDS,
    ScenarioPolicy,
    align_common_non_dst_support,
    apply_counterfactual_shape_overlay,
    build_hourly_residual_blocks,
    build_shape_library,
    build_steel_experiment_manifest,
    calibrate_hourly_level_scale,
    generate_hourly_nested_scenarios,
    read_physical_prerequisite,
    realised_cost_differences,
    select_regime_weeks,
    validate_overlay_contract,
    validate_scenario_contract,
)
from hourly_da.core.coupled_multiday_scenarios import (
    ResidualBlock,
    generate_raw_coupled_paths,
)
from hourly_da.core.multiday_scenario_reduction import reduce_weighted_paths
from quarterhour_da import representative_regime_study as study_module


LOCAL_TZ = "Europe/Amsterdam"


def _origin_for_day(day: str) -> pd.Timestamp:
    return (
        pd.Timestamp(day, tz=LOCAL_TZ)
        - pd.Timedelta(days=1)
        + pd.Timedelta(hours=8)
    ).tz_convert("UTC")


def _point_day(model_id: str, day: str, split: str, offset: float = 0.0) -> pd.DataFrame:
    start = pd.Timestamp(day, tz=LOCAL_TZ).tz_convert("UTC")
    timestamp = pd.date_range(start, periods=24, freq="h")
    actual = 50.0 + np.sin(np.arange(24) / 3.0)
    return pd.DataFrame(
        {
            "model_id": model_id,
            "forecast_origin_utc": _origin_for_day(day),
            "target_timestamp_utc": timestamp,
            "delivery_date_local": day,
            "lead_day": 0,
            "dataset_split": split,
            "point_forecast": actual + offset,
            "actual_price": actual,
            "support_status": "candidate",
        },
        columns=POINT_COLUMNS,
    )


def test_common_support_is_exact_and_excludes_non_24h_days() -> None:
    frames = {}
    for index, model_id in enumerate(PUBLIC_MODEL_IDS.values()):
        frames[model_id] = pd.concat(
            [
                _point_day(model_id, "2024-01-08", "validation", index),
                _point_day(model_id, "2024-01-09", "validation", index),
                _point_day(model_id, "2024-10-07", "test", index),
            ],
            ignore_index=True,
        )
    aligned, support = align_common_non_dst_support(frames)
    assert support.set_index("dataset_split").loc["validation", "exact_common_complete_24h_days"] == 2
    assert support.set_index("dataset_split").loc["test", "exact_common_complete_24h_days"] == 1
    assert all(frame["support_status"].eq("exact_common_complete_24h_non_dst").all() for frame in aligned.values())


def test_all_families_use_nested_probability_aware_scenario_contract() -> None:
    model_id = PUBLIC_MODEL_IDS["strict"]
    frame = pd.concat(
        [
            _point_day(model_id, "2024-01-08", "validation", 1.0),
            _point_day(model_id, "2024-01-10", "validation", -1.0),
            _point_day(model_id, "2024-10-07", "test", 0.5),
        ],
        ignore_index=True,
    )
    blocks = build_hourly_residual_blocks(frame)
    policy = ScenarioPolicy(
        raw_count=20,
        parent_count=5,
        final_count=3,
        protected_tail_share=0.2,
        level_scales=(1.0,),
        random_seed=7,
    )
    scale, calibration = calibrate_hourly_level_scale(frame, blocks, policy)
    scenarios, mapping, parent_scenarios = generate_hourly_nested_scenarios(
        frame, blocks, policy, level_scale=scale
    )
    checks = validate_scenario_contract(scenarios, expected_count=3)
    assert calibration.loc[calibration["selected"], "level_scale"].tolist() == [1.0]
    assert checks["status"].eq("pass").all()
    assert len(mapping) == 5
    assert validate_scenario_contract(parent_scenarios, expected_count=5)["status"].eq("pass").all()
    assert np.isclose(scenarios.drop_duplicates("scenario_id")["scenario_probability"].sum(), 1.0)


def test_hourly_specialisation_matches_coupled_generator_and_reduction() -> None:
    blocks = [
        ResidualBlock(
            block_id=f"block_{index}",
            source_origin_utc=pd.Timestamp("2024-01-01T07:00:00Z") + pd.Timedelta(days=index),
            available_at_utc=pd.Timestamp("2024-01-02T00:00:00Z") + pd.Timedelta(days=index),
            dataset_split="validation",
            hourly_by_lead=(np.linspace(-index, index, 24),),
            shape_by_lead=(np.zeros(96),),
        )
        for index in range(1, 6)
    ]
    point = np.linspace(40.0, 60.0, 24)
    specialised_error, specialised_sources = study_module._sample_hourly_unit_residuals(
        blocks, n_raw=20, seed=19
    )
    generic = generate_raw_coupled_paths(
        hourly_point=point,
        qh_point=np.repeat(point, 4),
        hourly_counts_by_lead=(24,),
        qh_counts_by_lead=(96,),
        qh_to_hour=np.repeat(np.arange(24), 4),
        residual_blocks=blocks,
        n_raw=20,
        level_scale=1.0,
        shape_scale=0.0,
        seed=19,
    )
    specialised_paths = point[None, :] + specialised_error
    assert np.allclose(specialised_paths, generic.hourly)
    assert specialised_sources == generic.source_block_ids
    weights = np.repeat(1.0 / 20, 20)
    hourly_reduction = reduce_weighted_paths(
        specialised_paths,
        scenario_ids=[str(index) for index in range(20)],
        weights=weights,
        n_keep=5,
        protected_count=1,
    )
    qh_reduction = reduce_weighted_paths(
        generic.quarterhour,
        scenario_ids=[str(index) for index in range(20)],
        weights=weights,
        n_keep=5,
        protected_count=1,
    )
    assert hourly_reduction.representative_ids == qh_reduction.representative_ids
    assert np.allclose(hourly_reduction.probabilities, qh_reduction.probabilities)


def _shape_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    origin = pd.Timestamp("2026-04-05T06:00:00Z")
    hourly_timestamp = pd.date_range("2026-04-05T22:00:00Z", periods=24, freq="h")
    qh_timestamp = pd.date_range("2026-04-05T22:00:00Z", periods=96, freq="15min")
    hourly_point = pd.DataFrame(
        {
            "forecast_origin_utc": origin,
            "target_timestamp_utc": hourly_timestamp,
            "lead_day": 0,
            "point_forecast": 50.0,
        }
    )
    delta = np.tile(np.array([-3.0, -1.0, 1.0, 3.0]), 24)
    qh_point = pd.DataFrame(
        {
            "forecast_origin_utc": origin,
            "target_timestamp_utc": qh_timestamp,
            "lead_day": 0,
            "point_forecast": 50.0 + delta,
        }
    )
    hourly_scenario = pd.concat(
        [
            hourly_point.assign(scenario_id=scenario, scenario_probability=0.5, scenario_price=price)
            for scenario, price in (("S10_01", 45.0), ("S10_02", 55.0))
        ],
        ignore_index=True,
    )
    qh_scenario = pd.concat(
        [
            qh_point.assign(
                scenario_id=scenario,
                scenario_probability=0.5,
                scenario_price=price + delta,
            )
            for scenario, price in (("S10_01", 45.0), ("S10_02", 55.0))
        ],
        ignore_index=True,
    )
    actuals = pd.concat(
        [
            hourly_point.rename(columns={"point_forecast": "actual_price"}).assign(granularity="hourly"),
            qh_point.rename(columns={"point_forecast": "actual_price"}).assign(granularity="quarterhour"),
        ],
        ignore_index=True,
    )
    return hourly_point, qh_point, hourly_scenario, qh_scenario, actuals


def test_additive_overlay_preserves_every_hourly_anchor() -> None:
    inputs = _shape_inputs()
    library = build_shape_library(*inputs)
    target_timestamp = pd.date_range("2025-01-12T23:00:00Z", periods=24, freq="h")
    target_point = pd.DataFrame(
        {
            "target_timestamp_utc": target_timestamp,
            "delivery_date_local": "2025-01-13",
            "point_forecast": 80.0,
        }
    )
    target_scenarios = pd.concat(
        [
            target_point.assign(
                scenario_id=scenario,
                scenario_probability=0.5,
                scenario_price=price,
            )
            for scenario, price in (("S10_01", 75.0), ("S10_02", 85.0))
        ],
        ignore_index=True,
    )
    target_actual = target_point.rename(columns={"point_forecast": "actual_price"})
    overlay, manifest = apply_counterfactual_shape_overlay(
        week_id="winter",
        hourly_points=target_point,
        hourly_scenarios=target_scenarios,
        hourly_actuals=target_actual,
        shape_library=library,
        random_seed=11,
    )
    checks = validate_overlay_contract(overlay)
    assert checks["status"].eq("pass").all()
    assert overlay["counterfactual"].all()
    assert manifest["observed_historical_qh_claim"] is False


def test_week_selection_is_role_ranked_not_forced_to_provisional() -> None:
    starts = pd.date_range("2024-10-07", periods=20, freq="28D")
    features = pd.DataFrame(
        {
            "week_start": starts.date.astype(str),
            "week_end": (starts + pd.Timedelta(days=6)).date.astype(str),
            "mean_price": np.arange(20, dtype=float),
            "std_price": np.arange(20, dtype=float) + 1.0,
            "iqr_price": np.arange(20, dtype=float) + 2.0,
            "p05_p95_range": np.arange(20, dtype=float) + 3.0,
            "negative_share": np.linspace(0.2, 0.0, 20),
            "mean_absolute_ramp": np.arange(20, dtype=float) + 4.0,
            "max_absolute_ramp": np.arange(20, dtype=float) + 5.0,
            "minimum_price": -10.0,
            "complete_non_interpolated_hourly_actuals": True,
        }
    )
    eligible = set(features["week_start"])
    provisional = {
        "typical_winter": features.iloc[0]["week_start"],
        "high_prices": features.iloc[0]["week_start"],
        "high_volatility": features.iloc[0]["week_start"],
        "typical_summer": features.iloc[0]["week_start"],
    }
    selected, _ = select_regime_weeks(
        features,
        eligible_week_starts=eligible,
        provisional=provisional,
        minimum_separation_days=28,
    )
    high_price = selected.set_index("regime_role").loc["high_prices"]
    assert high_price["week_start"] != provisional["high_prices"]
    assert bool(high_price["provisional_retained"]) is False


def test_steel_matrix_is_maintenance_free_and_fails_closed() -> None:
    weeks = pd.DataFrame(
        [
            {
                "week_id": "typical_winter__2025-01-13",
                "regime_role": "typical_winter",
                "week_start": "2025-01-13",
                "week_end": "2025-01-19",
            }
        ]
    )
    manifest, readiness = build_steel_experiment_manifest(
        weeks,
        physical_prerequisite={"economic_steel_execution_allowed": False, "status": "blocked"},
        long_horizon_support_available=False,
        scenario_30_support_available=True,
    )
    assert readiness["status"] == "blocked"
    assert not manifest["economic_execution_ready"].any()
    assert manifest["maintenance_policy"].eq("maintenance_free_normal_operation_week").all()
    assert not manifest["weekly_eaf_maintenance_active"].any()
    assert manifest.loc[manifest["horizon_hours"].gt(24), "blockers"].str.contains(
        "causal_strict_dplus1_to_dplus4_support_missing"
    ).all()
    assert not manifest["mfrr_active"].any()


def test_physical_gate_keeps_performance_time_limit_as_warning() -> None:
    summary = json.dumps(
        {
            "run_id": "phase6d",
            "gate_a_status": "pass",
            "validation_failure_count": 0,
            "failure_count": 1,
        }
    )
    failures = pd.DataFrame(
        [{"classification": "performance_incomplete", "error": "maxTimeLimit"}]
    )
    with (
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "read_text", return_value=summary),
        patch.object(study_module.pd, "read_csv", return_value=failures),
    ):
        gate = read_physical_prerequisite("run_summary.json", "failures.csv")
    assert gate["status"] == "pass_with_performance_warning"
    assert gate["economic_steel_execution_allowed"] is True
    assert gate["performance_incomplete"] is True


def test_cost_differences_use_positive_equals_saving_convention() -> None:
    result = realised_cost_differences(100.0, 90.0, 80.0)
    assert result["delta_qh_market_eur"] == 10.0
    assert result["delta_shape_eur"] == 10.0
    assert result["delta_total_eur"] == 20.0
    assert result["positive_means_saving"] is True


def test_c1_24h_infeasibility_blocks_the_complete_economic_matrix() -> None:
    weeks = pd.DataFrame(
        [
            {
                "week_id": "winter",
                "regime_role": "typical_winter",
                "week_start": "2024-12-02",
                "week_end": "2024-12-08",
            }
        ]
    )
    manifest, readiness = build_steel_experiment_manifest(
        weeks,
        physical_prerequisite={"economic_steel_execution_allowed": True, "status": "pass"},
        long_horizon_support_available=False,
        scenario_30_support_available=True,
        c1_split_horizon_feasible=False,
    )
    c0_central = manifest[
        manifest["configuration"].eq("C0")
        & manifest["experiment_class"].eq("central")
    ]
    assert not c0_central["economic_execution_ready"].any()
    assert not manifest["economic_execution_ready"].any()
    assert manifest["blockers"].str.contains(
        "global_c1_24e48p_split_horizon_prerequisite_failed"
    ).all()
    assert readiness["status"] == "blocked"
