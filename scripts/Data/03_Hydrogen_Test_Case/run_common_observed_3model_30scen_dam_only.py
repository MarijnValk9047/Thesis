from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
import yaml

from hydrogen.bidding_backtest import run_real_scenario_bidding_dry_run
from hydrogen.full_year_repaired_lear_strict import _append_stochastic_payload_outputs, _build_runtime_summary
from hydrogen.lear_strict_cvar_opportunity_diagnostic import _load_artifact_daily_support
from hydrogen.optimisation.cache_manager import CacheManager
from hydrogen.optimisation.progress_reporting import ProgressPaths, ProgressReporter
from hydrogen.plant_parameters import HydrogenConfig, load_hydrogen_config
from hydrogen.run_registry import build_inputs_manifest, create_run_folder, save_inputs_manifest
from hydrogen.scenario_loader import resolve_artifact_specs
from hydrogen.weekly_band_emergency_selection import _build_emergency_import_summary, _compute_variant_bounds
from hydrogen.weekly_hard_band_decision import _accepted_solver_status, _actual_prices_from_day_frame, _payload_from_live_result
from hydrogen.weekly_hard_band_target import (
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_hard_band_settings,
    target_accounting_fields_from_bounds,
)


DEFAULT_ARTIFACT_IDS = (
    "hourly_common_observed_lear_strict_30scen",
    "hourly_common_observed_lear_fs3_30scen",
    "hourly_common_observed_xgboost_fs3_30scen",
)
DEFAULT_START_DATE = "2024-10-01"
DEFAULT_END_DATE = "2025-09-25"
DEFAULT_SCENARIO_CAP = 30
DEFAULT_ALPHA = 0.95
DEFAULT_GAMMA = 0.0
DEFAULT_EMERGENCY_IMPORT_PRICE = 3000.0
DEFAULT_RUN_SLUG = "common_observed_3model_30scen_dam_only"

ARTIFACT_LABELS = {
    "hourly_common_observed_lear_strict_30scen": "LEAR Strict D-only 1092 repaired anchor",
    "hourly_common_observed_lear_fs3_30scen": "LEAR FS3 promoted",
    "hourly_common_observed_xgboost_fs3_30scen": "XGBoost FS3 pruned candidate",
}

DISALLOWED_PATH_SNIPPETS = (
    "model_max_supported",
    "qh_anchor",
    "quarter_hour_anchor",
    "qh_bridge",
    "bridge_outputs",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the compact cached DAM-only common-observed 3-model 30-scenario hydrogen backtest."
    )
    parser.add_argument(
        "--config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
        help="Base hydrogen config path.",
    )
    parser.add_argument(
        "--scenario-catalog",
        required=True,
        help="Scenario catalog YAML containing the three common-observed artifacts.",
    )
    parser.add_argument(
        "--support-days-csv",
        required=True,
        help="Common-support scenario_count_checks.csv used to enforce the exact 307-day day whitelist.",
    )
    parser.add_argument(
        "--artifact-ids",
        nargs="+",
        default=list(DEFAULT_ARTIFACT_IDS),
        help="Exactly three artifact ids to run.",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--scenario-cap", type=int, default=DEFAULT_SCENARIO_CAP)
    parser.add_argument("--risk-measure", default="risk_neutral")
    parser.add_argument("--cvar-gamma", type=float, default=DEFAULT_GAMMA)
    parser.add_argument("--cvar-alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--emergency-import-price", type=float, default=DEFAULT_EMERGENCY_IMPORT_PRICE)
    parser.add_argument(
        "--output-root",
        default="scripts/Data/03_Hydrogen_Test_Case/runs",
        help="Root under which the governed run folder will be created.",
    )
    parser.add_argument("--run-slug", default=DEFAULT_RUN_SLUG)
    parser.add_argument(
        "--delivery-days",
        default="",
        help="Optional comma-separated delivery days to run instead of the full common-support window.",
    )
    return parser.parse_args()


def _to_path(value: str | Path, *, repo_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (repo_root / path).resolve()


def _ensure_three_artifacts(artifact_ids: list[str]) -> None:
    if len(artifact_ids) != 3:
        raise ValueError(f"Expected exactly three artifacts, got {artifact_ids!r}.")
    if len(set(str(value) for value in artifact_ids)) != 3:
        raise ValueError(f"Artifact ids must be unique, got {artifact_ids!r}.")


def _read_expected_delivery_days(
    *,
    support_days_csv: Path,
    start_date: str,
    end_date: str,
    artifact_ids: list[str],
    delivery_days_override: list[str] | None,
) -> tuple[list[str], pd.DataFrame]:
    frame = pd.read_csv(support_days_csv)
    required = {"candidate_key", "forecast_origin_utc", "delivery_day", "scenario_count"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns in {support_days_csv}: {sorted(missing)}")
    frame["delivery_day"] = pd.to_datetime(frame["delivery_day"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["scenario_count"] = pd.to_numeric(frame["scenario_count"], errors="raise").astype(int)
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    filtered = frame.loc[
        frame["delivery_day"].between(str(start_date), str(end_date))
    ].copy()
    if delivery_days_override:
        wanted = sorted(set(str(day) for day in delivery_days_override))
        filtered = filtered.loc[filtered["delivery_day"].isin(wanted)].copy()
    day_sets = {
        str(candidate_key): sorted(group["delivery_day"].astype(str).unique().tolist())
        for candidate_key, group in filtered.groupby("candidate_key", sort=True)
    }
    if len(set(tuple(days) for days in day_sets.values())) != 1:
        raise ValueError(f"Common-support CSV does not define equal support across models: {day_sets!r}")
    expected_days = sorted(filtered["delivery_day"].astype(str).unique().tolist())
    if not expected_days:
        raise ValueError("No delivery days selected from the common-support CSV.")
    counts_by_day = (
        filtered.groupby(["candidate_key", "delivery_day"], as_index=False)
        .agg(
            forecast_origin_count=("forecast_origin_utc", "nunique"),
            scenario_count=("scenario_count", "max"),
        )
        .sort_values(["candidate_key", "delivery_day"])
        .reset_index(drop=True)
    )
    if not counts_by_day["forecast_origin_count"].astype(int).eq(1).all():
        raise ValueError("Expected exactly one forecast origin per model-day in common support.")
    return expected_days, counts_by_day


def _build_run_config(
    *,
    base_config: HydrogenConfig,
    args: argparse.Namespace,
    artifact_ids: list[str],
) -> HydrogenConfig:
    outputs_root = _to_path(args.output_root, repo_root=base_config.repo_root)
    catalog_path = _to_path(args.scenario_catalog, repo_root=base_config.repo_root)
    config = replace(
        base_config,
        experiment=replace(
            base_config.experiment,
            name=str(args.run_slug),
            execution_mode="common_observed_full_period_dam_only",
            dataset_split="test",
            custom_start=str(args.start_date),
            custom_end=str(args.end_date),
        ),
        models=replace(
            base_config.models,
            include=tuple(str(value) for value in artifact_ids),
            scenario_catalog=catalog_path,
        ),
        strategies=("stochastic_risk_neutral",),
        risk=replace(
            base_config.risk,
            alpha=float(args.cvar_alpha),
            gamma=float(args.cvar_gamma),
            gamma_grid=(float(args.cvar_gamma),),
            gamma_selection="fixed_for_common_observed_3model_run",
        ),
        mfrr_capacity_pilot=replace(base_config.mfrr_capacity_pilot, enabled=False),
        outputs=replace(
            base_config.outputs,
            root=outputs_root,
            save_figures=False,
            save_timeseries=False,
            save_solver_log=False,
        ),
    )
    return config


def _write_resolved_config(run_dir: Path, config: HydrogenConfig) -> Path:
    target = run_dir / "resolved_config.yaml"
    payload = json.loads(json.dumps(asdict(config), default=str))
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def _artifact_label(artifact_id: str) -> str:
    return ARTIFACT_LABELS.get(str(artifact_id), str(artifact_id))


def _same_source_path(specs: list[Any]) -> Path:
    paths = {str(Path(spec.path).resolve()) for spec in specs}
    if len(paths) != 1:
        raise ValueError(f"Expected the three common-observed artifacts to share one source CSV, got {sorted(paths)!r}")
    return Path(next(iter(paths)))


def _support_cache_payload(
    *,
    shared_path: Path,
    artifact_specs: list[Any],
    expected_days: list[str],
    scenario_cap: int,
) -> dict[str, Any]:
    stat = shared_path.stat()
    return {
        "shared_scenario_path": str(shared_path),
        "shared_scenario_size_bytes": int(stat.st_size),
        "shared_scenario_modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "artifact_ids": [str(spec.artifact_key) for spec in artifact_specs],
        "model_ids": [str(spec.model_id) for spec in artifact_specs],
        "validation_modes": [str(spec.validation_mode) for spec in artifact_specs],
        "scenario_cap": int(scenario_cap),
        "expected_day_count": int(len(expected_days)),
        "expected_start_day": expected_days[0],
        "expected_end_day": expected_days[-1],
        "support_policy": "common_observed_3model_30scen_24h_days_v1",
    }


def _load_or_build_common_support_bundle(
    *,
    run_dir: Path,
    config: HydrogenConfig,
    artifact_ids: list[str],
    expected_days: list[str],
    scenario_cap: int,
) -> tuple[dict[str, dict[str, Any]], pd.DataFrame, dict[str, Any], str, list[Path]]:
    specs = resolve_artifact_specs(config)
    spec_by_artifact = {str(spec.artifact_key): spec for spec in specs}
    for artifact_id in artifact_ids:
        if artifact_id not in spec_by_artifact:
            raise KeyError(f"Artifact {artifact_id!r} not present in scenario catalog {config.models.scenario_catalog}.")
    ordered_specs = [spec_by_artifact[artifact_id] for artifact_id in artifact_ids]
    shared_path = _same_source_path(ordered_specs)
    cache_payload = _support_cache_payload(
        shared_path=shared_path,
        artifact_specs=ordered_specs,
        expected_days=expected_days,
        scenario_cap=scenario_cap,
    )
    cache_key = "co3m30"
    cache_manager = CacheManager(run_dir / "cache_sb")
    manifest_sources = build_inputs_manifest([shared_path]).get("files", [])
    cached = cache_manager.load_bundle(
        namespace="co",
        key=cache_key,
        expected_source_fingerprints=manifest_sources,
    )
    cache_status = "hit"
    if cached is None or cached.manifest.get("cache_payload") != cache_payload:
        cache_status = "written"
        raw_source = pd.read_csv(shared_path)
        frames: dict[str, pd.DataFrame] = {}
        for artifact_id, spec in zip(artifact_ids, ordered_specs, strict=True):
            scenarios, registry, selected_daily, _ = _load_artifact_daily_support(
                config=config,
                artifact_id=artifact_id,
                preloaded_scenarios=raw_source,
                pre_resolved_spec=spec,
            )
            selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(expected_days)].copy()
            frames[f"{artifact_id}__scenarios"] = scenarios
            frames[f"{artifact_id}__registry"] = registry
            frames[f"{artifact_id}__selected_daily"] = selected_daily
        cached = cache_manager.save_bundle(
            namespace="co",
            key=cache_key,
            frames=frames,
            manifest={
                "cache_payload": cache_payload,
                "source_fingerprints": manifest_sources,
            },
        )
    bundle: dict[str, dict[str, Any]] = {}
    summary_rows: list[dict[str, Any]] = []
    input_paths: list[Path] = [config.config_path, config.models.scenario_catalog, shared_path]
    for artifact_id in artifact_ids:
        spec = spec_by_artifact[artifact_id]
        scenarios = cached.frames[f"{artifact_id}__scenarios"].copy()
        registry = cached.frames[f"{artifact_id}__registry"].copy()
        selected_daily = cached.frames[f"{artifact_id}__selected_daily"].copy()
        selected_daily["delivery_day"] = pd.to_datetime(selected_daily["delivery_day"], errors="raise").dt.strftime("%Y-%m-%d")
        observed_days = sorted(selected_daily["delivery_day"].astype(str).unique().tolist())
        if observed_days != expected_days:
            raise ValueError(
                f"Artifact {artifact_id!r} does not match the enforced common-support days. "
                f"observed_start={observed_days[:1]} observed_end={observed_days[-1:]}"
            )
        if not selected_daily["scenario_count"].astype(int).eq(int(scenario_cap)).all():
            raise ValueError(f"Artifact {artifact_id!r} violates scenario_cap={scenario_cap}.")
        if not selected_daily["probability_sum"].astype(float).between(0.999999, 1.000001).all():
            raise ValueError(f"Artifact {artifact_id!r} has invalid daily probability sums.")
        day_map: dict[str, Any] = {}
        for row in selected_daily.to_dict(orient="records"):
            delivery_day = str(row["delivery_day"])
            origin = pd.Timestamp(pd.to_datetime(row["forecast_origin_utc"], utc=True, errors="raise"))
            day_scenarios = scenarios.loc[scenarios["forecast_origin_utc"].eq(origin)].copy()
            day_scenarios = day_scenarios.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)
            if day_scenarios.empty:
                raise ValueError(f"No scenario rows found for artifact={artifact_id}, delivery_day={delivery_day}.")
            actual_prices = _actual_prices_from_day_frame(day_scenarios)
            if actual_prices.shape[0] != 24:
                raise ValueError(f"Artifact {artifact_id!r} delivery_day={delivery_day} is not a 24-hour day.")
            if int(day_scenarios["scenario_id"].astype(str).nunique()) != int(scenario_cap):
                raise ValueError(f"Artifact {artifact_id!r} delivery_day={delivery_day} does not have {scenario_cap} scenarios.")
            day_map[delivery_day] = {
                "day_meta": row,
                "forecast_origin_utc": origin,
                "scenarios": day_scenarios,
                "actual_prices": actual_prices,
                "model_id": str(row.get("model_id", spec.model_id)),
                "model_label": _artifact_label(artifact_id),
                "validation_mode": str(row.get("validation_mode", spec.validation_mode)),
                "thesis_grade": bool(row.get("thesis_grade", True)),
                "forecast_origin_reconstruction_used": bool(row.get("forecast_origin_reconstruction_used", False)),
                "artifact_path": shared_path,
                "cache_status": cache_status,
            }
        bundle[artifact_id] = day_map
        summary_rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_id": str(spec.model_id),
                "model_label": _artifact_label(artifact_id),
                "scenario_path": str(shared_path),
                "cache_status": str(cache_status),
                "delivery_day_count": int(len(day_map)),
                "delivery_day_start": expected_days[0],
                "delivery_day_end": expected_days[-1],
                "scenario_rows": int(scenarios.shape[0]),
                "selected_rows": int(sum(item["scenarios"].shape[0] for item in day_map.values())),
                "scenario_count_mode": int(selected_daily["scenario_count"].mode().iloc[0]),
                "probability_sum_min": float(pd.to_numeric(selected_daily["probability_sum"], errors="coerce").min()),
                "probability_sum_max": float(pd.to_numeric(selected_daily["probability_sum"], errors="coerce").max()),
                "actual_hour_count_min": int(pd.to_numeric(selected_daily["actual_hour_count"], errors="coerce").min()),
                "actual_hour_count_max": int(pd.to_numeric(selected_daily["actual_hour_count"], errors="coerce").max()),
            }
        )
    return bundle, pd.DataFrame(summary_rows), cache_payload, cache_status, input_paths


def _week_rows_for_days(delivery_days: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = pd.DataFrame({"delivery_day": pd.to_datetime(pd.Series(delivery_days), errors="raise")})
    frame["week_start"] = frame["delivery_day"] - pd.to_timedelta(frame["delivery_day"].dt.weekday, unit="D")
    for week_start, group in frame.groupby("week_start", sort=True):
        ordered = group.sort_values("delivery_day").reset_index(drop=True)
        week_end = pd.Timestamp(week_start) + pd.Timedelta(days=6)
        rows.append(
            {
                "week_id": f"week_{pd.Timestamp(week_start).strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}",
                "week_label": f"{pd.Timestamp(week_start).strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
                "delivery_start_date": ordered["delivery_day"].min().strftime("%Y-%m-%d"),
                "delivery_end_date": ordered["delivery_day"].max().strftime("%Y-%m-%d"),
                "included_delivery_days": ordered["delivery_day"].dt.strftime("%Y-%m-%d").tolist(),
            }
        )
    return pd.DataFrame(rows)


def _prepare_validation_checks(
    *,
    config: HydrogenConfig,
    args: argparse.Namespace,
    artifact_ids: list[str],
    scenario_input_summary: pd.DataFrame,
    full_support_days: list[str],
    execution_days: list[str],
    support_days_csv: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_path = str(scenario_input_summary["scenario_path"].iloc[0]) if not scenario_input_summary.empty else ""
    rows.append({"check": "common_observed_path", "status": "pass" if "common_observed_comparison" in source_path else "fail", "details": source_path})
    rows.append({"check": "three_models", "status": "pass" if len(artifact_ids) == 3 else "fail", "details": str(artifact_ids)})
    rows.append({"check": "common_day_count_307", "status": "pass" if len(full_support_days) == 307 else "fail", "details": str(len(full_support_days))})
    rows.append({"check": "support_window", "status": "pass" if full_support_days[0] == DEFAULT_START_DATE and full_support_days[-1] == DEFAULT_END_DATE else "fail", "details": f"{full_support_days[0]}..{full_support_days[-1]}"})
    rows.append({"check": "execution_day_count", "status": "pass", "details": str(len(execution_days))})
    rows.append({"check": "execution_window", "status": "pass", "details": f"{execution_days[0]}..{execution_days[-1]}"})
    rows.append({"check": "scenario_cap_30", "status": "pass" if scenario_input_summary["scenario_count_mode"].astype(int).eq(int(args.scenario_cap)).all() else "fail", "details": str(args.scenario_cap)})
    rows.append({"check": "dam_only_mode", "status": "pass" if str(config.experiment.horizon_mode).strip().upper() == "D_ONLY" else "fail", "details": str(config.experiment.horizon_mode)})
    rows.append({"check": "hourly_only", "status": "pass" if str(config.experiment.granularity).strip().lower() == "hourly" else "fail", "details": str(config.experiment.granularity)})
    rows.append({"check": "risk_neutral_gamma_zero", "status": "pass" if str(args.risk_measure).strip().lower() == "risk_neutral" and abs(float(args.cvar_gamma)) <= 1e-12 else "fail", "details": f"risk_measure={args.risk_measure}; gamma={args.cvar_gamma}"})
    rows.append({"check": "mfrr_disabled", "status": "pass" if not bool(config.mfrr_capacity_pilot.enabled) else "fail", "details": f"enabled={config.mfrr_capacity_pilot.enabled}"})
    path_checks = []
    for snippet in DISALLOWED_PATH_SNIPPETS:
        present = snippet in source_path.lower() or snippet in str(support_days_csv).lower()
        rows.append({"check": f"disallowed_path_{snippet}", "status": "fail" if present else "pass", "details": source_path})
        path_checks.append(not present)
    output_root = str(config.outputs.root)
    rows.append({"check": "approved_output_location", "status": "pass" if "scripts\\Data\\03_Hydrogen_Test_Case\\runs" in output_root or "scripts/Data/03_Hydrogen_Test_Case/runs" in output_root else "fail", "details": output_root})
    rows.append({"check": "emergency_import_enabled", "status": "pass" if float(args.emergency_import_price) > 0.0 else "fail", "details": str(args.emergency_import_price)})
    return rows


def _model_summary_from_daily(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if daily_metrics.empty:
        return pd.DataFrame()
    for (artifact_id, model_id, model_label), group in daily_metrics.groupby(["artifact_id", "model_id", "model_label"], sort=False):
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_id": str(model_id),
                "model_label": str(model_label),
                "delivery_day_count": int(group["delivery_day"].astype(str).nunique()),
                "scenario_count": int(pd.to_numeric(group["scenario_count"], errors="coerce").max()),
                "realised_adjusted_profit_total_eur": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                "expected_adjusted_profit_total_eur": float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum()),
                "average_realised_adjusted_profit_eur": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").mean()),
                "hydrogen_sold_or_compressed_total_kg": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                "da_settlement_cost_total_eur": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
                "shortfall_total_kg": float(pd.to_numeric(group["shortfall_kg"], errors="coerce").sum()),
                "emergency_import_total_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "days_with_emergency_import": int(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0).gt(1e-9).sum()),
                "stochastic_optimal_days": int(group["solver_status"].map(_accepted_solver_status).sum()),
                "redispatch_feasible_days": int(group["actual_redispatch_feasible"].astype(bool).sum()),
                "validation_fail_count_total": int(pd.to_numeric(group["validation_fail_count"], errors="coerce").sum()),
                "total_solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
                "mean_solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").mean()),
                "max_variable_count": int(pd.to_numeric(group["variable_count"], errors="coerce").max()),
                "max_constraint_count": int(pd.to_numeric(group["constraint_count"], errors="coerce").max()),
            }
        )
    return pd.DataFrame(rows).sort_values("model_label").reset_index(drop=True)


def _feasibility_summary_from_daily(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if daily_metrics.empty:
        return pd.DataFrame()
    for (artifact_id, model_label), group in daily_metrics.groupby(["artifact_id", "model_label"], sort=False):
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "days_total": int(group.shape[0]),
                "stochastic_optimal_days": int(group["solver_status"].map(_accepted_solver_status).sum()),
                "actual_redispatch_feasible_days": int(group["actual_redispatch_feasible"].astype(bool).sum()),
                "all_days_feasible": bool(group["solver_status"].map(_accepted_solver_status).all() and group["actual_redispatch_feasible"].astype(bool).all()),
                "total_validation_fail_count": int(pd.to_numeric(group["validation_fail_count"], errors="coerce").sum()),
                "days_with_validation_fail": int(pd.to_numeric(group["validation_fail_count"], errors="coerce").fillna(0).gt(0).sum()),
                "daily_band_violations": int(pd.to_numeric(group["daily_band_violations"], errors="coerce").sum()),
                "shortfall_total_kg": float(pd.to_numeric(group["shortfall_kg"], errors="coerce").sum()),
                "max_shortfall_kg": float(pd.to_numeric(group["shortfall_kg"], errors="coerce").max()),
                "days_with_emergency_import": int(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0).gt(1e-9).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("model_label").reset_index(drop=True)


def _runtime_row(
    *,
    solve_stage: str,
    artifact_id: str,
    model_label: str,
    delivery_day: str | None,
    wall_time_seconds: float,
    used_cache: bool,
    solver_status: str,
) -> dict[str, Any]:
    return {
        "solve_stage": str(solve_stage),
        "artifact_id": str(artifact_id),
        "model_label": str(model_label),
        "gamma": float(DEFAULT_GAMMA),
        "week_id": "",
        "delivery_day": "" if delivery_day is None else str(delivery_day),
        "wall_time_seconds": float(wall_time_seconds),
        "used_cache": bool(used_cache),
        "solver_status": str(solver_status),
    }


def _write_frame(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _write_validation_report(
    *,
    run_dir: Path,
    validation_rows: list[dict[str, Any]],
    scenario_input_summary: pd.DataFrame,
    failure_log: pd.DataFrame,
    daily_metrics: pd.DataFrame,
) -> Path:
    lines = [
        "# Validation Report",
        "",
        "## Preflight Checks",
        "",
        "| Check | Status | Details |",
        "|---|---|---|",
    ]
    for row in validation_rows:
        lines.append(f"| {row['check']} | {row['status']} | {row['details']} |")
    lines.extend(
        [
            "",
            "## Scenario Input Summary",
            "",
            "```csv",
            scenario_input_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Failure Log",
            "",
            "```csv",
            (failure_log.to_csv(index=False).strip() if not failure_log.empty else "failure_stage,artifact_id,model_label,delivery_day,solver_status,details"),
            "```",
        ]
    )
    if not daily_metrics.empty:
        lines.extend(
            [
                "",
                "## Daily Outcome Snapshot",
                "",
                "```csv",
                daily_metrics.head(10).to_csv(index=False).strip(),
                "```",
            ]
        )
    target = run_dir / "validation_report.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> None:
    args = _parse_args()
    artifact_ids = [str(value) for value in args.artifact_ids]
    _ensure_three_artifacts(artifact_ids)
    if str(args.risk_measure).strip().lower() != "risk_neutral":
        raise ValueError("This runner is fixed to DAM-only risk-neutral mode for the common-observed comparison run.")
    if abs(float(args.cvar_gamma)) > 1e-12:
        raise ValueError("This runner is fixed to cvar_gamma=0.0 for the common-observed comparison run.")

    base_config = load_hydrogen_config(args.config)
    support_days_csv = _to_path(args.support_days_csv, repo_root=base_config.repo_root)
    delivery_days_override = [value.strip() for value in str(args.delivery_days).split(",") if value.strip()]
    full_support_days, support_day_counts = _read_expected_delivery_days(
        support_days_csv=support_days_csv,
        start_date=str(args.start_date),
        end_date=str(args.end_date),
        artifact_ids=artifact_ids,
        delivery_days_override=None,
    )
    execution_days = (
        delivery_days_override
        if delivery_days_override
        else list(full_support_days)
    )
    execution_days = sorted(execution_days)
    config = _build_run_config(base_config=base_config, args=args, artifact_ids=artifact_ids)
    run_id, run_dir = create_run_folder(config)
    _write_resolved_config(run_dir, config)
    save_inputs_manifest(run_dir, [config.config_path, config.models.scenario_catalog, support_days_csv])

    support_load_started = perf_counter()
    bundle, scenario_input_summary, support_cache_payload, support_cache_status, input_paths = _load_or_build_common_support_bundle(
        run_dir=run_dir,
        config=config,
        artifact_ids=artifact_ids,
        expected_days=execution_days,
        scenario_cap=int(args.scenario_cap),
    )
    support_load_seconds = perf_counter() - support_load_started

    validation_rows = _prepare_validation_checks(
        config=config,
        args=args,
        artifact_ids=artifact_ids,
        scenario_input_summary=scenario_input_summary,
        full_support_days=full_support_days,
        execution_days=execution_days,
        support_days_csv=support_days_csv,
    )

    physical_daily_max_kg = float(
        config.hydrogen_system.electrolyser_nominal_mw * 24.0 * config.hydrogen_system.h2_efficiency_kg_per_mwh
    )
    accounting_frame = build_included_day_prorated_weekly_accounting(
        included_delivery_days=full_support_days,
        daily_target_kg=float(config.economics.daily_target_kg),
        excluded_day_reasons={},
        target_accounting_policy=TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    )
    accounting_lookup = build_production_accounting_lookup(accounting_frame)
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(config.economics.daily_target_kg),
        daily_min_fraction=0.0,
        daily_max_fraction=float(physical_daily_max_kg / config.economics.daily_target_kg),
        target_accounting_policy=TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    )
    week_rows = _week_rows_for_days(full_support_days)
    week_lookup = {
        str(day): row
        for _, row in week_rows.iterrows()
        for day in row["included_delivery_days"]
    }

    progress = ProgressReporter(
        run_id=run_id,
        run_folder=run_dir,
        split="test",
        period_mode="common_observed_full_period",
        total_solves=len(execution_days) * len(artifact_ids),
        progress_paths=ProgressPaths(
            log_csv=run_dir / "aggregate_progress_log.csv",
            current_json=run_dir / "progress_current.json",
        ),
    )

    pending_store: dict[str, list[Any]] = {
        "daily_metrics": [],
        "validation_checks": [],
        "actual_settlement": [],
        "scenario_settlement": [],
        "submitted_bids": [],
        "actual_clearing": [],
        "actual_redispatch": [],
        "weekly_tracker": [],
        "runtime_diagnostics": [],
        "infeasibility_report": [],
    }
    failures: list[dict[str, Any]] = []
    stochastic_rows_consumed = 0
    runtime_rows: list[dict[str, Any]] = [
        _runtime_row(
            solve_stage="support_bundle_load",
            artifact_id="common_bundle",
            model_label="common_bundle",
            delivery_day=None,
            wall_time_seconds=float(support_load_seconds),
            used_cache=bool(support_cache_status == "hit"),
            solver_status="loaded",
        )
    ]

    for artifact_id in artifact_ids:
        model_label = _artifact_label(artifact_id)
        cumulative_before_kg = 0.0
        inventory_start_kg = float(config.hydrogen_system.storage_initial_kg)
        current_week_id = ""
        for delivery_day in execution_days:
            week_row = week_lookup[delivery_day]
            week_id = str(week_row["week_id"])
            if week_id != current_week_id:
                current_week_id = week_id
                cumulative_before_kg = 0.0
                inventory_start_kg = float(config.hydrogen_system.storage_initial_kg)
            accounting_day = accounting_lookup[delivery_day]
            bounds = _compute_variant_bounds(
                settings=settings,
                production_variant=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                cumulative_realised_h2_kg_before_today=float(cumulative_before_kg),
                days_remaining_in_week=None,
                physical_daily_max_kg=float(physical_daily_max_kg),
                accounting_day=accounting_day,
            )
            day_payload = bundle[artifact_id][delivery_day]
            day_started = perf_counter()
            try:
                result = run_real_scenario_bidding_dry_run(
                    config=config,
                    artifact_id=artifact_id,
                    forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                    max_origins=1,
                    output_root=run_dir,
                    strategy_name="stochastic_bid_risk_neutral",
                    dry_run_label=str(args.run_slug),
                    include_price_insensitive_comparison=False,
                    risk_measure="risk_neutral",
                    cvar_alpha=float(args.cvar_alpha),
                    cvar_gamma=float(args.cvar_gamma),
                    production_target_mode=PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
                    inventory_start_kg=float(inventory_start_kg),
                    reserve_kg=float(config.hydrogen_system.reserve_kg),
                    target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                    emergency_import_price_eur_per_mwh=float(args.emergency_import_price),
                    selected_scenarios_override=day_payload["scenarios"],
                    actual_prices_override=day_payload["actual_prices"],
                    loader_findings_override=(f"support_bundle_cache_status={support_cache_status}",),
                    input_cache_status=str(support_cache_status),
                    input_source_used="common_support_bundle",
                    raw_artifact_read_again=False,
                    write_outputs=False,
                )
                payload = _payload_from_live_result(result, model_id=str(day_payload["model_id"]))
                appended = _append_stochastic_payload_outputs(
                    pending_store=pending_store,
                    run_id=run_id,
                    artifact_id=artifact_id,
                    model_label=model_label,
                    week_id=week_id,
                    week_label=str(week_row["week_label"]),
                    delivery_day=delivery_day,
                    day_payload=day_payload,
                    day_meta=pd.Series(day_payload["day_meta"]),
                    week_series=pd.Series(
                        {
                            "week_id": str(week_row["week_id"]),
                            "week_label": str(week_row["week_label"]),
                            "regime_label": "common_observed_full_period",
                            "selection_reason": "common_observed_full_support",
                        }
                    ),
                    payload=payload,
                    gamma=float(args.cvar_gamma),
                    alpha=float(args.cvar_alpha),
                    emergency_import_price=float(args.emergency_import_price),
                    benchmark_profit_row=None,
                    perfect_foresight_profit_row=None,
                    bounds=bounds,
                    cumulative_before_kg=float(cumulative_before_kg),
                    inventory_start_kg=float(inventory_start_kg),
                )
                cumulative_before_kg = float(appended["cumulative_after_kg"])
                inventory_start_kg = float(appended["actual_summary"]["terminal_inventory_end_kg"])
                stochastic_rows_consumed += int(day_payload["scenarios"].shape[0])
                total_day_seconds = perf_counter() - day_started
                runtime_rows.append(
                    _runtime_row(
                        solve_stage="model_day_run",
                        artifact_id=artifact_id,
                        model_label=model_label,
                        delivery_day=delivery_day,
                        wall_time_seconds=float(total_day_seconds),
                        used_cache=True,
                        solver_status=str(payload["actual_settlement_results"].iloc[0]["solver_status"]),
                    )
                )
                build_seconds = float(result.optimisation_result.solver.model_build_time_seconds or 0.0)
                solver_seconds = float(result.optimisation_result.solver.solver_time_seconds or 0.0) + float(
                    result.actual_redispatch_solver.solver_time_seconds or 0.0
                )
                postprocess_seconds = max(0.0, float(total_day_seconds - build_seconds - solver_seconds))
                overall_status = (
                    "Optimal"
                    if _accepted_solver_status(result.optimisation_result.solver.status)
                    and _accepted_solver_status(result.actual_redispatch_solver.status)
                    else f"stochastic={result.optimisation_result.solver.status};redispatch={result.actual_redispatch_solver.status}"
                )
                progress.record_solve(
                    regime="dam_only_common_observed",
                    model=model_label,
                    delivery_day=delivery_day,
                    gamma=float(args.cvar_gamma),
                    build_seconds=float(build_seconds),
                    solver_seconds=float(solver_seconds),
                    postprocess_seconds=float(postprocess_seconds),
                    status=str(overall_status),
                    mip_gap=0.001 if _accepted_solver_status(result.optimisation_result.solver.status) else None,
                    variables=int(result.optimisation_result.model_stats.variable_count),
                    binaries=int(result.optimisation_result.model_stats.binary_variable_count),
                    constraints=int(result.optimisation_result.model_stats.constraint_count),
                    warning="",
                )
                fail_count = int(
                    result.validation_checks.loc[
                        result.validation_checks["status"].astype(str).eq("fail")
                    ].shape[0]
                )
                if not _accepted_solver_status(result.optimisation_result.solver.status) or not _accepted_solver_status(result.actual_redispatch_solver.status) or fail_count > 0:
                    failures.append(
                        {
                            "failure_stage": "solver_or_validation",
                            "artifact_id": artifact_id,
                            "model_label": model_label,
                            "delivery_day": delivery_day,
                            "solver_status": overall_status,
                            "details": f"validation_fail_count={fail_count}",
                        }
                    )
            except Exception as exc:
                progress.mark_failed(
                    regime="dam_only_common_observed",
                    model=model_label,
                    delivery_day=delivery_day,
                    warning=str(exc),
                )
                failures.append(
                    {
                        "failure_stage": "exception",
                        "artifact_id": artifact_id,
                        "model_label": model_label,
                        "delivery_day": delivery_day,
                        "solver_status": "exception",
                        "details": str(exc),
                    }
                )
                runtime_rows.append(
                    _runtime_row(
                        solve_stage="model_day_run",
                        artifact_id=artifact_id,
                        model_label=model_label,
                        delivery_day=delivery_day,
                        wall_time_seconds=float(perf_counter() - day_started),
                        used_cache=True,
                        solver_status="exception",
                    )
                )
                break

    daily_metrics = (
        pd.concat([frame for frame in pending_store["daily_metrics"]], ignore_index=True)
        if pending_store["daily_metrics"]
        else pd.DataFrame()
    )
    runtime_diagnostics = pd.DataFrame(runtime_rows)
    runtime_summary = _build_runtime_summary(runtime_diagnostics)
    model_summary = _model_summary_from_daily(daily_metrics)
    feasibility_summary = _feasibility_summary_from_daily(daily_metrics)
    emergency_import_summary = (
        _build_emergency_import_summary(daily_metrics)
        if not daily_metrics.empty
        else pd.DataFrame(
            columns=[
                "artifact_id",
                "model_label",
                "gamma",
                "production_variant",
                "total_emergency_import_mwh",
                "total_emergency_import_cost",
                "total_emergency_import_hours",
                "days_with_emergency_import",
                "emergency_import_share_of_used_energy",
            ]
        )
    )
    if not daily_metrics.empty and "production_variant" not in daily_metrics.columns:
        daily_metrics["production_variant"] = PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF
    failure_log = pd.DataFrame(
        failures,
        columns=["failure_stage", "artifact_id", "model_label", "delivery_day", "solver_status", "details"],
    )

    _write_frame(run_dir / "model_day_metrics.csv", daily_metrics.sort_values(["model_label", "delivery_day"]).reset_index(drop=True))
    _write_frame(run_dir / "model_summary_metrics.csv", model_summary)
    _write_frame(run_dir / "feasibility_summary.csv", feasibility_summary)
    _write_frame(run_dir / "emergency_import_summary.csv", emergency_import_summary)
    _write_frame(run_dir / "runtime_summary.csv", runtime_summary)
    _write_json(run_dir / "runtime_summary.json", runtime_summary.to_dict(orient="records"))
    _write_frame(run_dir / "scenario_input_summary.csv", scenario_input_summary)
    _write_json(run_dir / "scenario_input_summary.json", scenario_input_summary.to_dict(orient="records"))
    _write_frame(run_dir / "failure_log.csv", failure_log)
    _write_validation_report(
        run_dir=run_dir,
        validation_rows=validation_rows,
        scenario_input_summary=scenario_input_summary,
        failure_log=failure_log,
        daily_metrics=daily_metrics,
    )

    run_manifest = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "execution_mode": "common_observed_full_period_dam_only",
        "risk_measure": "risk_neutral",
        "cvar_alpha": float(args.cvar_alpha),
        "cvar_gamma": float(args.cvar_gamma),
        "target_mode": PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
        "model_target_formulation": "weekly_hard_band_target",
        "target_accounting_policy": TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
        "emergency_import_enabled": True,
        "emergency_import_price_eur_per_mwh": float(args.emergency_import_price),
        "artifact_ids": artifact_ids,
        "model_labels": [_artifact_label(value) for value in artifact_ids],
        "full_support_delivery_day_count": int(len(full_support_days)),
        "full_support_day_start": full_support_days[0],
        "full_support_day_end": full_support_days[-1],
        "execution_delivery_day_count": int(len(execution_days)),
        "execution_day_start": execution_days[0],
        "execution_day_end": execution_days[-1],
        "scenario_cap": int(args.scenario_cap),
        "scenario_rows_consumed": int(stochastic_rows_consumed),
        "shared_support_cache_status": str(support_cache_status),
        "shared_support_cache_payload": support_cache_payload,
        "validation_checks": validation_rows,
        "inputs_manifest": build_inputs_manifest(input_paths + [support_days_csv]),
        "support_day_counts": support_day_counts.to_dict(orient="records"),
        "output_files": [
            "run_manifest.json",
            "resolved_config.yaml",
            "aggregate_progress_log.csv",
            "runtime_summary.csv",
            "runtime_summary.json",
            "model_day_metrics.csv",
            "model_summary_metrics.csv",
            "feasibility_summary.csv",
            "emergency_import_summary.csv",
            "scenario_input_summary.csv",
            "scenario_input_summary.json",
            "validation_report.md",
            "failure_log.csv",
        ],
    }
    _write_json(run_dir / "run_manifest.json", run_manifest)

    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id}, indent=2))


if __name__ == "__main__":
    main()
