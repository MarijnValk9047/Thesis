"""Contracts for the D-only four-regime hourly/quarter-hour study.

This module deliberately separates three evidence layers:

* a common-support audit of frozen hourly point models with one scenario method;
* a mean-preserving, explicitly counterfactual quarter-hour overlay;
* deterministic week selection and a fail-closed steel experiment manifest.

It contains no optimiser calls.  Economic steel execution is only allowed after
the shared-quarter-hour physical prerequisite has passed in a governed run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

from hourly_da.core.coupled_multiday_scenarios import (
    ResidualBlock,
    crps_by_timestamp,
    eligible_blocks,
    generate_raw_coupled_paths,
    stable_seed,
    weighted_interval_summary,
    weighted_quantile,
)
from hourly_da.core.multiday_scenario_reduction import (
    assert_nested_reduction,
    reduce_weighted_paths,
)


LOCAL_TIMEZONE = "Europe/Amsterdam"
PUBLIC_MODEL_IDS = {
    "strict": "lear_lago_direct_dplus4_strict_no_future_1092",
    "lear_fs3": "lear_fs3_combo_pruned_candidate",
    "xgboost_fs3": "xgboost_fs3_combo_pruned_candidate",
}
STRICT_MODEL_ID = PUBLIC_MODEL_IDS["strict"]
POINT_COLUMNS = [
    "model_id",
    "forecast_origin_utc",
    "target_timestamp_utc",
    "delivery_date_local",
    "lead_day",
    "dataset_split",
    "point_forecast",
    "actual_price",
    "support_status",
]
SCENARIO_COLUMNS = [
    "model_id",
    "forecast_origin_utc",
    "target_timestamp_utc",
    "delivery_date_local",
    "lead_day",
    "scenario_set_size",
    "scenario_id",
    "parent_scenario_id",
    "scenario_probability",
    "point_forecast",
    "scenario_price",
    "source_residual_block_id",
    "support_status",
]
OVERLAY_COLUMNS = [
    "week_id",
    "path_kind",
    "scenario_id",
    "scenario_probability",
    "scenario_set_size",
    "target_timestamp_utc",
    "hour_start_utc",
    "quarter_index",
    "hourly_anchor_price",
    "quarterhour_delta",
    "quarterhour_price",
    "source_profile_id",
    "counterfactual",
]


class StudyContractError(ValueError):
    """Raised when a hard information, support, or artifact contract fails."""


@dataclass(frozen=True)
class ScenarioPolicy:
    raw_count: int = 400
    parent_count: int = 30
    final_count: int = 10
    protected_tail_share: float = 0.20
    level_scales: tuple[float, ...] = (1.00, 1.15, 1.30, 1.45, 1.60)
    random_seed: int = 20260731


def load_study_config(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    required = {"study_id", "forecast_family_audit", "week_selection", "steel_experiment"}
    missing = sorted(required.difference(payload))
    if missing:
        raise StudyContractError(f"study config misses required sections: {missing}")
    return payload


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def normalise_frozen_point_source(
    path: str | Path,
    *,
    model_id: str,
    source_model: str | None = None,
) -> pd.DataFrame:
    """Map the historical Strict/FS3 exports to one frozen point contract."""

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    frame = _read_table(source).copy()
    if source_model is not None and "model" in frame.columns:
        frame = frame[frame["model"].astype(str).eq(str(source_model))].copy()
    rename = {
        "delivery_start_utc": "target_timestamp_utc",
        "point_forecast_eur_per_mwh": "point_forecast",
        "actual_price_eur_per_mwh": "actual_price",
        "y_pred": "point_forecast",
        "y_true": "actual_price",
    }
    frame = frame.rename(columns={key: value for key, value in rename.items() if key in frame.columns})
    required = {
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "dataset_split",
        "point_forecast",
        "actual_price",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise StudyContractError(f"{source.name} misses point columns: {missing}")
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["point_forecast"] = pd.to_numeric(frame["point_forecast"], errors="coerce")
    frame["actual_price"] = pd.to_numeric(frame["actual_price"], errors="coerce")
    frame["dataset_split"] = frame["dataset_split"].astype(str).str.lower()
    frame = frame[frame["lead_day"].eq(0)].copy()
    local = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TIMEZONE)
    frame["delivery_date_local"] = local.dt.date.astype(str)
    frame["model_id"] = str(model_id)
    frame["support_status"] = "candidate"
    frame = frame[POINT_COLUMNS].dropna(
        subset=["forecast_origin_utc", "target_timestamp_utc", "point_forecast", "actual_price"]
    )
    frame = frame.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
    duplicate_count = int(
        frame.duplicated(["model_id", "forecast_origin_utc", "target_timestamp_utc"]).sum()
    )
    if duplicate_count:
        raise StudyContractError(f"{model_id} has {duplicate_count} duplicate point keys")
    return frame.reset_index(drop=True)


def information_timing_checks(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the fixed D-1 08:00 Europe/Amsterdam information policy."""

    origin = pd.to_datetime(frame["forecast_origin_utc"], utc=True)
    target_local = pd.to_datetime(frame["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    expected = pd.Series(
        [
            pd.Timestamp(timestamp.date() - timedelta(days=1), tz=LOCAL_TIMEZONE)
            .replace(hour=8)
            .tz_convert("UTC")
            for timestamp in target_local
        ],
        index=frame.index,
    )
    difference_minutes = (origin - expected).dt.total_seconds().abs() / 60.0
    rows = [
        {
            "check_name": "forecast_origin_is_d_minus_1_08_local",
            "status": "pass" if bool(difference_minutes.le(1e-9).all()) else "fail",
            "observed": float(difference_minutes.max()) if not difference_minutes.empty else np.nan,
            "expected": 0.0,
        },
        {
            "check_name": "origin_precedes_every_target",
            "status": "pass" if bool(origin.lt(frame["target_timestamp_utc"]).all()) else "fail",
            "observed": int(origin.ge(frame["target_timestamp_utc"]).sum()),
            "expected": 0,
        },
        {
            "check_name": "d_only_rows",
            "status": "pass" if bool(pd.to_numeric(frame["lead_day"]).eq(0).all()) else "fail",
            "observed": sorted(pd.to_numeric(frame["lead_day"]).dropna().astype(int).unique().tolist()),
            "expected": [0],
        },
    ]
    return pd.DataFrame(rows)


def align_common_non_dst_support(
    frames: dict[str, pd.DataFrame],
    *,
    splits: Iterable[str] = ("validation", "test"),
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Intersect exact complete 24-hour local days without interpolating DST."""

    if set(frames) != set(PUBLIC_MODEL_IDS.values()):
        raise StudyContractError("the common-support audit requires exactly the three frozen public model IDs")
    selected_days: dict[str, list[str]] = {}
    support_rows: list[dict[str, Any]] = []
    for split in splits:
        model_maps: dict[str, dict[str, tuple[str, ...]]] = {}
        for model_id, frame in frames.items():
            part = frame[frame["dataset_split"].eq(str(split))].copy()
            day_map: dict[str, tuple[str, ...]] = {}
            for day, group in part.groupby("delivery_date_local"):
                timestamps = tuple(
                    sorted(pd.to_datetime(group["target_timestamp_utc"], utc=True).astype(str).unique().tolist())
                )
                if len(timestamps) == 24:
                    day_map[str(day)] = timestamps
            model_maps[model_id] = day_map
        common_days = set.intersection(*(set(values) for values in model_maps.values()))
        exact_days = [
            day
            for day in sorted(common_days)
            if len({model_maps[model_id][day] for model_id in sorted(model_maps)}) == 1
        ]
        selected_days[str(split)] = exact_days
        support_rows.append(
            {
                "dataset_split": split,
                "strict_complete_24h_days": len(model_maps[STRICT_MODEL_ID]),
                "lear_fs3_complete_24h_days": len(model_maps[PUBLIC_MODEL_IDS["lear_fs3"]]),
                "xgboost_fs3_complete_24h_days": len(model_maps[PUBLIC_MODEL_IDS["xgboost_fs3"]]),
                "exact_common_complete_24h_days": len(exact_days),
                "support_start": exact_days[0] if exact_days else None,
                "support_end": exact_days[-1] if exact_days else None,
                "dst_policy": "23h_and_25h_days_excluded_not_interpolated",
            }
        )
    aligned: dict[str, pd.DataFrame] = {}
    for model_id, frame in frames.items():
        keep = pd.Series(False, index=frame.index)
        for split, days in selected_days.items():
            keep |= frame["dataset_split"].eq(split) & frame["delivery_date_local"].isin(days)
        result = frame.loc[keep].copy()
        result["support_status"] = "exact_common_complete_24h_non_dst"
        aligned[model_id] = result.reset_index(drop=True)
    if not selected_days.get("validation") or not selected_days.get("test"):
        raise StudyContractError("no exact common validation/test support for the three-model audit")
    return aligned, pd.DataFrame(support_rows)


def build_hourly_residual_blocks(frame: pd.DataFrame) -> list[ResidualBlock]:
    """Build causal complete-day residual blocks for the shared Strict algorithm."""

    blocks: list[ResidualBlock] = []
    validation = frame[frame["dataset_split"].eq("validation")].copy()
    for origin, group in validation.groupby("forecast_origin_utc"):
        ordered = group.sort_values("target_timestamp_utc")
        if len(ordered) != 24:
            continue
        residual = (ordered["actual_price"] - ordered["point_forecast"]).to_numpy(dtype=float)
        blocks.append(
            ResidualBlock(
                block_id=f"{frame['model_id'].iloc[0]}__{pd.Timestamp(origin).strftime('%Y%m%dT%H%M%SZ')}",
                source_origin_utc=pd.Timestamp(origin),
                available_at_utc=pd.Timestamp(ordered["target_timestamp_utc"].max()) + pd.Timedelta(hours=1),
                dataset_split="validation",
                hourly_by_lead=(residual,),
                shape_by_lead=(np.zeros(96, dtype=float),),
            )
        )
    return blocks


def _hourly_origin_case(frame: pd.DataFrame, origin: pd.Timestamp) -> dict[str, Any]:
    group = frame[frame["forecast_origin_utc"].eq(origin)].sort_values("target_timestamp_utc").reset_index(drop=True)
    if len(group) != 24:
        raise StudyContractError(f"origin {origin} is not a complete 24-hour D-only path")
    point = group["point_forecast"].to_numpy(dtype=float)
    return {
        "frame": group,
        "point": point,
        "actual": group["actual_price"].to_numpy(dtype=float),
        "qh_point": np.repeat(point, 4),
        "qh_to_hour": np.repeat(np.arange(24), 4),
    }


def _sample_hourly_unit_residuals(
    blocks: list[ResidualBlock],
    *,
    n_raw: int,
    seed: int,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Exact D-only hourly specialisation of ``generate_raw_coupled_paths``.

    Every audit block is a native 24-hour residual path and has zero QH-shape
    residuals.  Repeating all 24 columns four times leaves standardised path
    distances, tail ranks, medoids, and probability transfer unchanged.  The
    audit can therefore sample and reduce the hourly residual matrix directly.
    """

    if not blocks:
        raise StudyContractError("no causally eligible residual blocks")
    rng = np.random.default_rng(int(seed))
    sampled = rng.integers(0, len(blocks), size=int(n_raw))
    values: list[np.ndarray] = []
    source_ids: list[str] = []
    for block_index in sampled.tolist():
        block = blocks[int(block_index)]
        residual = np.asarray(block.hourly_by_lead[0], dtype=float)
        if residual.shape != (24,):
            raise StudyContractError("D-only hourly residual specialisation requires native 24-hour blocks")
        values.append(residual)
        source_ids.append(block.block_id)
    return np.stack(values), tuple(source_ids)


def calibrate_hourly_level_scale(
    frame: pd.DataFrame,
    blocks: list[ResidualBlock],
    policy: ScenarioPolicy,
) -> tuple[float, pd.DataFrame]:
    """Select dispersion prequentially on validation data only."""

    summaries_by_scale: dict[float, list[dict[str, float]]] = {
        float(scale): [] for scale in policy.level_scales
    }
    origins_by_scale = {float(scale): 0 for scale in policy.level_scales}
    origins = sorted(frame.loc[frame["dataset_split"].eq("validation"), "forecast_origin_utc"].unique())
    # The sampled residual-block identities do not depend on the scale.  Draw
    # them once per origin, then apply each candidate scale to the same draw.
    # This is numerically equivalent to repeated generator calls because the
    # stable seed deliberately excludes the scale.
    for origin_value in origins:
        origin = pd.Timestamp(origin_value)
        bank = eligible_blocks(blocks, forecast_origin_utc=origin, allowed_splits={"validation"})
        if not bank:
            continue
        case = _hourly_origin_case(frame, origin)
        sampled_error, _ = _sample_hourly_unit_residuals(
            bank,
            n_raw=policy.raw_count,
            seed=stable_seed(policy.random_seed, frame["model_id"].iloc[0], origin, "calibration"),
        )
        weights = np.repeat(1.0 / policy.raw_count, policy.raw_count)
        for scale in policy.level_scales:
            scaled_paths = case["point"][None, :] + float(scale) * sampled_error
            summaries_by_scale[float(scale)].append(
                weighted_interval_summary(scaled_paths, case["actual"], weights)
            )
            origins_by_scale[float(scale)] += 1

    rows: list[dict[str, Any]] = []
    for scale in policy.level_scales:
        summaries = summaries_by_scale[float(scale)]
        if not summaries:
            continue
        metrics = pd.DataFrame(summaries)
        coverage = float(metrics["coverage_p05_p95"].mean())
        coverage_penalty = max(0.85 - coverage, 0.0) + max(coverage - 0.90, 0.0)
        imbalance = float(abs(metrics["high_tail_miss_rate"].mean() - metrics["low_tail_miss_rate"].mean()))
        width = float(metrics["average_width_p05_p95"].mean())
        rows.append(
            {
                "level_scale": float(scale),
                "coverage_90": coverage,
                "width_90": width,
                "high_tail_miss_rate": float(metrics["high_tail_miss_rate"].mean()),
                "low_tail_miss_rate": float(metrics["low_tail_miss_rate"].mean()),
                "selection_score": 1000.0 * coverage_penalty + 100.0 * imbalance + 0.001 * width,
                "validation_origin_count": origins_by_scale[float(scale)],
                "calibration_support": "validation_only_prequential_causal",
                "draw_reuse_policy": "same_seed_same_residual_draw_reused_across_scale_candidates",
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        raise StudyContractError("no level scale could be calibrated from past validation residuals")
    table = table.sort_values(["selection_score", "width_90", "level_scale"]).reset_index(drop=True)
    table["selected"] = False
    table.loc[0, "selected"] = True
    return float(table.loc[0, "level_scale"]), table


def generate_hourly_nested_scenarios(
    frame: pd.DataFrame,
    blocks: list[ResidualBlock],
    policy: ScenarioPolicy,
    *,
    level_scale: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate raw-to-S30-to-nested-S10 paths under one shared draw."""

    model_id = str(frame["model_id"].iloc[0])
    scenario_frames: list[pd.DataFrame] = []
    parent_frames: list[pd.DataFrame] = []
    mapping_rows: list[dict[str, Any]] = []
    origins = sorted(frame.loc[frame["dataset_split"].eq("test"), "forecast_origin_utc"].unique())
    for origin_value in origins:
        origin = pd.Timestamp(origin_value)
        case = _hourly_origin_case(frame, origin)
        bank = eligible_blocks(blocks, forecast_origin_utc=origin, allowed_splits={"validation"})
        if not bank:
            raise StudyContractError(f"{model_id} has no causal validation residual pool at {origin}")
        sampled_error, source_block_ids = _sample_hourly_unit_residuals(
            bank,
            n_raw=policy.raw_count,
            seed=stable_seed(policy.random_seed, model_id, origin, "evaluation"),
        )
        raw_hourly = case["point"][None, :] + float(level_scale) * sampled_error
        raw_ids = [f"RAW_{index + 1:03d}" for index in range(policy.raw_count)]
        raw_probability = np.repeat(1.0 / policy.raw_count, policy.raw_count)
        parent = reduce_weighted_paths(
            raw_hourly,
            scenario_ids=raw_ids,
            weights=raw_probability,
            n_keep=policy.parent_count,
            protected_count=int(round(policy.parent_count * policy.protected_tail_share)),
        )
        parent_ids = [f"S30_{index + 1:02d}" for index in range(policy.parent_count)]
        child = reduce_weighted_paths(
            raw_hourly[parent.representative_indices],
            scenario_ids=parent_ids,
            weights=parent.probabilities,
            n_keep=policy.final_count,
            protected_count=int(round(policy.final_count * policy.protected_tail_share)),
        )
        assert_nested_reduction(parent_ids, child)
        final_raw_indices = parent.representative_indices[child.representative_indices]
        final_paths = raw_hourly[final_raw_indices]
        final_sources = [source_block_ids[index] for index in final_raw_indices.tolist()]
        final_ids = [f"S10_{index + 1:02d}" for index in range(policy.final_count)]
        final_parent_ids = list(child.representative_ids)
        target = case["frame"]
        parent_paths = raw_hourly[parent.representative_indices]
        parent_sources = [
            source_block_ids[index]
            for index in parent.representative_indices.tolist()
        ]
        parent_records: list[dict[str, Any]] = []
        for scenario_position, scenario_id in enumerate(parent_ids):
            for period_position, row in target.reset_index(drop=True).iterrows():
                parent_records.append(
                    {
                        "model_id": model_id,
                        "forecast_origin_utc": origin,
                        "target_timestamp_utc": row["target_timestamp_utc"],
                        "delivery_date_local": row["delivery_date_local"],
                        "lead_day": 0,
                        "scenario_set_size": policy.parent_count,
                        "scenario_id": scenario_id,
                        "parent_scenario_id": parent.representative_ids[scenario_position],
                        "scenario_probability": float(parent.probabilities[scenario_position]),
                        "point_forecast": float(row["point_forecast"]),
                        "scenario_price": float(parent_paths[scenario_position, period_position]),
                        "source_residual_block_id": parent_sources[scenario_position],
                        "support_status": "exact_common_complete_24h_non_dst",
                    }
                )
        parent_frames.append(
            pd.DataFrame(parent_records, columns=SCENARIO_COLUMNS)
        )
        records: list[dict[str, Any]] = []
        for scenario_position, scenario_id in enumerate(final_ids):
            for period_position, row in target.reset_index(drop=True).iterrows():
                records.append(
                    {
                        "model_id": model_id,
                        "forecast_origin_utc": origin,
                        "target_timestamp_utc": row["target_timestamp_utc"],
                        "delivery_date_local": row["delivery_date_local"],
                        "lead_day": 0,
                        "scenario_set_size": policy.final_count,
                        "scenario_id": scenario_id,
                        "parent_scenario_id": final_parent_ids[scenario_position],
                        "scenario_probability": float(child.probabilities[scenario_position]),
                        "point_forecast": float(row["point_forecast"]),
                        "scenario_price": float(final_paths[scenario_position, period_position]),
                        "source_residual_block_id": final_sources[scenario_position],
                        "support_status": "exact_common_complete_24h_non_dst",
                    }
                )
        scenario_frames.append(pd.DataFrame(records, columns=SCENARIO_COLUMNS))
        for parent_position, parent_id in enumerate(parent_ids):
            child_position = int(child.source_to_representative_index[parent_position])
            mapping_rows.append(
                {
                    "model_id": model_id,
                    "forecast_origin_utc": origin,
                    "parent_scenario_id_30": parent_id,
                    "child_scenario_id_10": final_ids[child_position],
                    "parent_probability_30": float(parent.probabilities[parent_position]),
                    "child_probability_10": float(child.probabilities[child_position]),
                }
            )
    scenarios = pd.concat(scenario_frames, ignore_index=True) if scenario_frames else pd.DataFrame(columns=SCENARIO_COLUMNS)
    parent_scenarios = pd.concat(parent_frames, ignore_index=True) if parent_frames else pd.DataFrame(columns=SCENARIO_COLUMNS)
    checks = validate_scenario_contract(scenarios, expected_count=policy.final_count)
    if checks["status"].eq("fail").any():
        raise StudyContractError(f"scenario contract failed: {checks[checks['status'].eq('fail')].to_dict('records')}")
    parent_checks = validate_scenario_contract(
        parent_scenarios, expected_count=policy.parent_count
    )
    if parent_checks["status"].eq("fail").any():
        raise StudyContractError(
            f"parent scenario contract failed: {parent_checks[parent_checks['status'].eq('fail')].to_dict('records')}"
        )
    return scenarios, pd.DataFrame(mapping_rows), parent_scenarios


def validate_scenario_contract(frame: pd.DataFrame, *, expected_count: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame([{"check_name": "non_empty", "status": "fail", "observed": 0, "expected": ">0"}])
    group = ["model_id", "forecast_origin_utc"]
    scenario_level = frame.drop_duplicates(group + ["scenario_id"])
    counts = scenario_level.groupby(group)["scenario_id"].nunique()
    probability = scenario_level.groupby(group)["scenario_probability"].sum()
    duplicates = int(
        frame.duplicated(["model_id", "forecast_origin_utc", "target_timestamp_utc", "scenario_id"]).sum()
    )
    path_rows = frame.groupby(group + ["scenario_id"]).size()
    return pd.DataFrame(
        [
            {
                "check_name": "exact_scenario_count",
                "status": "pass" if bool(counts.eq(expected_count).all()) else "fail",
                "observed": sorted(counts.unique().tolist()),
                "expected": expected_count,
            },
            {
                "check_name": "probability_mass_one",
                "status": "pass" if bool(np.allclose(probability, 1.0, atol=1e-12)) else "fail",
                "observed": float((probability - 1.0).abs().max()),
                "expected": 0.0,
            },
            {
                "check_name": "scenario_key_unique",
                "status": "pass" if duplicates == 0 else "fail",
                "observed": duplicates,
                "expected": 0,
            },
            {
                "check_name": "complete_24h_paths",
                "status": "pass" if bool(path_rows.eq(24).all()) else "fail",
                "observed": sorted(path_rows.unique().tolist()),
                "expected": [24],
            },
            {
                "check_name": "optimisation_contract_has_no_actuals",
                "status": "pass" if not any("actual" in column.lower() or "y_true" in column.lower() for column in frame.columns) else "fail",
                "observed": [column for column in frame.columns if "actual" in column.lower() or "y_true" in column.lower()],
                "expected": [],
            },
        ]
    )


def previous_week_naive(frame: pd.DataFrame, truth: pd.DataFrame) -> pd.Series:
    lookup = truth.copy()
    local = pd.to_datetime(lookup["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    lookup["local_date"] = local.dt.date
    lookup["local_hour"] = local.dt.hour
    value_map = lookup.groupby(["local_date", "local_hour"])["actual_price"].mean().to_dict()
    target = pd.to_datetime(frame["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
    return pd.Series(
        [value_map.get((timestamp.date() - timedelta(days=7), timestamp.hour), np.nan) for timestamp in target],
        index=frame.index,
        dtype=float,
    )


def point_metrics(frame: pd.DataFrame, truth: pd.DataFrame) -> dict[str, Any]:
    test = frame[frame["dataset_split"].eq("test")].copy()
    test["naive_price"] = previous_week_naive(test, truth)
    point_usable = test.dropna(subset=["point_forecast", "actual_price"])
    paired = point_usable.dropna(subset=["naive_price"])
    error = point_usable["point_forecast"].to_numpy(dtype=float) - point_usable["actual_price"].to_numpy(dtype=float)
    paired_error = paired["point_forecast"].to_numpy(dtype=float) - paired["actual_price"].to_numpy(dtype=float)
    naive_error = paired["naive_price"].to_numpy(dtype=float) - paired["actual_price"].to_numpy(dtype=float)
    mae = float(np.mean(np.abs(error)))
    naive_mae = float(np.mean(np.abs(naive_error)))
    paired_model_mae = float(np.mean(np.abs(paired_error)))
    rmae = paired_model_mae / naive_mae if naive_mae > 0.0 else np.nan
    return {
        "model_id": str(frame["model_id"].iloc[0]),
        "mae": mae,
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "paired_model_mae_for_rmae": paired_model_mae,
        "naive_previous_week_mae": naive_mae,
        "rmae": float(rmae),
        "skill_1_minus_rmae": float(1.0 - rmae),
        "origin_count": int(point_usable["forecast_origin_utc"].nunique()),
        "timestamp_count": int(len(point_usable)),
        "rmae_origin_count": int(paired["forecast_origin_utc"].nunique()),
        "rmae_timestamp_count": int(len(paired)),
        "naive_policy": "same_local_hour_seven_days_earlier_DST_aware",
    }


def _weighted_quantiles_by_period(paths: np.ndarray, weights: np.ndarray, levels: Iterable[float]) -> dict[float, np.ndarray]:
    return {
        float(level): np.asarray(
            [weighted_quantile(paths[:, index], weights, float(level)) for index in range(paths.shape[1])]
        )
        for level in levels
    }


def _interval_score(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray, alpha: float) -> np.ndarray:
    return (
        upper
        - lower
        + (2.0 / alpha) * (lower - actual) * (actual < lower)
        + (2.0 / alpha) * (actual - upper) * (actual > upper)
    )


def scenario_metrics(scenarios: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    """Report proper scores, coverage, spread, ramps, tails, and diversity."""

    rows: list[dict[str, Any]] = []
    model_id = str(scenarios["model_id"].iloc[0])
    test_points = points[points["dataset_split"].eq("test")]
    for origin, group in scenarios.groupby("forecast_origin_utc"):
        ordered_scenarios = sorted(group["scenario_id"].unique().tolist())
        ordered_targets = sorted(group["target_timestamp_utc"].unique().tolist())
        pivot = group.pivot(index="scenario_id", columns="target_timestamp_utc", values="scenario_price")
        paths = pivot.reindex(index=ordered_scenarios, columns=ordered_targets).to_numpy(dtype=float)
        probability = (
            group.drop_duplicates("scenario_id").set_index("scenario_id").reindex(ordered_scenarios)["scenario_probability"].to_numpy(dtype=float)
        ).copy()
        probability /= probability.sum()
        actual = (
            test_points[test_points["forecast_origin_utc"].eq(origin)]
            .set_index("target_timestamp_utc")
            .reindex(ordered_targets)["actual_price"]
            .to_numpy(dtype=float)
        )
        quantile = _weighted_quantiles_by_period(paths, probability, (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95))
        intervals = {0.50: (0.25, 0.75), 0.80: (0.10, 0.90), 0.90: (0.05, 0.95)}
        metrics: dict[str, Any] = {}
        interval_scores: list[tuple[float, np.ndarray]] = []
        for nominal, (lower_q, upper_q) in intervals.items():
            lower = quantile[lower_q]
            upper = quantile[upper_q]
            suffix = str(int(100 * nominal))
            metrics[f"coverage_{suffix}"] = float(np.mean((actual >= lower) & (actual <= upper)))
            metrics[f"width_{suffix}"] = float(np.mean(upper - lower))
            alpha = 1.0 - nominal
            interval_scores.append((alpha, _interval_score(actual, lower, upper, alpha)))
        wis_numerator = 0.5 * np.abs(actual - quantile[0.50])
        for alpha, score in interval_scores:
            wis_numerator += (alpha / 2.0) * score
        wis = wis_numerator / (len(interval_scores) + 0.5)
        scenario_ramps = np.diff(paths, axis=1)
        actual_ramps = np.diff(actual)
        ramp_low = np.asarray(
            [weighted_quantile(scenario_ramps[:, index], probability, 0.05) for index in range(scenario_ramps.shape[1])]
        )
        ramp_high = np.asarray(
            [weighted_quantile(scenario_ramps[:, index], probability, 0.95) for index in range(scenario_ramps.shape[1])]
        )
        rounded_paths = np.round(paths, 10)
        unique_paths = int(np.unique(rounded_paths, axis=0).shape[0])
        pairwise = np.sqrt(np.mean((paths[:, None, :] - paths[None, :, :]) ** 2, axis=2))
        off_diagonal = pairwise[~np.eye(pairwise.shape[0], dtype=bool)]
        rows.append(
            {
                "model_id": model_id,
                "forecast_origin_utc": origin,
                **metrics,
                "mean_crps": float(np.mean(crps_by_timestamp(paths, actual, probability))),
                "mean_wis": float(np.mean(wis)),
                "mean_scenario_std": float(np.mean(np.sqrt(np.average((paths - np.average(paths, axis=0, weights=probability)) ** 2, axis=0, weights=probability)))),
                "ramp_coverage_90": float(np.mean((actual_ramps >= ramp_low) & (actual_ramps <= ramp_high))),
                "actual_max_abs_ramp": float(np.max(np.abs(actual_ramps))),
                "scenario_max_abs_ramp_p95": float(weighted_quantile(np.max(np.abs(scenario_ramps), axis=1), probability, 0.95)),
                "high_tail_miss_rate_90": float(np.mean(actual > quantile[0.95])),
                "low_tail_miss_rate_90": float(np.mean(actual < quantile[0.05])),
                "minimum_scenario_price": float(paths.min()),
                "maximum_scenario_price": float(paths.max()),
                "unique_complete_paths": unique_paths,
                "duplicate_complete_paths": int(len(ordered_scenarios) - unique_paths),
                "mean_pairwise_path_rmse": float(np.mean(off_diagonal)) if off_diagonal.size else 0.0,
                "effective_scenario_count": float(1.0 / np.sum(probability**2)),
                "probability_mass": float(probability.sum()),
            }
        )
    by_origin = pd.DataFrame(rows)
    if by_origin.empty:
        return by_origin
    numeric = [column for column in by_origin.columns if column not in {"model_id", "forecast_origin_utc"}]
    summary = by_origin.groupby("model_id", as_index=False)[numeric].mean(numeric_only=True)
    summary["forecast_origin_utc"] = "ALL"
    return pd.concat([by_origin, summary[by_origin.columns]], ignore_index=True)


def build_shape_library(
    hourly_points: pd.DataFrame,
    quarterhour_points: pd.DataFrame,
    hourly_scenarios: pd.DataFrame,
    quarterhour_scenarios: pd.DataFrame,
    actuals: pd.DataFrame,
    *,
    tolerance: float = 1e-10,
) -> dict[str, pd.DataFrame]:
    """Build point/scenario/actual zero-mean shape pools from governed QH data."""

    hourly_points = hourly_points[pd.to_numeric(hourly_points["lead_day"], errors="coerce").eq(0)].copy()
    quarterhour_points = quarterhour_points[
        pd.to_numeric(quarterhour_points["lead_day"], errors="coerce").eq(0)
    ].copy()
    hourly_scenarios = hourly_scenarios[
        pd.to_numeric(hourly_scenarios["lead_day"], errors="coerce").eq(0)
    ].copy()
    quarterhour_scenarios = quarterhour_scenarios[
        pd.to_numeric(quarterhour_scenarios["lead_day"], errors="coerce").eq(0)
    ].copy()
    actuals = actuals[pd.to_numeric(actuals["lead_day"], errors="coerce").eq(0)].copy()
    for frame in (hourly_points, quarterhour_points, hourly_scenarios, quarterhour_scenarios, actuals):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True)
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)
    q_point = quarterhour_points.copy()
    q_point["hour_start_utc"] = q_point["target_timestamp_utc"].dt.floor("h")
    h_point = hourly_points.rename(columns={"target_timestamp_utc": "hour_start_utc", "point_forecast": "hourly_anchor"})
    point = q_point.merge(
        h_point[["forecast_origin_utc", "hour_start_utc", "lead_day", "hourly_anchor"]],
        on=["forecast_origin_utc", "hour_start_utc", "lead_day"],
        validate="many_to_one",
    )
    point["quarterhour_delta"] = point["point_forecast"] - point["hourly_anchor"]

    q_scenario = quarterhour_scenarios.copy()
    q_scenario["hour_start_utc"] = q_scenario["target_timestamp_utc"].dt.floor("h")
    h_scenario = hourly_scenarios.rename(
        columns={"target_timestamp_utc": "hour_start_utc", "scenario_price": "hourly_anchor"}
    )
    scenario = q_scenario.merge(
        h_scenario[
            ["forecast_origin_utc", "hour_start_utc", "lead_day", "scenario_id", "hourly_anchor"]
        ],
        on=["forecast_origin_utc", "hour_start_utc", "lead_day", "scenario_id"],
        validate="many_to_one",
    )
    scenario["quarterhour_delta"] = scenario["scenario_price"] - scenario["hourly_anchor"]

    q_actual = actuals[actuals["granularity"].eq("quarterhour")].copy()
    h_actual = actuals[actuals["granularity"].eq("hourly")].copy().rename(
        columns={"target_timestamp_utc": "hour_start_utc", "actual_price": "hourly_anchor"}
    )
    q_actual["hour_start_utc"] = q_actual["target_timestamp_utc"].dt.floor("h")
    actual = q_actual.merge(
        h_actual[["forecast_origin_utc", "hour_start_utc", "lead_day", "hourly_anchor"]],
        on=["forecast_origin_utc", "hour_start_utc", "lead_day"],
        validate="many_to_one",
    )
    actual["quarterhour_delta"] = actual["actual_price"] - actual["hourly_anchor"]

    for label, frame, keys in (
        ("point", point, ["forecast_origin_utc", "hour_start_utc"]),
        ("scenario", scenario, ["forecast_origin_utc", "hour_start_utc", "scenario_id"]),
        ("actual", actual, ["forecast_origin_utc", "hour_start_utc"]),
    ):
        counts = frame.groupby(keys).size()
        means = frame.groupby(keys)["quarterhour_delta"].mean()
        if not bool(counts.eq(4).all()):
            raise StudyContractError(f"{label} shape library contains incomplete hours")
        if float(means.abs().max()) > tolerance:
            raise StudyContractError(f"{label} shape library violates hourly mean preservation")
        local = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TIMEZONE)
        frame["local_hour"] = local.dt.hour
        frame["quarter_index"] = local.dt.minute.floordiv(15).add(1)
        frame["weekend"] = local.dt.dayofweek.ge(5)
        frame["source_local_date"] = local.dt.date.astype(str)
    return {"point": point, "scenario": scenario, "actual": actual}


def apply_counterfactual_shape_overlay(
    *,
    week_id: str,
    hourly_points: pd.DataFrame,
    hourly_scenarios: pd.DataFrame,
    hourly_actuals: pd.DataFrame,
    shape_library: dict[str, pd.DataFrame],
    random_seed: int,
    tolerance: float = 1e-10,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create flat and shape QH paths while retaining every hourly anchor."""

    point_template = (
        shape_library["point"]
        .groupby(["local_hour", "quarter_index", "weekend"])["quarterhour_delta"]
        .mean()
        .to_dict()
    )
    actual_profiles = [
        (key, group.sort_values("target_timestamp_utc"))
        for key, group in shape_library["actual"].groupby(["source_local_date", "weekend"])
        if len(group) == 96
    ]
    scenario_profiles = [
        (key, group.sort_values("target_timestamp_utc"))
        for key, group in shape_library["scenario"].groupby(["source_local_date", "weekend", "scenario_id"])
        if len(group) == 96
    ]
    rows: list[dict[str, Any]] = []

    def emit_hour(
        *,
        path_kind: str,
        scenario_id: str,
        probability: float,
        timestamp: pd.Timestamp,
        anchor: float,
        deltas: np.ndarray,
        source_profile_id: str,
        scenario_set_size: int,
    ) -> None:
        centred = np.asarray(deltas, dtype=float) - float(np.mean(deltas))
        for quarter_offset, delta in enumerate(centred):
            rows.append(
                {
                    "week_id": week_id,
                    "path_kind": path_kind,
                    "scenario_id": scenario_id,
                    "scenario_probability": probability,
                    "scenario_set_size": int(scenario_set_size),
                    "target_timestamp_utc": timestamp + pd.Timedelta(minutes=15 * quarter_offset),
                    "hour_start_utc": timestamp,
                    "quarter_index": quarter_offset + 1,
                    "hourly_anchor_price": float(anchor),
                    "quarterhour_delta": float(delta),
                    "quarterhour_price": float(anchor + delta),
                    "source_profile_id": source_profile_id,
                    "counterfactual": True,
                }
            )

    point_week = hourly_points.sort_values("target_timestamp_utc")
    for _, row in point_week.iterrows():
        local = pd.Timestamp(row["target_timestamp_utc"]).tz_convert(LOCAL_TIMEZONE)
        deltas = np.asarray(
            [point_template.get((local.hour, quarter, bool(local.dayofweek >= 5)), 0.0) for quarter in range(1, 5)]
        )
        emit_hour(
            path_kind="point_shape",
            scenario_id="POINT",
            probability=1.0,
            timestamp=pd.Timestamp(row["target_timestamp_utc"]),
            anchor=float(row["point_forecast"]),
            deltas=deltas,
            source_profile_id="mean_shape_local_hour_quarter_weekend",
            scenario_set_size=1,
        )
        emit_hour(
            path_kind="point_flat",
            scenario_id="POINT",
            probability=1.0,
            timestamp=pd.Timestamp(row["target_timestamp_utc"]),
            anchor=float(row["point_forecast"]),
            deltas=np.zeros(4),
            source_profile_id="flat_repeat",
            scenario_set_size=1,
        )

    for scenario_id, scenario_path in hourly_scenarios.groupby("scenario_id"):
        probability = float(scenario_path["scenario_probability"].iloc[0])
        if "scenario_set_size" in scenario_path.columns:
            scenario_set_size = int(scenario_path["scenario_set_size"].iloc[0])
        else:
            scenario_set_size = int(hourly_scenarios["scenario_id"].nunique())
        for day, day_group in scenario_path.groupby("delivery_date_local"):
            weekend = pd.Timestamp(day).dayofweek >= 5
            candidates = [(key, profile) for key, profile in scenario_profiles if bool(key[1]) == bool(weekend)]
            if not candidates:
                raise StudyContractError("no complete scenario shape profile for requested day type")
            choice = stable_seed(random_seed, week_id, scenario_id, day, "scenario_shape") % len(candidates)
            source_key, source = candidates[choice]
            source_by_hour = {
                int(hour): group.sort_values("quarter_index")["quarterhour_delta"].to_numpy(dtype=float)
                for hour, group in source.groupby("local_hour")
            }
            for _, row in day_group.sort_values("target_timestamp_utc").iterrows():
                local = pd.Timestamp(row["target_timestamp_utc"]).tz_convert(LOCAL_TIMEZONE)
                emit_hour(
                    path_kind="scenario_shape",
                    scenario_id=str(scenario_id),
                    probability=probability,
                    timestamp=pd.Timestamp(row["target_timestamp_utc"]),
                    anchor=float(row["scenario_price"]),
                    deltas=source_by_hour[local.hour],
                    source_profile_id=f"{source_key[0]}__{source_key[2]}",
                    scenario_set_size=scenario_set_size,
                )
                emit_hour(
                    path_kind="scenario_flat",
                    scenario_id=str(scenario_id),
                    probability=probability,
                    timestamp=pd.Timestamp(row["target_timestamp_utc"]),
                    anchor=float(row["scenario_price"]),
                    deltas=np.zeros(4),
                    source_profile_id="flat_repeat",
                    scenario_set_size=scenario_set_size,
                )

    actual_week = hourly_actuals.sort_values("target_timestamp_utc")
    for day, day_group in actual_week.groupby("delivery_date_local"):
        weekend = pd.Timestamp(day).dayofweek >= 5
        candidates = [(key, profile) for key, profile in actual_profiles if bool(key[1]) == bool(weekend)]
        if not candidates:
            raise StudyContractError("no complete actual shape profile for requested day type")
        choice = stable_seed(random_seed, week_id, day, "actual_shape") % len(candidates)
        source_key, source = candidates[choice]
        source_by_hour = {
            int(hour): group.sort_values("quarter_index")["quarterhour_delta"].to_numpy(dtype=float)
            for hour, group in source.groupby("local_hour")
        }
        for _, row in day_group.iterrows():
            local = pd.Timestamp(row["target_timestamp_utc"]).tz_convert(LOCAL_TIMEZONE)
            emit_hour(
                path_kind="counterfactual_actual",
                scenario_id="ACTUAL",
                probability=1.0,
                timestamp=pd.Timestamp(row["target_timestamp_utc"]),
                anchor=float(row["actual_price"]),
                deltas=source_by_hour[local.hour],
                source_profile_id=str(source_key[0]),
                scenario_set_size=1,
            )

    overlay = pd.DataFrame(rows, columns=OVERLAY_COLUMNS)
    checks = validate_overlay_contract(overlay, tolerance=tolerance)
    if checks["status"].eq("fail").any():
        raise StudyContractError(f"counterfactual overlay failed: {checks[checks['status'].eq('fail')].to_dict('records')}")
    manifest = {
        "week_id": week_id,
        "method": "additive_mean_preserving_shape_overlay",
        "formula": "quarterhour_price = hourly_anchor_price + quarterhour_delta",
        "random_seed": int(random_seed),
        "counterfactual": True,
        "mean_preservation_tolerance": float(tolerance),
        "point_shape_pool_rows": int(len(shape_library["point"])),
        "scenario_shape_pool_rows": int(len(shape_library["scenario"])),
        "actual_shape_pool_rows": int(len(shape_library["actual"])),
        "observed_historical_qh_claim": False,
        "checks": checks.to_dict(orient="records"),
    }
    return overlay, manifest


def validate_overlay_contract(overlay: pd.DataFrame, *, tolerance: float = 1e-10) -> pd.DataFrame:
    keys = ["week_id", "path_kind", "scenario_id", "hour_start_utc"]
    group = overlay.groupby(keys)
    counts = group.size()
    mean_delta = group["quarterhour_delta"].mean()
    reconstructed = (overlay["hourly_anchor_price"] + overlay["quarterhour_delta"] - overlay["quarterhour_price"]).abs()
    counterfactual = overlay["counterfactual"].fillna(False).astype(bool)
    return pd.DataFrame(
        [
            {"check_name": "four_quarters_per_hour", "status": "pass" if bool(counts.eq(4).all()) else "fail", "observed": sorted(counts.unique().tolist()), "expected": [4]},
            {"check_name": "zero_mean_delta_per_hour", "status": "pass" if float(mean_delta.abs().max()) <= tolerance else "fail", "observed": float(mean_delta.abs().max()), "expected": tolerance},
            {"check_name": "additive_price_identity", "status": "pass" if float(reconstructed.max()) <= tolerance else "fail", "observed": float(reconstructed.max()), "expected": tolerance},
            {"check_name": "explicit_counterfactual_label", "status": "pass" if bool(counterfactual.all()) else "fail", "observed": int((~counterfactual).sum()), "expected": 0},
        ]
    )


def compute_week_features(hourly_actuals: pd.DataFrame) -> pd.DataFrame:
    """Compute robust-regime features for complete Monday-Sunday weeks."""

    frame = hourly_actuals.copy()
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)
    local = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TIMEZONE)
    frame["local_date"] = local.dt.date
    frame["week_start"] = pd.to_datetime(frame["local_date"]) - pd.to_timedelta(local.dt.dayofweek, unit="D")
    rows: list[dict[str, Any]] = []
    for week_start, group in frame.groupby("week_start"):
        ordered = group.sort_values("target_timestamp_utc")
        dates = sorted(set(ordered["local_date"]))
        if len(dates) != 7 or pd.Timestamp(week_start).dayofweek != 0 or len(ordered) != 168:
            continue
        price = ordered["actual_price"].to_numpy(dtype=float)
        ramps = np.abs(np.diff(price))
        rows.append(
            {
                "week_start": pd.Timestamp(week_start).date().isoformat(),
                "week_end": (pd.Timestamp(week_start) + pd.Timedelta(days=6)).date().isoformat(),
                "mean_price": float(np.mean(price)),
                "std_price": float(np.std(price, ddof=0)),
                "iqr_price": float(np.quantile(price, 0.75) - np.quantile(price, 0.25)),
                "p05_p95_range": float(np.quantile(price, 0.95) - np.quantile(price, 0.05)),
                "negative_share": float(np.mean(price < 0.0)),
                "mean_absolute_ramp": float(np.mean(ramps)),
                "max_absolute_ramp": float(np.max(ramps)),
                "minimum_price": float(np.min(price)),
                "complete_non_interpolated_hourly_actuals": True,
            }
        )
    return pd.DataFrame(rows).sort_values("week_start").reset_index(drop=True)


def _robust_z(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for column in columns:
        values = frame[column].astype(float)
        median = float(values.median())
        mad = float(np.median(np.abs(values - median)))
        scale = 1.4826 * mad
        if not np.isfinite(scale) or scale <= 1e-12:
            scale = float(values.std(ddof=0)) or 1.0
        result[column] = (values - median) / scale
    return result


def select_regime_weeks(
    features: pd.DataFrame,
    *,
    eligible_week_starts: set[str],
    provisional: dict[str, str],
    minimum_separation_days: int = 28,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select four predeclared roles deterministically before optimisation."""

    work = features[features["week_start"].isin(eligible_week_starts)].copy().reset_index(drop=True)
    if work.empty:
        raise StudyContractError("no weeks meet actual, Strict, look-ahead, and overlay support")
    start = pd.to_datetime(work["week_start"])
    month = start.dt.month
    work["season"] = np.where(month.isin([11, 12, 1, 2, 3]), "winter", np.where(month.isin([5, 6, 7, 8, 9]), "summer", "shoulder"))
    feature_columns = ["mean_price", "std_price", "iqr_price", "p05_p95_range", "negative_share", "mean_absolute_ramp"]
    z = _robust_z(work, feature_columns)
    work["volatility_composite"] = z[["std_price", "iqr_price", "p05_p95_range", "mean_absolute_ramp"]].mean(axis=1)
    work["mean_price_percentile"] = work["mean_price"].rank(pct=True, method="max")
    work["volatility_percentile"] = work["volatility_composite"].rank(pct=True, method="max")
    for season in ("winter", "summer"):
        mask = work["season"].eq(season)
        if not mask.any():
            raise StudyContractError(f"no eligible {season} week")
        centre = z.loc[mask, feature_columns].median()
        work.loc[mask, f"distance_to_{season}_median"] = np.sqrt(
            ((z.loc[mask, feature_columns] - centre) ** 2).sum(axis=1)
        )

    rankings: dict[str, list[str]] = {
        "typical_winter": work[work["season"].eq("winter")].sort_values(["distance_to_winter_median", "week_start"])["week_start"].tolist(),
        "high_prices": work[work["mean_price_percentile"].ge(0.90)].sort_values(["mean_price", "week_start"], ascending=[False, True])["week_start"].tolist(),
        "high_volatility": work[work["volatility_percentile"].ge(0.90)].sort_values(["volatility_composite", "week_start"], ascending=[False, True])["week_start"].tolist(),
        "typical_summer": work[work["season"].eq("summer")].sort_values(["distance_to_summer_median", "week_start"])["week_start"].tolist(),
    }
    roles = ("typical_winter", "high_prices", "high_volatility", "typical_summer")
    best: tuple[tuple[Any, ...], dict[str, tuple[str, int]]] | None = None

    def search(
        role_index: int,
        chosen: dict[str, tuple[str, int]],
        timestamps: list[pd.Timestamp],
    ) -> None:
        nonlocal best
        if role_index == len(roles):
            ranks = tuple(chosen[role][1] for role in roles)
            dates = tuple(chosen[role][0] for role in roles)
            score: tuple[Any, ...] = (sum(ranks), max(ranks), ranks, dates)
            if best is None or score < best[0]:
                best = (score, dict(chosen))
            return
        role = roles[role_index]
        for candidate_rank, candidate in enumerate(rankings[role], start=1):
            timestamp = pd.Timestamp(candidate)
            if any(abs((timestamp - prior).days) < int(minimum_separation_days) for prior in timestamps):
                continue
            chosen[role] = (candidate, candidate_rank)
            search(role_index + 1, chosen, timestamps + [timestamp])
            chosen.pop(role)

    search(0, {}, [])
    if best is None:
        raise StudyContractError(
            f"no globally feasible four-role combination satisfies the {minimum_separation_days}-day separation rule"
        )

    selected_rows: list[dict[str, Any]] = []
    for role in roles:
        selected, rank = best[1][role]
        provisional_week = provisional.get(role)
        row = work[work["week_start"].eq(selected)].iloc[0]
        selected_rows.append(
            {
                "regime_role": role,
                "week_id": f"{role}__{selected}",
                "week_start": selected,
                "week_end": row["week_end"],
                "deterministic_role_rank": rank,
                "provisional_candidate": provisional_week,
                "provisional_retained": bool(selected == provisional_week),
                "mean_price_percentile": float(row["mean_price_percentile"]),
                "volatility_percentile": float(row["volatility_percentile"]),
                "distance_to_winter_median": row.get("distance_to_winter_median", np.nan),
                "distance_to_summer_median": row.get("distance_to_summer_median", np.nan),
                "minimum_separation_days": int(minimum_separation_days),
                "selection_frozen_before_optimisation": True,
            }
        )
    selected_table = pd.DataFrame(selected_rows)
    work["selected_regime_role"] = ""
    for row in selected_rows:
        work.loc[work["week_start"].eq(row["week_start"]), "selected_regime_role"] = row["regime_role"]
    return selected_table, work


def read_physical_prerequisite(summary_path: str | Path, failures_path: str | Path | None = None) -> dict[str, Any]:
    summary_file = Path(summary_path)
    if not summary_file.exists():
        return {
            "status": "blocked",
            "reason": "physical_prerequisite_run_summary_missing",
            "economic_steel_execution_allowed": False,
        }
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    failures: list[dict[str, Any]] = []
    if failures_path is not None and Path(failures_path).exists():
        failures = pd.read_csv(failures_path).fillna("").to_dict(orient="records")
    physical_failures = [
        failure
        for failure in failures
        if str(failure.get("classification", "")) != "performance_incomplete"
    ]
    passed = (
        summary.get("gate_a_status") == "pass"
        and int(summary.get("validation_failure_count", 0)) == 0
        and not physical_failures
    )
    performance_incomplete = any(
        str(failure.get("classification", "")) == "performance_incomplete"
        for failure in failures
    )
    return {
        "status": (
            "pass_with_performance_warning"
            if passed and performance_incomplete
            else "pass" if passed else "blocked"
        ),
        "source_run_id": summary.get("run_id"),
        "source_decision": summary.get("decision"),
        "gate_a_status": summary.get("gate_a_status"),
        "failure_count": int(summary.get("failure_count", 0)),
        "failures": failures,
        "physical_failure_count": len(physical_failures),
        "performance_incomplete": performance_incomplete,
        "economic_steel_execution_allowed": bool(passed),
        "repair_policy": "implementation_or_contract_errors_only_no_physical_bound_widening",
    }


def build_steel_experiment_manifest(
    selected_weeks: pd.DataFrame,
    *,
    physical_prerequisite: dict[str, Any],
    long_horizon_support_available: bool,
    scenario_30_support_available: bool = False,
    c1_split_horizon_feasible: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enumerate central/sensitivity rows and their fail-closed readiness."""

    rows: list[dict[str, Any]] = []
    physical_ready = bool(physical_prerequisite.get("economic_steel_execution_allowed", False))

    def add(
        week: pd.Series,
        *,
        experiment_class: str,
        arm: str,
        configuration: str,
        horizon_hours: int,
        scenario_count: int,
        benchmark: str,
    ) -> None:
        missing_long = horizon_hours > 24 and not long_horizon_support_available
        missing_s30 = scenario_count == 30 and not scenario_30_support_available
        missing_c1_split = not c1_split_horizon_feasible
        ready = physical_ready and not missing_long and not missing_s30 and not missing_c1_split
        blockers: list[str] = []
        if not physical_ready:
            blockers.append("shared_qh_physical_prerequisite_failed")
        if missing_long:
            blockers.append("causal_strict_dplus1_to_dplus4_support_missing")
        if missing_s30:
            blockers.append("strict_s30_counterfactual_overlay_missing")
        if missing_c1_split:
            blockers.append("global_c1_24e48p_split_horizon_prerequisite_failed")
        rows.append(
            {
                "experiment_id": (
                    f"{week['week_id']}__{experiment_class}__{arm}__{configuration}"
                    f"__h{int(horizon_hours)}__s{int(scenario_count)}__{benchmark}"
                ),
                "week_id": week["week_id"],
                "regime_role": week["regime_role"],
                "week_start": week["week_start"],
                "week_end": week["week_end"],
                "experiment_class": experiment_class,
                "arm": arm,
                "configuration": configuration,
                "horizon_hours": int(horizon_hours),
                "economic_horizon_hours": int(horizon_hours),
                "physical_horizon_hours": 48 if int(horizon_hours) == 24 else int(horizon_hours),
                "physical_feasibility_tail_active": int(horizon_hours) == 24,
                "tail_price_information": "none" if int(horizon_hours) == 24 else "not_applicable",
                "tail_market_binding": False if int(horizon_hours) == 24 else None,
                "tail_executed_or_settled": False if int(horizon_hours) == 24 else None,
                "execution_hours": 24,
                "scenario_count": int(scenario_count),
                "risk_policy": "risk_neutral",
                "benchmark": benchmark,
                "internal_physics_grid": "quarterhour",
                "maintenance_policy": "maintenance_free_normal_operation_week",
                "weekly_eaf_maintenance_active": False,
                "annual_outage_active": False,
                "solver_time_limit_seconds": 900,
                "mfrr_active": False,
                "cvar_active": False,
                "economic_execution_ready": ready,
                "blockers": "|".join(blockers),
            }
        )

    for _, week in selected_weeks.iterrows():
        for configuration in ("C0", "C1"):
            for arm in ("A_hourly", "B_qh_flat", "C_qh_shape"):
                add(week, experiment_class="central", arm=arm, configuration=configuration, horizon_hours=24, scenario_count=10, benchmark="stochastic_policy")
            for benchmark_arm in ("A_hourly", "BC_qh_shared"):
                for benchmark in ("price_insensitive", "true_perfect_foresight"):
                    add(week, experiment_class="central_benchmark", arm=benchmark_arm, configuration=configuration, horizon_hours=24, scenario_count=10, benchmark=benchmark)
            for horizon in (24, 48, 72, 96, 120):
                add(week, experiment_class="horizon_sensitivity", arm="C_qh_shape", configuration=configuration, horizon_hours=horizon, scenario_count=10, benchmark="stochastic_policy")
            for count in (10, 30):
                add(week, experiment_class="scenario_count_sensitivity", arm="C_qh_shape", configuration=configuration, horizon_hours=24, scenario_count=count, benchmark="stochastic_policy")
    manifest = pd.DataFrame(rows)
    ready_count = int(manifest["economic_execution_ready"].sum())
    readiness_status = (
        "ready"
        if ready_count == len(manifest)
        else "partially_ready" if ready_count else "blocked"
    )
    readiness = {
        "status": readiness_status,
        "physical_prerequisite": physical_prerequisite,
        "long_horizon_support_available": bool(long_horizon_support_available),
        "scenario_30_support_available": bool(scenario_30_support_available),
        "c1_split_horizon_feasible": bool(c1_split_horizon_feasible),
        "central_rows": int(manifest["experiment_class"].isin(["central", "central_benchmark"]).sum()),
        "sensitivity_rows": int(manifest["experiment_class"].str.contains("sensitivity").sum()),
        "total_rows": int(len(manifest)),
        "ready_rows": ready_count,
        "blocked_rows": int(len(manifest) - ready_count),
        "claims": {
            "representative_regime_cases_only": True,
            "annualisation_allowed": False,
            "historical_qh_2024_2025_claim_allowed": False,
            "positive_economic_effect_required": False,
        },
        "forbidden_scope": ["mFRR", "CVaR", "ETS", "export", "product_revenue", "emergency_import", "imbalance_optimisation"],
    }
    return manifest, readiness


def realised_cost_differences(cost_a: float, cost_b: float, cost_c: float) -> dict[str, float]:
    return {
        "delta_qh_market_eur": float(cost_a - cost_b),
        "delta_shape_eur": float(cost_b - cost_c),
        "delta_total_eur": float(cost_a - cost_c),
        "positive_means_saving": True,
    }


__all__ = [
    "OVERLAY_COLUMNS",
    "POINT_COLUMNS",
    "PUBLIC_MODEL_IDS",
    "SCENARIO_COLUMNS",
    "STRICT_MODEL_ID",
    "ScenarioPolicy",
    "StudyContractError",
    "align_common_non_dst_support",
    "apply_counterfactual_shape_overlay",
    "build_hourly_residual_blocks",
    "build_shape_library",
    "build_steel_experiment_manifest",
    "calibrate_hourly_level_scale",
    "compute_week_features",
    "generate_hourly_nested_scenarios",
    "information_timing_checks",
    "load_study_config",
    "normalise_frozen_point_source",
    "point_metrics",
    "read_physical_prerequisite",
    "realised_cost_differences",
    "scenario_metrics",
    "select_regime_weeks",
    "sha256_file",
    "validate_overlay_contract",
    "validate_scenario_contract",
]
