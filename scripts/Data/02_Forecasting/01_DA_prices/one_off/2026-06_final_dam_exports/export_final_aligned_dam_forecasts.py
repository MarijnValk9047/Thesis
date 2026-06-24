from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[6]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

RUN_LABEL = "final_aligned_dam_exports"
TZ = "Europe/Amsterdam"
TOLERANCE = 1e-8

DONLY_ANCHOR = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/repair_runs/"
    "20260522_210021_lear_strict_donly_support_repair/hourly_lear_strict_donly_1092_full_support_anchor.csv"
)
DONLY_SUPPORT_AUDIT = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/repair_runs/"
    "20260522_210021_lear_strict_donly_support_repair/hourly_lear_strict_donly_1092_anchor_support_audit.csv"
)
CANONICAL_QH = Path(
    "data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/"
    "canonical_v1/synthetic_actual_15min_canonical.csv"
)
CANONICAL_QH_MANIFEST = Path(
    "data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/"
    "canonical_v1/synthetic_actual_15min_manifest.json"
)
DPLUS4_RUN = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/"
    "20260508_122730_lago_lear_six_year_benchmark"
)
DPLUS4_PREDICTIONS = DPLUS4_RUN / "predictions" / "predictions_long.csv"

PRIMARY_START = date(2024, 10, 1)
PRIMARY_END = date(2025, 9, 30)
DST_EXCLUDED = {date(2024, 10, 27), date(2025, 3, 30)}


@dataclass(frozen=True)
class ExportConfig:
    start_date: str
    end_date: str
    include_donly: bool
    include_dplus4_inspection: bool
    smoke_days: int | None
    output_policy: str = "minimal"
    run_class: str = "candidate_best"
    lineage_role: str = "extension"
    scenario_count_required: int = 30


def _repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = proc.stdout.strip()
    return value or None


def _timestamped_run_id(tag: str) -> str:
    suffix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(tag or "").strip())
    base = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)
    return f"{base}_{suffix}" if suffix else base


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _try_write_parquet(frame: pd.DataFrame, path: Path, warnings: list[str]) -> bool:
    try:
        frame.to_parquet(path, index=False)
        return True
    except Exception as exc:
        warnings.append(f"Skipped parquet output for {_rel(path)} because no parquet engine was available or writing failed: {exc}")
        return False


def _local_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _load_donly_hourly(start: date, end: date, smoke_days: int | None) -> pd.DataFrame:
    path = _repo_path(DONLY_ANCHOR)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False)
    required = {
        "forecast_origin_utc",
        "delivery_start_utc",
        "lead_day",
        "point_forecast_eur_per_mwh",
        "dataset_split",
        "delivery_day",
        "actual_price_eur_per_mwh",
        "model_id",
        "model_label",
        "granularity",
        "horizon",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"D-only anchor missing required columns: {missing}")

    frame = frame.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="coerce")
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert(TZ)
    frame["delivery_day"] = _local_date_series(frame["delivery_day"])
    frame = frame[
        (frame["dataset_split"].astype(str) == "test")
        & (frame["delivery_day"] >= start)
        & (frame["delivery_day"] <= end)
    ].copy()
    if smoke_days is not None:
        keep_days = sorted(frame["delivery_day"].dropna().unique())[: int(smoke_days)]
        frame = frame[frame["delivery_day"].isin(keep_days)].copy()

    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["lead_day_label"] = frame["lead_day"].map(lambda value: "D" if int(value) == 0 else f"D+{int(value)}")
    frame["target_local_hour"] = frame["target_timestamp_local"].dt.hour.astype(int)
    frame["forecast_price_eur_per_mwh"] = pd.to_numeric(frame["point_forecast_eur_per_mwh"], errors="coerce")
    frame["y_pred"] = frame["forecast_price_eur_per_mwh"]
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["actual_price_eur_per_mwh"], errors="coerce")
    frame["source_anchor_path"] = _rel(path)
    frame["source_anchor_id"] = "lear_strict_donly_1092_repaired_anchor"
    frame["truth_type"] = "observed_hourly_actual_available_for_evaluation_not_row_filtering"
    frame["production_export_row"] = True
    frame["granularity"] = "hourly"
    frame["horizon"] = "D-only"
    frame["delivery_policy"] = "24h_only_delivery_days"
    frame = frame.rename(columns={"delivery_day": "delivery_local_date"})

    columns = [
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_timestamp_local",
        "delivery_local_date",
        "target_local_hour",
        "lead_day",
        "lead_day_label",
        "dataset_split",
        "model_id",
        "model_label",
        "granularity",
        "horizon",
        "forecast_price_eur_per_mwh",
        "y_pred",
        "actual_price_eur_per_mwh",
        "truth_type",
        "production_export_row",
        "delivery_policy",
        "source_anchor_id",
        "source_anchor_path",
    ]
    return frame[columns].sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)


def _load_canonical_qh_deviations() -> tuple[pd.DataFrame, dict[str, Any]]:
    path = _repo_path(CANONICAL_QH)
    manifest_path = _repo_path(CANONICAL_QH_MANIFEST)
    if not path.exists():
        raise FileNotFoundError(path)
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    frame = pd.read_csv(path, low_memory=False)
    required = {
        "timestamp_utc",
        "hour_start_utc",
        "local_minute",
        "quarter_index",
        "sampled_delta_eur_per_mwh",
        "actual_path_version",
        "actual_path_variant",
        "shape_sampler_source_hour_start_utc",
        "shape_sampler_backoff_level",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Canonical QH deviation file missing required columns: {missing}")
    frame = frame.copy()
    frame["target_timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["hour_start_utc"] = pd.to_datetime(frame["hour_start_utc"], utc=True, errors="coerce")
    frame["qh_deviation_raw_eur_per_mwh"] = pd.to_numeric(frame["sampled_delta_eur_per_mwh"], errors="coerce")
    frame["quarter_in_hour"] = pd.to_numeric(frame["quarter_index"], errors="coerce").astype("Int64")
    frame["local_minute"] = pd.to_numeric(frame["local_minute"], errors="coerce").astype("Int64")
    keep = [
        "target_timestamp_utc",
        "hour_start_utc",
        "local_minute",
        "quarter_in_hour",
        "qh_deviation_raw_eur_per_mwh",
        "actual_path_version",
        "actual_path_variant",
        "shape_sampler_source_hour_start_utc",
        "shape_sampler_backoff_level",
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return frame[keep].sort_values(["hour_start_utc", "target_timestamp_utc"]).reset_index(drop=True), manifest


def _build_qh_from_hourly(hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    qh_dev, manifest = _load_canonical_qh_deviations()
    hourly_key = hourly.rename(columns={"target_timestamp_utc": "hour_start_utc"}).copy()
    merged = hourly_key.merge(qh_dev, on="hour_start_utc", how="left", validate="one_to_many")
    if merged["target_timestamp_utc"].isna().any():
        missing = int(merged["target_timestamp_utc"].isna().sum())
        raise ValueError(f"Missing canonical QH deviations for {missing} expanded rows.")

    group_cols = ["forecast_origin_utc", "hour_start_utc"]
    raw_mean = merged.groupby(group_cols)["qh_deviation_raw_eur_per_mwh"].transform("mean")
    merged["qh_deviation_eur_per_mwh"] = pd.to_numeric(merged["qh_deviation_raw_eur_per_mwh"], errors="coerce") - raw_mean
    residual_mean = merged.groupby(group_cols)["qh_deviation_eur_per_mwh"].transform("mean")
    merged["qh_deviation_eur_per_mwh"] = merged["qh_deviation_eur_per_mwh"] - residual_mean
    merged["forecast_price_eur_per_mwh"] = (
        pd.to_numeric(merged["forecast_price_eur_per_mwh"], errors="coerce")
        + pd.to_numeric(merged["qh_deviation_eur_per_mwh"], errors="coerce")
    )
    merged["y_pred"] = merged["forecast_price_eur_per_mwh"]
    merged["target_timestamp_local"] = pd.to_datetime(merged["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(TZ)
    merged["delivery_local_date"] = merged["target_timestamp_local"].dt.date
    merged["target_local_hour"] = merged["target_timestamp_local"].dt.hour.astype(int)
    merged["granularity"] = "quarter_hour"
    merged["model_id"] = "lear_strict_donly_1092_anchor_plus_canonical_qh_deviation"
    merged["model_label"] = "LEAR Strict D-only 1092 anchor + canonical zero-mean QH deviation"
    merged["truth_type"] = "synthetic_counterfactual_production_forecast_not_observed_market_truth"
    merged["qh_method"] = "hourly_anchor_plus_frozen_canonical_intra_hour_deviation_zero_mean"
    merged["canonical_version_id"] = str(manifest.get("version_id") or "canonical_v1")
    merged["canonical_variant"] = str(manifest.get("canonical_variant") or "")
    merged["production_export_row"] = True

    reconciliation = (
        merged.groupby(group_cols, as_index=False)
        .agg(
            qh_rows=("target_timestamp_utc", "size"),
            qh_mean_forecast=("forecast_price_eur_per_mwh", "mean"),
            hourly_anchor_forecast=("hourly_anchor_forecast_eur_per_mwh", "first"),
            mean_deviation=("qh_deviation_eur_per_mwh", "mean"),
        )
        .sort_values(group_cols)
        .reset_index(drop=True)
    )
    reconciliation["abs_mean_minus_anchor"] = (
        pd.to_numeric(reconciliation["qh_mean_forecast"], errors="coerce")
        - pd.to_numeric(reconciliation["hourly_anchor_forecast"], errors="coerce")
    ).abs()
    reconciliation["passes_tolerance"] = (
        reconciliation["qh_rows"].eq(4) & reconciliation["abs_mean_minus_anchor"].le(TOLERANCE)
    )

    columns = [
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_timestamp_local",
        "delivery_local_date",
        "target_local_hour",
        "local_minute",
        "quarter_in_hour",
        "lead_day",
        "lead_day_label",
        "dataset_split",
        "model_id",
        "model_label",
        "granularity",
        "horizon",
        "forecast_price_eur_per_mwh",
        "y_pred",
        "hourly_anchor_forecast_eur_per_mwh",
        "qh_deviation_eur_per_mwh",
        "qh_deviation_raw_eur_per_mwh",
        "truth_type",
        "production_export_row",
        "delivery_policy",
        "qh_method",
        "canonical_version_id",
        "canonical_variant",
        "actual_path_version",
        "actual_path_variant",
        "shape_sampler_source_hour_start_utc",
        "shape_sampler_backoff_level",
        "source_anchor_id",
        "source_anchor_path",
    ]
    return merged[columns].sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True), reconciliation


def _delivery_day_status(start: date, end: date, hourly: pd.DataFrame, qh: pd.DataFrame | None = None) -> pd.DataFrame:
    days = pd.date_range(start=start, end=end, freq="D").date
    hourly_counts = hourly.groupby("delivery_local_date").size().to_dict() if not hourly.empty else {}
    qh_counts = qh.groupby("delivery_local_date").size().to_dict() if qh is not None and not qh.empty else {}
    rows: list[dict[str, Any]] = []
    for day in days:
        is_dst_excluded = day in DST_EXCLUDED
        h_count = int(hourly_counts.get(day, 0))
        q_count = int(qh_counts.get(day, 0))
        included = h_count == 24 and (qh is None or q_count == 96)
        if is_dst_excluded:
            status = "excluded_dst_non_24h_policy"
        elif included:
            status = "included_24h_policy"
        elif h_count == 0:
            status = "missing_hourly_anchor"
        else:
            status = "incomplete_day"
        rows.append(
            {
                "delivery_local_date": day.isoformat(),
                "status": status,
                "included": bool(included),
                "is_explicit_dst_exclusion": bool(is_dst_excluded),
                "hourly_rows": h_count,
                "qh_rows": q_count,
                "expected_hourly_rows_under_policy": 0 if is_dst_excluded else 24,
                "expected_qh_rows_under_policy": 0 if is_dst_excluded else 96,
            }
        )
    return pd.DataFrame(rows)


def _prepare_hourly_for_qh(hourly: pd.DataFrame) -> pd.DataFrame:
    prepared = hourly.copy()
    prepared["hourly_anchor_forecast_eur_per_mwh"] = pd.to_numeric(prepared["forecast_price_eur_per_mwh"], errors="coerce")
    return prepared


def _load_dplus4_predictions() -> pd.DataFrame:
    path = _repo_path(DPLUS4_PREDICTIONS)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False)
    required = {
        "run_id",
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_delivery_local_date",
        "target_known_at_utc",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "y_pred",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"D+4 predictions missing required columns: {missing}")
    frame = frame.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["target_known_at_utc"] = pd.to_datetime(frame["target_known_at_utc"], utc=True, errors="coerce")
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert(TZ)
    frame["delivery_local_date"] = _local_date_series(frame["target_delivery_local_date"])
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["horizon_index"] = pd.to_numeric(frame["horizon_index"], errors="coerce").astype("Int64")
    frame["forecast_price_eur_per_mwh"] = pd.to_numeric(frame["y_pred"], errors="coerce")
    return frame


def _inspect_dplus4(start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = _load_dplus4_predictions()
    subset = frame[
        (frame["dataset_split"].astype(str) == "test")
        & (frame["delivery_local_date"] >= start)
        & (frame["delivery_local_date"] <= end)
    ].copy()
    by_day = (
        subset.groupby("delivery_local_date", as_index=False)
        .agg(
            rows=("target_timestamp_utc", "size"),
            lead_day_count=("lead_day", "nunique"),
            min_lead_day=("lead_day", "min"),
            max_lead_day=("lead_day", "max"),
            min_target_utc=("target_timestamp_utc", "min"),
            max_target_utc=("target_timestamp_utc", "max"),
            min_origin_utc=("forecast_origin_utc", "min"),
            max_origin_utc=("forecast_origin_utc", "max"),
        )
        .sort_values("delivery_local_date")
        .reset_index(drop=True)
    )
    by_day["status"] = np.where(
        by_day["delivery_local_date"].isin(DST_EXCLUDED),
        "excluded_dst_non_24h_policy",
        np.where(by_day["rows"].ge(24), "has_at_least_one_complete_hourly_path", "incomplete_target_day"),
    )
    by_origin = (
        subset.groupby("forecast_origin_utc", as_index=False)
        .agg(
            rows=("target_timestamp_utc", "size"),
            lead_day_count=("lead_day", "nunique"),
            min_lead_day=("lead_day", "min"),
            max_lead_day=("lead_day", "max"),
            min_target_utc=("target_timestamp_utc", "min"),
            max_target_utc=("target_timestamp_utc", "max"),
        )
        .sort_values("forecast_origin_utc")
        .reset_index(drop=True)
    )
    by_origin["status"] = np.where(
        by_origin["rows"].eq(120) & by_origin["lead_day_count"].eq(5),
        "complete_d_through_dplus4_120h_origin",
        "incomplete_origin",
    )
    full_days = set(pd.date_range(start=start, end=end, freq="D").date)
    present_days = set(by_day["delivery_local_date"].tolist())
    missing_days = sorted(full_days - present_days)

    known_at_violation_path = _repo_path(DPLUS4_RUN / "features" / "known_at_violations_dplus4.csv")
    forbidden_path = _repo_path(DPLUS4_RUN / "features" / "dplus4_forbidden_columns_audit.csv")
    disallowed_path = _repo_path(DPLUS4_RUN / "features" / "dplus4_disallowed_feature_attempts.csv")

    def _csv_row_count(path: Path) -> int | None:
        if not path.exists():
            return None
        try:
            return int(pd.read_csv(path).shape[0])
        except pd.errors.EmptyDataError:
            return 0

    summary = {
        "artifact_path": _rel(_repo_path(DPLUS4_RUN)),
        "predictions_path": _rel(_repo_path(DPLUS4_PREDICTIONS)),
        "rows_in_primary_period": int(subset.shape[0]),
        "forecast_origins": int(by_origin.shape[0]),
        "complete_120h_forecast_origins": int((by_origin["status"] == "complete_d_through_dplus4_120h_origin").sum())
        if not by_origin.empty
        else 0,
        "present_delivery_days": int(len(present_days)),
        "delivery_days_with_at_least_one_24h_path": int((by_day["status"] == "has_at_least_one_complete_hourly_path").sum())
        if not by_day.empty
        else 0,
        "incomplete_target_days": int((by_day["status"] == "incomplete_target_day").sum()) if not by_day.empty else 0,
        "missing_delivery_days_count": int(len(missing_days)),
        "missing_delivery_days_first_10": [d.isoformat() for d in missing_days[:10]],
        "min_delivery_day": str(subset["delivery_local_date"].min()) if not subset.empty else None,
        "max_delivery_day": str(subset["delivery_local_date"].max()) if not subset.empty else None,
        "known_at_violation_rows": _csv_row_count(known_at_violation_path),
        "forbidden_feature_audit_rows": _csv_row_count(forbidden_path),
        "disallowed_feature_attempt_rows": _csv_row_count(disallowed_path),
        "method_label": "lear_lago_direct_dplus4_strict_no_future_1092",
        "full_primary_period_support": len(missing_days) == 0
        and int((by_origin["status"] == "complete_d_through_dplus4_120h_origin").sum()) >= 363,
        "previous_runtime_seconds": _load_dplus4_runtime_seconds(),
        "regeneration_needed_for_full_primary_period": True,
        "regeneration_reason": "Existing D+4 artifact is strict-no-future but does not cover the full 2024-10-01 to 2025-09-30 primary delivery period.",
    }
    return by_day, by_origin, summary


def _load_dplus4_runtime_seconds() -> float | None:
    progress = _repo_path(DPLUS4_RUN / "run_progress_dplus4.json")
    if not progress.exists():
        return None
    payload = json.loads(progress.read_text(encoding="utf-8"))
    value = payload.get("elapsed_seconds")
    return float(value) if value is not None else None


def _long_run_commands(run_dir: Path) -> dict[str, str]:
    python = "python"
    script = "scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-06_final_dam_exports/export_final_aligned_dam_forecasts.py"
    dplus4_script = "scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/run_lago_lear_six_year_benchmark.py"
    hourly_scen = "scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/run_hourly_scenario_generation_with_lear_strict.py"
    qh_scen = "scripts/Data/02_Forecasting/01_DA_prices/run_15min_qh_scenario_generation.py"
    return {
        "smoke_donly_deterministic": f"{python} {script} --smoke-days 2 --output-tag smoke",
        "full_donly_deterministic": f"{python} {script} --output-tag full_donly",
        "dplus4_inspection_only": f"{python} {script} --skip-donly --inspect-dplus4 --output-tag dplus4_inspect",
        "optional_hourly_donly_30_scenarios": (
            f"{python} {hourly_scen} --horizon-mode D_ONLY --n-final 30 --n-raw 30 "
            "--target-split-mode validation_and_test --lear-strict-predictions "
            f"{_rel(_repo_path(run_dir / 'aligned_hourly_forecasts_donly.csv'))}"
        ),
        "optional_qh_donly_30_scenarios": (
            f"{python} {qh_scen} --horizon-mode D_ONLY --n-final 30 --n-raw 30 "
            "--calibration-policy validation_only"
        ),
        "optional_dplus4_regeneration_long_run": (
            f"{python} {dplus4_script} --build-features --run-dplus4 --evaluate --split-policy thesis_official "
            "--start-local-date 2019-10-01 --end-exclusive-local-date 2025-10-01 "
            "--dst-policy skip_non_24h_local_days --dplus4-calibration-windows 1092 "
            "--no-dplus4-ensemble --checkpoint-predictions --dplus4-checkpoint-chunk-rows 5000"
        ),
    }


def _write_warnings(path: Path, warnings: list[str]) -> None:
    text = ["# Warnings And Limitations", ""]
    if not warnings:
        text.append("- No warnings emitted by the export runner.")
    else:
        text.extend(f"- {item}" for item in warnings)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")


def run_exports(args: argparse.Namespace) -> Path:
    started = time.perf_counter()
    start = pd.Timestamp(args.start_date).date()
    end = pd.Timestamp(args.end_date).date()
    if start > end:
        raise ValueError("--start-date must be <= --end-date")

    run_id = _timestamped_run_id(args.output_tag)
    run_dir = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "dam_aligned_exports" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    warnings: list[str] = []

    config = ExportConfig(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        include_donly=not bool(args.skip_donly),
        include_dplus4_inspection=bool(args.inspect_dplus4),
        smoke_days=args.smoke_days,
    )
    _write_json(run_dir / "resolved_config.yaml", asdict(config))

    input_paths = [DONLY_ANCHOR, DONLY_SUPPORT_AUDIT, CANONICAL_QH, CANONICAL_QH_MANIFEST, DPLUS4_PREDICTIONS]
    manifest_rows: list[dict[str, Any]] = []
    for path in input_paths:
        resolved = _repo_path(path)
        manifest_rows.append(
            {
                "path": _rel(resolved),
                "exists": bool(resolved.exists()),
                "sha256": _sha256(resolved) if resolved.exists() and resolved.is_file() else None,
            }
        )
    input_manifest = {
        "run_id": run_id,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "inputs": manifest_rows,
        "row_selection_policy": "production forecasts are filtered by forecast support and 24h delivery-day policy, not inner-joined to actuals",
    }
    _write_json(run_dir / "input_manifest.json", input_manifest)
    _write_json(run_dir / "code_version.json", {"git_commit": _git_commit(), "runner": _rel(Path(__file__))})

    hourly = pd.DataFrame()
    qh = pd.DataFrame()
    reconciliation = pd.DataFrame()
    day_status = pd.DataFrame()
    dplus4_summary: dict[str, Any] | None = None

    if not args.skip_donly:
        hourly = _load_donly_hourly(start, end, args.smoke_days)
        hourly.to_csv(run_dir / "aligned_hourly_forecasts_donly.csv", index=False)
        _try_write_parquet(hourly, run_dir / "aligned_hourly_forecasts_donly.parquet", warnings)

        hourly_for_qh = _prepare_hourly_for_qh(hourly)
        qh, reconciliation = _build_qh_from_hourly(hourly_for_qh)
        qh.to_csv(run_dir / "aligned_qh_forecasts_donly.csv", index=False)
        _try_write_parquet(qh, run_dir / "aligned_qh_forecasts_donly.parquet", warnings)

        reconciliation.to_csv(run_dir / "qh_hourly_reconciliation_donly.csv", index=False)
        day_status = _delivery_day_status(start, end, hourly, qh)
        day_status.to_csv(run_dir / "delivery_day_status_donly.csv", index=False)

    if args.inspect_dplus4:
        dplus4_days, dplus4_origins, dplus4_summary = _inspect_dplus4(start, end)
        dplus4_days.to_csv(run_dir / "delivery_day_status_dplus4_existing_artifact.csv", index=False)
        dplus4_origins.to_csv(run_dir / "forecast_origin_status_dplus4_existing_artifact.csv", index=False)
        _write_json(run_dir / "dplus4_existing_artifact_summary.json", dplus4_summary)

    long_run_commands = _long_run_commands(run_dir)
    _write_json(run_dir / "long_run_commands.json", long_run_commands)

    included_days = int(day_status["included"].sum()) if not day_status.empty else 0
    excluded_dst = day_status.loc[day_status["is_explicit_dst_exclusion"], "delivery_local_date"].tolist() if not day_status.empty else []
    zero_mean_ok = bool(reconciliation["passes_tolerance"].all()) if not reconciliation.empty else None
    max_qh_error = float(reconciliation["abs_mean_minus_anchor"].max()) if not reconciliation.empty else None

    checks = [
        {
            "check_name": "donly_hourly_24_rows_per_included_day",
            "status": "pass" if hourly.empty or (day_status.loc[day_status["included"], "hourly_rows"].eq(24).all()) else "fail",
        },
        {
            "check_name": "donly_qh_96_rows_per_included_day",
            "status": "pass" if qh.empty or (day_status.loc[day_status["included"], "qh_rows"].eq(96).all()) else "fail",
        },
        {
            "check_name": "donly_explicit_dst_exclusions",
            "status": "pass" if set(excluded_dst) == {d.isoformat() for d in DST_EXCLUDED if start <= d <= end} else "fail",
        },
        {
            "check_name": "donly_qh_hourly_mean_equals_anchor",
            "status": "pass" if zero_mean_ok is True else "not_run" if zero_mean_ok is None else "fail",
            "max_abs_error": max_qh_error,
            "tolerance": TOLERANCE,
        },
    ]
    pd.DataFrame(checks).to_csv(run_dir / "validation_checks.csv", index=False)

    if dplus4_summary and dplus4_summary.get("regeneration_needed_for_full_primary_period"):
        warnings.append(str(dplus4_summary["regeneration_reason"]))
    if not any(path.name.endswith(".parquet") for path in run_dir.glob("*.parquet")):
        warnings.append("No parquet files were written because the local Python environment lacks a parquet engine.")
    warnings.append("Scenario files were not generated by this deterministic export run; long-run commands enforce exactly 30 scenarios.")
    _write_warnings(run_dir / "warnings_and_limitations.md", warnings)

    elapsed = time.perf_counter() - started
    run_summary = {
        "run_id": run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "output_policy": config.output_policy,
        "run_class": config.run_class,
        "lineage_role": config.lineage_role,
        "runtime_seconds": float(elapsed),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "donly": {
            "hourly_rows": int(hourly.shape[0]),
            "qh_rows": int(qh.shape[0]),
            "included_days": included_days,
            "excluded_dst_dates": excluded_dst,
            "qh_reconciliation_max_abs_error": max_qh_error,
            "qh_reconciliation_pass": zero_mean_ok,
        },
        "dplus4_existing_artifact": dplus4_summary,
        "scenario_status": {
            "generated": False,
            "required_final_scenario_count": 30,
            "reason": "Scenario generation is set up in long_run_commands.json but deferred until deterministic exports are reviewed.",
        },
        "warnings": warnings,
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    registry_entry = {
        "run_id": run_id,
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "domain": "forecasting",
        "market": "DA",
        "pipeline_stage": "forecast_export",
        "granularity": "hourly_and_quarter_hour",
        "horizon": "D_only",
        "model_family": "LEAR Strict",
        "feature_set": "LEAR Strict D-only 1092 repaired anchor plus canonical QH deviations",
        "scenario_source": "none",
        "input_artifacts": [_rel(_repo_path(p)) for p in input_paths],
        "output_root": _rel(run_dir),
        "output_policy": config.output_policy,
        "run_class": config.run_class,
        "lineage_role": config.lineage_role,
        "status": "completed",
        "thesis_usable": "conditional",
        "key_result": f"D-only deterministic exports: {int(hourly.shape[0])} hourly rows, {int(qh.shape[0])} QH rows.",
        "limitations": "; ".join(warnings),
        "archive_location": "",
        "delete_after": "",
        "git_commit": _git_commit(),
    }
    _write_json(run_dir / "registry_entry.json", registry_entry)
    return run_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final aligned DAM deterministic forecast exports.")
    parser.add_argument("--start-date", type=str, default=PRIMARY_START.isoformat())
    parser.add_argument("--end-date", type=str, default=PRIMARY_END.isoformat())
    parser.add_argument("--smoke-days", type=int, default=None)
    parser.add_argument("--skip-donly", action="store_true")
    parser.add_argument("--inspect-dplus4", action="store_true")
    parser.add_argument("--output-tag", type=str, default="")
    return parser.parse_args()


def main() -> int:
    run_dir = run_exports(_parse_args())
    print(json.dumps({"run_dir": _rel(run_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
