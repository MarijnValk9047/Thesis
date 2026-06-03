from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .lago_lear_config import LagoLearBenchmarkConfig


@dataclass(frozen=True)
class LagoDataBundle:
    price_frame: pd.DataFrame
    exogenous_frames: dict[str, pd.DataFrame]
    source_root_used: str
    coverage_summary: pd.DataFrame
    complete_index_audit: pd.DataFrame
    target_truth_audit: pd.DataFrame


def _candidate_roots(config: LagoLearBenchmarkConfig) -> list[Path]:
    roots: list[Path] = []
    if config.staged_cleaned_root.exists():
        roots.append(config.staged_cleaned_root)
    if config.allow_official_cleaned_fallback:
        roots.append(config.official_cleaned_root)
    if not roots:
        roots.append(config.staged_cleaned_root)
    return roots


def _resolve_existing_path(candidate_paths: list[Path]) -> Path | None:
    for path in candidate_paths:
        if path.exists():
            return path
    return None


def _load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in frame.columns:
        if column.endswith("_utc"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    return frame


def _normalize_market_region(frame: pd.DataFrame, target_region: str) -> pd.DataFrame:
    normalized = frame.copy()
    if "market" in normalized.columns:
        normalized["region"] = normalized["market"]
    if "region" in normalized.columns:
        normalized = normalized[normalized["region"].astype(str) == str(target_region)].copy()
    return normalized.reset_index(drop=True)


def _with_local_delivery_columns(frame: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    normalized = normalized.dropna(subset=["timestamp_utc"]).copy()
    normalized["timestamp_local"] = normalized["timestamp_utc"].dt.tz_convert(config.local_timezone)
    normalized["target_delivery_local_date"] = normalized["timestamp_local"].dt.date
    normalized["target_hour_local"] = normalized["timestamp_local"].dt.hour.astype("Int64")
    normalized["known_at_utc"] = [
        config.forecast_origin_utc_for_delivery_day(local_day)
        for local_day in normalized["target_delivery_local_date"].tolist()
    ]
    return normalized


def construct_local_delivery_days(config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    rows = [{"delivery_local_date": value.isoformat()} for value in config.benchmark_delivery_days()]
    return pd.DataFrame(rows)


def make_hourly_complete_index(config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for local_day in config.benchmark_delivery_days():
        start_utc, end_utc = config.local_day_utc_bounds(local_day)
        utc_index = pd.date_range(start=start_utc, end=end_utc, freq="h", inclusive="left", tz="UTC")
        expected_hours = int(len(utc_index))
        for idx, timestamp_utc in enumerate(utc_index, start=1):
            rows.append(
                {
                    "target_delivery_local_date": local_day.isoformat(),
                    "target_timestamp_utc": timestamp_utc,
                    "target_hour_local": int(timestamp_utc.tz_convert(config.local_timezone).hour),
                    "position_in_local_day": int(idx),
                    "expected_hours_in_local_day": int(expected_hours),
                }
            )
    return pd.DataFrame(rows)


def load_lago_price_frame(config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    roots = _candidate_roots(config)
    candidate_paths: list[Path] = []
    for root in roots:
        candidate_paths.extend(
            [
                root / "Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv",
                root / "Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
            ]
        )
    resolved = _resolve_existing_path(candidate_paths)
    if resolved is None:
        raise FileNotFoundError(
            "Could not find staged or fallback hourly NL DA price files. "
            f"Checked: {[str(path) for path in candidate_paths]}"
        )

    frame = _load_csv(resolved)
    frame = _normalize_market_region(frame, config.target_region)
    if "price_eur_per_mwh" not in frame.columns:
        raise ValueError(f"Missing price column in {resolved}")
    frame = _with_local_delivery_columns(frame.rename(columns={"timestamp_utc": "timestamp_utc"}), config)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    frame["source_dataset_path"] = str(resolved)
    return frame


def _load_family_with_fallback(
    config: LagoLearBenchmarkConfig,
    relative_paths: list[Path],
) -> tuple[pd.DataFrame, Path | None]:
    for root in _candidate_roots(config):
        for relative_path in relative_paths:
            path = root / relative_path
            if path.exists():
                frame = _load_csv(path)
                return frame, path
    return pd.DataFrame(), None


def load_lago_exogenous_frames(config: LagoLearBenchmarkConfig) -> dict[str, pd.DataFrame]:
    family_paths = {
        "da_total_load_forecast": [
            Path("Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv"),
        ],
        "week_ahead_total_load_forecast": [
            Path("Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv"),
        ],
        "da_generation_forecast": [
            Path("Generation/da_generation_forecast/hourly/da_generation_forecast_hourly_long.csv"),
        ],
        "da_res_generation_forecast": [
            Path("Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv"),
            Path("Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_long.csv"),
        ],
        "da_res_generation_forecast_by_psr": [
            Path("Generation/da_res_generation_forecast_by_psr/hourly/da_res_generation_forecast_by_psr_hourly_feature_ready_long.csv"),
            Path("Generation/da_res_generation_forecast_by_psr/hourly/da_res_generation_forecast_by_psr_hourly_long.csv"),
        ],
        "actual_generation_by_psr": [
            Path("Generation/actual_generation_by_psr/hourly/actual_generation_by_psr_hourly_long.csv"),
        ],
        "installed_capacity_by_psr": [
            Path("Generation/installed_capacity_by_psr/hourly/installed_capacity_by_psr_hourly_long.csv"),
        ],
    }

    out: dict[str, pd.DataFrame] = {}
    for family_name, rel_paths in family_paths.items():
        frame, source_path = _load_family_with_fallback(config, rel_paths)
        if frame.empty:
            out[family_name] = frame
            continue
        frame = _normalize_market_region(frame, config.target_region)
        timestamp_col = "timestamp_utc" if "timestamp_utc" in frame.columns else None
        if timestamp_col is None:
            out[family_name] = pd.DataFrame()
            continue
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp_utc"]).copy()
        if "known_at_utc" in frame.columns:
            frame["known_at_utc"] = pd.to_datetime(frame["known_at_utc"], utc=True, errors="coerce")
        frame["source_dataset_path"] = str(source_path) if source_path is not None else None
        if family_name == "da_res_generation_forecast" and source_path is not None and "feature_ready" not in str(source_path):
            logging.warning(
                "Falling back to strict RES aggregate file for x2: %s. Feature-ready file not found.",
                source_path,
            )
        if family_name == "da_res_generation_forecast_by_psr" and source_path is not None and "feature_ready" not in str(source_path):
            logging.warning(
                "Falling back to strict RES by-PSR file for x2 diagnostics: %s. Feature-ready file not found.",
                source_path,
            )
        frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
        out[family_name] = frame
    return out


def filter_observed_targets(price_df: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    frame = price_df.copy()
    if config.exclude_interpolated_targets:
        if "is_interpolated_value" in frame.columns:
            frame = frame[~frame["is_interpolated_value"].fillna(False).astype(bool)].copy()
        if "is_flagged_missing_value" in frame.columns:
            frame = frame[~frame["is_flagged_missing_value"].fillna(False).astype(bool)].copy()
    frame = frame[frame["price_eur_per_mwh"].notna()].copy()
    return frame.reset_index(drop=True)


def _within_benchmark_period(frame: pd.DataFrame, config: LagoLearBenchmarkConfig) -> pd.DataFrame:
    filtered = frame.copy()
    if "target_delivery_local_date" not in filtered.columns:
        filtered["timestamp_local"] = pd.to_datetime(filtered["timestamp_utc"], utc=True).dt.tz_convert(config.local_timezone)
        filtered["target_delivery_local_date"] = filtered["timestamp_local"].dt.date
    mask = (
        (filtered["target_delivery_local_date"] >= config.benchmark_start_local_date)
        & (filtered["target_delivery_local_date"] < config.benchmark_end_exclusive_local_date)
    )
    return filtered[mask].copy().reset_index(drop=True)


def audit_lago_data_coverage(config: LagoLearBenchmarkConfig) -> LagoDataBundle:
    price_full = load_lago_price_frame(config)
    price_in_period = _within_benchmark_period(price_full, config)
    price_observed = filter_observed_targets(price_in_period, config)
    exogenous = load_lago_exogenous_frames(config)
    complete_index = make_hourly_complete_index(config)

    coverage_rows: list[dict[str, Any]] = []
    coverage_rows.append(
        {
            "dataset_name": "price_full",
            "rows": int(price_full.shape[0]),
            "min_timestamp_utc": price_full["timestamp_utc"].min().isoformat() if not price_full.empty else None,
            "max_timestamp_utc": price_full["timestamp_utc"].max().isoformat() if not price_full.empty else None,
            "source_path": str(price_full["source_dataset_path"].iloc[0]) if not price_full.empty else None,
        }
    )
    coverage_rows.append(
        {
            "dataset_name": "price_observed_benchmark_period",
            "rows": int(price_observed.shape[0]),
            "min_timestamp_utc": price_observed["timestamp_utc"].min().isoformat() if not price_observed.empty else None,
            "max_timestamp_utc": price_observed["timestamp_utc"].max().isoformat() if not price_observed.empty else None,
            "source_path": str(price_observed["source_dataset_path"].iloc[0]) if not price_observed.empty else None,
        }
    )
    for family_name, frame in exogenous.items():
        coverage_rows.append(
            {
                "dataset_name": family_name,
                "rows": int(frame.shape[0]),
                "min_timestamp_utc": frame["timestamp_utc"].min().isoformat() if (not frame.empty and "timestamp_utc" in frame.columns) else None,
                "max_timestamp_utc": frame["timestamp_utc"].max().isoformat() if (not frame.empty and "timestamp_utc" in frame.columns) else None,
                "source_path": str(frame["source_dataset_path"].iloc[0]) if (not frame.empty and "source_dataset_path" in frame.columns) else None,
            }
        )

    observed_targets = price_observed[["timestamp_utc", "target_delivery_local_date"]].copy()
    observed_targets["is_observed_target"] = True
    complete_index_norm = complete_index.rename(columns={"target_timestamp_utc": "timestamp_utc"})
    truth_audit = complete_index_norm.merge(observed_targets[["timestamp_utc", "is_observed_target"]], on="timestamp_utc", how="left")
    truth_audit["is_observed_target"] = truth_audit["is_observed_target"].fillna(False).astype(bool)

    complete_index_audit = (
        truth_audit.groupby("target_delivery_local_date", as_index=False)
        .agg(
            expected_hours=("expected_hours_in_local_day", "max"),
            observed_hours=("is_observed_target", "sum"),
        )
        .assign(observed_coverage_pct=lambda frame: frame["observed_hours"] / frame["expected_hours"] * 100.0)
    )

    source_root = "staged_cleaned_root" if config.staged_cleaned_root.exists() else "official_cleaned_root"
    return LagoDataBundle(
        price_frame=price_observed,
        exogenous_frames=exogenous,
        source_root_used=source_root,
        coverage_summary=pd.DataFrame(coverage_rows),
        complete_index_audit=complete_index_audit,
        target_truth_audit=truth_audit.sort_values("timestamp_utc").reset_index(drop=True),
    )


def write_data_audit_artifacts(config: LagoLearBenchmarkConfig, output_dir: Path) -> LagoDataBundle:
    bundle = audit_lago_data_coverage(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle.coverage_summary.to_csv(output_dir / "data_coverage_summary.csv", index=False)
    bundle.complete_index_audit.to_csv(output_dir / "complete_index_audit.csv", index=False)
    bundle.target_truth_audit.to_csv(output_dir / "target_truth_audit.csv", index=False)
    pd.DataFrame(
        [{"source_root_used": bundle.source_root_used, "allow_official_cleaned_fallback": bool(config.allow_official_cleaned_fallback)}]
    ).to_csv(output_dir / "data_sources.csv", index=False)
    construct_local_delivery_days(config).to_csv(output_dir / "benchmark_delivery_days.csv", index=False)
    return bundle
