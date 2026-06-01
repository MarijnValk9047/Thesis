from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .lago_lear_config import LagoLearBenchmarkConfig
from .reporting import load_csv


def _load_run_predictions(run_path: Path) -> pd.DataFrame:
    if not run_path.exists():
        return pd.DataFrame()
    try:
        frame = load_csv(run_path, "predictions_long.csv")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    if frame.empty:
        return frame
    for column in ("forecast_origin_utc", "target_timestamp_utc"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    return frame


def load_existing_candidate_runs(config: LagoLearBenchmarkConfig) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for run_path in config.fs_candidate_run_paths:
        out[str(run_path.name)] = _load_run_predictions(run_path)
    return out


def _build_alignment_report(
    lago_predictions: pd.DataFrame,
    external_runs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if lago_predictions.empty:
        return pd.DataFrame()
    lago_keys = lago_predictions[["forecast_origin_utc", "target_timestamp_utc", "lead_day"]].drop_duplicates()
    for run_name, frame in external_runs.items():
        if frame.empty:
            rows.append(
                {
                    "run_name": run_name,
                    "status": "missing_or_empty",
                    "lago_rows": int(lago_predictions.shape[0]),
                    "external_rows": 0,
                    "overlap_keys": 0,
                    "overlap_pct_of_lago": 0.0,
                }
            )
            continue
        required = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "model", "y_pred"}
        if not required.issubset(set(frame.columns)):
            rows.append(
                {
                    "run_name": run_name,
                    "status": "missing_required_columns",
                    "lago_rows": int(lago_predictions.shape[0]),
                    "external_rows": int(frame.shape[0]),
                    "overlap_keys": 0,
                    "overlap_pct_of_lago": 0.0,
                }
            )
            continue
        ext_keys = frame[["forecast_origin_utc", "target_timestamp_utc", "lead_day"]].drop_duplicates()
        overlap = lago_keys.merge(ext_keys, on=["forecast_origin_utc", "target_timestamp_utc", "lead_day"], how="inner")
        overlap_count = int(overlap.shape[0])
        rows.append(
            {
                "run_name": run_name,
                "status": "comparable" if overlap_count > 0 else "not_comparable_no_overlap",
                "lago_rows": int(lago_predictions.shape[0]),
                "external_rows": int(frame.shape[0]),
                "overlap_keys": overlap_count,
                "overlap_pct_of_lago": float(overlap_count / max(int(lago_keys.shape[0]), 1) * 100.0),
            }
        )
    return pd.DataFrame(rows).sort_values("run_name").reset_index(drop=True)


def build_aligned_comparison_tables(
    lago_predictions: pd.DataFrame,
    external_runs: dict[str, pd.DataFrame],
    *,
    selected_weeks: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if lago_predictions.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    alignment_report = _build_alignment_report(lago_predictions, external_runs)
    comparable = alignment_report[alignment_report["status"] == "comparable"]["run_name"].tolist()
    if not comparable:
        return alignment_report, pd.DataFrame(), pd.DataFrame()

    lago_part = lago_predictions.copy()
    lago_part["model"] = lago_part["model"].astype(str)
    lago_part = lago_part[
        [
            "dataset_split",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "lead_day",
            "lead_day_label",
            "y_true",
            "y_pred",
            "model",
            "target_delivery_local_date",
        ]
    ].copy()

    external_join_parts: list[pd.DataFrame] = []
    for run_name in comparable:
        frame = external_runs[run_name].copy()
        frame["model"] = frame["model"].astype(str)
        if "dataset_split" not in frame.columns:
            frame["dataset_split"] = "unknown"
        if "lead_day_label" not in frame.columns:
            frame["lead_day_label"] = frame["lead_day"].map(lambda value: "D" if int(value) == 0 else f"D+{int(value)}")
        if "target_delivery_local_date" not in frame.columns:
            if "target_timestamp_utc" in frame.columns:
                frame["target_delivery_local_date"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True).dt.tz_convert("Europe/Amsterdam").dt.date
            else:
                frame["target_delivery_local_date"] = pd.NaT
        frame = frame[
            [
                "dataset_split",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "lead_day_label",
                "y_pred",
                "model",
                "target_delivery_local_date",
            ]
        ].copy()
        frame = frame.rename(columns={"y_pred": "y_pred_external", "model": "external_model"})
        frame["external_run_name"] = run_name
        external_join_parts.append(frame)

    external_all = pd.concat(external_join_parts, ignore_index=True)
    merged = lago_part.merge(
        external_all,
        on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "lead_day_label", "target_delivery_local_date"],
        how="inner",
    )
    if merged.empty:
        return alignment_report, pd.DataFrame(), pd.DataFrame()

    metric_rows: list[dict[str, Any]] = []
    for keys, group in merged.groupby(["dataset_split", "lead_day", "lead_day_label", "external_run_name", "external_model"], dropna=False):
        split_name, lead_day, lead_label, run_name, ext_model = keys
        valid = group[group["y_true"].notna() & group["y_pred"].notna() & group["y_pred_external"].notna()].copy()
        if valid.empty:
            continue
        err_lago = valid["y_pred"] - valid["y_true"]
        err_ext = valid["y_pred_external"] - valid["y_true"]
        metric_rows.append(
            {
                "dataset_split": split_name,
                "lead_day": int(lead_day),
                "lead_day_label": lead_label,
                "external_run_name": run_name,
                "external_model": ext_model,
                "observations": int(valid.shape[0]),
                "lago_mae": float(err_lago.abs().mean()),
                "external_mae": float(err_ext.abs().mean()),
                "delta_mae_external_minus_lago": float(err_ext.abs().mean() - err_lago.abs().mean()),
                "lago_rmse": float(np.sqrt((err_lago**2).mean())),
                "external_rmse": float(np.sqrt((err_ext**2).mean())),
                "delta_rmse_external_minus_lago": float(np.sqrt((err_ext**2).mean()) - np.sqrt((err_lago**2).mean())),
            }
        )
    comparison_metrics = pd.DataFrame(metric_rows).sort_values(
        ["dataset_split", "lead_day", "external_run_name", "external_model"]
    ).reset_index(drop=True)

    if selected_weeks is None or selected_weeks.empty:
        return alignment_report, comparison_metrics, pd.DataFrame()

    merged["target_delivery_local_date"] = pd.to_datetime(merged["target_delivery_local_date"], errors="coerce").dt.date
    week_rows: list[dict[str, Any]] = []
    for week in selected_weeks.to_dict(orient="records"):
        start_day = pd.Timestamp(week["week_start_local_date"]).date()
        end_day = pd.Timestamp(week["week_end_local_date"]).date()
        part = merged[
            (merged["target_delivery_local_date"] >= start_day)
            & (merged["target_delivery_local_date"] <= end_day)
        ].copy()
        if part.empty:
            continue
        for keys, group in part.groupby(["external_run_name", "external_model"], dropna=False):
            run_name, ext_model = keys
            valid = group[group["y_true"].notna() & group["y_pred"].notna() & group["y_pred_external"].notna()].copy()
            if valid.empty:
                continue
            err_lago = valid["y_pred"] - valid["y_true"]
            err_ext = valid["y_pred_external"] - valid["y_true"]
            week_rows.append(
                {
                    "category": week["category"],
                    "iso_week_id": week["iso_week_id"],
                    "week_start_local_date": week["week_start_local_date"],
                    "week_end_local_date": week["week_end_local_date"],
                    "external_run_name": run_name,
                    "external_model": ext_model,
                    "observations": int(valid.shape[0]),
                    "lago_mae": float(err_lago.abs().mean()),
                    "external_mae": float(err_ext.abs().mean()),
                    "delta_mae_external_minus_lago": float(err_ext.abs().mean() - err_lago.abs().mean()),
                }
            )
    week_metrics = pd.DataFrame(week_rows).sort_values(["category", "external_run_name", "external_model"]).reset_index(drop=True)
    return alignment_report, comparison_metrics, week_metrics
