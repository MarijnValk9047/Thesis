from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .benchmarks import run_price_insensitive
from .bidding import dispatch_schedule_to_one_block_bid_curve
from .bidding_metrics import (
    compute_cvar_backtest_frontier_metrics,
    compute_cvar_sweep_summary,
    compute_realised_backtest_summary,
)
from .bidding_model import (
    TOY_BIDDING_STRATEGY,
    StochasticBiddingSolveResult,
    build_phase4a_toy_config,
    build_phase5a_toy_config,
    build_phase5b_toy_case_config,
    build_toy_hourly_scenario_set,
    solve_stochastic_hourly_bidding,
)
from .clearing import aggregate_cleared_energy, clear_hourly_bids
from .plots import (
    plot_actual_clearing_heatmap,
    plot_actual_storage_trajectories,
    plot_cvar_bid_firmness,
    plot_cvar_realised_profit_comparison,
    plot_cvar_risk_return_frontier,
    plot_cvar_scenario_profit_by_gamma,
    plot_cvar_sweep_diagnostics,
    plot_cvar_cleared_used_unused_by_gamma,
    plot_cleared_used_unused_electricity,
    plot_expected_vs_realised_profit_distribution,
    plot_real_scenario_fan_vs_actual,
    plot_realised_profit_comparison_bar,
    plot_suite_average_actual_price_paid_by_origin,
    plot_suite_clearing_ratio_by_origin,
    plot_suite_hydrogen_and_shortfall_by_origin,
    plot_suite_price_spread_vs_profit_delta,
    plot_suite_profit_delta_by_origin,
    plot_suite_realised_profit_by_origin,
    plot_submitted_bid_curves_with_actual_overlays,
    plot_submitted_cleared_rejected_energy,
)
from .optimisation_model import ModelStats, SolverResult
from .optimisation.runtime_profiling import RuntimeProfiler
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .redispatch import RedispatchSolveResult, solve_actual_redispatch_from_cleared_energy
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs
from .validation_checks import validate_scenario_table


@dataclass(frozen=True)
class ToyStochasticBacktestResult:
    optimisation_result: StochasticBiddingSolveResult
    actual_price_paths: pd.DataFrame
    actual_clearing: pd.DataFrame
    actual_clearing_by_hour: pd.DataFrame
    actual_redispatch_timeseries: pd.DataFrame
    actual_settlement_results: pd.DataFrame
    stochastic_vs_realised_summary: pd.DataFrame
    scenario_objective_summary: pd.DataFrame
    run_dir: Path | None


@dataclass(frozen=True)
class ToyCvarSweepResult:
    scenarios: pd.DataFrame
    actual_price_paths: pd.DataFrame
    sweep_summary: pd.DataFrame
    scenario_results: pd.DataFrame
    submitted_bids: pd.DataFrame
    scenario_clearing: pd.DataFrame
    scenario_dispatch: pd.DataFrame
    backtest_results: pd.DataFrame
    backtest_frontier: pd.DataFrame
    model_stats_by_gamma: pd.DataFrame
    run_dir: Path | None


@dataclass(frozen=True)
class RealScenarioBiddingDryRunResult:
    artifact_id: str
    forecast_origin_utc: pd.Timestamp
    delivery_day: str
    scenarios: pd.DataFrame
    actual_prices: pd.DataFrame
    optimisation_result: StochasticBiddingSolveResult
    actual_clearing: pd.DataFrame
    actual_clearing_by_hour: pd.DataFrame
    actual_redispatch_timeseries: pd.DataFrame
    actual_settlement_results: pd.DataFrame
    actual_redispatch_solver: SolverResult
    actual_redispatch_model_stats: ModelStats
    scenario_objective_summary: pd.DataFrame
    metrics_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    sanity_summary: pd.DataFrame
    benchmark_comparison: pd.DataFrame
    benchmark_clearing: pd.DataFrame
    benchmark_timeseries: pd.DataFrame
    input_manifest_payload: dict[str, Any]
    scenario_manifest_payload: dict[str, Any]
    model_stats_payload: dict[str, Any]
    runtime_profile: pd.DataFrame
    execution_audit: pd.DataFrame
    run_dir: Path | None


@dataclass(frozen=True)
class SelectedOriginSuiteResult:
    suite_dir: Path
    selected_origin_registry: pd.DataFrame
    metrics_by_origin: pd.DataFrame
    metrics_by_artifact_summary: pd.DataFrame
    benchmark_comparison_by_origin: pd.DataFrame
    validation_checks_all_origins: pd.DataFrame
    model_stats_by_origin: pd.DataFrame
    origin_run_dirs: pd.DataFrame


def build_phase4b_toy_backtest_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    experiment_name: str = "hydrogen_phase4b_toy_stochastic_bidding_backtest",
) -> HydrogenConfig:
    base = build_phase4a_toy_config(config_or_path, experiment_name=experiment_name)
    return replace(base, experiment=replace(base.experiment, name=experiment_name))


def build_toy_realised_actual_price_paths(
    *,
    toy_case: str = "mixed_clearing",
    forecast_origin_utc: str = "2024-12-31T07:00:00Z",
) -> pd.DataFrame:
    forecast_origin = pd.Timestamp(pd.to_datetime(forecast_origin_utc, utc=True, errors="raise"))
    path_map_by_case = {
        "mixed_clearing": {
            "realised_low": [60.0, 80.0, 100.0, 125.0],
            "realised_medium": [145.0, 170.0, 205.0, 245.0],
            "realised_high": [240.0, 270.0, 305.0, 330.0],
        },
        "cvar_stress": {
            "realised_low": [60.0, 80.0, 100.0, 125.0],
            "realised_medium": [145.0, 170.0, 205.0, 245.0],
            "realised_high": [240.0, 270.0, 305.0, 330.0],
        },
        "cvar_high_price_exposure": {
            "realised_low": [70.0, 70.0, 70.0, 70.0, 70.0, 70.0],
            "realised_medium": [70.0, 70.0, 70.0, 70.0, 180.0, 180.0],
            "realised_high": [70.0, 70.0, 70.0, 70.0, 400.0, 800.0],
        },
        "cvar_overprocurement_unused_energy": {
            "realised_low": [60.0, 60.0, 60.0, 60.0],
            "realised_medium": [500.0, 60.0, 60.0, 60.0],
            "realised_high": [500.0, 240.0, 500.0, 500.0],
        },
    }
    path_map = path_map_by_case.get(toy_case)
    if path_map is None:
        raise ValueError(f"Unsupported toy_case for realised actual paths: {toy_case!r}")
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=len(next(iter(path_map.values()))), freq="h", tz="UTC")
    rows: list[dict[str, Any]] = []
    for actual_path_id, prices in path_map.items():
        for timestamp, price in zip(timestamps, prices, strict=True):
            rows.append(
                {
                    "actual_path_id": actual_path_id,
                    "forecast_origin_utc": forecast_origin,
                    "delivery_start_utc": pd.Timestamp(timestamp),
                    "actual_price_eur_per_mwh": float(price),
                    "granularity": "hourly",
                    "horizon": "D_only",
                    "toy_source": "artificial_phase4b_actual_path",
                }
            )
    return pd.DataFrame(rows)


def _build_input_manifest(
    *,
    toy_case: str,
    bid_price_grid_eur_per_mwh: list[float],
    actual_price_paths: pd.DataFrame,
) -> dict[str, Any]:
    return {
        "scenario_source": "artificial_phase4a_toy",
        "actual_price_source": "artificial_phase4b_actual_paths",
        "toy_case": toy_case,
        "bid_price_grid_eur_per_mwh": list(bid_price_grid_eur_per_mwh),
        "actual_paths": {
            path_id: group[["delivery_start_utc", "actual_price_eur_per_mwh"]].to_dict(orient="records")
            for path_id, group in actual_price_paths.groupby("actual_path_id", sort=True)
        },
        "known_limitations": [
            "toy_scenarios_only",
            "toy_actual_price_paths_only",
            "hourly_only",
            "single_delivery_day_only",
            "no_real_thesis_grade_scenarios",
        ],
    }


def _build_scenario_objective_summary(optimisation_result: StochasticBiddingSolveResult) -> pd.DataFrame:
    summary_row = optimisation_result.summary.iloc[0]
    frame = optimisation_result.scenario_economics.copy()
    frame["objective_with_regularisation"] = float(summary_row["objective_with_regularisation"])
    frame["expected_adjusted_profit_without_regularisation"] = float(summary_row["expected_adjusted_profit_without_regularisation"])
    frame["regularisation_term"] = float(summary_row["regularisation_term"])
    frame["regularisation_weight"] = float(summary_row["regularisation_weight"])
    return frame


def _load_catalog_payload(config: HydrogenConfig) -> dict[str, Any]:
    payload = yaml.safe_load(config.models.scenario_catalog.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid scenario catalog payload: {config.models.scenario_catalog}")
    return payload


def _load_artifact_manifest(artifact_path: Path) -> dict[str, Any]:
    manifest_path = artifact_path.parent / "scenario_export_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _build_phase6c_suite_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    output_root: Path | None,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    config = replace(
        base,
        experiment=replace(
            base.experiment,
            name="hydrogen_phase6c_selected_origins_suite",
            execution_mode="selected_origins_integration_dry_run",
        ),
        strategies=("stochastic_risk_neutral",),
    )
    if output_root is not None:
        config = replace(config, outputs=replace(config.outputs, root=Path(output_root)))
    return config


def _origin_diagnostics_for_artifact(
    *,
    config: HydrogenConfig,
    artifact_id: str,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    catalog_payload = _load_catalog_payload(config)
    artifact_map = catalog_payload.get("artifacts", {})
    if artifact_id not in artifact_map:
        raise KeyError(f"Artifact '{artifact_id}' not present in scenario catalog.")
    artifact_entry = artifact_map[artifact_id]
    artifact_config = replace(config, models=replace(config.models, include=(str(artifact_id),)))
    specs = resolve_artifact_specs(artifact_config)
    if len(specs) != 1:
        raise ValueError(f"Expected exactly one artifact spec for '{artifact_id}', got {len(specs)}.")
    spec = specs[0]
    artifact_manifest = _load_artifact_manifest(spec.path)
    scenarios, _ = load_scenarios_for_artifact(spec, config=artifact_config)
    frame = scenarios.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    probability = (
        frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
    )
    actual = (
        frame.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_day=("delivery_day", "first"),
            actual_price_mean=("actual_price_eur_per_mwh", "mean"),
            actual_price_min=("actual_price_eur_per_mwh", "min"),
            actual_price_max=("actual_price_eur_per_mwh", "max"),
            actual_price_peak=("actual_price_eur_per_mwh", "max"),
            actual_price_count=("delivery_start_utc", "nunique"),
            missing_actual_rows=("actual_price_eur_per_mwh", lambda s: int(s.isna().sum())),
            duplicate_row_count=("scenario_id", lambda s: 0),
        )
    )
    duplicate = (
        frame.duplicated(subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"], keep=False)
        .groupby(frame["forecast_origin_utc"])
        .sum()
        .rename("duplicate_row_count")
        .reset_index()
    )
    registry = actual.merge(probability, on="forecast_origin_utc", how="inner").merge(duplicate, on="forecast_origin_utc", how="left", suffixes=("", "_dup"))
    registry["duplicate_row_count"] = registry["duplicate_row_count_dup"].fillna(registry["duplicate_row_count"]).fillna(0).astype(int)
    if "duplicate_row_count_dup" in registry.columns:
        registry = registry.drop(columns=["duplicate_row_count_dup"])
    registry["actual_price_spread"] = registry["actual_price_max"].astype(float) - registry["actual_price_min"].astype(float)
    registry["thesis_grade"] = bool(artifact_manifest.get("thesis_grade", artifact_entry.get("thesis_grade", True)))
    registry["forecast_origin_reconstructed"] = bool(artifact_manifest.get("forecast_origin_reconstructed", False))
    registry["artifact_id"] = artifact_id
    candidate_counts = registry.loc[
        (registry["actual_price_count"].astype(int) == 24)
        & (registry["missing_actual_rows"].astype(int) == 0)
        & (registry["duplicate_row_count"].astype(int) == 0)
        & (registry["probability_sum"].astype(float).between(0.999999, 1.000001)),
        "scenario_count",
    ].astype(int)
    expected_scenario_count = int(candidate_counts.mode().iloc[0]) if not candidate_counts.empty else 0
    valid = registry.loc[
        (registry["scenario_count"].astype(int) == expected_scenario_count)
        & (registry["actual_price_count"].astype(int) == 24)
        & (registry["missing_actual_rows"].astype(int) == 0)
        & (registry["duplicate_row_count"].astype(int) == 0)
        & (registry["probability_sum"].astype(float).between(0.999999, 1.000001))
    ].copy()
    return valid.sort_values("forecast_origin_utc").reset_index(drop=True), artifact_entry, artifact_manifest


def _pick_origin_by_reason(
    registry: pd.DataFrame,
    *,
    reason: str,
    chosen: set[pd.Timestamp],
) -> dict[str, Any] | None:
    candidates = registry.loc[~registry["forecast_origin_utc"].isin(list(chosen))].copy()
    if candidates.empty:
        return None
    if reason == "lowest_average_actual_price_day":
        row = candidates.sort_values(["actual_price_mean", "forecast_origin_utc"]).iloc[0]
    elif reason == "median_average_actual_price_day":
        target = float(registry["actual_price_mean"].median())
        candidates["distance"] = (candidates["actual_price_mean"].astype(float) - target).abs()
        row = candidates.sort_values(["distance", "forecast_origin_utc"]).iloc[0]
    elif reason == "highest_average_actual_price_day":
        row = candidates.sort_values(["actual_price_mean", "forecast_origin_utc"], ascending=[False, True]).iloc[0]
    elif reason == "highest_realised_daily_price_spread_day":
        row = candidates.sort_values(["actual_price_spread", "forecast_origin_utc"], ascending=[False, True]).iloc[0]
    elif reason == "highest_actual_peak_price_day":
        row = candidates.sort_values(["actual_price_peak", "forecast_origin_utc"], ascending=[False, True]).iloc[0]
    else:
        raise ValueError(f"Unsupported selection reason: {reason}")
    return {
        "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]),
        "delivery_day": str(row["delivery_day"]),
        "selection_reason": reason,
        "actual_price_mean": float(row["actual_price_mean"]),
        "actual_price_min": float(row["actual_price_min"]),
        "actual_price_max": float(row["actual_price_max"]),
        "actual_price_spread": float(row["actual_price_spread"]),
        "scenario_count": int(row["scenario_count"]),
        "probability_sum": float(row["probability_sum"]),
        "thesis_grade": bool(row["thesis_grade"]),
        "forecast_origin_reconstructed": bool(row["forecast_origin_reconstructed"]),
    }


def select_real_scenario_origins_for_artifact(
    *,
    config: HydrogenConfig | str | Path,
    artifact_id: str,
    max_origins_per_artifact: int = 5,
    selection_method: str = "price_diagnostics",
) -> pd.DataFrame:
    if str(selection_method) != "price_diagnostics":
        raise ValueError(f"Unsupported selection_method={selection_method!r}.")
    run_config = _build_phase6c_suite_config(config, output_root=None)
    registry, _, _ = _origin_diagnostics_for_artifact(config=run_config, artifact_id=artifact_id)
    if registry.empty:
        raise ValueError(f"No valid 24-hour origins found for artifact '{artifact_id}'.")
    ordered_reasons = [
        "lowest_average_actual_price_day",
        "median_average_actual_price_day",
        "highest_average_actual_price_day",
        "highest_realised_daily_price_spread_day",
        "highest_actual_peak_price_day",
    ]
    max_count = max(3, min(int(max_origins_per_artifact), len(ordered_reasons)))
    chosen: set[pd.Timestamp] = set()
    rows: list[dict[str, Any]] = []
    for reason in ordered_reasons:
        if len(rows) >= max_count:
            break
        picked = _pick_origin_by_reason(registry, reason=reason, chosen=chosen)
        if picked is None:
            continue
        chosen.add(picked["forecast_origin_utc"])
        rows.append({"artifact_id": artifact_id, **picked})
    return pd.DataFrame(rows).sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)


def _build_phase6b_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
    output_root: Path | None,
    strategy_name: str,
    dry_run_label: str,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    config = replace(
        base,
        experiment=replace(
            base.experiment,
            name="hydrogen_phase6b_real_dry_run",
            execution_mode="custom_day_integration_dry_run",
        ),
        models=replace(base.models, include=(str(artifact_id),)),
        strategies=("stochastic_risk_neutral",),
    )
    if output_root is not None:
        config = replace(config, outputs=replace(config.outputs, root=Path(output_root)))
    return config


def _select_complete_forecast_origin(
    scenarios: pd.DataFrame,
    *,
    explicit_forecast_origin_utc: str | None,
    expected_scenario_count: int | None = None,
) -> tuple[pd.Timestamp, pd.DataFrame]:
    frame = scenarios.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    if explicit_forecast_origin_utc is not None:
        target = pd.Timestamp(pd.to_datetime(explicit_forecast_origin_utc, utc=True, errors="raise"))
        selected = frame.loc[frame["forecast_origin_utc"] == target].copy()
        if selected.empty:
            raise ValueError(f"Requested forecast_origin_utc not present in artifact: {target}")
        return target, selected.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)

    scenario_meta = (
        frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
    )
    hourly_meta = (
        frame.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_hour_count=("delivery_start_utc", "nunique"),
            missing_actual_rows=("actual_price_eur_per_mwh", lambda s: int(s.isna().sum())),
        )
    )
    merged = scenario_meta.merge(hourly_meta, on="forecast_origin_utc", how="inner").sort_values("forecast_origin_utc")
    complete = merged.loc[
        (merged["delivery_hour_count"].astype(int) == 24)
        & (merged["missing_actual_rows"].astype(int) == 0)
        & (merged["probability_sum"].astype(float).between(0.999999, 1.000001))
    ].copy()
    if expected_scenario_count is None:
        if complete.empty:
            raise ValueError("No complete 24-hour forecast origin with valid actual prices and probability mass was found.")
        expected_scenario_count = int(complete["scenario_count"].astype(int).mode().iloc[0])
    candidates = complete.loc[complete["scenario_count"].astype(int) == int(expected_scenario_count)].copy()
    if candidates.empty:
        raise ValueError(
            "No complete 24-hour forecast origin with the expected scenario count and valid actual prices was found. "
            f"expected_scenario_count={int(expected_scenario_count)}"
        )
    chosen = pd.Timestamp(candidates.iloc[0]["forecast_origin_utc"])
    selected = frame.loc[frame["forecast_origin_utc"] == chosen].copy()
    return chosen, selected.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)


def _build_real_dry_run_validation_checks(
    *,
    artifact_id: str,
    artifact_path: Path,
    catalog_entry: dict[str, Any],
    artifact_manifest: dict[str, Any],
    selected_scenarios: pd.DataFrame,
    actual_prices: pd.DataFrame,
    optimisation_result: StochasticBiddingSolveResult,
    actual_clearing: pd.DataFrame,
    actual_clearing_by_hour: pd.DataFrame,
    redispatch: RedispatchSolveResult,
    benchmark_comparison: pd.DataFrame,
    benchmark_clearing: pd.DataFrame,
    expected_scenario_count: int,
    validation_mode: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(check_name: str, status: str, severity: str, details: str) -> None:
        rows.append(
            {
                "check_name": str(check_name),
                "status": str(status),
                "severity": str(severity),
                "details": str(details),
            }
        )

    add("artifact_exists", "pass" if artifact_path.exists() else "fail", "hard_fail", str(artifact_path))
    validation_mode = str(catalog_entry.get("validation_mode", "unknown"))
    add(
        "artifact_validation_mode_matches_catalog",
        "pass",
        "informational",
        f"artifact_id={artifact_id}, validation_mode={validation_mode}",
    )
    validation_status = str(artifact_manifest.get("validation_status", catalog_entry.get("validation_status", "unknown")))
    add(
        "integration_candidate_warning",
        "warn" if validation_status == "integration_candidate" else "pass",
        "smoke_warning",
        f"validation_status={validation_status}",
    )
    reconstructed = bool(artifact_manifest.get("forecast_origin_reconstructed", False))
    add(
        "forecast_origin_reconstructed_warning",
        "warn" if reconstructed else "pass",
        "smoke_warning",
        (
            "forecast_origin_utc reconstructed upstream via D-1 08:00 Europe/Amsterdam converted to UTC"
            if reconstructed
            else "forecast_origin_utc stored explicitly in source artifact"
        ),
    )

    thesis_grade = bool(artifact_manifest.get("thesis_grade", catalog_entry.get("thesis_grade", True)))
    add(
        "artifact_not_thesis_grade",
        "warn" if not thesis_grade else "pass",
        "smoke_warning" if not thesis_grade else "informational",
        f"thesis_grade={thesis_grade}",
    )

    rows.extend(validate_scenario_table(selected_scenarios))

    unique_hours = int(selected_scenarios["delivery_start_utc"].nunique())
    unique_scenarios = int(selected_scenarios["scenario_id"].astype(str).nunique())
    probability_sum = float(
        selected_scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])["scenario_probability"]
        .astype(float)
        .sum()
    )
    forecast_origin_count = int(selected_scenarios["forecast_origin_utc"].nunique())
    actual_price_count = int(actual_prices["delivery_start_utc"].nunique())
    missing_actual_count = int(actual_prices["actual_price_eur_per_mwh"].isna().sum())
    add(
        "selected_origin_complete_24_hour_d_only",
        "pass" if unique_hours == 24 else "fail",
        "hard_fail",
        f"delivery_hour_count={unique_hours}, scenario_count={unique_scenarios}",
    )
    add(
        "selected_origin_has_exactly_one_scenario_set",
        "pass" if forecast_origin_count == 1 else "fail",
        "hard_fail",
        f"forecast_origin_count={forecast_origin_count}",
    )
    add(
        "selected_origin_scenario_count_matches_expected",
        "pass" if unique_scenarios == int(expected_scenario_count) else "fail",
        "hard_fail",
        f"scenario_count={unique_scenarios}, expected_scenario_count={int(expected_scenario_count)}",
    )
    add(
        "selected_origin_probability_mass_equals_one",
        "pass" if abs(probability_sum - 1.0) <= 1e-6 else "fail",
        "hard_fail",
        f"probability_sum={probability_sum:.12f}",
    )
    add(
        "actual_prices_complete_for_24_hours",
        "pass" if actual_price_count == 24 and missing_actual_count == 0 else "fail",
        "hard_fail",
        f"actual_price_count={actual_price_count}, missing_actual_count={missing_actual_count}",
    )

    submitted = optimisation_result.submitted_bids.copy()
    add(
        "submitted_bids_has_no_scenario_id",
        "pass" if "scenario_id" not in submitted.columns else "fail",
        "hard_fail",
        f"columns={list(submitted.columns)}",
    )
    q_unique = submitted.groupby(["delivery_start_utc", "bid_block"], as_index=False)["bid_quantity_mw"].nunique()
    add(
        "q_nonanticipative_single_bid_curve",
        "pass" if int(q_unique["bid_quantity_mw"].max()) <= 1 else "fail",
        "hard_fail",
        f"max_distinct_quantities_per_hour_block={int(q_unique['bid_quantity_mw'].max())}",
    )

    acceptance_ok = bool(
        (actual_clearing["accepted"].astype(bool))
        .eq(actual_clearing["bid_price_eur_per_mwh"].astype(float) >= actual_clearing["actual_price_eur_per_mwh"].astype(float))
        .all()
    )
    add(
        "actual_clearing_acceptance_rule_bid_ge_actual",
        "pass" if acceptance_ok else "fail",
        "hard_fail",
        "accepted == (bid_price_eur_per_mwh >= actual_price_eur_per_mwh)",
    )

    expected_settlement = float(
        (actual_clearing_by_hour["actual_price_eur_per_mwh"].astype(float) * actual_clearing_by_hour["cleared_energy_mwh"].astype(float)).sum()
    )
    realised_settlement = float(redispatch.summary["realised_DA_settlement_cost_eur"].iloc[0])
    add(
        "actual_settlement_uses_actual_price_not_bid_price",
        "pass" if abs(expected_settlement - realised_settlement) <= 1e-6 else "fail",
        "hard_fail",
        f"expected={expected_settlement:.6f}, realised={realised_settlement:.6f}",
    )
    add(
        "pay_as_cleared_settlement",
        "pass" if abs(expected_settlement - realised_settlement) <= 1e-6 else "fail",
        "hard_fail",
        "realised settlement cost equals sum(actual_price * cleared_energy)",
    )

    balance_error = float(
        (
            redispatch.timeseries["used_energy_mwh"].astype(float)
            + redispatch.timeseries["unused_cleared_energy_mwh"].astype(float)
            - redispatch.timeseries["cleared_energy_mwh"].astype(float)
            - pd.to_numeric(pd.Series(redispatch.timeseries.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0).astype(float)
        )
        .abs()
        .max()
    )
    add(
        "used_plus_unused_equals_cleared",
        "pass" if balance_error <= 1e-6 else "fail",
        "hard_fail",
        f"max_abs_error={balance_error:.6f}",
    )
    if "emergency_import_cost_eur" in redispatch.summary.columns:
        emergency_import_mwh = float(redispatch.summary["emergency_import_mwh"].iloc[0])
        emergency_import_cost = float(redispatch.summary["emergency_import_cost_eur"].iloc[0])
        add(
            "emergency_import_nonnegative",
            "pass" if emergency_import_mwh >= -1e-9 and emergency_import_cost >= -1e-9 else "fail",
            "hard_fail",
            f"emergency_import_mwh={emergency_import_mwh:.6f}, emergency_import_cost_eur={emergency_import_cost:.6f}",
        )
    add(
        "above_target_hydrogen_reported_separately",
        "pass" if "hydrogen_above_target_kg" in redispatch.summary.columns else "fail",
        "hard_fail",
        "hydrogen_above_target_kg column present in realised summary",
    )
    add(
        "no_production_cap_introduced",
        "pass",
        "informational",
        "No upper cap on hydrogen sold/produced was added in this integration dry run.",
    )
    if not benchmark_comparison.empty and not benchmark_clearing.empty:
        benchmark_same_day = bool(
            pd.to_datetime(benchmark_clearing["delivery_start_utc"], utc=True, errors="raise")
            .sort_values()
            .reset_index(drop=True)
            .equals(pd.to_datetime(actual_prices["delivery_start_utc"], utc=True, errors="raise").sort_values().reset_index(drop=True))
        )
        benchmark_same_prices = bool(
            pd.Series(benchmark_clearing.groupby("delivery_start_utc", as_index=False)["actual_price_eur_per_mwh"].first().sort_values("delivery_start_utc")["actual_price_eur_per_mwh"].to_list())
            .equals(pd.Series(actual_prices.sort_values("delivery_start_utc")["actual_price_eur_per_mwh"].astype(float).to_list()))
        )
        add(
            "benchmark_same_day_alignment",
            "pass" if benchmark_same_day else "fail",
            "hard_fail",
            f"same_delivery_timestamps={benchmark_same_day}",
        )
        add(
            "benchmark_same_actual_prices",
            "pass" if benchmark_same_prices else "fail",
            "hard_fail",
            f"same_actual_prices={benchmark_same_prices}",
        )
    if not redispatch.validation_checks.empty:
        for row in redispatch.validation_checks.to_dict(orient="records"):
            rows.append(
                {
                    "check_name": f"redispatch.{row['check_name']}",
                    "status": row["status"],
                    "severity": row["severity"],
                    "details": row["details"],
                }
            )
    return pd.DataFrame(rows)


def _build_real_sanity_summary(
    *,
    artifact_id: str,
    forecast_origin_utc: pd.Timestamp,
    delivery_day: str,
    scenario_count: int,
    probability_sum: float,
    metrics_summary: pd.DataFrame,
    validation_checks: pd.DataFrame,
    thesis_grade: bool,
) -> pd.DataFrame:
    metric_row = metrics_summary.iloc[0]
    fail_count = int((validation_checks["status"].astype(str) == "fail").sum())
    validation_status = "fail" if fail_count > 0 else "warn" if (validation_checks["status"].astype(str) == "warn").any() else "pass"
    benchmark_profit = float(metric_row["benchmark_realised_adjusted_profit_eur"]) if "benchmark_realised_adjusted_profit_eur" in metric_row.index else float("nan")
    realised_profit = float(metric_row["realised_adjusted_profit_eur"])
    return pd.DataFrame(
        [
            {
                "artifact_id": artifact_id,
                "forecast_origin_utc": forecast_origin_utc,
                "delivery_day": delivery_day,
                "scenario_count": int(scenario_count),
                "probability_sum": float(probability_sum),
                "submitted_energy_mwh": float(metric_row["submitted_energy_mwh"]),
                "cleared_energy_mwh": float(metric_row["cleared_energy_mwh"]),
                "rejected_energy_mwh": float(metric_row["rejected_energy_mwh"]),
                "used_energy_mwh": float(metric_row["used_energy_mwh"]),
                "unused_energy_mwh": float(metric_row["unused_cleared_energy_mwh"]),
                "realised_profit": realised_profit,
                "benchmark_profit": benchmark_profit,
                "stochastic_minus_benchmark_profit": realised_profit - benchmark_profit if pd.notna(benchmark_profit) else float("nan"),
                "validation_status": validation_status,
                "thesis_grade": bool(thesis_grade),
            }
        ]
    )


def _build_real_metrics_summary(
    *,
    artifact_id: str,
    delivery_day: str,
    forecast_origin_utc: pd.Timestamp,
    optimisation_result: StochasticBiddingSolveResult,
    actual_clearing_by_hour: pd.DataFrame,
    redispatch: RedispatchSolveResult,
    benchmark_comparison: pd.DataFrame,
) -> pd.DataFrame:
    summary_row = optimisation_result.summary.iloc[0]
    actual_row = redispatch.summary.iloc[0]
    submitted_energy = float(actual_clearing_by_hour["submitted_energy_mwh"].sum())
    cleared_energy = float(actual_clearing_by_hour["cleared_energy_mwh"].sum())
    rejected_energy = float(actual_clearing_by_hour["rejected_energy_mwh"].sum())
    price_weighted_avg = float(
        (actual_clearing_by_hour["actual_price_eur_per_mwh"].astype(float) * actual_clearing_by_hour["cleared_energy_mwh"].astype(float)).sum()
        / cleared_energy
    ) if cleared_energy > 0.0 else float("nan")
    payload = {
        "artifact_id": artifact_id,
        "forecast_origin_utc": forecast_origin_utc,
        "delivery_day": delivery_day,
        "risk_measure": str(summary_row["risk_measure"]),
        "cvar_alpha": float(summary_row["cvar_alpha"]),
        "cvar_gamma": float(summary_row["cvar_gamma"]),
        "expected_adjusted_profit_eur": float(summary_row["expected_adjusted_profit_without_regularisation"]),
        "worst_scenario_profit_eur": float(summary_row["worst_scenario_profit"]),
        "worst_scenario_loss_eur": float(summary_row["worst_scenario_loss"]),
        "var_loss_eur": float(summary_row["VaR_loss_zeta"]),
        "cvar_loss_eur": float(summary_row["CVaR_loss"]),
        "downside_tail_loss_mean_eur": float(summary_row["downside_tail_loss_mean"]),
        "submitted_energy_mwh": submitted_energy,
        "cleared_energy_mwh": cleared_energy,
        "rejected_energy_mwh": rejected_energy,
        "clearing_ratio": float(cleared_energy / submitted_energy) if submitted_energy > 0.0 else 0.0,
        "used_energy_mwh": float(actual_row["used_energy_mwh"]),
        "unused_cleared_energy_mwh": float(actual_row["unused_cleared_energy_mwh"]),
        "emergency_import_mwh": float(actual_row.get("emergency_import_mwh", 0.0)),
        "emergency_import_cost_eur": float(actual_row.get("emergency_import_cost_eur", 0.0)),
        "unused_energy_penalty_eur": float(actual_row["unused_energy_penalty_eur"]),
        "realised_DA_settlement_cost_eur": float(actual_row["realised_DA_settlement_cost_eur"]),
        "hydrogen_sold_or_compressed_kg": float(actual_row["hydrogen_compressed_or_sold_kg"]),
        "hydrogen_above_target_kg": float(actual_row["hydrogen_above_target_kg"]),
        "target_fulfilment_ratio_capped_for_reliability": float(actual_row["target_fulfilment_ratio_capped_for_reliability"]),
        "production_to_target_ratio_uncapped": float(actual_row["production_to_target_ratio_uncapped"]),
        "shortfall_kg": float(actual_row["shortfall_kg"]),
        "terminal_inventory_change_kg": float(actual_row["terminal_inventory_change_kg"]),
        "terminal_inventory_correction_eur": float(actual_row["terminal_inventory_correction_eur"]),
        "realised_adjusted_profit_eur": float(actual_row["realised_adjusted_profit_eur"]),
        "weighted_average_actual_price_paid_for_cleared_energy": price_weighted_avg,
        "zero_clearing_hours": int((actual_clearing_by_hour["cleared_energy_mwh"].astype(float) <= 1e-9).sum()),
        "partial_clearing_hours": int(
            ((actual_clearing_by_hour["clearing_ratio"].astype(float) > 1e-9) & (actual_clearing_by_hour["clearing_ratio"].astype(float) < 1.0 - 1e-9)).sum()
        ),
        "objective_with_regularisation": float(summary_row["objective_with_regularisation"]),
        "regularisation_term": float(summary_row["regularisation_term"]),
        "regularisation_weight": float(summary_row["regularisation_weight"]),
        "solver_status": summary_row["solver_status"],
        "solve_time_seconds": float(summary_row["solve_time_seconds"]),
        "objective_without_regularisation": float(summary_row["objective_without_regularisation"]),
    }
    if not benchmark_comparison.empty:
        benchmark_row = benchmark_comparison.iloc[0]
        payload.update(
            {
                "benchmark_realised_adjusted_profit_eur": float(benchmark_row["realised_adjusted_profit_eur"]),
                "benchmark_hydrogen_sold_kg": float(benchmark_row["hydrogen_compressed_or_sold_kg"]),
                "benchmark_hydrogen_above_target_kg": float(benchmark_row["hydrogen_above_target_kg"]),
                "benchmark_cleared_energy_mwh": float(benchmark_row["cleared_energy_mwh"]),
                "benchmark_average_actual_price_paid_eur_per_mwh": float(benchmark_row["weighted_average_actual_price_paid_for_cleared_energy"]),
                "benchmark_shortfall_kg": float(benchmark_row["shortfall_kg"]),
                "benchmark_terminal_inventory_correction_eur": float(benchmark_row["terminal_inventory_correction_eur"]),
            }
        )
    return pd.DataFrame([payload])


def _run_price_insensitive_badarinath_style_comparison(
    *,
    day_frame: pd.DataFrame,
    actual_prices: pd.DataFrame,
    config: HydrogenConfig,
    run_id: str,
    model_id: str,
    forecast_origin_utc: pd.Timestamp,
    solver_log_root: Path | None,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    benchmark = run_price_insensitive(
        day_frame=day_frame,
        config=config,
        inventory_start_kg=float(config.hydrogen_system.storage_initial_kg),
        reserve_kg=float(config.hydrogen_system.reserve_kg),
        apply_terminal_value=True,
        terminal_reference_start_kg=float(config.hydrogen_system.storage_initial_kg),
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=str(solver_log_root / "bench_solver_log.txt") if solver_log_root is not None and config.outputs.save_solver_log else None,
    )
    benchmark_dispatch = benchmark.dispatch.copy()
    benchmark_dispatch["forecast_origin_utc"] = forecast_origin_utc
    benchmark_dispatch["scenario_model"] = model_id
    benchmark_bids = dispatch_schedule_to_one_block_bid_curve(
        benchmark_dispatch,
        run_id=f"{run_id}__price_insensitive",
        source_strategy="price_insensitive",
        bridge_strategy="price_insensitive_plan_first_market_cap",
        bid_price_eur_per_mwh=float(config.bidding.price_insensitive_bid_price_eur_per_mwh),
        scenario_model=model_id,
        forecast_origin_utc=forecast_origin_utc,
    )
    benchmark_clearing = clear_hourly_bids(benchmark_bids, actual_prices)
    benchmark_clearing_by_hour = aggregate_cleared_energy(benchmark_clearing)
    benchmark_clearing_by_hour["redispatch_case"] = "historical_actual_da"
    benchmark_clearing_by_hour["timestep_hours"] = float(config.delta_t_hours)
    benchmark_redispatch = solve_actual_redispatch_from_cleared_energy(
        benchmark_clearing_by_hour,
        config=config,
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        solver_log_path=solver_log_root / "bench_redisp_log.txt" if solver_log_root is not None and config.outputs.save_solver_log else None,
    )
    benchmark_summary = benchmark_redispatch.summary.copy()
    benchmark_summary["submitted_energy_mwh"] = float(benchmark_clearing_by_hour["submitted_energy_mwh"].sum())
    benchmark_summary["cleared_energy_mwh"] = float(benchmark_clearing_by_hour["cleared_energy_mwh"].sum())
    benchmark_summary["weighted_average_actual_price_paid_for_cleared_energy"] = (
        float(
            (benchmark_clearing_by_hour["actual_price_eur_per_mwh"].astype(float) * benchmark_clearing_by_hour["cleared_energy_mwh"].astype(float)).sum()
            / benchmark_summary["cleared_energy_mwh"].iloc[0]
        )
        if float(benchmark_summary["cleared_energy_mwh"].iloc[0]) > 0.0
        else float("nan")
    )
    benchmark_summary["strategy_label"] = "price_insensitive_plan_first_market_cap"
    return benchmark_summary, benchmark_clearing, benchmark_redispatch.timeseries


def run_real_scenario_bidding_dry_run(
    *,
    config: HydrogenConfig | str | Path,
    artifact_id: str,
    forecast_origin_utc: str | None = None,
    max_origins: int = 1,
    output_root: Path | None = None,
    strategy_name: str = "stochastic_bid_risk_neutral",
    dry_run_label: str = "integration_candidate",
    include_price_insensitive_comparison: bool = True,
    risk_measure: str = "risk_neutral",
    cvar_alpha: float | None = None,
    cvar_gamma: float = 0.0,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
    inventory_start_kg: float | None = None,
    reserve_kg: float | None = None,
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    terminal_reference_start_kg: float | None = None,
    firm_bid_floor_mw: list[float] | tuple[float, ...] | None = None,
    emergency_import_price_eur_per_mwh: float | None = None,
    selected_scenarios_override: pd.DataFrame | None = None,
    actual_prices_override: pd.DataFrame | None = None,
    loader_findings_override: list[str] | tuple[str, ...] | None = None,
    benchmark_result_override: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None = None,
    input_cache_status: str | None = None,
    input_source_used: str | None = None,
    raw_artifact_read_again: bool | None = None,
    write_outputs: bool = True,
) -> RealScenarioBiddingDryRunResult:
    if int(max_origins) != 1:
        raise ValueError("Phase 6b dry run currently supports exactly one forecast origin.")
    normalized_risk_measure = str(risk_measure).strip().lower()
    if normalized_risk_measure not in {"risk_neutral", "cvar"}:
        raise ValueError(f"Unsupported risk_measure for real scenario dry run: {risk_measure!r}")
    run_config = _build_phase6b_config(
        config,
        artifact_id=artifact_id,
        output_root=output_root,
        strategy_name=strategy_name,
        dry_run_label=dry_run_label,
    )
    resolved_cvar_alpha = float(run_config.risk.alpha if cvar_alpha is None else cvar_alpha)
    resolved_cvar_gamma = float(cvar_gamma)
    profiler = RuntimeProfiler()
    catalog_payload = _load_catalog_payload(run_config)
    artifact_map = catalog_payload.get("artifacts", {})
    if artifact_id not in artifact_map:
        raise KeyError(f"Artifact '{artifact_id}' not present in scenario catalog.")
    artifact_entry = artifact_map[artifact_id]
    specs = resolve_artifact_specs(run_config)
    if len(specs) != 1:
        raise ValueError(f"Expected exactly one artifact spec for Phase 6b, got {len(specs)}.")
    spec = specs[0]
    artifact_manifest = _load_artifact_manifest(spec.path)
    scenario_source_used = str(
        input_source_used
        if input_source_used is not None
        else ("selected_scenarios_override" if selected_scenarios_override is not None else "scenario_loader_raw_artifact")
    )
    raw_read_flag = bool(
        raw_artifact_read_again if raw_artifact_read_again is not None else selected_scenarios_override is None
    )
    with profiler.track(
        "scenario_slice_load_resolve",
        artifact_id=str(artifact_id),
        requested_forecast_origin_utc="" if forecast_origin_utc is None else str(forecast_origin_utc),
        source_used=scenario_source_used,
        cache_status="" if input_cache_status is None else str(input_cache_status),
        raw_artifact_read_again=raw_read_flag,
        accounting_bucket="wall",
    ):
        if selected_scenarios_override is not None:
            selected_scenarios = selected_scenarios_override.copy()
            selected_scenarios["forecast_origin_utc"] = pd.to_datetime(
                selected_scenarios["forecast_origin_utc"], utc=True, errors="raise"
            )
            selected_scenarios["delivery_start_utc"] = pd.to_datetime(
                selected_scenarios["delivery_start_utc"], utc=True, errors="raise"
            )
            loader_findings = [str(value) for value in (loader_findings_override or [])]
            unique_origins = selected_scenarios["forecast_origin_utc"].drop_duplicates().sort_values()
            if int(unique_origins.shape[0]) != 1:
                raise ValueError(
                    "selected_scenarios_override must contain exactly one forecast origin for Phase 6b dry runs."
                )
            selected_origin = pd.Timestamp(unique_origins.iloc[0])
            if forecast_origin_utc is not None:
                expected_origin = pd.Timestamp(pd.to_datetime(forecast_origin_utc, utc=True, errors="raise"))
                if selected_origin != expected_origin:
                    raise ValueError(
                        f"selected_scenarios_override origin mismatch: expected {expected_origin}, got {selected_origin}."
                    )
        else:
            scenarios, loader_findings = load_scenarios_for_artifact(spec, config=run_config)
            selected_origin, selected_scenarios = _select_complete_forecast_origin(
                scenarios,
                explicit_forecast_origin_utc=forecast_origin_utc,
            )

    with profiler.track(
        "market_actual_load_resolve",
        artifact_id=str(artifact_id),
        delivery_day_hint=str(selected_scenarios["delivery_day"].iloc[0]) if not selected_scenarios.empty else "",
        accounting_bucket="wall",
    ):
        actual_prices = (
            actual_prices_override.copy()
            if actual_prices_override is not None
            else selected_scenarios[["delivery_start_utc", "actual_price_eur_per_mwh"]]
        )
        actual_prices = (
            actual_prices[["delivery_start_utc", "actual_price_eur_per_mwh"]]
            .drop_duplicates(subset=["delivery_start_utc"])
            .sort_values("delivery_start_utc")
            .reset_index(drop=True)
        )
        actual_prices["delivery_start_utc"] = pd.to_datetime(actual_prices["delivery_start_utc"], utc=True, errors="raise")
    if actual_prices.shape[0] != 24:
        raise ValueError(f"Selected origin does not have a 24-hour D-only delivery horizon: {selected_origin}")
    if actual_prices["actual_price_eur_per_mwh"].isna().any():
        raise ValueError(f"Selected origin is missing actual_price_eur_per_mwh values: {selected_origin}")

    delivery_day = str(selected_scenarios["delivery_day"].iloc[0])
    model_id = str(selected_scenarios["model_id"].iloc[0])

    run_dir: Path | None = None
    run_id = "phase6b_real_scenario_in_memory"
    solver_log_path: str | None = None
    if write_outputs:
        run_id, run_dir = create_run_folder(run_config)
        save_config_resolved(run_dir, run_config)
        save_inputs_manifest(run_dir, [run_config.config_path, run_config.models.scenario_catalog, spec.path])
        solver_log_path = str(run_dir / "solver_log.txt") if run_config.outputs.save_solver_log else None

    with profiler.track(
        "stochastic_optimisation",
        artifact_id=str(artifact_id),
        delivery_day=str(selected_scenarios["delivery_day"].iloc[0]),
        accounting_bucket="wall",
    ):
        optimisation_result = solve_stochastic_hourly_bidding(
            scenarios=selected_scenarios,
            config=run_config,
            run_id=run_id,
            strategy_name=strategy_name,
            bid_price_grid_eur_per_mwh=list(run_config.bidding.bid_price_grid_eur_per_mwh),
            solver_log_path=solver_log_path,
            toy_case=f"real_integration::{artifact_id}",
            risk_measure=normalized_risk_measure,
            cvar_alpha=resolved_cvar_alpha,
            cvar_gamma=resolved_cvar_gamma,
            production_target_mode=production_target_mode,
            shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
            inventory_start_kg=inventory_start_kg,
            reserve_kg=reserve_kg,
            target_hydrogen_min_kg=target_hydrogen_min_kg,
            target_hydrogen_max_kg=target_hydrogen_max_kg,
            terminal_reference_start_kg=terminal_reference_start_kg,
            firm_bid_floor_mw=firm_bid_floor_mw,
            emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
        )

    with profiler.track(
        "redispatch_clearing_settlement",
        artifact_id=str(artifact_id),
        delivery_day=str(selected_scenarios["delivery_day"].iloc[0]),
        accounting_bucket="wall",
    ):
        actual_clearing = clear_hourly_bids(optimisation_result.submitted_bids, actual_prices)
        actual_clearing["actual_path_id"] = "historical_actual_da"
        actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
        actual_clearing_by_hour["actual_path_id"] = "historical_actual_da"
        actual_clearing_by_hour["redispatch_case"] = "historical_actual_da"
        actual_clearing_by_hour["timestep_hours"] = float(run_config.delta_t_hours)

        redispatch = solve_actual_redispatch_from_cleared_energy(
            actual_clearing_by_hour,
            config=run_config,
            inventory_start_kg=inventory_start_kg,
            reserve_kg=reserve_kg,
            production_target_mode=production_target_mode,
            target_hydrogen_kg=target_hydrogen_min_kg,
            target_hydrogen_max_kg=target_hydrogen_max_kg,
            shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
            terminal_reference_start_kg=terminal_reference_start_kg,
            emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
            solver_log_path=run_dir / "actual_redispatch_solver_log.txt" if run_dir is not None and run_config.outputs.save_solver_log else None,
        )
    actual_redispatch_timeseries = redispatch.timeseries.assign(actual_path_id="historical_actual_da")
    actual_settlement_results = redispatch.summary.assign(actual_path_id="historical_actual_da")
    scenario_objective_summary = _build_scenario_objective_summary(optimisation_result)
    expected_scenario_count = int(selected_scenarios["scenario_id"].astype(str).nunique())

    benchmark_comparison = pd.DataFrame()
    benchmark_clearing = pd.DataFrame()
    benchmark_timeseries = pd.DataFrame()
    with profiler.track(
        "benchmark_load_solve",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        benchmark_cache_status="hit" if benchmark_result_override is not None else "miss",
        accounting_bucket="wall",
    ):
        if include_price_insensitive_comparison:
            if benchmark_result_override is not None:
                benchmark_comparison, benchmark_clearing, benchmark_timeseries = (
                    benchmark_result_override[0].copy(),
                    benchmark_result_override[1].copy(),
                    benchmark_result_override[2].copy(),
                )
            else:
                benchmark_result = _run_price_insensitive_badarinath_style_comparison(
                    day_frame=selected_scenarios,
                    actual_prices=actual_prices,
                    config=run_config,
                    run_id=run_id,
                    model_id=model_id,
                    forecast_origin_utc=selected_origin,
                    solver_log_root=run_dir,
                    production_target_mode=production_target_mode,
                    shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
                )
                if benchmark_result is not None:
                    benchmark_comparison, benchmark_clearing, benchmark_timeseries = benchmark_result

    with profiler.track(
        "validation_checks",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        accounting_bucket="wall",
    ):
        validation_checks = _build_real_dry_run_validation_checks(
            artifact_id=artifact_id,
            artifact_path=spec.path,
            catalog_entry=artifact_entry,
            artifact_manifest=artifact_manifest,
            selected_scenarios=selected_scenarios,
            actual_prices=actual_prices,
            optimisation_result=optimisation_result,
            actual_clearing=actual_clearing,
            actual_clearing_by_hour=actual_clearing_by_hour,
            redispatch=redispatch,
            benchmark_comparison=benchmark_comparison,
            benchmark_clearing=benchmark_clearing,
            expected_scenario_count=expected_scenario_count,
            validation_mode=str(spec.validation_mode),
        )
    with profiler.track(
        "metrics",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        accounting_bucket="wall",
    ):
        metrics_summary = _build_real_metrics_summary(
            artifact_id=artifact_id,
            delivery_day=delivery_day,
            forecast_origin_utc=selected_origin,
            optimisation_result=optimisation_result,
            actual_clearing_by_hour=actual_clearing_by_hour,
            redispatch=redispatch,
            benchmark_comparison=benchmark_comparison,
        )
    scenario_probability_sum = float(
        selected_scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])["scenario_probability"]
        .astype(float)
        .sum()
    )
    thesis_grade = bool(artifact_manifest.get("thesis_grade", artifact_entry.get("thesis_grade", True)))
    sanity_summary = _build_real_sanity_summary(
        artifact_id=artifact_id,
        forecast_origin_utc=selected_origin,
        delivery_day=delivery_day,
        scenario_count=int(selected_scenarios["scenario_id"].astype(str).nunique()),
        probability_sum=scenario_probability_sum,
        metrics_summary=metrics_summary,
        validation_checks=validation_checks,
        thesis_grade=thesis_grade,
    )
    input_manifest_payload = {
        "artifact_id": artifact_id,
        "artifact_path": str(spec.path),
        "catalog_validation_mode": spec.validation_mode,
        "allow_forecast_origin_reconstruction": bool(spec.allow_forecast_origin_reconstruction),
        "loader_findings": loader_findings,
        "selected_forecast_origin_utc": selected_origin.isoformat(),
        "selected_delivery_day": delivery_day,
        "selected_model_id": model_id,
        "selected_scenario_count": expected_scenario_count,
        "selected_delivery_hour_count": int(selected_scenarios["delivery_start_utc"].nunique()),
        "selected_probability_sum_unique": scenario_probability_sum,
        "actual_price_source": "scenario_input.actual_price_eur_per_mwh",
        "risk_measure": normalized_risk_measure,
        "cvar_alpha": resolved_cvar_alpha,
        "cvar_gamma": resolved_cvar_gamma,
        "inventory_start_kg_override": inventory_start_kg,
        "reserve_kg_override": reserve_kg,
        "target_hydrogen_min_kg_override": target_hydrogen_min_kg,
        "target_hydrogen_max_kg_override": target_hydrogen_max_kg,
        "terminal_reference_start_kg_override": terminal_reference_start_kg,
        "firm_bid_floor_mw_override": list(firm_bid_floor_mw) if firm_bid_floor_mw is not None else None,
        "emergency_import_price_eur_per_mwh_override": emergency_import_price_eur_per_mwh,
        "known_limitations": (
            [
                "hourly_only",
                "D_only_only",
                "single_forecast_origin_only",
            ]
            + ([] if normalized_risk_measure == "cvar" else ["risk_neutral_only", "no_CVaR"])
            + (["integration_candidate_only"] if spec.validation_mode == "smoke_test" else [])
            + (["forecast_origin_reconstructed_upstream"] if bool(artifact_manifest.get("forecast_origin_reconstructed", False)) else [])
        ),
    }
    scenario_manifest_payload = {
        "artifact_id": artifact_id,
        "catalog_entry": artifact_entry,
        "artifact_export_manifest": artifact_manifest,
        "selected_forecast_origin_utc": selected_origin.isoformat(),
        "selected_delivery_day": delivery_day,
        "delivery_timestamp_min_utc": str(actual_prices["delivery_start_utc"].min()),
        "delivery_timestamp_max_utc": str(actual_prices["delivery_start_utc"].max()),
        "risk_measure": normalized_risk_measure,
        "cvar_alpha": resolved_cvar_alpha,
        "cvar_gamma": resolved_cvar_gamma,
        "scenario_ids": sorted(selected_scenarios["scenario_id"].astype(str).unique().tolist()),
        "scenario_probability_sum_unique": float(
            selected_scenarios[["scenario_id", "scenario_probability"]]
            .drop_duplicates(subset=["scenario_id"])["scenario_probability"]
            .astype(float)
            .sum()
        ),
    }
    model_stats_payload = {
        "stochastic_bidding_model": {
            "solver_status": optimisation_result.solver.status,
            "objective_value": optimisation_result.solver.objective_value,
            "solve_time_seconds": optimisation_result.solver.runtime_seconds,
            "variable_count": optimisation_result.model_stats.variable_count,
            "binary_variable_count": optimisation_result.model_stats.binary_variable_count,
            "constraint_count": optimisation_result.model_stats.constraint_count,
            "scenario_count": optimisation_result.model_stats.scenario_count,
            "horizon_steps": optimisation_result.model_stats.horizon_steps,
            "timestep_hours": optimisation_result.model_stats.timestep_hours,
        },
        "actual_redispatch_model": {
            "solver_status": redispatch.solver.status,
            "objective_value": redispatch.solver.objective_value,
            "solve_time_seconds": redispatch.solver.runtime_seconds,
            "variable_count": redispatch.model_stats.variable_count,
            "binary_variable_count": redispatch.model_stats.binary_variable_count,
            "constraint_count": redispatch.model_stats.constraint_count,
            "scenario_count": redispatch.model_stats.scenario_count,
            "horizon_steps": redispatch.model_stats.horizon_steps,
            "timestep_hours": redispatch.model_stats.timestep_hours,
        },
    }

    with profiler.track(
        "output_writing",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        persisted=bool(write_outputs and run_dir is not None),
        accounting_bucket="wall",
    ):
        if write_outputs and run_dir is not None:
            save_frame_parquet(run_dir, "submitted_bids.parquet", optimisation_result.submitted_bids)
            save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
            save_frame_parquet(run_dir, "actual_clearing_by_hour.parquet", actual_clearing_by_hour)
            save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
            save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
            save_frame_parquet(run_dir, "scenario_clearing.parquet", optimisation_result.scenario_clearing)
            save_frame_parquet(run_dir, "scenario_dispatch.parquet", optimisation_result.scenario_dispatch)
            save_frame_csv(run_dir, "scenario_settlement_results.csv", optimisation_result.scenario_economics)
            save_frame_csv(run_dir, "scenario_objective_summary.csv", scenario_objective_summary)
            save_frame_csv(run_dir, "metrics_summary.csv", metrics_summary)
            save_frame_csv(run_dir, "validation_checks.csv", validation_checks)
            save_frame_csv(run_dir, "real_scenario_dry_run_sanity_summary.csv", sanity_summary)
            if not benchmark_comparison.empty:
                save_frame_csv(run_dir, "benchmark_comparison.csv", benchmark_comparison)
                save_frame_parquet(run_dir, "benchmark_actual_clearing.parquet", benchmark_clearing)
                save_frame_parquet(run_dir, "benchmark_actual_redispatch_timeseries.parquet", benchmark_timeseries)
            save_json(run_dir, "input_manifest.json", input_manifest_payload)
            save_json(run_dir, "scenario_manifest.json", scenario_manifest_payload)
            save_json(run_dir, "model_stats.json", model_stats_payload)

    with profiler.track(
        "figure_generation",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        persisted=bool(write_outputs and run_dir is not None and run_config.outputs.save_figures),
        accounting_bucket="wall",
    ):
        if write_outputs and run_dir is not None and run_config.outputs.save_figures:
            figures_dir = run_dir / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            plot_real_scenario_fan_vs_actual(
                scenario_period=selected_scenarios,
                output_dir=figures_dir,
                filename="scenario_fan_vs_actual.png",
            )
            selected_hours = list(pd.DatetimeIndex(optimisation_result.submitted_bids["delivery_start_utc"]).unique()[:3])
            actual_path_frame = actual_prices.assign(actual_path_id="historical_actual_da")
            plot_submitted_bid_curves_with_actual_overlays(
                submitted_bids=optimisation_result.submitted_bids,
                actual_price_paths=actual_path_frame,
                selected_hours=selected_hours,
                output_dir=figures_dir,
                filename="submitted_bid_curve_with_actual_overlay.png",
            )
            plot_actual_clearing_heatmap(
                actual_clearing=actual_clearing,
                output_dir=figures_dir,
                filename="actual_clearing_heatmap.png",
            )
            plot_submitted_cleared_rejected_energy(
                actual_clearing_by_hour=actual_clearing_by_hour,
                output_dir=figures_dir,
                filename="submitted_cleared_rejected_energy.png",
            )
            plot_cleared_used_unused_electricity(
                redispatch=actual_redispatch_timeseries,
                output_dir=figures_dir,
                filename="cleared_used_unused_energy.png",
                title="historical_actual_da",
            )
            plot_actual_storage_trajectories(
                actual_redispatch_timeseries=actual_redispatch_timeseries,
                output_dir=figures_dir,
                filename="actual_storage_trajectory.png",
            )
            plot_expected_vs_realised_profit_distribution(
                scenario_economics=optimisation_result.scenario_economics,
                realised_summary=pd.DataFrame(
                    [
                        {
                            "actual_path_id": "historical_actual_da",
                            "realised_adjusted_profit_after_actual_clearing": float(actual_settlement_results["realised_adjusted_profit_eur"].iloc[0]),
                        }
                    ]
                ),
                output_dir=figures_dir,
                filename="scenario_profit_distribution_with_realised_marker.png",
            )
            if not benchmark_comparison.empty:
                plot_realised_profit_comparison_bar(
                    comparison=pd.DataFrame(
                        [
                            {
                                "strategy_label": strategy_name,
                                "realised_adjusted_profit_eur": float(actual_settlement_results["realised_adjusted_profit_eur"].iloc[0]),
                            },
                            {
                                "strategy_label": "price_insensitive_plan_first_market_cap",
                                "realised_adjusted_profit_eur": float(benchmark_comparison["realised_adjusted_profit_eur"].iloc[0]),
                            },
                        ]
                    ),
                    output_dir=figures_dir,
                    filename="realised_profit_comparison_vs_price_insensitive.png",
                )

    with profiler.track(
        "readme_generation",
        artifact_id=str(artifact_id),
        delivery_day=str(delivery_day),
        persisted=bool(write_outputs and run_dir is not None),
        accounting_bucket="wall",
    ):
        if write_outputs and run_dir is not None:
            summary_csv = metrics_summary.to_csv(index=False).strip()
            scenario_csv = scenario_objective_summary.to_csv(index=False).strip()
            validation_csv = validation_checks.to_csv(index=False).strip()
            readme_lines = [
                "# Real Scenario Bidding Integration Dry Run",
                "",
                (
                    "This run is an integration dry run only. It is not thesis-grade stochastic bidding evidence."
                    if spec.validation_mode == "smoke_test"
                    else "This run uses a thesis-grade real-scenario artifact, but it remains a one-origin diagnostic run rather than a representative backtest."
                ),
                "",
                f"- Artifact ID: `{artifact_id}`",
                f"- Model ID: `{model_id}`",
                f"- Forecast origin UTC: `{selected_origin.isoformat()}`",
                f"- Delivery day: `{delivery_day}`",
                f"- Dry-run label: `{dry_run_label}`",
                f"- Validation mode: `{spec.validation_mode}`",
                f"- Scenario count: `{expected_scenario_count}`",
                f"- Risk measure: `{normalized_risk_measure}`",
                f"- CVaR alpha: `{resolved_cvar_alpha:.4f}`",
                f"- CVaR gamma: `{resolved_cvar_gamma}`",
                (
                    "- Forecast origin provenance was reconstructed upstream and written explicitly into the source artifact."
                    if bool(artifact_manifest.get("forecast_origin_reconstructed", False))
                    else "- Forecast origin provenance is stored explicitly in the source artifact."
                ),
                "- The expected stochastic objective and realised settlement are separate quantities and must not be conflated.",
                "",
                "## Summary",
                "",
                "```csv",
                summary_csv,
                "```",
                "",
                "## Sanity Summary",
                "",
                "```csv",
                sanity_summary.to_csv(index=False).strip(),
                "```",
                "",
                "## Validation Checks",
                "",
                "```csv",
                validation_csv,
                "```",
                "",
                "## Scenario Objective Summary",
                "",
                "```csv",
                scenario_csv,
                "```",
            ]
            if not benchmark_comparison.empty:
                readme_lines.extend(
                    [
                        "",
                        "## Price-Insensitive Comparison",
                        "",
                        "```csv",
                        benchmark_comparison.to_csv(index=False).strip(),
                        "```",
                    ]
                )
            readme_lines.extend(
                [
                    "",
                    "## Warnings",
                    "",
                    "- one forecast origin and one delivery day only.",
                    (
                        "- risk-neutral only; no CVaR sweep in this phase."
                        if normalized_risk_measure == "risk_neutral"
                        else "- CVaR was activated for this run; interpret expected-profit and downside-risk tradeoffs jointly."
                    ),
                ]
            )
            if spec.validation_mode == "smoke_test":
                readme_lines.insert(-3, "- integration_candidate only; not thesis-grade.")
            if bool(artifact_manifest.get("forecast_origin_reconstructed", False)):
                readme_lines.insert(-3, "- forecast_origin_utc was reconstructed upstream from D-1 08:00 Europe/Amsterdam.")
            save_text(run_dir, "README_real_scenario_dry_run.md", "\n".join(readme_lines))

    runtime_profile = profiler.to_frame()
    detail_rows: list[dict[str, Any]] = [
        {
            "stage": "model_build",
            "started_utc": pd.NA,
            "finished_utc": pd.NA,
            "wall_time_seconds": float(optimisation_result.solver.model_build_time_seconds or 0.0),
            "artifact_id": str(artifact_id),
            "delivery_day": str(delivery_day),
            "accounting_bucket": "detail_component",
            "component_scope": "stochastic",
        },
        {
            "stage": "stochastic_solve",
            "started_utc": pd.NA,
            "finished_utc": pd.NA,
            "wall_time_seconds": float(optimisation_result.solver.solver_time_seconds or 0.0),
            "artifact_id": str(artifact_id),
            "delivery_day": str(delivery_day),
            "accounting_bucket": "detail_component",
            "component_scope": "stochastic",
        },
        {
            "stage": "redispatch_solver",
            "started_utc": pd.NA,
            "finished_utc": pd.NA,
            "wall_time_seconds": float(redispatch.solver.solver_time_seconds or 0.0),
            "artifact_id": str(artifact_id),
            "delivery_day": str(delivery_day),
            "accounting_bucket": "detail_component",
            "component_scope": "redispatch",
        },
    ]
    runtime_profile = pd.concat([runtime_profile, pd.DataFrame(detail_rows)], ignore_index=True, sort=False)
    execution_audit = pd.DataFrame(
        [
            {
                "artifact_id": str(artifact_id),
                "model_id": str(model_id),
                "delivery_day": str(delivery_day),
                "forecast_origin_utc": selected_origin,
                "scenario_row_count": int(selected_scenarios.shape[0]),
                "scenario_count": int(selected_scenarios["scenario_id"].astype(str).nunique()),
                "actual_hour_count": int(actual_prices["delivery_start_utc"].nunique()),
                "cache_status": "" if input_cache_status is None else str(input_cache_status),
                "source_used": scenario_source_used,
                "raw_artifact_read_again": raw_read_flag,
                "benchmark_cache_status": "hit" if benchmark_result_override is not None else "miss",
                "write_outputs": bool(write_outputs),
                "run_dir": "" if run_dir is None else str(run_dir),
            }
        ]
    )

    return RealScenarioBiddingDryRunResult(
        artifact_id=artifact_id,
        forecast_origin_utc=selected_origin,
        delivery_day=delivery_day,
        scenarios=selected_scenarios,
        actual_prices=actual_prices,
        optimisation_result=optimisation_result,
        actual_clearing=actual_clearing,
        actual_clearing_by_hour=actual_clearing_by_hour,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        actual_settlement_results=actual_settlement_results,
        actual_redispatch_solver=redispatch.solver,
        actual_redispatch_model_stats=redispatch.model_stats,
        scenario_objective_summary=scenario_objective_summary,
        metrics_summary=metrics_summary,
        validation_checks=validation_checks,
        sanity_summary=sanity_summary,
        benchmark_comparison=benchmark_comparison,
        benchmark_clearing=benchmark_clearing,
        benchmark_timeseries=benchmark_timeseries,
        input_manifest_payload=input_manifest_payload,
        scenario_manifest_payload=scenario_manifest_payload,
        model_stats_payload=model_stats_payload,
        runtime_profile=runtime_profile,
        execution_audit=execution_audit,
        run_dir=run_dir,
    )


def run_real_scenario_selected_origin_suite(
    *,
    config: HydrogenConfig | str | Path,
    artifact_ids: list[str] | tuple[str, ...],
    max_origins_per_artifact: int = 5,
    selection_method: str = "price_diagnostics",
    output_root: Path | None = None,
    dry_run_label: str = "integration_candidate",
    strategy_name: str = "stochastic_bid_risk_neutral",
) -> SelectedOriginSuiteResult:
    suite_config = _build_phase6c_suite_config(config, output_root=output_root)
    suite_run_id, suite_dir = create_run_folder(suite_config)
    save_config_resolved(suite_dir, suite_config)
    save_inputs_manifest(suite_dir, [suite_config.config_path, suite_config.models.scenario_catalog])

    selected_registry_rows: list[pd.DataFrame] = []
    metrics_rows: list[pd.DataFrame] = []
    benchmark_rows: list[pd.DataFrame] = []
    validation_rows: list[pd.DataFrame] = []
    model_stats_rows: list[dict[str, Any]] = []
    run_dir_rows: list[dict[str, Any]] = []

    origin_output_root = suite_dir / "origin_runs"
    origin_output_root.mkdir(parents=True, exist_ok=True)

    for artifact_id in [str(value) for value in artifact_ids]:
        selected = select_real_scenario_origins_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
            max_origins_per_artifact=max_origins_per_artifact,
            selection_method=selection_method,
        )
        selected_registry_rows.append(selected)
        for origin_row in selected.to_dict(orient="records"):
            result = run_real_scenario_bidding_dry_run(
                config=suite_config,
                artifact_id=artifact_id,
                forecast_origin_utc=str(pd.Timestamp(origin_row["forecast_origin_utc"]).isoformat()),
                max_origins=1,
                output_root=origin_output_root,
                strategy_name=strategy_name,
                dry_run_label=dry_run_label,
                include_price_insensitive_comparison=True,
                write_outputs=True,
            )
            metrics = result.metrics_summary.copy()
            metrics["selection_reason"] = origin_row["selection_reason"]
            metrics["actual_price_mean"] = origin_row["actual_price_mean"]
            metrics["actual_price_min"] = origin_row["actual_price_min"]
            metrics["actual_price_max"] = origin_row["actual_price_max"]
            metrics["actual_price_spread"] = origin_row["actual_price_spread"]
            metrics["thesis_grade"] = origin_row["thesis_grade"]
            metrics["forecast_origin_reconstructed"] = origin_row["forecast_origin_reconstructed"]
            metrics_rows.append(metrics)

            validation = result.validation_checks.copy()
            validation["artifact_id"] = artifact_id
            validation["forecast_origin_utc"] = result.forecast_origin_utc
            validation["delivery_day"] = result.delivery_day
            validation["selection_reason"] = origin_row["selection_reason"]
            validation_rows.append(validation)

            model_stats_rows.append(
                {
                    "artifact_id": artifact_id,
                    "forecast_origin_utc": result.forecast_origin_utc,
                    "delivery_day": result.delivery_day,
                    "selection_reason": origin_row["selection_reason"],
                    "stochastic_solver_status": result.optimisation_result.solver.status,
                    "stochastic_objective_value": result.optimisation_result.solver.objective_value,
                    "stochastic_solve_time_seconds": result.optimisation_result.solver.runtime_seconds,
                    "stochastic_variable_count": result.optimisation_result.model_stats.variable_count,
                    "stochastic_binary_variable_count": result.optimisation_result.model_stats.binary_variable_count,
                    "stochastic_constraint_count": result.optimisation_result.model_stats.constraint_count,
                    "scenario_count": result.optimisation_result.model_stats.scenario_count,
                    "horizon_steps": result.optimisation_result.model_stats.horizon_steps,
                    "redispatch_solver_status": result.actual_settlement_results["solver_status"].iloc[0],
                    "redispatch_objective_value": float(result.actual_settlement_results["objective_value"].iloc[0]),
                    "redispatch_solve_time_seconds": float(result.actual_settlement_results["solve_time_seconds"].iloc[0]),
                    "redispatch_variable_count": int(result.actual_settlement_results["variable_count"].iloc[0]),
                    "redispatch_binary_variable_count": int(result.actual_settlement_results["binary_variable_count"].iloc[0]),
                    "redispatch_constraint_count": int(result.actual_settlement_results["constraint_count"].iloc[0]),
                }
            )

            if not result.benchmark_comparison.empty:
                benchmark = result.benchmark_comparison.copy()
                benchmark["artifact_id"] = artifact_id
                benchmark["delivery_day"] = result.delivery_day
                benchmark["selection_reason"] = origin_row["selection_reason"]
                benchmark["stochastic_realised_adjusted_profit_eur"] = float(result.metrics_summary["realised_adjusted_profit_eur"].iloc[0])
                benchmark["stochastic_cleared_energy_mwh"] = float(result.metrics_summary["cleared_energy_mwh"].iloc[0])
                benchmark["stochastic_hydrogen_sold_kg"] = float(result.metrics_summary["hydrogen_sold_or_compressed_kg"].iloc[0])
                benchmark["stochastic_average_actual_price_paid_eur_per_mwh"] = float(result.metrics_summary["weighted_average_actual_price_paid_for_cleared_energy"].iloc[0])
                benchmark["stochastic_shortfall_kg"] = float(result.metrics_summary["shortfall_kg"].iloc[0])
                benchmark["stochastic_minus_benchmark_profit"] = (
                    float(result.metrics_summary["realised_adjusted_profit_eur"].iloc[0])
                    - float(benchmark["realised_adjusted_profit_eur"].iloc[0])
                )
                benchmark["stochastic_minus_benchmark_cleared_energy"] = (
                    float(result.metrics_summary["cleared_energy_mwh"].iloc[0])
                    - float(benchmark["cleared_energy_mwh"].iloc[0])
                )
                benchmark["stochastic_minus_benchmark_hydrogen_sold"] = (
                    float(result.metrics_summary["hydrogen_sold_or_compressed_kg"].iloc[0])
                    - float(benchmark["hydrogen_compressed_or_sold_kg"].iloc[0])
                )
                benchmark["stochastic_minus_benchmark_average_price_paid"] = (
                    float(result.metrics_summary["weighted_average_actual_price_paid_for_cleared_energy"].iloc[0])
                    - float(benchmark["weighted_average_actual_price_paid_for_cleared_energy"].iloc[0])
                )
                benchmark_rows.append(benchmark)

            run_dir_rows.append(
                {
                    "artifact_id": artifact_id,
                    "forecast_origin_utc": result.forecast_origin_utc,
                    "delivery_day": result.delivery_day,
                    "selection_reason": origin_row["selection_reason"],
                    "run_dir": str(result.run_dir) if result.run_dir is not None else "",
                }
            )

    selected_origin_registry = pd.concat(selected_registry_rows, ignore_index=True) if selected_registry_rows else pd.DataFrame()
    metrics_by_origin = pd.concat(metrics_rows, ignore_index=True) if metrics_rows else pd.DataFrame()
    benchmark_comparison_by_origin = pd.concat(benchmark_rows, ignore_index=True) if benchmark_rows else pd.DataFrame()
    validation_checks_all_origins = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    model_stats_by_origin = pd.DataFrame(model_stats_rows)
    origin_run_dirs = pd.DataFrame(run_dir_rows)

    if metrics_by_origin.empty:
        raise RuntimeError("Selected-origin suite produced no origin metrics.")

    metrics_by_origin["stochastic_minus_benchmark_profit"] = (
        metrics_by_origin["realised_adjusted_profit_eur"].astype(float)
        - metrics_by_origin["benchmark_realised_adjusted_profit_eur"].astype(float)
    )
    metrics_by_origin["stochastic_minus_benchmark_cleared_energy"] = (
        metrics_by_origin["cleared_energy_mwh"].astype(float)
        - metrics_by_origin["benchmark_cleared_energy_mwh"].astype(float)
    )
    metrics_by_origin["stochastic_minus_benchmark_hydrogen_sold"] = (
        metrics_by_origin["hydrogen_sold_or_compressed_kg"].astype(float)
        - metrics_by_origin["benchmark_hydrogen_sold_kg"].astype(float)
    )
    metrics_by_origin["stochastic_minus_benchmark_average_price_paid"] = (
        metrics_by_origin["weighted_average_actual_price_paid_for_cleared_energy"].astype(float)
        - metrics_by_origin["benchmark_average_actual_price_paid_eur_per_mwh"].astype(float)
    )
    metrics_by_origin["value_captured_vs_benchmark"] = metrics_by_origin["stochastic_minus_benchmark_profit"].astype(float)

    metrics_by_artifact_summary = (
        metrics_by_origin.groupby("artifact_id", as_index=False)
        .agg(
            origin_count=("forecast_origin_utc", "count"),
            mean_realised_profit_eur=("realised_adjusted_profit_eur", "mean"),
            mean_benchmark_profit_eur=("benchmark_realised_adjusted_profit_eur", "mean"),
            mean_stochastic_minus_benchmark_profit=("stochastic_minus_benchmark_profit", "mean"),
            median_stochastic_minus_benchmark_profit=("stochastic_minus_benchmark_profit", "median"),
            mean_clearing_ratio=("clearing_ratio", "mean"),
            mean_rejected_energy_mwh=("rejected_energy_mwh", "mean"),
            mean_hydrogen_sold_kg=("hydrogen_sold_or_compressed_kg", "mean"),
            mean_shortfall_kg=("shortfall_kg", "mean"),
            mean_average_actual_price_paid_eur_per_mwh=("weighted_average_actual_price_paid_for_cleared_energy", "mean"),
        )
        .sort_values("artifact_id")
        .reset_index(drop=True)
    )

    save_frame_csv(suite_dir, "selected_origin_registry.csv", selected_origin_registry)
    save_frame_csv(suite_dir, "metrics_by_origin.csv", metrics_by_origin)
    save_frame_csv(suite_dir, "metrics_by_artifact_summary.csv", metrics_by_artifact_summary)
    save_frame_csv(suite_dir, "benchmark_comparison_by_origin.csv", benchmark_comparison_by_origin)
    save_frame_csv(suite_dir, "validation_checks_all_origins.csv", validation_checks_all_origins)
    save_frame_csv(suite_dir, "model_stats_by_origin.csv", model_stats_by_origin)
    save_frame_csv(suite_dir, "origin_run_dirs.csv", origin_run_dirs)

    figures_dir = suite_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_suite_realised_profit_by_origin(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_realised_profit_by_origin.png",
    )
    plot_suite_profit_delta_by_origin(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_stochastic_minus_benchmark_profit_by_origin.png",
    )
    plot_suite_clearing_ratio_by_origin(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_clearing_ratio_by_origin.png",
    )
    plot_suite_hydrogen_and_shortfall_by_origin(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_hydrogen_and_shortfall_by_origin.png",
    )
    plot_suite_average_actual_price_paid_by_origin(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_average_actual_price_paid_by_origin.png",
    )
    plot_suite_price_spread_vs_profit_delta(
        metrics_by_origin=metrics_by_origin,
        output_dir=figures_dir,
        filename="suite_price_spread_vs_profit_delta.png",
    )

    warnings = [
        "integration_candidate_only",
        "forecast_origin_reconstructed_upstream",
        "hourly_only",
        "D_only_only",
        "risk_neutral_only",
        "no_CVaR",
        "no_LEAR_Strict_hourly_artifact_available",
        "selected_origin_diagnostics_only_not_thesis_grade",
    ]
    save_json(
        suite_dir,
        "suite_manifest.json",
        {
            "suite_run_id": suite_run_id,
            "artifact_ids": [str(value) for value in artifact_ids],
            "max_origins_per_artifact": int(max_origins_per_artifact),
            "selection_method": str(selection_method),
            "dry_run_label": str(dry_run_label),
            "strategy_name": str(strategy_name),
            "warnings": warnings,
        },
    )
    readme_lines = [
        "# Selected-Origin Real Scenario Dry-Run Suite",
        "",
        "This suite runs a small set of integration-candidate origins before any selected-week scaling.",
        "",
        f"- Artifacts: `{[str(value) for value in artifact_ids]}`",
        f"- Max origins per artifact: `{int(max_origins_per_artifact)}`",
        f"- Selection method: `{selection_method}`",
        "- This suite is not thesis-grade evidence.",
        "- LEAR Strict hourly scenarios remain unavailable and were not used.",
        "",
        "## Selected Origins",
        "",
        "```csv",
        selected_origin_registry.to_csv(index=False).strip(),
        "```",
        "",
        "## Metrics by Artifact",
        "",
        "```csv",
        metrics_by_artifact_summary.to_csv(index=False).strip(),
        "```",
        "",
        "## Known Limitations",
        "",
        "- integration-candidate artifacts only",
        "- reconstructed forecast origins",
        "- hourly only",
        "- D-only only",
        "- risk-neutral only",
        "- no CVaR, mFRR, exclusive group bids, endogenous bid prices, or full EUPHEMIA",
        "- results are integration diagnostics only, not thesis-grade strategy evidence",
    ]
    save_text(suite_dir, "README_selected_origin_suite.md", "\n".join(readme_lines))

    return SelectedOriginSuiteResult(
        suite_dir=suite_dir,
        selected_origin_registry=selected_origin_registry,
        metrics_by_origin=metrics_by_origin,
        metrics_by_artifact_summary=metrics_by_artifact_summary,
        benchmark_comparison_by_origin=benchmark_comparison_by_origin,
        validation_checks_all_origins=validation_checks_all_origins,
        model_stats_by_origin=model_stats_by_origin,
        origin_run_dirs=origin_run_dirs,
    )


def run_toy_stochastic_bidding_backtest(
    *,
    config: HydrogenConfig | str | Path,
    toy_case: str = "mixed_clearing",
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...] | None = None,
    output_root: Path | None = None,
    write_outputs: bool = True,
    risk_measure: str = "risk_neutral",
    cvar_alpha: float = 0.95,
    cvar_gamma: float = 0.0,
) -> ToyStochasticBacktestResult:
    if toy_case in {"cvar_high_price_exposure", "cvar_overprocurement_unused_energy"}:
        run_config = build_phase5b_toy_case_config(
            config,
            toy_case=toy_case,
            experiment_name="hydrogen_phase5b_toy_stochastic_bidding_backtest",
        )
    else:
        run_config = (
            build_phase5a_toy_config(config, experiment_name="hydrogen_phase5a_toy_stochastic_bidding_backtest")
            if str(risk_measure).strip().lower() == "cvar"
            else build_phase4b_toy_backtest_config(config)
        )
    if output_root is not None:
        run_config = replace(run_config, outputs=replace(run_config.outputs, root=Path(output_root)))

    scenarios = build_toy_hourly_scenario_set(toy_case)
    actual_price_paths = build_toy_realised_actual_price_paths(
        toy_case=toy_case,
        forecast_origin_utc=str(pd.Timestamp(scenarios["forecast_origin_utc"].iloc[0]).isoformat())
    )
    bid_grid = list(bid_price_grid_eur_per_mwh) if bid_price_grid_eur_per_mwh is not None else list(run_config.bidding.bid_price_grid_eur_per_mwh)

    run_dir: Path | None = None
    stochastic_solver_log_path: str | None = None
    redispatch_log_root: Path | None = None
    if write_outputs:
        run_id, run_dir = create_run_folder(run_config)
        save_config_resolved(run_dir, run_config)
        save_inputs_manifest(run_dir, [run_config.config_path])
        stochastic_solver_log_path = str(run_dir / "solver_log.txt") if run_config.outputs.save_solver_log else None
        redispatch_log_root = run_dir
    else:
        run_id = "toy_phase4b_in_memory"

    optimisation_result = solve_stochastic_hourly_bidding(
        scenarios=scenarios,
        config=run_config,
        run_id=run_id,
        bid_price_grid_eur_per_mwh=bid_grid,
        solver_log_path=stochastic_solver_log_path,
        toy_case=toy_case,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
    )

    actual_clearing_rows: list[pd.DataFrame] = []
    actual_clearing_by_hour_rows: list[pd.DataFrame] = []
    redispatch_timeseries_rows: list[pd.DataFrame] = []
    redispatch_summary_rows: list[pd.DataFrame] = []

    for actual_path_id, actual_path in actual_price_paths.groupby("actual_path_id", sort=True):
        actual_path = actual_path.sort_values("delivery_start_utc").reset_index(drop=True)
        cleared = clear_hourly_bids(
            optimisation_result.submitted_bids,
            actual_path[["delivery_start_utc", "actual_price_eur_per_mwh"]],
        )
        cleared["actual_path_id"] = actual_path_id
        actual_clearing_rows.append(cleared)

        cleared_by_hour = aggregate_cleared_energy(cleared)
        cleared_by_hour["actual_path_id"] = actual_path_id
        cleared_by_hour["redispatch_case"] = actual_path_id
        cleared_by_hour["timestep_hours"] = float(optimisation_result.submitted_bids["timestep_hours"].iloc[0])
        actual_clearing_by_hour_rows.append(cleared_by_hour)

        redispatch_log_path = None
        if redispatch_log_root is not None and run_config.outputs.save_solver_log:
            redispatch_log_path = redispatch_log_root / f"{actual_path_id}__redispatch_solver_log.txt"
        redispatch = solve_actual_redispatch_from_cleared_energy(
            cleared_by_hour,
            config=run_config,
            solver_log_path=redispatch_log_path,
        )
        redispatch_timeseries_rows.append(redispatch.timeseries.assign(actual_path_id=actual_path_id))
        redispatch_summary_rows.append(redispatch.summary.assign(actual_path_id=actual_path_id))

    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True)
    actual_clearing_by_hour = pd.concat(actual_clearing_by_hour_rows, ignore_index=True)
    actual_redispatch_timeseries = pd.concat(redispatch_timeseries_rows, ignore_index=True)
    actual_settlement_results = pd.concat(redispatch_summary_rows, ignore_index=True)
    stochastic_vs_realised_summary = compute_realised_backtest_summary(
        optimisation_summary=optimisation_result.summary,
        actual_clearing_by_hour=actual_clearing_by_hour,
        actual_redispatch_summary=actual_settlement_results,
    )
    scenario_objective_summary = _build_scenario_objective_summary(optimisation_result)

    if write_outputs and run_dir is not None:
        save_frame_parquet(run_dir, "stochastic_submitted_bids.parquet", optimisation_result.submitted_bids)
        save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
        save_frame_parquet(run_dir, "actual_clearing_by_hour.parquet", actual_clearing_by_hour)
        save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
        save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
        save_frame_csv(run_dir, "stochastic_vs_realised_summary.csv", stochastic_vs_realised_summary)
        save_frame_csv(run_dir, "scenario_objective_summary.csv", scenario_objective_summary)
        save_json(
            run_dir,
            "model_stats.json",
            {
                "stochastic_bidding_model": {
                    "solver_status": optimisation_result.solver.status,
                    "objective_value": optimisation_result.solver.objective_value,
                    "solve_time_seconds": optimisation_result.solver.runtime_seconds,
                    "variable_count": optimisation_result.model_stats.variable_count,
                    "binary_variable_count": optimisation_result.model_stats.binary_variable_count,
                    "constraint_count": optimisation_result.model_stats.constraint_count,
                    "scenario_count": optimisation_result.model_stats.scenario_count,
                    "horizon_steps": optimisation_result.model_stats.horizon_steps,
                },
                "actual_redispatch_models": actual_settlement_results[
                    [
                        "actual_path_id",
                        "solver_status",
                        "objective_value",
                        "solve_time_seconds",
                        "variable_count",
                        "binary_variable_count",
                        "constraint_count",
                    ]
                ].to_dict(orient="records"),
            },
        )
        save_json(run_dir, "input_manifest.json", _build_input_manifest(
            toy_case=toy_case,
            bid_price_grid_eur_per_mwh=bid_grid,
            actual_price_paths=actual_price_paths,
        ))

        figures_dir = run_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        selected_hours = list(pd.DatetimeIndex(optimisation_result.submitted_bids["delivery_start_utc"]).unique()[:2])
        plot_submitted_bid_curves_with_actual_overlays(
            submitted_bids=optimisation_result.submitted_bids,
            actual_price_paths=actual_price_paths,
            selected_hours=selected_hours,
            output_dir=figures_dir,
            filename="submitted_bid_curve_with_actual_overlays.png",
        )
        plot_actual_clearing_heatmap(
            actual_clearing=actual_clearing,
            output_dir=figures_dir,
            filename="actual_clearing_heatmap.png",
        )
        plot_submitted_cleared_rejected_energy(
            actual_clearing_by_hour=actual_clearing_by_hour,
            output_dir=figures_dir,
            filename="submitted_cleared_rejected_energy.png",
        )
        for actual_path_id, group in actual_redispatch_timeseries.groupby("actual_path_id", sort=True):
            plot_cleared_used_unused_electricity(
                redispatch=group,
                output_dir=figures_dir,
                filename=f"{actual_path_id}__cleared_used_unused.png",
                title=str(actual_path_id),
            )
        plot_actual_storage_trajectories(
            actual_redispatch_timeseries=actual_redispatch_timeseries,
            output_dir=figures_dir,
            filename="actual_storage_trajectories.png",
        )
        plot_expected_vs_realised_profit_distribution(
            scenario_economics=optimisation_result.scenario_economics,
            realised_summary=stochastic_vs_realised_summary,
            output_dir=figures_dir,
            filename="expected_vs_realised_profit_distribution.png",
        )

        readme_lines = [
            "# Stochastic Bidding Toy Backtest",
            "",
            "This Phase 4b run executes the full toy backtest loop:",
            "",
            "1. solve the Phase 4a stochastic hourly bidding MILP;",
            "2. submit one non-anticipative bid curve;",
            "3. clear that bid curve against toy realised actual prices;",
            "4. redispatch deterministically from realised cleared electricity;",
            "5. report expected and realised results separately.",
            "",
            "## Regularisation",
            "",
            f"- objective_with_regularisation: `{float(optimisation_result.summary['objective_with_regularisation'].iloc[0]):.6f}`",
            f"- expected_adjusted_profit_without_regularisation: `{float(optimisation_result.summary['expected_adjusted_profit_without_regularisation'].iloc[0]):.6f}`",
            f"- regularisation_term: `{float(optimisation_result.summary['regularisation_term'].iloc[0]):.6f}`",
            f"- regularisation_weight: `{float(optimisation_result.summary['regularisation_weight'].iloc[0]):.8f}`",
            "- The regularisation is only used to break degeneracy among never-clearing bids and should remain negligible.",
            "",
            "## Expected vs Realised",
            "",
            "```csv",
            stochastic_vs_realised_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Known Limitations",
            "",
            "- Toy scenarios only.",
            "- Toy realised actual price paths only.",
            "- Hourly and one-day only.",
            "- No real thesis-grade scenario integration, mFRR, exclusive group bids, or endogenous bid prices.",
        ]
        save_text(run_dir, "README_stochastic_bidding_backtest_toy.md", "\n".join(readme_lines))

    return ToyStochasticBacktestResult(
        optimisation_result=optimisation_result,
        actual_price_paths=actual_price_paths,
        actual_clearing=actual_clearing,
        actual_clearing_by_hour=actual_clearing_by_hour,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        actual_settlement_results=actual_settlement_results,
        stochastic_vs_realised_summary=stochastic_vs_realised_summary,
        scenario_objective_summary=scenario_objective_summary,
        run_dir=run_dir,
    )


def _model_stats_row(result: StochasticBiddingSolveResult) -> dict[str, Any]:
    return {
        "risk_measure": result.risk_measure,
        "cvar_alpha": result.cvar_alpha,
        "cvar_gamma": result.cvar_gamma,
        "solver_status": result.solver.status,
        "objective_value": result.solver.objective_value,
        "solve_time_seconds": result.solver.runtime_seconds,
        "mip_gap": result.solver.mip_gap,
        "variable_count": result.model_stats.variable_count,
        "binary_variable_count": result.model_stats.binary_variable_count,
        "constraint_count": result.model_stats.constraint_count,
        "scenario_count": result.model_stats.scenario_count,
        "horizon_steps": result.model_stats.horizon_steps,
        "timestep_hours": result.model_stats.timestep_hours,
    }


def run_toy_cvar_stochastic_bidding_sweep(
    *,
    config: HydrogenConfig | str | Path,
    toy_case: str = "cvar_stress",
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...] | None = None,
    cvar_alpha: float = 0.95,
    gamma_values: list[float] | tuple[float, ...] = (0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 1.00),
    selected_backtest_gammas: list[float] | tuple[float, ...] = (0.0, 0.25, 1.00),
    output_root: Path | None = None,
    write_outputs: bool = True,
) -> ToyCvarSweepResult:
    if toy_case in {"cvar_high_price_exposure", "cvar_overprocurement_unused_energy"}:
        run_config = build_phase5b_toy_case_config(config, toy_case=toy_case)
    else:
        run_config = build_phase5a_toy_config(config)
    if output_root is not None:
        run_config = replace(run_config, outputs=replace(run_config.outputs, root=Path(output_root)))

    scenarios = build_toy_hourly_scenario_set(toy_case)
    actual_price_paths = build_toy_realised_actual_price_paths(
        forecast_origin_utc=str(pd.Timestamp(scenarios["forecast_origin_utc"].iloc[0]).isoformat())
    )
    bid_grid = list(bid_price_grid_eur_per_mwh) if bid_price_grid_eur_per_mwh is not None else list(run_config.bidding.bid_price_grid_eur_per_mwh)
    gamma_list = [float(value) for value in gamma_values]
    selected_gamma_list = [float(value) for value in selected_backtest_gammas]

    run_dir: Path | None = None
    if write_outputs:
        _, run_dir = create_run_folder(run_config)
        save_config_resolved(run_dir, run_config)
        save_inputs_manifest(run_dir, [run_config.config_path])

    submitted_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_dispatch_rows: list[pd.DataFrame] = []
    scenario_result_rows: list[pd.DataFrame] = []
    summary_rows: list[pd.DataFrame] = []
    model_stats_rows: list[dict[str, Any]] = []
    backtest_rows: list[pd.DataFrame] = []

    for gamma in gamma_list:
        risk_measure = "risk_neutral" if abs(gamma) <= 1e-12 else "cvar"
        result = solve_stochastic_hourly_bidding(
            scenarios=scenarios,
            config=run_config,
            run_id=f"phase5a_gamma_{str(gamma).replace('.', 'p')}",
            bid_price_grid_eur_per_mwh=bid_grid,
            solver_log_path=str(run_dir / f"gamma_{str(gamma).replace('.', 'p')}__solver_log.txt") if run_dir is not None and run_config.outputs.save_solver_log else None,
            toy_case=toy_case,
            risk_measure=risk_measure,
            cvar_alpha=float(cvar_alpha),
            cvar_gamma=float(gamma),
        )
        submitted_rows.append(result.submitted_bids.assign(cvar_gamma=float(gamma), cvar_alpha=float(cvar_alpha), risk_measure=risk_measure))
        scenario_clearing_rows.append(result.scenario_clearing.assign(cvar_gamma=float(gamma), cvar_alpha=float(cvar_alpha), risk_measure=risk_measure))
        scenario_dispatch_rows.append(result.scenario_dispatch.assign(cvar_gamma=float(gamma), cvar_alpha=float(cvar_alpha), risk_measure=risk_measure))
        scenario_result_rows.append(result.scenario_economics.assign(cvar_gamma=float(gamma), cvar_alpha=float(cvar_alpha), risk_measure=risk_measure))
        summary_rows.append(result.summary.assign(cvar_gamma=float(gamma), cvar_alpha=float(cvar_alpha), risk_measure=risk_measure))
        model_stats_rows.append(_model_stats_row(result))

        if any(abs(gamma - selected_gamma) <= 1e-12 for selected_gamma in selected_gamma_list):
            backtest_risk_measure = "cvar"
            backtest = run_toy_stochastic_bidding_backtest(
                config=run_config,
                toy_case=toy_case,
                bid_price_grid_eur_per_mwh=bid_grid,
                write_outputs=False,
                risk_measure=backtest_risk_measure,
                cvar_alpha=float(cvar_alpha),
                cvar_gamma=float(gamma),
            )
            backtest_rows.append(
                backtest.stochastic_vs_realised_summary.assign(
                    cvar_gamma=float(gamma),
                    cvar_alpha=float(cvar_alpha),
                    risk_measure=risk_measure,
                )
            )

    submitted_bids = pd.concat(submitted_rows, ignore_index=True)
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True)
    scenario_dispatch = pd.concat(scenario_dispatch_rows, ignore_index=True)
    scenario_results = pd.concat(scenario_result_rows, ignore_index=True)
    summaries_by_gamma = pd.concat(summary_rows, ignore_index=True)
    model_stats_by_gamma = pd.DataFrame(model_stats_rows).sort_values("cvar_gamma").reset_index(drop=True)
    backtest_results = pd.concat(backtest_rows, ignore_index=True) if backtest_rows else pd.DataFrame()
    sweep_summary = compute_cvar_sweep_summary(
        summaries_by_gamma=summaries_by_gamma,
        scenario_clearing_by_gamma=scenario_clearing,
    )
    backtest_frontier = compute_cvar_backtest_frontier_metrics(backtest_results=backtest_results) if not backtest_results.empty else pd.DataFrame()

    if write_outputs and run_dir is not None:
        save_frame_csv(run_dir, "cvar_sweep_summary.csv", sweep_summary)
        save_frame_csv(run_dir, "cvar_scenario_results.csv", scenario_results)
        save_frame_parquet(run_dir, "cvar_submitted_bids.parquet", submitted_bids)
        save_frame_parquet(run_dir, "cvar_scenario_clearing.parquet", scenario_clearing)
        save_frame_parquet(run_dir, "cvar_scenario_dispatch.parquet", scenario_dispatch)
        save_frame_csv(run_dir, "cvar_backtest_results.csv", backtest_results)
        save_frame_csv(run_dir, "model_stats_by_gamma.csv", model_stats_by_gamma)
        save_json(
            run_dir,
            "input_manifest.json",
            {
                "scenario_source": "artificial_phase5a_toy",
                "actual_price_source": "artificial_phase4b_actual_paths",
                "toy_case": toy_case,
                "risk_measure": "cvar_sweep_with_gamma_zero_risk_neutral_baseline",
                "cvar_alpha": float(cvar_alpha),
                "gamma_values": gamma_list,
                "selected_backtest_gammas": selected_gamma_list,
                "bid_price_grid_eur_per_mwh": bid_grid,
                "known_limitations": [
                    "toy_scenarios_only",
                    "toy_actual_price_paths_only",
                    "hourly_only",
                    "single_delivery_day_only",
                    "no_real_thesis_grade_scenarios",
                    "no_mfrr",
                    "no_exclusive_group_bids",
                    "no_endogenous_bid_prices",
                ],
            },
        )

        figures_dir = run_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        plot_cvar_risk_return_frontier(
            sweep_summary=sweep_summary,
            output_dir=figures_dir,
            filename="cvar_risk_return_frontier.png",
        )
        plot_cvar_sweep_diagnostics(
            sweep_summary=sweep_summary,
            output_dir=figures_dir,
            filename="cvar_sweep_diagnostics.png",
        )
        plot_cvar_bid_firmness(
            sweep_summary=sweep_summary,
            output_dir=figures_dir,
            filename="cvar_bid_firmness.png",
        )
        plot_cvar_scenario_profit_by_gamma(
            scenario_results=scenario_results,
            output_dir=figures_dir,
            filename="cvar_scenario_profit_by_gamma.png",
        )
        plot_cvar_cleared_used_unused_by_gamma(
            sweep_summary=sweep_summary,
            output_dir=figures_dir,
            filename="cvar_cleared_used_unused_by_gamma.png",
        )
        if not backtest_results.empty:
            plot_cvar_realised_profit_comparison(
                backtest_results=backtest_results,
                output_dir=figures_dir,
                filename="cvar_actual_path_realised_profit_comparison.png",
            )

        gamma_zero_result = submitted_bids.loc[submitted_bids["cvar_gamma"].astype(float) == 0.0].copy()
        selected_hours = list(pd.DatetimeIndex(gamma_zero_result["delivery_start_utc"]).drop_duplicates()[:2])
        plot_submitted_bid_curves_with_actual_overlays(
            submitted_bids=gamma_zero_result.drop(columns=["cvar_gamma", "cvar_alpha", "risk_measure"]),
            actual_price_paths=actual_price_paths,
            selected_hours=selected_hours,
            output_dir=figures_dir,
            filename="gamma0_submitted_bid_curve_with_actual_overlays.png",
        )

        readme_lines = [
            "# CVaR Stochastic Bidding Toy Run",
            "",
            "This Phase 5a run validates the transparent linear CVaR formulation on artificial hourly scenarios.",
            "",
            f"- Toy case: `{toy_case}`",
            f"- CVaR alpha: `{float(cvar_alpha):.4f}`",
            f"- Gamma values: `{gamma_list}`",
            f"- Selected realised-path backtest gammas: `{selected_gamma_list}`",
            "- Scenario loss is defined as loss = - adjusted_profit.",
            "- The objective is expected_adjusted_profit - gamma * CVaR_loss.",
            "- Gamma = 0 is the preserved risk-neutral baseline.",
            "- Accepted electricity always pays actual or scenario market price, never the bid price.",
            "",
            "## Sweep Summary",
            "",
            "```csv",
            sweep_summary.to_csv(index=False).strip(),
            "```",
        ]
        if not backtest_results.empty:
            readme_lines.extend(
                [
                    "",
                    "## Selected Backtests",
                    "",
                    "```csv",
                    backtest_results.to_csv(index=False).strip(),
                    "```",
                ]
            )
        readme_lines.extend(
            [
                "",
                "## Known Limitations",
                "",
                "- Toy scenarios and toy realised price paths only.",
                "- Hourly and one-day only.",
                "- This sweep validates the formulation only; it is not gamma tuning.",
                "- No real thesis-grade scenario integration, mFRR, exclusive group bids, endogenous bid prices, or full EUPHEMIA.",
                "- The tiny bid regularisation only breaks degeneracy and should remain negligible.",
            ]
        )
        save_text(run_dir, "README_cvar_stochastic_bidding_toy.md", "\n".join(readme_lines))

    return ToyCvarSweepResult(
        scenarios=scenarios,
        actual_price_paths=actual_price_paths,
        sweep_summary=sweep_summary,
        scenario_results=scenario_results,
        submitted_bids=submitted_bids,
        scenario_clearing=scenario_clearing,
        scenario_dispatch=scenario_dispatch,
        backtest_results=backtest_results,
        backtest_frontier=backtest_frontier,
        model_stats_by_gamma=model_stats_by_gamma,
        run_dir=run_dir,
    )
