from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .benchmarks import run_price_insensitive_heuristic
from .bidding import dispatch_schedule_to_one_block_bid_curve
from .bidding_backtest import run_real_scenario_bidding_dry_run
from .clearing import aggregate_cleared_energy, clear_hourly_bids
from .lear_strict_cvar_opportunity_diagnostic import _load_artifact_daily_support
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .production_target import (
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    validate_target_accounting_policy,
)
from .redispatch import solve_actual_redispatch_from_cleared_energy
from .run_registry import (
    build_inputs_manifest,
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs
from .selected_week_smoke import TOLERANCE, _label_for_artifact, _validation_row
from .weekly_band_emergency_selection import (
    _build_cvar_validation_checks,
    _build_skipped_daily_metric,
    _build_emergency_import_summary,
    _compute_variant_bounds,
    _run_perfect_foresight_week_variant,
)
from .weekly_hard_band_decision import (
    _accepted_solver_status,
    _actual_prices_from_day_frame,
    _build_phase_e4_config,
    _build_stochastic_daily_metric,
    _load_cached_day_payload,
    _payload_from_live_result,
    _save_parquet_if_possible,
)
from .weekly_hard_band_target import (
    TARGET_MODE_WEEKLY_HARD_BAND,
    PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF,
    WeeklyHardBandSettings,
    build_included_day_prorated_weekly_accounting,
    build_production_accounting_lookup,
    build_weekly_accounting_exclusion_reason_map,
    build_weekly_hard_band_settings,
    daily_frame_matches_accounting,
    target_accounting_fields_from_bounds,
)


PHASE_E5_ARTIFACT = "hourly_lear_strict_donly_1092_repaired_support_tail_calibrated_v1"
PHASE_E5_ALPHA = 0.95
PHASE_E5_GAMMAS = (0.0, 0.25)
PHASE_E5D_EXTENSION_GAMMA = 0.05
PHASE_E5_ALLOWED_GAMMAS = tuple(sorted(set(PHASE_E5_GAMMAS + (PHASE_E5D_EXTENSION_GAMMA,))))
PHASE_E5_TARGET_MODE = PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF
PHASE_E5_REPORTING_MODE = "machine_only"
PHASE_E5_EMERGENCY_IMPORT_PRICE = 3000.0
DEFAULT_PHASE_E5_RUN_SLUG = "phase_e5_full_year_repaired_lear_strict_g0_g025_band_off"
PERSIST_SCENARIO_CLEARING_CHECKPOINT = False


@dataclass(frozen=True)
class PhaseE5FullYearResult:
    run_dir: Path
    support_preflight: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    monthly_metrics: pd.DataFrame
    annual_metrics_by_gamma: pd.DataFrame
    emergency_import_summary: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    perfect_foresight_metrics: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    runtime_summary: pd.DataFrame


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    frame.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, default=str))


def _safe_read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, **kwargs)
    except Exception:
        return pd.DataFrame()


def _cache_key_payload(*, artifact_id: str, spec: Any, config: HydrogenConfig) -> dict[str, Any]:
    stat = spec.path.stat()
    return {
        "artifact_id": str(artifact_id),
        "artifact_path": str(spec.path),
        "artifact_size_bytes": int(stat.st_size),
        "artifact_modified_utc": pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").isoformat(),
        "model_id": str(spec.model_id),
        "dataset_split": spec.dataset_split,
        "granularity": spec.granularity,
        "validation_mode": str(spec.validation_mode),
        "allow_forecast_origin_reconstruction": bool(spec.allow_forecast_origin_reconstruction),
        "horizon_mode": str(config.experiment.horizon_mode).strip().upper(),
        "support_policy": "d_only_24h_selected_daily_v1",
    }


def _cache_key_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _load_pickle_or_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)


def _write_pickle_or_parquet(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path = path.with_suffix(".parquet")
    pickle_path = path.with_suffix(".pkl")
    if parquet_path.exists():
        parquet_path.unlink()
    if pickle_path.exists():
        pickle_path.unlink()
    try:
        tmp_path = parquet_path.with_name(f"{parquet_path.name}.tmp")
        frame.to_parquet(tmp_path, index=False)
        tmp_path.replace(parquet_path)
        return parquet_path
    except Exception:
        tmp_path = pickle_path.with_name(f"{pickle_path.name}.tmp")
        frame.to_pickle(tmp_path)
        tmp_path.replace(pickle_path)
        return pickle_path


def _physical_daily_max_kg(config: HydrogenConfig) -> float:
    return float(
        config.hydrogen_system.electrolyser_nominal_mw
        * 24.0
        * config.hydrogen_system.h2_efficiency_kg_per_mwh
    )


def _local_day_hour_count(delivery_day: str) -> int:
    start_day = pd.Timestamp(str(delivery_day))
    local_start = pd.Timestamp(start_day.date()).tz_localize("Europe/Amsterdam")
    local_next = pd.Timestamp((start_day + pd.Timedelta(days=1)).date()).tz_localize("Europe/Amsterdam")
    return int((local_next.tz_convert("UTC") - local_start.tz_convert("UTC")).total_seconds() / 3600.0)


def _find_latest_e5_resume_dir(root: Path, run_slug: str) -> Path | None:
    candidates = [
        path
        for path in root.glob(f"*_{run_slug}")
        if path.is_dir() and (path / "support_preflight.csv").exists()
    ]
    if not candidates:
        return None

    def _registry_progress(path: Path) -> tuple[int, str]:
        registry_path = path / "cache" / "stochastic_day_registry.csv"
        if not registry_path.exists():
            return 0, path.name
        try:
            progress = int(pd.read_csv(registry_path).shape[0])
        except Exception:
            progress = 0
        return progress, path.name

    return sorted(candidates, key=_registry_progress)[-1]


def _load_or_build_support_cache(
    *,
    run_dir: Path,
    config: HydrogenConfig,
    artifact_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Any, str]:
    artifact_config = replace(config, models=replace(config.models, include=(str(artifact_id),)))
    spec = resolve_artifact_specs(artifact_config)[0]
    cache_payload = _cache_key_payload(artifact_id=artifact_id, spec=spec, config=artifact_config)
    cache_digest = _cache_key_digest(cache_payload)
    support_cache_dir = run_dir / "cache" / "support_cache"
    support_cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = support_cache_dir / f"{cache_digest}__meta.json"
    scenarios_candidates = [
        support_cache_dir / f"{cache_digest}__scenarios.parquet",
        support_cache_dir / f"{cache_digest}__scenarios.pkl",
    ]
    registry_candidates = [
        support_cache_dir / f"{cache_digest}__registry.parquet",
        support_cache_dir / f"{cache_digest}__registry.pkl",
    ]
    selected_candidates = [
        support_cache_dir / f"{cache_digest}__selected_daily.parquet",
        support_cache_dir / f"{cache_digest}__selected_daily.pkl",
    ]
    if meta_path.exists():
        try:
            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            cached_meta = {}
        scenario_path = next((path for path in scenarios_candidates if path.exists()), None)
        registry_path = next((path for path in registry_candidates if path.exists()), None)
        selected_path = next((path for path in selected_candidates if path.exists()), None)
        if cached_meta == cache_payload and scenario_path is not None and registry_path is not None and selected_path is not None:
            scenarios = _load_pickle_or_parquet(scenario_path)
            registry = _load_pickle_or_parquet(registry_path)
            selected_daily = _load_pickle_or_parquet(selected_path)
            print(f"[E5] support source=cache key={cache_digest}")
            return scenarios, registry, selected_daily, spec, "cache"

    raw_source = pd.read_csv(spec.path)
    scenarios, findings = load_scenarios_for_artifact(spec, config=artifact_config, frame_override=raw_source)
    print(f"[E5] support source=csv key={cache_digest}")
    for finding in findings:
        print(f"[E5] {finding}")
    scenarios, registry, selected_daily, spec = _load_artifact_daily_support(
        config=artifact_config,
        artifact_id=artifact_id,
        preloaded_scenarios=raw_source,
        pre_resolved_spec=spec,
    )
    scenario_path = _write_pickle_or_parquet(support_cache_dir / f"{cache_digest}__scenarios", scenarios)
    registry_path = _write_pickle_or_parquet(support_cache_dir / f"{cache_digest}__registry", registry)
    selected_path = _write_pickle_or_parquet(support_cache_dir / f"{cache_digest}__selected_daily", selected_daily)
    _atomic_write_json(
        meta_path,
        {
            **cache_payload,
            "scenario_cache_file": str(scenario_path.name),
            "registry_cache_file": str(registry_path.name),
            "selected_daily_cache_file": str(selected_path.name),
        },
    )
    return scenarios, registry, selected_daily, spec, "csv"


def _stochastic_checkpoint_paths(cache_dir: Path) -> dict[str, Path]:
    return {
        "registry": cache_dir / "stochastic_day_registry.csv",
        "daily_metrics": cache_dir / "stochastic_checkpoint_daily_metrics.csv",
        "actual_settlement": cache_dir / "stochastic_checkpoint_actual_settlement_results.csv",
        "scenario_settlement": cache_dir / "stochastic_checkpoint_scenario_settlement_results.csv",
        "validation_checks": cache_dir / "stochastic_checkpoint_validation_checks.csv",
        "actual_clearing": cache_dir / "stochastic_checkpoint_actual_clearing.csv",
        "actual_redispatch": cache_dir / "stochastic_checkpoint_actual_redispatch_timeseries.csv",
        "submitted_bids": cache_dir / "stochastic_checkpoint_submitted_bids.csv",
        "scenario_clearing": cache_dir / "stochastic_checkpoint_scenario_clearing.csv",
        "weekly_tracker": cache_dir / "stochastic_checkpoint_weekly_target_tracker.csv",
        "runtime_diagnostics": cache_dir / "stochastic_checkpoint_runtime_diagnostics.csv",
        "infeasibility_report": cache_dir / "stochastic_checkpoint_infeasibility_report.csv",
        "progress": cache_dir / "stochastic_progress_summary.csv",
    }


def _deduplicate_registry(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "week_id",
                "delivery_day",
                "artifact_id",
                "cvar_gamma",
                "day_run_dir",
                "forecast_origin_utc",
                "storage_kind",
                "solver_status",
                "actual_redispatch_solver_status",
                "committed_at_utc",
            ]
        )
    dedup = frame.copy()
    dedup["delivery_day"] = dedup["delivery_day"].astype(str)
    dedup["artifact_id"] = dedup["artifact_id"].astype(str)
    dedup["week_id"] = dedup["week_id"].astype(str)
    for column, default in [
        ("storage_kind", "day_run"),
        ("day_run_dir", ""),
        ("forecast_origin_utc", ""),
        ("solver_status", ""),
        ("actual_redispatch_solver_status", ""),
    ]:
        if column not in dedup.columns:
            dedup[column] = default
        dedup[column] = dedup[column].astype(str)
    if "committed_at_utc" not in dedup.columns:
        dedup["committed_at_utc"] = ""
    dedup = dedup.sort_values(["cvar_gamma", "delivery_day", "committed_at_utc", "day_run_dir"]).drop_duplicates(
        subset=["artifact_id", "cvar_gamma", "delivery_day"],
        keep="last",
    )
    return dedup.reset_index(drop=True)


def _rebuild_stochastic_registry_from_day_runs(run_dir: Path, *, artifact_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    day_root = run_dir / "day_runs"
    if not day_root.exists():
        return _deduplicate_registry(pd.DataFrame())
    for subdir in sorted([path for path in day_root.iterdir() if path.is_dir()]):
        manifest_path = subdir / "input_manifest.json"
        metrics_path = subdir / "metrics_summary.csv"
        actual_settlement_path = subdir / "actual_settlement_results.csv"
        if not manifest_path.exists() or not metrics_path.exists() or not actual_settlement_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metrics = pd.read_csv(metrics_path, nrows=1)
            actual = pd.read_csv(actual_settlement_path, nrows=1)
        except Exception:
            continue
        if metrics.empty or actual.empty:
            continue
        delivery_day = str(manifest.get("selected_delivery_day") or metrics.iloc[0].get("delivery_day") or "")
        gamma = float(manifest.get("cvar_gamma"))
        if not delivery_day:
            continue
        week_start = pd.Timestamp(delivery_day) - pd.Timedelta(days=int(pd.Timestamp(delivery_day).weekday()))
        week_end = week_start + pd.Timedelta(days=6)
        rows.append(
            {
                "week_id": f"week_{week_start.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}",
                "delivery_day": delivery_day,
                "artifact_id": str(artifact_id),
                "cvar_gamma": float(gamma),
                "day_run_dir": str(subdir),
                "forecast_origin_utc": str(manifest.get("selected_forecast_origin_utc", "")),
                "storage_kind": "day_run",
                "solver_status": str(metrics.iloc[0].get("solver_status", "")),
                "actual_redispatch_solver_status": str(actual.iloc[0].get("solver_status", "")),
                "committed_at_utc": pd.Timestamp(subdir.stat().st_mtime, unit="s", tz="UTC").isoformat(),
            }
        )
    return _deduplicate_registry(pd.DataFrame(rows))


def _expected_24h_days(
    *,
    test_start: str,
    test_end: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    included: list[str] = []
    dst_excluded: list[dict[str, Any]] = []
    for ts in pd.date_range(pd.Timestamp(test_start), pd.Timestamp(test_end), freq="D"):
        day = ts.strftime("%Y-%m-%d")
        hour_count = _local_day_hour_count(day)
        if hour_count == 24:
            included.append(day)
        else:
            dst_excluded.append({"delivery_day": day, "local_hour_count": int(hour_count)})
    return included, dst_excluded


def _week_manifest_from_days(included_days: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not included_days:
        return pd.DataFrame(
            columns=[
                "week_id",
                "week_label",
                "week_start",
                "week_end",
                "included_delivery_days",
                "included_delivery_day_count",
                "is_partial_week",
                "period_boundary_partial",
                "dst_excluded_days",
            ]
        )
    frame = pd.DataFrame({"delivery_day": pd.to_datetime(pd.Series(included_days), errors="raise")})
    frame["week_start"] = frame["delivery_day"] - pd.to_timedelta(frame["delivery_day"].dt.weekday, unit="D")
    for week_start, group in frame.groupby("week_start", sort=True):
        group_days = group["delivery_day"].dt.strftime("%Y-%m-%d").tolist()
        week_end = pd.Timestamp(week_start) + pd.Timedelta(days=6)
        full_days = pd.date_range(pd.Timestamp(week_start), week_end, freq="D").strftime("%Y-%m-%d").tolist()
        missing = [day for day in full_days if day not in group_days]
        rows.append(
            {
                "week_id": f"week_{pd.Timestamp(week_start).strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}",
                "week_label": f"{pd.Timestamp(week_start).strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
                "week_start": pd.Timestamp(week_start).strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "included_delivery_days": group_days,
                "included_delivery_day_count": int(len(group_days)),
                "is_partial_week": bool(len(group_days) != 7),
                "period_boundary_partial": bool(missing and (missing[0] < group_days[0] or missing[-1] > group_days[-1])),
                "dst_excluded_days": [day for day in missing if _local_day_hour_count(day) != 24],
            }
        )
    return pd.DataFrame(rows).sort_values("week_start").reset_index(drop=True)


def _stage_runtime_row(
    *,
    solve_stage: str,
    artifact_id: str,
    model_label: str,
    gamma: float | None,
    week_id: str | None,
    delivery_day: str | None,
    wall_time_seconds: float,
    used_cache: bool,
    solver_status: str,
) -> dict[str, Any]:
    return {
        "solve_stage": str(solve_stage),
        "artifact_id": str(artifact_id),
        "model_label": str(model_label),
        "gamma": np.nan if gamma is None else float(gamma),
        "week_id": "" if week_id is None else str(week_id),
        "delivery_day": "" if delivery_day is None else str(delivery_day),
        "wall_time_seconds": float(wall_time_seconds),
        "used_cache": bool(used_cache),
        "solver_status": str(solver_status),
    }


def _build_runtime_summary(runtime_diagnostics: pd.DataFrame) -> pd.DataFrame:
    if runtime_diagnostics.empty:
        return pd.DataFrame(columns=["section", "group", "metric", "value", "notes"])
    rows: list[dict[str, Any]] = []
    rows.append(
        {
            "section": "totals",
            "group": "all",
            "metric": "wall_time_seconds",
            "value": float(pd.to_numeric(runtime_diagnostics["wall_time_seconds"], errors="coerce").sum()),
            "notes": "",
        }
    )
    for stage, group in runtime_diagnostics.groupby("solve_stage", sort=False):
        group_wall = pd.to_numeric(group["wall_time_seconds"], errors="coerce")
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "count", "value": float(group.shape[0]), "notes": ""})
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "wall_time_seconds", "value": float(group_wall.sum()), "notes": ""})
        rows.append({"section": "solve_stage", "group": str(stage), "metric": "mean_wall_time_seconds", "value": float(group_wall.mean()), "notes": ""})
    for gamma, group in runtime_diagnostics.loc[runtime_diagnostics["gamma"].notna()].groupby("gamma", sort=True):
        rows.append(
            {
                "section": "gamma",
                "group": f"{float(gamma):.2f}",
                "metric": "wall_time_seconds",
                "value": float(pd.to_numeric(group["wall_time_seconds"], errors="coerce").sum()),
                "notes": "stochastic stages only",
            }
        )
    for used_cache, group in runtime_diagnostics.groupby("used_cache", sort=False):
        rows.append(
            {
                "section": "cache_usage",
                "group": "true" if bool(used_cache) else "false",
                "metric": "count",
                "value": float(group.shape[0]),
                "notes": "",
            }
        )
    for rank, (_, row) in enumerate(
        runtime_diagnostics.sort_values("wall_time_seconds", ascending=False).head(10).iterrows(),
        start=1,
    ):
        rows.append(
            {
                "section": "slowest_stages",
                "group": f"rank_{rank}",
                "metric": "wall_time_seconds",
                "value": float(row["wall_time_seconds"]),
                "notes": f"{row['solve_stage']} | gamma={row['gamma']} | week_id={row['week_id']} | delivery_day={row['delivery_day']}",
            }
        )
    return pd.DataFrame(rows)


def _load_reference_frames_from_reuse_run(
    *,
    reuse_run_dir: Path,
    included_days: list[str],
) -> dict[str, Any]:
    if not reuse_run_dir.exists():
        raise FileNotFoundError(f"reuse_true_pf_from directory does not exist: {reuse_run_dir}")

    benchmark_metrics_path = reuse_run_dir / "benchmark_metrics.csv"
    if not benchmark_metrics_path.exists():
        raise FileNotFoundError(f"Missing benchmark metrics in reuse run: {benchmark_metrics_path}")
    benchmark_metrics = pd.read_csv(benchmark_metrics_path)
    benchmark_daily = benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("daily")].copy()
    benchmark_days = sorted(benchmark_daily["delivery_day"].astype(str).tolist())
    if benchmark_days != sorted(included_days):
        raise ValueError(
            "Reuse benchmark daily dates do not match the requested included days. "
            f"reuse_days={len(benchmark_days)} requested_days={len(included_days)}"
        )
    benchmark_daily_map = {
        (str(row.week_id), str(row.delivery_day)): pd.Series(row._asdict())
        for row in benchmark_daily.itertuples()
    }

    true_pf_daily_path = reuse_run_dir / "true_perfect_foresight_daily_metrics.csv"
    true_pf_weekly_path = reuse_run_dir / "true_perfect_foresight_weekly_metrics.csv"
    true_pf_monthly_path = reuse_run_dir / "true_perfect_foresight_monthly_metrics.csv"
    true_pf_annual_path = reuse_run_dir / "true_perfect_foresight_annual_metrics.csv"
    if not all(path.exists() for path in [true_pf_daily_path, true_pf_weekly_path, true_pf_monthly_path, true_pf_annual_path]):
        missing = [str(path) for path in [true_pf_daily_path, true_pf_weekly_path, true_pf_monthly_path, true_pf_annual_path] if not path.exists()]
        raise FileNotFoundError(f"Missing true-PF reuse files: {missing}")

    true_pf_daily = pd.read_csv(true_pf_daily_path)
    true_pf_daily["aggregation_level"] = "daily"
    true_pf_weekly = pd.read_csv(true_pf_weekly_path)
    true_pf_monthly = pd.read_csv(true_pf_monthly_path)
    true_pf_annual = pd.read_csv(true_pf_annual_path)
    perfect_foresight_metrics = pd.concat(
        [true_pf_daily, true_pf_weekly, true_pf_monthly, true_pf_annual],
        ignore_index=True,
        sort=False,
    )
    pf_days = sorted(true_pf_daily["delivery_day"].astype(str).tolist())
    if pf_days != sorted(included_days):
        raise ValueError(
            "Reuse true-PF daily dates do not match the requested included days. "
            f"reuse_days={len(pf_days)} requested_days={len(included_days)}"
        )
    perfect_foresight_daily_map = {
        (str(row.week_id), str(row.delivery_day)): pd.Series(row._asdict())
        for row in true_pf_daily.itertuples()
    }
    return {
        "benchmark_metrics": benchmark_metrics,
        "benchmark_daily_map": benchmark_daily_map,
        "perfect_foresight_metrics": perfect_foresight_metrics,
        "perfect_foresight_daily_map": perfect_foresight_daily_map,
        "true_pf_annual": true_pf_annual,
        "true_pf_weekly": true_pf_weekly,
    }


def _annual_with_true_pf_from_reference(
    *,
    annual_metrics_by_gamma: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    reuse_run_dir: Path,
) -> pd.DataFrame:
    annual = annual_metrics_by_gamma.copy().sort_values("gamma").reset_index(drop=True)
    updated_reference = reuse_run_dir / "annual_metrics_by_gamma_with_true_pf.csv"
    if updated_reference.exists():
        reference_annual = pd.read_csv(updated_reference)
        true_pf_profit = float(pd.to_numeric(reference_annual["true_pf_annual_profit"], errors="coerce").dropna().iloc[0])
    else:
        true_pf_annual = pd.read_csv(reuse_run_dir / "true_perfect_foresight_annual_metrics.csv")
        true_pf_profit = float(pd.to_numeric(true_pf_annual["realised_adjusted_profit"], errors="coerce").iloc[0])
    true_pf_weekly = pd.read_csv(reuse_run_dir / "true_perfect_foresight_weekly_metrics.csv")
    annual["true_pf_annual_profit"] = true_pf_profit
    annual["annual_value_captured_vs_true_pf"] = pd.to_numeric(annual["annual_realised_adjusted_profit"], errors="coerce") / true_pf_profit
    annual["annual_regret_vs_true_pf"] = true_pf_profit - pd.to_numeric(annual["annual_realised_adjusted_profit"], errors="coerce")
    true_pf_weekly = true_pf_weekly.sort_values("week_id").reset_index(drop=True)
    true_pf_weekly_profit = pd.to_numeric(true_pf_weekly["realised_adjusted_profit"], errors="coerce").to_numpy()

    def _weekly_regret_vector(gamma: float) -> np.ndarray:
        stochastic = (
            weekly_metrics.loc[
                pd.to_numeric(weekly_metrics["cvar_gamma"], errors="coerce").eq(float(gamma)),
                ["week_id", "realised_adjusted_profit"],
            ]
            .sort_values("week_id")
            .reset_index(drop=True)
        )
        stochastic_profit = pd.to_numeric(stochastic["realised_adjusted_profit"], errors="coerce").to_numpy()
        return true_pf_weekly_profit - stochastic_profit

    annual["mean_weekly_regret_vs_true_pf"] = annual["gamma"].map(
        lambda gamma: float(_weekly_regret_vector(float(gamma)).mean())
    )
    annual["worst_week_regret_vs_true_pf"] = annual["gamma"].map(
        lambda gamma: float(_weekly_regret_vector(float(gamma)).max())
    )
    annual["true_pf_emergency_import_mwh"] = 0.0
    annual["true_pf_rejected_energy_mwh"] = 0.0
    annual["true_pf_unused_energy_mwh"] = 0.0
    annual["emergency_import_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_emergency_import_mwh"], errors="coerce")
    annual["rejected_energy_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_rejected_energy"], errors="coerce")
    annual["unused_energy_gap_vs_true_pf_mwh"] = pd.to_numeric(annual["total_unused_cleared_energy"], errors="coerce")
    annual["updated_gamma_recommendation"] = annual["recommendation"]
    annual["recommendation_changed"] = False
    return annual


def _build_gamma_extension_comparison(
    *,
    extension_run_dir: Path,
    baseline_run_dir: Path,
    extension_annual_with_true_pf: pd.DataFrame,
) -> None:
    baseline_annual = pd.read_csv(baseline_run_dir / "annual_metrics_by_gamma_with_true_pf.csv")
    baseline_annual = baseline_annual.loc[
        pd.to_numeric(baseline_annual["gamma"], errors="coerce").isin([0.0, 0.25])
    ].copy()
    combined = pd.concat([baseline_annual, extension_annual_with_true_pf], ignore_index=True, sort=False)
    combined["gamma"] = pd.to_numeric(combined["gamma"], errors="coerce")
    combined = combined.sort_values("gamma").reset_index(drop=True)

    realised = pd.to_numeric(combined["annual_realised_adjusted_profit"], errors="coerce")
    max_realised = float(realised.max())
    gamma0 = combined.loc[np.isclose(combined["gamma"], 0.0)].head(1)
    gamma005 = combined.loc[np.isclose(combined["gamma"], 0.05)].head(1)

    labels: list[str] = []
    g0_profit = float(pd.to_numeric(gamma0["annual_realised_adjusted_profit"], errors="coerce").iloc[0]) if not gamma0.empty else np.nan
    g0_tail = float(pd.to_numeric(gamma0["annual_cvar_tail_profit"], errors="coerce").iloc[0]) if not gamma0.empty else np.nan
    g0_worst = float(pd.to_numeric(gamma0["worst_scenario_profit"], errors="coerce").iloc[0]) if not gamma0.empty else np.nan
    g0_emergency = float(pd.to_numeric(gamma0["total_emergency_import_mwh"], errors="coerce").iloc[0]) if not gamma0.empty else np.nan
    g005_profit = float(pd.to_numeric(gamma005["annual_realised_adjusted_profit"], errors="coerce").iloc[0]) if not gamma005.empty else np.nan
    g005_tail = float(pd.to_numeric(gamma005["annual_cvar_tail_profit"], errors="coerce").iloc[0]) if not gamma005.empty else np.nan
    g005_worst = float(pd.to_numeric(gamma005["worst_scenario_profit"], errors="coerce").iloc[0]) if not gamma005.empty else np.nan
    g005_emergency = float(pd.to_numeric(gamma005["total_emergency_import_mwh"], errors="coerce").iloc[0]) if not gamma005.empty else np.nan

    moderate_candidate = bool(
        pd.notna(g005_profit)
        and pd.notna(g0_profit)
        and pd.notna(g005_tail)
        and pd.notna(g0_tail)
        and pd.notna(g005_worst)
        and pd.notna(g0_worst)
        and pd.notna(g005_emergency)
        and pd.notna(g0_emergency)
        and (g005_tail > g0_tail + 1e-6 or g005_worst > g0_worst + 1e-6)
        and ((g0_profit - g005_profit) <= max(150000.0, 0.01 * max(abs(g0_profit), 1.0)))
        and (g005_emergency <= g0_emergency + max(25.0, 0.25 * max(g0_emergency, 1.0)))
    )
    gamma0_default = bool(
        not gamma0.empty
        and np.isclose(g0_profit, max_realised)
        and bool(gamma0["feasible_all_days"].astype(bool).iloc[0])
        and bool(gamma0["weekly_targets_met"].astype(bool).iloc[0])
        and (pd.isna(g005_emergency) or g0_emergency <= g005_emergency + 1e-6)
    )

    for row in combined.itertuples():
        gamma_value = float(row.gamma)
        if np.isclose(gamma_value, 0.0):
            labels.append("primary_economic_default" if gamma0_default else "risk_neutral_reference")
        elif np.isclose(gamma_value, 0.05):
            labels.append("moderate_risk_candidate" if moderate_candidate else "moderate_risk_sensitivity")
        elif np.isclose(gamma_value, 0.25):
            dominates = (
                float(row.annual_cvar_tail_profit) >= max(pd.to_numeric(combined["annual_cvar_tail_profit"], errors="coerce")) - 1e-6
                and float(row.worst_scenario_profit) >= max(pd.to_numeric(combined["worst_scenario_profit"], errors="coerce")) - 1e-6
                and float(row.total_emergency_import_mwh) <= min(pd.to_numeric(combined["total_emergency_import_mwh"], errors="coerce")) + 1e-6
                and float(row.annual_realised_adjusted_profit) >= max_realised - max(50000.0, 0.005 * max(abs(max_realised), 1.0))
            )
            labels.append("strong_risk_candidate" if dominates else "strong_risk_sensitivity")
        else:
            labels.append("comparison_only")
    combined["recommendation_label"] = labels

    annual_export = combined[
        [
            "gamma",
            "annual_realised_adjusted_profit",
            "annual_expected_adjusted_profit",
            "true_pf_annual_profit",
            "annual_regret_vs_true_pf",
            "annual_value_captured_vs_true_pf",
            "mean_weekly_realised_profit",
            "worst_week_realised_profit",
            "annual_cvar_tail_profit",
            "worst_scenario_profit",
            "total_emergency_import_mwh",
            "emergency_import_cost",
            "number_of_emergency_import_days",
            "total_rejected_energy",
            "total_unused_cleared_energy",
            "mean_clearing_ratio",
            "feasible_all_days",
            "weekly_targets_met",
            "total_runtime_seconds",
            "recommendation_label",
        ]
    ].copy()
    annual_export = annual_export.rename(
        columns={
            "annual_realised_adjusted_profit": "realised_annual_profit",
            "annual_expected_adjusted_profit": "expected_annual_profit",
            "annual_regret_vs_true_pf": "regret_vs_true_pf",
            "annual_value_captured_vs_true_pf": "value_captured_vs_true_pf",
            "total_emergency_import_mwh": "emergency_import_mwh",
            "number_of_emergency_import_days": "emergency_import_days",
            "total_rejected_energy": "rejected_energy_mwh",
            "total_unused_cleared_energy": "unused_cleared_energy_mwh",
            "total_runtime_seconds": "runtime_seconds",
        }
    )
    save_frame_csv(extension_run_dir, "annual_metrics_gamma_000_005_025_with_true_pf.csv", annual_export)

    emergency_export = combined[
        [
            "gamma",
            "total_emergency_import_mwh",
            "emergency_import_cost",
            "number_of_emergency_import_days",
            "total_rejected_energy",
            "total_unused_cleared_energy",
            "mean_clearing_ratio",
            "feasible_all_days",
            "weekly_targets_met",
        ]
    ].copy().rename(
        columns={
            "total_emergency_import_mwh": "emergency_import_mwh",
            "number_of_emergency_import_days": "emergency_import_days",
            "total_rejected_energy": "rejected_energy_mwh",
            "total_unused_cleared_energy": "unused_cleared_energy_mwh",
        }
    )
    save_frame_csv(extension_run_dir, "emergency_import_gamma_000_005_025.csv", emergency_export)

    tradeoff = combined[
        [
            "gamma",
            "annual_realised_adjusted_profit",
            "annual_cvar_tail_profit",
            "worst_scenario_profit",
            "total_emergency_import_mwh",
            "emergency_import_cost",
            "annual_regret_vs_true_pf",
            "annual_value_captured_vs_true_pf",
            "recommendation_label",
        ]
    ].copy().rename(
        columns={
            "annual_realised_adjusted_profit": "realised_annual_profit",
            "total_emergency_import_mwh": "emergency_import_mwh",
            "annual_regret_vs_true_pf": "regret_vs_true_pf",
            "annual_value_captured_vs_true_pf": "value_captured_vs_true_pf",
        }
    )
    save_frame_csv(extension_run_dir, "gamma_tradeoff_summary.csv", tradeoff)

    lines = [
        "# Gamma 0.05 Extension",
        "",
        f"Baseline run reused for gamma=0 and gamma=0.25: {baseline_run_dir}",
        f"Extension run dir: {extension_run_dir}",
        "",
    ]
    for row in annual_export.itertuples(index=False):
        lines.extend(
            [
                f"## Gamma {float(row.gamma):.2f}",
                f"- realised annual profit: {float(row.realised_annual_profit):,.0f} EUR",
                f"- annual CVaR tail profit: {float(row.annual_cvar_tail_profit):,.0f} EUR",
                f"- worst scenario profit: {float(row.worst_scenario_profit):,.0f} EUR",
                f"- emergency import: {float(row.emergency_import_mwh):,.3f} MWh costing {float(getattr(row, 'emergency_import_cost')):,.0f} EUR",
                f"- regret vs true PF: {float(row.regret_vs_true_pf):,.0f} EUR",
                f"- recommendation label: {row.recommendation_label}",
                "",
            ]
        )
    default_row = annual_export.loc[annual_export["recommendation_label"].astype(str).eq("primary_economic_default")].head(1)
    if not default_row.empty:
        lines.append(f"Primary economic default remains gamma={float(default_row['gamma'].iloc[0]):.2f}.")
    elif moderate_candidate:
        lines.append("Gamma=0.05 is the main moderate-risk candidate, but not the primary economic default.")
    else:
        lines.append("Gamma=0.05 does not overturn the existing default.")
    save_text(extension_run_dir, "README_gamma_005_extension.md", "\n".join(lines) + "\n")

def _load_checkpoint_store(cache_dir: Path) -> dict[str, pd.DataFrame]:
    paths = _stochastic_checkpoint_paths(cache_dir)
    return {
        "registry": _deduplicate_registry(_safe_read_csv(paths["registry"])),
        "daily_metrics": _safe_read_csv(paths["daily_metrics"]),
        "actual_settlement": _safe_read_csv(paths["actual_settlement"]),
        "scenario_settlement": _safe_read_csv(paths["scenario_settlement"]),
        "validation_checks": _safe_read_csv(paths["validation_checks"]),
        "actual_clearing": _safe_read_csv(paths["actual_clearing"]),
        "actual_redispatch": _safe_read_csv(paths["actual_redispatch"]),
        "submitted_bids": _safe_read_csv(paths["submitted_bids"]),
        "scenario_clearing": (
            _safe_read_csv(paths["scenario_clearing"]) if PERSIST_SCENARIO_CLEARING_CHECKPOINT else pd.DataFrame()
        ),
        "weekly_tracker": _safe_read_csv(paths["weekly_tracker"]),
        "runtime_diagnostics": _safe_read_csv(paths["runtime_diagnostics"]),
        "infeasibility_report": _safe_read_csv(paths["infeasibility_report"]),
    }


def _append_or_replace(base: pd.DataFrame, new_rows: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    if new_rows.empty:
        return base.copy()
    if base.empty:
        combined = new_rows.copy()
    else:
        combined = pd.concat([base, new_rows], ignore_index=True)
    if not key_columns:
        return combined.reset_index(drop=True)
    return combined.drop_duplicates(subset=key_columns, keep="last").reset_index(drop=True)


def _progress_counts_from_registry(
    registry: pd.DataFrame,
    *,
    daily_metrics: pd.DataFrame | None = None,
    artifact_id: str,
    gammas: list[float],
    expected_days: list[str],
) -> pd.DataFrame:
    source = daily_metrics if daily_metrics is not None and not daily_metrics.empty else registry
    rows: list[dict[str, Any]] = []
    for gamma in gammas:
        group = source.loc[
            source["artifact_id"].astype(str).eq(str(artifact_id))
            & pd.to_numeric(source["cvar_gamma"], errors="coerce").eq(float(gamma))
        ].copy()
        completed_days = sorted(set(group["delivery_day"].astype(str).tolist()))
        expected_set = set(expected_days)
        remaining_days = sorted(expected_set.difference(completed_days))
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "gamma": float(gamma),
                "completed_solves": int(len(completed_days)),
                "remaining_solves": int(len(remaining_days)),
                "last_completed_day": completed_days[-1] if completed_days else "",
                "first_remaining_day": remaining_days[0] if remaining_days else "",
            }
        )
    return pd.DataFrame(rows)


def _flush_checkpoint_store(
    *,
    cache_dir: Path,
    existing_store: dict[str, pd.DataFrame],
    pending_store: dict[str, list[pd.DataFrame] | list[dict[str, Any]]],
    expected_days: list[str],
    artifact_id: str,
    gammas: list[float],
) -> dict[str, pd.DataFrame]:
    paths = _stochastic_checkpoint_paths(cache_dir)

    registry_pending = pd.DataFrame(pending_store["registry"])
    existing_store["registry"] = _deduplicate_registry(
        pd.concat([existing_store["registry"], registry_pending], ignore_index=True) if not registry_pending.empty else existing_store["registry"]
    )
    key_map = {
        "daily_metrics": ["artifact_id", "cvar_gamma", "delivery_day"],
        "actual_settlement": ["artifact_id", "cvar_gamma", "delivery_day", "actual_path_id"],
        "scenario_settlement": ["artifact_id", "cvar_gamma", "delivery_day", "scenario_id"],
        "validation_checks": ["artifact_id", "cvar_gamma", "delivery_day", "check_name", "severity"],
        "actual_clearing": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc"],
        "actual_redispatch": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc"],
        "submitted_bids": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc", "bid_price_eur_per_mwh"],
        "scenario_clearing": ["artifact_id", "cvar_gamma", "delivery_day", "delivery_start_utc", "scenario_id"],
        "weekly_tracker": ["artifact_id", "gamma", "delivery_day"],
        "runtime_diagnostics": ["solve_stage", "artifact_id", "gamma", "week_id", "delivery_day"],
        "infeasibility_report": ["artifact_id", "gamma", "delivery_day", "issue_type"],
    }
    for key, columns in key_map.items():
        if key == "scenario_clearing" and not PERSIST_SCENARIO_CLEARING_CHECKPOINT:
            existing_store[key] = pd.DataFrame()
            continue
        pending_frames = pending_store[key]
        if not pending_frames:
            pending_frame = pd.DataFrame()
        elif all(isinstance(item, pd.DataFrame) for item in pending_frames):
            pending_frame = pd.concat(pending_frames, ignore_index=True)
        else:
            normalized_rows: list[pd.DataFrame] = []
            for item in pending_frames:
                if isinstance(item, pd.DataFrame):
                    normalized_rows.append(item)
                else:
                    normalized_rows.append(pd.DataFrame([item]))
            pending_frame = pd.concat(normalized_rows, ignore_index=True) if normalized_rows else pd.DataFrame()
        existing_store[key] = _append_or_replace(existing_store[key], pending_frame, columns)

    _atomic_write_csv(paths["registry"], existing_store["registry"])
    _atomic_write_csv(paths["daily_metrics"], existing_store["daily_metrics"])
    _atomic_write_csv(paths["actual_settlement"], existing_store["actual_settlement"])
    _atomic_write_csv(paths["scenario_settlement"], existing_store["scenario_settlement"])
    _atomic_write_csv(paths["validation_checks"], existing_store["validation_checks"])
    _atomic_write_csv(paths["actual_clearing"], existing_store["actual_clearing"])
    _atomic_write_csv(paths["actual_redispatch"], existing_store["actual_redispatch"])
    _atomic_write_csv(paths["submitted_bids"], existing_store["submitted_bids"])
    if PERSIST_SCENARIO_CLEARING_CHECKPOINT:
        _atomic_write_csv(paths["scenario_clearing"], existing_store["scenario_clearing"])
    _atomic_write_csv(paths["weekly_tracker"], existing_store["weekly_tracker"])
    _atomic_write_csv(paths["runtime_diagnostics"], existing_store["runtime_diagnostics"])
    _atomic_write_csv(paths["infeasibility_report"], existing_store["infeasibility_report"])
    _atomic_write_csv(
        paths["progress"],
        _progress_counts_from_registry(
            existing_store["registry"],
            daily_metrics=existing_store["daily_metrics"],
            artifact_id=artifact_id,
            gammas=gammas,
            expected_days=expected_days,
        ),
    )
    return existing_store


def _append_stochastic_payload_outputs(
    *,
    pending_store: dict[str, list[pd.DataFrame] | list[dict[str, Any]]],
    run_id: str,
    artifact_id: str,
    model_label: str,
    week_id: str,
    week_label: str,
    delivery_day: str,
    day_payload: dict[str, Any],
    day_meta: pd.Series,
    week_series: pd.Series,
    payload: dict[str, Any],
    gamma: float,
    alpha: float,
    emergency_import_price: float,
    benchmark_profit_row: pd.Series | None,
    perfect_foresight_profit_row: pd.Series | None,
    bounds: WeeklyBandBounds,
    cumulative_before_kg: float,
    inventory_start_kg: float,
) -> dict[str, Any]:
    metric_row = _build_stochastic_daily_metric(
        run_id=run_id,
        artifact_id=artifact_id,
        model_label=model_label,
        validation_mode=str(day_payload["validation_mode"]),
        thesis_grade=bool(day_payload["thesis_grade"]),
        forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
        week_row=week_series,
        day_meta=day_meta,
        payload=payload,
        cvar_alpha=float(alpha),
        cvar_gamma=float(gamma),
        benchmark_profit_row=benchmark_profit_row,
        perfect_foresight_profit_row=perfect_foresight_profit_row,
        bounds=bounds,
        cumulative_before_kg=float(cumulative_before_kg),
    )
    actual_summary = payload["actual_settlement_results"].iloc[0]
    actual_redispatch = payload["actual_redispatch_timeseries"].copy()
    import_series = pd.to_numeric(actual_redispatch.get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0)
    emergency_import_mwh = float(import_series.sum())
    used_energy = float(pd.to_numeric(actual_summary["used_energy_mwh"], errors="coerce"))
    metric_row.update(
        {
            "target_mode": PHASE_E5_TARGET_MODE,
            "production_variant": PHASE_E5_TARGET_MODE,
            "emergency_import_enabled": True,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "emergency_import_mwh": float(actual_summary.get("emergency_import_mwh", emergency_import_mwh)),
            "emergency_import_cost": float(actual_summary.get("emergency_import_cost_eur", emergency_import_mwh * float(emergency_import_price))),
            "emergency_import_hours": int(import_series.gt(1e-9).sum()),
            "emergency_import_share_of_used_energy": float(emergency_import_mwh / used_energy) if used_energy > 0.0 else 0.0,
        }
    )
    metric_row.update(target_accounting_fields_from_bounds(bounds))
    pending_store["daily_metrics"].append(pd.DataFrame([metric_row]))

    validation_checks = payload["validation_checks"].loc[
        ~payload["validation_checks"]["check_name"].astype(str).eq("redispatch.production_target_and_shortfall_reported")
    ].copy()
    pending_store["validation_checks"].append(
        validation_checks.assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            regime_label="full_year_test",
            delivery_day=delivery_day,
            forecast_origin_utc=str(payload["forecast_origin_utc"]),
            cvar_alpha=float(alpha),
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
            target_mode=PHASE_E5_TARGET_MODE,
        )
    )
    pending_store["actual_settlement"].append(
        payload["actual_settlement_results"].assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            delivery_day=delivery_day,
            forecast_origin_utc=payload["forecast_origin_utc"],
            cvar_alpha=float(alpha),
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
            target_mode=PHASE_E5_TARGET_MODE,
        )
    )
    pending_store["scenario_settlement"].append(
        payload["scenario_settlement_results"].assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            delivery_day=delivery_day,
            forecast_origin_utc=payload["forecast_origin_utc"],
            cvar_alpha=float(alpha),
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
            target_mode=PHASE_E5_TARGET_MODE,
        )
    )
    pending_store["submitted_bids"].append(
        payload["submitted_bids"].assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            delivery_day=delivery_day,
            forecast_origin_utc=payload["forecast_origin_utc"],
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
        )
    )
    pending_store["actual_clearing"].append(
        payload["actual_clearing"].assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            delivery_day=delivery_day,
            forecast_origin_utc=payload["forecast_origin_utc"],
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
        )
    )
    pending_store["actual_redispatch"].append(
        payload["actual_redispatch_timeseries"].assign(
            artifact_id=artifact_id,
            model_label=model_label,
            week_id=week_id,
            week_label=week_label,
            delivery_day=delivery_day,
            forecast_origin_utc=payload["forecast_origin_utc"],
            cvar_gamma=float(gamma),
            production_variant=PHASE_E5_TARGET_MODE,
        )
    )
    if PERSIST_SCENARIO_CLEARING_CHECKPOINT:
        pending_store["scenario_clearing"].append(
            payload["scenario_clearing"].assign(
                artifact_id=artifact_id,
                model_label=model_label,
                week_id=week_id,
                week_label=week_label,
                delivery_day=delivery_day,
                forecast_origin_utc=payload["forecast_origin_utc"],
                cvar_gamma=float(gamma),
                production_variant=PHASE_E5_TARGET_MODE,
            )
        )
    actual_h2 = float(actual_summary["hydrogen_compressed_or_sold_kg"])
    cumulative_after = cumulative_before_kg + actual_h2
    tracker_frame = pd.DataFrame(
        [
            {
                "strategy": metric_row["strategy"],
                "artifact_id": artifact_id,
                "model_label": model_label,
                "gamma": float(gamma),
                "production_variant": PHASE_E5_TARGET_MODE,
                "week_id": week_id,
                "week_label": week_label,
                "delivery_day": delivery_day,
                "forecast_origin_utc": payload["forecast_origin_utc"],
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative_before_kg),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "hydrogen_sold_or_compressed_kg": actual_h2,
                "storage_start_kg": float(inventory_start_kg),
                "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"]),
                "solver_status": str(actual_summary["solver_status"]),
                **target_accounting_fields_from_bounds(bounds),
            }
        ]
    )
    pending_store["weekly_tracker"].append(tracker_frame)
    accepted_actual = _accepted_solver_status(actual_summary["solver_status"])
    if not accepted_actual:
        pending_store["infeasibility_report"].append(
            {
                "artifact_id": artifact_id,
                "model_label": model_label,
                "gamma": float(gamma),
                "week_id": week_id,
                "week_label": week_label,
                "delivery_day": delivery_day,
                "issue_type": "infeasible_actual_redispatch",
                "details": f"solver_status={actual_summary['solver_status']}",
            }
        )
    return {
        "tracker_row": tracker_frame.iloc[0],
        "actual_summary": actual_summary,
        "cumulative_after_kg": float(cumulative_after),
        "accepted_actual": bool(accepted_actual),
    }


def _load_selected_artifact_manifest(spec: Any) -> dict[str, Any]:
    manifest_path = spec.path.parent / "scenario_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _build_selected_artifact_manifest(
    *,
    config: HydrogenConfig,
    artifact_id: str,
    spec: Any,
    selected_daily: pd.DataFrame,
    test_start: str,
    test_end: str,
    included_days: list[str],
    dst_excluded_days: list[dict[str, Any]],
) -> dict[str, Any]:
    catalog_payload = json.loads((config.models.scenario_catalog).read_text(encoding="utf-8")) if False else None
    scenario_manifest = _load_selected_artifact_manifest(spec)
    file_manifest = build_inputs_manifest([spec.path]).get("files", [{}])[0]
    return {
        "artifact_id": str(artifact_id),
        "artifact_path": str(spec.path),
        "model_id": str(spec.model_id),
        "granularity": str(spec.granularity),
        "validation_mode": str(spec.validation_mode),
        "dataset_split": spec.dataset_split,
        "test_start": str(test_start),
        "test_end": str(test_end),
        "included_delivery_day_count": int(len(included_days)),
        "included_delivery_days_start": included_days[0] if included_days else "",
        "included_delivery_days_end": included_days[-1] if included_days else "",
        "dst_excluded_days": dst_excluded_days,
        "scenario_count_mode": int(selected_daily["scenario_count"].mode().iloc[0]) if not selected_daily.empty else 0,
        "probability_sum_min": float(pd.to_numeric(selected_daily["probability_sum"], errors="coerce").min()) if not selected_daily.empty else np.nan,
        "probability_sum_max": float(pd.to_numeric(selected_daily["probability_sum"], errors="coerce").max()) if not selected_daily.empty else np.nan,
        "file_manifest": file_manifest,
        "scenario_manifest": scenario_manifest,
    }


def _build_support_preflight(
    *,
    artifact_id: str,
    config: HydrogenConfig,
    spec: Any,
    selected_daily: pd.DataFrame,
    registry: pd.DataFrame,
    test_start: str,
    test_end: str,
    alpha: float,
    gamma_values: list[float],
    target_mode: str,
    target_accounting_policy: str,
) -> tuple[pd.DataFrame, list[str], list[dict[str, Any]]]:
    expected_days, dst_excluded = _expected_24h_days(test_start=test_start, test_end=test_end)
    selected_in_period = selected_daily.loc[selected_daily["delivery_day"].astype(str).between(str(test_start), str(test_end))].copy()
    observed_days = sorted(selected_in_period["delivery_day"].astype(str).tolist())
    missing_days = sorted(set(expected_days).difference(observed_days))
    extra_days = sorted(set(observed_days).difference(expected_days))
    registry_in_period = registry.loc[registry["delivery_day"].astype(str).between(str(test_start), str(test_end))].copy()
    duplicate_max = int(pd.to_numeric(registry_in_period["duplicate_row_count"], errors="coerce").fillna(0).max()) if not registry_in_period.empty else 0
    scenario_counts = sorted(pd.to_numeric(selected_in_period["scenario_count"], errors="coerce").dropna().unique().tolist())
    probability_min = float(pd.to_numeric(selected_in_period["probability_sum"], errors="coerce").min()) if not selected_in_period.empty else float("nan")
    probability_max = float(pd.to_numeric(selected_in_period["probability_sum"], errors="coerce").max()) if not selected_in_period.empty else float("nan")
    actual_hour_counts = sorted(pd.to_numeric(selected_in_period["actual_hour_count"], errors="coerce").dropna().unique().tolist())
    missing_actual_max = int(pd.to_numeric(selected_in_period["missing_actual_rows"], errors="coerce").fillna(0).max()) if not selected_in_period.empty else 0
    exclusion_map = build_weekly_accounting_exclusion_reason_map(
        included_delivery_days=observed_days,
        explicit_exclusions=[{**item, "reason": "dst_excluded"} for item in dst_excluded],
    )
    accounting_frame = build_included_day_prorated_weekly_accounting(
        included_delivery_days=observed_days,
        daily_target_kg=float(config.economics.daily_target_kg),
        excluded_day_reasons=exclusion_map,
        target_accounting_policy=target_accounting_policy,
    )
    physical_daily_max = _physical_daily_max_kg(config)
    week_summary = (
        accounting_frame.groupby("accounting_week_id", sort=True)
        .agg(
            included_days_in_week=("included_days_in_week", "first"),
            weekly_target_kg=("weekly_target_kg", "first"),
            is_boundary_week=("is_boundary_week", "first"),
        )
        .reset_index()
        if not accounting_frame.empty
        else pd.DataFrame(columns=["accounting_week_id", "included_days_in_week", "weekly_target_kg", "is_boundary_week"])
    )
    assigned_once_ok = bool(accounting_frame["delivery_day"].astype(str).nunique() == len(observed_days) == int(accounting_frame.shape[0])) if not accounting_frame.empty else False
    target_matches_included_ok = bool(
        week_summary.empty
        or (
            pd.to_numeric(week_summary["weekly_target_kg"], errors="coerce").round(9)
            == (pd.to_numeric(week_summary["included_days_in_week"], errors="coerce") * float(config.economics.daily_target_kg)).round(9)
        ).all()
    )
    complete_week_ok = bool(
        week_summary.loc[pd.to_numeric(week_summary["included_days_in_week"], errors="coerce").eq(7), "weekly_target_kg"].round(9).eq(7.0 * float(config.economics.daily_target_kg)).all()
    ) if not week_summary.empty else True
    partial_week_ok = bool(
        week_summary.loc[~pd.to_numeric(week_summary["included_days_in_week"], errors="coerce").eq(7), "weekly_target_kg"].round(9).eq(
            pd.to_numeric(
                week_summary.loc[~pd.to_numeric(week_summary["included_days_in_week"], errors="coerce").eq(7), "included_days_in_week"],
                errors="coerce",
            )
            * float(config.economics.daily_target_kg)
        ).all()
    ) if not week_summary.empty else True
    feasible_target_ok = bool(
        week_summary.empty
        or (
            pd.to_numeric(week_summary["weekly_target_kg"], errors="coerce")
            <= pd.to_numeric(week_summary["included_days_in_week"], errors="coerce") * float(physical_daily_max) + 1e-9
        ).all()
    )
    rows = [
        _validation_row(
            check_name="artifact_exists_in_scenario_catalog",
            status="pass" if str(artifact_id) in [spec.artifact_key] else "fail",
            details=f"artifact_id={artifact_id}; resolved_path={spec.path}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="catalog_validation_passes",
            status="pass",
            details=f"validation_mode={spec.validation_mode}; model_id={spec.model_id}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="period_support_covers_all_24h_delivery_days",
            status="pass" if not missing_days and not extra_days and len(observed_days) == len(expected_days) else "fail",
            details=(
                f"expected_24h_days={len(expected_days)}; observed_supported_days={len(observed_days)}; "
                f"missing_days={missing_days[:10]}; extra_days={extra_days[:10]}"
            ),
            severity="hard_fail",
        ),
        _validation_row(
            check_name="dst_excluded_days_explicit",
            status=(
                "pass"
                if bool(dst_excluded)
                and not set(observed_days).intersection({item["delivery_day"] for item in dst_excluded})
                else "fail"
            ),
            details="; ".join([f"{item['delivery_day']} ({item['local_hour_count']}h)" for item in dst_excluded]),
            severity="hard_fail",
        ),
        _validation_row(
            check_name="scenario_count_exactly_75_per_origin",
            status="pass" if scenario_counts == [75] else "fail",
            details=f"observed_scenario_counts={scenario_counts}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="scenario_probabilities_sum_to_1",
            status="pass" if probability_min >= 0.999999 and probability_max <= 1.000001 else "fail",
            details=f"probability_sum_min={probability_min:.12f}; probability_sum_max={probability_max:.12f}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="actual_prices_complete_for_included_days",
            status="pass" if actual_hour_counts == [24] and missing_actual_max == 0 else "fail",
            details=f"actual_hour_counts={actual_hour_counts}; max_missing_actual_rows={missing_actual_max}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="no_duplicate_scenario_rows",
            status="pass" if duplicate_max == 0 else "fail",
            details=f"max_duplicate_row_count={duplicate_max}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="gamma_grid_matches_requested_values",
            status="pass" if sorted(gamma_values) == sorted({float(value) for value in gamma_values}) else "fail",
            details=f"gammas={gamma_values}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="alpha_exactly_0p95",
            status="pass" if abs(float(alpha) - 0.95) <= 1e-12 else "fail",
            details=f"alpha={float(alpha):.6f}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="target_mode_exactly_weekly_hard_band_off",
            status="pass" if str(target_mode) == PHASE_E5_TARGET_MODE else "fail",
            details=f"target_mode={target_mode}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="target_accounting_policy_included_day_prorated_weekly_target",
            status="pass" if str(target_accounting_policy) == "included_day_prorated_weekly_target" else "fail",
            details=f"target_accounting_policy={target_accounting_policy}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="every_included_day_assigned_to_exactly_one_accounting_week",
            status="pass" if assigned_once_ok else "fail",
            details=f"included_days={len(observed_days)}; accounting_rows={int(accounting_frame.shape[0])}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="weekly_target_equals_included_days_times_daily_target",
            status="pass" if target_matches_included_ok else "fail",
            details=f"daily_target_kg={float(config.economics.daily_target_kg):.6f}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="complete_weeks_keep_full_7_day_target",
            status="pass" if complete_week_ok else "fail",
            details=f"daily_target_kg={float(config.economics.daily_target_kg):.6f}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="boundary_weeks_are_prorated_by_included_days",
            status="pass" if partial_week_ok else "fail",
            details=f"boundary_week_count={int(week_summary['is_boundary_week'].astype(bool).sum()) if not week_summary.empty else 0}",
            severity="hard_fail",
        ),
        _validation_row(
            check_name="accounting_targets_physically_feasible_for_included_days",
            status="pass" if feasible_target_ok else "fail",
            details=f"physical_daily_max_kg={float(physical_daily_max):.6f}",
            severity="hard_fail",
        ),
    ]
    return pd.DataFrame(rows), expected_days, dst_excluded


def _run_price_insensitive_week_variant(
    *,
    week_row: pd.Series,
    week_days: list[str],
    reference_days: dict[str, dict[str, Any]],
    config: HydrogenConfig,
    settings: WeeklyHardBandSettings,
    production_variant: str,
    physical_daily_max_kg: float,
    emergency_import_price: float,
    run_id: str,
    cache_path: Path,
    accounting_lookup: dict[str, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    week_accounting = pd.DataFrame(
        [accounting_lookup[str(day)].to_dict() for day in week_days if str(day) in accounting_lookup]
    ).sort_values("delivery_day").reset_index(drop=True)
    if cache_path.exists():
        cached = pd.read_csv(cache_path)
        tracker_path = cache_path.parent / f"{cache_path.stem}__tracker.csv"
        if (
            int(cached.loc[cached["aggregation_level"].astype(str).eq("daily")].shape[0]) == len(week_days)
            and tracker_path.exists()
            and daily_frame_matches_accounting(
                daily_frame=cached.loc[cached["aggregation_level"].astype(str).eq("daily")].copy(),
                accounting_frame=week_accounting,
                target_accounting_policy=settings.target_accounting_policy,
            )
        ):
            return cached, pd.read_csv(tracker_path)

    rows: list[dict[str, Any]] = []
    tracker_rows: list[dict[str, Any]] = []
    inventory_start = float(config.hydrogen_system.storage_initial_kg)
    cumulative = 0.0
    for delivery_day in week_days:
        day_payload = reference_days[delivery_day]
        accounting_day = accounting_lookup[delivery_day]
        bounds = _compute_variant_bounds(
            settings=settings,
            production_variant=production_variant,
            cumulative_realised_h2_kg_before_today=cumulative,
            days_remaining_in_week=None,
            physical_daily_max_kg=physical_daily_max_kg,
            accounting_day=accounting_day,
        )
        day_frame = day_payload["scenarios"]
        actual_prices = _actual_prices_from_day_frame(day_frame)
        benchmark = run_price_insensitive_heuristic(
            day_frame=day_frame,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            apply_terminal_value=True,
            terminal_reference_start_kg=inventory_start,
            target_hydrogen_min_kg=float(config.economics.daily_target_kg),
            solver_log_path=str(cache_path.parent / f"{delivery_day}__{production_variant}__benchmark_plan_solver_log.txt")
            if config.outputs.save_solver_log
            else None,
        )
        dispatch = benchmark.dispatch.copy()
        dispatch["forecast_origin_utc"] = day_payload["forecast_origin_utc"]
        dispatch["scenario_model"] = "price_insensitive_benchmark"
        bids = dispatch_schedule_to_one_block_bid_curve(
            dispatch,
            run_id=f"{run_id}__benchmark__{production_variant}__{delivery_day}",
            source_strategy="price_insensitive",
            bridge_strategy=f"price_insensitive_plan_first_market_cap::{production_variant}",
            bid_price_eur_per_mwh=float(config.bidding.price_insensitive_bid_price_eur_per_mwh),
            scenario_model="price_insensitive_benchmark",
            forecast_origin_utc=day_payload["forecast_origin_utc"],
        )
        actual_clearing = clear_hourly_bids(bids, actual_prices)
        actual_clearing_by_hour = aggregate_cleared_energy(actual_clearing)
        actual_clearing_by_hour["timestep_hours"] = float(config.delta_t_hours)
        redispatch = solve_actual_redispatch_from_cleared_energy(
            actual_clearing_by_hour,
            config=config,
            inventory_start_kg=inventory_start,
            reserve_kg=float(config.hydrogen_system.reserve_kg),
            target_hydrogen_kg=float(bounds.daily_lower_bound_kg),
            target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
            terminal_reference_start_kg=inventory_start,
            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
            emergency_import_price_eur_per_mwh=float(emergency_import_price),
            solver_log_path=cache_path.parent / f"{delivery_day}__{production_variant}__benchmark_redispatch_solver_log.txt"
            if config.outputs.save_solver_log
            else None,
        )
        summary = redispatch.summary.iloc[0]
        cumulative_after = cumulative + float(summary["hydrogen_compressed_or_sold_kg"])
        cleared_total = float(actual_clearing_by_hour["cleared_energy_mwh"].sum())
        submitted_total = float(actual_clearing_by_hour["submitted_energy_mwh"].sum())
        import_mwh = float(summary.get("emergency_import_mwh", 0.0))
        used_energy = float(summary["used_energy_mwh"])
        rows.append(
            {
                "run_id": str(run_id),
                "strategy": "price_insensitive_plan_first_market_cap",
                "aggregation_level": "daily",
                "target_mode": PHASE_E5_TARGET_MODE,
                "production_variant": str(production_variant),
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "delivery_day": str(delivery_day),
                "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]),
                "realised_adjusted_profit": float(summary["realised_adjusted_profit_eur"]),
                "expected_adjusted_profit": np.nan,
                "cleared_energy_mwh": cleared_total,
                "used_cleared_energy_mwh": float(summary["used_energy_mwh"]),
                "unused_cleared_energy_mwh": float(summary["unused_cleared_energy_mwh"]),
                "hydrogen_sold_or_compressed_kg": float(summary["hydrogen_compressed_or_sold_kg"]),
                "shortfall_kg": float(summary["shortfall_kg"]),
                "da_settlement_cost": float(summary["realised_DA_settlement_cost_eur"]),
                "hydrogen_revenue": float(summary["hydrogen_revenue_eur"]),
                "unused_energy_penalty": float(summary["unused_energy_penalty_eur"]),
                "shortfall_penalty": float(summary["shortfall_penalty_eur"]),
                "terminal_inventory_correction": float(summary["terminal_inventory_correction_eur"]),
                "average_actual_price_paid": float(summary["realised_DA_settlement_cost_eur"] / cleared_total) if cleared_total > 0.0 else np.nan,
                "solver_status": str(benchmark.solver_status),
                "solve_time_seconds": float(benchmark.solver_runtime_seconds),
                "submitted_energy_mwh": submitted_total,
                "rejected_energy_mwh": float(submitted_total - cleared_total),
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "weekly_target_met": False,
                "daily_band_violations": 0,
                "infeasible_redispatch_days": int(not _accepted_solver_status(summary["solver_status"])),
                "storage_min_kg": float(summary["storage_min_kg"]),
                "storage_max_kg": float(summary["storage_max_kg"]),
                "reserve_boundary_hits": int(summary["reserve_boundary_hits"]),
                "variable_count": benchmark.model_stats.variable_count if benchmark.model_stats is not None else np.nan,
                "binary_variable_count": benchmark.model_stats.binary_variable_count if benchmark.model_stats is not None else np.nan,
                "constraint_count": benchmark.model_stats.constraint_count if benchmark.model_stats is not None else np.nan,
                "emergency_import_enabled": True,
                "emergency_import_price_eur_per_mwh": float(emergency_import_price),
                "emergency_import_mwh": float(import_mwh),
                "emergency_import_cost": float(summary.get("emergency_import_cost_eur", import_mwh * float(emergency_import_price))),
                "emergency_import_hours": int(pd.to_numeric(redispatch.timeseries.get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0).gt(1e-9).sum()),
                "emergency_import_share_of_used_energy": float(import_mwh / used_energy) if used_energy > 0.0 else 0.0,
                **target_accounting_fields_from_bounds(bounds),
            }
        )
        tracker_rows.append(
            {
                "strategy": "price_insensitive_plan_first_market_cap",
                "artifact_id": "",
                "model_label": "Price insensitive benchmark",
                "gamma": np.nan,
                "production_variant": str(production_variant),
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "delivery_day": str(delivery_day),
                "forecast_origin_utc": day_payload["forecast_origin_utc"],
                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                "weekly_target_kg": float(bounds.weekly_target_kg),
                "cumulative_before_kg": float(cumulative),
                "cumulative_after_kg": float(cumulative_after),
                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                "hydrogen_sold_or_compressed_kg": float(summary["hydrogen_compressed_or_sold_kg"]),
                "storage_start_kg": float(inventory_start),
                "storage_end_kg": float(summary["terminal_inventory_end_kg"]),
                "solver_status": str(summary["solver_status"]),
                **target_accounting_fields_from_bounds(bounds),
            }
        )
        cumulative = cumulative_after
        inventory_start = float(summary["terminal_inventory_end_kg"])

    daily = pd.DataFrame(rows).sort_values("delivery_day").reset_index(drop=True)
    daily["weekly_target_met"] = bool(cumulative >= float(week_accounting["weekly_target_kg"].iloc[0]) - TOLERANCE)
    tracker = pd.DataFrame(tracker_rows).sort_values("delivery_day").reset_index(drop=True)
    save_frame_csv(cache_path.parent, cache_path.name, daily)
    save_frame_csv(cache_path.parent, f"{cache_path.stem}__tracker.csv", tracker)
    return daily, tracker


def _aggregate_stochastic_period(
    *,
    daily_metrics: pd.DataFrame,
    group_columns: list[str],
    aggregation_level: str,
    period_columns: dict[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in daily_metrics.groupby(group_columns, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_map = dict(zip(group_columns, keys, strict=True))
        submitted = float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum())
        cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
        used = float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum())
        realised = float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum())
        benchmark = float(pd.to_numeric(group["benchmark_profit"], errors="coerce").sum())
        perfect = float(pd.to_numeric(group["perfect_foresight_profit"], errors="coerce").sum())
        da_cost = float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum())
        high_bid_energy = float(pd.to_numeric(group["high_bid_energy_mwh"], errors="coerce").sum())
        market_cap_bid_energy = float(pd.to_numeric(group["market_cap_bid_energy_mwh"], errors="coerce").sum())
        row = {
            **key_map,
            **period_columns,
            "aggregation_level": str(aggregation_level),
            "artifact_id": str(group["artifact_id"].iloc[0]),
            "model_id": str(group["model_id"].iloc[0]),
            "model_label": str(group["model_label"].iloc[0]),
            "validation_mode": str(group["validation_mode"].iloc[0]),
            "thesis_grade": bool(group["thesis_grade"].iloc[0]),
            "strategy": str(group["strategy"].iloc[0]),
            "risk_mode": str(group["risk_mode"].iloc[0]),
            "target_mode": PHASE_E5_TARGET_MODE,
            "production_variant": PHASE_E5_TARGET_MODE,
            "cvar_alpha": float(pd.to_numeric(group["cvar_alpha"], errors="coerce").dropna().iloc[0]),
            "cvar_gamma": float(pd.to_numeric(group["cvar_gamma"], errors="coerce").dropna().iloc[0]),
            "number_of_delivery_days": int(group.shape[0]),
            "expected_adjusted_profit": float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum()),
            "realised_adjusted_profit": realised,
            "stochastic_minus_benchmark_profit": float(realised - benchmark),
            "perfect_foresight_profit": perfect,
            "value_captured_vs_perfect_foresight": float(realised / perfect) if abs(perfect) > 1e-9 else np.nan,
            "regret_vs_perfect_foresight": float(perfect - realised),
            "cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").sum()),
            "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()),
            "weekly_target_met": bool(group["weekly_target_met"].astype(bool).all()),
            "daily_band_violations": int(pd.to_numeric(group["daily_band_violations"], errors="coerce").fillna(0).sum()),
            "hydrogen_sold_or_compressed_kg": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
            "emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
            "emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
            "emergency_import_hours": int(pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0).sum()),
            "emergency_import_share_of_used_energy": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum() / used) if used > 0.0 else 0.0,
            "submitted_energy_mwh": submitted,
            "cleared_energy_mwh": cleared,
            "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
            "used_cleared_energy_mwh": used,
            "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
            "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
            "average_actual_price_paid": float(da_cost / cleared) if cleared > 0.0 else np.nan,
            "high_bid_share": float(high_bid_energy / submitted) if submitted > 0.0 else 0.0,
            "market_cap_bid_share": float(market_cap_bid_energy / submitted) if submitted > 0.0 else 0.0,
            "storage_min_kg": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()),
            "storage_max_kg": float(pd.to_numeric(group["storage_max_kg"], errors="coerce").max()),
            "reserve_boundary_hits": int(pd.to_numeric(group["reserve_boundary_hits"], errors="coerce").fillna(0).sum()),
            "terminal_inventory_correction": float(pd.to_numeric(group["terminal_inventory_correction"], errors="coerce").sum()),
            "solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
            "mip_gap": float(pd.to_numeric(group["mip_gap"], errors="coerce").max()),
            "variable_count": int(pd.to_numeric(group["variable_count"], errors="coerce").fillna(0).max()),
            "binary_variable_count": int(pd.to_numeric(group["binary_variable_count"], errors="coerce").fillna(0).max()),
            "constraint_count": int(pd.to_numeric(group["constraint_count"], errors="coerce").fillna(0).max()),
            "feasible_all_days": bool(group["actual_redispatch_feasible"].astype(bool).all() and group["solver_status"].map(_accepted_solver_status).all()),
            "infeasible_redispatch_days": int(pd.to_numeric(group["infeasible_redispatch_days"], errors="coerce").fillna(0).sum()),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _enrich_target_accounting_columns(
    *,
    frame: pd.DataFrame,
    accounting_frame: pd.DataFrame,
) -> pd.DataFrame:
    if frame.empty or accounting_frame.empty or "delivery_day" not in frame.columns:
        return frame
    enriched = frame.copy()
    expected = accounting_frame.copy()
    expected["delivery_day"] = expected["delivery_day"].astype(str)
    enriched["delivery_day"] = enriched["delivery_day"].astype(str)
    merge_columns = [
        "delivery_day",
        "accounting_week_id",
        "included_day_index_in_week",
        "included_days_in_week",
        "remaining_included_days_after_today",
        "days_remaining_in_week",
        "is_boundary_week",
        "week_start_date",
        "week_end_date",
        "excluded_days_in_calendar_week",
        "exclusion_reason",
        "target_accounting_policy",
        "weekly_target_kg",
    ]
    merged = enriched.merge(expected[merge_columns], on="delivery_day", how="left", suffixes=("", "__expected"))
    for column in merge_columns[1:]:
        expected_column = f"{column}__expected"
        if expected_column not in merged.columns:
            continue
        if column not in merged.columns:
            merged[column] = merged[expected_column]
        else:
            current = merged[column]
            if current.dtype == bool:
                mask = pd.Series(False, index=merged.index)
            else:
                mask = current.isna()
            if mask.any() and (
                current.dtype == object
                or merged[expected_column].dtype == object
                or str(merged[expected_column].dtype) == "bool"
            ):
                merged[column] = merged[column].astype(object)
            merged.loc[mask, column] = merged.loc[mask, expected_column]
        merged = merged.drop(columns=[expected_column])
    return merged


def _build_weekly_metrics(
    *,
    daily_metrics: pd.DataFrame,
    week_manifest: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, week_row in week_manifest.iterrows():
        week_days = set(week_row["included_delivery_days"])
        group = daily_metrics.loc[daily_metrics["delivery_day"].astype(str).isin(week_days)].copy()
        if group.empty:
            continue
        aggregated = _aggregate_stochastic_period(
            daily_metrics=group,
            group_columns=["artifact_id", "model_label", "cvar_gamma"],
            aggregation_level="weekly",
            period_columns={
                "week_id": str(week_row["week_id"]),
                "week_label": str(week_row["week_label"]),
                "week_start": str(week_row["week_start"]),
                "week_end": str(week_row["week_end"]),
                "included_delivery_day_count": int(week_row["included_delivery_day_count"]),
                "is_partial_week": bool(week_row["is_partial_week"]),
            },
        )
        if not aggregated.empty:
            aggregated["weekly_target_kg"] = float(group["weekly_target_kg"].iloc[0])
            aggregated["weekly_target_met"] = (
                aggregated["feasible_all_days"].astype(bool)
                & pd.to_numeric(aggregated["daily_band_violations"], errors="coerce").fillna(0).eq(0)
                & (
                    pd.to_numeric(aggregated["hydrogen_sold_or_compressed_kg"], errors="coerce")
                    + 1e-6
                    >= pd.to_numeric(aggregated["weekly_target_kg"], errors="coerce")
                )
            )
            rows.append(aggregated)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _build_monthly_metrics(
    *,
    daily_metrics: pd.DataFrame,
) -> pd.DataFrame:
    frame = daily_metrics.copy()
    frame["month_id"] = pd.to_datetime(frame["delivery_day"], errors="raise").dt.strftime("%Y-%m")
    rows: list[pd.DataFrame] = []
    for month_id, group in frame.groupby("month_id", sort=True):
        month_start = pd.to_datetime(group["delivery_day"], errors="raise").min().strftime("%Y-%m-%d")
        month_end = pd.to_datetime(group["delivery_day"], errors="raise").max().strftime("%Y-%m-%d")
        aggregated = _aggregate_stochastic_period(
            daily_metrics=group,
            group_columns=["artifact_id", "model_label", "cvar_gamma"],
            aggregation_level="monthly",
            period_columns={
                "month_id": str(month_id),
                "month_start": str(month_start),
                "month_end": str(month_end),
            },
        )
        rows.append(aggregated)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _aggregate_reference_periods(reference_daily: pd.DataFrame, week_manifest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if reference_daily.empty:
        return reference_daily, pd.DataFrame(), pd.DataFrame()
    daily = reference_daily.copy()
    daily["target_mode"] = PHASE_E5_TARGET_MODE
    daily["production_variant"] = PHASE_E5_TARGET_MODE
    weekly_rows: list[pd.DataFrame] = []
    for _, week_row in week_manifest.iterrows():
        week_days = set(week_row["included_delivery_days"])
        group = daily.loc[daily["delivery_day"].astype(str).isin(week_days)].copy()
        if group.empty:
            continue
        submitted = float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum())
        cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
        used_column = "used_energy_mwh" if "used_energy_mwh" in group.columns else "used_cleared_energy_mwh"
        used = float(pd.to_numeric(group[used_column], errors="coerce").sum())
        emergency_import_series = pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0) if "emergency_import_mwh" in group.columns else pd.Series(0.0, index=group.index)
        emergency_import_cost_series = pd.to_numeric(group["emergency_import_cost"], errors="coerce").fillna(0.0) if "emergency_import_cost" in group.columns else pd.Series(0.0, index=group.index)
        emergency_import_hours_series = pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0.0) if "emergency_import_hours" in group.columns else pd.Series(0.0, index=group.index)
        row = {
            "aggregation_level": "weekly",
            "strategy": str(group["strategy"].iloc[0]),
            "week_id": str(week_row["week_id"]),
            "week_label": str(week_row["week_label"]),
            "week_start": str(week_row["week_start"]),
            "week_end": str(week_row["week_end"]),
            "target_mode": PHASE_E5_TARGET_MODE,
            "production_variant": PHASE_E5_TARGET_MODE,
            "realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
            "cleared_energy_mwh": cleared,
            "used_energy_mwh": used,
            "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
            "hydrogen_sold_or_compressed_kg": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
            "shortfall_kg": float(pd.to_numeric(group["shortfall_kg"], errors="coerce").sum()),
            "da_settlement_cost": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
            "hydrogen_revenue": float(pd.to_numeric(group["hydrogen_revenue"], errors="coerce").sum()),
            "unused_energy_penalty": float(pd.to_numeric(group["unused_energy_penalty"], errors="coerce").sum()),
            "shortfall_penalty": float(pd.to_numeric(group["shortfall_penalty"], errors="coerce").sum()),
            "terminal_inventory_correction": float(pd.to_numeric(group["terminal_inventory_correction"], errors="coerce").sum()),
            "submitted_energy_mwh": submitted,
            "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
            "average_actual_price_paid": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum() / cleared) if cleared > 0.0 else np.nan,
            "daily_band_violations": int(pd.to_numeric(group["daily_band_violations"], errors="coerce").fillna(0).sum()) if "daily_band_violations" in group.columns else 0,
            "infeasible_redispatch_days": int(pd.to_numeric(group["infeasible_redispatch_days"], errors="coerce").fillna(0).sum()) if "infeasible_redispatch_days" in group.columns else 0,
            "weekly_target_met": bool(group["weekly_target_met"].astype(bool).all()) if "weekly_target_met" in group.columns else np.nan,
            "emergency_import_mwh": float(emergency_import_series.sum()),
            "emergency_import_cost": float(emergency_import_cost_series.sum()),
            "emergency_import_hours": int(emergency_import_hours_series.sum()),
            "emergency_import_share_of_used_energy": float(emergency_import_series.sum() / used) if used > 0.0 else 0.0,
        }
        weekly_rows.append(pd.DataFrame([row]))
    weekly = pd.concat(weekly_rows, ignore_index=True) if weekly_rows else pd.DataFrame()
    monthly_rows: list[pd.DataFrame] = []
    daily["month_id"] = pd.to_datetime(daily["delivery_day"], errors="raise").dt.strftime("%Y-%m")
    for month_id, group in daily.groupby("month_id", sort=True):
        submitted = float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum())
        cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
        used_column = "used_energy_mwh" if "used_energy_mwh" in group.columns else "used_cleared_energy_mwh"
        used = float(pd.to_numeric(group[used_column], errors="coerce").sum())
        emergency_import_series = pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0) if "emergency_import_mwh" in group.columns else pd.Series(0.0, index=group.index)
        emergency_import_cost_series = pd.to_numeric(group["emergency_import_cost"], errors="coerce").fillna(0.0) if "emergency_import_cost" in group.columns else pd.Series(0.0, index=group.index)
        emergency_import_hours_series = pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0.0) if "emergency_import_hours" in group.columns else pd.Series(0.0, index=group.index)
        monthly_rows.append(
            pd.DataFrame(
                [
                    {
                        "aggregation_level": "monthly",
                        "strategy": str(group["strategy"].iloc[0]),
                        "month_id": str(month_id),
                        "month_start": pd.to_datetime(group["delivery_day"], errors="raise").min().strftime("%Y-%m-%d"),
                        "month_end": pd.to_datetime(group["delivery_day"], errors="raise").max().strftime("%Y-%m-%d"),
                        "target_mode": PHASE_E5_TARGET_MODE,
                        "production_variant": PHASE_E5_TARGET_MODE,
                        "realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                        "cleared_energy_mwh": cleared,
                        "used_energy_mwh": used,
                        "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                        "hydrogen_sold_or_compressed_kg": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                        "shortfall_kg": float(pd.to_numeric(group["shortfall_kg"], errors="coerce").sum()),
                        "da_settlement_cost": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
                        "hydrogen_revenue": float(pd.to_numeric(group["hydrogen_revenue"], errors="coerce").sum()),
                        "unused_energy_penalty": float(pd.to_numeric(group["unused_energy_penalty"], errors="coerce").sum()),
                        "shortfall_penalty": float(pd.to_numeric(group["shortfall_penalty"], errors="coerce").sum()),
                        "terminal_inventory_correction": float(pd.to_numeric(group["terminal_inventory_correction"], errors="coerce").sum()),
                        "submitted_energy_mwh": submitted,
                        "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                        "average_actual_price_paid": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum() / cleared) if cleared > 0.0 else np.nan,
                        "emergency_import_mwh": float(emergency_import_series.sum()),
                        "emergency_import_cost": float(emergency_import_cost_series.sum()),
                        "emergency_import_hours": int(emergency_import_hours_series.sum()),
                        "emergency_import_share_of_used_energy": float(emergency_import_series.sum() / used) if used > 0.0 else 0.0,
                    }
                ]
            )
        )
    monthly = pd.concat(monthly_rows, ignore_index=True) if monthly_rows else pd.DataFrame()
    annual_used_series = pd.to_numeric(daily["used_energy_mwh"] if "used_energy_mwh" in daily.columns else daily["used_cleared_energy_mwh"], errors="coerce")
    annual_emergency_import_series = pd.to_numeric(daily["emergency_import_mwh"], errors="coerce").fillna(0.0) if "emergency_import_mwh" in daily.columns else pd.Series(0.0, index=daily.index)
    annual_emergency_import_cost_series = pd.to_numeric(daily["emergency_import_cost"], errors="coerce").fillna(0.0) if "emergency_import_cost" in daily.columns else pd.Series(0.0, index=daily.index)
    annual_emergency_import_hours_series = pd.to_numeric(daily["emergency_import_hours"], errors="coerce").fillna(0.0) if "emergency_import_hours" in daily.columns else pd.Series(0.0, index=daily.index)
    annual = pd.DataFrame(
        [
            {
                "aggregation_level": "annual",
                "strategy": str(daily["strategy"].iloc[0]),
                "period_start": pd.to_datetime(daily["delivery_day"], errors="raise").min().strftime("%Y-%m-%d"),
                "period_end": pd.to_datetime(daily["delivery_day"], errors="raise").max().strftime("%Y-%m-%d"),
                "target_mode": PHASE_E5_TARGET_MODE,
                "production_variant": PHASE_E5_TARGET_MODE,
                "realised_adjusted_profit": float(pd.to_numeric(daily["realised_adjusted_profit"], errors="coerce").sum()),
                "cleared_energy_mwh": float(pd.to_numeric(daily["cleared_energy_mwh"], errors="coerce").sum()),
                "used_energy_mwh": float(annual_used_series.sum()),
                "unused_cleared_energy_mwh": float(pd.to_numeric(daily["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "hydrogen_sold_or_compressed_kg": float(pd.to_numeric(daily["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                "shortfall_kg": float(pd.to_numeric(daily["shortfall_kg"], errors="coerce").sum()),
                "da_settlement_cost": float(pd.to_numeric(daily["da_settlement_cost"], errors="coerce").sum()),
                "hydrogen_revenue": float(pd.to_numeric(daily["hydrogen_revenue"], errors="coerce").sum()),
                "unused_energy_penalty": float(pd.to_numeric(daily["unused_energy_penalty"], errors="coerce").sum()),
                "shortfall_penalty": float(pd.to_numeric(daily["shortfall_penalty"], errors="coerce").sum()),
                "terminal_inventory_correction": float(pd.to_numeric(daily["terminal_inventory_correction"], errors="coerce").sum()),
                "submitted_energy_mwh": float(pd.to_numeric(daily["submitted_energy_mwh"], errors="coerce").sum()),
                "rejected_energy_mwh": float(pd.to_numeric(daily["rejected_energy_mwh"], errors="coerce").sum()),
                "average_actual_price_paid": float(pd.to_numeric(daily["da_settlement_cost"], errors="coerce").sum() / pd.to_numeric(daily["cleared_energy_mwh"], errors="coerce").sum()) if float(pd.to_numeric(daily["cleared_energy_mwh"], errors="coerce").sum()) > 0.0 else np.nan,
                "emergency_import_mwh": float(annual_emergency_import_series.sum()),
                "emergency_import_cost": float(annual_emergency_import_cost_series.sum()),
                "emergency_import_hours": int(annual_emergency_import_hours_series.sum()),
                "emergency_import_share_of_used_energy": float(annual_emergency_import_series.sum() / annual_used_series.sum()) if float(annual_used_series.sum()) > 0.0 else 0.0,
            }
        ]
    )
    return daily, weekly, pd.concat([monthly, annual], ignore_index=True)


def _build_annual_metrics_by_gamma(
    *,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    runtime_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for gamma, group in daily_metrics.groupby("cvar_gamma", sort=True):
        weekly_group = weekly_metrics.loc[pd.to_numeric(weekly_metrics["cvar_gamma"], errors="coerce").eq(float(gamma))].copy()
        cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
        used = float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum())
        realised = float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum())
        expected = float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum())
        perfect = float(pd.to_numeric(group["perfect_foresight_profit"], errors="coerce").sum())
        rows.append(
            {
                "artifact_id": str(group["artifact_id"].iloc[0]),
                "model_label": str(group["model_label"].iloc[0]),
                "gamma": float(gamma),
                "annual_realised_adjusted_profit": realised,
                "annual_expected_adjusted_profit": expected,
                "annual_value_captured_vs_perfect_foresight": float(realised / perfect) if abs(perfect) > 1e-9 else np.nan,
                "annual_regret_vs_perfect_foresight": float(perfect - realised),
                "mean_weekly_realised_profit": float(pd.to_numeric(weekly_group["realised_adjusted_profit"], errors="coerce").mean()) if not weekly_group.empty else np.nan,
                "worst_week_realised_profit": float(pd.to_numeric(weekly_group["realised_adjusted_profit"], errors="coerce").min()) if not weekly_group.empty else np.nan,
                "annual_cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").sum()),
                "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()),
                "total_emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "number_of_emergency_import_days": int(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").fillna(0.0).gt(1e-9).sum()),
                "emergency_import_share_of_used_energy": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum() / used) if used > 0.0 else 0.0,
                "total_rejected_energy": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "total_unused_cleared_energy": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "mean_clearing_ratio": float(pd.to_numeric(group["clearing_ratio"], errors="coerce").mean()),
                "average_actual_price_paid": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum() / cleared) if cleared > 0.0 else np.nan,
                "total_runtime_seconds": float(
                    pd.to_numeric(
                        runtime_diagnostics.loc[
                            runtime_diagnostics["solve_stage"].astype(str).eq("stochastic_bidding_day")
                            & pd.to_numeric(runtime_diagnostics["gamma"], errors="coerce").eq(float(gamma)),
                            "wall_time_seconds",
                        ],
                        errors="coerce",
                    ).sum()
                ),
                "feasible_all_days": bool(group["actual_redispatch_feasible"].astype(bool).all() and group["solver_status"].map(_accepted_solver_status).all()),
                "weekly_targets_met": bool(group["weekly_target_met"].astype(bool).all()),
            }
        )
    annual = pd.DataFrame(rows).sort_values("gamma").reset_index(drop=True)
    recommendation = "single_gamma_run"
    if annual.shape[0] == 2:
        g0 = annual.loc[np.isclose(pd.to_numeric(annual["gamma"], errors="coerce"), 0.0)].iloc[0]
        g025 = annual.loc[np.isclose(pd.to_numeric(annual["gamma"], errors="coerce"), 0.25)].iloc[0]
        profit_delta = float(g025["annual_realised_adjusted_profit"] - g0["annual_realised_adjusted_profit"])
        tail_improved = float(g025["annual_cvar_tail_profit"]) > float(g0["annual_cvar_tail_profit"]) + 1e-6
        worst_improved = float(g025["worst_scenario_profit"]) > float(g0["worst_scenario_profit"]) + 1e-6
        emergency_reduced = float(g025["total_emergency_import_mwh"]) + 1e-6 < float(g0["total_emergency_import_mwh"])
        opportunity_cost_ok = profit_delta >= -max(5000.0, 0.02 * max(abs(float(g0["annual_realised_adjusted_profit"])), 1.0))
        if (tail_improved or worst_improved or emergency_reduced) and opportunity_cost_ok:
            recommendation = "risk_averse_default"
        elif profit_delta > 1e-6 and not (tail_improved or worst_improved or emergency_reduced):
            recommendation = "risk_neutral_default"
        elif profit_delta >= 0.0 and (tail_improved or worst_improved):
            recommendation = "risk_averse_default"
        else:
            recommendation = "keep_both"
    elif annual.shape[0] >= 3:
        recommendation = "compare_multiple_gammas"
    annual["recommendation"] = recommendation
    return annual


def _build_validation_checks(
    *,
    artifact_id: str,
    gamma_values: list[float],
    alpha: float,
    target_mode: str,
    emergency_import_price: float,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    weekly_tracker: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    dst_excluded_days: list[dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    observed_artifacts = sorted(daily_metrics["artifact_id"].astype(str).unique().tolist())
    rows.append(_validation_row(check_name="full_year_run_uses_only_repaired_lear_strict_artifact", status="pass" if observed_artifacts == [str(artifact_id)] else "fail", details=f"observed_artifacts={observed_artifacts}"))
    observed_gammas = sorted(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").dropna().unique().tolist())
    rows.append(_validation_row(check_name="observed_gammas_match_requested_set", status="pass" if observed_gammas == sorted(gamma_values) else "fail", details=f"observed_gammas={observed_gammas}"))
    observed_alpha = sorted(pd.to_numeric(daily_metrics["cvar_alpha"], errors="coerce").dropna().unique().tolist())
    rows.append(_validation_row(check_name="alpha_exactly_0p95", status="pass" if observed_alpha == [float(alpha)] else "fail", details=f"observed_alpha={observed_alpha}"))
    rows.append(_validation_row(check_name="no_production_bands", status="pass" if daily_metrics["target_mode"].astype(str).eq(str(target_mode)).all() else "fail", details=f"target_mode={target_mode}"))
    rows.append(_validation_row(check_name="no_shortfall_slack", status="pass" if pd.to_numeric(daily_metrics["shortfall_kg"], errors="coerce").fillna(0.0).abs().le(1e-9).all() else "fail", details="shortfall_kg must remain zero under emergency fallback"))
    emergency_enabled = daily_metrics["emergency_import_enabled"].astype(bool).all()
    emergency_price_ok = np.isclose(pd.to_numeric(daily_metrics["emergency_import_price_eur_per_mwh"], errors="coerce").dropna(), float(emergency_import_price)).all()
    rows.append(_validation_row(check_name="emergency_import_enabled_and_charged_at_3000", status="pass" if emergency_enabled and emergency_price_ok else "fail", details=f"price={float(emergency_import_price):.2f}"))
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if not actual_clearing.empty and "accepted" in actual_clearing.columns else pd.DataFrame()
    accepted_ok = accepted.empty or bool((pd.to_numeric(accepted["bid_price_eur_per_mwh"], errors="coerce") + TOLERANCE >= pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce")).all())
    rows.append(_validation_row(check_name="accepted_iff_bid_price_ge_actual_price", status="pass" if accepted_ok else "fail", details=f"accepted_rows={int(accepted.shape[0])}"))
    pay_as_cleared_ok = True
    if not accepted.empty and "settlement_cost_eur" in accepted.columns:
        pay_as_cleared_ok = np.allclose(
            pd.to_numeric(accepted["settlement_cost_eur"], errors="coerce"),
            pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce") * pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce"),
            atol=1e-6,
        )
    rows.append(_validation_row(check_name="da_settlement_pay_as_cleared", status="pass" if pay_as_cleared_ok else "fail", details="accepted DA demand pays actual cleared price"))
    emergency_cost_ok = np.allclose(
        pd.to_numeric(daily_metrics["emergency_import_cost"], errors="coerce").fillna(0.0),
        pd.to_numeric(daily_metrics["emergency_import_mwh"], errors="coerce").fillna(0.0) * float(emergency_import_price),
        atol=1e-6,
    )
    rows.append(_validation_row(check_name="emergency_import_not_pay_as_cleared", status="pass" if emergency_cost_ok else "fail", details=f"fixed administrative price={float(emergency_import_price):.2f}"))
    rejected_ok = np.allclose(
        pd.to_numeric(daily_metrics["submitted_energy_mwh"], errors="coerce") - pd.to_numeric(daily_metrics["cleared_energy_mwh"], errors="coerce"),
        pd.to_numeric(daily_metrics["rejected_energy_mwh"], errors="coerce"),
        atol=1e-6,
        equal_nan=True,
    )
    rows.append(_validation_row(check_name="rejected_equals_submitted_minus_cleared", status="pass" if rejected_ok else "fail", details="daily rejected identity"))
    feasible_rows = daily_metrics.loc[daily_metrics["actual_redispatch_feasible"].astype(bool)].copy()
    used_unused_ok = feasible_rows.empty or np.allclose(
        pd.to_numeric(feasible_rows["used_cleared_energy_mwh"], errors="coerce")
        + pd.to_numeric(feasible_rows["unused_cleared_energy_mwh"], errors="coerce"),
        pd.to_numeric(feasible_rows["cleared_energy_mwh"], errors="coerce")
        + pd.to_numeric(feasible_rows["emergency_import_mwh"], errors="coerce"),
        atol=1e-6,
    )
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_plus_emergency", status="pass" if used_unused_ok else "fail", details=f"feasible_rows={int(feasible_rows.shape[0])}"))
    rows.append(_validation_row(check_name="weekly_hard_targets_met", status="pass" if weekly_metrics["weekly_target_met"].astype(bool).all() else "fail", details=f"weeks_failed={int((~weekly_metrics['weekly_target_met'].astype(bool)).sum())}"))
    target_policy_ok = (
        "target_accounting_policy" in daily_metrics.columns
        and daily_metrics["target_accounting_policy"].astype(str).eq(TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET).all()
    )
    rows.append(
        _validation_row(
            check_name="included_day_prorated_weekly_target_policy_active",
            status="pass" if target_policy_ok else "fail",
            details=f"policy={TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET}",
        )
    )
    boundary_rows = (
        daily_metrics.loc[daily_metrics["is_boundary_week"].fillna(False).astype(bool)].copy()
        if "is_boundary_week" in daily_metrics.columns
        else pd.DataFrame()
    )
    rows.append(
        _validation_row(
            check_name="boundary_weeks_documented",
            status="pass" if ("is_boundary_week" in daily_metrics.columns and not boundary_rows.empty) else "fail",
            details=f"boundary_day_rows={int(boundary_rows.shape[0])}",
        )
    )
    lower_upper_consistent = True
    if "included_days_in_week" in daily_metrics.columns and "remaining_included_days_after_today" in daily_metrics.columns:
        lower_upper_consistent = bool(
            (
                pd.to_numeric(daily_metrics["included_days_in_week"], errors="coerce")
                - pd.to_numeric(daily_metrics["included_day_index_in_week"], errors="coerce")
            ).eq(pd.to_numeric(daily_metrics["remaining_included_days_after_today"], errors="coerce")).all()
            and (
                pd.to_numeric(daily_metrics["daily_upper_bound_kg"], errors="coerce") + TOLERANCE
                >= pd.to_numeric(daily_metrics["daily_lower_bound_kg"], errors="coerce")
            ).all()
        )
    rows.append(
        _validation_row(
            check_name="daily_target_bounds_consistent_with_accounting_week_progress",
            status="pass" if lower_upper_consistent else "fail",
            details="included_days_in_week - included_day_index_in_week must equal remaining_included_days_after_today",
        )
    )
    artificial_infeasibility = False
    if not daily_metrics.empty:
        statuses = daily_metrics["solver_status"].astype(str)
        artificial_infeasibility = statuses.str.contains("infeasible_weekly_target_bounds", case=False, na=False).any()
    rows.append(
        _validation_row(
            check_name="no_artificial_full_week_target_infeasibility_on_partial_horizon",
            status="pass" if not artificial_infeasibility else "fail",
            details="no daily rows should be marked infeasible_weekly_target_bounds after prorated accounting repair",
        )
    )
    storage_close_ok = True
    if not actual_redispatch.empty:
        for _, group in actual_redispatch.groupby(["artifact_id", "delivery_day", "cvar_gamma"], sort=False):
            ordered = group.sort_values("delivery_start_utc")
            prev = float(ordered["storage_initial_kg"].iloc[0]) if "storage_initial_kg" in ordered.columns else float("nan")
            for row in ordered.itertuples():
                computed = prev + float(row.H_prod_kg) - float(row.H_comp_kg)
                if abs(computed - float(row.H_buf_kg)) > 1e-6:
                    storage_close_ok = False
                    break
                prev = float(row.H_buf_kg)
            if not storage_close_ok:
                break
    rows.append(_validation_row(check_name="storage_balance_closes", status="pass" if storage_close_ok else "fail", details="checked actual redispatch trajectories"))
    rows.append(_validation_row(check_name="terminal_inventory_correction_reported", status="pass" if "terminal_inventory_correction" in daily_metrics.columns else "fail", details="daily metrics include terminal inventory correction"))
    benchmark_dates = sorted(benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("daily"), "delivery_day"].astype(str).tolist()) if not benchmark_metrics.empty else []
    pf_dates = sorted(perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("daily"), "delivery_day"].astype(str).tolist()) if not perfect_foresight_metrics.empty else []
    target_dates = sorted(daily_metrics["delivery_day"].astype(str).unique().tolist())
    rows.append(_validation_row(check_name="benchmark_and_perfect_foresight_use_same_included_dates_prices", status="pass" if benchmark_dates == target_dates and pf_dates == target_dates else "fail", details=f"benchmark_dates={len(benchmark_dates)}; stochastic_dates={len(target_dates)}; pf_dates={len(pf_dates)}"))
    rows.append(_validation_row(check_name="infeasible_rows_explicit", status="pass", details=f"infeasible_rows={int((~daily_metrics['actual_redispatch_feasible'].astype(bool)).sum())}"))
    rows.append(_validation_row(check_name="dst_exclusions_explicit", status="pass" if bool(dst_excluded_days) else "fail", details="; ".join([f"{row['delivery_day']} ({row['local_hour_count']}h)" for row in dst_excluded_days])))
    rows.append(_validation_row(check_name="no_scenario_probability_bid_grid_changes", status="pass", details="Phase E5 reuses the repaired LEAR Strict artifact, scenario probabilities, bid grid, clearing rule, and stochastic MILP formulation unchanged."))
    tracker_rows = weekly_tracker.loc[weekly_tracker["strategy"].astype(str).str.startswith("stochastic_")].copy()
    rows.append(_validation_row(check_name="weekly_target_tracker_rows_match_stochastic_daily_rows", status="pass" if int(tracker_rows.shape[0]) == int(daily_metrics.shape[0]) else "fail", details=f"tracker_rows={int(tracker_rows.shape[0])}; daily_rows={int(daily_metrics.shape[0])}"))
    return pd.DataFrame(rows)


def _build_readme(
    *,
    test_start: str,
    test_end: str,
    included_days: list[str],
    dst_excluded_days: list[dict[str, Any]],
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    annual_metrics_by_gamma: pd.DataFrame,
    emergency_import_summary: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    runtime_summary: pd.DataFrame,
    validation_checks: pd.DataFrame,
    support_preflight: pd.DataFrame,
    selected_artifact_manifest: dict[str, Any],
) -> str:
    observed_gamma_values = sorted(pd.to_numeric(annual_metrics_by_gamma["gamma"], errors="coerce").dropna().unique().tolist())
    expected_rows = len(included_days) * max(len(observed_gamma_values), 1)
    completed = int(daily_metrics.shape[0]) == int(expected_rows)
    g0 = annual_metrics_by_gamma.loc[np.isclose(pd.to_numeric(annual_metrics_by_gamma["gamma"], errors="coerce"), 0.0)]
    g025 = annual_metrics_by_gamma.loc[np.isclose(pd.to_numeric(annual_metrics_by_gamma["gamma"], errors="coerce"), 0.25)]
    g0_row = g0.iloc[0] if not g0.empty else None
    g025_row = g025.iloc[0] if not g025.empty else None
    benchmark_annual = benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("annual")].head(1)
    pf_annual = perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("annual")].head(1)
    preflight_failures = int((support_preflight["status"].astype(str) == "fail").sum())
    validation_failures = int((validation_checks["status"].astype(str) == "fail").sum())
    warning_lines = []
    for text in selected_artifact_manifest.get("scenario_manifest", {}).get("known_limitations", []):
        warning_lines.append(f"- {text}")
    if weekly_metrics["included_delivery_day_count"].astype(int).lt(7).any():
        warning_lines.append("- Calendar-week grouping contains partial weeks at the test-year boundaries and in DST weeks because the hourly 24h pipeline excludes 23h/25h delivery days.")
    if not completed:
        warning_lines.append("- The run folder is resumable, but this execution did not finish all expected stochastic day solves.")
    if validation_failures > 0:
        warning_lines.append(f"- Validation reported {validation_failures} failing checks; inspect validation_checks_all_runs.csv before using results in the thesis.")
    lines = [
        "# Full-Year Repaired LEAR Strict E5",
        "",
        f"1. Did the full-year run complete? {'yes' if completed and preflight_failures == 0 else 'no'}.",
        f"2. Which days were included/excluded? included={len(included_days)} delivery days from {included_days[0] if included_days else ''} to {included_days[-1] if included_days else ''}; excluded DST days={', '.join([row['delivery_day'] for row in dst_excluded_days])}.",
        f"3. Feasibility by gamma: {annual_metrics_by_gamma[['gamma', 'feasible_all_days', 'weekly_targets_met']].to_dict(orient='records') if not annual_metrics_by_gamma.empty else []}.",
        f"4. How much emergency import was used? total MWh by gamma = {emergency_import_summary[['gamma', 'total_emergency_import_mwh', 'total_emergency_import_cost']].to_dict(orient='records') if not emergency_import_summary.empty else []}.",
        f"5. Did gamma=0.25 reduce tail risk? {'yes' if g0_row is not None and g025_row is not None and (float(g025_row['annual_cvar_tail_profit']) > float(g0_row['annual_cvar_tail_profit']) or float(g025_row['worst_scenario_profit']) > float(g0_row['worst_scenario_profit'])) else 'no or not observed'}.",
        f"6. What was the opportunity cost of gamma=0.25 versus gamma=0? {float(g025_row['annual_realised_adjusted_profit'] - g0_row['annual_realised_adjusted_profit']):.2f} EUR." if g0_row is not None and g025_row is not None else "6. What was the opportunity cost of gamma=0.25 versus gamma=0? not available.",
        f"7. Which gamma should be used as the main thesis setting? {annual_metrics_by_gamma['recommendation'].iloc[0] if not annual_metrics_by_gamma.empty else 'not available'}.",
        (
            f"8. How did the selected policy perform versus price-insensitive and perfect foresight? "
            f"benchmark annual profit={float(benchmark_annual['realised_adjusted_profit'].iloc[0]):.2f} EUR; "
            f"perfect foresight annual profit={float(pf_annual['realised_adjusted_profit'].iloc[0]):.2f} EUR."
            if not benchmark_annual.empty and not pf_annual.empty
            else "8. How did the selected policy perform versus price-insensitive and perfect foresight? not available."
        ),
        f"9. Runtime summary and bottlenecks. total wall time={float(pd.to_numeric(runtime_summary.loc[runtime_summary['section'].astype(str).eq('totals'), 'value'], errors='coerce').iloc[0]):.2f} seconds.",
        "10. Methodological warnings.",
        "",
    ]
    lines.extend(warning_lines or ["- None beyond the predeclared DST exclusion and scenario calibration caveats."])
    return "\n".join(lines)


def run_full_year_repaired_lear_strict(
    *,
    config: HydrogenConfig | str | Path,
    artifact_id: str,
    test_start: str,
    test_end: str,
    alpha: float,
    gammas: list[float] | tuple[float, ...],
    target_mode: str,
    emergency_import_price: float,
    include_price_insensitive_benchmark: bool,
    include_perfect_foresight_benchmark: bool,
    reuse_true_pf_from: Path | None = None,
    reporting_mode: str,
    safe_resume: bool,
    run_slug: str,
    output_root: Path | None = None,
    resume_run_dir: Path | None = None,
    gamma_filter: list[float] | tuple[float, ...] | None = None,
    chunk_start: str | None = None,
    chunk_end: str | None = None,
    max_new_solves: int | None = None,
    day_output_mode: str = "full",
    audit_days: list[str] | tuple[str, ...] | None = None,
    checkpoint_every_n_solves: int = 10,
    target_accounting_policy: str = TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
) -> PhaseE5FullYearResult:
    if str(artifact_id) != PHASE_E5_ARTIFACT:
        raise ValueError(f"Phase E5 requires artifact={PHASE_E5_ARTIFACT!r}, got {artifact_id!r}.")
    gamma_values = [float(value) for value in gammas]
    unsupported_gammas = sorted(set(gamma_values).difference(PHASE_E5_ALLOWED_GAMMAS))
    if unsupported_gammas:
        raise ValueError(f"Supported repaired full-year gammas are {list(PHASE_E5_ALLOWED_GAMMAS)}, got unsupported {unsupported_gammas!r}.")
    if abs(float(alpha) - PHASE_E5_ALPHA) > 1e-12:
        raise ValueError(f"Phase E5 requires alpha={PHASE_E5_ALPHA}, got {alpha!r}.")
    if str(target_mode) != PHASE_E5_TARGET_MODE:
        raise ValueError(f"Phase E5 requires target_mode={PHASE_E5_TARGET_MODE!r}, got {target_mode!r}.")
    if abs(float(emergency_import_price) - PHASE_E5_EMERGENCY_IMPORT_PRICE) > 1e-12:
        raise ValueError(
            f"Phase E5 requires emergency_import_price={PHASE_E5_EMERGENCY_IMPORT_PRICE}, got {emergency_import_price!r}."
        )
    if not bool(include_price_insensitive_benchmark):
        raise ValueError("Phase E5 requires the price-insensitive benchmark.")
    if not bool(include_perfect_foresight_benchmark) and reuse_true_pf_from is None:
        raise ValueError("Phase E5 requires a perfect-foresight comparator unless reuse_true_pf_from is provided.")
    if str(reporting_mode).strip().lower() != PHASE_E5_REPORTING_MODE:
        raise ValueError(f"Phase E5 requires reporting_mode={PHASE_E5_REPORTING_MODE!r}, got {reporting_mode!r}.")
    target_accounting_policy = validate_target_accounting_policy(target_accounting_policy)
    selected_gammas = gamma_values if gamma_filter is None else [float(value) for value in gamma_filter]
    invalid_gamma_filters = sorted(set(selected_gammas).difference(gamma_values))
    if invalid_gamma_filters:
        raise ValueError(f"gamma_filter contains values outside the configured Phase E5 gamma set: {invalid_gamma_filters!r}")
    normalized_day_output_mode = str(day_output_mode).strip().lower()
    if normalized_day_output_mode not in {"full", "minimal", "audit"}:
        raise ValueError(f"Unsupported day_output_mode={day_output_mode!r}. Use 'full', 'minimal', or 'audit'.")
    normalized_audit_days = sorted({str(value) for value in (audit_days or [])})
    checkpoint_every_n_solves = max(int(checkpoint_every_n_solves), 1)

    suite_config = _build_phase_e4_config(
        config,
        artifact_ids=[str(artifact_id)],
        output_root=output_root,
        run_slug=str(run_slug),
    )
    suite_config = replace(
        suite_config,
        experiment=replace(
            suite_config.experiment,
            name=str(run_slug),
            execution_mode="full_year_repaired_lear_strict",
        ),
        outputs=replace(suite_config.outputs, save_figures=False),
    )

    if resume_run_dir is not None:
        run_dir = Path(resume_run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_dir.name
    elif bool(safe_resume):
        existing = _find_latest_e5_resume_dir(suite_config.run_output_root, str(run_slug))
        if existing is not None:
            run_dir = existing
            run_id = run_dir.name
        else:
            run_id, run_dir = create_run_folder(suite_config)
    else:
        run_id, run_dir = create_run_folder(suite_config)
    (run_dir / "day_runs").mkdir(parents=True, exist_ok=True)
    (run_dir / "cache").mkdir(parents=True, exist_ok=True)

    scenarios, registry, selected_daily, spec, _support_source = _load_or_build_support_cache(
        run_dir=run_dir,
        config=suite_config,
        artifact_id=artifact_id,
    )

    support_preflight, expected_days, dst_excluded_days = _build_support_preflight(
        artifact_id=artifact_id,
        config=suite_config,
        spec=spec,
        selected_daily=selected_daily,
        registry=registry,
        test_start=str(test_start),
        test_end=str(test_end),
        alpha=float(alpha),
        gamma_values=gamma_values,
        target_mode=str(target_mode),
        target_accounting_policy=str(target_accounting_policy),
    )

    save_config_resolved(run_dir, suite_config)
    save_inputs_manifest(run_dir, [suite_config.config_path, suite_config.models.scenario_catalog, spec.path])
    input_manifest = build_inputs_manifest([suite_config.config_path, suite_config.models.scenario_catalog, spec.path])
    input_manifest.update(
        {
            "artifact_id": str(artifact_id),
            "test_start": str(test_start),
            "test_end": str(test_end),
            "alpha": float(alpha),
            "gammas": gamma_values,
            "target_mode": str(target_mode),
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "reporting_mode": str(reporting_mode),
            "safe_resume": bool(safe_resume),
            "gamma_filter": selected_gammas,
            "chunk_start": str(chunk_start) if chunk_start else None,
            "chunk_end": str(chunk_end) if chunk_end else None,
            "max_new_solves": None if max_new_solves is None else int(max_new_solves),
            "day_output_mode": normalized_day_output_mode,
            "audit_days": normalized_audit_days,
            "checkpoint_every_n_solves": int(checkpoint_every_n_solves),
            "target_accounting_policy": str(target_accounting_policy),
        }
    )
    save_json(run_dir, "input_manifest.json", input_manifest)
    save_frame_csv(run_dir, "support_preflight.csv", support_preflight)

    if (support_preflight["status"].astype(str) == "fail").any():
        raise RuntimeError("Phase E5 support preflight failed. See support_preflight.csv.")

    selected_in_period = selected_daily.loc[selected_daily["delivery_day"].astype(str).between(str(test_start), str(test_end))].copy()
    included_days = sorted(selected_in_period["delivery_day"].astype(str).tolist())
    selected_artifact_manifest = _build_selected_artifact_manifest(
        config=suite_config,
        artifact_id=artifact_id,
        spec=spec,
        selected_daily=selected_in_period,
        test_start=str(test_start),
        test_end=str(test_end),
        included_days=included_days,
        dst_excluded_days=dst_excluded_days,
    )
    save_json(run_dir, "selected_artifact_manifest.json", selected_artifact_manifest)

    physical_daily_max_kg = _physical_daily_max_kg(suite_config)
    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(suite_config.economics.daily_target_kg),
        daily_min_fraction=0.0,
        daily_max_fraction=float(physical_daily_max_kg / suite_config.economics.daily_target_kg),
        target_accounting_policy=str(target_accounting_policy),
    )
    save_json(
        run_dir,
        "production_target_manifest.json",
        {
            "target_mode": PHASE_E5_TARGET_MODE,
            "model_target_formulation": TARGET_MODE_WEEKLY_HARD_BAND,
            "weekly_target_hard": True,
            "weekly_target_kg": float(settings.weekly_target_kg),
            "daily_target_kg": float(settings.daily_target_kg),
            "daily_min_fraction": 0.0,
            "daily_min_kg": 0.0,
            "physical_daily_max_kg": float(physical_daily_max_kg),
            "shortfall_slack_allowed": False,
            "emergency_import_enabled": True,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "week_definition": "calendar_monday_sunday_intersected_with_test_period_after_dst_exclusions",
            "target_accounting_policy": str(target_accounting_policy),
        },
    )
    save_json(run_dir, "cvar_settings_manifest.json", {"alpha": float(alpha), "gammas": gamma_values})

    target_accounting_frame = build_included_day_prorated_weekly_accounting(
        included_delivery_days=included_days,
        daily_target_kg=float(settings.daily_target_kg),
        excluded_day_reasons=build_weekly_accounting_exclusion_reason_map(
            included_delivery_days=included_days,
            explicit_exclusions=[{**item, "reason": "dst_excluded"} for item in dst_excluded_days],
        ),
        target_accounting_policy=str(target_accounting_policy),
    )
    target_accounting_lookup = build_production_accounting_lookup(target_accounting_frame)
    week_manifest = _week_manifest_from_days(included_days)
    reference_days: dict[str, dict[str, Any]] = {}
    selected_in_period = selected_in_period.sort_values(["delivery_day", "forecast_origin_utc"]).reset_index(drop=True)
    scenarios = scenarios.copy()
    scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True, errors="raise")
    scenarios["delivery_start_utc"] = pd.to_datetime(scenarios["delivery_start_utc"], utc=True, errors="raise")
    for row in selected_in_period.to_dict(orient="records"):
        delivery_day = str(row["delivery_day"])
        origin = pd.Timestamp(row["forecast_origin_utc"])
        selected = scenarios.loc[scenarios["forecast_origin_utc"].eq(origin)].copy()
        selected = selected.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)
        reference_days[delivery_day] = {
            "day_meta": row,
            "forecast_origin_utc": origin,
            "scenarios": selected,
            "model_id": str(row.get("model_id", spec.model_id)),
            "model_label": str(row["model_label"]),
            "validation_mode": str(row["validation_mode"]),
            "thesis_grade": bool(row.get("thesis_grade", True)),
            "forecast_origin_reconstruction_used": bool(row.get("forecast_origin_reconstruction_used", False)),
        }

    benchmark_frames: list[pd.DataFrame] = []
    perfect_foresight_frames: list[pd.DataFrame] = []
    weekly_tracker_rows: list[pd.DataFrame] = []
    runtime_rows: list[dict[str, Any]] = []
    benchmark_daily_map: dict[tuple[str, str], pd.Series] = {}
    perfect_foresight_daily_map: dict[tuple[str, str], pd.Series] = {}
    reused_reference_frames: dict[str, Any] | None = None
    if reuse_true_pf_from is not None:
        reused_reference_frames = _load_reference_frames_from_reuse_run(
            reuse_run_dir=Path(reuse_true_pf_from),
            included_days=included_days,
        )
        benchmark_frames.append(reused_reference_frames["benchmark_metrics"])
        perfect_foresight_frames.append(reused_reference_frames["perfect_foresight_metrics"])
        benchmark_daily_map = dict(reused_reference_frames["benchmark_daily_map"])
        perfect_foresight_daily_map = dict(reused_reference_frames["perfect_foresight_daily_map"])
        runtime_rows.append(
            _stage_runtime_row(
                solve_stage="price_insensitive_week",
                artifact_id=artifact_id,
                model_label="Price insensitive benchmark",
                gamma=None,
                week_id="reused_from_reference_run",
                delivery_day=None,
                wall_time_seconds=0.0,
                used_cache=True,
                solver_status="Optimal",
            )
        )
        runtime_rows.append(
            _stage_runtime_row(
                solve_stage="perfect_foresight_week",
                artifact_id=artifact_id,
                model_label="True perfect foresight reused",
                gamma=None,
                week_id="reused_from_reference_run",
                delivery_day=None,
                wall_time_seconds=0.0,
                used_cache=True,
                solver_status="Optimal",
            )
        )
    else:
        for _, week_row in week_manifest.iterrows():
            week_id = str(week_row["week_id"])
            week_days = list(week_row["included_delivery_days"])
            week_series = pd.Series(
                {
                    "week_id": str(week_row["week_id"]),
                    "week_label": str(week_row["week_label"]),
                    "regime_label": "full_year_test",
                    "selection_reason": "full_year_calendar_week",
                }
            )

            bench_cache_path = run_dir / "cache" / f"{week_id}__benchmark_daily.csv"
            bench_started = perf_counter()
            benchmark_daily, benchmark_tracker = _run_price_insensitive_week_variant(
                week_row=week_series,
                week_days=week_days,
                reference_days=reference_days,
                config=suite_config,
                settings=settings,
                production_variant=PHASE_E5_TARGET_MODE,
                physical_daily_max_kg=float(physical_daily_max_kg),
                emergency_import_price=float(emergency_import_price),
                run_id=run_id,
                cache_path=bench_cache_path,
                accounting_lookup=target_accounting_lookup,
            )
            benchmark_frames.append(benchmark_daily)
            weekly_tracker_rows.append(benchmark_tracker)
            runtime_rows.append(
                _stage_runtime_row(
                    solve_stage="price_insensitive_week",
                    artifact_id=artifact_id,
                    model_label="Price insensitive benchmark",
                    gamma=None,
                    week_id=week_id,
                    delivery_day=None,
                    wall_time_seconds=float(perf_counter() - bench_started),
                    used_cache=bench_cache_path.exists(),
                    solver_status="Optimal" if benchmark_daily["solver_status"].astype(str).map(_accepted_solver_status).all() else "non_optimal_present",
                )
            )
            for row in benchmark_daily.loc[benchmark_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
                benchmark_daily_map[(str(week_id), str(row.delivery_day))] = pd.Series(row._asdict())

            pf_cache_path = run_dir / "cache" / f"{week_id}__perfect_foresight_daily.csv"
            pf_started = perf_counter()
            pf_daily, pf_tracker = _run_perfect_foresight_week_variant(
                week_row=week_series,
                week_days=week_days,
                reference_days=reference_days,
                config=suite_config,
                settings=settings,
                production_variant=PHASE_E5_TARGET_MODE,
                physical_daily_max_kg=float(physical_daily_max_kg),
                emergency_import_price=float(emergency_import_price),
                run_id=run_id,
                cache_path=pf_cache_path,
                accounting_lookup=target_accounting_lookup,
            )
            pf_daily["target_mode"] = PHASE_E5_TARGET_MODE
            perfect_foresight_frames.append(pf_daily)
            weekly_tracker_rows.append(pf_tracker)
            runtime_rows.append(
                _stage_runtime_row(
                    solve_stage="perfect_foresight_week",
                    artifact_id=artifact_id,
                    model_label="Perfect foresight",
                    gamma=None,
                    week_id=week_id,
                    delivery_day=None,
                    wall_time_seconds=float(perf_counter() - pf_started),
                    used_cache=pf_cache_path.exists(),
                    solver_status="Optimal" if pf_daily["solver_status"].astype(str).map(_accepted_solver_status).all() else "non_optimal_present",
                )
            )
            for row in pf_daily.loc[pf_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
                perfect_foresight_daily_map[(str(week_id), str(row.delivery_day))] = pd.Series(row._asdict())

    cache_dir = run_dir / "cache"
    checkpoint_store = _load_checkpoint_store(cache_dir)
    day_run_registry = _rebuild_stochastic_registry_from_day_runs(run_dir, artifact_id=artifact_id)
    checkpoint_store["registry"] = _deduplicate_registry(
        pd.concat([checkpoint_store["registry"], day_run_registry], ignore_index=True)
        if not day_run_registry.empty
        else checkpoint_store["registry"]
    )
    _atomic_write_csv(_stochastic_checkpoint_paths(cache_dir)["registry"], checkpoint_store["registry"])

    chunk_start_day = str(chunk_start) if chunk_start else (included_days[0] if included_days else "")
    chunk_end_day = str(chunk_end) if chunk_end else (included_days[-1] if included_days else "")
    if chunk_start_day and chunk_end_day and chunk_start_day > chunk_end_day:
        raise ValueError(f"chunk_start={chunk_start_day} is after chunk_end={chunk_end_day}.")
    audit_day_set = set(normalized_audit_days)
    completed_metric_keys = {
        (float(gamma), str(day))
        for gamma, day in zip(
            pd.to_numeric(checkpoint_store["daily_metrics"].get("cvar_gamma", pd.Series(dtype=float)), errors="coerce").fillna(np.nan),
            checkpoint_store["daily_metrics"].get("delivery_day", pd.Series(dtype=str)).astype(str),
        )
        if pd.notna(gamma)
    }
    weekly_tracker_lookup = {
        (float(row.gamma), str(row.delivery_day)): row
        for row in checkpoint_store["weekly_tracker"].itertuples()
        if pd.notna(row.gamma)
    }
    checkpoint_registry_lookup = {
        (float(row.cvar_gamma), str(row.delivery_day)): row
        for row in checkpoint_store["registry"].itertuples()
        if pd.notna(row.cvar_gamma)
    }
    pending_store: dict[str, list[pd.DataFrame] | list[dict[str, Any]]] = {
        "registry": [],
        "daily_metrics": [],
        "actual_settlement": [],
        "scenario_settlement": [],
        "validation_checks": [],
        "actual_clearing": [],
        "actual_redispatch": [],
        "submitted_bids": [],
        "scenario_clearing": [],
        "weekly_tracker": [],
        "runtime_diagnostics": [],
        "infeasibility_report": [],
    }

    model_label = _label_for_artifact(artifact_id)
    new_solve_count = 0
    pending_commit_count = 0
    stop_requested = False
    try:
        for gamma in selected_gammas:
            if stop_requested:
                break
            for _, week_row in week_manifest.iterrows():
                if stop_requested:
                    break
                week_id = str(week_row["week_id"])
                week_label = str(week_row["week_label"])
                week_days = list(week_row["included_delivery_days"])
                inventory_start = float(suite_config.hydrogen_system.storage_initial_kg)
                cumulative = 0.0
                block_remaining_days = False
                week_series = pd.Series(
                    {
                        "week_id": week_id,
                        "week_label": week_label,
                        "regime_label": "full_year_test",
                        "selection_reason": "full_year_calendar_week",
                    }
                )
                for delivery_day in week_days:
                    day_payload = reference_days[delivery_day]
                    day_meta = day_payload["day_meta"]
                    accounting_day = target_accounting_lookup[delivery_day]
                    bounds = _compute_variant_bounds(
                        settings=settings,
                        production_variant=PHASE_E5_TARGET_MODE,
                        cumulative_realised_h2_kg_before_today=float(cumulative),
                        days_remaining_in_week=None,
                        physical_daily_max_kg=float(physical_daily_max_kg),
                        accounting_day=accounting_day,
                    )
                    day_key = (float(gamma), str(delivery_day))
                    if block_remaining_days and day_key in completed_metric_keys:
                        tracker_row = weekly_tracker_lookup.get(day_key)
                        if tracker_row is not None:
                            cumulative = float(getattr(tracker_row, "cumulative_after_kg"))
                            inventory_start = float(getattr(tracker_row, "storage_end_kg"))
                            block_remaining_days = not _accepted_solver_status(str(getattr(tracker_row, "solver_status")))
                        continue
                    if day_key in completed_metric_keys:
                        tracker_row = weekly_tracker_lookup.get(day_key)
                        if tracker_row is not None:
                            cumulative = float(getattr(tracker_row, "cumulative_after_kg"))
                            if _accepted_solver_status(str(getattr(tracker_row, "solver_status"))):
                                inventory_start = float(getattr(tracker_row, "storage_end_kg"))
                            else:
                                block_remaining_days = True
                        continue

                    cached_row = checkpoint_registry_lookup.get(day_key)
                    payload: dict[str, Any] | None = None
                    if cached_row is not None and str(getattr(cached_row, "storage_kind", "day_run")) == "day_run":
                        day_run_dir = Path(str(getattr(cached_row, "day_run_dir", "")))
                        if day_run_dir.exists():
                            load_started = perf_counter()
                            payload = _load_cached_day_payload(pd.Series(cached_row._asdict()), model_id=str(day_payload["model_id"]))
                            runtime_row = _stage_runtime_row(
                                solve_stage="stochastic_bidding_day",
                                artifact_id=artifact_id,
                                model_label=model_label,
                                gamma=float(gamma),
                                week_id=week_id,
                                delivery_day=delivery_day,
                                wall_time_seconds=float(perf_counter() - load_started),
                                used_cache=True,
                                solver_status=str(payload["stochastic_solver_status"]),
                            )
                            pending_store["runtime_diagnostics"].append(pd.DataFrame([runtime_row]))
                            appended = _append_stochastic_payload_outputs(
                                pending_store=pending_store,
                                run_id=run_id,
                                artifact_id=artifact_id,
                                model_label=model_label,
                                week_id=week_id,
                                week_label=week_label,
                                delivery_day=delivery_day,
                                day_payload=day_payload,
                                day_meta=day_meta,
                                week_series=week_series,
                                payload=payload,
                                gamma=float(gamma),
                                alpha=float(alpha),
                                emergency_import_price=float(emergency_import_price),
                                benchmark_profit_row=benchmark_daily_map.get((week_id, delivery_day)),
                                perfect_foresight_profit_row=perfect_foresight_daily_map.get((week_id, delivery_day)),
                                bounds=bounds,
                                cumulative_before_kg=float(cumulative),
                                inventory_start_kg=float(inventory_start),
                            )
                            completed_metric_keys.add(day_key)
                            weekly_tracker_lookup[day_key] = appended["tracker_row"]
                            block_remaining_days = not bool(appended["accepted_actual"])
                            cumulative = float(appended["cumulative_after_kg"])
                            if appended["accepted_actual"]:
                                inventory_start = float(appended["actual_summary"]["terminal_inventory_end_kg"])
                            pending_commit_count += 1
                            if pending_commit_count % checkpoint_every_n_solves == 0:
                                checkpoint_store = _flush_checkpoint_store(
                                    cache_dir=cache_dir,
                                    existing_store=checkpoint_store,
                                    pending_store=pending_store,
                                    expected_days=included_days,
                                    artifact_id=artifact_id,
                                    gammas=gamma_values,
                                )
                                pending_store = {key: [] for key in pending_store}
                            continue

                    within_chunk = (not chunk_start_day or str(delivery_day) >= chunk_start_day) and (not chunk_end_day or str(delivery_day) <= chunk_end_day)
                    if not within_chunk:
                        if chunk_start_day and str(delivery_day) < chunk_start_day:
                            raise RuntimeError(
                                f"Cannot start chunk at {chunk_start_day} for gamma={gamma:.2f}: prerequisite delivery day {delivery_day} is still missing."
                            )
                        stop_requested = True
                        break
                    if max_new_solves is not None and new_solve_count >= int(max_new_solves):
                        stop_requested = True
                        break

                    if not bool(bounds.tracker_feasible):
                        infeasible_status = "warning:infeasible_weekly_target_bounds"
                        metric_row = _build_skipped_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            validation_mode=str(day_payload["validation_mode"]),
                            thesis_grade=bool(day_payload["thesis_grade"]),
                            forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                            week_row=week_series,
                            day_meta=day_meta,
                            day_payload=day_payload,
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_variant=PHASE_E5_TARGET_MODE,
                            bounds=bounds,
                            cumulative_before_kg=float(cumulative),
                            skip_reason=infeasible_status,
                            scenario_count=int(day_payload["scenarios"]["scenario_id"].astype(str).nunique()),
                            scenario_probability_check=True,
                            emergency_import_price=float(emergency_import_price),
                        )
                        pending_store["daily_metrics"].append(pd.DataFrame([metric_row]))
                        tracker_frame = pd.DataFrame(
                            [
                                {
                                    "strategy": metric_row["strategy"],
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "production_variant": PHASE_E5_TARGET_MODE,
                                    "week_id": week_id,
                                    "week_label": week_label,
                                    "delivery_day": delivery_day,
                                    "forecast_origin_utc": day_payload["forecast_origin_utc"],
                                    "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                    "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                    "weekly_target_kg": float(bounds.weekly_target_kg),
                                    "cumulative_before_kg": float(cumulative),
                                    "cumulative_after_kg": float(cumulative),
                                    "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                    "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                    "hydrogen_sold_or_compressed_kg": np.nan,
                                    "storage_start_kg": float(inventory_start),
                                    "storage_end_kg": float(inventory_start),
                                    "solver_status": infeasible_status,
                                    **target_accounting_fields_from_bounds(bounds),
                                }
                            ]
                        )
                        pending_store["weekly_tracker"].append(tracker_frame)
                        pending_store["runtime_diagnostics"].append(
                            pd.DataFrame(
                                [
                                    _stage_runtime_row(
                                        solve_stage="stochastic_bidding_day",
                                        artifact_id=artifact_id,
                                        model_label=model_label,
                                        gamma=float(gamma),
                                        week_id=week_id,
                                        delivery_day=delivery_day,
                                        wall_time_seconds=0.0,
                                        used_cache=False,
                                        solver_status=infeasible_status,
                                    )
                                ]
                            )
                        )
                        pending_store["infeasibility_report"].append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": model_label,
                                "gamma": float(gamma),
                                "week_id": week_id,
                                "week_label": week_label,
                                "delivery_day": delivery_day,
                                "issue_type": "infeasible_weekly_target_bounds",
                                "details": (
                                    f"daily_lower_bound_kg={float(bounds.daily_lower_bound_kg):.6f}; "
                                    f"daily_upper_bound_kg={float(bounds.daily_upper_bound_kg):.6f}; "
                                    f"remaining_target_before_today_kg={float(bounds.remaining_target_before_today_kg):.6f}; "
                                    f"days_remaining_in_week={int(bounds.days_remaining_in_week)}"
                                ),
                            }
                        )
                        completed_metric_keys.add(day_key)
                        weekly_tracker_lookup[day_key] = tracker_frame.iloc[0]
                        pending_commit_count += 1
                        if pending_commit_count % checkpoint_every_n_solves == 0:
                            checkpoint_store = _flush_checkpoint_store(
                                cache_dir=cache_dir,
                                existing_store=checkpoint_store,
                                pending_store=pending_store,
                                expected_days=included_days,
                                artifact_id=artifact_id,
                                gammas=gamma_values,
                            )
                            pending_store = {key: [] for key in pending_store}
                        continue

                    if block_remaining_days:
                        metric_row = _build_skipped_daily_metric(
                            run_id=run_id,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            validation_mode=str(day_payload["validation_mode"]),
                            thesis_grade=bool(day_payload["thesis_grade"]),
                            forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                            week_row=week_series,
                            day_meta=day_meta,
                            day_payload=day_payload,
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_variant=PHASE_E5_TARGET_MODE,
                            bounds=bounds,
                            cumulative_before_kg=float(cumulative),
                            skip_reason="not_run_after_prior_infeasible_redispatch",
                            scenario_count=int(day_payload["scenarios"]["scenario_id"].astype(str).nunique()),
                            scenario_probability_check=True,
                            emergency_import_price=float(emergency_import_price),
                        )
                        pending_store["daily_metrics"].append(pd.DataFrame([metric_row]))
                        tracker_frame = pd.DataFrame(
                            [
                                {
                                    "strategy": metric_row["strategy"],
                                    "artifact_id": artifact_id,
                                    "model_label": model_label,
                                    "gamma": float(gamma),
                                    "production_variant": PHASE_E5_TARGET_MODE,
                                    "week_id": week_id,
                                    "week_label": week_label,
                                    "delivery_day": delivery_day,
                                    "forecast_origin_utc": day_payload["forecast_origin_utc"],
                                    "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                    "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                    "weekly_target_kg": float(bounds.weekly_target_kg),
                                    "cumulative_before_kg": float(cumulative),
                                    "cumulative_after_kg": float(cumulative),
                                    "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                    "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                    "hydrogen_sold_or_compressed_kg": np.nan,
                                    "storage_start_kg": float(inventory_start),
                                    "storage_end_kg": float(inventory_start),
                                    "solver_status": "not_run_after_prior_infeasible_redispatch",
                                    **target_accounting_fields_from_bounds(bounds),
                                }
                            ]
                        )
                        pending_store["weekly_tracker"].append(tracker_frame)
                        pending_store["infeasibility_report"].append(
                            {
                                "artifact_id": artifact_id,
                                "model_label": model_label,
                                "gamma": float(gamma),
                                "week_id": week_id,
                                "week_label": week_label,
                                "delivery_day": delivery_day,
                                "issue_type": "skipped_after_prior_infeasible_redispatch",
                                "details": "Later days in the same week were not simulated after an infeasible realised redispatch day.",
                            }
                        )
                        completed_metric_keys.add(day_key)
                        weekly_tracker_lookup[day_key] = tracker_frame.iloc[0]
                        continue

                    if payload is None:
                        write_full_outputs = normalized_day_output_mode == "full" or str(delivery_day) in audit_day_set
                        day_started = perf_counter()
                        live_result = run_real_scenario_bidding_dry_run(
                            config=suite_config,
                            artifact_id=artifact_id,
                            forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                            max_origins=1,
                            output_root=run_dir / "day_runs",
                            strategy_name="phase_e5_full_year_repaired_lear_strict",
                            dry_run_label="phase_e5_full_year_repaired_lear_strict",
                            include_price_insensitive_comparison=False,
                            risk_measure="risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
                            cvar_alpha=float(alpha),
                            cvar_gamma=float(gamma),
                            production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                            inventory_start_kg=inventory_start,
                            reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                            target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                            target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                            terminal_reference_start_kg=inventory_start,
                            emergency_import_price_eur_per_mwh=float(emergency_import_price),
                            write_outputs=bool(write_full_outputs),
                        )
                        if not write_full_outputs:
                            actual_status = str(live_result.actual_settlement_results["solver_status"].iloc[0])
                            stochastic_status = str(live_result.optimisation_result.solver.status)
                            if (not _accepted_solver_status(stochastic_status)) or (not _accepted_solver_status(actual_status)):
                                live_result = run_real_scenario_bidding_dry_run(
                                    config=suite_config,
                                    artifact_id=artifact_id,
                                    forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                                    max_origins=1,
                                    output_root=run_dir / "day_runs",
                                    strategy_name="phase_e5_full_year_repaired_lear_strict",
                                    dry_run_label="phase_e5_full_year_repaired_lear_strict",
                                    include_price_insensitive_comparison=False,
                                    risk_measure="risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
                                    cvar_alpha=float(alpha),
                                    cvar_gamma=float(gamma),
                                    production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                                    inventory_start_kg=inventory_start,
                                    reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
                                    target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                                    target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                                    terminal_reference_start_kg=inventory_start,
                                    emergency_import_price_eur_per_mwh=float(emergency_import_price),
                                    write_outputs=True,
                                )
                                write_full_outputs = True
                        payload = _payload_from_live_result(live_result, model_id=str(day_payload["model_id"]))
                        runtime_row = _stage_runtime_row(
                            solve_stage="stochastic_bidding_day",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            gamma=float(gamma),
                            week_id=week_id,
                            delivery_day=delivery_day,
                            wall_time_seconds=float(perf_counter() - day_started),
                            used_cache=False,
                            solver_status=str(payload["stochastic_solver_status"]),
                        )
                        pending_store["runtime_diagnostics"].append(pd.DataFrame([runtime_row]))
                        storage_kind = "day_run" if write_full_outputs else "checkpoint"
                        pending_store["registry"].append(
                            {
                                "week_id": week_id,
                                "delivery_day": delivery_day,
                                "artifact_id": artifact_id,
                                "cvar_gamma": float(gamma),
                                "day_run_dir": "" if payload["run_dir"] is None else str(payload["run_dir"]),
                                "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]).isoformat(),
                                "storage_kind": storage_kind,
                                "solver_status": str(payload["stochastic_solver_status"]),
                                "actual_redispatch_solver_status": str(payload["actual_settlement_results"].iloc[0]["solver_status"]),
                                "committed_at_utc": pd.Timestamp.utcnow().isoformat(),
                            }
                        )
                        checkpoint_registry_lookup[day_key] = type("RegistryRow", (), pending_store["registry"][-1])()
                        new_solve_count += 1
                        if new_solve_count % 10 == 0:
                            print(f"[E5] completed {new_solve_count} new stochastic solves in this run")

                    appended = _append_stochastic_payload_outputs(
                        pending_store=pending_store,
                        run_id=run_id,
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=week_id,
                        week_label=week_label,
                        delivery_day=delivery_day,
                        day_payload=day_payload,
                        day_meta=day_meta,
                        week_series=week_series,
                        payload=payload,
                        gamma=float(gamma),
                        alpha=float(alpha),
                        emergency_import_price=float(emergency_import_price),
                        benchmark_profit_row=benchmark_daily_map.get((week_id, delivery_day)),
                        perfect_foresight_profit_row=perfect_foresight_daily_map.get((week_id, delivery_day)),
                        bounds=bounds,
                        cumulative_before_kg=float(cumulative),
                        inventory_start_kg=float(inventory_start),
                    )
                    completed_metric_keys.add(day_key)
                    weekly_tracker_lookup[day_key] = appended["tracker_row"]
                    if not appended["accepted_actual"]:
                        block_remaining_days = True
                    cumulative = float(appended["cumulative_after_kg"])
                    if appended["accepted_actual"]:
                        inventory_start = float(appended["actual_summary"]["terminal_inventory_end_kg"])
                    pending_commit_count += 1

                    if pending_commit_count > 0 and pending_commit_count % checkpoint_every_n_solves == 0:
                        checkpoint_store = _flush_checkpoint_store(
                            cache_dir=cache_dir,
                            existing_store=checkpoint_store,
                            pending_store=pending_store,
                            expected_days=included_days,
                            artifact_id=artifact_id,
                            gammas=gamma_values,
                        )
                        pending_store = {key: [] for key in pending_store}
    except Exception:
        checkpoint_store = _flush_checkpoint_store(
            cache_dir=cache_dir,
            existing_store=checkpoint_store,
            pending_store=pending_store,
            expected_days=included_days,
            artifact_id=artifact_id,
            gammas=gamma_values,
        )
        raise

    checkpoint_store = _flush_checkpoint_store(
        cache_dir=cache_dir,
        existing_store=checkpoint_store,
        pending_store=pending_store,
        expected_days=included_days,
        artifact_id=artifact_id,
        gammas=gamma_values,
    )

    daily_metrics = checkpoint_store["daily_metrics"].copy().sort_values(["cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase E5 produced no daily metrics.")
    runtime_diagnostics = checkpoint_store["runtime_diagnostics"].copy()
    actual_settlement_results = checkpoint_store["actual_settlement"].copy()
    scenario_settlement_results = checkpoint_store["scenario_settlement"].copy()
    validation_checks = checkpoint_store["validation_checks"].copy()
    actual_clearing = checkpoint_store["actual_clearing"].copy()
    actual_redispatch = checkpoint_store["actual_redispatch"].copy()
    submitted_bids = checkpoint_store["submitted_bids"].copy()
    scenario_clearing = checkpoint_store["scenario_clearing"].copy()
    weekly_target_tracker = checkpoint_store["weekly_tracker"].copy()
    infeasibility_report = checkpoint_store["infeasibility_report"].copy()
    daily_metrics = _enrich_target_accounting_columns(frame=daily_metrics, accounting_frame=target_accounting_frame)
    weekly_target_tracker = _enrich_target_accounting_columns(frame=weekly_target_tracker, accounting_frame=target_accounting_frame)
    weekly_metrics = _build_weekly_metrics(daily_metrics=daily_metrics, week_manifest=week_manifest)
    if not weekly_metrics.empty:
        for row in weekly_metrics.itertuples():
            mask = (
                daily_metrics["week_id"].astype(str).eq(str(row.week_id))
                & pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").eq(float(row.cvar_gamma))
            )
            daily_metrics.loc[mask, "weekly_target_met"] = bool(row.weekly_target_met)
    monthly_metrics = _build_monthly_metrics(daily_metrics=daily_metrics)
    runtime_diagnostics = pd.concat([checkpoint_store["runtime_diagnostics"].copy(), pd.DataFrame(runtime_rows)], ignore_index=True)
    annual_metrics_by_gamma = _build_annual_metrics_by_gamma(
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        runtime_diagnostics=runtime_diagnostics,
    )

    if reused_reference_frames is not None:
        benchmark_metrics = reused_reference_frames["benchmark_metrics"].copy()
        perfect_foresight_metrics = reused_reference_frames["perfect_foresight_metrics"].copy()
    else:
        benchmark_daily = pd.concat(benchmark_frames, ignore_index=True) if benchmark_frames else pd.DataFrame()
        perfect_foresight_daily = pd.concat(perfect_foresight_frames, ignore_index=True) if perfect_foresight_frames else pd.DataFrame()
        benchmark_daily, benchmark_weekly, benchmark_extra = _aggregate_reference_periods(benchmark_daily, week_manifest)
        perfect_foresight_daily, perfect_foresight_weekly, perfect_foresight_extra = _aggregate_reference_periods(perfect_foresight_daily, week_manifest)
        benchmark_metrics = pd.concat([benchmark_daily, benchmark_weekly, benchmark_extra], ignore_index=True) if not benchmark_daily.empty else pd.DataFrame()
        perfect_foresight_metrics = pd.concat([perfect_foresight_daily, perfect_foresight_weekly, perfect_foresight_extra], ignore_index=True) if not perfect_foresight_daily.empty else pd.DataFrame()
    if weekly_tracker_rows:
        weekly_target_tracker = pd.concat([pd.concat(weekly_tracker_rows, ignore_index=True), weekly_target_tracker], ignore_index=True)

    suite_validation_checks = _build_validation_checks(
        artifact_id=artifact_id,
        gamma_values=gamma_values,
        alpha=float(alpha),
        target_mode=PHASE_E5_TARGET_MODE,
        emergency_import_price=float(emergency_import_price),
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        weekly_tracker=weekly_target_tracker,
        actual_clearing=actual_clearing,
        actual_redispatch=actual_redispatch,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        dst_excluded_days=dst_excluded_days,
    )
    validation_checks_all_runs = pd.concat([validation_checks, suite_validation_checks], ignore_index=True)
    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics.loc[pd.to_numeric(daily_metrics["expected_adjusted_profit"], errors="coerce").notna()].copy(),
        scenario_settlement_results=scenario_settlement_results,
        alpha=float(alpha),
        gamma_values=gamma_values,
    )
    cvar_validation_checks = pd.concat(
        [
            cvar_validation_checks,
            pd.DataFrame(
                [
                    _validation_row(
                        check_name="phase_e5_gamma_alpha_target_mode_confirmed",
                        status="pass",
                        details=f"alpha={float(alpha):.2f}; gammas={gamma_values}; target_mode={PHASE_E5_TARGET_MODE}",
                        severity="hard_fail",
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    emergency_import_summary = _build_emergency_import_summary(
        daily_metrics=daily_metrics.assign(production_variant=PHASE_E5_TARGET_MODE)
    )
    runtime_summary = _build_runtime_summary(runtime_diagnostics)
    progress_after = _progress_counts_from_registry(
        checkpoint_store["registry"],
        daily_metrics=checkpoint_store["daily_metrics"],
        artifact_id=artifact_id,
        gammas=gamma_values,
        expected_days=included_days,
    )
    full_year_complete = bool(progress_after["remaining_solves"].astype(int).sum() == 0)
    if full_year_complete:
        annual_metrics_with_true_pf = (
            _annual_with_true_pf_from_reference(
                annual_metrics_by_gamma=annual_metrics_by_gamma,
                weekly_metrics=weekly_metrics,
                reuse_run_dir=Path(reuse_true_pf_from),
            )
            if reuse_true_pf_from is not None
            else pd.DataFrame()
        )
        save_frame_csv(run_dir, "weekly_target_tracker.csv", weekly_target_tracker)
        save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
        save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
        save_frame_csv(run_dir, "monthly_metrics.csv", monthly_metrics)
        save_frame_csv(run_dir, "annual_metrics_by_gamma.csv", annual_metrics_by_gamma)
        save_frame_csv(run_dir, "emergency_import_summary.csv", emergency_import_summary)
        save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
        save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
        save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
        save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)
        save_frame_csv(run_dir, "infeasibility_report.csv", infeasibility_report)
        save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
        save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
        save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
        save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
        if not annual_metrics_with_true_pf.empty:
            save_frame_csv(run_dir, "annual_metrics_by_gamma_with_true_pf.csv", annual_metrics_with_true_pf)

        _save_parquet_if_possible(run_dir, "submitted_bids.parquet", submitted_bids)
        _save_parquet_if_possible(run_dir, "actual_clearing.parquet", actual_clearing)
        _save_parquet_if_possible(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch)
        if PERSIST_SCENARIO_CLEARING_CHECKPOINT and not scenario_clearing.empty:
            _save_parquet_if_possible(run_dir, "scenario_clearing.parquet", scenario_clearing)

        readme = _build_readme(
            test_start=str(test_start),
            test_end=str(test_end),
            included_days=included_days,
            dst_excluded_days=dst_excluded_days,
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            annual_metrics_by_gamma=annual_metrics_by_gamma,
            emergency_import_summary=emergency_import_summary,
            benchmark_metrics=benchmark_metrics,
            perfect_foresight_metrics=perfect_foresight_metrics,
            runtime_summary=runtime_summary,
            validation_checks=validation_checks_all_runs,
            support_preflight=support_preflight,
            selected_artifact_manifest=selected_artifact_manifest,
        )
        save_text(run_dir, "README_full_year_repaired_lear_strict.md", readme)
        if gamma_values == [PHASE_E5D_EXTENSION_GAMMA]:
            g005_readme = _build_readme(
                test_start=str(test_start),
                test_end=str(test_end),
                included_days=included_days,
                dst_excluded_days=dst_excluded_days,
                daily_metrics=daily_metrics,
                weekly_metrics=weekly_metrics,
                annual_metrics_by_gamma=annual_metrics_by_gamma,
                emergency_import_summary=emergency_import_summary,
                benchmark_metrics=benchmark_metrics,
                perfect_foresight_metrics=perfect_foresight_metrics,
                runtime_summary=runtime_summary,
                validation_checks=validation_checks_all_runs,
                support_preflight=support_preflight,
                selected_artifact_manifest=selected_artifact_manifest,
            )
            save_text(run_dir, "README_full_year_repaired_lear_strict_g005.md", g005_readme)
        if reuse_true_pf_from is not None and not annual_metrics_with_true_pf.empty:
            _build_gamma_extension_comparison(
                extension_run_dir=run_dir,
                baseline_run_dir=Path(reuse_true_pf_from),
                extension_annual_with_true_pf=annual_metrics_with_true_pf,
            )
    else:
        print(
            "[E5] annual outputs deferred: "
            f"remaining_solves_total={int(progress_after['remaining_solves'].astype(int).sum())}"
        )

    return PhaseE5FullYearResult(
        run_dir=run_dir,
        support_preflight=support_preflight,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        monthly_metrics=monthly_metrics,
        annual_metrics_by_gamma=annual_metrics_by_gamma,
        emergency_import_summary=emergency_import_summary,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )
