from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time
import unittest

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydrogen.optimisation.cache_manager import CacheManager  # noqa: E402
from hydrogen.optimisation.fingerprinting import (  # noqa: E402
    build_experiment_fingerprint,
    dataframe_fingerprint,
    fingerprint_file,
    fingerprint_payload,
)
from hydrogen.optimisation.input_resolver import InputSliceRequest, resolve_input_slice  # noqa: E402
from hydrogen.optimisation.output_policy import get_output_policy  # noqa: E402
from hydrogen.optimisation.runtime_profiling import RuntimeProfiler  # noqa: E402
from hydrogen.plant_parameters import (  # noqa: E402
    BiddingSettings,
    EconomicSettings,
    ExperimentSettings,
    HydrogenConfig,
    HydrogenSystemSettings,
    ModelSettings,
    OutputSettings,
    ProductionSettings,
    RiskSettings,
    SolverSettings,
)


def _build_tiny_scenario_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    local_index = pd.date_range("2025-01-06 00:00:00", periods=24, freq="h", tz="Europe/Amsterdam")
    forecast_origin_utc = pd.Timestamp("2025-01-05 07:00:00+00:00")
    for scenario_id, adjustment in [("s0", -5.0), ("s1", 5.0)]:
        for step, local_ts in enumerate(local_index):
            delivery_utc = local_ts.tz_convert("UTC")
            actual_price = float(100.0 + step)
            rows.append(
                {
                    "forecast_origin_utc": forecast_origin_utc,
                    "delivery_start_utc": delivery_utc,
                    "delivery_start_local": local_ts,
                    "delivery_day": local_ts.date().isoformat(),
                    "lead_day": 0,
                    "model_id": "tiny_model",
                    "scenario_id": scenario_id,
                    "scenario_probability": 0.5,
                    "point_forecast_eur_per_mwh": actual_price,
                    "scenario_price_eur_per_mwh": actual_price + adjustment,
                    "actual_price_eur_per_mwh": actual_price,
                    "granularity": "hourly",
                    "scenario_generation_run_id": "tiny_run",
                }
            )
    return pd.DataFrame(rows)


def _build_test_config(temp_root: Path, scenario_path: Path, catalog_path: Path) -> HydrogenConfig:
    return HydrogenConfig(
        repo_root=temp_root,
        config_path=temp_root / "tiny_config.yaml",
        experiment=ExperimentSettings(
            name="tiny_infra_smoke",
            granularity="hourly",
            horizon_mode="D_only",
            execution_mode="custom_period",
            selected_weeks_source=temp_root / "selected_weeks.yaml",
            selected_week_labels=(),
            custom_start="2025-01-06",
            custom_end="2025-01-06",
            dataset_split="test",
            random_seed=42,
        ),
        models=ModelSettings(
            include=("tiny_hourly_artifact",),
            scenario_catalog=catalog_path,
        ),
        strategies=("stochastic_risk_neutral",),
        risk=RiskSettings(
            alpha=0.95,
            gamma_grid=(0.0, 0.05),
            gamma=0.0,
            gamma_selection="validation_only",
            frozen_gamma_path=None,
        ),
        bidding=BiddingSettings(
            bid_price_grid_eur_per_mwh=(-500.0, 0.0, 100.0, 3000.0),
            price_insensitive_bid_price_eur_per_mwh=3000.0,
        ),
        production=ProductionSettings(
            target_semantics="lower_bound_reference",
            allow_above_target_production=True,
            allow_above_target_sales=True,
        ),
        hydrogen_system=HydrogenSystemSettings(
            electrolyser_nominal_mw=55.0,
            electrolyser_min_mw=5.5,
            electrolyser_ramp_mw_per_h=52.25,
            h2_efficiency_kg_per_mwh=18.0,
            compressor_max_mw=3.0,
            compressor_specific_mwh_per_kg=0.002,
            storage_capacity_kg=10000.0,
            storage_initial_kg=5000.0,
            reserve_fraction=0.10,
            reserve_sensitivity=(0.0, 0.10),
        ),
        economics=EconomicSettings(
            h2_sale_price_eur_per_kg=8.0,
            daily_target_kg=19000.0,
            p_ref_eur_per_mwh=158.0,
            terminal_inventory_location="before_compression",
            shortfall_penalty_eur_per_kg=20.0,
            unused_energy_penalty_eur_per_mwh=4000.0,
        ),
        solver=SolverSettings(
            package_preference="pyomo",
            solver_name="gurobi",
            mip_gap=0.001,
            time_limit_seconds=300,
            grb_license_file=None,
        ),
        outputs=OutputSettings(
            root=temp_root / "runs",
            save_figures=False,
            save_timeseries=False,
            save_solver_log=False,
        ),
    )


class OptimisationRunInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir_context = tempfile.TemporaryDirectory()
        self.tempdir = Path(self.tempdir_context.name)
        self.scenario_path = self.tempdir / "tiny_scenarios.csv"
        self.catalog_path = self.tempdir / "scenario_catalog.yaml"
        self.config_path = self.tempdir / "tiny_config.yaml"
        scenario_frame = _build_tiny_scenario_frame()
        scenario_frame.to_csv(self.scenario_path, index=False)
        self.catalog_path.write_text(
            yaml.safe_dump(
                {
                    "default_artifact": "tiny_hourly_artifact",
                    "artifacts": {
                        "tiny_hourly_artifact": {
                            "path": str(self.scenario_path),
                            "model_id": "tiny_model",
                            "dataset_split": None,
                            "granularity": "hourly",
                            "validation_mode": "thesis_grade",
                            "allow_forecast_origin_reconstruction": False,
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.config = _build_test_config(self.tempdir, self.scenario_path, self.catalog_path)
        self.config_path.write_text("tiny_config: true\n", encoding="utf-8")
        self.config = replace(self.config, config_path=self.config_path)

    def tearDown(self) -> None:
        self.tempdir_context.cleanup()

    def test_fingerprint_stability_and_sensitivity(self) -> None:
        payload_a = {"b": 2, "a": 1}
        payload_b = {"a": 1, "b": 2}
        self.assertEqual(fingerprint_payload(payload_a), fingerprint_payload(payload_b))
        self.assertNotEqual(fingerprint_payload(payload_a), fingerprint_payload({"a": 1, "b": 3}))

        frame = pd.DataFrame({"delivery_day": ["2025-01-06", "2025-01-05"], "price": [1.0, 2.0]})
        same_values_different_order = frame.iloc[[1, 0]].reset_index(drop=True)
        self.assertEqual(
            dataframe_fingerprint(frame, sort_by=["delivery_day"]),
            dataframe_fingerprint(same_values_different_order, sort_by=["delivery_day"]),
        )
        changed = frame.copy()
        changed.loc[0, "price"] = 9.0
        self.assertNotEqual(dataframe_fingerprint(frame, sort_by=["delivery_day"]), dataframe_fingerprint(changed, sort_by=["delivery_day"]))

    def test_cache_equivalence_on_tiny_fixture(self) -> None:
        cache_root = self.tempdir / "cache_equivalence"
        manager = CacheManager(cache_root)
        frame = _build_tiny_scenario_frame().head(4).reset_index(drop=True)
        sources = [fingerprint_file(self.scenario_path, include_sha256=False).to_dict()]
        manager.save_bundle(
            namespace="tiny",
            key="abc123",
            frames={"sample": frame},
            manifest={"source_fingerprints": sources, "kind": "fixture"},
        )
        loaded = manager.load_bundle(namespace="tiny", key="abc123", expected_source_fingerprints=sources)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.cache_status, "hit")
        pd.testing.assert_frame_equal(loaded.frames["sample"], frame)

    def test_stale_cache_invalidation(self) -> None:
        cache_root = self.tempdir / "cache_stale"
        manager = CacheManager(cache_root)
        frame = _build_tiny_scenario_frame().head(4).reset_index(drop=True)
        initial_sources = [fingerprint_file(self.scenario_path, include_sha256=False).to_dict()]
        manager.save_bundle(
            namespace="tiny",
            key="stale-key",
            frames={"sample": frame},
            manifest={"source_fingerprints": initial_sources},
        )
        with self.scenario_path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        time.sleep(0.01)
        updated_sources = [fingerprint_file(self.scenario_path, include_sha256=False).to_dict()]
        loaded = manager.load_bundle(namespace="tiny", key="stale-key", expected_source_fingerprints=updated_sources)
        self.assertIsNone(loaded)

    def test_output_policy_behaviour(self) -> None:
        minimal = get_output_policy("minimal")
        audit = get_output_policy("audit")
        full = get_output_policy("full")

        self.assertFalse(minimal.save_timeseries)
        self.assertTrue(full.save_figures)
        self.assertFalse(minimal.should_persist_solver_log(solver_status="optimal", audit_day=False))
        self.assertTrue(audit.should_persist_solver_log(solver_status="infeasible", audit_day=False))
        self.assertTrue(full.should_persist_solver_log(solver_status="optimal", audit_day=True))

    def test_runtime_profiler_writes_expected_timing_fields(self) -> None:
        profiler = RuntimeProfiler()
        for stage in ("load", "build", "solve", "write"):
            with profiler.track(stage, artifact_id="tiny"):
                pass
        output_path = self.tempdir / "runtime.csv"
        profiler.save_csv(output_path)
        frame = pd.read_csv(output_path)
        self.assertEqual(frame["stage"].tolist(), ["load", "build", "solve", "write"])
        self.assertTrue({"started_utc", "finished_utc", "wall_time_seconds", "artifact_id"}.issubset(frame.columns))

    def test_runner_scripts_do_not_directly_load_large_files(self) -> None:
        runner_dir = Path(__file__).resolve().parents[1]
        disallowed_tokens = ("read_csv(", "read_parquet(", "read_pickle(")
        offending: list[str] = []
        for path in sorted(runner_dir.glob("run_*.py")):
            content = path.read_text(encoding="utf-8")
            if any(token in content for token in disallowed_tokens):
                offending.append(str(path))
        self.assertEqual(offending, [])

    def test_input_resolver_and_cache_manager_smoke(self) -> None:
        request = InputSliceRequest(
            artifact_id="tiny_hourly_artifact",
            start_local_date="2025-01-06",
            end_local_date="2025-01-06",
            period_mode="custom_period",
            dataset_split="test",
        )
        profiler = RuntimeProfiler()
        cache_root = self.tempdir / "resolver_cache"
        policy = get_output_policy("minimal")

        with profiler.track("load", source="cold"):
            cold = resolve_input_slice(
                self.config,
                request=request,
                output_policy_name=policy.name,
                cache_root=cache_root,
            )
        with profiler.track("load", source="warm"):
            warm = resolve_input_slice(
                self.config,
                request=request,
                output_policy_name=policy.name,
                cache_root=cache_root,
            )
        with profiler.track("write", target="runtime_profile"):
            profiler.save_csv(self.tempdir / "smoke_runtime.csv")

        self.assertEqual(cold.cache_status, "miss")
        self.assertEqual(warm.cache_status, "hit")
        self.assertEqual(cold.slice_fingerprint, warm.slice_fingerprint)
        self.assertEqual(cold.experiment_fingerprint.digest, warm.experiment_fingerprint.digest)
        self.assertEqual(int(cold.market_actuals.shape[0]), 24)
        self.assertEqual(int(cold.origin_registry.shape[0]), 1)
        self.assertEqual(int(cold.scenarios["scenario_id"].nunique()), 2)
        self.assertTrue((cache_root / "input_slices" / cold.slice_fingerprint / "manifest.json").exists())

        experiment_fingerprint = build_experiment_fingerprint(
            config=self.config,
            input_slice_fingerprint=cold.slice_fingerprint,
            output_policy_name=policy.name,
        )
        self.assertEqual(experiment_fingerprint.digest, cold.experiment_fingerprint.digest)


if __name__ == "__main__":
    unittest.main()
