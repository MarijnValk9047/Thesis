from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.lago_benchmark_data import load_lago_exogenous_frames
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_lear_model import LagoLearModel
from hourly_da.core.lago_multiday_features import build_lago_dplus4_direct_matrix_strict_no_future


DEFAULT_TARGETS_BY_ORIGIN = Path(
    "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/"
    "20260503_174631_observed_market_deterministic_forecast/targets_by_origin.csv"
)
DEFAULT_OUTPUT_ROOT = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid"
)
DEFAULT_MODEL_WINDOW_DAYS = 1092
RUN_LABEL = "lear_strict_observed_qh_grid_export"
MODEL_FAMILY = "LEAR"
FS_LEVEL = "LAGO"
FEATURE_VARIANT = "LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE"
TARGET_TIMEZONE = "Europe/Amsterdam"
DEFAULT_MARKET_AREA = "NL"
DEFAULT_PHASE07_BRIDGE_NL = Path(
    "data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/"
    "20260505_134716_phase07_realistic_track_a/bridged_hourly_target_input_all_regions.csv"
)


@dataclass(frozen=True)
class ExportPaths:
    run_dir: Path
    predictions_csv: Path
    predictions_parquet: Path
    progress_json: Path
    run_summary_json: Path
    grid_summary_csv: Path
    coverage_summary_csv: Path
    validation_report_json: Path
    runtime_estimate_json: Path
    export_config_json: Path
    checkpoint_dir: Path
    strict_key_level_skip_reasons_csv: Path
    strict_key_level_skip_reason_counts_csv: Path
    strict_key_level_skip_reason_by_split_lead_day_csv: Path
    strict_key_level_skip_reason_by_month_csv: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export LEAR_STRICT hourly anchors on the observed-QH hourly grid (quarter_in_hour == 1)."
    )
    parser.add_argument("--targets-by-origin", type=str, default=str(DEFAULT_TARGETS_BY_ORIGIN))
    parser.add_argument(
        "--output-root",
        type=str,
        default=str(DEFAULT_OUTPUT_ROOT),
    )
    parser.add_argument("--output-tag", type=str, default="")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--estimate-runtime", action="store_true")
    parser.add_argument("--sample-origins", type=int, default=5)
    parser.add_argument("--max-origins", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-dir", type=str, default="")
    parser.add_argument("--run-dir", type=str, default="")
    parser.add_argument(
        "--bridge-source",
        type=str,
        default="observed_run",
        choices=["observed_run", "phase07_nl", "bridge_path"],
    )
    parser.add_argument("--bridge-path", type=str, default="")
    parser.add_argument("--bridge-market-area", type=str, default=DEFAULT_MARKET_AREA)
    parser.add_argument("--window-days", type=int, default=DEFAULT_MODEL_WINDOW_DAYS)
    parser.add_argument("--x2-policy", type=str, default="res_forecast_if_available")
    parser.add_argument("--allow-official-cleaned-fallback", action="store_true")
    parser.add_argument("--checkpoint-flush-rows", type=int, default=500)
    parser.add_argument("--no-parquet", action="store_true")
    parser.add_argument("--log-every-rows", type=int, default=250)
    return parser.parse_args()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _timestamp_now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _iso(ts: pd.Timestamp | None) -> str | None:
    if ts is None:
        return None
    return pd.Timestamp(ts).isoformat()


def _memory_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:
        return None


def _read_targets_by_origin(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"targets_by_origin.csv not found: {path}")
    frame = pd.read_csv(path)
    required = {
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "dataset_split",
        "quarter_in_hour",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"targets_by_origin.csv missing required columns: {missing}")
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["quarter_in_hour"] = pd.to_numeric(frame["quarter_in_hour"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "quarter_in_hour"]).copy()
    frame["lead_day"] = frame["lead_day"].astype(int)
    frame["quarter_in_hour"] = frame["quarter_in_hour"].astype(int)
    return frame


def _build_hourly_anchor_grid(targets_by_origin: pd.DataFrame) -> pd.DataFrame:
    anchor = targets_by_origin[targets_by_origin["quarter_in_hour"].eq(1)].copy()
    anchor = anchor[
        [
            "forecast_origin_utc",
            "target_timestamp_utc",
            "lead_day",
            "dataset_split",
        ]
    ].copy()
    anchor = anchor.drop_duplicates(
        subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"], keep="first"
    ).sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    return anchor


def _apply_origin_limit(grid: pd.DataFrame, max_origins: int | None) -> pd.DataFrame:
    if max_origins is None:
        return grid.copy()
    ordered = (
        grid[["forecast_origin_utc"]]
        .drop_duplicates()
        .sort_values("forecast_origin_utc")
        .head(int(max_origins))
    )
    keep = set(ordered["forecast_origin_utc"].tolist())
    return grid[grid["forecast_origin_utc"].isin(keep)].copy()


def _resolve_horizon_policy_csv() -> Path:
    search_root = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "runs_lago_lear"
    candidates = sorted(
        search_root.glob("settings_availability_audit_*/horizon_allowed_feature_policy.csv"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            "Could not resolve horizon_allowed_feature_policy.csv under runs_lago_lear/settings_availability_audit_*/"
        )
    return candidates[0]


def _resolve_bridge_input(args: argparse.Namespace, targets_path: Path) -> tuple[Path, str]:
    source = str(args.bridge_source or "observed_run").strip()
    explicit = str(args.bridge_path or "").strip()
    if source == "bridge_path":
        if not explicit:
            raise ValueError("--bridge-source bridge_path requires --bridge-path.")
        bridge = (REPO_ROOT / Path(explicit)).resolve()
        if not bridge.exists():
            raise FileNotFoundError(f"Explicit bridge path not found: {bridge}")
        return bridge, "explicit_bridge_path"
    if explicit:
        bridge = (REPO_ROOT / Path(explicit)).resolve()
        if not bridge.exists():
            raise FileNotFoundError(f"Explicit bridge path not found: {bridge}")
        return bridge, "explicit_bridge_path"
    if source == "phase07_nl":
        bridge = (REPO_ROOT / DEFAULT_PHASE07_BRIDGE_NL).resolve()
        if not bridge.exists():
            raise FileNotFoundError(f"Default phase07 NL bridge not found: {bridge}")
        return bridge, "phase07_nl"
    run_dir = targets_path.parent
    bridge = run_dir / "hourly_backbone_bridge_input.csv"
    if not bridge.exists():
        raise FileNotFoundError(f"Bridge hourly input not found beside targets_by_origin.csv: {bridge}")
    return bridge, "observed_run"


def _load_bridge_price_frame(
    bridge_path: Path,
    config: LagoLearBenchmarkConfig,
    *,
    start_local_date: date,
    end_exclusive_local_date: date,
    bridge_source: str,
    market_area: str,
) -> pd.DataFrame:
    frame = pd.read_csv(bridge_path, low_memory=False)
    required = {"timestamp_utc", "price_eur_per_mwh"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Bridge hourly file missing columns {missing}: {bridge_path}")
    if "region" in frame.columns:
        frame = frame[frame["region"].astype(str) == str(market_area)].copy()
    elif bridge_source in {"phase07_nl"}:
        raise ValueError(f"Bridge source '{bridge_source}' requires a region column to filter {market_area}.")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).copy()
    frame["timestamp_local"] = frame["timestamp_utc"].dt.tz_convert(config.local_timezone)
    frame["target_delivery_local_date"] = frame["timestamp_local"].dt.date
    frame["target_hour_local"] = frame["timestamp_local"].dt.hour.astype("Int64")
    frame["known_at_utc"] = frame["target_delivery_local_date"].map(config.forecast_origin_utc_for_delivery_day)

    if "is_interpolated_value" in frame.columns:
        frame = frame[~frame["is_interpolated_value"].fillna(False).astype(bool)].copy()
    if "is_flagged_missing_value" in frame.columns:
        frame = frame[~frame["is_flagged_missing_value"].fillna(False).astype(bool)].copy()
    frame = frame[frame["price_eur_per_mwh"].notna()].copy()

    in_period = (
        (frame["target_delivery_local_date"] >= start_local_date)
        & (frame["target_delivery_local_date"] < end_exclusive_local_date)
    )
    frame = frame[in_period].copy().sort_values("timestamp_utc").reset_index(drop=True)
    return frame


def _bridge_validation_report(
    *,
    bridge_source: str,
    bridge_path: Path,
    market_area: str,
    raw_bridge: pd.DataFrame,
    filtered_bridge: pd.DataFrame,
    anchor_grid: pd.DataFrame,
) -> pd.DataFrame:
    report_rows: list[dict[str, Any]] = []
    raw_ts = pd.to_datetime(raw_bridge.get("timestamp_utc"), utc=True, errors="coerce")
    filt_ts = pd.to_datetime(filtered_bridge.get("timestamp_utc"), utc=True, errors="coerce")
    anchor_ts = pd.to_datetime(anchor_grid["target_timestamp_utc"], utc=True, errors="coerce")
    post_cutoff_utc = pd.Timestamp("2025-10-01", tz=TARGET_TIMEZONE).tz_convert("UTC")

    duplicates_nl = 0
    if {"timestamp_utc", "region"}.issubset(set(raw_bridge.columns)):
        region = raw_bridge["region"].astype(str)
        dups = raw_bridge[region == str(market_area)].duplicated(subset=["timestamp_utc", "region"]).sum()
        duplicates_nl = int(dups)
    elif "timestamp_utc" in raw_bridge.columns:
        duplicates_nl = int(raw_bridge.duplicated(subset=["timestamp_utc"]).sum())

    post_rule_ok = None
    post_rule_detail = ""
    if bridge_source == "phase07_nl":
        if "bridge_source" in raw_bridge.columns:
            post = raw_bridge[
                (pd.to_datetime(raw_bridge["timestamp_utc"], utc=True, errors="coerce") >= post_cutoff_utc)
                & (raw_bridge["region"].astype(str) == str(market_area))
            ].copy()
            bad = post[post["bridge_source"].astype(str) != "derived_hourly_mean_from_observed_15min"]
            post_rule_ok = bool(bad.empty)
            post_rule_detail = (
                "post-cutoff rows all tagged derived_hourly_mean_from_observed_15min"
                if post_rule_ok
                else f"post-cutoff rows with unexpected bridge_source={int(bad.shape[0])}"
            )
        else:
            post_rule_ok = False
            post_rule_detail = "phase07 bridge_source column missing; cannot verify quarter_count==4 provenance token"

    report_rows.append(
        {
            "bridge_source": bridge_source,
            "bridge_path": str(bridge_path),
            "market_area_filter": str(market_area),
            "raw_rows": int(raw_bridge.shape[0]),
            "filtered_rows": int(filtered_bridge.shape[0]),
            "raw_min_timestamp_utc": _iso(raw_ts.min() if raw_ts.notna().any() else None),
            "raw_max_timestamp_utc": _iso(raw_ts.max() if raw_ts.notna().any() else None),
            "filtered_min_timestamp_utc": _iso(filt_ts.min() if filt_ts.notna().any() else None),
            "filtered_max_timestamp_utc": _iso(filt_ts.max() if filt_ts.notna().any() else None),
            "anchor_min_timestamp_utc": _iso(anchor_ts.min() if anchor_ts.notna().any() else None),
            "anchor_max_timestamp_utc": _iso(anchor_ts.max() if anchor_ts.notna().any() else None),
            "nl_duplicate_timestamp_rows": duplicates_nl,
            "post_transition_rule_verified": post_rule_ok,
            "post_transition_rule_detail": post_rule_detail,
            "covers_anchor_max_timestamp": bool(filt_ts.notna().any() and pd.Timestamp(filt_ts.max()) >= pd.Timestamp(anchor_ts.max())),
        }
    )
    return pd.DataFrame(report_rows)


def _choose_x2_frames(exogenous: dict[str, pd.DataFrame], policy: str) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    res = exogenous.get("da_res_generation_forecast", pd.DataFrame())
    agg = exogenous.get("da_generation_forecast", pd.DataFrame())
    if policy == "aggregate_generation":
        return agg, None
    if policy == "no_x2":
        primary = res if not res.empty else agg
        return primary, agg if not agg.empty else None
    primary = res if not res.empty else agg
    fallback = agg if (not agg.empty and not primary.equals(agg)) else None
    return primary, fallback


def _build_split_days_for_target_dates(
    config: LagoLearBenchmarkConfig,
    target_local_dates: set[date],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for local_day in config.benchmark_delivery_days():
        rows.append(
            {
                "delivery_local_date": local_day.isoformat(),
                "dataset_split": "validation" if local_day in target_local_dates else "train",
            }
        )
    return pd.DataFrame(rows)


def _make_run_id(tag: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    return f"{ts}_{RUN_LABEL}{suffix}"


def _find_latest_run_dir(output_root: Path) -> Path | None:
    if not output_root.exists():
        return None
    candidates = [path for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_run_dir(args: argparse.Namespace, output_root: Path) -> Path:
    explicit = str(args.run_dir or "").strip()
    if explicit:
        run_dir = Path(explicit)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    explicit_resume = str(args.resume_dir or "").strip()
    if explicit_resume:
        run_dir = Path(explicit_resume)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    if args.resume:
        # Safety: do not silently attach to an unrelated latest run directory.
        # Resume without --run-dir/--resume-dir creates a clean run directory.
        pass

    run_id = _make_run_id(str(args.output_tag or "").strip())
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _paths_for_run(run_dir: Path) -> ExportPaths:
    return ExportPaths(
        run_dir=run_dir,
        predictions_csv=run_dir / "predictions_long.csv",
        predictions_parquet=run_dir / "predictions_long.parquet",
        progress_json=run_dir / "progress.json",
        run_summary_json=run_dir / "run_summary.json",
        grid_summary_csv=run_dir / "grid_summary.csv",
        coverage_summary_csv=run_dir / "coverage_summary.csv",
        validation_report_json=run_dir / "validation_report.json",
        runtime_estimate_json=run_dir / "runtime_estimate.json",
        export_config_json=run_dir / "export_config.json",
        checkpoint_dir=run_dir / "checkpoints",
        strict_key_level_skip_reasons_csv=run_dir / "strict_key_level_skips.csv",
        strict_key_level_skip_reason_counts_csv=run_dir / "strict_key_level_skip_counts.csv",
        strict_key_level_skip_reason_by_split_lead_day_csv=run_dir / "strict_key_level_skip_by_split_lead.csv",
        strict_key_level_skip_reason_by_month_csv=run_dir / "strict_key_level_skip_by_month.csv",
    )


def _key_tuple(origin: pd.Timestamp, target: pd.Timestamp, lead_day: int) -> tuple[int, int, int]:
    return (int(origin.value), int(target.value), int(lead_day))


def _load_completed_keys(predictions_csv: Path) -> set[tuple[int, int, int]]:
    if not predictions_csv.exists():
        return set()
    frame = pd.read_csv(
        predictions_csv,
        usecols=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
    )
    if frame.empty:
        return set()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame = frame.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"]).copy()
    frame["lead_day"] = frame["lead_day"].astype(int)
    keys = {
        _key_tuple(row.forecast_origin_utc, row.target_timestamp_utc, int(row.lead_day))
        for row in frame.itertuples(index=False)
    }
    return keys


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _append_rows_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        return
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(path, mode="a", index=False, header=not path.exists())


def _summarize_grid(grid: pd.DataFrame) -> pd.DataFrame:
    out_rows: list[dict[str, Any]] = []
    lead_values = sorted(grid["lead_day"].dropna().astype(int).unique().tolist())
    for lead_day in lead_values:
        part = grid[grid["lead_day"].eq(lead_day)].copy()
        out_rows.append(
            {
                "lead_day": int(lead_day),
                "rows": int(part.shape[0]),
                "origins": int(part["forecast_origin_utc"].nunique()),
                "targets": int(part["target_timestamp_utc"].nunique()),
                "min_forecast_origin_utc": _iso(part["forecast_origin_utc"].min()),
                "max_forecast_origin_utc": _iso(part["forecast_origin_utc"].max()),
                "min_target_timestamp_utc": _iso(part["target_timestamp_utc"].min()),
                "max_target_timestamp_utc": _iso(part["target_timestamp_utc"].max()),
            }
        )
    out_rows.append(
        {
            "lead_day": "ALL",
            "rows": int(grid.shape[0]),
            "origins": int(grid["forecast_origin_utc"].nunique()),
            "targets": int(grid["target_timestamp_utc"].nunique()),
            "min_forecast_origin_utc": _iso(grid["forecast_origin_utc"].min()),
            "max_forecast_origin_utc": _iso(grid["forecast_origin_utc"].max()),
            "min_target_timestamp_utc": _iso(grid["target_timestamp_utc"].min()),
            "max_target_timestamp_utc": _iso(grid["target_timestamp_utc"].max()),
        }
    )
    return pd.DataFrame(out_rows)


def _coverage_summary(expected_grid: pd.DataFrame, predicted: pd.DataFrame) -> pd.DataFrame:
    pred_keys = predicted[["forecast_origin_utc", "target_timestamp_utc", "lead_day"]].drop_duplicates()
    merged = expected_grid.merge(
        pred_keys.assign(has_prediction=True),
        on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        how="left",
    )
    merged["has_prediction"] = merged["has_prediction"].fillna(False).astype(bool)

    rows: list[dict[str, Any]] = []
    group_cols = ["dataset_split", "lead_day"]
    for values, part in merged.groupby(group_cols, dropna=False):
        split_name, lead_day = values
        rows.append(
            {
                "dataset_split": str(split_name),
                "lead_day": int(lead_day),
                "expected_rows": int(part.shape[0]),
                "predicted_rows": int(part["has_prediction"].sum()),
                "coverage_pct": float(part["has_prediction"].mean() * 100.0),
            }
        )
    rows.append(
        {
            "dataset_split": "ALL",
            "lead_day": "ALL",
            "expected_rows": int(merged.shape[0]),
            "predicted_rows": int(merged["has_prediction"].sum()),
            "coverage_pct": float(merged["has_prediction"].mean() * 100.0),
        }
    )
    return pd.DataFrame(rows)


def _validation_report(expected_grid: pd.DataFrame, predicted: pd.DataFrame) -> dict[str, Any]:
    report: dict[str, Any] = {}
    pred = predicted.copy()
    pred["forecast_origin_utc"] = pd.to_datetime(pred["forecast_origin_utc"], utc=True, errors="coerce")
    pred["target_timestamp_utc"] = pd.to_datetime(pred["target_timestamp_utc"], utc=True, errors="coerce")
    pred["lead_day"] = pd.to_numeric(pred["lead_day"], errors="coerce").astype("Int64")

    required_leads_ok = sorted(pred["lead_day"].dropna().astype(int).unique().tolist())
    dup_count = int(
        pred.duplicated(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"]).sum()
    )
    null_y_pred = int(pd.to_numeric(pred["y_pred"], errors="coerce").isna().sum())
    lead_out_of_range = int((~pred["lead_day"].isin([0, 1, 2, 3, 4])).sum())

    expected_keys = expected_grid[["forecast_origin_utc", "target_timestamp_utc", "lead_day"]].drop_duplicates()
    observed_keys = pred[["forecast_origin_utc", "target_timestamp_utc", "lead_day"]].drop_duplicates()
    missing = expected_keys.merge(
        observed_keys.assign(has_key=True),
        on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        how="left",
    )
    has_key = missing["has_key"].fillna(False).astype(bool)
    missing_count = int((~has_key).sum())

    report["row_count_expected"] = int(expected_grid.shape[0])
    report["row_count_predicted"] = int(pred.shape[0])
    report["missing_rows_vs_expected"] = missing_count
    report["duplicate_key_rows"] = dup_count
    report["null_y_pred_rows"] = null_y_pred
    report["lead_day_values_present"] = required_leads_ok
    report["lead_day_out_of_range_rows"] = lead_out_of_range
    report["forecast_origin_utc_timezone_aware"] = isinstance(pred["forecast_origin_utc"].dtype, pd.DatetimeTZDtype)
    report["target_timestamp_utc_timezone_aware"] = isinstance(pred["target_timestamp_utc"].dtype, pd.DatetimeTZDtype)
    report["checks_passed"] = bool(
        missing_count == 0
        and dup_count == 0
        and null_y_pred == 0
        and lead_out_of_range == 0
        and report["forecast_origin_utc_timezone_aware"]
        and report["target_timestamp_utc_timezone_aware"]
    )
    return report


def _strict_key_level_skip_diagnostics(
    *,
    expected_grid: pd.DataFrame,
    predicted: pd.DataFrame,
    eval_rows: pd.DataFrame,
    feature_matrix: Any,
    price_df: pd.DataFrame,
    export_skip_details: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["forecast_origin_utc", "target_timestamp_utc", "lead_day"]
    base = expected_grid[keys + ["dataset_split"]].drop_duplicates(subset=keys).copy()
    base["forecast_origin_utc"] = pd.to_datetime(base["forecast_origin_utc"], utc=True, errors="coerce")
    base["target_timestamp_utc"] = pd.to_datetime(base["target_timestamp_utc"], utc=True, errors="coerce")
    base["lead_day"] = pd.to_numeric(base["lead_day"], errors="coerce").astype("Int64")
    base = base.dropna(subset=keys).copy()
    base["lead_day"] = base["lead_day"].astype(int)

    pred_keys = predicted[keys].drop_duplicates().assign(has_prediction=True)
    eval_keys = eval_rows[keys + ["target_hour_local"]].drop_duplicates(subset=keys).assign(in_eval_rows=True)
    out = base.merge(pred_keys, on=keys, how="left").merge(eval_keys, on=keys, how="left")
    out["has_prediction"] = out["has_prediction"].fillna(False).astype(bool)
    out["in_eval_rows"] = out["in_eval_rows"].fillna(False).astype(bool)

    price_ts = pd.to_datetime(price_df.get("timestamp_utc"), utc=True, errors="coerce")
    available_ts = set(price_ts.dropna().tolist())
    bridge_min = price_ts.min() if price_ts.notna().any() else pd.NaT
    bridge_max = price_ts.max() if price_ts.notna().any() else pd.NaT
    local_day_counts = (
        price_df.assign(target_delivery_local_date=pd.to_datetime(price_df["target_delivery_local_date"], errors="coerce"))
        .groupby("target_delivery_local_date", dropna=False)
        .size()
        .to_dict()
        if "target_delivery_local_date" in price_df.columns
        else {}
    )

    # Builder skip reasons are only available at delivery-day level; map dominant reason to each local day.
    skipped = feature_matrix.skipped_rows.copy()
    if not skipped.empty and "delivery_start_local_date" in skipped.columns and "reason" in skipped.columns:
        skipped["delivery_start_local_date"] = pd.to_datetime(
            skipped["delivery_start_local_date"], errors="coerce"
        ).dt.date
        dominant = (
            skipped.groupby(["delivery_start_local_date", "reason"], dropna=False)
            .size()
            .reset_index(name="n")
            .sort_values(["delivery_start_local_date", "n"], ascending=[True, False])
            .drop_duplicates(subset=["delivery_start_local_date"], keep="first")
            .rename(columns={"delivery_start_local_date": "target_local_date", "reason": "builder_skip_reason"})
        )
        dominant = dominant[["target_local_date", "builder_skip_reason"]]
    else:
        dominant = pd.DataFrame(columns=["target_local_date", "builder_skip_reason"])

    out["target_local_date"] = out["target_timestamp_utc"].dt.tz_convert(TARGET_TIMEZONE).dt.date
    out = out.merge(dominant, on="target_local_date", how="left")

    if not export_skip_details.empty:
        detail = export_skip_details[keys + ["target_hour_local", "skip_reason", "missing_feature", "diagnostic_detail"]].drop_duplicates(
            subset=keys, keep="last"
        )
        out = out.merge(
            detail.rename(
                columns={
                    "skip_reason": "export_skip_reason",
                    "missing_feature": "export_missing_feature",
                    "diagnostic_detail": "export_diagnostic_detail",
                    "target_hour_local": "export_target_hour_local",
                }
            ),
            on=keys,
            how="left",
        )
    else:
        out["export_skip_reason"] = np.nan
        out["export_missing_feature"] = np.nan
        out["export_diagnostic_detail"] = np.nan
        out["export_target_hour_local"] = np.nan

    rows: list[dict[str, Any]] = []
    for row in out.itertuples(index=False):
        if bool(row.has_prediction):
            continue
        missing_feature = ""
        diagnostic_detail = ""
        source_stage = ""
        skip_reason = ""
        target_ts = pd.Timestamp(row.target_timestamp_utc)
        local_date = getattr(row, "target_local_date", None)
        local_count = int(local_day_counts.get(local_date, 0)) if local_date is not None else 0
        if not bool(row.in_eval_rows):
            source_stage = "feature_builder"
            if target_ts not in available_ts:
                if pd.notna(bridge_max) and target_ts > pd.Timestamp(bridge_max):
                    skip_reason = "target_beyond_bridge_max"
                else:
                    skip_reason = "missing_hourly_bridge_price"
                missing_feature = "hourly_bridge_price"
                diagnostic_detail = "target_timestamp not present in observed hourly bridge"
            else:
                builder_reason = str(getattr(row, "builder_skip_reason", "") or "")
                if builder_reason:
                    skip_reason = builder_reason
                    if builder_reason.startswith("missing_"):
                        missing_feature = builder_reason
                    diagnostic_detail = "mapped from delivery-day level strict builder skip summary"
                else:
                    skip_reason = "feature_builder_drop_unknown"
                    diagnostic_detail = "row not present in eval matrix and no delivery-day reason available"
            if local_count != 24:
                diagnostic_detail = f"{diagnostic_detail}; local_day_hour_count={local_count} (DST/incomplete-day signal)"
        else:
            source_stage = "export_predict_loop"
            skip_reason = str(getattr(row, "export_skip_reason", "") or "export_skip_unknown")
            missing_feature = str(getattr(row, "export_missing_feature", "") or "")
            diagnostic_detail = str(getattr(row, "export_diagnostic_detail", "") or "")
        rows.append(
            {
                "forecast_origin_utc": pd.Timestamp(row.forecast_origin_utc),
                "target_timestamp_utc": target_ts,
                "lead_day": int(row.lead_day),
                "dataset_split": str(row.dataset_split),
                "target_delivery_local_date": local_date.isoformat() if local_date is not None else None,
                "target_hour_local": int(getattr(row, "export_target_hour_local"))
                if pd.notna(getattr(row, "export_target_hour_local", np.nan))
                else (int(row.target_hour_local) if pd.notna(getattr(row, "target_hour_local", np.nan)) else None),
                "skip_reason": skip_reason,
                "missing_feature": missing_feature,
                "source_stage": source_stage,
                "diagnostic_detail": diagnostic_detail,
            }
        )
    return pd.DataFrame(rows)


def _progress_payload(
    *,
    started: float,
    total_rows: int,
    completed_rows: int,
    total_origins: int,
    completed_origins: int,
    current_origin: pd.Timestamp | None,
    stage: str,
) -> dict[str, Any]:
    elapsed = float(time.perf_counter() - started)
    sec_per_row = elapsed / completed_rows if completed_rows > 0 else None
    remaining_rows = max(0, total_rows - completed_rows)
    eta_sec = (sec_per_row * remaining_rows) if sec_per_row is not None else None
    sec_per_origin = elapsed / completed_origins if completed_origins > 0 else None
    remaining_origins = max(0, total_origins - completed_origins)
    eta_origin_sec = (sec_per_origin * remaining_origins) if sec_per_origin is not None else None
    return {
        "timestamp_utc": _iso(_timestamp_now_utc()),
        "stage": str(stage),
        "elapsed_seconds": elapsed,
        "completed_rows": int(completed_rows),
        "total_rows": int(total_rows),
        "completed_origins": int(completed_origins),
        "total_origins": int(total_origins),
        "rolling_seconds_per_origin": sec_per_origin,
        "estimated_remaining_seconds_rows": eta_sec,
        "estimated_remaining_seconds_origins": eta_origin_sec,
        "current_origin_utc": _iso(current_origin),
        "memory_rss_mb": _memory_mb(),
    }


def _prepare_training_matrix(
    *,
    feature_matrix: Any,
    anchor_grid: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    X_long = feature_matrix.X_long.copy()
    y_long = feature_matrix.y_long.copy()
    meta = feature_matrix.metadata_long.copy()

    meta["forecast_origin_utc"] = pd.to_datetime(meta["forecast_origin_utc"], utc=True, errors="coerce")
    meta["target_timestamp_utc"] = pd.to_datetime(meta["target_timestamp_utc"], utc=True, errors="coerce")
    meta["lead_day"] = pd.to_numeric(meta["lead_day"], errors="coerce").astype("Int64")
    meta["target_hour_local"] = pd.to_numeric(meta["target_hour_local"], errors="coerce").astype("Int64")
    y_long["y_true"] = pd.to_numeric(y_long["y_true"], errors="coerce")

    matrix = pd.concat([meta.reset_index(drop=True), X_long.reset_index(drop=True), y_long.reset_index(drop=True)], axis=1)
    matrix = matrix.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "target_hour_local"]).copy()
    matrix["lead_day"] = matrix["lead_day"].astype(int)
    matrix["target_hour_local"] = matrix["target_hour_local"].astype(int)
    matrix["origin_ns_i64"] = matrix["forecast_origin_utc"].astype("int64")

    anchor_keys = anchor_grid.copy()
    anchor_keys["forecast_origin_utc"] = pd.to_datetime(anchor_keys["forecast_origin_utc"], utc=True, errors="coerce")
    anchor_keys["target_timestamp_utc"] = pd.to_datetime(anchor_keys["target_timestamp_utc"], utc=True, errors="coerce")
    anchor_keys["lead_day"] = pd.to_numeric(anchor_keys["lead_day"], errors="coerce").astype("Int64")
    anchor_keys = anchor_keys.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"]).copy()
    anchor_keys["lead_day"] = anchor_keys["lead_day"].astype(int)

    eval_rows = matrix.merge(
        anchor_keys,
        on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        how="inner",
    )
    eval_rows = eval_rows.sort_values(["forecast_origin_utc", "lead_day", "target_hour_local", "target_timestamp_utc"]).reset_index(drop=True)
    feature_cols = list(X_long.columns)
    return matrix, eval_rows, feature_cols


def _fit_predict_rows(
    *,
    matrix: pd.DataFrame,
    eval_rows: pd.DataFrame,
    feature_cols: list[str],
    config: LagoLearBenchmarkConfig,
    window_days: int,
    model_name: str,
    already_done: set[tuple[int, int, int]],
    predictions_csv_path: Path | None,
    progress_path: Path,
    checkpoint_flush_rows: int,
    log_every_rows: int,
    estimate_only: bool,
) -> dict[str, Any]:
    by_group: dict[tuple[int, int], pd.DataFrame] = {}
    for (lead_day, target_hour_local), part in matrix.groupby(["lead_day", "target_hour_local"], dropna=False):
        key = (_safe_int(lead_day), _safe_int(target_hour_local))
        by_group[key] = part.sort_values("forecast_origin_utc").reset_index(drop=True)
        by_group[key]["origin_ns_i64"] = by_group[key]["forecast_origin_utc"].astype("int64")

    started = time.perf_counter()
    total_rows = int(eval_rows.shape[0])
    total_origins = int(eval_rows["forecast_origin_utc"].nunique())
    completed_rows = 0
    completed_origins: set[pd.Timestamp] = set()
    pending_rows_buffer: list[dict[str, Any]] = []
    skipped_rows = 0
    skipped_detail_rows: list[dict[str, Any]] = []
    fit_time_total = 0.0
    predict_time_total = 0.0

    min_days = int(config.min_training_days_by_window.get(int(window_days), 1))
    eval_rows = eval_rows.copy()
    eval_rows["origin_ns_i64"] = eval_rows["forecast_origin_utc"].astype("int64")

    for idx, row in enumerate(eval_rows.itertuples(index=False), start=1):
        origin_utc = pd.Timestamp(row.forecast_origin_utc)
        target_utc = pd.Timestamp(row.target_timestamp_utc)
        lead_day = int(row.lead_day)
        key_triplet = _key_tuple(origin_utc, target_utc, lead_day)
        if key_triplet in already_done:
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue

        grp_key = (lead_day, int(row.target_hour_local))
        pool = by_group.get(grp_key)
        if pool is None or pool.empty:
            skipped_rows += 1
            skipped_detail_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": target_utc,
                    "lead_day": int(lead_day),
                    "dataset_split": str(getattr(row, "dataset_split", "unknown")),
                    "target_hour_local": int(getattr(row, "target_hour_local", -1)),
                    "skip_reason": "export_skip_pool_empty",
                    "missing_feature": "",
                    "source_stage": "export_predict_loop",
                    "diagnostic_detail": "No training pool for (lead_day,target_hour_local) group.",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue

        cutoff = int(
            np.searchsorted(
                pool["origin_ns_i64"].to_numpy(dtype=np.int64),
                int(getattr(row, "origin_ns_i64")),
                side="left",
            )
        )
        if cutoff <= 0:
            skipped_rows += 1
            skipped_detail_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": target_utc,
                    "lead_day": int(lead_day),
                    "dataset_split": str(getattr(row, "dataset_split", "unknown")),
                    "target_hour_local": int(getattr(row, "target_hour_local", -1)),
                    "skip_reason": "export_skip_no_history_before_origin",
                    "missing_feature": "",
                    "source_stage": "export_predict_loop",
                    "diagnostic_detail": "No historical rows in group before forecast origin.",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue

        train = pool.iloc[:cutoff]
        if int(train["forecast_origin_utc"].nunique()) < min_days:
            skipped_rows += 1
            skipped_detail_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": target_utc,
                    "lead_day": int(lead_day),
                    "dataset_split": str(getattr(row, "dataset_split", "unknown")),
                    "target_hour_local": int(getattr(row, "target_hour_local", -1)),
                    "skip_reason": "export_skip_min_training_days",
                    "missing_feature": "",
                    "source_stage": "export_predict_loop",
                    "diagnostic_detail": f"Unique origin days in train < min_days={min_days}.",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue

        y_train = pd.to_numeric(train["y_true"], errors="coerce")
        valid = y_train.notna()
        X_train = train.loc[valid, feature_cols]
        y_train = y_train.loc[valid]
        if X_train.empty:
            skipped_rows += 1
            skipped_detail_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": target_utc,
                    "lead_day": int(lead_day),
                    "dataset_split": str(getattr(row, "dataset_split", "unknown")),
                    "target_hour_local": int(getattr(row, "target_hour_local", -1)),
                    "skip_reason": "export_skip_empty_train_after_y_filter",
                    "missing_feature": "",
                    "source_stage": "export_predict_loop",
                    "diagnostic_detail": "Training rows removed after y_true notna filter.",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue

        X_test = pd.DataFrame([{col: getattr(row, col) for col in feature_cols}])
        model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
        model.fit(X_train, y_train)
        if model.pipeline is None:
            skipped_rows += 1
            skipped_detail_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": target_utc,
                    "lead_day": int(lead_day),
                    "dataset_split": str(getattr(row, "dataset_split", "unknown")),
                    "target_hour_local": int(getattr(row, "target_hour_local", -1)),
                    "skip_reason": "export_skip_model_pipeline_none",
                    "missing_feature": "",
                    "source_stage": "export_predict_loop",
                    "diagnostic_detail": "Model fit completed without pipeline.",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            continue
        pred_value = float(model.predict(X_test)[0])
        fit_time_total += float(model.fit_time_sec)
        predict_time_total += float(model.predict_time_sec)

        pending_rows_buffer.append(
            {
                "forecast_origin_utc": origin_utc,
                "target_timestamp_utc": target_utc,
                "lead_day": int(lead_day),
                "y_pred": pred_value,
                "model": model_name,
                "model_family": MODEL_FAMILY,
                "dataset_split": str(getattr(row, "dataset_split", "unknown")),
            }
        )

        completed_rows += 1
        completed_origins.add(origin_utc)

        if (not estimate_only) and predictions_csv_path is not None and len(pending_rows_buffer) >= max(1, int(checkpoint_flush_rows)):
            _append_rows_csv(
                predictions_csv_path,
                pending_rows_buffer,
                columns=[
                    "forecast_origin_utc",
                    "target_timestamp_utc",
                    "lead_day",
                    "y_pred",
                    "model",
                    "model_family",
                    "dataset_split",
                ],
            )
            pending_rows_buffer = []

        if idx % max(1, int(log_every_rows)) == 0:
            progress = _progress_payload(
                started=started,
                total_rows=total_rows,
                completed_rows=completed_rows,
                total_origins=total_origins,
                completed_origins=len(completed_origins),
                current_origin=origin_utc,
                stage="predicting",
            )
            _write_json(progress_path, progress)

    if (not estimate_only) and predictions_csv_path is not None and pending_rows_buffer:
        _append_rows_csv(
            predictions_csv_path,
            pending_rows_buffer,
            columns=[
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "y_pred",
                "model",
                "model_family",
                "dataset_split",
            ],
        )

    progress = _progress_payload(
        started=started,
        total_rows=total_rows,
        completed_rows=completed_rows,
        total_origins=total_origins,
        completed_origins=len(completed_origins),
        current_origin=None,
        stage="done",
    )
    _write_json(progress_path, progress)

    return {
        "elapsed_seconds": float(time.perf_counter() - started),
        "completed_rows": int(completed_rows),
        "total_rows": int(total_rows),
        "completed_origins": int(len(completed_origins)),
        "total_origins": int(total_origins),
        "skipped_rows": int(skipped_rows),
        "fit_time_total_sec": float(fit_time_total),
        "predict_time_total_sec": float(predict_time_total),
        "skipped_detail_rows": skipped_detail_rows,
    }


def main() -> int:
    args = parse_args()
    started_all = time.perf_counter()
    targets_path = (REPO_ROOT / Path(args.targets_by_origin)).resolve()
    output_root = (REPO_ROOT / Path(args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = _resolve_run_dir(args, output_root)
    paths = _paths_for_run(run_dir)
    paths.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    stage_started = time.perf_counter()
    targets = _read_targets_by_origin(targets_path)
    anchor_grid = _build_hourly_anchor_grid(targets)
    if anchor_grid.empty:
        raise ValueError("Hourly anchor grid is empty after filtering quarter_in_hour==1 and max-origins.")

    lead_values = sorted(anchor_grid["lead_day"].dropna().astype(int).unique().tolist())
    if any(value not in {0, 1, 2, 3, 4} for value in lead_values):
        raise ValueError(f"Anchor grid contains lead_day outside 0..4: {lead_values}")

    target_local_dates = set(
        anchor_grid["target_timestamp_utc"].dt.tz_convert(TARGET_TIMEZONE).dt.date.tolist()
    )
    min_target_local = min(target_local_dates)
    max_target_local = max(target_local_dates)
    max_window_days = int(args.window_days)
    start_local_date = min(date(2022, 1, 1), min_target_local - timedelta(days=max_window_days + 14))
    end_exclusive_local_date = max_target_local + timedelta(days=1)

    config = LagoLearBenchmarkConfig(
        benchmark_start_local_date=start_local_date,
        benchmark_end_exclusive_local_date=end_exclusive_local_date,
        allow_official_cleaned_fallback=bool(args.allow_official_cleaned_fallback),
        x2_policy="res_forecast_if_available",
        x2_missing_policy="impute_training_median",
        dplus4_x2_policy="strict_no_future_x2",
    )
    split_days = _build_split_days_for_target_dates(config, target_local_dates)

    model_name = f"lear_lago_direct_dplus4_strict_no_future_{int(args.window_days)}"
    grid_summary = _summarize_grid(anchor_grid)
    grid_summary.to_csv(paths.grid_summary_csv, index=False)

    export_config = {
        "created_at_utc": _iso(_timestamp_now_utc()),
        "targets_by_origin_path": str(targets_path),
        "run_dir": str(run_dir),
        "model_name": model_name,
        "model_family": MODEL_FAMILY,
        "fs_level": FS_LEVEL,
        "feature_variant": FEATURE_VARIANT,
        "window_days": int(args.window_days),
        "benchmark_start_local_date": start_local_date.isoformat(),
        "benchmark_end_exclusive_local_date": end_exclusive_local_date.isoformat(),
        "target_grid_rows": int(anchor_grid.shape[0]),
        "target_grid_origins": int(anchor_grid["forecast_origin_utc"].nunique()),
        "max_origins": args.max_origins,
        "check_only": bool(args.check_only),
        "estimate_runtime": bool(args.estimate_runtime),
        "sample_origins": int(args.sample_origins),
        "resume": bool(args.resume),
        "resume_dir": str(args.resume_dir or ""),
        "bridge_source": str(args.bridge_source),
        "bridge_path": str(args.bridge_path or ""),
        "bridge_market_area": str(args.bridge_market_area),
    }
    _write_json(paths.export_config_json, export_config)
    stage_grid_seconds = float(time.perf_counter() - stage_started)

    stage_started = time.perf_counter()
    bridge_path, bridge_source = _resolve_bridge_input(args, targets_path)
    bridge_raw = pd.read_csv(bridge_path, low_memory=False)
    price_df = _load_bridge_price_frame(
        bridge_path,
        config,
        start_local_date=start_local_date,
        end_exclusive_local_date=end_exclusive_local_date,
        bridge_source=str(bridge_source),
        market_area=str(args.bridge_market_area),
    )
    if price_df.empty:
        raise ValueError(f"Observed hourly bridge became empty after observed-target filtering: {bridge_path}")
    bridge_validation = _bridge_validation_report(
        bridge_source=str(bridge_source),
        bridge_path=bridge_path,
        market_area=str(args.bridge_market_area),
        raw_bridge=bridge_raw,
        filtered_bridge=price_df,
        anchor_grid=anchor_grid,
    )
    bridge_validation_path = run_dir / "phase07_bridge_validation_report.csv"
    bridge_validation.to_csv(bridge_validation_path, index=False)

    exogenous = load_lago_exogenous_frames(config)
    x2_primary, _ = _choose_x2_frames(exogenous, str(args.x2_policy))
    if x2_primary.empty:
        raise ValueError("x2 generation forecast frame is empty; cannot build LEAR_STRICT matrix.")
    horizon_policy_csv = _resolve_horizon_policy_csv()
    stage_data_seconds = float(time.perf_counter() - stage_started)

    if args.check_only:
        payload = {
            "completed_successfully": True,
            "mode": "check_only",
            "run_dir": str(run_dir),
            "target_grid_rows": int(anchor_grid.shape[0]),
            "target_grid_origins": int(anchor_grid["forecast_origin_utc"].nunique()),
            "lead_day_values": lead_values,
            "bridge_path": str(bridge_path),
            "bridge_source": str(bridge_source),
            "bridge_market_area": str(args.bridge_market_area),
            "bridge_validation_report_path": str(bridge_validation_path),
            "horizon_policy_csv": str(horizon_policy_csv),
            "price_rows_after_observed_filter": int(price_df.shape[0]),
            "exogenous_rows": {name: int(frame.shape[0]) for name, frame in exogenous.items()},
            "elapsed_seconds": float(time.perf_counter() - started_all),
        }
        _write_json(paths.run_summary_json, payload)
        print(f"Check-only passed. Run dir: {run_dir}")
        return 0

    stage_started = time.perf_counter()
    feature_matrix = build_lago_dplus4_direct_matrix_strict_no_future(
        price_df=price_df,
        load_forecast_df=exogenous.get("da_total_load_forecast", pd.DataFrame()),
        week_ahead_load_forecast_df=exogenous.get("week_ahead_total_load_forecast", pd.DataFrame()),
        generation_forecast_df=x2_primary,
        config=config,
        horizon_policy_csv=horizon_policy_csv,
        hard_fail_on_policy_violation=True,
    )
    matrix, eval_rows_all, feature_cols = _prepare_training_matrix(feature_matrix=feature_matrix, anchor_grid=anchor_grid)
    if eval_rows_all.empty:
        raise ValueError("No overlap between LEAR_STRICT matrix rows and observed-QH hourly anchor grid.")
    if args.max_origins is not None:
        # Smoke runs should stay non-empty even if earliest origins have no observed hourly truth coverage.
        overlap_limited = _apply_origin_limit(eval_rows_all, int(args.max_origins))
        if overlap_limited.empty:
            raise ValueError(
                "No overlap rows remain after --max-origins filter. "
                "Choose a larger value or run without --max-origins."
            )
        eval_rows_all = overlap_limited
        keep_origins = set(eval_rows_all["forecast_origin_utc"].drop_duplicates().tolist())
        anchor_grid = anchor_grid[anchor_grid["forecast_origin_utc"].isin(keep_origins)].copy()
        grid_summary = _summarize_grid(anchor_grid)
        grid_summary.to_csv(paths.grid_summary_csv, index=False)
    stage_features_seconds = float(time.perf_counter() - stage_started)

    sample_eval = eval_rows_all.copy()
    if args.estimate_runtime:
        sample_eval = _apply_origin_limit(sample_eval, int(args.sample_origins))
        if sample_eval.empty:
            raise ValueError("Runtime estimation sample is empty after sample-origins filter.")
        est = _fit_predict_rows(
            matrix=matrix,
            eval_rows=sample_eval,
            feature_cols=feature_cols,
            config=config,
            window_days=int(args.window_days),
            model_name=model_name,
            already_done=set(),
            predictions_csv_path=None,
            progress_path=paths.progress_json,
            checkpoint_flush_rows=int(args.checkpoint_flush_rows),
            log_every_rows=max(1, int(args.log_every_rows)),
            estimate_only=True,
        )
        sampled_origins = int(sample_eval["forecast_origin_utc"].nunique())
        total_origins = int(eval_rows_all["forecast_origin_utc"].nunique())
        sec_per_origin = float(est["elapsed_seconds"] / sampled_origins) if sampled_origins > 0 else None
        estimate_payload = {
            "mode": "estimate_runtime",
            "sampled_origins": sampled_origins,
            "total_origins": total_origins,
            "sample_rows": int(sample_eval.shape[0]),
            "total_rows": int(eval_rows_all.shape[0]),
            "elapsed_seconds_sample": float(est["elapsed_seconds"]),
            "seconds_per_origin_estimate": sec_per_origin,
            "estimated_total_seconds": float(sec_per_origin * total_origins) if sec_per_origin is not None else None,
            "estimated_total_hours": float((sec_per_origin * total_origins) / 3600.0) if sec_per_origin is not None else None,
            "window_days": int(args.window_days),
            "target_grid_rows": int(anchor_grid.shape[0]),
            "timestamp_utc": _iso(_timestamp_now_utc()),
        }
        _write_json(paths.runtime_estimate_json, estimate_payload)
        _write_json(
            paths.run_summary_json,
            {
                "completed_successfully": True,
                "mode": "estimate_runtime",
                "run_dir": str(run_dir),
                "runtime_estimate_path": str(paths.runtime_estimate_json),
                "elapsed_seconds_total": float(time.perf_counter() - started_all),
            },
        )
        print(f"Runtime estimate written: {paths.runtime_estimate_json}")
        return 0

    already_done = _load_completed_keys(paths.predictions_csv) if args.resume else set()
    result = _fit_predict_rows(
        matrix=matrix,
        eval_rows=eval_rows_all,
        feature_cols=feature_cols,
        config=config,
        window_days=int(args.window_days),
        model_name=model_name,
        already_done=already_done,
        predictions_csv_path=paths.predictions_csv,
        progress_path=paths.progress_json,
        checkpoint_flush_rows=int(args.checkpoint_flush_rows),
        log_every_rows=max(1, int(args.log_every_rows)),
        estimate_only=False,
    )

    if not paths.predictions_csv.exists():
        raise RuntimeError("No predictions_long.csv was written.")
    predictions = pd.read_csv(paths.predictions_csv)
    predictions["forecast_origin_utc"] = pd.to_datetime(predictions["forecast_origin_utc"], utc=True, errors="coerce")
    predictions["target_timestamp_utc"] = pd.to_datetime(predictions["target_timestamp_utc"], utc=True, errors="coerce")
    predictions["lead_day"] = pd.to_numeric(predictions["lead_day"], errors="coerce").astype("Int64")
    predictions = predictions.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"]).copy()
    predictions["lead_day"] = predictions["lead_day"].astype(int)
    predictions = predictions.sort_values(["forecast_origin_utc", "target_timestamp_utc", "lead_day"]).drop_duplicates(
        subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        keep="last",
    )
    predictions.to_csv(paths.predictions_csv, index=False)

    if not bool(args.no_parquet):
        try:
            predictions.to_parquet(paths.predictions_parquet, index=False)
        except Exception as exc:  # noqa: BLE001
            print(f"Parquet write skipped due to error: {exc}")

    coverage = _coverage_summary(anchor_grid, predictions)
    coverage.to_csv(paths.coverage_summary_csv, index=False)
    validation = _validation_report(anchor_grid, predictions)
    _write_json(paths.validation_report_json, validation)
    export_skip_details = pd.DataFrame(result.get("skipped_detail_rows", []))
    key_level_skips = _strict_key_level_skip_diagnostics(
        expected_grid=anchor_grid,
        predicted=predictions,
        eval_rows=eval_rows_all,
        feature_matrix=feature_matrix,
        price_df=price_df,
        export_skip_details=export_skip_details,
    )
    if key_level_skips.empty:
        key_level_skips = pd.DataFrame(
            columns=[
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "dataset_split",
                "target_delivery_local_date",
                "target_hour_local",
                "skip_reason",
                "missing_feature",
                "source_stage",
                "diagnostic_detail",
            ]
        )
    key_level_skips = key_level_skips.sort_values(
        ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "skip_reason"], na_position="last"
    ).reset_index(drop=True)
    paths.strict_key_level_skip_reasons_csv.parent.mkdir(parents=True, exist_ok=True)
    key_level_skips.to_csv(paths.strict_key_level_skip_reasons_csv, index=False)
    if key_level_skips.empty:
        pd.DataFrame(
            columns=["skip_reason", "source_stage", "missing_feature", "rows", "pct_of_expected"]
        ).to_csv(paths.strict_key_level_skip_reason_counts_csv, index=False)
        pd.DataFrame(
            columns=["dataset_split", "lead_day", "skip_reason", "source_stage", "rows", "pct_within_split_lead_day"]
        ).to_csv(paths.strict_key_level_skip_reason_by_split_lead_day_csv, index=False)
        pd.DataFrame(
            columns=["forecast_origin_month", "target_month", "skip_reason", "source_stage", "rows"]
        ).to_csv(paths.strict_key_level_skip_reason_by_month_csv, index=False)
    else:
        total_expected = max(1, int(anchor_grid.shape[0]))
        reason_counts = (
            key_level_skips.groupby(["skip_reason", "source_stage", "missing_feature"], dropna=False)
            .size()
            .reset_index(name="rows")
            .sort_values("rows", ascending=False)
        )
        reason_counts["pct_of_expected"] = reason_counts["rows"] / total_expected * 100.0
        paths.strict_key_level_skip_reason_counts_csv.parent.mkdir(parents=True, exist_ok=True)
        reason_counts.to_csv(paths.strict_key_level_skip_reason_counts_csv, index=False)
        tmp = key_level_skips.copy()
        tmp["forecast_origin_month"] = tmp["forecast_origin_utc"].dt.tz_convert("UTC").dt.strftime("%Y-%m")
        tmp["target_month"] = tmp["target_timestamp_utc"].dt.tz_convert("UTC").dt.strftime("%Y-%m")
        by_split_lead = (
            tmp.groupby(["dataset_split", "lead_day", "skip_reason", "source_stage"], dropna=False)
            .size()
            .reset_index(name="rows")
            .sort_values(["dataset_split", "lead_day", "rows"], ascending=[True, True, False])
        )
        by_split_lead["pct_within_split_lead_day"] = by_split_lead["rows"] / by_split_lead.groupby(
            ["dataset_split", "lead_day"], dropna=False
        )["rows"].transform("sum") * 100.0
        paths.strict_key_level_skip_reason_by_split_lead_day_csv.parent.mkdir(parents=True, exist_ok=True)
        by_split_lead.to_csv(paths.strict_key_level_skip_reason_by_split_lead_day_csv, index=False)
        by_month = (
            tmp.groupby(["forecast_origin_month", "target_month", "skip_reason", "source_stage"], dropna=False)
            .size()
            .reset_index(name="rows")
            .sort_values(["forecast_origin_month", "target_month", "rows"], ascending=[True, True, False])
        )
        paths.strict_key_level_skip_reason_by_month_csv.parent.mkdir(parents=True, exist_ok=True)
        by_month.to_csv(paths.strict_key_level_skip_reason_by_month_csv, index=False)

    run_summary = {
        "completed_successfully": True,
        "validation_checks_passed": bool(validation.get("checks_passed", False)),
        "run_dir": str(run_dir),
        "targets_by_origin_path": str(targets_path),
        "bridge_path": str(bridge_path),
        "bridge_source": str(bridge_source),
        "bridge_market_area": str(args.bridge_market_area),
        "bridge_validation_report_path": str(bridge_validation_path),
        "horizon_policy_csv": str(horizon_policy_csv),
        "model": model_name,
        "model_family": MODEL_FAMILY,
        "fs_level": FS_LEVEL,
        "feature_variant": FEATURE_VARIANT,
        "window_days": int(args.window_days),
        "resume_mode": bool(args.resume),
        "already_done_rows_at_start": int(len(already_done)),
        "n_origins": int(anchor_grid["forecast_origin_utc"].nunique()),
        "n_predictions_expected": int(anchor_grid.shape[0]),
        "n_predictions_written": int(predictions.shape[0]),
        "coverage_pct_vs_expected": float(
            predictions.shape[0] / anchor_grid.shape[0] * 100.0 if anchor_grid.shape[0] else 0.0
        ),
        "runtime_seconds_total": float(time.perf_counter() - started_all),
        "runtime_seconds_grid_stage": stage_grid_seconds,
        "runtime_seconds_data_stage": stage_data_seconds,
        "runtime_seconds_feature_stage": stage_features_seconds,
        "runtime_seconds_prediction_stage": float(result["elapsed_seconds"]),
        "prediction_loop_stats": result,
        "validation_report_path": str(paths.validation_report_json),
        "coverage_summary_path": str(paths.coverage_summary_csv),
        "strict_key_level_skip_reasons_path": str(paths.strict_key_level_skip_reasons_csv),
        "strict_key_level_skip_reason_counts_path": str(paths.strict_key_level_skip_reason_counts_csv),
        "strict_key_level_skip_reason_by_split_lead_day_path": str(paths.strict_key_level_skip_reason_by_split_lead_day_csv),
        "strict_key_level_skip_reason_by_month_path": str(paths.strict_key_level_skip_reason_by_month_csv),
        "predictions_long_csv_path": str(paths.predictions_csv),
        "predictions_long_parquet_path": str(paths.predictions_parquet) if not args.no_parquet else None,
        "timestamp_utc": _iso(_timestamp_now_utc()),
        "limitations": [
            "Hourly anchor generation uses LEAR_STRICT direct D..D+4 logic only.",
            "QH_MODEL_3 and scenario generation are intentionally out of scope in this phase.",
        ],
    }
    _write_json(paths.run_summary_json, run_summary)

    print(f"LEAR_STRICT anchor export completed. Run dir: {run_dir}")
    print(f"Predictions: {paths.predictions_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
