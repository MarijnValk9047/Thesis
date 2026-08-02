"""Canonical Strict LEAR hourly/QH D..D+4 finalisation pipeline.

This module owns the observed-support grid, mean-shape walk-forward extension,
coupled residual blocks, scenario calibration/reduction, contract checks and
compact statistical reporting.  It deliberately does not call an optimisation
model and keeps realised prices out of optimisation-facing exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time as wall_time
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from hourly_da.core.coupled_multiday_scenarios import (
    ResidualBlock,
    crps_by_timestamp,
    eligible_blocks,
    energy_score,
    generate_raw_coupled_paths,
    stable_seed,
    weighted_interval_summary,
)
from hourly_da.core.multiday_scenario_reduction import assert_nested_reduction, reduce_weighted_paths
from quarterhour_da.phase04 import _fit_mean_shape, _predict_mean_shape


LOCAL_TIMEZONE = "Europe/Amsterdam"
HOURLY_MODEL_ID = "lear_lago_direct_dplus4_strict_no_future_1092"
QH_MODEL_ID = "qh-fs1__mean_shape__hourly_anchor__lear_strict"
SCENARIO_COLUMNS = [
    "model_id",
    "granularity",
    "forecast_origin_utc",
    "target_timestamp_utc",
    "lead_day",
    "scenario_set_size",
    "scenario_id",
    "parent_scenario_id",
    "scenario_probability",
    "point_forecast",
    "scenario_price",
    "source_residual_block_id",
]


@dataclass(frozen=True)
class FinalisationConfig:
    train_start_local_date: date
    validation_start_local_date: date
    evaluation_start_local_date: date
    requested_end_local_date: date
    raw_scenarios: int
    final_scenarios: int
    nested_scenarios: int
    level_scales: tuple[float, ...]
    shape_scales: tuple[float, ...]
    protected_tail_share: float
    window_days: int
    random_seed: int


def load_config(path: Path) -> FinalisationConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FinalisationConfig(
        train_start_local_date=date.fromisoformat(payload["timeline"]["train_start_local_date"]),
        validation_start_local_date=date.fromisoformat(payload["timeline"]["validation_start_local_date"]),
        evaluation_start_local_date=date.fromisoformat(payload["timeline"]["evaluation_start_local_date"]),
        requested_end_local_date=date.fromisoformat(payload["timeline"]["requested_end_local_date"]),
        raw_scenarios=int(payload["scenarios"]["raw_count"]),
        final_scenarios=int(payload["scenarios"]["final_count"]),
        nested_scenarios=int(payload["scenarios"]["nested_count"]),
        level_scales=tuple(float(v) for v in payload["scenarios"]["level_scales"]),
        shape_scales=tuple(float(v) for v in payload["scenarios"]["shape_scales"]),
        protected_tail_share=float(payload["scenarios"]["protected_tail_share"]),
        window_days=int(payload["hourly_anchor"]["window_days"]),
        random_seed=int(payload["scenarios"]["random_seed"]),
    )


def _timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")


def _local_day_bounds(local_day: date, frequency: str) -> pd.DatetimeIndex:
    start = pd.Timestamp(datetime.combine(local_day, time.min)).tz_localize(LOCAL_TIMEZONE)
    end = pd.Timestamp(datetime.combine(local_day + timedelta(days=1), time.min)).tz_localize(LOCAL_TIMEZONE)
    return pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq=frequency, inclusive="left")


def _forecast_origin(local_day: date) -> pd.Timestamp:
    local = pd.Timestamp(datetime.combine(local_day - timedelta(days=1), time(hour=8))).tz_localize(LOCAL_TIMEZONE)
    return local.tz_convert("UTC")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")


def load_observed_qh(historical_path: Path, refreshed_path: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for priority, path in enumerate((historical_path, refreshed_path)):
        frame = pd.read_csv(path, low_memory=False)
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
        frame["price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
        frame = frame[frame.get("region", "NL").astype(str).eq("NL")].copy() if "region" in frame.columns else frame.copy()
        frame["_source_priority"] = int(priority)
        interpolated = frame.get("is_interpolated_value", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        flagged = frame.get("is_flagged_missing_value", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        frame["_observed"] = frame["price_eur_per_mwh"].notna() & ~interpolated & ~flagged
        frames.append(frame)
    merged = pd.concat(frames, ignore_index=True, sort=False).dropna(subset=["timestamp_utc"])
    merged = merged.sort_values(["timestamp_utc", "_observed", "_source_priority"], kind="stable")
    merged = merged.drop_duplicates(subset=["timestamp_utc"], keep="last")
    merged = merged[merged["_observed"]].copy().sort_values("timestamp_utc").reset_index(drop=True)
    merged["timestamp_local"] = merged["timestamp_utc"].dt.tz_convert(LOCAL_TIMEZONE)
    merged["local_date"] = merged["timestamp_local"].dt.date
    merged["hour_start_utc"] = merged["timestamp_utc"].dt.floor("h")
    merged["local_hour_of_day"] = merged["timestamp_local"].dt.hour.astype(int)
    merged["quarter_index"] = (merged["timestamp_local"].dt.minute // 15 + 1).astype(int)
    merged["weekend_flag"] = (merged["timestamp_local"].dt.dayofweek >= 5).astype(int)
    merged["known_at_utc"] = merged["timestamp_utc"] + pd.Timedelta(minutes=15)
    return merged


def build_supported_grid(qh: pd.DataFrame, config: FinalisationConfig) -> tuple[pd.DataFrame, pd.DataFrame, date]:
    available = set(qh["timestamp_utc"].tolist())
    complete_days: list[date] = []
    for local_day, group in qh.groupby("local_date"):
        expected = _local_day_bounds(local_day, "15min")
        if len(group) == len(expected) and set(group["timestamp_utc"]) == set(expected):
            complete_days.append(local_day)
    if not complete_days:
        raise ValueError("no complete observed QH days")
    last_complete = min(max(complete_days), config.requested_end_local_date)
    last_origin_day = last_complete - timedelta(days=4)
    price_map = qh.set_index("timestamp_utc")["price_eur_per_mwh"].to_dict()
    rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    base_day = config.train_start_local_date
    while base_day <= last_origin_day:
        origin = _forecast_origin(base_day)
        expected_parts = [_local_day_bounds(base_day + timedelta(days=lead), "15min") for lead in range(5)]
        expected = expected_parts[0].append(expected_parts[1:])
        missing = [timestamp for timestamp in expected if timestamp not in available]
        split = (
            "train"
            if base_day < config.validation_start_local_date
            else "validation"
            if base_day < config.evaluation_start_local_date
            else "evaluation"
        )
        support_rows.append(
            {
                "delivery_start_local_date": base_day.isoformat(),
                "forecast_origin_utc": origin,
                "dataset_split": split,
                "expected_qh_targets": int(len(expected)),
                "observed_qh_targets": int(len(expected) - len(missing)),
                "missing_qh_targets": int(len(missing)),
                "selected": len(missing) == 0,
                "exclusion_reason": "" if not missing else "incomplete_observed_D_Dplus4_truth",
            }
        )
        if not missing:
            horizon_index = 0
            for lead, timestamps in enumerate(expected_parts):
                for timestamp in timestamps:
                    horizon_index += 1
                    local = timestamp.tz_convert(LOCAL_TIMEZONE)
                    rows.append(
                        {
                            "delivery_start_local_date": base_day.isoformat(),
                            "forecast_origin_utc": origin,
                            "target_timestamp_utc": timestamp,
                            "target_timestamp_local": local,
                            "lead_day": int(lead),
                            "lead_day_label": "D" if lead == 0 else f"D+{lead}",
                            "horizon_index": int(horizon_index),
                            "quarter_in_hour": int(local.minute // 15 + 1),
                            "local_hour_of_day": int(local.hour),
                            "quarter_index": int(local.minute // 15 + 1),
                            "weekend_flag": int(local.dayofweek >= 5),
                            "hour_start_utc": timestamp.floor("h"),
                            "dataset_split": split,
                            "y_true": float(price_map[timestamp]),
                            "is_observed_target": True,
                        }
                    )
        base_day += timedelta(days=1)
    grid = pd.DataFrame(rows).sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    support = pd.DataFrame(support_rows)
    return grid, support, last_complete


def _merge_timestamp_csv(base_path: Path, overlay_path: Path, output_path: Path) -> None:
    base = pd.read_csv(base_path, low_memory=False)
    overlay = pd.read_csv(overlay_path, low_memory=False)
    combined = pd.concat([base.assign(_priority=0), overlay.assign(_priority=1)], ignore_index=True, sort=False)
    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True, errors="coerce")
    keys = ["timestamp_utc"]
    for candidate in ("market", "region", "psr_type"):
        if candidate in combined.columns:
            keys.append(candidate)
    combined = combined.dropna(subset=["timestamp_utc"]).sort_values(keys + ["_priority"], kind="stable")
    combined = combined.drop_duplicates(subset=keys, keep="last").drop(columns=["_priority"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)


def prepare_anchor_inputs(
    *,
    run_dir: Path,
    staging_root: Path | None = None,
    legacy_cleaned_root: Path,
    refreshed_root: Path,
    refreshed_res_cleaned_root: Path,
    qh: pd.DataFrame,
    horizon_policy_csv: Path,
) -> tuple[Path, Path, Path]:
    operational_root = staging_root if staging_root is not None else run_dir / "inputs"
    staged = operational_root / "cleaned"
    mappings = (
        (
            legacy_cleaned_root / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
            refreshed_root / "da_load_forecast_2026.csv",
            staged / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
        ),
        (
            legacy_cleaned_root / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
            refreshed_root / "weekahead_load_2026.csv",
            staged / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
        ),
        (
            legacy_cleaned_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv",
            refreshed_res_cleaned_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv",
            staged / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv",
        ),
    )
    for base, overlay, output in mappings:
        if not base.exists() or not overlay.exists():
            raise FileNotFoundError(f"anchor input missing: base={base.exists()} overlay={overlay.exists()} ({base}, {overlay})")
        _merge_timestamp_csv(base, overlay, output)
    policy_copy = operational_root / "horizon_policy.csv"
    policy_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(horizon_policy_csv, policy_copy)

    hourly_old_path = legacy_cleaned_root / "Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv"
    hourly_old = pd.read_csv(hourly_old_path, low_memory=False)
    hourly_old["timestamp_utc"] = pd.to_datetime(hourly_old["timestamp_utc"], utc=True, errors="coerce")
    hourly_old["price_eur_per_mwh"] = pd.to_numeric(hourly_old["price_eur_per_mwh"], errors="coerce")
    qh_hourly = qh.groupby("hour_start_utc", as_index=False)["price_eur_per_mwh"].agg(["mean", "count"]).reset_index()
    qh_hourly = qh_hourly[qh_hourly["count"].eq(4)].rename(columns={"hour_start_utc": "timestamp_utc", "mean": "price_eur_per_mwh"})
    qh_hourly["region"] = "NL"
    bridge = pd.concat(
        [
            hourly_old[[column for column in hourly_old.columns if column in {"timestamp_utc", "region", "price_eur_per_mwh", "is_interpolated_value", "is_flagged_missing_value"}]],
            qh_hourly[["timestamp_utc", "region", "price_eur_per_mwh"]],
        ],
        ignore_index=True,
        sort=False,
    )
    bridge = bridge.dropna(subset=["timestamp_utc", "price_eur_per_mwh"]).sort_values("timestamp_utc")
    bridge = bridge.drop_duplicates(subset=["timestamp_utc", "region"], keep="last")
    bridge_path = operational_root / "hourly_price_bridge.csv"
    bridge.to_csv(bridge_path, index=False)
    return staged, policy_copy, bridge_path


def write_anchor_targets(grid: pd.DataFrame, path: Path) -> None:
    target = grid.copy()
    target["price_eur_per_mwh"] = target["y_true"]
    target.to_csv(path, index=False)


def run_hourly_anchor(
    *,
    repo_root: Path,
    run_dir: Path,
    target_path: Path,
    bridge_path: Path,
    staged_cleaned_root: Path,
    horizon_policy_csv: Path,
    anchor_seed_predictions: Path | None,
    window_days: int,
) -> Path:
    anchor_dir = run_dir / "anchor"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    existing_parquet = anchor_dir / "predictions_long.parquet"
    existing_csv = anchor_dir / "predictions_long.csv"
    existing_summary = anchor_dir / "run_summary.json"
    if existing_summary.exists() and (existing_parquet.exists() or existing_csv.exists()):
        summary = json.loads(existing_summary.read_text(encoding="utf-8"))
        if bool(summary.get("completed_successfully")):
            return existing_parquet if existing_parquet.exists() else existing_csv
    if anchor_seed_predictions is not None and anchor_seed_predictions.exists() and not existing_csv.exists():
        seed = pd.read_csv(anchor_seed_predictions, low_memory=False)
        targets = pd.read_csv(target_path, usecols=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "quarter_in_hour"])
        targets = targets[targets["quarter_in_hour"].eq(1)].drop(columns=["quarter_in_hour"])
        for frame in (seed, targets):
            frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
            frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
            frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
        seeded = seed.merge(targets.drop_duplicates(), on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"], how="inner")
        seeded.to_csv(anchor_dir / "predictions_long.csv", index=False)
    script = repo_root / "scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/run_lago_lear_export_for_qh.py"
    command = [
        sys.executable,
        str(script),
        "--targets-by-origin",
        str(target_path),
        "--bridge-source",
        "bridge_path",
        "--bridge-path",
        str(bridge_path),
        "--staged-cleaned-root",
        str(staged_cleaned_root),
        "--horizon-policy-csv",
        str(horizon_policy_csv),
        "--window-days",
        str(int(window_days)),
        "--run-dir",
        str(anchor_dir),
        "--resume",
        "--checkpoint-flush-rows",
        "240",
        "--log-every-rows",
        "240",
        "--n-jobs",
        "6",
    ]
    completed = subprocess.run(command, cwd=repo_root, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Strict LEAR anchor exporter failed with exit code {completed.returncode}")
    prediction_path = anchor_dir / "predictions_long.parquet"
    if not prediction_path.exists():
        prediction_path = anchor_dir / "predictions_long.csv"
    return prediction_path


def build_point_forecasts(qh: pd.DataFrame, grid: pd.DataFrame, anchor_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    anchor = pd.read_parquet(anchor_path) if anchor_path.suffix == ".parquet" else pd.read_csv(anchor_path, low_memory=False)
    anchor["forecast_origin_utc"] = pd.to_datetime(anchor["forecast_origin_utc"], utc=True, errors="coerce")
    anchor["target_timestamp_utc"] = pd.to_datetime(anchor["target_timestamp_utc"], utc=True, errors="coerce")
    anchor["hour_start_utc"] = anchor["target_timestamp_utc"].dt.floor("h")
    anchor = anchor.rename(columns={"y_pred": "hourly_point_forecast"})
    anchor = anchor[["forecast_origin_utc", "hour_start_utc", "lead_day", "hourly_point_forecast"]].drop_duplicates()
    point = grid.merge(anchor, on=["forecast_origin_utc", "hour_start_utc", "lead_day"], how="left")
    coverage = point.groupby("forecast_origin_utc")["hourly_point_forecast"].agg(["count", "size"]).reset_index()
    good_origins = set(coverage.loc[coverage["count"].eq(coverage["size"]), "forecast_origin_utc"])
    point = point[point["forecast_origin_utc"].isin(good_origins)].copy()
    if point.empty:
        raise ValueError("no fully covered origins remain after joining the Strict LEAR anchor")

    qh_complete = qh.groupby("hour_start_utc")["price_eur_per_mwh"].agg(["mean", "count"]).reset_index()
    qh_complete = qh_complete[qh_complete["count"].eq(4)].rename(columns={"mean": "hourly_actual"})
    shape_history = qh.merge(qh_complete[["hour_start_utc", "hourly_actual"]], on="hour_start_utc", how="inner")
    shape_history["delta_eur_per_mwh"] = shape_history["price_eur_per_mwh"] - shape_history["hourly_actual"]

    frames: list[pd.DataFrame] = []
    for origin, origin_frame in point.groupby("forecast_origin_utc", sort=True):
        training = shape_history[shape_history["known_at_utc"] <= pd.Timestamp(origin)].copy()
        if training.empty:
            continue
        state = _fit_mean_shape(training)
        ordered = origin_frame.sort_values("target_timestamp_utc").copy()
        raw = _predict_mean_shape(state, ordered)
        ordered["delta_pred_raw"] = raw
        ordered["delta_pred_adjusted"] = ordered["delta_pred_raw"] - ordered.groupby("hour_start_utc")["delta_pred_raw"].transform("mean")
        ordered["flat_qh_point_forecast"] = ordered["hourly_point_forecast"]
        ordered["qh_point_forecast"] = ordered["hourly_point_forecast"] + ordered["delta_pred_adjusted"]
        frames.append(ordered)
    qh_point = pd.concat(frames, ignore_index=True)
    hourly = (
        qh_point.groupby(["forecast_origin_utc", "hour_start_utc", "lead_day", "dataset_split"], as_index=False)
        .agg(point_forecast=("hourly_point_forecast", "first"), actual_price=("y_true", "mean"), qh_rows=("y_true", "size"))
        .rename(columns={"hour_start_utc": "target_timestamp_utc"})
    )
    qh_export = qh_point.rename(columns={"qh_point_forecast": "point_forecast", "y_true": "actual_price"})
    flat_export = qh_point.rename(columns={"flat_qh_point_forecast": "point_forecast", "y_true": "actual_price"})
    return hourly, qh_export, flat_export


def build_residual_blocks(hourly: pd.DataFrame, qh: pd.DataFrame) -> list[ResidualBlock]:
    blocks: list[ResidualBlock] = []
    for origin, qh_origin in qh[qh["dataset_split"].isin(["train", "validation"])].groupby("forecast_origin_utc"):
        hourly_origin = hourly[hourly["forecast_origin_utc"].eq(origin)].sort_values("target_timestamp_utc")
        qh_origin = qh_origin.sort_values("target_timestamp_utc").copy()
        if hourly_origin.empty or qh_origin.empty:
            continue
        hourly_origin["level_error"] = hourly_origin["actual_price"] - hourly_origin["point_forecast"]
        actual_hour_map = hourly_origin.set_index("target_timestamp_utc")["actual_price"].to_dict()
        qh_origin["hourly_actual"] = qh_origin["hour_start_utc"].map(actual_hour_map)
        qh_origin["shape_error"] = (
            qh_origin["actual_price"]
            - qh_origin["hourly_actual"]
            - qh_origin["delta_pred_adjusted"]
        )
        if qh_origin[["shape_error", "hourly_actual"]].isna().any().any():
            continue
        hourly_by_lead = tuple(
            hourly_origin.loc[hourly_origin["lead_day"].eq(lead), "level_error"].to_numpy(dtype=float)
            for lead in range(5)
        )
        shape_by_lead = tuple(
            qh_origin.loc[qh_origin["lead_day"].eq(lead), "shape_error"].to_numpy(dtype=float)
            for lead in range(5)
        )
        if any(values.size == 0 for values in hourly_by_lead + shape_by_lead):
            continue
        blocks.append(
            ResidualBlock(
                block_id=f"residual_origin_{pd.Timestamp(origin).strftime('%Y%m%dT%H%M%SZ')}",
                source_origin_utc=pd.Timestamp(origin),
                available_at_utc=pd.Timestamp(qh_origin["target_timestamp_utc"].max()) + pd.Timedelta(minutes=15),
                dataset_split=str(qh_origin["dataset_split"].iloc[0]),
                hourly_by_lead=hourly_by_lead,
                shape_by_lead=shape_by_lead,
            )
        )
    return blocks


def _origin_case(hourly: pd.DataFrame, qh: pd.DataFrame, origin: pd.Timestamp) -> dict[str, Any]:
    h = hourly[hourly["forecast_origin_utc"].eq(origin)].sort_values("target_timestamp_utc").reset_index(drop=True)
    q = qh[qh["forecast_origin_utc"].eq(origin)].sort_values("target_timestamp_utc").reset_index(drop=True)
    hour_lookup = {timestamp: index for index, timestamp in enumerate(h["target_timestamp_utc"].tolist())}
    qh_to_hour = q["hour_start_utc"].map(hour_lookup).to_numpy(dtype=int)
    return {
        "origin": pd.Timestamp(origin),
        "hourly_frame": h,
        "qh_frame": q,
        "hourly_point": h["point_forecast"].to_numpy(dtype=float),
        "qh_point": q["point_forecast"].to_numpy(dtype=float),
        "hourly_actual": h["actual_price"].to_numpy(dtype=float),
        "qh_actual": q["actual_price"].to_numpy(dtype=float),
        "hourly_counts": tuple(int(h["lead_day"].eq(lead).sum()) for lead in range(5)),
        "qh_counts": tuple(int(q["lead_day"].eq(lead).sum()) for lead in range(5)),
        "qh_to_hour": qh_to_hour,
    }


def calibrate_scenario_scales(
    *,
    hourly: pd.DataFrame,
    qh: pd.DataFrame,
    blocks: list[ResidualBlock],
    config: FinalisationConfig,
) -> tuple[float, float, pd.DataFrame]:
    origins = sorted(qh.loc[qh["dataset_split"].eq("validation"), "forecast_origin_utc"].unique().tolist())
    if not origins:
        raise ValueError("scenario calibration requires validation origins")
    rows: list[dict[str, Any]] = []
    for level_scale in config.level_scales:
        for shape_scale in config.shape_scales:
            summaries: list[dict[str, float]] = []
            violations = 0
            for origin_value in origins:
                case = _origin_case(hourly, qh, pd.Timestamp(origin_value))
                bank = eligible_blocks(blocks, forecast_origin_utc=case["origin"], allowed_splits={"train"})
                if not bank:
                    continue
                raw = generate_raw_coupled_paths(
                    hourly_point=case["hourly_point"],
                    qh_point=case["qh_point"],
                    hourly_counts_by_lead=case["hourly_counts"],
                    qh_counts_by_lead=case["qh_counts"],
                    qh_to_hour=case["qh_to_hour"],
                    residual_blocks=bank,
                    n_raw=config.raw_scenarios,
                    level_scale=level_scale,
                    shape_scale=shape_scale,
                    seed=stable_seed(config.random_seed, case["origin"], "calibration"),
                )
                weights = np.repeat(1.0 / config.raw_scenarios, config.raw_scenarios)
                summaries.append(weighted_interval_summary(raw.hourly, case["hourly_actual"], weights))
                summaries.append(weighted_interval_summary(raw.quarterhour, case["qh_actual"], weights))
                aggregated = np.column_stack(
                    [raw.quarterhour[:, np.asarray(case["qh_to_hour"]) == index].mean(axis=1) for index in range(raw.hourly.shape[1])]
                )
                if float(np.max(np.abs(aggregated - raw.hourly))) > 1e-10:
                    violations += 1
            if not summaries:
                continue
            frame = pd.DataFrame(summaries)
            coverage = float(frame["coverage_p05_p95"].mean())
            lower_distance = max(0.85 - coverage, 0.0)
            upper_distance = max(coverage - 0.90, 0.0)
            imbalance = float(abs(frame["high_tail_miss_rate"].mean() - frame["low_tail_miss_rate"].mean()))
            width = float(frame["average_width_p05_p95"].mean())
            rows.append(
                {
                    "level_scale": float(level_scale),
                    "shape_scale": float(shape_scale),
                    "weighted_coverage_p05_p95": coverage,
                    "high_tail_miss_rate": float(frame["high_tail_miss_rate"].mean()),
                    "low_tail_miss_rate": float(frame["low_tail_miss_rate"].mean()),
                    "average_width_p05_p95": width,
                    "methodological_violations": int(violations),
                    "selection_score": float(1000.0 * (lower_distance + upper_distance) + 100.0 * imbalance + 0.001 * width + 10000.0 * violations),
                    "validation_origin_count": int(len(summaries) // 2),
                }
            )
    table = pd.DataFrame(rows).sort_values(
        ["selection_score", "average_width_p05_p95", "level_scale", "shape_scale"]
    ).reset_index(drop=True)
    if table.empty:
        raise ValueError("no scenario calibration setting could be evaluated")
    selected = table.iloc[0]
    table["selected"] = False
    table.loc[0, "selected"] = True
    return float(selected["level_scale"]), float(selected["shape_scale"]), table


def _scenario_rows(
    *,
    case: dict[str, Any],
    paths: np.ndarray,
    probabilities: np.ndarray,
    scenario_ids: list[str],
    parent_ids: list[str],
    source_ids: list[str],
    granularity: str,
    set_size: int,
) -> pd.DataFrame:
    frame = case["hourly_frame"] if granularity == "hourly" else case["qh_frame"]
    model_id = HOURLY_MODEL_ID if granularity == "hourly" else QH_MODEL_ID
    records: list[dict[str, Any]] = []
    timestamps = frame["target_timestamp_utc"].tolist()
    leads = frame["lead_day"].astype(int).tolist()
    points = frame["point_forecast"].astype(float).tolist()
    for scenario_index, scenario_id in enumerate(scenario_ids):
        probability = float(probabilities[scenario_index])
        for period_index, timestamp in enumerate(timestamps):
            records.append(
                {
                    "model_id": model_id,
                    "granularity": granularity,
                    "forecast_origin_utc": case["origin"],
                    "target_timestamp_utc": timestamp,
                    "lead_day": int(leads[period_index]),
                    "scenario_set_size": int(set_size),
                    "scenario_id": scenario_id,
                    "parent_scenario_id": parent_ids[scenario_index],
                    "scenario_probability": probability,
                    "point_forecast": float(points[period_index]),
                    "scenario_price": float(paths[scenario_index, period_index]),
                    "source_residual_block_id": source_ids[scenario_index],
                }
            )
    return pd.DataFrame(records, columns=SCENARIO_COLUMNS)


def _metric_rows_for_paths(
    *,
    paths: np.ndarray,
    actual: np.ndarray,
    weights: np.ndarray,
    lead_values: np.ndarray,
    origin: pd.Timestamp,
    granularity: str,
    set_label: str,
    protected_weight: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lead_label, mask in [("ALL", np.ones(actual.size, dtype=bool))] + [
        (str(lead), lead_values == lead) for lead in range(5)
    ]:
        summary = weighted_interval_summary(paths[:, mask], actual[mask], weights)
        crps = crps_by_timestamp(paths[:, mask], actual[mask], weights)
        rows.append(
            {
                "forecast_origin_utc": origin,
                "granularity": granularity,
                "scenario_set": set_label,
                "lead_day": lead_label,
                **summary,
                "mean_crps": float(np.mean(crps)),
                "energy_score": float(energy_score(paths[:, mask], actual[mask], weights)) if lead_label == "ALL" else np.nan,
                "effective_scenario_size": float(1.0 / np.sum(np.asarray(weights) ** 2)),
                "protected_tail_weight": float(protected_weight),
                "timestamp_count": int(mask.sum()),
            }
        )
    return rows


def generate_evaluation_scenarios(
    *,
    hourly: pd.DataFrame,
    qh: pd.DataFrame,
    blocks: list[ResidualBlock],
    config: FinalisationConfig,
    level_scale: float,
    shape_scale: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    export_frames: list[pd.DataFrame] = []
    mapping_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    origins = sorted(qh.loc[qh["dataset_split"].eq("evaluation"), "forecast_origin_utc"].unique().tolist())
    for origin_value in origins:
        started = wall_time.perf_counter()
        case = _origin_case(hourly, qh, pd.Timestamp(origin_value))
        bank = eligible_blocks(blocks, forecast_origin_utc=case["origin"], allowed_splits={"train", "validation"})
        raw = generate_raw_coupled_paths(
            hourly_point=case["hourly_point"],
            qh_point=case["qh_point"],
            hourly_counts_by_lead=case["hourly_counts"],
            qh_counts_by_lead=case["qh_counts"],
            qh_to_hour=case["qh_to_hour"],
            residual_blocks=bank,
            n_raw=config.raw_scenarios,
            level_scale=level_scale,
            shape_scale=shape_scale,
            seed=stable_seed(config.random_seed, case["origin"], "evaluation"),
        )
        raw_ids = [f"RAW{index + 1:03d}" for index in range(config.raw_scenarios)]
        raw_weights = np.repeat(1.0 / config.raw_scenarios, config.raw_scenarios)
        reduce_start = wall_time.perf_counter()
        reduced30 = reduce_weighted_paths(
            raw.quarterhour,
            scenario_ids=raw_ids,
            weights=raw_weights,
            n_keep=config.final_scenarios,
            protected_count=int(round(config.final_scenarios * config.protected_tail_share)),
        )
        h30 = raw.hourly[reduced30.representative_indices]
        q30 = raw.quarterhour[reduced30.representative_indices]
        source30 = [raw.source_block_ids[index] for index in reduced30.representative_indices.tolist()]
        ids30 = [f"S30_{index + 1:02d}" for index in range(config.final_scenarios)]
        parent30 = list(reduced30.representative_ids)
        reduced10 = reduce_weighted_paths(
            q30,
            scenario_ids=ids30,
            weights=reduced30.probabilities,
            n_keep=config.nested_scenarios,
            protected_count=int(round(config.nested_scenarios * config.protected_tail_share)),
        )
        assert_nested_reduction(ids30, reduced10)
        h10 = h30[reduced10.representative_indices]
        q10 = q30[reduced10.representative_indices]
        source10 = [source30[index] for index in reduced10.representative_indices.tolist()]
        ids10 = [f"S10_{index + 1:02d}" for index in range(config.nested_scenarios)]
        parent10 = list(reduced10.representative_ids)
        reduction_seconds = wall_time.perf_counter() - reduce_start

        for granularity, paths30, paths10 in (("hourly", h30, h10), ("quarterhour", q30, q10)):
            export_frames.append(
                _scenario_rows(
                    case=case,
                    paths=paths30,
                    probabilities=reduced30.probabilities,
                    scenario_ids=ids30,
                    parent_ids=parent30,
                    source_ids=source30,
                    granularity=granularity,
                    set_size=config.final_scenarios,
                )
            )
            export_frames.append(
                _scenario_rows(
                    case=case,
                    paths=paths10,
                    probabilities=reduced10.probabilities,
                    scenario_ids=ids10,
                    parent_ids=parent10,
                    source_ids=source10,
                    granularity=granularity,
                    set_size=config.nested_scenarios,
                )
            )
        for parent_index, parent_id in enumerate(ids30):
            child_position = int(reduced10.source_to_representative_index[parent_index])
            mapping_rows.append(
                {
                    "forecast_origin_utc": case["origin"],
                    "parent_scenario_id_30": parent_id,
                    "child_scenario_id_10": ids10[child_position],
                    "parent_probability_30": float(reduced30.probabilities[parent_index]),
                    "child_probability_10": float(reduced10.probabilities[child_position]),
                }
            )
        protected30 = float(
            sum(
                reduced30.probabilities[index]
                for index, raw_id in enumerate(reduced30.representative_ids)
                if raw_id in set(reduced30.protected_representative_ids)
            )
        )
        protected10 = float(
            sum(
                reduced10.probabilities[index]
                for index, parent_id in enumerate(reduced10.representative_ids)
                if parent_id in set(reduced10.protected_representative_ids)
            )
        )
        for granularity, raw_paths, paths30, paths10, actual, lead_values in (
            ("hourly", raw.hourly, h30, h10, case["hourly_actual"], case["hourly_frame"]["lead_day"].to_numpy(dtype=int)),
            ("quarterhour", raw.quarterhour, q30, q10, case["qh_actual"], case["qh_frame"]["lead_day"].to_numpy(dtype=int)),
        ):
            metric_rows.extend(_metric_rows_for_paths(paths=raw_paths, actual=actual, weights=raw_weights, lead_values=lead_values, origin=case["origin"], granularity=granularity, set_label="raw_400", protected_weight=0.0))
            metric_rows.extend(_metric_rows_for_paths(paths=paths30, actual=actual, weights=reduced30.probabilities, lead_values=lead_values, origin=case["origin"], granularity=granularity, set_label="reduced_30", protected_weight=protected30))
            metric_rows.extend(_metric_rows_for_paths(paths=paths10, actual=actual, weights=reduced10.probabilities, lead_values=lead_values, origin=case["origin"], granularity=granularity, set_label="nested_10", protected_weight=protected10))
        timing_rows.append(
            {
                "forecast_origin_utc": case["origin"],
                "eligible_residual_blocks": int(len(bank)),
                "generation_and_total_seconds": float(wall_time.perf_counter() - started),
                "reduction_seconds": float(reduction_seconds),
            }
        )
    scenarios = pd.concat(export_frames, ignore_index=True) if export_frames else pd.DataFrame(columns=SCENARIO_COLUMNS)
    metrics = pd.DataFrame(metric_rows)
    mapping = pd.DataFrame(mapping_rows)
    timings = pd.DataFrame(timing_rows)
    return scenarios, mapping, metrics, timings


def _previous_week_naive(frame: pd.DataFrame, truth: pd.DataFrame, granularity: str) -> pd.Series:
    lookup = truth.copy()
    lookup["timestamp_local"] = pd.to_datetime(lookup["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    lookup["local_date"] = lookup["timestamp_local"].dt.date
    lookup["local_hour"] = lookup["timestamp_local"].dt.hour
    lookup["local_minute"] = lookup["timestamp_local"].dt.minute
    value_map = lookup.groupby(["local_date", "local_hour", "local_minute"])["actual_price"].mean().to_dict()
    target_local = pd.to_datetime(frame["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    return pd.Series(
        [
            value_map.get((timestamp.date() - timedelta(days=7), timestamp.hour, timestamp.minute), np.nan)
            for timestamp in target_local
        ],
        index=frame.index,
        dtype=float,
        name=f"previous_week_naive_{granularity}",
    )


def _forecast_metric_group(group: pd.DataFrame) -> dict[str, float]:
    actual = group["actual_price"].to_numpy(dtype=float)
    predicted = group["point_forecast"].to_numpy(dtype=float)
    error = predicted - actual
    absolute = np.abs(error)
    naive = group["naive_price"].to_numpy(dtype=float)
    naive_mae = float(np.nanmean(np.abs(naive - actual))) if np.isfinite(naive).any() else np.nan
    daily_stats: list[dict[str, float]] = []
    for _, day in group.groupby(["forecast_origin_utc", "lead_day"]):
        y = day["actual_price"].to_numpy(dtype=float)
        p = day["point_forecast"].to_numpy(dtype=float)
        k = min(6, len(day))
        top_actual = set(np.argsort(-y)[:k].tolist())
        top_predicted = set(np.argsort(-p)[:k].tolist())
        bottom_actual = set(np.argsort(y)[:k].tolist())
        bottom_predicted = set(np.argsort(p)[:k].tolist())
        spearman = stats.spearmanr(y, p, nan_policy="omit").statistic if len(np.unique(y)) > 1 and len(np.unique(p)) > 1 else np.nan
        daily_stats.append(
            {
                "spearman": float(spearman),
                "top6": float(len(top_actual & top_predicted) / k),
                "bottom6": float(len(bottom_actual & bottom_predicted) / k),
                "spread_error": float(abs((p.max() - p.min()) - (y.max() - y.min()))),
            }
        )
    tail_low, tail_high = np.quantile(actual, [0.10, 0.90])
    tail_mask = (actual <= tail_low) | (actual >= tail_high)
    day_frame = pd.DataFrame(daily_stats)
    return {
        "mae": float(np.mean(absolute)),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "p90_absolute_error": float(np.quantile(absolute, 0.90)),
        "p95_absolute_error": float(np.quantile(absolute, 0.95)),
        "rmae_vs_official_naive_previous_week": float(np.mean(absolute) / naive_mae) if np.isfinite(naive_mae) and naive_mae > 0 else np.nan,
        "daily_spearman": float(day_frame["spearman"].mean()),
        "top6_hit_rate": float(day_frame["top6"].mean()),
        "bottom6_hit_rate": float(day_frame["bottom6"].mean()),
        "tail_mae": float(np.mean(absolute[tail_mask])),
        "high_low_spread_error": float(day_frame["spread_error"].mean()),
        "origin_count": int(group["forecast_origin_utc"].nunique()),
        "timestamp_count": int(group.shape[0]),
        "coverage_pct": 100.0,
    }


def point_forecast_metrics(hourly: pd.DataFrame, qh: pd.DataFrame, flat: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hourly_eval = hourly[hourly["dataset_split"].eq("evaluation")].copy()
    qh_eval = qh[qh["dataset_split"].eq("evaluation")].copy()
    flat_eval = flat[flat["dataset_split"].eq("evaluation")].copy()
    hourly_eval["model_comparison_id"] = "hourly_lear_vs_aggregated_qh_truth"
    qh_eval["model_comparison_id"] = "qh_mean_shape_vs_native_qh_truth"
    flat_eval["model_comparison_id"] = "hourly_flat_repeat_vs_native_qh_truth"
    hourly_truth = hourly[["target_timestamp_utc", "actual_price"]].drop_duplicates()
    qh_truth = qh[["target_timestamp_utc", "actual_price"]].drop_duplicates()
    hourly_eval["naive_price"] = _previous_week_naive(hourly_eval, hourly_truth, "hourly")
    qh_eval["naive_price"] = _previous_week_naive(qh_eval, qh_truth, "quarterhour")
    flat_eval["naive_price"] = _previous_week_naive(flat_eval, qh_truth, "quarterhour")
    combined = pd.concat([hourly_eval, flat_eval, qh_eval], ignore_index=True, sort=False)
    combined["month"] = pd.to_datetime(combined["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE).dt.strftime("%Y-%m")
    rows: list[dict[str, Any]] = []
    grouping_specs = (
        ("overall", []),
        ("month", ["month"]),
        ("lead_day", ["lead_day"]),
    )
    for model_id, model_frame in combined.groupby("model_comparison_id"):
        for level, keys in grouping_specs:
            grouped = [((), model_frame)] if not keys else model_frame.groupby(keys[0] if len(keys) == 1 else keys)
            for key, group in grouped:
                key_values = key if isinstance(key, tuple) else (key,)
                row = {"model_comparison_id": model_id, "reporting_level": level, "month": "ALL", "lead_day": "ALL"}
                for column, value in zip(keys, key_values, strict=True):
                    row[column] = value
                row.update(_forecast_metric_group(group))
                rows.append(row)
    metrics = pd.DataFrame(rows)
    qh_metric = metrics[metrics["model_comparison_id"].eq("qh_mean_shape_vs_native_qh_truth")].copy()
    flat_metric = metrics[metrics["model_comparison_id"].eq("hourly_flat_repeat_vs_native_qh_truth")].copy()
    comparison = qh_metric.merge(flat_metric, on=["reporting_level", "month", "lead_day"], suffixes=("_shape", "_flat"))
    for metric in ("mae", "rmse", "tail_mae", "high_low_spread_error"):
        comparison[f"absolute_improvement_{metric}"] = comparison[f"{metric}_flat"] - comparison[f"{metric}_shape"]
        comparison[f"percent_improvement_{metric}"] = 100.0 * comparison[f"absolute_improvement_{metric}"] / comparison[f"{metric}_flat"]

    paired = qh_eval[["forecast_origin_utc", "target_timestamp_utc", "lead_day", "actual_price", "point_forecast"]].merge(
        flat_eval[["forecast_origin_utc", "target_timestamp_utc", "lead_day", "point_forecast"]],
        on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        suffixes=("_shape", "_flat"),
    )
    paired["loss_difference"] = np.abs(paired["point_forecast_shape"] - paired["actual_price"]) - np.abs(paired["point_forecast_flat"] - paired["actual_price"])
    daily = paired.groupby("forecast_origin_utc")["loss_difference"].mean().sort_index()
    values = daily.to_numpy(dtype=float)
    mean_diff = float(values.mean())
    centred = values - mean_diff
    lag = min(4, max(len(values) - 1, 0))
    variance = float(np.dot(centred, centred) / len(values))
    for index in range(1, lag + 1):
        covariance = float(np.dot(centred[index:], centred[:-index]) / len(values))
        variance += 2.0 * (1.0 - index / (lag + 1.0)) * covariance
    statistic = mean_diff / math.sqrt(max(variance / len(values), 1e-15))
    dm = pd.DataFrame(
        [
            {
                "comparison": "qh_mean_shape_vs_flat_repeat",
                "loss": "absolute_error",
                "aggregation": "mean_loss_per_forecast_origin",
                "hac_lag_origins": lag,
                "mean_loss_difference_shape_minus_flat": mean_diff,
                "dm_statistic": float(statistic),
                "two_sided_p_value": float(2.0 * stats.norm.sf(abs(statistic))),
                "origin_count": int(len(values)),
                "timestamp_count": int(len(paired)),
            }
        ]
    )
    return metrics, comparison, dm


def validate_contracts(
    *,
    grid: pd.DataFrame,
    support: pd.DataFrame,
    hourly: pd.DataFrame,
    qh: pd.DataFrame,
    scenarios: pd.DataFrame,
    mapping: pd.DataFrame,
    blocks: list[ResidualBlock],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str, hard: bool = True) -> None:
        rows.append({"check_name": name, "status": "pass" if passed else "fail", "hard_gate": bool(hard), "details": detail})

    selection_column = "selected_for_final_run" if "selected_for_final_run" in support.columns else "selected"
    selected = support[support[selection_column]]
    add("selected_origin_truth_support", bool((selected["missing_qh_targets"] == 0).all()), f"selected_origins={len(selected)}")
    point_dup = qh.duplicated(["forecast_origin_utc", "target_timestamp_utc"]).sum()
    add("point_key_uniqueness", point_dup == 0, f"duplicate_qh_keys={int(point_dup)}")
    scenario_key = ["granularity", "forecast_origin_utc", "target_timestamp_utc", "scenario_set_size", "scenario_id"]
    scenario_dup = scenarios.duplicated(scenario_key).sum()
    add("scenario_key_uniqueness", scenario_dup == 0, f"duplicate_scenario_keys={int(scenario_dup)}")
    probability = scenarios.drop_duplicates(["granularity", "forecast_origin_utc", "scenario_set_size", "scenario_id"]).groupby(
        ["granularity", "forecast_origin_utc", "scenario_set_size"]
    )["scenario_probability"].sum()
    add("probability_mass", bool(np.allclose(probability.to_numpy(dtype=float), 1.0, atol=1e-10)), f"max_abs_error={float(np.max(np.abs(probability - 1.0))):.3g}")
    point_mean = qh.groupby(["forecast_origin_utc", "hour_start_utc"])["point_forecast"].mean().reset_index()
    point_anchor = hourly.rename(columns={"target_timestamp_utc": "hour_start_utc", "point_forecast": "hourly_anchor"})
    point_parity = point_mean.merge(point_anchor[["forecast_origin_utc", "hour_start_utc", "hourly_anchor"]], on=["forecast_origin_utc", "hour_start_utc"])
    point_error = float((point_parity["point_forecast"] - point_parity["hourly_anchor"]).abs().max())
    add("qh_point_hourly_mean_parity", point_error <= 1e-10, f"max_abs_error={point_error:.3g}")
    qh_scen = scenarios[scenarios["granularity"].eq("quarterhour")].copy()
    qh_scen["hour_start_utc"] = pd.to_datetime(qh_scen["target_timestamp_utc"], utc=True).dt.floor("h")
    qh_mean = qh_scen.groupby(["forecast_origin_utc", "hour_start_utc", "scenario_set_size", "scenario_id"])["scenario_price"].mean().reset_index()
    h_scen = scenarios[scenarios["granularity"].eq("hourly")].rename(columns={"target_timestamp_utc": "hour_start_utc", "scenario_price": "hourly_scenario_price"})
    parity = qh_mean.merge(h_scen[["forecast_origin_utc", "hour_start_utc", "scenario_set_size", "scenario_id", "hourly_scenario_price"]], on=["forecast_origin_utc", "hour_start_utc", "scenario_set_size", "scenario_id"])
    scenario_error = float((parity["scenario_price"] - parity["hourly_scenario_price"]).abs().max())
    add("qh_scenario_hourly_mean_parity", scenario_error <= 1e-10, f"max_abs_error={scenario_error:.3g}")
    meta = scenarios.drop_duplicates(["granularity", "forecast_origin_utc", "scenario_set_size", "scenario_id"])
    h_meta = meta[meta["granularity"].eq("hourly")].drop(columns=["granularity", "model_id"])
    q_meta = meta[meta["granularity"].eq("quarterhour")].drop(columns=["granularity", "model_id"])
    paired_meta = h_meta.merge(q_meta, on=["forecast_origin_utc", "scenario_set_size", "scenario_id"], suffixes=("_h", "_q"))
    identity_ok = bool(
        np.allclose(paired_meta["scenario_probability_h"], paired_meta["scenario_probability_q"], atol=1e-12)
        and (paired_meta["source_residual_block_id_h"] == paired_meta["source_residual_block_id_q"]).all()
    )
    add("hourly_qh_scenario_identity", identity_ok, f"paired_scenarios={len(paired_meta)}")
    block_available = {block.block_id: block.available_at_utc for block in blocks}
    causal = meta["source_residual_block_id"].map(block_available) < meta["forecast_origin_utc"]
    add("causal_source_residuals", bool(causal.all()), f"violations={int((~causal).sum())}")
    nested_ok = bool(mapping.groupby("forecast_origin_utc").size().eq(30).all() and mapping["child_scenario_id_10"].str.startswith("S10_").all())
    add("nested_30_to_10_mapping", nested_ok, f"mapping_rows={len(mapping)}")
    forbidden = [column for column in scenarios.columns if any(token in column.lower() for token in ("actual", "error", "y_true"))]
    add("optimisation_exports_exclude_actuals", not forbidden, f"forbidden_columns={forbidden}")
    supported_path_lengths = sorted(set(pd.to_numeric(support["expected_qh_targets"], errors="coerce").dropna().astype(int).tolist()))
    selected_dst_origins = int(((support[selection_column]) & support["expected_qh_targets"].eq(476)).sum())
    add(
        "dst_native_qh_counts",
        476 in supported_path_lengths and 480 in supported_path_lengths,
        f"expected_five_day_path_lengths={supported_path_lengths}; selected_spring_dst_origins={selected_dst_origins}; incomplete DST truth is excluded, never interpolated",
    )
    checks = pd.DataFrame(rows)
    failed_hard = checks[(checks["status"] == "fail") & checks["hard_gate"]]
    if not failed_hard.empty:
        raise AssertionError(f"hard contract checks failed: {failed_hard[['check_name', 'details']].to_dict(orient='records')}")
    return checks


def run_finalisation(
    *,
    repo_root: Path,
    config_path: Path,
    run_dir: Path,
    legacy_cleaned_root: Path,
    historical_qh_path: Path,
    refreshed_input_root: Path,
    refreshed_qh_path: Path | None,
    refreshed_res_cleaned_root: Path,
    horizon_policy_csv: Path,
    anchor_seed_predictions: Path | None,
    resume_run: bool = False,
) -> dict[str, Any]:
    started = wall_time.perf_counter()
    config = load_config(config_path)
    run_dir.mkdir(parents=True, exist_ok=bool(resume_run))
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    resolved = {
        "timeline": {
            "train_start_local_date": config.train_start_local_date.isoformat(),
            "validation_start_local_date": config.validation_start_local_date.isoformat(),
            "evaluation_start_local_date": config.evaluation_start_local_date.isoformat(),
            "requested_end_local_date": config.requested_end_local_date.isoformat(),
            "classification": "extended_out_of_sample_evaluation",
        },
        "models": {"hourly": HOURLY_MODEL_ID, "quarterhour": QH_MODEL_ID},
        "scenarios": {
            "raw_count": config.raw_scenarios,
            "final_count": config.final_scenarios,
            "nested_count": config.nested_scenarios,
            "level_scales": list(config.level_scales),
            "shape_scales": list(config.shape_scales),
            "protected_tail_share": config.protected_tail_share,
            "probability_policy": "empirical_cluster_mass",
            "raw_storage_policy": "in_memory_only",
        },
        "output_policy": "full",
        "run_class": "full",
        "lineage_role": "thesis-candidate generated evaluation",
    }
    (run_dir / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")

    effective_refreshed_qh = refreshed_qh_path or (refreshed_input_root / "qh_prices_2026.csv")
    input_paths = [historical_qh_path, effective_refreshed_qh, horizon_policy_csv]
    for candidate in (
        legacy_cleaned_root / "Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv",
        legacy_cleaned_root / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
        legacy_cleaned_root / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
        legacy_cleaned_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv",
        refreshed_input_root / "da_load_forecast_2026.csv",
        refreshed_input_root / "weekahead_load_2026.csv",
        refreshed_res_cleaned_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv",
    ):
        input_paths.append(candidate)
    if anchor_seed_predictions is not None:
        input_paths.append(anchor_seed_predictions)
    missing_inputs = [str(path) for path in input_paths if not path.exists()]
    if missing_inputs:
        raise FileNotFoundError(f"missing finalisation inputs: {missing_inputs}")
    manifest = [
        {"logical_name": path.name, "bytes": int(path.stat().st_size), "sha256": _sha256(path)}
        for path in input_paths
    ]
    _write_json(run_dir / "input_manifest.json", {"inputs": manifest, "paths_redacted": True})
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=False).stdout.strip()
    _write_json(run_dir / "code_version.json", {"git_head": git_head, "python": sys.version, "dirty_worktree_not_embedded": True})

    qh_actual = load_observed_qh(historical_qh_path, effective_refreshed_qh)
    grid, support, last_complete = build_supported_grid(qh_actual, config)
    support.to_csv(run_dir / "support_pre_anchor.csv", index=False)
    target_path = run_dir / "inputs" / "targets_by_origin.csv"
    write_anchor_targets(grid, target_path)
    short_staging_root = repo_root / "tmp" / f"strict_lear_stage_{run_dir.name[:20]}"
    short_staging_root.mkdir(parents=True, exist_ok=True)
    staged_root, policy_copy, bridge_path = prepare_anchor_inputs(
        run_dir=run_dir,
        staging_root=short_staging_root,
        legacy_cleaned_root=legacy_cleaned_root,
        refreshed_root=refreshed_input_root,
        refreshed_res_cleaned_root=refreshed_res_cleaned_root,
        qh=qh_actual,
        horizon_policy_csv=horizon_policy_csv,
    )
    anchor_path = run_hourly_anchor(
        repo_root=repo_root,
        run_dir=run_dir,
        target_path=target_path,
        bridge_path=bridge_path,
        staged_cleaned_root=staged_root,
        horizon_policy_csv=policy_copy,
        anchor_seed_predictions=anchor_seed_predictions,
        window_days=config.window_days,
    )
    hourly, qh_point, flat_point = build_point_forecasts(qh_actual, grid, anchor_path)
    final_origins = set(qh_point["forecast_origin_utc"].unique().tolist())
    support["selected_for_final_run"] = support["selected"] & support["forecast_origin_utc"].isin(final_origins)
    support.loc[support["selected"] & ~support["selected_for_final_run"], "exclusion_reason"] = "incomplete_strict_lear_anchor"
    support.to_csv(run_dir / "support_summary.csv", index=False)
    grid = grid[grid["forecast_origin_utc"].isin(final_origins)].copy()

    blocks = build_residual_blocks(hourly, qh_point)
    if not blocks:
        raise ValueError("no complete causal train/validation residual blocks were constructed")
    residual_manifest = pd.DataFrame(
        [
            {
                "source_residual_block_id": block.block_id,
                "source_origin_utc": block.source_origin_utc,
                "available_at_utc": block.available_at_utc,
                "dataset_split": block.dataset_split,
                "hourly_periods": sum(len(values) for values in block.hourly_by_lead),
                "quarterhour_periods": sum(len(values) for values in block.shape_by_lead),
            }
            for block in blocks
        ]
    )
    residual_manifest.to_csv(run_dir / "residual_block_manifest.csv", index=False)
    level_scale, shape_scale, calibration = calibrate_scenario_scales(hourly=hourly, qh=qh_point, blocks=blocks, config=config)
    calibration.to_csv(run_dir / "scenario_calibration_validation.csv", index=False)
    scenario_started = wall_time.perf_counter()
    scenarios, reduction_mapping, scenario_origin_metrics, timings = generate_evaluation_scenarios(
        hourly=hourly,
        qh=qh_point,
        blocks=blocks,
        config=config,
        level_scale=level_scale,
        shape_scale=shape_scale,
    )
    scenario_seconds = wall_time.perf_counter() - scenario_started
    if scenarios.empty:
        raise ValueError("no evaluation scenarios were generated")

    checks = validate_contracts(
        grid=grid,
        support=support,
        hourly=hourly,
        qh=qh_point,
        scenarios=scenarios,
        mapping=reduction_mapping,
        blocks=blocks,
    )
    checks.to_csv(run_dir / "contract_checks.csv", index=False)
    probability_checks = (
        scenarios.drop_duplicates(["granularity", "forecast_origin_utc", "scenario_set_size", "scenario_id"])
        .groupby(["granularity", "forecast_origin_utc", "scenario_set_size"], as_index=False)["scenario_probability"]
        .sum()
    )
    probability_checks["absolute_error_from_one"] = (probability_checks["scenario_probability"] - 1.0).abs()
    probability_checks.to_csv(run_dir / "probability_checks.csv", index=False)

    optimisation = run_dir / "optimisation_inputs"
    hourly_export = hourly[hourly["dataset_split"].eq("evaluation")][
        ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "point_forecast"]
    ].copy()
    hourly_export.insert(0, "granularity", "hourly")
    hourly_export.insert(0, "model_id", HOURLY_MODEL_ID)
    qh_export = qh_point[qh_point["dataset_split"].eq("evaluation")][
        ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "point_forecast"]
    ].copy()
    qh_export.insert(0, "granularity", "quarterhour")
    qh_export.insert(0, "model_id", QH_MODEL_ID)
    _write_parquet(hourly_export, optimisation / "hourly_point_forecasts.parquet")
    _write_parquet(qh_export, optimisation / "quarterhour_point_forecasts.parquet")
    for granularity, label in (("hourly", "hourly"), ("quarterhour", "quarterhour")):
        for set_size in (config.final_scenarios, config.nested_scenarios):
            subset = scenarios[(scenarios["granularity"].eq(granularity)) & scenarios["scenario_set_size"].eq(set_size)]
            _write_parquet(subset, optimisation / f"{label}_scenarios_{set_size}.parquet")
    reduction_mapping.to_csv(optimisation / "scenario_reduction_30_to_10.csv", index=False)

    actual_evaluation = qh_point[qh_point["dataset_split"].eq("evaluation")][
        ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "actual_price"]
    ].copy()
    actual_evaluation.insert(0, "granularity", "quarterhour")
    hourly_actual = hourly[hourly["dataset_split"].eq("evaluation")][
        ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "actual_price"]
    ].copy()
    hourly_actual.insert(0, "granularity", "hourly")
    _write_parquet(pd.concat([hourly_actual, actual_evaluation], ignore_index=True), run_dir / "evaluation_actuals.parquet")

    point_metrics, point_comparison, dm = point_forecast_metrics(hourly, qh_point, flat_point)
    point_metrics.to_csv(run_dir / "point_forecast_metrics.csv", index=False)
    point_comparison.to_csv(run_dir / "qh_incremental_improvement.csv", index=False)
    dm.to_csv(run_dir / "diebold_mariano_test.csv", index=False)
    scenario_origin_metrics.to_csv(run_dir / "scenario_metrics_by_origin.csv", index=False)
    scenario_metrics = (
        scenario_origin_metrics.groupby(["granularity", "scenario_set", "lead_day"], as_index=False)
        .agg(
            coverage_p10_p90=("coverage_p10_p90", "mean"),
            coverage_p05_p95=("coverage_p05_p95", "mean"),
            average_width_p10_p90=("average_width_p10_p90", "mean"),
            average_width_p05_p95=("average_width_p05_p95", "mean"),
            p50_bias=("p50_bias", "mean"),
            high_tail_miss_rate=("high_tail_miss_rate", "mean"),
            low_tail_miss_rate=("low_tail_miss_rate", "mean"),
            min_max_containment=("min_max_containment", "mean"),
            mean_crps=("mean_crps", "mean"),
            energy_score=("energy_score", "mean"),
            effective_scenario_size=("effective_scenario_size", "mean"),
            protected_tail_weight=("protected_tail_weight", "mean"),
            origin_count=("forecast_origin_utc", "nunique"),
        )
    )
    scenario_metrics.to_csv(run_dir / "scenario_metrics_summary.csv", index=False)
    base = scenario_metrics[scenario_metrics["scenario_set"].eq("raw_400")].copy()
    reduction_effects = scenario_metrics.merge(
        base,
        on=["granularity", "lead_day"],
        suffixes=("", "_raw"),
    )
    reduction_effects = reduction_effects[reduction_effects["scenario_set"].isin(["reduced_30", "nested_10"])]
    for metric in ("coverage_p05_p95", "average_width_p05_p95", "mean_crps", "energy_score"):
        reduction_effects[f"difference_vs_raw_{metric}"] = reduction_effects[metric] - reduction_effects[f"{metric}_raw"]
    reduction_effects.to_csv(run_dir / "scenario_reduction_effects.csv", index=False)
    timings.to_csv(run_dir / "generation_reduction_timings.csv", index=False)

    overall_reduced = scenario_metrics[(scenario_metrics["lead_day"].astype(str).eq("ALL")) & scenario_metrics["scenario_set"].isin(["reduced_30", "nested_10"])]
    undercoverage = overall_reduced[overall_reduced["coverage_p05_p95"] < 0.85]
    warning_lines = [
        "# Warnings and limitations",
        "",
        "- March-July is classified as extended out-of-sample evaluation because March-April had already been inspected.",
        "- Origins whose D..D+4 truth contains any unobserved QH price are excluded; no evaluation prices are interpolated.",
        "- The inherited Strict LEAR feature definition requires 24-hour lag vectors. The 23-hour spring-DST target is forecast natively, but later origins are excluded while that day is required as a D-1, D-2, D-3, or D-7 lag; no synthetic lag hour is inserted.",
        "- Scenario scales are selected on validation only; evaluation residuals are never scenario sources.",
        "- Perfect foresight is an optimisation upper-bound benchmark and is deferred to the later hydrogen/steel runs.",
    ]
    if not undercoverage.empty:
        warning_lines.append("- WARNING: p05-p95 scenario coverage is below 85% for at least one final granularity/set; calibrated-risk-coverage claims are not permitted.")
    else:
        warning_lines.append("- Validation-selected scenario intervals meet the prespecified evaluation undercoverage warning threshold overall.")
    (run_dir / "warnings_and_limitations.md").write_text("\n".join(warning_lines) + "\n", encoding="utf-8")

    thesis_body = point_metrics[(point_metrics["reporting_level"].eq("overall"))].copy()
    thesis_body.to_csv(run_dir / "thesis_body_point_table.csv", index=False)
    scenario_metrics[scenario_metrics["lead_day"].astype(str).eq("ALL")].to_csv(run_dir / "thesis_body_scenario_table.csv", index=False)
    point_metrics.to_csv(run_dir / "thesis_appendix_point_table.csv", index=False)
    scenario_metrics.to_csv(run_dir / "thesis_appendix_scenario_table.csv", index=False)

    file_inventory = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            file_inventory.append({"relative_path": str(path.relative_to(run_dir)), "bytes": int(path.stat().st_size)})
    pd.DataFrame(file_inventory).to_csv(run_dir / "artifact_inventory.csv", index=False)
    selected_eval_support = support[
        support["dataset_split"].eq("evaluation") & support["selected_for_final_run"]
    ]
    selected_eval_delivery_days = pd.to_datetime(
        selected_eval_support["delivery_start_local_date"]
    ).dt.date
    excluded_evaluation = support[
        support["dataset_split"].eq("evaluation") & ~support["selected_for_final_run"]
    ]
    excluded_counts = {
        str(reason): int(count)
        for reason, count in excluded_evaluation["exclusion_reason"].value_counts().items()
    }
    summary = {
        "completed_successfully": True,
        "run_id": run_dir.name,
        "last_complete_observed_local_day": last_complete.isoformat(),
        "first_evaluation_local_day": config.evaluation_start_local_date.isoformat(),
        "first_selected_evaluation_delivery_day": min(selected_eval_delivery_days).isoformat(),
        "last_selected_evaluation_delivery_day": max(selected_eval_delivery_days).isoformat(),
        "excluded_evaluation_origins_by_reason": excluded_counts,
        "selected_evaluation_origins": int(qh_point.loc[qh_point["dataset_split"].eq("evaluation"), "forecast_origin_utc"].nunique()),
        "selected_train_origins": int(qh_point.loc[qh_point["dataset_split"].eq("train"), "forecast_origin_utc"].nunique()),
        "selected_validation_origins": int(qh_point.loc[qh_point["dataset_split"].eq("validation"), "forecast_origin_utc"].nunique()),
        "selected_level_scale": level_scale,
        "selected_shape_scale": shape_scale,
        "scenario_undercoverage_warning": bool(not undercoverage.empty),
        "contract_checks_passed": bool(checks["status"].eq("pass").all()),
        "scenario_generation_seconds": float(scenario_seconds),
        "runtime_seconds_total": float(wall_time.perf_counter() - started),
        "output_file_count": int(len(file_inventory) + 3),
        "output_bytes_before_summary": int(sum(item["bytes"] for item in file_inventory)),
    }
    _write_json(run_dir / "run_summary.json", summary)
    _write_json(
        run_dir / "registry_entry.json",
        {
            "run_id": run_dir.name,
            "status": "complete",
            "models": [HOURLY_MODEL_ID, QH_MODEL_ID],
            "horizon": "D_Dplus4",
            "scenario_sets": [30, 10],
            "lineage_role": "thesis-candidate generated evaluation",
            "actuals_separated_from_optimisation_exports": True,
        },
    )
    return summary
