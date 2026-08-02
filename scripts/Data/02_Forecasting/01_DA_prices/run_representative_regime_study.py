from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.representative_regime_study import (
    PUBLIC_MODEL_IDS,
    STRICT_MODEL_ID,
    ScenarioPolicy,
    StudyContractError,
    align_common_non_dst_support,
    apply_counterfactual_shape_overlay,
    build_hourly_residual_blocks,
    build_shape_library,
    build_steel_experiment_manifest,
    calibrate_hourly_level_scale,
    compute_week_features,
    generate_hourly_nested_scenarios,
    information_timing_checks,
    load_study_config,
    normalise_frozen_point_source,
    point_metrics,
    read_physical_prerequisite,
    scenario_metrics,
    select_regime_weeks,
    sha256_file,
    validate_scenario_contract,
)


DEFAULT_CONFIG = Path(
    "scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/configs/representative_regime_study.yaml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen D-only family audit or prepare the four-regime counterfactual study."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=("family-audit", "prepare-study", "preflight"), required=True)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        default=REPO_ROOT.parent / "Thesis",
        help="Read-only historical upstream repository containing the frozen 2024/25 point artifacts.",
    )
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument(
        "--resume-run",
        action="store_true",
        help="Reuse an incomplete governed run directory after a controlled interruption.",
    )
    return parser.parse_args()


def _resolve_repo(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _resolve_upstream(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_standard_files(
    run_dir: Path,
    *,
    config_path: Path,
    config: dict[str, Any],
    input_paths: dict[str, Path],
    output_contract: dict[str, Any],
    resume_run: bool = False,
) -> None:
    if run_dir.exists():
        if not resume_run:
            raise FileExistsError(run_dir)
        if (run_dir / "run_summary.json").exists():
            raise StudyContractError("a completed run directory cannot be resumed or overwritten")
    run_dir.mkdir(parents=True, exist_ok=resume_run)
    (run_dir / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _write_json(
        run_dir / "input_manifest.json",
        {
            "inputs": [
                {
                    "logical_name": logical_name,
                    "bytes": int(path.stat().st_size),
                    "sha256": sha256_file(path),
                    "upstream_read_only": not str(path).startswith(str(REPO_ROOT)),
                }
                for logical_name, path in input_paths.items()
            ],
            "absolute_paths_redacted": True,
        },
    )
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    _write_json(
        run_dir / "code_version.json",
        {
            "git_head": git_head,
            "dirty_worktree_not_embedded": True,
            "runner_sha256": sha256_file(Path(__file__)),
            "config_sha256": sha256_file(config_path),
        },
    )
    _write_json(run_dir / "output_contract.json", output_contract)


def _scenario_policy(config: dict[str, Any]) -> ScenarioPolicy:
    source = config["forecast_family_audit"]["scenario_policy"]
    return ScenarioPolicy(
        raw_count=int(source["raw_count"]),
        parent_count=int(source["parent_count"]),
        final_count=int(source["final_count"]),
        protected_tail_share=float(source["protected_tail_share"]),
        level_scales=tuple(float(value) for value in source["level_scales"]),
        random_seed=int(source["random_seed"]),
    )


def _source_paths(config: dict[str, Any], upstream_root: Path) -> dict[str, Path]:
    sources = config["forecast_family_audit"]["frozen_sources"]
    return {
        model_key: _resolve_upstream(upstream_root, source["path"])
        for model_key, source in sources.items()
    }


def _load_point_frames(config: dict[str, Any], upstream_root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Path]]:
    sources = config["forecast_family_audit"]["frozen_sources"]
    paths = _source_paths(config, upstream_root)
    frames: dict[str, pd.DataFrame] = {}
    for model_key, public_id in PUBLIC_MODEL_IDS.items():
        source = sources[model_key]
        frames[public_id] = normalise_frozen_point_source(
            paths[model_key],
            model_id=public_id,
            source_model=source.get("source_model"),
        )
    return frames, paths


def run_preflight(config_path: Path, config: dict[str, Any], upstream_root: Path) -> dict[str, Any]:
    frames, paths = _load_point_frames(config, upstream_root)
    timing_frames = []
    for model_id, frame in frames.items():
        checks = information_timing_checks(frame)
        checks.insert(0, "model_id", model_id)
        timing_frames.append(checks)
    timing = pd.concat(timing_frames, ignore_index=True)
    aligned, support = align_common_non_dst_support(frames)
    strict_test = aligned[STRICT_MODEL_ID][
        aligned[STRICT_MODEL_ID]["dataset_split"].eq("test")
    ]
    physical = config["steel_experiment"]["physical_prerequisite"]
    physical_gate = read_physical_prerequisite(
        _resolve_repo(physical["run_summary"]), _resolve_repo(physical["failures"])
    )
    return {
        "status": "pass" if timing["status"].eq("pass").all() else "fail",
        "input_count": len(paths),
        "timing_checks": timing.to_dict(orient="records"),
        "common_support": support.to_dict(orient="records"),
        "strict_test_origins": int(strict_test["forecast_origin_utc"].nunique()),
        "physical_prerequisite": physical_gate,
        "c1_split_horizon_prerequisite": config["steel_experiment"][
            "c1_split_horizon_prerequisite"
        ],
        "long_horizon_support": {
            "available": bool(config["steel_experiment"]["long_horizon_forecast_support"]["available"]),
            "policy": config["steel_experiment"]["long_horizon_forecast_support"]["policy"],
        },
        "family_audit_output_contract": config["outputs"]["family_audit"],
        "study_preparation_output_contract": config["outputs"]["study_preparation"],
    }


def run_family_audit(
    config_path: Path,
    config: dict[str, Any],
    upstream_root: Path,
    run_id: str,
    resume_run: bool = False,
) -> Path:
    started = time.perf_counter()
    frames, source_paths = _load_point_frames(config, upstream_root)
    output = config["outputs"]["family_audit"]
    run_dir = _resolve_repo(output["root"]) / run_id
    _write_standard_files(
        run_dir,
        config_path=config_path,
        config=config,
        input_paths=source_paths,
        output_contract=output,
        resume_run=resume_run,
    )
    timing_frames = []
    for model_id, frame in frames.items():
        checks = information_timing_checks(frame)
        checks.insert(0, "model_id", model_id)
        timing_frames.append(checks)
    timing = pd.concat(timing_frames, ignore_index=True)
    timing.to_csv(run_dir / "information_timing_checks.csv", index=False)
    if timing["status"].eq("fail").any():
        raise StudyContractError("one or more frozen models fail the D-1 timing contract")

    aligned, support = align_common_non_dst_support(frames)
    support.to_csv(run_dir / "common_support_summary.csv", index=False)
    common_points = pd.concat(aligned.values(), ignore_index=True)
    common_points.to_parquet(run_dir / "common_point_forecasts_with_actuals.parquet", index=False)
    # The official naive may use observed truth seven local days earlier even
    # when that earlier day is outside the three-model forecast intersection.
    truth = frames[STRICT_MODEL_ID][
        ["target_timestamp_utc", "actual_price"]
    ].drop_duplicates("target_timestamp_utc")
    point_table = pd.DataFrame([point_metrics(frame, truth) for frame in aligned.values()])
    point_table.to_csv(run_dir / "point_metrics.csv", index=False)

    policy = _scenario_policy(config)
    scenario_frames: list[pd.DataFrame] = []
    mapping_frames: list[pd.DataFrame] = []
    calibration_frames: list[pd.DataFrame] = []
    metric_frames: list[pd.DataFrame] = []
    check_frames: list[pd.DataFrame] = []
    strict_parent_scenarios: pd.DataFrame | None = None
    for model_id in (STRICT_MODEL_ID, PUBLIC_MODEL_IDS["lear_fs3"], PUBLIC_MODEL_IDS["xgboost_fs3"]):
        frame = aligned[model_id]
        blocks = build_hourly_residual_blocks(frame)
        scale, calibration = calibrate_hourly_level_scale(frame, blocks, policy)
        calibration.insert(0, "model_id", model_id)
        calibration_frames.append(calibration)
        scenarios, mapping, parent_scenarios = generate_hourly_nested_scenarios(
            frame, blocks, policy, level_scale=scale
        )
        if model_id == STRICT_MODEL_ID:
            strict_parent_scenarios = parent_scenarios
        scenario_frames.append(scenarios)
        mapping_frames.append(mapping)
        metric_frames.append(scenario_metrics(scenarios, frame))
        checks = validate_scenario_contract(scenarios, expected_count=policy.final_count)
        checks.insert(0, "model_id", model_id)
        check_frames.append(checks)

    scenarios = pd.concat(scenario_frames, ignore_index=True)
    mappings = pd.concat(mapping_frames, ignore_index=True)
    calibration = pd.concat(calibration_frames, ignore_index=True)
    metrics = pd.concat(metric_frames, ignore_index=True)
    checks = pd.concat(check_frames, ignore_index=True)
    scenarios.to_parquet(run_dir / "scenario_prices_long.parquet", index=False)
    if strict_parent_scenarios is None:
        raise StudyContractError("Strict S30 parent scenarios were not generated")
    strict_parent_scenarios.to_parquet(
        run_dir / "strict_scenario_prices_30.parquet", index=False
    )
    mappings.to_parquet(run_dir / "scenario_reduction_30_to_10.parquet", index=False)
    calibration.to_csv(run_dir / "scenario_calibration_validation_only.csv", index=False)
    metrics.to_csv(run_dir / "scenario_metrics.csv", index=False)
    checks.to_csv(run_dir / "scenario_contract_checks.csv", index=False)
    strict_ready = bool(
        timing[timing["model_id"].eq(STRICT_MODEL_ID)]["status"].eq("pass").all()
        and checks[checks["model_id"].eq(STRICT_MODEL_ID)]["status"].eq("pass").all()
    )
    summary = {
        "run_id": run_id,
        "status": "pass" if strict_ready and checks["status"].eq("pass").all() else "fail",
        "strict_main_experiment_ready": strict_ready,
        "selection_reopened": False,
        "model_ids": list(PUBLIC_MODEL_IDS.values()),
        "scenario_algorithm": "strict_coupled_residual_paths_raw400_to_s30_to_nested_s10",
        "scenario_rows": int(len(scenarios)),
        "strict_s30_scenario_rows": int(len(strict_parent_scenarios)),
        "common_point_rows": int(len(common_points)),
        "common_test_origins_per_model": int(
            aligned[STRICT_MODEL_ID].loc[aligned[STRICT_MODEL_ID]["dataset_split"].eq("test"), "forecast_origin_utc"].nunique()
        ),
        "runtime_seconds": float(time.perf_counter() - started),
        "output_policy": output["output_policy"],
        "run_class": output["run_class"],
        "lineage_role": output["lineage_role"],
    }
    _write_json(run_dir / "run_summary.json", summary)
    (run_dir / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The three frozen point models are not reselected on the test period.\n"
        "- Native 23/25-hour DST days are reported as support exclusions and are never interpolated.\n"
        "- S10 is obtained by a nested 30-to-10 probability-aware reduction; raw paths are not stored.\n"
        "- Scenario calibration uses validation outcomes only and is causal within validation.\n",
        encoding="utf-8",
    )
    return run_dir


def _complete_week_and_lookahead_days(strict_test: pd.DataFrame, start: str) -> bool:
    available = set(strict_test["delivery_date_local"].astype(str))
    start_date = pd.Timestamp(start).date()
    return all((start_date + timedelta(days=offset)).isoformat() in available for offset in range(11))


def run_study_preparation(
    config_path: Path,
    config: dict[str, Any],
    run_id: str,
) -> Path:
    started = time.perf_counter()
    family_run = _resolve_repo(config["forecast_family_audit"]["accepted_run_root"])
    required_family = [
        family_run / "common_point_forecasts_with_actuals.parquet",
        family_run / "scenario_prices_long.parquet",
        family_run / "strict_scenario_prices_30.parquet",
        family_run / "run_summary.json",
    ]
    for path in required_family:
        if not path.exists():
            raise FileNotFoundError(f"study preparation requires completed family audit artifact: {path}")
    family_summary = json.loads((family_run / "run_summary.json").read_text(encoding="utf-8"))
    if not family_summary.get("strict_main_experiment_ready"):
        raise StudyContractError("Strict failed the frozen family audit; automatic family fallback is forbidden")

    shape_root = _resolve_repo(config["shape_overlay"]["strict_qh_run_root"])
    shape_files = {
        "hourly_points": shape_root / "optimisation_inputs/hourly_point_forecasts.parquet",
        "quarterhour_points": shape_root / "optimisation_inputs/quarterhour_point_forecasts.parquet",
        "hourly_scenarios": shape_root / "optimisation_inputs/hourly_scenarios_10.parquet",
        "quarterhour_scenarios": shape_root / "optimisation_inputs/quarterhour_scenarios_10.parquet",
        "hourly_scenarios_30": shape_root / "optimisation_inputs/hourly_scenarios_30.parquet",
        "quarterhour_scenarios_30": shape_root / "optimisation_inputs/quarterhour_scenarios_30.parquet",
        "actuals": shape_root / "evaluation_actuals.parquet",
        "point_metrics": shape_root / "point_forecast_metrics.csv",
        "qh_improvement": shape_root / "qh_incremental_improvement.csv",
        "dm_test": shape_root / "diebold_mariano_test.csv",
        "scenario_metrics_summary": shape_root / "scenario_metrics_summary.csv",
    }
    for path in shape_files.values():
        if not path.exists():
            raise FileNotFoundError(path)

    output = config["outputs"]["study_preparation"]
    run_dir = _resolve_repo(output["root"]) / run_id
    input_paths = {
        "family_common_points": required_family[0],
        "family_scenarios": required_family[1],
        "family_strict_s30": required_family[2],
        "family_summary": required_family[3],
        **{f"shape_{name}": path for name, path in shape_files.items()},
    }
    physical = config["steel_experiment"]["physical_prerequisite"]
    input_paths["physical_run_summary"] = _resolve_repo(physical["run_summary"])
    input_paths["physical_failures"] = _resolve_repo(physical["failures"])
    _write_standard_files(
        run_dir,
        config_path=config_path,
        config=config,
        input_paths=input_paths,
        output_contract=output,
    )

    points = pd.read_parquet(required_family[0])
    scenarios = pd.read_parquet(required_family[1])
    strict_scenarios_30 = pd.read_parquet(required_family[2])
    strict_test = points[
        points["model_id"].eq(STRICT_MODEL_ID) & points["dataset_split"].eq("test")
    ].copy()
    features = compute_week_features(
        strict_test[["target_timestamp_utc", "actual_price"]].drop_duplicates()
    )
    date_policy = config["week_selection"]
    features = features[
        features["week_start"].between(date_policy["test_start"], date_policy["test_end"])
    ].copy()
    eligible = {
        week_start
        for week_start in features["week_start"].tolist()
        if _complete_week_and_lookahead_days(strict_test, week_start)
    }
    selected, regime_features = select_regime_weeks(
        features,
        eligible_week_starts=eligible,
        provisional=date_policy["provisional_candidates"],
        minimum_separation_days=int(date_policy["minimum_separation_days"]),
    )
    selected.to_csv(run_dir / "selected_regime_weeks.csv", index=False)
    regime_features.to_csv(run_dir / "regime_week_features.csv", index=False)

    shape_hourly_points = pd.read_parquet(shape_files["hourly_points"])
    shape_qh_points = pd.read_parquet(shape_files["quarterhour_points"])
    shape_hourly_scenarios_10 = pd.read_parquet(shape_files["hourly_scenarios"])
    shape_qh_scenarios_10 = pd.read_parquet(shape_files["quarterhour_scenarios"])
    shape_hourly_scenarios_30 = pd.read_parquet(shape_files["hourly_scenarios_30"])
    shape_qh_scenarios_30 = pd.read_parquet(shape_files["quarterhour_scenarios_30"])
    shape_actuals = pd.read_parquet(shape_files["actuals"])
    shape_library_10 = build_shape_library(
        shape_hourly_points,
        shape_qh_points,
        shape_hourly_scenarios_10,
        shape_qh_scenarios_10,
        shape_actuals,
    )
    shape_library_30 = build_shape_library(
        shape_hourly_points,
        shape_qh_points,
        shape_hourly_scenarios_30,
        shape_qh_scenarios_30,
        shape_actuals,
    )

    qh_actual = shape_actuals[shape_actuals["granularity"].eq("quarterhour")].copy()
    qh_actual["target_timestamp_utc"] = pd.to_datetime(
        qh_actual["target_timestamp_utc"], utc=True
    )
    qh_points_eval = shape_qh_points.merge(
        qh_actual[
            ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "actual_price"]
        ],
        on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        how="inner",
        validate="one_to_one",
    )
    qh_points_eval["dataset_split"] = "test"
    scenario_evidence: list[pd.DataFrame] = []
    for set_size, scenario_frame in (
        (10, shape_qh_scenarios_10),
        (30, shape_qh_scenarios_30),
    ):
        evidence = scenario_metrics(scenario_frame, qh_points_eval)
        evidence = evidence[evidence["forecast_origin_utc"].astype(str).eq("ALL")].copy()
        evidence.insert(1, "scenario_set_size", set_size)
        scenario_evidence.append(evidence)
    pd.concat(scenario_evidence, ignore_index=True).to_csv(
        run_dir / "observed_qh_scenario_validation.csv", index=False
    )

    qh_points_eval["hour_start_utc"] = qh_points_eval["target_timestamp_utc"].dt.floor("h")
    hourly_for_flat = shape_hourly_points.rename(
        columns={"target_timestamp_utc": "hour_start_utc", "point_forecast": "flat_forecast"}
    )
    point_eval = qh_points_eval.merge(
        hourly_for_flat[
            ["forecast_origin_utc", "hour_start_utc", "lead_day", "flat_forecast"]
        ],
        on=["forecast_origin_utc", "hour_start_utc", "lead_day"],
        how="inner",
        validate="many_to_one",
    ).rename(columns={"point_forecast": "shape_forecast"})
    qh_improvement = pd.read_csv(shape_files["qh_improvement"])
    overall_improvement = qh_improvement[
        qh_improvement["reporting_level"].eq("overall")
    ].iloc[0]
    proof_rows: list[dict[str, Any]] = []
    for label, forecast_column, suffix in (
        ("hourly_flat_repeat", "flat_forecast", "flat"),
        ("additive_mean_shape", "shape_forecast", "shape"),
    ):
        ramp_errors: list[float] = []
        for _, origin_rows in point_eval.groupby("forecast_origin_utc"):
            ordered = origin_rows.sort_values("target_timestamp_utc")
            ramp_errors.extend(
                np.abs(
                    np.diff(ordered[forecast_column].to_numpy(dtype=float))
                    - np.diff(ordered["actual_price"].to_numpy(dtype=float))
                ).tolist()
            )
        ranges = point_eval.groupby(
            ["forecast_origin_utc", "hour_start_utc"], as_index=False
        ).agg(
            forecast_range=(forecast_column, lambda values: float(values.max() - values.min())),
            actual_range=("actual_price", lambda values: float(values.max() - values.min())),
        )
        proof_rows.append(
            {
                "model": label,
                "mae": float(overall_improvement[f"mae_{suffix}"]),
                "rmse": float(overall_improvement[f"rmse_{suffix}"]),
                "bias": float(overall_improvement[f"bias_{suffix}"]),
                "rmae_vs_previous_week_naive": float(
                    overall_improvement[f"rmae_vs_official_naive_previous_week_{suffix}"]
                ),
                "ramp_mae": float(np.mean(ramp_errors)),
                "intra_hour_range_mae": float(
                    np.mean(np.abs(ranges["forecast_range"] - ranges["actual_range"]))
                ),
                "heldout_rows": int(len(point_eval)),
                "minimum_observed_qh_price": float(point_eval["actual_price"].min()),
                "observations_at_or_below_minus_499": int(
                    point_eval["actual_price"].le(-499.0).sum()
                ),
                "extreme_observations_included": True,
            }
        )
    pd.DataFrame(proof_rows).to_csv(
        run_dir / "observed_qh_shape_validation.csv", index=False
    )
    overlays: list[pd.DataFrame] = []
    overlay_manifests: list[dict[str, Any]] = []
    for _, week in selected.iterrows():
        week_days = pd.date_range(week["week_start"], week["week_end"], freq="D").date
        day_strings = {day.isoformat() for day in week_days}
        week_points = strict_test[strict_test["delivery_date_local"].isin(day_strings)].copy()
        week_scenarios = scenarios[
            scenarios["model_id"].eq(STRICT_MODEL_ID)
            & scenarios["delivery_date_local"].isin(day_strings)
        ].copy()
        week_actuals = week_points[
            ["target_timestamp_utc", "delivery_date_local", "actual_price"]
        ].drop_duplicates()
        overlay_10, manifest_10 = apply_counterfactual_shape_overlay(
            week_id=week["week_id"],
            hourly_points=week_points,
            hourly_scenarios=week_scenarios,
            hourly_actuals=week_actuals,
            shape_library=shape_library_10,
            random_seed=int(config["shape_overlay"]["random_seed"]),
        )
        week_scenarios_30 = strict_scenarios_30[
            strict_scenarios_30["model_id"].eq(STRICT_MODEL_ID)
            & strict_scenarios_30["delivery_date_local"].isin(day_strings)
        ].copy()
        overlay_30, manifest_30 = apply_counterfactual_shape_overlay(
            week_id=week["week_id"],
            hourly_points=week_points,
            hourly_scenarios=week_scenarios_30,
            hourly_actuals=week_actuals,
            shape_library=shape_library_30,
            random_seed=int(config["shape_overlay"]["random_seed"]),
        )
        overlay_30 = overlay_30[
            overlay_30["path_kind"].isin(["scenario_shape", "scenario_flat"])
        ].copy()
        overlays.extend([overlay_10, overlay_30])
        for scenario_count, manifest in ((10, manifest_10), (30, manifest_30)):
            manifest["scenario_set_size"] = scenario_count
            manifest["source_qh_run_id"] = shape_root.name
            manifest["source_qh_run_sha256"] = sha256_file(shape_root / "run_summary.json")
            overlay_manifests.append(manifest)
    combined_overlay = pd.concat(overlays, ignore_index=True)
    combined_overlay.to_parquet(run_dir / "counterfactual_qh_overlay.parquet", index=False)
    _write_json(run_dir / "counterfactual_overlay_manifest.json", overlay_manifests)

    physical_gate = read_physical_prerequisite(
        input_paths["physical_run_summary"], input_paths["physical_failures"]
    )
    long_horizon = bool(config["steel_experiment"]["long_horizon_forecast_support"]["available"])
    experiment_manifest, readiness = build_steel_experiment_manifest(
        selected,
        physical_prerequisite=physical_gate,
        long_horizon_support_available=long_horizon,
        scenario_30_support_available=True,
        c1_split_horizon_feasible=bool(
            config["steel_experiment"]["c1_split_horizon_prerequisite"]["available"]
        ),
    )
    experiment_manifest.to_csv(run_dir / "steel_experiment_manifest.csv", index=False)
    _write_json(run_dir / "steel_execution_readiness.json", readiness)
    h2_manifest = pd.DataFrame(
        [
            {
                "experiment_id": "observed_qh_full_support_statistical_validation",
                "evidence_type": "observed_quarterhour",
                "extreme_minus_500_included": True,
                "economic_run": False,
                "horizon_sweep": False,
                "scenario_count_sweep": False,
            },
            {
                "experiment_id": "observed_qh_preselected_non_extreme_h2_week",
                "evidence_type": "observed_quarterhour",
                "extreme_minus_500_included": False,
                "economic_run": True,
                "horizon_sweep": False,
                "scenario_count_sweep": False,
            },
            {
                "experiment_id": "counterfactual_typical_winter_h2_bridge",
                "evidence_type": "counterfactual_quarterhour",
                "extreme_minus_500_included": False,
                "economic_run": True,
                "horizon_sweep": False,
                "scenario_count_sweep": False,
            },
        ]
    )
    h2_manifest.to_csv(run_dir / "h2_mechanism_test_manifest.csv", index=False)
    summary = {
        "run_id": run_id,
        "status": {
            "blocked": "prepared_but_steel_execution_blocked",
            "partially_ready": "donly_split_horizon_ready_long_price_horizons_blocked",
            "ready": "ready",
        }[readiness["status"]],
        "selected_week_count": int(len(selected)),
        "overlay_rows": int(len(combined_overlay)),
        "steel_manifest_rows": int(len(experiment_manifest)),
        "physical_prerequisite_status": physical_gate["status"],
        "long_horizon_forecast_support_available": long_horizon,
        "economic_steel_runs_executed": 0,
        "runtime_seconds": float(time.perf_counter() - started),
        "output_policy": output["output_policy"],
        "run_class": output["run_class"],
        "lineage_role": output["lineage_role"],
    }
    _write_json(run_dir / "run_summary.json", summary)
    (run_dir / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- All 2024/25 quarter-hour paths are synthetic counterfactual overlays, not observed prices.\n"
        "- The four weeks are representative regime cases and are never annualised.\n"
        "- C1 is conditioned on a maintenance-free normal-operation week.\n"
        "- Shared-QH physical Gate A passed; a prior stochastic solve time limit remains a performance warning.\n"
        "- D-only economics use 24 hours of price information plus a 24-hour price-free physical feasibility tail.\n"
        "- The tail has no bid, clearing, execution, settlement, or future-price information.\n"
        "- Horizons above 24 hours remain blocked until a causally available Strict D+1...D+4 input is supplied.\n"
        "- mFRR, CVaR, ETS, export, product revenue, emergency import, and imbalance optimisation are absent.\n",
        encoding="utf-8",
    )
    return run_dir


def main() -> int:
    args = parse_args()
    config_path = _resolve_repo(args.config)
    config = load_study_config(config_path)
    upstream_root = args.upstream_root.resolve()
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if args.mode == "preflight":
        print(json.dumps(run_preflight(config_path, config, upstream_root), indent=2, default=str))
        return 0
    if args.mode == "family-audit":
        path = run_family_audit(
            config_path,
            config,
            upstream_root,
            run_id,
            resume_run=bool(args.resume_run),
        )
    else:
        path = run_study_preparation(config_path, config, run_id)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
