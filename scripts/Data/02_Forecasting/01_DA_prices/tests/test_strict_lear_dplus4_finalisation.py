from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.coupled_multiday_scenarios import ResidualBlock, eligible_blocks, generate_raw_coupled_paths
from hourly_da.core.multiday_scenario_reduction import assert_nested_reduction, reduce_weighted_paths
from quarterhour_da.phase04 import _fit_mean_shape, _predict_mean_shape
from quarterhour_da.strict_lear_finalisation import FinalisationConfig, build_supported_grid
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig


def _load_qh_cleaner_module():
    path = PACKAGE_ROOT.parents[1] / "01_Cleaning" / "nl_quarterly_da_prices_pipeline.py"
    spec = importlib.util.spec_from_file_location("test_nl_qh_cleaner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_anchor_exporter_module():
    path = PACKAGE_ROOT / "one_off" / "2026-05_campaign" / "run_lago_lear_export_for_qh.py"
    spec = importlib.util.spec_from_file_location("test_strict_anchor_exporter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_weighted_reduction_is_nested_and_probability_aware() -> None:
    paths = np.random.default_rng(7).normal(size=(400, 120))
    raw_weights = np.linspace(1.0, 2.0, 400)
    raw_weights /= raw_weights.sum()
    reduced_30 = reduce_weighted_paths(
        paths,
        scenario_ids=[f"raw_{index}" for index in range(400)],
        weights=raw_weights,
        n_keep=30,
        protected_count=6,
    )
    reduced_10 = reduce_weighted_paths(
        paths[reduced_30.representative_indices],
        scenario_ids=list(reduced_30.representative_ids),
        weights=reduced_30.probabilities,
        n_keep=10,
        protected_count=2,
    )
    assert_nested_reduction(reduced_30.representative_ids, reduced_10)
    assert len(reduced_30.protected_representative_ids) == 6
    assert len(reduced_10.protected_representative_ids) == 2
    assert np.isclose(reduced_30.probabilities.sum(), 1.0, atol=1e-12)
    assert np.isclose(reduced_10.probabilities.sum(), 1.0, atol=1e-12)
    assert not np.allclose(reduced_30.probabilities, np.repeat(1 / 30, 30))


def test_coupled_paths_preserve_hourly_mean_and_causal_source_rule() -> None:
    origin = pd.Timestamp("2026-03-18T07:00:00Z")
    block = ResidualBlock(
        block_id="source",
        source_origin_utc=pd.Timestamp("2026-01-01T07:00:00Z"),
        available_at_utc=pd.Timestamp("2026-01-06T00:00:00Z"),
        dataset_split="train",
        hourly_by_lead=tuple(np.linspace(-2.0, 2.0, 24) for _ in range(5)),
        shape_by_lead=tuple(np.tile(np.array([-1.0, 0.0, 0.5, 0.5]), 24) for _ in range(5)),
    )
    assert eligible_blocks([block], forecast_origin_utc=origin, allowed_splits={"train"}) == [block]
    hourly_point = np.repeat(50.0, 120)
    qh_point = np.repeat(hourly_point, 4)
    qh_to_hour = np.repeat(np.arange(120), 4)
    generated = generate_raw_coupled_paths(
        hourly_point=hourly_point,
        qh_point=qh_point,
        hourly_counts_by_lead=(24, 24, 24, 24, 24),
        qh_counts_by_lead=(96, 96, 96, 96, 96),
        qh_to_hour=qh_to_hour,
        residual_blocks=[block],
        n_raw=4,
        level_scale=1.3,
        shape_scale=1.5,
        seed=11,
    )
    qh_hourly = generated.quarterhour.reshape(4, 120, 4).mean(axis=2)
    assert np.allclose(qh_hourly, generated.hourly, atol=1e-12)


def test_supported_grid_keeps_native_spring_dst_length_and_rejects_missing_truth() -> None:
    index = pd.date_range("2026-03-23T23:00:00Z", "2026-04-03T22:00:00Z", freq="15min", inclusive="left")
    qh = pd.DataFrame({"timestamp_utc": index, "price_eur_per_mwh": 50.0})
    qh["timestamp_local"] = qh["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    qh["local_date"] = qh["timestamp_local"].dt.date
    config = FinalisationConfig(
        train_start_local_date=date(2026, 3, 25),
        validation_start_local_date=date(2026, 3, 26),
        evaluation_start_local_date=date(2026, 3, 27),
        requested_end_local_date=date(2026, 4, 2),
        raw_scenarios=400,
        final_scenarios=30,
        nested_scenarios=10,
        level_scales=(1.0,),
        shape_scales=(1.0,),
        protected_tail_share=0.2,
        window_days=1092,
        random_seed=1,
    )
    grid, support, _ = build_supported_grid(qh, config)
    crossing = grid[grid["delivery_start_local_date"].eq("2026-03-25")]
    assert len(crossing) == 476
    assert crossing.groupby("lead_day").size().tolist() == [96, 96, 96, 96, 92]
    missing_timestamp = pd.Timestamp("2026-03-27T10:15:00Z")
    reduced = qh[qh["timestamp_utc"].ne(missing_timestamp)]
    _, missing_support, _ = build_supported_grid(reduced, config)
    assert (~missing_support["selected"]).any()


def test_a03_variable_blocks_are_forward_expanded_not_interpolated() -> None:
    cleaner = _load_qh_cleaner_module()
    period_start = pd.Timestamp("2026-01-01T00:00:00Z")
    common = {
        "curve_type": "A03",
        "source_path": "source.xml",
        "document_id": "doc",
        "timeseries_index": 1,
        "period_index": 1,
        "period_start_utc": period_start,
        "period_end_utc": period_start + pd.Timedelta(hours=1),
        "resolution_minutes": 15,
        "created_datetime_utc": pd.Timestamp("2025-12-31T12:00:00Z"),
    }
    source = pd.DataFrame(
        [
            {**common, "timestamp_utc": period_start, "position": 1, "price_eur_per_mwh": 50.0},
            {**common, "timestamp_utc": period_start + pd.Timedelta(minutes=45), "position": 4, "price_eur_per_mwh": 70.0},
        ]
    )
    expanded = cleaner.expand_a03_variable_blocks(source, expected_minutes=15)
    assert expanded["position"].tolist() == [1, 2, 3, 4]
    assert expanded["price_eur_per_mwh"].tolist() == [50.0, 50.0, 50.0, 70.0]
    assert expanded["a03_variable_block_expanded"].tolist() == [False, True, True, False]
    assert set(expanded["a03_expansion_method"]) == {"official_curve_type_a03_forward_block"}


def test_mean_shape_fallback_handles_filtered_nonconsecutive_index() -> None:
    training = pd.DataFrame(
        {
            "local_hour_of_day": [0, 0, 0, 0],
            "quarter_index": [1, 2, 3, 4],
            "weekend_flag": [False, False, False, False],
            "delta_eur_per_mwh": [-3.0, -1.0, 1.0, 3.0],
        }
    )
    state = _fit_mean_shape(training)
    evaluation = pd.DataFrame(
        {
            "local_hour_of_day": [0, 0],
            "quarter_index": [1, 4],
            "weekend_flag": [True, True],
        },
        index=[100, 400],
    )
    prediction = _predict_mean_shape(state, evaluation)
    assert prediction.tolist() == [-3.0, 3.0]


def test_parallel_strict_anchor_fit_writes_predictions() -> None:
    exporter = _load_anchor_exporter_module()
    scratch = Path("tmp/strict_anchor_parallel_contract_test")
    scratch.mkdir(parents=True, exist_ok=True)
    origins = pd.date_range("2025-01-01T07:00:00Z", periods=20, freq="D")
    matrix = pd.DataFrame(
        {
            "forecast_origin_utc": origins,
            "target_timestamp_utc": origins + pd.Timedelta(hours=16),
            "lead_day": 0,
            "target_hour_local": 0,
            "dataset_split": "train",
            "origin_ns_i64": origins.astype("int64"),
            "x1": np.arange(20, dtype=float),
            "x2": np.sin(np.arange(20, dtype=float)),
            "y_true": 40.0 + np.arange(20, dtype=float),
        }
    )
    evaluation = matrix.tail(2).copy()
    output = scratch / "predictions.csv"
    progress = scratch / "progress.json"
    config = LagoLearBenchmarkConfig(min_training_days_by_window={1092: 1})
    result = exporter._fit_predict_rows(
        matrix=matrix,
        eval_rows=evaluation,
        feature_cols=["x1", "x2"],
        config=config,
        window_days=1092,
        model_name="test",
        already_done=set(),
        predictions_csv_path=output,
        progress_path=progress,
        checkpoint_flush_rows=1,
        log_every_rows=1,
        estimate_only=False,
        n_jobs=2,
    )
    predictions = pd.read_csv(output)
    assert result["n_jobs"] == 2
    assert len(predictions) == 2
    assert predictions["y_pred"].notna().all()
    output.unlink(missing_ok=True)
    progress.unlink(missing_ok=True)
    scratch.rmdir()
