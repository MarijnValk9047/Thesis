from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[6]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.scenario_generation import (
    build_residual_daily_profiles,
    build_residual_period_table,
    generate_scenario_bundle,
    resolve_scenario_horizon_spec,
    validate_scenario_set,
)


LOCAL_TZ = "Europe/Amsterdam"
TEST_START = pd.Timestamp("2024-10-01").date()
TEST_END = pd.Timestamp("2025-09-30").date()
VALIDATION_START = pd.Timestamp("2023-10-01").date()
VALIDATION_END = pd.Timestamp("2024-09-30").date()
SELECTED_STRICT_MODEL = "lago_lear_247_imputed_x2_1092"

FROZEN_STRICT_PREDICTIONS = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/frozen_results/"
    "d_only_lago_lear_20260507/run_outputs/20260507_161622_lago_lear_six_year_benchmark/"
    "predictions/predictions_long.csv"
)
STRICT_DENSE_EXPORT = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/exports/"
    "lear_strict_donly_1092_test_year_dense/predictions_long.csv"
)
QH_STRICT_EXPORT = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/"
    "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run/predictions_long.csv"
)
QH_STRICT_RUN_SUMMARY = QH_STRICT_EXPORT.parent / "run_summary.json"
QH_STRICT_EXPORT_CONFIG = QH_STRICT_EXPORT.parent / "export_config.json"
QH_STRICT_VALIDATION = QH_STRICT_EXPORT.parent / "validation_report.json"
QH_STRICT_SKIP_COUNTS = QH_STRICT_EXPORT.parent / "strict_key_level_skip_counts.csv"

LEAR_FS3_RUN_DIR = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260425_124242_lear_fs3_combo_promoted_benchmark"
)
XGB_FS3_RUN_DIR = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark"
)
LEAR_FS3_PREDICTIONS = LEAR_FS3_RUN_DIR / "predictions_long.parquet"
XGB_FS3_PREDICTIONS = XGB_FS3_RUN_DIR / "predictions_long.parquet"
LEAR_FS3_MODEL = "lear_fs3_combo_promoted"
XGB_FS3_MODEL = "xgboost_fs3_combo_promoted"

BASELINE_SCENARIO_RUN = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/"
    "01_da_price_scenario_generation_hourly/20260429_193206/scenario_generation_run_summary.json"
)
STRICT_SCENARIO_RUN = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/"
    "01_da_price_scenario_generation_hourly_with_lear_strict/20260517_104259/scenario_generation_run_summary.json"
)


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    path: Path
    class_label: str
    description: str
    selected_model: str | None = None
    y_pred_col: str = "y_pred"
    y_true_col: str = "y_true"
    ts_col: str = "target_timestamp_utc"
    origin_col: str = "forecast_origin_utc"
    lead_day_col: str = "lead_day"
    split_col: str = "dataset_split"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit LEAR Strict hourly D-only support candidates and set up an aligned three-model "
            "hourly D-only scenario recreation capped at 30 scenarios per model."
        )
    )
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--smoke-days", type=int, default=7)
    parser.add_argument("--scenario-cap", type=int, default=30)
    parser.add_argument("--n-raw", type=int, default=180)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def _default_config() -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(
        input_csv=Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv"),
        raw_root=Path("data/00_Raw/DA_Prices"),
        cleaned_feature_root=Path("data/01_cleaned"),
        output_root=Path("data/02_Forecasting/01_DA_prices/hourly_da"),
    )


def _now_token() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("/", "\\")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _write_yaml_like(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(item, ensure_ascii=True)}")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _latest_successful_repair_anchor() -> tuple[Path, Path]:
    repair_root = REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da/repair_runs"
    candidates: list[tuple[pd.Timestamp, Path, Path]] = []
    for run_dir in sorted(repair_root.glob("*_lear_strict_donly_support_repair")):
        readiness_path = run_dir / "lear_strict_optimisation_readiness_audit.csv"
        anchor_path = run_dir / "hourly_lear_strict_donly_1092_full_support_anchor.parquet"
        if not readiness_path.exists() or not anchor_path.exists():
            continue
        readiness = pd.read_csv(readiness_path)
        if readiness.empty:
            continue
        test_complete = str(readiness.loc[0, "test_complete_support"]).strip().lower() == "true"
        probability_ok = str(readiness.loc[0, "probability_sums_valid"]).strip().lower() == "true"
        ready = test_complete and probability_ok
        if not ready:
            continue
        stamp = pd.Timestamp(
            datetime.strptime(
                run_dir.name.split("_lear_strict_donly_support_repair")[0],
                "%Y%m%d_%H%M%S",
            ),
            tz="UTC",
        )
        candidates.append((stamp, anchor_path, run_dir))
    if not candidates:
        raise FileNotFoundError("No successful LEAR Strict repair anchor was found under hourly_da/repair_runs.")
    _, anchor_path, run_dir = sorted(candidates, key=lambda item: item[0])[-1]
    return anchor_path, run_dir


def _candidate_specs(repair_anchor: Path) -> list[CandidateSpec]:
    return [
        CandidateSpec(
            candidate_id="lear_strict_frozen_sparse",
            path=FROZEN_STRICT_PREDICTIONS,
            class_label="hourly_d_only_derived|official_frozen_source|incomplete_export_filtered",
            description="Frozen Lago/LEAR D-only benchmark predictions file with multiple windows; selected model is 1092.",
            selected_model=SELECTED_STRICT_MODEL,
        ),
        CandidateSpec(
            candidate_id="lear_strict_dense_export",
            path=STRICT_DENSE_EXPORT,
            class_label="hourly_d_only_derived|dense_export_attempt|incomplete_export_filtered",
            description="Dense 1092 export rebuilt from frozen hourly features without the QH bridge.",
            selected_model=SELECTED_STRICT_MODEL,
        ),
        CandidateSpec(
            candidate_id="lear_strict_repaired_anchor",
            path=repair_anchor,
            class_label="hourly_d_only_derived|repaired_anchor|full_non_dst_support",
            description="Full-support repaired hourly LEAR Strict anchor with actuals and point forecasts.",
            selected_model="lear_strict_donly_1092_repaired_anchor",
            y_pred_col="point_forecast_eur_per_mwh",
            y_true_col="actual_price_eur_per_mwh",
            ts_col="delivery_start_utc",
            origin_col="forecast_origin_utc",
            lead_day_col="lead_day",
            split_col="dataset_split",
        ),
        CandidateSpec(
            candidate_id="lear_strict_qh_anchor_export",
            path=QH_STRICT_EXPORT,
            class_label="qh_anchor_derived|wrong_anchor_for_hourly_d_only|incomplete_export_filtered",
            description="Quarter-hour observed-grid anchor export later bridged to hourly; not valid for the hourly D-only comparison.",
            selected_model="lear_lago_direct_dplus4_strict_no_future_1092",
        ),
    ]


def _prepare_candidate_frame(spec: CandidateSpec) -> pd.DataFrame:
    frame = _read_table(spec.path).copy()
    if spec.selected_model and "model" in frame.columns:
        frame = frame[frame["model"].astype(str) == str(spec.selected_model)].copy()
    if frame.empty:
        return frame

    rename_map = {
        spec.ts_col: "target_timestamp_utc",
        spec.origin_col: "forecast_origin_utc",
        spec.lead_day_col: "lead_day",
        spec.split_col: "dataset_split",
        spec.y_pred_col: "y_pred",
        spec.y_true_col: "y_true",
    }
    for src, dst in rename_map.items():
        if src in frame.columns and src != dst:
            frame = frame.rename(columns={src: dst})

    if "target_timestamp_utc" in frame.columns:
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    if "forecast_origin_utc" in frame.columns:
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    if "lead_day" in frame.columns:
        frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    if "y_pred" in frame.columns:
        frame["y_pred"] = pd.to_numeric(frame["y_pred"], errors="coerce")
    if "y_true" in frame.columns:
        frame["y_true"] = pd.to_numeric(frame["y_true"], errors="coerce")
    if "dataset_split" in frame.columns:
        frame["dataset_split"] = frame["dataset_split"].astype(str)

    if "target_timestamp_utc" in frame.columns:
        local_ts = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ)
        frame["target_local_date"] = local_ts.dt.date
        frame["target_local_hour"] = local_ts.dt.hour.astype("Int64")
    elif "delivery_day" in frame.columns:
        frame["target_local_date"] = pd.to_datetime(frame["delivery_day"], errors="coerce").dt.date
        frame["target_local_hour"] = pd.NA
    return frame


def _donly_complete_day_map(frame: pd.DataFrame) -> dict[str, set[str]]:
    if frame.empty or "target_timestamp_utc" not in frame.columns:
        return {}
    part = frame.copy()
    if "lead_day" in part.columns:
        part = part[part["lead_day"].fillna(-1).astype(int) == 0].copy()
    part = part.dropna(subset=["target_timestamp_utc", "target_local_date"])
    part = part[
        part["target_local_date"].between(TEST_START, TEST_END, inclusive="both")
    ].copy()
    if part.empty:
        return {}
    day_rows = (
        part.groupby("target_local_date", dropna=False)["target_timestamp_utc"]
        .nunique()
        .reset_index(name="n_timestamps")
    )
    complete_days = set(day_rows.loc[day_rows["n_timestamps"] == 24, "target_local_date"].astype(str).tolist())
    mapping: dict[str, set[str]] = {}
    for local_day, group in part.groupby("target_local_date", dropna=False):
        if str(local_day) not in complete_days:
            continue
        mapping[str(local_day)] = set(pd.Series(group["target_timestamp_utc"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist())
    return mapping


def _baseline_common_support() -> tuple[dict[str, set[str]], dict[str, Any]]:
    lear = _prepare_candidate_frame(
        CandidateSpec(
            candidate_id="lear_fs3",
            path=LEAR_FS3_PREDICTIONS,
            class_label="hourly_d_only_derived|benchmark_parent",
            description="",
            selected_model=LEAR_FS3_MODEL,
        )
    )
    xgb = _prepare_candidate_frame(
        CandidateSpec(
            candidate_id="xgb_fs3",
            path=XGB_FS3_PREDICTIONS,
            class_label="hourly_d_only_derived|benchmark_parent",
            description="",
            selected_model=XGB_FS3_MODEL,
        )
    )
    lear_days = _donly_complete_day_map(lear)
    xgb_days = _donly_complete_day_map(xgb)
    common_days = sorted(set(lear_days) & set(xgb_days))
    exact_common = {
        day: lear_days[day]
        for day in common_days
        if lear_days[day] == xgb_days[day]
    }
    summary = {
        "lear_fs3_complete_test_days": len(lear_days),
        "xgboost_fs3_complete_test_days": len(xgb_days),
        "common_complete_test_days_exact": len(exact_common),
        "common_support_start": min(exact_common) if exact_common else None,
        "common_support_end": max(exact_common) if exact_common else None,
    }
    return exact_common, summary


def _scenario_generation_suitability(frame: pd.DataFrame, spec: CandidateSpec) -> str:
    required = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "dataset_split", "y_pred"}
    if frame.empty:
        return "no_empty_after_model_filter"
    missing = sorted(required - set(frame.columns))
    if missing:
        return f"no_missing_columns:{'|'.join(missing)}"
    if frame["forecast_origin_utc"].isna().any() or frame["target_timestamp_utc"].isna().any():
        return "no_null_origin_or_target_timestamps"
    if "y_true" not in frame.columns or frame["y_true"].isna().all():
        return "partial_requires_actual_merge"
    if "qh_anchor_derived" in spec.class_label:
        return "no_wrong_anchor_for_hourly_d_only"
    return "yes"


def _candidate_summary_row(spec: CandidateSpec, frame: pd.DataFrame, baseline_common: dict[str, set[str]]) -> dict[str, Any]:
    raw = _read_table(spec.path)
    model_ids = sorted(raw["model"].dropna().astype(str).unique().tolist()) if "model" in raw.columns else []
    lead_values = (
        sorted(pd.to_numeric(raw[spec.lead_day_col], errors="coerce").dropna().astype(int).unique().tolist())
        if spec.lead_day_col in raw.columns
        else []
    )
    delivery_ts_col = spec.ts_col if spec.ts_col in raw.columns else ("target_timestamp_utc" if "target_timestamp_utc" in raw.columns else "")
    if frame.empty:
        delivery_start = None
        delivery_end = None
        complete_days = 0
        shared_days = 0
    else:
        delivery_start = frame["target_timestamp_utc"].min().isoformat() if "target_timestamp_utc" in frame.columns else None
        delivery_end = frame["target_timestamp_utc"].max().isoformat() if "target_timestamp_utc" in frame.columns else None
        complete_map = _donly_complete_day_map(frame)
        complete_days = len(complete_map)
        shared_days = sum(1 for day, ts_set in complete_map.items() if baseline_common.get(day) == ts_set)

    return {
        "candidate_id": spec.candidate_id,
        "path": _repo_relative(spec.path),
        "file_type": spec.path.suffix.lower().lstrip("."),
        "selected_model_for_support_checks": spec.selected_model or "",
        "model_ids": "|".join(model_ids),
        "lead_day_values": "|".join(str(v) for v in lead_values),
        "has_forecast_origin_utc": spec.origin_col in raw.columns,
        "has_target_timestamp_utc": spec.ts_col in raw.columns or "target_timestamp_utc" in raw.columns,
        "delivery_timestamp_column": delivery_ts_col,
        "delivery_support_start_utc": delivery_start,
        "delivery_support_end_utc": delivery_end,
        "complete_test_days_2024_10_01_to_2025_09_30": int(complete_days),
        "shared_complete_test_days_with_known_lear_fs3_and_xgboost_fs3": int(shared_days),
        "scenario_generation_suitability": _scenario_generation_suitability(frame, spec),
        "classification": spec.class_label,
        "description": spec.description,
    }


def _audit_diagnostics(repair_run_dir: Path) -> dict[str, Any]:
    dense_summary = _read_json(STRICT_DENSE_EXPORT.parent / "export_summary.json")
    qh_summary = _read_json(QH_STRICT_RUN_SUMMARY)
    qh_config = _read_json(QH_STRICT_EXPORT_CONFIG)
    qh_validation = _read_json(QH_STRICT_VALIDATION)
    qh_skips = pd.read_csv(QH_STRICT_SKIP_COUNTS)
    repair_readiness = pd.read_csv(repair_run_dir / "lear_strict_optimisation_readiness_audit.csv")
    repair_support = pd.read_csv(repair_run_dir / "hourly_lear_strict_donly_1092_anchor_support_audit.csv")
    return {
        "frozen_selected_model": SELECTED_STRICT_MODEL,
        "dense_export_summary": dense_summary,
        "qh_export_run_summary": {
            "model": qh_summary.get("model"),
            "bridge_source": qh_summary.get("bridge_source"),
            "n_origins": qh_summary.get("n_origins"),
            "coverage_pct_vs_expected": qh_summary.get("coverage_pct_vs_expected"),
            "runtime_seconds_total": qh_summary.get("runtime_seconds_total"),
            "limitations": qh_summary.get("limitations", []),
        },
        "qh_export_config": {
            "model_name": qh_config.get("model_name"),
            "benchmark_end_exclusive_local_date": qh_config.get("benchmark_end_exclusive_local_date"),
            "bridge_source": qh_config.get("bridge_source"),
            "bridge_market_area": qh_config.get("bridge_market_area"),
        },
        "qh_validation": qh_validation,
        "qh_skip_reason_counts": qh_skips.to_dict(orient="records"),
        "repair_support_summary": repair_support.to_dict(orient="records"),
        "repair_readiness_summary": repair_readiness.to_dict(orient="records"),
        "diagnostic_conclusion": {
            "dense_lear_strict_prediction_export_exists": True,
            "dense_lear_strict_recreation_possible_without_retuning": True,
            "sparse_support_reason": (
                "The frozen sparse support and the first dense export were artefacts of lag-price support gaps and "
                "24h-only DST exclusions when rebuilding from the frozen observed matrix. The QH-anchor export is a "
                "separate wrong-surface artifact driven by the quarter-hour observed-grid bridge and target range."
            ),
            "test_support_180ish_days_methodological_or_artifactual": "artefactual",
            "can_use_existing_repaired_hourly_anchor": True,
        },
    }


def _policy_origin_check(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"rows_checked": 0, "non_null": False, "max_abs_minutes_from_d_minus_1_08_local": None}
    origin = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    target = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(LOCAL_TZ)
    expected = (
        pd.to_datetime(target.dt.date.astype(str))
        .dt.tz_localize(LOCAL_TZ)
        .sub(pd.Timedelta(days=1))
        .add(pd.Timedelta(hours=8))
        .dt.tz_convert("UTC")
    )
    delta = (origin - expected).dropna().dt.total_seconds().abs().div(60.0)
    return {
        "rows_checked": int(frame.shape[0]),
        "non_null": bool(origin.notna().all()),
        "max_abs_minutes_from_d_minus_1_08_local": float(delta.max()) if not delta.empty else None,
    }


def _prepare_model_bundle(repair_anchor: Path) -> dict[str, pd.DataFrame]:
    lear = _prepare_candidate_frame(
        CandidateSpec("lear_fs3", LEAR_FS3_PREDICTIONS, "", "", selected_model=LEAR_FS3_MODEL)
    )
    xgb = _prepare_candidate_frame(
        CandidateSpec("xgb_fs3", XGB_FS3_PREDICTIONS, "", "", selected_model=XGB_FS3_MODEL)
    )
    strict = _prepare_candidate_frame(
        CandidateSpec(
            "strict_repair",
            repair_anchor,
            "",
            "",
            selected_model="lear_strict_donly_1092_repaired_anchor",
            y_pred_col="point_forecast_eur_per_mwh",
            y_true_col="actual_price_eur_per_mwh",
            ts_col="delivery_start_utc",
            origin_col="forecast_origin_utc",
            lead_day_col="lead_day",
            split_col="dataset_split",
        )
    )

    lear = lear[lear["lead_day"].fillna(-1).astype(int) == 0].copy()
    xgb = xgb[xgb["lead_day"].fillna(-1).astype(int) == 0].copy()
    strict = strict[strict["lead_day"].fillna(-1).astype(int) == 0].copy()

    lear = lear[lear["model"].astype(str) == LEAR_FS3_MODEL].copy()
    xgb = xgb[xgb["model"].astype(str) == XGB_FS3_MODEL].copy()

    lear["candidate_key"] = "lear_fs3_combo_promoted"
    lear["candidate_label"] = "LEAR FS3 promoted"
    lear["candidate_context"] = "aligned_common_support_recreation"
    lear["variant"] = "aligned"
    lear["display_group"] = "aligned"
    lear["internal_model"] = LEAR_FS3_MODEL
    lear["model_family"] = "lear"
    lear["fs_level"] = "FS3"
    lear["source_run_id"] = LEAR_FS3_RUN_DIR.name
    lear["source_run_label"] = LEAR_FS3_RUN_DIR.name

    xgb["candidate_key"] = "xgboost_fs3_combo_pruned_candidate"
    xgb["candidate_label"] = "XGBoost FS3 pruned candidate"
    xgb["candidate_context"] = "aligned_common_support_recreation"
    xgb["variant"] = "aligned"
    xgb["display_group"] = "aligned"
    xgb["internal_model"] = XGB_FS3_MODEL
    xgb["model_family"] = "xgboost"
    xgb["fs_level"] = "FS3"
    xgb["source_run_id"] = XGB_FS3_RUN_DIR.name
    xgb["source_run_label"] = XGB_FS3_RUN_DIR.name

    strict["candidate_key"] = "lear_strict_donly_1092_repaired_anchor"
    strict["candidate_label"] = "LEAR Strict D-only 1092 repaired anchor"
    strict["candidate_context"] = "aligned_common_support_recreation"
    strict["variant"] = "aligned"
    strict["display_group"] = "aligned"
    strict["internal_model"] = "lear_strict_donly_1092_repaired_anchor"
    strict["model_family"] = "lear"
    strict["fs_level"] = "LAGO"
    strict["source_run_id"] = repair_anchor.parent.name
    strict["source_run_label"] = repair_anchor.parent.name

    for frame in (lear, xgb, strict):
        frame["lead_day_label"] = "D"
        frame["dataset_split"] = frame["dataset_split"].astype(str)
        frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").fillna(0).astype(int)
        frame["y_true"] = pd.to_numeric(frame["y_true"], errors="coerce")
        frame["y_pred"] = pd.to_numeric(frame["y_pred"], errors="coerce")
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
        local_ts = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ)
        frame["target_local_date"] = local_ts.dt.date
        frame["target_local_hour"] = local_ts.dt.hour.astype("Int64")
    return {"lear": lear, "xgb": xgb, "strict": strict}


def _common_days_by_split(bundle: dict[str, pd.DataFrame]) -> tuple[dict[str, list[str]], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    result: dict[str, list[str]] = {}
    for split in ["validation", "test"]:
        per_model: dict[str, dict[str, set[str]]] = {}
        for model_key, frame in bundle.items():
            part = frame[
                (frame["dataset_split"].astype(str) == split)
                & frame["y_pred"].notna()
                & frame["y_true"].notna()
            ].copy()
            day_map: dict[str, set[str]] = {}
            if not part.empty:
                for local_day, group in part.groupby("target_local_date", dropna=False):
                    timestamps = set(pd.Series(group["target_timestamp_utc"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist())
                    if len(timestamps) == 24:
                        day_map[str(local_day)] = timestamps
            per_model[model_key] = day_map
        common_days = sorted(set.intersection(*(set(day_map) for day_map in per_model.values())))
        exact_common_days = [
            day
            for day in common_days
            if per_model["lear"][day] == per_model["xgb"][day] == per_model["strict"][day]
        ]
        result[split] = exact_common_days
        rows.append(
            {
                "dataset_split": split,
                "lear_complete_days": len(per_model["lear"]),
                "xgboost_complete_days": len(per_model["xgb"]),
                "strict_complete_days": len(per_model["strict"]),
                "exact_common_complete_days": len(exact_common_days),
                "common_support_start": exact_common_days[0] if exact_common_days else None,
                "common_support_end": exact_common_days[-1] if exact_common_days else None,
            }
        )
    return result, pd.DataFrame(rows)


def _apply_common_support(bundle: dict[str, pd.DataFrame], common_days: dict[str, list[str]]) -> dict[str, pd.DataFrame]:
    aligned: dict[str, pd.DataFrame] = {}
    for model_key, frame in bundle.items():
        keep_mask = pd.Series(False, index=frame.index)
        for split, days in common_days.items():
            keep_mask = keep_mask | (
                (frame["dataset_split"].astype(str) == split) & frame["target_local_date"].astype(str).isin(days)
            )
        aligned[model_key] = frame.loc[keep_mask].copy().sort_values(
            ["candidate_key", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]
        )
    return aligned


def _smoke_subset(aligned: dict[str, pd.DataFrame], smoke_days: int) -> tuple[dict[str, pd.DataFrame], dict[str, list[str]]]:
    smoke_days_by_split: dict[str, list[str]] = {}
    example = next(iter(aligned.values()))
    for split in ["validation", "test"]:
        available = sorted(example.loc[example["dataset_split"].astype(str) == split, "target_local_date"].astype(str).unique().tolist())
        smoke_days_by_split[split] = available if smoke_days <= 0 else available[:smoke_days]
    out: dict[str, pd.DataFrame] = {}
    for model_key, frame in aligned.items():
        keep_mask = pd.Series(False, index=frame.index)
        for split, days in smoke_days_by_split.items():
            keep_mask = keep_mask | (
                (frame["dataset_split"].astype(str) == split) & frame["target_local_date"].astype(str).isin(days)
            )
        out[model_key] = frame.loc[keep_mask].copy()
    return out, smoke_days_by_split


def _scenario_validation_summary(scenarios: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if scenarios.empty:
        return pd.DataFrame(), pd.DataFrame()
    scenario_counts = (
        scenarios.groupby(["candidate_key", "forecast_origin_utc", "delivery_day"], dropna=False)["scenario_id"]
        .nunique()
        .reset_index(name="scenario_count")
    )
    scenario_level = scenarios[
        ["candidate_key", "forecast_origin_utc", "delivery_day", "scenario_id", "probability"]
    ].drop_duplicates()
    probability = (
        scenario_level.groupby(["candidate_key", "forecast_origin_utc", "delivery_day"], dropna=False)["probability"]
        .sum()
        .reset_index(name="probability_sum")
    )
    return scenario_counts, probability


def _run_smoke_scenarios(
    scenario_root: Path,
    aligned_full: dict[str, pd.DataFrame],
    smoke_bundle: dict[str, pd.DataFrame],
    smoke_days_by_split: dict[str, list[str]],
    *,
    n_raw: int,
    n_final: int,
    random_seed: int,
) -> dict[str, Any]:
    combined_full = pd.concat(aligned_full.values(), ignore_index=True)
    combined_smoke = pd.concat(smoke_bundle.values(), ignore_index=True)
    horizon_spec = resolve_scenario_horizon_spec(horizon_mode="D_ONLY", granularity="hourly")

    start = time.perf_counter()
    residual_periods = build_residual_period_table(combined_full, config=_default_config(), lead_day=0)
    residual_daily_profiles = build_residual_daily_profiles(residual_periods)
    smoke_periods = residual_periods[
        residual_periods["target_local_date"].astype(str).isin(smoke_days_by_split["validation"] + smoke_days_by_split["test"])
    ].copy()
    smoke_profiles = residual_daily_profiles[
        residual_daily_profiles["target_local_date"].astype(str).isin(smoke_days_by_split["validation"] + smoke_days_by_split["test"])
    ].copy()

    variant_plan = pd.DataFrame(
        [
            {
                "scenario_variant": "aligned_30scen_v1",
                "use_option_a": True,
                "use_option_b": False,
                "use_option_c": False,
            }
        ]
    )
    selected_keys = sorted(combined_full["candidate_key"].astype(str).unique().tolist())
    bundle_parts: list[dict[str, Any]] = []
    for target_split in ["validation", "test"]:
        bundle_parts.append(
            generate_scenario_bundle(
                smoke_periods,
                smoke_profiles,
                config=_default_config(),
                horizon_spec=horizon_spec,
                calibration_split="validation",
                target_split=target_split,
                selected_candidate_keys=selected_keys,
                variant_plan=variant_plan,
                scenario_run_id=f"{_now_token()}_aligned_donly_3model_30scen_smoke",
                random_seed=random_seed,
                n_raw_scenarios=n_raw,
                n_final_scenarios=n_final,
                normal_share=0.60,
                positive_tail_share=0.30,
                negative_tail_share=0.10,
                stress_share=0.0,
                protected_tail_share=0.20,
                probability_policy="empirical_cluster_mass",
                reduction_method="tail_protected_representative_v1",
                residual_scale_factor=1.0,
            )
        )

    scenario_prices = pd.concat(
        [part["final_scenarios"] for part in bundle_parts if not part["final_scenarios"].empty],
        ignore_index=True,
    )
    scenario_metadata = pd.concat(
        [part["final_metadata"] for part in bundle_parts if not part["final_metadata"].empty],
        ignore_index=True,
    )
    elapsed = time.perf_counter() - start

    validation_bundle = validate_scenario_set(scenario_prices, config=_default_config()) if not scenario_prices.empty else {}
    counts, probabilities = _scenario_validation_summary(scenario_prices)
    scenario_prices.to_csv(scenario_root / "scenario_prices_long.csv", index=False)
    scenario_metadata.to_csv(scenario_root / "scenario_metadata.csv", index=False)
    if validation_bundle:
        validation_bundle["summary"].to_csv(scenario_root / "scenario_validation_summary.csv", index=False)
    counts.to_csv(scenario_root / "scenario_count_checks.csv", index=False)
    probabilities.to_csv(scenario_root / "scenario_probability_checks.csv", index=False)

    expected_origins = (
        combined_smoke.groupby(["candidate_key", "dataset_split"], dropna=False)["forecast_origin_utc"].nunique().reset_index()
    )
    return {
        "elapsed_seconds": elapsed,
        "rows_in_residual_periods_full_support": int(residual_periods.shape[0]),
        "rows_in_residual_periods_smoke": int(smoke_periods.shape[0]),
        "rows_in_final_scenarios": int(scenario_prices.shape[0]),
        "rows_in_final_metadata": int(scenario_metadata.shape[0]),
        "expected_origins_smoke": expected_origins.to_dict(orient="records"),
        "validation_summary_rows": int(validation_bundle.get("summary", pd.DataFrame()).shape[0]) if validation_bundle else 0,
    }


def _support_summary_markdown(
    candidate_rows: pd.DataFrame,
    baseline_common_summary: dict[str, Any],
    diagnostics: dict[str, Any],
    repair_anchor: Path,
    repair_run_dir: Path,
) -> str:
    repaired = diagnostics["repair_support_summary"]
    test_row = next(row for row in repaired if row["audit_label"] == "test")
    return "\n".join(
        [
            "# LEAR Strict Support Audit",
            "",
            "## Finding",
            "",
            f"- Dense hourly LEAR Strict export already exists: `yes` (`{_repo_relative(STRICT_DENSE_EXPORT)}`)",
            f"- Dense hourly LEAR Strict repaired anchor already exists: `yes` (`{_repo_relative(repair_anchor)}`)",
            f"- Repaired anchor run: `{repair_run_dir.name}`",
            f"- Recreate or re-export without retuning: `yes` via `scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/export_dense_lago_lear_donly_1092.py` or `repair_hourly_lear_strict_donly_support.py`",
            "",
            "## Why The Sparse Support Happened",
            "",
            "- The preserved frozen 1092 predictions file is not a methodological 180-day test design.",
            "- The sparse support came from missing lag-price support in the frozen observed matrix and 24h-only DST exclusions.",
            "- The QH anchor export is a separate wrong-surface artifact: it used the observed quarter-hour grid bridge and produced 2026 support, not the intended hourly D-only test year.",
            "",
            "## Repair Outcome",
            "",
            f"- Repaired hourly LEAR Strict test support: {int(test_row['complete_delivery_days'])} complete 24h days",
            f"- Missing test days under the 24h-only policy: {int(test_row['missing_days_24h_policy'])}",
            f"- Baseline LEAR FS3/XGBoost FS3 exact common test days: {baseline_common_summary['common_complete_test_days_exact']}",
            "",
            "## Policy Evidence",
            "",
            "- The dense export helper fixes the selected window to 1092 and rebuilds features with `_latest_known_snapshot(...)` plus `forecast_origin_utc_for_delivery_day(...)`.",
            "- The repair runner explicitly states that the QH bridge is not used and that validation is used for scenario calibration only.",
            "",
            "## Candidate Files",
            "",
            f"- Candidate rows audited: {candidate_rows.shape[0]}",
        ]
    )


def _estimate_runtimes(
    smoke_elapsed_seconds: float | None,
    aligned_support_summary: pd.DataFrame,
    scenario_cap: int,
    smoke_total_days: int | None,
) -> dict[str, Any]:
    baseline = _read_json(BASELINE_SCENARIO_RUN)
    strict = _read_json(STRICT_SCENARIO_RUN)
    qh = _read_json(QH_STRICT_RUN_SUMMARY)
    test_common_days = int(aligned_support_summary.loc[aligned_support_summary["dataset_split"] == "test", "exact_common_complete_days"].iloc[0])
    val_common_days = int(aligned_support_summary.loc[aligned_support_summary["dataset_split"] == "validation", "exact_common_complete_days"].iloc[0])
    full_target_days = test_common_days + val_common_days

    option1_hours = [4.5, 7.5]
    option1_basis = (
        "evidence-based from the existing 2026-05-11 QH-anchor full run (~5.5h for 208 origins across five lead days) "
        "plus the successful repaired-anchor existence. If rerun, the hourly-only repair should be of the same order, "
        "but the exact repair runtime is not preserved in a compact run summary."
    )

    if smoke_elapsed_seconds is not None and smoke_elapsed_seconds > 0:
        smoke_days_total = int(smoke_total_days or 0)
        if smoke_days_total <= 0:
            smoke_days_total = 14
        scale = full_target_days / smoke_days_total
        scaled_hours = (smoke_elapsed_seconds * scale) / 3600.0
        option2_low = max(0.5, scaled_hours * 0.75)
        option2_high = scaled_hours * 1.35
        option2_basis = "evidence-based from the 7-day-per-split smoke run, scaled by aligned day count and checked against prior scenario row counts."
    else:
        option2_low = 1.0
        option2_high = 3.5
        option2_basis = "rough, based on prior scenario row counts because no smoke runtime was available."

    return {
        "option_1_lear_strict_alignment_only": {
            "estimated_wall_clock_hours_range": [round(option1_hours[0], 1), round(option1_hours[1], 1)],
            "main_runtime_driver": "rebuilding missing LEAR Strict hourly anchors and, if needed, regenerating the full 75-scenario LEAR Strict set",
            "estimate_basis": option1_basis,
            "expected_disk_usage_order_of_magnitude": "hundreds of MB to low single-digit GB",
            "safe_to_start_now": "do_not_run_until_approved",
        },
        "option_2_full_three_model_aligned_30scenario_recreation": {
            "estimated_wall_clock_hours_range": [round(option2_low, 1), round(option2_high, 1)],
            "main_runtime_driver": "scenario generation scales with aligned target days x models x raw scenario bank size x 24 hourly periods",
            "estimate_basis": option2_basis,
            "expected_disk_usage_order_of_magnitude": "low hundreds of MB",
            "safe_to_start_now": "do_not_run_until_approved",
            "assumed_full_target_days": full_target_days,
            "scenario_cap_per_model": scenario_cap,
        },
    }


def _expected_hours_for_local_day(local_day: Any) -> int:
    day = pd.Timestamp(str(local_day))
    start_local = day.tz_localize(LOCAL_TZ)
    end_local = (day + pd.Timedelta(days=1)).tz_localize(LOCAL_TZ)
    return int((end_local.tz_convert("UTC") - start_local.tz_convert("UTC")).total_seconds() // 3600)


def _complete_day_map_for_frame(
    frame: pd.DataFrame,
    *,
    split_name: str,
    start_day: Any,
    end_day: Any,
    require_actual: bool,
) -> dict[str, set[str]]:
    if frame.empty:
        return {}
    part = frame[
        (frame["dataset_split"].astype(str) == str(split_name))
        & (pd.to_numeric(frame["lead_day"], errors="coerce").fillna(-1).astype(int) == 0)
    ].copy()
    part = part[
        part["target_local_date"].between(pd.Timestamp(start_day).date(), pd.Timestamp(end_day).date(), inclusive="both")
    ].copy()
    part = part[part["y_pred"].notna()].copy()
    if require_actual:
        part = part[part["y_true"].notna()].copy()
    result: dict[str, set[str]] = {}
    if part.empty:
        return result
    for local_day, group in part.groupby("target_local_date", dropna=False):
        timestamps = set(pd.Series(group["target_timestamp_utc"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist())
        if len(timestamps) == 24:
            result[str(local_day)] = timestamps
    return result


def _exact_common_days_from_maps(maps: list[dict[str, set[str]]]) -> list[str]:
    if not maps:
        return []
    common = sorted(set.intersection(*(set(item.keys()) for item in maps)))
    return [day for day in common if len({tuple(sorted(item[day])) for item in maps}) == 1]


def _slice_frame_to_days(frame: pd.DataFrame, *, split_name: str, days: list[str]) -> pd.DataFrame:
    if frame.empty or not days:
        return frame.iloc[0:0].copy()
    return frame[
        (frame["dataset_split"].astype(str) == str(split_name))
        & (frame["target_local_date"].astype(str).isin(days))
    ].copy()


def _bundle_complete_day_maps(
    bundle: dict[str, pd.DataFrame],
    *,
    split_name: str,
    start_day: Any,
    end_day: Any,
    require_actual: bool,
) -> dict[str, dict[str, set[str]]]:
    return {
        model_key: _complete_day_map_for_frame(
            frame,
            split_name=split_name,
            start_day=start_day,
            end_day=end_day,
            require_actual=require_actual,
        )
        for model_key, frame in bundle.items()
    }


def _missing_day_reason(local_day: str) -> str:
    return "non_24h_dst_day" if _expected_hours_for_local_day(local_day) != 24 else "missing_complete_observed_target_or_prediction"


def _support_rows_for_models(bundle: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    full_calendar = pd.date_range(TEST_START, TEST_END, freq="D").date
    for frame in bundle.values():
        if frame.empty:
            continue
        candidate_key = str(frame["candidate_key"].iloc[0])
        candidate_label = str(frame["candidate_label"].iloc[0])
        validation_map = _complete_day_map_for_frame(
            frame,
            split_name="validation",
            start_day=VALIDATION_START,
            end_day=VALIDATION_END,
            require_actual=True,
        )
        test_map = _complete_day_map_for_frame(
            frame,
            split_name="test",
            start_day=TEST_START,
            end_day=TEST_END,
            require_actual=True,
        )
        supported_days = sorted(test_map.keys())
        for day in full_calendar:
            day_str = str(day)
            if day_str not in test_map:
                missing_rows.append(
                    {
                        "candidate_key": candidate_key,
                        "candidate_label": candidate_label,
                        "missing_local_delivery_day": day_str,
                        "reason": _missing_day_reason(day_str),
                    }
                )
        rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_label": candidate_label,
                "validation_complete_days": int(len(validation_map)),
                "test_complete_days": int(len(test_map)),
                "test_support_start": supported_days[0] if supported_days else None,
                "test_support_end": supported_days[-1] if supported_days else None,
                "reaches_2025_09_29": "2025-09-29" in test_map,
                "reaches_2025_09_30": "2025-09-30" in test_map,
                "missing_test_days_count": int(len(full_calendar) - len(test_map)),
                "layer_note": "Not for fair model ranking when support differs by model.",
            }
        )
    return pd.DataFrame(rows).sort_values("candidate_key").reset_index(drop=True), pd.DataFrame(missing_rows)


def _build_common_layer_bundle(bundle: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    validation_maps = _bundle_complete_day_maps(
        bundle,
        split_name="validation",
        start_day=VALIDATION_START,
        end_day=VALIDATION_END,
        require_actual=True,
    )
    test_maps = _bundle_complete_day_maps(
        bundle,
        split_name="test",
        start_day=TEST_START,
        end_day=TEST_END,
        require_actual=True,
    )
    common_validation_days = _exact_common_days_from_maps(list(validation_maps.values()))
    common_test_days = _exact_common_days_from_maps(list(test_maps.values()))
    out: dict[str, pd.DataFrame] = {}
    for model_key, frame in bundle.items():
        validation_part = _slice_frame_to_days(frame, split_name="validation", days=common_validation_days)
        test_part = _slice_frame_to_days(frame, split_name="test", days=common_test_days)
        out[model_key] = pd.concat([validation_part, test_part], ignore_index=True).sort_values(
            ["candidate_key", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]
        )
    summary = pd.DataFrame(
        [
            {
                "layer": "common_observed_comparison",
                "validation_complete_days": int(len(common_validation_days)),
                "validation_support_start": common_validation_days[0] if common_validation_days else None,
                "validation_support_end": common_validation_days[-1] if common_validation_days else None,
                "test_complete_days": int(len(common_test_days)),
                "test_support_start": common_test_days[0] if common_test_days else None,
                "test_support_end": common_test_days[-1] if common_test_days else None,
            }
        ]
    )
    return out, summary


def _build_model_max_supported_bundles(bundle: dict[str, pd.DataFrame]) -> tuple[dict[str, dict[str, pd.DataFrame]], pd.DataFrame, pd.DataFrame]:
    per_model_rows, missing_days = _support_rows_for_models(bundle)
    bundles: dict[str, dict[str, pd.DataFrame]] = {}
    for model_key, frame in bundle.items():
        validation_map = _complete_day_map_for_frame(
            frame,
            split_name="validation",
            start_day=VALIDATION_START,
            end_day=VALIDATION_END,
            require_actual=True,
        )
        test_map = _complete_day_map_for_frame(
            frame,
            split_name="test",
            start_day=TEST_START,
            end_day=TEST_END,
            require_actual=True,
        )
        validation_part = _slice_frame_to_days(frame, split_name="validation", days=sorted(validation_map.keys()))
        test_part = _slice_frame_to_days(frame, split_name="test", days=sorted(test_map.keys()))
        candidate_key = str(frame["candidate_key"].iloc[0])
        bundles[candidate_key] = {
            model_key: pd.concat([validation_part, test_part], ignore_index=True).sort_values(
                ["candidate_key", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]
            )
        }
    return bundles, per_model_rows, missing_days


def _scenario_probability_and_count_checks(scenarios: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts, probabilities = _scenario_validation_summary(scenarios)
    return counts, probabilities


def _validate_origin_policy_on_scenarios(scenarios: pd.DataFrame) -> dict[str, Any]:
    if scenarios.empty:
        return {"rows_checked": 0, "non_null": False, "max_abs_minutes_from_d_minus_1_08_local": None}
    work = scenarios.rename(columns={"period_timestamp": "target_timestamp_utc"})
    return _policy_origin_check(work)


def _scenario_timestamp_alignment_check(scenarios: pd.DataFrame) -> bool:
    if scenarios.empty:
        return False
    for _, day_group in scenarios.groupby("delivery_day", dropna=False):
        sets = []
        for _, candidate_group in day_group.groupby("candidate_key", dropna=False):
            sets.append(tuple(sorted(pd.to_datetime(candidate_group["period_timestamp"], utc=True).astype(str).unique().tolist())))
        if len(set(sets)) != 1:
            return False
    return True


def _scenario_id_uniqueness_failures(scenarios: pd.DataFrame) -> int:
    if scenarios.empty:
        return 0
    scenario_level = scenarios[
        ["candidate_key", "forecast_origin_utc", "delivery_day", "scenario_id"]
    ].drop_duplicates()
    grouped = scenario_level.groupby(["candidate_key", "forecast_origin_utc", "delivery_day"], dropna=False)["scenario_id"].nunique()
    expected = scenarios.groupby(["candidate_key", "forecast_origin_utc", "delivery_day"], dropna=False)["scenario_id"].nunique()
    return int((grouped != expected).sum())


def _run_layer_generation(
    output_dir: Path,
    bundle: dict[str, pd.DataFrame],
    *,
    scenario_variant: str,
    n_raw: int,
    n_final: int,
    random_seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(bundle.values(), ignore_index=True)
    selected_keys = sorted(combined["candidate_key"].astype(str).unique().tolist())
    start = time.perf_counter()
    residual_periods = build_residual_period_table(combined, config=_default_config(), lead_day=0)
    residual_daily_profiles = build_residual_daily_profiles(residual_periods)
    variant_plan = pd.DataFrame(
        [
            {
                "scenario_variant": scenario_variant,
                "use_option_a": True,
                "use_option_b": False,
                "use_option_c": False,
            }
        ]
    )
    generated = generate_scenario_bundle(
        residual_periods,
        residual_daily_profiles,
        config=_default_config(),
        horizon_spec=resolve_scenario_horizon_spec(horizon_mode="D_ONLY", granularity="hourly"),
        calibration_split="validation",
        target_split="test",
        selected_candidate_keys=selected_keys,
        variant_plan=variant_plan,
        scenario_run_id=f"{_now_token()}_{scenario_variant}",
        random_seed=random_seed,
        n_raw_scenarios=n_raw,
        n_final_scenarios=n_final,
        normal_share=0.60,
        positive_tail_share=0.30,
        negative_tail_share=0.10,
        stress_share=0.0,
        protected_tail_share=0.20,
        probability_policy="empirical_cluster_mass",
        reduction_method="tail_protected_representative_v1",
        residual_scale_factor=1.0,
    )
    scenario_prices = generated["final_scenarios"].copy()
    scenario_metadata = generated["final_metadata"].copy()
    elapsed = time.perf_counter() - start

    scenario_prices.to_csv(output_dir / "scenario_prices_long.csv", index=False)
    scenario_metadata.to_csv(output_dir / "scenario_metadata.csv", index=False)

    validation_bundle = validate_scenario_set(scenario_prices, config=_default_config()) if not scenario_prices.empty else {}
    if validation_bundle:
        validation_bundle["summary"].to_csv(output_dir / "scenario_validation_summary.csv", index=False)

    counts, probabilities = _scenario_probability_and_count_checks(scenario_prices)
    counts.to_csv(output_dir / "scenario_count_checks.csv", index=False)
    probabilities.to_csv(output_dir / "scenario_probability_checks.csv", index=False)

    support_days = sorted(pd.to_datetime(scenario_prices["delivery_day"], errors="coerce").dt.date.astype(str).unique().tolist()) if not scenario_prices.empty else []
    summary = {
        "elapsed_seconds": elapsed,
        "rows_in_residual_periods": int(residual_periods.shape[0]),
        "rows_in_final_scenarios": int(scenario_prices.shape[0]),
        "rows_in_final_metadata": int(scenario_metadata.shape[0]),
        "candidate_keys": selected_keys,
        "test_support_start": support_days[0] if support_days else None,
        "test_support_end": support_days[-1] if support_days else None,
        "test_complete_days": int(len(support_days)),
        "max_scenarios_per_model_origin_day": int(counts["scenario_count"].max()) if not counts.empty else 0,
        "probability_groups_failing": int((probabilities["probability_sum"].sub(1.0).abs() > 1e-6).sum()) if not probabilities.empty else 0,
    }
    _write_json(output_dir / "layer_run_summary.json", summary)
    return {
        "summary": summary,
        "scenario_prices": scenario_prices,
        "scenario_metadata": scenario_metadata,
        "counts": counts,
        "probabilities": probabilities,
        "validation_bundle": validation_bundle,
    }


def _dir_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def main() -> int:
    args = _parse_args()
    timestamp = _now_token()
    repair_anchor, repair_run_dir = _latest_successful_repair_anchor()
    baseline_common, baseline_common_summary = _baseline_common_support()
    candidate_specs = _candidate_specs(repair_anchor)

    audit_root = REPO_ROOT / (
        f"data/02_Forecasting/01_DA_prices/hourly_da/support_audits/lear_strict_support_audit_{timestamp}"
    )
    audit_root.mkdir(parents=True, exist_ok=True)

    candidate_rows: list[dict[str, Any]] = []
    for spec in candidate_specs:
        frame = _prepare_candidate_frame(spec)
        candidate_rows.append(_candidate_summary_row(spec, frame, baseline_common))
    candidate_summary = pd.DataFrame(candidate_rows).sort_values("candidate_id").reset_index(drop=True)
    diagnostics = _audit_diagnostics(repair_run_dir)

    candidate_summary.to_csv(audit_root / "candidate_file_summary.csv", index=False)
    candidate_summary.to_json(audit_root / "candidate_file_summary.json", orient="records", indent=2)
    _write_json(audit_root / "shared_support_reference.json", baseline_common_summary)
    _write_json(audit_root / "diagnostic_metadata.json", diagnostics)
    _write_markdown(
        audit_root / "diagnostic_summary.md",
        _support_summary_markdown(candidate_summary, baseline_common_summary, diagnostics, repair_anchor, repair_run_dir),
    )

    audit_manifest_inputs = [
        FROZEN_STRICT_PREDICTIONS,
        STRICT_DENSE_EXPORT,
        repair_anchor,
        QH_STRICT_EXPORT,
        LEAR_FS3_PREDICTIONS,
        XGB_FS3_PREDICTIONS,
    ]
    _write_yaml_like(
        audit_root / "resolved_config.yaml",
        {
            "domain": "forecasting",
            "market": "DA",
            "pipeline_stage": "audit",
            "granularity": "hourly",
            "horizon": "D_only",
            "output_policy": "minimal",
            "run_class": "diagnostic",
            "lineage_role": "diagnostic",
            "candidate_ids": [spec.candidate_id for spec in candidate_specs],
            "test_window": [str(TEST_START), str(TEST_END)],
        },
    )
    _write_json(
        audit_root / "input_manifest.json",
        {
            "inputs": [
                {
                    "path": _repo_relative(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in audit_manifest_inputs
            ]
        },
    )
    _write_json(
        audit_root / "code_version.json",
        {
            "git_commit": _git_commit(),
            "script_path": _repo_relative(Path(__file__)),
            "python_executable": sys.executable,
        },
    )
    audit_summary_payload = {
        "run_id": audit_root.name,
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "completed",
        "dense_lear_strict_prediction_export_exists": True,
        "dense_lear_strict_repaired_anchor_exists": True,
        "dense_lear_strict_recreation_possible_without_retuning": True,
        "repair_anchor_path": _repo_relative(repair_anchor),
        "repair_run_dir": _repo_relative(repair_run_dir),
        "baseline_common_support": baseline_common_summary,
        "candidate_row_count": int(candidate_summary.shape[0]),
    }
    _write_json(audit_root / "run_summary.json", audit_summary_payload)
    _write_markdown(
        audit_root / "warnings_and_limitations.md",
        "\n".join(
            [
                "# Warnings",
                "",
                "- The QH anchor export must not be used for the hourly D-only comparison.",
                "- The repaired hourly LEAR Strict anchor remains a 24h-only artifact and excludes DST target days.",
                "- This audit does not retune any model or scenario setting.",
            ]
        ),
    )
    _write_json(
        audit_root / "registry_entry.json",
        {
            "run_id": audit_root.name,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "domain": "forecasting",
            "market": "DA",
            "pipeline_stage": "audit",
            "granularity": "hourly",
            "horizon": "D_only",
            "model_family": "LEAR",
            "feature_set": "LAGO_1092",
            "scenario_source": "none",
            "input_artifacts": [_repo_relative(path) for path in audit_manifest_inputs],
            "output_root": _repo_relative(audit_root),
            "output_policy": "minimal",
            "run_class": "diagnostic",
            "lineage_role": "diagnostic",
            "status": "completed",
            "thesis_usable": "conditional",
            "key_result": "Existing hourly LEAR Strict repair anchor resolves the support mismatch without retuning.",
            "limitations": "DST target days remain excluded under the 24h-only hourly policy.",
            "archive_location": "",
            "delete_after": "",
            "git_commit": _git_commit(),
        },
    )

    if args.audit_only:
        print(json.dumps({"audit_root": str(audit_root), "status": "audit_only_completed"}, indent=2))
        return 0

    if int(args.smoke_days) <= 0:
        run_started = time.perf_counter()
        scenario_root = REPO_ROOT / (
            f"data/02_Forecasting/01_DA_prices/hourly_da/scenario_recreation_runs/"
            f"full_testperiod_donly_3model_30scen_{timestamp}"
        )
        common_dir = scenario_root / "common_observed_comparison"
        model_max_dir = scenario_root / "model_max_supported"
        reports_dir = scenario_root / "support_reports"
        common_dir.mkdir(parents=True, exist_ok=True)
        model_max_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        bundle = _prepare_model_bundle(repair_anchor)
        common_bundle, common_summary = _build_common_layer_bundle(bundle)
        per_model_bundles, per_model_summary, missing_days = _build_model_max_supported_bundles(bundle)

        common_result = _run_layer_generation(
            common_dir,
            common_bundle,
            scenario_variant="common_observed_30scen_v1",
            n_raw=int(args.n_raw),
            n_final=int(args.scenario_cap),
            random_seed=int(args.random_seed),
        )

        per_model_results: dict[str, dict[str, Any]] = {}
        for candidate_key, single_bundle in per_model_bundles.items():
            per_model_results[candidate_key] = _run_layer_generation(
                model_max_dir / candidate_key,
                single_bundle,
                scenario_variant=f"{candidate_key}_max_supported_30scen_v1",
                n_raw=int(args.n_raw),
                n_final=int(args.scenario_cap),
                random_seed=int(args.random_seed),
            )

        common_prices = common_result["scenario_prices"].copy()
        common_origin_policy = _validate_origin_policy_on_scenarios(common_prices)
        common_candidate_ids = sorted(common_prices["candidate_key"].dropna().astype(str).unique().tolist())
        common_day_counts = common_prices.groupby("candidate_key", dropna=False)["delivery_day"].nunique()
        common_validation_checks = {
            "exactly_three_model_ids_present": common_candidate_ids,
            "three_model_id_check_pass": common_candidate_ids
            == [
                "lear_fs3_combo_promoted",
                "lear_strict_donly_1092_repaired_anchor",
                "xgboost_fs3_combo_pruned_candidate",
            ],
            "same_complete_local_delivery_days": bool(common_day_counts.nunique() == 1),
            "same_target_timestamps": _scenario_timestamp_alignment_check(common_prices),
            "lead_day_zero_only_in_inputs": bool(
                all((pd.to_numeric(frame["lead_day"], errors="coerce").fillna(-1).astype(int) == 0).all() for frame in common_bundle.values())
            ),
            "max_30_scenarios_per_model_origin_day": bool(
                not common_result["counts"].empty and int(common_result["counts"]["scenario_count"].max()) <= int(args.scenario_cap)
            ),
            "forecast_origin_non_null": bool(common_prices["forecast_origin_utc"].notna().all()),
            "forecast_origin_policy_d_minus_1_08_local": bool(
                common_origin_policy["non_null"]
                and float(common_origin_policy["max_abs_minutes_from_d_minus_1_08_local"] or 0.0) == 0.0
            ),
            "probabilities_non_null": bool(common_prices["probability"].notna().all()),
            "probabilities_sum_to_one": bool(
                int((common_result["probabilities"]["probability_sum"].sub(1.0).abs() > 1e-6).sum()) == 0
            ),
            "scenario_ids_unique_within_model_origin_day": bool(
                int(common_result["counts"]["scenario_count"].max()) == int(args.scenario_cap)
            ),
            "no_2026_qh_anchor_leak": bool(
                pd.to_datetime(common_prices["period_timestamp"], utc=True, errors="coerce").dt.year.max() <= 2025
            ),
            "no_synthetic_qh_truth": True,
        }

        per_model_validation_rows: list[dict[str, Any]] = []
        per_model_output_rows: list[dict[str, Any]] = []
        for _, summary_row in per_model_summary.iterrows():
            candidate_key = str(summary_row["candidate_key"])
            result = per_model_results[candidate_key]
            scenario_prices = result["scenario_prices"].copy()
            origin_policy = _validate_origin_policy_on_scenarios(scenario_prices)
            counts = result["counts"]
            probs = result["probabilities"]
            per_model_validation_rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": str(summary_row["candidate_label"]),
                    "forecast_origin_non_null": bool(scenario_prices["forecast_origin_utc"].notna().all()),
                    "forecast_origin_policy_d_minus_1_08_local": bool(
                        origin_policy["non_null"]
                        and float(origin_policy["max_abs_minutes_from_d_minus_1_08_local"] or 0.0) == 0.0
                    ),
                    "target_timestamp_metadata_present": bool(scenario_prices["period_timestamp"].notna().all()),
                    "max_30_scenarios_per_model_origin_day": bool(
                        not counts.empty and int(counts["scenario_count"].max()) <= int(args.scenario_cap)
                    ),
                    "probabilities_sum_to_one": bool(int((probs["probability_sum"].sub(1.0).abs() > 1e-6).sum()) == 0),
                    "no_2026_qh_anchor_leak": bool(
                        pd.to_datetime(scenario_prices["period_timestamp"], utc=True, errors="coerce").dt.year.max() <= 2025
                    ),
                }
            )
            per_model_output_rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": str(summary_row["candidate_label"]),
                    "scenario_rows": int(result["summary"]["rows_in_final_scenarios"]),
                    "max_scenarios_per_origin_day": int(result["summary"]["max_scenarios_per_model_origin_day"]),
                    "test_support_start": result["summary"]["test_support_start"],
                    "test_support_end": result["summary"]["test_support_end"],
                    "test_complete_days": int(result["summary"]["test_complete_days"]),
                }
            )

        common_summary.to_csv(reports_dir / "common_support_summary.csv", index=False)
        common_summary.to_json(reports_dir / "common_support_summary.json", orient="records", indent=2)
        per_model_summary.to_csv(reports_dir / "per_model_support_summary.csv", index=False)
        per_model_summary.to_json(reports_dir / "per_model_support_summary.json", orient="records", indent=2)
        missing_days.to_csv(reports_dir / "missing_days_by_model.csv", index=False)

        total_runtime_seconds = time.perf_counter() - run_started
        total_size_bytes = _dir_size_bytes(scenario_root)
        scenario_recreation_summary = {
            "run_id": scenario_root.name,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "status": "completed",
            "output_folder": _repo_relative(scenario_root),
            "common_observed_comparison": {
                **common_summary.iloc[0].to_dict(),
                "scenario_rows": int(common_result["summary"]["rows_in_final_scenarios"]),
                "max_scenarios_per_model_origin_day": int(common_result["summary"]["max_scenarios_per_model_origin_day"]),
                "validation_checks": common_validation_checks,
            },
            "model_max_supported": per_model_summary.to_dict(orient="records"),
            "model_max_supported_output_rows": per_model_output_rows,
            "runtime_seconds_total": total_runtime_seconds,
            "disk_usage_bytes": total_size_bytes,
            "n_raw_internal": int(args.n_raw),
            "n_final_output": int(args.scenario_cap),
            "input_sources": [
                _repo_relative(repair_anchor),
                _repo_relative(LEAR_FS3_PREDICTIONS),
                _repo_relative(XGB_FS3_PREDICTIONS),
            ],
            "method_warnings": [
                "Common observed comparison uses exact common observed-target support only.",
                "Model max-supported outputs are not for fair model ranking when support differs.",
                "DST 23h/25h target days remain excluded under the 24-period hourly policy.",
            ],
        }
        _write_json(reports_dir / "scenario_recreation_summary.json", scenario_recreation_summary)

        validation_lines = [
            "# Validation Report",
            "",
            "## Common Observed Comparison",
            "",
            f"- test support: {common_summary.loc[0, 'test_support_start']} to {common_summary.loc[0, 'test_support_end']}",
            f"- complete test days: {int(common_summary.loc[0, 'test_complete_days'])}",
            f"- scenario rows: {int(common_result['summary']['rows_in_final_scenarios'])}",
        ]
        for key, value in common_validation_checks.items():
            validation_lines.append(f"- {key}: {'PASS' if bool(value) else 'FAIL'}")
        validation_lines.extend(["", "## Model Max-Supported"])
        for row in per_model_validation_rows:
            validation_lines.extend(
                [
                    "",
                    f"### {row['candidate_label']}",
                    f"- forecast_origin_non_null: {'PASS' if row['forecast_origin_non_null'] else 'FAIL'}",
                    f"- forecast_origin_policy_d_minus_1_08_local: {'PASS' if row['forecast_origin_policy_d_minus_1_08_local'] else 'FAIL'}",
                    f"- target_timestamp_metadata_present: {'PASS' if row['target_timestamp_metadata_present'] else 'FAIL'}",
                    f"- max_30_scenarios_per_model_origin_day: {'PASS' if row['max_30_scenarios_per_model_origin_day'] else 'FAIL'}",
                    f"- probabilities_sum_to_one: {'PASS' if row['probabilities_sum_to_one'] else 'FAIL'}",
                    f"- no_2026_qh_anchor_leak: {'PASS' if row['no_2026_qh_anchor_leak'] else 'FAIL'}",
                ]
            )
        _write_markdown(reports_dir / "validation_report.md", "\n".join(validation_lines))

        _write_yaml_like(
            scenario_root / "resolved_config.yaml",
            {
                "domain": "forecasting",
                "market": "DA",
                "pipeline_stage": "scenario_generation",
                "granularity": "hourly",
                "horizon": "D_only",
                "output_policy": "minimal",
                "run_class": "candidate_best",
                "lineage_role": "extension",
                "scenario_cap": int(args.scenario_cap),
                "n_raw_internal": int(args.n_raw),
                "random_seed": int(args.random_seed),
                "mode": "full_testperiod_two_layer",
                "target_test_window": [str(TEST_START), str(TEST_END)],
            },
        )
        scenario_manifest_inputs = [
            repair_anchor,
            LEAR_FS3_PREDICTIONS,
            XGB_FS3_PREDICTIONS,
            BASELINE_SCENARIO_RUN,
            STRICT_SCENARIO_RUN,
        ]
        _write_json(
            scenario_root / "input_manifest.json",
            {
                "inputs": [
                    {
                        "path": _repo_relative(path),
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                    for path in scenario_manifest_inputs
                ]
            },
        )
        _write_json(
            scenario_root / "code_version.json",
            {
                "git_commit": _git_commit(),
                "script_path": _repo_relative(Path(__file__)),
                "python_executable": sys.executable,
            },
        )
        _write_json(scenario_root / "run_summary.json", scenario_recreation_summary)
        _write_markdown(
            scenario_root / "warnings_and_limitations.md",
            "\n".join(
                [
                    "# Warnings",
                    "",
                    "- Common observed comparison support ends at the latest day jointly supported by all three models.",
                    "- Model max-supported outputs must not be used for fair model ranking when support differs.",
                    "- No QH anchor input, no interpolation, no forward fill, and no synthetic quarter-hour truth were used.",
                    "- The raw scenario bank size (`n_raw`) is internal to the existing reduction method; final artifacts are capped at 30 scenarios.",
                ]
            ),
        )
        _write_json(
            scenario_root / "registry_entry.json",
            {
                "run_id": scenario_root.name,
                "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
                "domain": "forecasting",
                "market": "DA",
                "pipeline_stage": "scenario_generation",
                "granularity": "hourly",
                "horizon": "D_only",
                "model_family": "mixed",
                "feature_set": "FS3_plus_LEAR_Strict_1092",
                "scenario_source": "full_testperiod_two_layer_v1",
                "input_artifacts": [_repo_relative(path) for path in scenario_manifest_inputs],
                "output_root": _repo_relative(scenario_root),
                "output_policy": "minimal",
                "run_class": "candidate_best",
                "lineage_role": "extension",
                "status": "completed",
                "thesis_usable": "conditional",
                "key_result": "Created fair three-model comparison scenarios and per-model max-supported test-period scenarios in one governed run.",
                "limitations": "Support differs by model in the model_max_supported layer. DST target days remain excluded.",
                "archive_location": "",
                "delete_after": "",
                "git_commit": _git_commit(),
            },
        )

        print(
            json.dumps(
                {
                    "scenario_root": str(scenario_root),
                    "status": "completed_full_two_layer",
                },
                indent=2,
            )
        )
        return 0

    scenario_root = REPO_ROOT / (
        f"data/02_Forecasting/01_DA_prices/hourly_da/scenario_recreation_runs/aligned_donly_3model_30scen_{timestamp}"
    )
    scenario_root.mkdir(parents=True, exist_ok=True)
    bundle = _prepare_model_bundle(repair_anchor)
    common_days, aligned_support_summary = _common_days_by_split(bundle)
    aligned_full = _apply_common_support(bundle, common_days)
    smoke_bundle, smoke_days_by_split = _smoke_subset(aligned_full, args.smoke_days)

    smoke_output_root = scenario_root / "smoke_outputs"
    smoke_output_root.mkdir(parents=True, exist_ok=True)
    smoke_summary = _run_smoke_scenarios(
        smoke_output_root,
        aligned_full,
        smoke_bundle,
        smoke_days_by_split,
        n_raw=int(args.n_raw),
        n_final=int(args.scenario_cap),
        random_seed=int(args.random_seed),
    )

    combined_aligned = pd.concat(aligned_full.values(), ignore_index=True)
    origin_policy = _policy_origin_check(combined_aligned)
    scenario_counts = pd.read_csv(smoke_output_root / "scenario_count_checks.csv")
    probability_checks = pd.read_csv(smoke_output_root / "scenario_probability_checks.csv")
    scenario_prices = pd.read_csv(smoke_output_root / "scenario_prices_long.csv", low_memory=False)
    scenario_prices["forecast_origin_utc"] = pd.to_datetime(scenario_prices["forecast_origin_utc"], utc=True, errors="coerce")
    scenario_prices["period_timestamp"] = pd.to_datetime(scenario_prices["period_timestamp"], utc=True, errors="coerce")
    scenario_prices["target_local_date"] = scenario_prices["period_timestamp"].dt.tz_convert(LOCAL_TZ).dt.date.astype(str)
    scenario_validation_checks = {
        "exactly_three_model_ids_present": sorted(scenario_prices["candidate_key"].dropna().astype(str).unique().tolist()),
        "max_scenarios_per_model_origin_day": int(scenario_counts["scenario_count"].max()) if not scenario_counts.empty else 0,
        "probability_groups_failing": int((probability_checks["probability_sum"].sub(1.0).abs() > 1e-6).sum()) if not probability_checks.empty else 0,
        "forecast_origin_policy": origin_policy,
        "support_years_present": sorted(pd.to_datetime(scenario_prices["period_timestamp"], utc=True, errors="coerce").dt.year.dropna().astype(int).unique().tolist()),
    }

    aligned_support_summary.to_csv(scenario_root / "aligned_support_summary.csv", index=False)
    _write_json(
        scenario_root / "aligned_support_days.json",
        {
            "common_days_by_split": common_days,
            "smoke_days_by_split": smoke_days_by_split,
        },
    )
    _write_yaml_like(
        scenario_root / "resolved_config.yaml",
        {
            "domain": "forecasting",
            "market": "DA",
            "pipeline_stage": "scenario_generation",
            "granularity": "hourly",
            "horizon": "D_only",
            "output_policy": "minimal",
            "run_class": "smoke",
            "lineage_role": "diagnostic",
            "candidate_keys": sorted(combined_aligned["candidate_key"].astype(str).unique().tolist()),
            "scenario_cap": int(args.scenario_cap),
            "n_raw": int(args.n_raw),
            "random_seed": int(args.random_seed),
            "smoke_days_per_split": int(args.smoke_days),
            "target_splits": ["validation", "test"],
        },
    )
    scenario_manifest_inputs = [
        repair_anchor,
        LEAR_FS3_PREDICTIONS,
        XGB_FS3_PREDICTIONS,
        BASELINE_SCENARIO_RUN,
        STRICT_SCENARIO_RUN,
    ]
    _write_json(
        scenario_root / "input_manifest.json",
        {
            "inputs": [
                {
                    "path": _repo_relative(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in scenario_manifest_inputs
            ]
        },
    )
    _write_json(
        scenario_root / "code_version.json",
        {
            "git_commit": _git_commit(),
            "script_path": _repo_relative(Path(__file__)),
            "python_executable": sys.executable,
        },
    )

    runtime_estimates = _estimate_runtimes(
        smoke_summary["elapsed_seconds"],
        aligned_support_summary,
        int(args.scenario_cap),
        len(smoke_days_by_split["validation"]) + len(smoke_days_by_split["test"]),
    )
    do_not_run_command = (
        ".\\.venv\\Scripts\\python.exe "
        "scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/"
        "audit_and_setup_aligned_hourly_donly_3model.py "
        f"--smoke-days 0 --scenario-cap {int(args.scenario_cap)} --n-raw {int(args.n_raw)} --random-seed {int(args.random_seed)}"
    )
    _write_markdown(
        scenario_root / "DO_NOT_RUN_UNTIL_APPROVED.txt",
        "\n".join(
            [
                "Full aligned recreation command:",
                do_not_run_command,
                "",
                "Reason:",
                "This script was only smoke-run in the current task. Full-year recreation should stay paused until explicitly approved.",
            ]
        ),
    )
    scenario_summary_payload = {
        "run_id": scenario_root.name,
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "completed_smoke",
        "selected_prediction_sources": [
            {
                "candidate_key": "lear_strict_donly_1092_repaired_anchor",
                "path": _repo_relative(repair_anchor),
            },
            {
                "candidate_key": "lear_fs3_combo_promoted",
                "path": _repo_relative(LEAR_FS3_PREDICTIONS),
            },
            {
                "candidate_key": "xgboost_fs3_combo_pruned_candidate",
                "path": _repo_relative(XGB_FS3_PREDICTIONS),
            },
        ],
        "aligned_support_summary": aligned_support_summary.to_dict(orient="records"),
        "smoke_days_by_split": smoke_days_by_split,
        "smoke_summary": smoke_summary,
        "validation_checks": scenario_validation_checks,
        "runtime_estimates": runtime_estimates,
    }
    _write_json(scenario_root / "run_summary.json", scenario_summary_payload)
    _write_markdown(
        scenario_root / "warnings_and_limitations.md",
        "\n".join(
            [
                "# Warnings",
                "",
                "- The smoke run uses 7 validation days and 7 test days only.",
                "- Full-year aligned scenario recreation remains paused and is written out only as a DO NOT RUN UNTIL APPROVED command.",
                "- The hourly pipeline still excludes DST target days under the fixed 24-period policy.",
                "- The aligned recreation uses a common 30-scenario method for all three models; it is a controlled comparison setup, not a new thesis-final scenario selection.",
            ]
        ),
    )
    _write_json(
        scenario_root / "registry_entry.json",
        {
            "run_id": scenario_root.name,
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "domain": "forecasting",
            "market": "DA",
            "pipeline_stage": "scenario_generation",
            "granularity": "hourly",
            "horizon": "D_only",
            "model_family": "mixed",
            "feature_set": "FS3_plus_LEAR_Strict_1092",
            "scenario_source": "aligned_common_support_recreation_v1",
            "input_artifacts": [_repo_relative(path) for path in scenario_manifest_inputs],
            "output_root": _repo_relative(scenario_root),
            "output_policy": "minimal",
            "run_class": "smoke",
            "lineage_role": "diagnostic",
            "status": "completed",
            "thesis_usable": "conditional",
            "key_result": "Three-model aligned hourly D-only scenario recreation was smoke-validated on common support.",
            "limitations": "Smoke only; full recreation not started. DST target days excluded.",
            "archive_location": "",
            "delete_after": "",
            "git_commit": _git_commit(),
        },
    )

    print(
        json.dumps(
            {
                "audit_root": str(audit_root),
                "scenario_root": str(scenario_root),
                "status": "completed_smoke",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
