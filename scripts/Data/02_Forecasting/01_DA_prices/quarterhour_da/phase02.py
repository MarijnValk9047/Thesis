from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig


@dataclass(frozen=True)
class EmpiricalSplitWindow:
    split: str
    start_date: date
    end_date: date
    notes: str


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase02_shape_targets")


def find_latest_phase02_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase02_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _read_phase01_authority(config: QuarterHourDAExtensionConfig) -> dict[str, Any]:
    phase01_run_root = config.phase01_runs_root
    if not phase01_run_root.exists():
        return {
            "phase01_run_dir": None,
            "authoritative_quarterhour_path": config.shared_quarterly_csv,
            "companion_quarterhour_path": config.dedicated_quarterly_csv,
        }
    candidates = sorted(path for path in phase01_run_root.iterdir() if path.is_dir() and (path / "foundation_contracts.csv").exists())
    latest = candidates[-1] if candidates else None
    authoritative = config.shared_quarterly_csv
    companion = config.dedicated_quarterly_csv
    if latest is not None:
        contracts = pd.read_csv(latest / "foundation_contracts.csv")
        authoritative_rows = contracts[contracts["contract_name"].astype(str) == "quarterhour_actual_authoritative"]
        companion_rows = contracts[contracts["contract_name"].astype(str) == "quarterhour_continuation_companion"]
        if not authoritative_rows.empty:
            authoritative = Path(str(authoritative_rows.iloc[0]["path_or_target"]))
        if not companion_rows.empty:
            companion = Path(str(companion_rows.iloc[0]["path_or_target"]))
    return {
        "phase01_run_dir": str(latest) if latest is not None else None,
        "authoritative_quarterhour_path": authoritative,
        "companion_quarterhour_path": companion,
    }


def _load_quarterhour_source(path: Path, *, timezone: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Quarter-hour source file not found: {path}")
    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError(f"Quarter-hour source file is empty: {path}")
    required_columns = {
        "timestamp_utc",
        "price_eur_per_mwh",
        "gap_fix_action",
        "is_interpolated_value",
        "is_flagged_missing_value",
        "missing_datapoint_source",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Quarter-hour source file is missing required columns: {missing_columns}")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
    frame["price_eur_per_mwh_original"] = pd.to_numeric(frame.get("price_eur_per_mwh_original"), errors="coerce")
    frame["is_interpolated_value"] = frame["is_interpolated_value"].astype(bool)
    frame["is_flagged_missing_value"] = frame["is_flagged_missing_value"].astype(bool)
    frame = frame.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)

    timestamp_local = frame["timestamp_utc"].dt.tz_convert(timezone)
    frame["timestamp_local"] = timestamp_local
    frame["delivery_local_date"] = timestamp_local.dt.date
    frame["local_hour_of_day"] = timestamp_local.dt.hour.astype(int)
    frame["local_minute"] = timestamp_local.dt.minute.astype(int)
    frame["quarter_index"] = (timestamp_local.dt.minute // 15 + 1).astype(int)
    frame["hour_start_utc"] = frame["timestamp_utc"].dt.floor("h")
    frame["hour_start_local"] = frame["hour_start_utc"].dt.tz_convert(timezone)
    frame["hour_local_date"] = frame["hour_start_local"].dt.date
    return frame


def _source_availability_summary(frame: pd.DataFrame, *, dataset_name: str) -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(frame["timestamp_utc"]).sort_values()
    expected = pd.date_range(start=timestamps.min(), end=timestamps.max(), freq="15min", tz="UTC")
    missing_count = int(expected.difference(timestamps).shape[0])
    return pd.DataFrame(
        [
            {
                "dataset_name": dataset_name,
                "start_timestamp_utc": timestamps.min().isoformat(),
                "end_timestamp_utc": timestamps.max().isoformat(),
                "frequency_minutes": 15,
                "number_of_rows": int(frame.shape[0]),
                "duplicate_timestamps": int(frame["timestamp_utc"].duplicated().sum()),
                "missing_timestamps": missing_count,
                "interpolated_points_count": int(frame["is_interpolated_value"].sum()),
                "flagged_missing_points_count": int(frame["is_flagged_missing_value"].sum()),
                "remaining_missing_price_points": int(frame["price_eur_per_mwh"].isna().sum()),
            }
        ]
    )


def _source_consistency_summary(authoritative: pd.DataFrame, companion: pd.DataFrame) -> pd.DataFrame:
    if companion.empty:
        return pd.DataFrame(
            [
                {
                    "comparison_name": "authoritative_vs_companion_quarterhour",
                    "authoritative_rows": int(authoritative.shape[0]),
                    "companion_rows": 0,
                    "same_row_count": False,
                    "same_min_timestamp": False,
                    "same_max_timestamp": False,
                    "timestamps_only_in_authoritative": int(authoritative.shape[0]),
                    "timestamps_only_in_companion": 0,
                    "shared_timestamps_with_price_mismatch": np.nan,
                    "notes": "Companion file was unavailable or empty.",
                }
            ]
        )

    left = authoritative[["timestamp_utc", "price_eur_per_mwh"]].rename(columns={"price_eur_per_mwh": "price_authoritative"})
    right = companion[["timestamp_utc", "price_eur_per_mwh"]].rename(columns={"price_eur_per_mwh": "price_companion"})
    merged = left.merge(right, on="timestamp_utc", how="outer", indicator=True)
    price_mismatch = merged[
        merged["_merge"].eq("both")
        & ~np.isclose(
            merged["price_authoritative"].astype(float),
            merged["price_companion"].astype(float),
            equal_nan=True,
        )
    ]
    return pd.DataFrame(
        [
            {
                "comparison_name": "authoritative_vs_companion_quarterhour",
                "authoritative_rows": int(authoritative.shape[0]),
                "companion_rows": int(companion.shape[0]),
                "same_row_count": bool(authoritative.shape[0] == companion.shape[0]),
                "same_min_timestamp": bool(authoritative["timestamp_utc"].min() == companion["timestamp_utc"].min()),
                "same_max_timestamp": bool(authoritative["timestamp_utc"].max() == companion["timestamp_utc"].max()),
                "timestamps_only_in_authoritative": int((merged["_merge"] == "left_only").sum()),
                "timestamps_only_in_companion": int((merged["_merge"] == "right_only").sum()),
                "shared_timestamps_with_price_mismatch": int(price_mismatch.shape[0]),
                "notes": "The shared cleaned quarterly source remains authoritative; the companion path is audited for equivalence.",
            }
        ]
    )


def _build_hour_group_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for hour_start_utc, group in frame.groupby("hour_start_utc", sort=True):
        quarter_values = sorted(group["quarter_index"].astype(int).tolist())
        rows.append(
            {
                "hour_start_utc": pd.Timestamp(hour_start_utc).isoformat(),
                "hour_start_local": pd.Timestamp(group["hour_start_local"].iloc[0]).isoformat(),
                "hour_local_date": str(group["hour_local_date"].iloc[0]),
                "local_hour_of_day": int(group["local_hour_of_day"].iloc[0]),
                "row_count": int(group.shape[0]),
                "non_missing_price_count": int(group["price_eur_per_mwh"].notna().sum()),
                "missing_price_count": int(group["price_eur_per_mwh"].isna().sum()),
                "interpolated_point_count": int(group["is_interpolated_value"].sum()),
                "flagged_missing_point_count": int(group["is_flagged_missing_value"].sum()),
                "has_duplicate_quarter_index": bool(pd.Series(quarter_values).duplicated().any()),
                "quarter_index_pattern": ",".join(str(value) for value in quarter_values),
            }
        )
    summary = pd.DataFrame(rows)
    summary["is_complete_4q_group"] = (
        summary["row_count"].eq(4)
        & summary["non_missing_price_count"].eq(4)
        & summary["has_duplicate_quarter_index"].eq(False)
        & summary["quarter_index_pattern"].eq("1,2,3,4")
    )
    summary["hour_group_quality"] = np.select(
        [
            summary["is_complete_4q_group"] & summary["interpolated_point_count"].eq(0),
            summary["is_complete_4q_group"] & summary["interpolated_point_count"].gt(0),
        ],
        [
            "complete_observed",
            "complete_with_interpolation",
        ],
        default="incomplete_or_missing",
    )
    return summary.sort_values("hour_start_utc").reset_index(drop=True)


def _build_shape_target_long(frame: pd.DataFrame, hour_group_summary: pd.DataFrame) -> pd.DataFrame:
    complete_hours = hour_group_summary[hour_group_summary["is_complete_4q_group"]].copy()
    complete_hours["hour_start_utc"] = pd.to_datetime(complete_hours["hour_start_utc"], utc=True)
    working = frame.merge(
        complete_hours[
            [
                "hour_start_utc",
                "is_complete_4q_group",
                "hour_group_quality",
                "interpolated_point_count",
                "flagged_missing_point_count",
            ]
        ],
        on="hour_start_utc",
        how="inner",
    ).copy()
    working["hourly_mean_eur_per_mwh"] = working.groupby("hour_start_utc")["price_eur_per_mwh"].transform("mean")
    working["delta_eur_per_mwh"] = working["price_eur_per_mwh"] - working["hourly_mean_eur_per_mwh"]
    working["abs_delta_eur_per_mwh"] = working["delta_eur_per_mwh"].abs()
    working["hour_contains_interpolation"] = working["interpolated_point_count"].gt(0)
    working["hour_contains_flagged_missing"] = working["flagged_missing_point_count"].gt(0)
    delta_mean_check = working.groupby("hour_start_utc")["delta_eur_per_mwh"].transform("mean")
    working["delta_zero_mean_check_abs"] = delta_mean_check.abs()
    column_order = [
        "timestamp_utc",
        "timestamp_local",
        "delivery_local_date",
        "hour_start_utc",
        "hour_start_local",
        "hour_local_date",
        "local_hour_of_day",
        "local_minute",
        "quarter_index",
        "price_eur_per_mwh",
        "hourly_mean_eur_per_mwh",
        "delta_eur_per_mwh",
        "abs_delta_eur_per_mwh",
        "price_eur_per_mwh_original",
        "gap_fix_action",
        "is_interpolated_value",
        "is_flagged_missing_value",
        "missing_datapoint_source",
        "hour_group_quality",
        "hour_contains_interpolation",
        "hour_contains_flagged_missing",
        "delta_zero_mean_check_abs",
    ]
    return working[column_order].sort_values(["hour_start_utc", "quarter_index"]).reset_index(drop=True)


def _preferred_split_windows() -> list[EmpiricalSplitWindow]:
    return [
        EmpiricalSplitWindow("train", date(2025, 10, 1), date(2025, 12, 31), "Preferred fixed train window."),
        EmpiricalSplitWindow("validation", date(2026, 1, 1), date(2026, 2, 28), "Preferred fixed validation window."),
        EmpiricalSplitWindow("test", date(2026, 3, 1), date(2026, 4, 30), "Preferred fixed test window."),
    ]


def _select_empirical_split_windows(available_start: date, available_end: date) -> tuple[str, list[EmpiricalSplitWindow]]:
    preferred = _preferred_split_windows()
    preferred_ok = available_start <= preferred[0].start_date and available_end >= preferred[-1].end_date
    if preferred_ok:
        return "preferred_fixed_oct2025_to_apr2026", preferred

    local_days = pd.date_range(start=available_start, end=available_end, freq="D")
    day_count = int(local_days.shape[0])
    if day_count < 90:
        return (
            "smoke_available_only",
            [EmpiricalSplitWindow("smoke_available", available_start, available_end, "Observed range is too short for a full train/validation/test split.")],
        )

    train_days = max(int(round(day_count * 0.60)), 1)
    validation_days = max(int(round(day_count * 0.20)), 1)
    test_days = day_count - train_days - validation_days
    if test_days <= 0:
        test_days = 1
        train_days = max(train_days - 1, 1)
    train_end = (local_days[train_days - 1]).date()
    validation_start = (local_days[train_days]).date()
    validation_end = (local_days[train_days + validation_days - 1]).date()
    test_start = (local_days[train_days + validation_days]).date()
    test_end = available_end
    return (
        "chronological_ratio_fallback",
        [
            EmpiricalSplitWindow("train", available_start, train_end, "Chronological ratio fallback train window."),
            EmpiricalSplitWindow("validation", validation_start, validation_end, "Chronological ratio fallback validation window."),
            EmpiricalSplitWindow("test", test_start, test_end, "Chronological ratio fallback test window."),
        ],
    )


def _apply_split_labels(shape_target_long: pd.DataFrame, windows: list[EmpiricalSplitWindow]) -> pd.DataFrame:
    working = shape_target_long.copy()
    working["dataset_split"] = "outside_defined_window"
    for window in windows:
        mask = (
            (working["delivery_local_date"] >= window.start_date)
            & (working["delivery_local_date"] <= window.end_date)
        )
        working.loc[mask, "dataset_split"] = window.split
    return working


def _split_summary(
    *,
    full_frame: pd.DataFrame,
    hour_group_summary: pd.DataFrame,
    windows: list[EmpiricalSplitWindow],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window in windows:
        full_mask = (full_frame["delivery_local_date"] >= window.start_date) & (full_frame["delivery_local_date"] <= window.end_date)
        full_slice = full_frame.loc[full_mask].copy()
        hour_mask = (
            pd.to_datetime(hour_group_summary["hour_local_date"]).dt.date >= window.start_date
        ) & (
            pd.to_datetime(hour_group_summary["hour_local_date"]).dt.date <= window.end_date
        )
        hour_slice = hour_group_summary.loc[hour_mask].copy()
        rows.append(
            {
                "split": window.split,
                "start_date": window.start_date.isoformat(),
                "end_date": window.end_date.isoformat(),
                "notes": window.notes,
                "number_of_days": int((window.end_date - window.start_date).days + 1),
                "number_of_quarterhours": int(full_slice.shape[0]),
                "number_of_complete_4q_groups": int(hour_slice["is_complete_4q_group"].sum()),
                "model_ready_quarterhours": int(hour_slice["is_complete_4q_group"].sum() * 4),
                "excluded_incomplete_groups": int((~hour_slice["is_complete_4q_group"]).sum()),
                "complete_groups_with_interpolation": int(hour_slice["hour_group_quality"].eq("complete_with_interpolation").sum()),
            }
        )
    return pd.DataFrame(rows)


def _quarter_diagnostics(shape_target_long: pd.DataFrame) -> pd.DataFrame:
    grouped = shape_target_long.groupby("quarter_index", sort=True)
    rows: list[dict[str, Any]] = []
    for quarter_index, group in grouped:
        delta = group["delta_eur_per_mwh"].astype(float)
        rows.append(
            {
                "quarter_index": int(quarter_index),
                "mean_delta": float(delta.mean()),
                "std_delta": float(delta.std(ddof=0)),
                "p10_delta": float(delta.quantile(0.10)),
                "p50_delta": float(delta.quantile(0.50)),
                "p90_delta": float(delta.quantile(0.90)),
                "mean_abs_delta": float(delta.abs().mean()),
                "count": int(delta.shape[0]),
            }
        )
    return pd.DataFrame(rows).sort_values("quarter_index").reset_index(drop=True)


def _hour_quarter_diagnostics(shape_target_long: pd.DataFrame) -> pd.DataFrame:
    grouped = shape_target_long.groupby(["local_hour_of_day", "quarter_index"], sort=True)
    rows: list[dict[str, Any]] = []
    for (hour_of_day, quarter_index), group in grouped:
        delta = group["delta_eur_per_mwh"].astype(float)
        rows.append(
            {
                "local_hour_of_day": int(hour_of_day),
                "quarter_index": int(quarter_index),
                "mean_delta": float(delta.mean()),
                "mean_abs_delta": float(delta.abs().mean()),
                "std_delta": float(delta.std(ddof=0)),
                "count": int(delta.shape[0]),
            }
        )
    return pd.DataFrame(rows).sort_values(["local_hour_of_day", "quarter_index"]).reset_index(drop=True)


def run_phase02_shape_targets(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase02_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    authority = _read_phase01_authority(config)
    authoritative_path = Path(authority["authoritative_quarterhour_path"])
    companion_path = Path(authority["companion_quarterhour_path"])

    authoritative = _load_quarterhour_source(authoritative_path, timezone=config.business_timezone)
    companion = _load_quarterhour_source(companion_path, timezone=config.business_timezone) if companion_path.exists() else pd.DataFrame()

    source_availability = pd.concat(
        [
            _source_availability_summary(authoritative, dataset_name="quarterhour_authoritative_shared"),
            _source_availability_summary(companion, dataset_name="quarterhour_companion_dedicated") if not companion.empty else pd.DataFrame(),
        ],
        ignore_index=True,
    )
    source_availability.to_csv(run_dir / "source_availability_summary.csv", index=False)

    consistency_summary = _source_consistency_summary(authoritative, companion)
    consistency_summary.to_csv(run_dir / "source_consistency_summary.csv", index=False)

    hour_group_summary = _build_hour_group_summary(authoritative)
    hour_group_summary.to_csv(run_dir / "hour_group_summary.csv", index=False)

    shape_target_long = _build_shape_target_long(authoritative, hour_group_summary)
    available_start = min(shape_target_long["delivery_local_date"])
    available_end = max(shape_target_long["delivery_local_date"])
    split_policy, split_windows = _select_empirical_split_windows(available_start, available_end)
    shape_target_long = _apply_split_labels(shape_target_long, split_windows)
    shape_target_long.to_csv(run_dir / "shape_target_long.csv", index=False)

    split_summary = _split_summary(full_frame=authoritative, hour_group_summary=hour_group_summary, windows=split_windows)
    split_summary.to_csv(run_dir / "split_summary.csv", index=False)

    quarter_diag = _quarter_diagnostics(shape_target_long)
    quarter_diag.to_csv(run_dir / "quarter_diagnostics.csv", index=False)

    hour_quarter_diag = _hour_quarter_diagnostics(shape_target_long)
    hour_quarter_diag.to_csv(run_dir / "hour_quarter_diagnostics.csv", index=False)

    zero_mean_max_abs = float(shape_target_long.groupby("hour_start_utc")["delta_eur_per_mwh"].mean().abs().max())
    run_summary = {
        "run_id": run_id,
        "phase": "phase02_shape_targets",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase01_run_dir": authority["phase01_run_dir"],
        "authoritative_quarterhour_path": str(authoritative_path),
        "companion_quarterhour_path": str(companion_path),
        "split_policy": split_policy,
        "split_windows": [
            {
                "split": window.split,
                "start_date": window.start_date.isoformat(),
                "end_date": window.end_date.isoformat(),
                "notes": window.notes,
            }
            for window in split_windows
        ],
        "shape_target_rows": int(shape_target_long.shape[0]),
        "complete_hour_groups": int(hour_group_summary["is_complete_4q_group"].sum()),
        "excluded_incomplete_hour_groups": int((~hour_group_summary["is_complete_4q_group"]).sum()),
        "complete_groups_with_interpolation": int(hour_group_summary["hour_group_quality"].eq("complete_with_interpolation").sum()),
        "observed_local_start_date": available_start.isoformat(),
        "observed_local_end_date": available_end.isoformat(),
        "zero_mean_check_max_abs_error": zero_mean_max_abs,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
