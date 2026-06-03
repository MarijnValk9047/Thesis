from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .observed_deterministic import (
    _apply_zero_mean_correction_to_eval_frame,
    _build_observed_hourly_training_table,
    load_and_build_canonical_quarterhour_frame,
)
from .phase04 import _fit_mean_shape, _predict_mean_shape
from .phase05 import _enrich_hourly_anchor_frame, _expand_hourly_to_quarters


RUN_LABEL = "qh_model3_lear_strict"
MODEL_ID = "qh-fs1__mean_shape__hourly_anchor__lear_strict"
MODEL_FAMILY = "mean_shape"
FEATURE_SET_ID = "QH-FS1"
SOURCE_MODEL_NAME = "mean_shape_deviation"
DEFAULT_OBSERVED_RUN_ID = "20260503_174631_observed_market_deterministic_forecast"
DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID = "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run"


@dataclass(frozen=True)
class Model3Paths:
    run_id: str
    run_dir: Path


def model3_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def find_latest_qh_model3_run(config: QuarterHourDAExtensionConfig | None = None) -> Path | None:
    root = model3_output_root(config)
    if not root.exists():
        return None
    runs = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return runs[-1] if runs else None


def _timestamped_run_id(output_tag: str = "") -> str:
    base = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)
    cleaned = str(output_tag or "").strip()
    if not cleaned:
        return base
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in cleaned)
    return f"{base}_{safe}"


def _build_run_paths(config: QuarterHourDAExtensionConfig, output_tag: str = "") -> Model3Paths:
    run_id = _timestamped_run_id(output_tag=output_tag)
    run_dir = model3_output_root(config) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return Model3Paths(run_id=run_id, run_dir=run_dir)


def _resolve_observed_target_grid_path(config: QuarterHourDAExtensionConfig, observed_run_id: str | None) -> Path:
    run_id = str(observed_run_id or DEFAULT_OBSERVED_RUN_ID).strip()
    return config.output_root / "runs" / run_id / "targets_by_origin.csv"


def _resolve_lear_strict_anchor_path(config: QuarterHourDAExtensionConfig, anchor_run_id: str | None) -> Path:
    run_id = str(anchor_run_id or DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID).strip()
    return (
        config.hourly_da_output_root
        / "qh_anchor_exports"
        / "lear_strict_observed_qh_grid"
        / run_id
        / "predictions_long.csv"
    )


def _required_target_columns() -> list[str]:
    return [
        "dataset_split",
        "forecast_origin_utc",
        "forecast_origin_local",
        "delivery_start_local_date",
        "target_timestamp_utc",
        "target_timestamp_local",
        "target_date_local",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "lead_quarter_index",
        "quarter_of_day",
        "hour_of_day",
        "quarter_in_hour",
        "y_true",
        "is_observed_target",
        "expected_normal_target_count_per_origin",
        "actual_target_count_per_origin",
        "observed_target_count_per_origin",
        "target_count_status",
        "availability_status",
    ]


def _load_target_template(path: Path, *, timezone: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Observed target grid not found: {path}")
    frame = pd.read_csv(path, low_memory=False)
    if frame.empty:
        raise ValueError(f"Observed target grid is empty: {path}")
    missing = sorted(set(_required_target_columns()) - set(frame.columns))
    if missing:
        raise ValueError(f"Observed target grid missing required columns: {missing}")

    frame = frame.copy()
    frame["dataset_split"] = frame["dataset_split"].astype(str)
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    frame["target_timestamp_local"] = pd.to_datetime(frame["target_timestamp_local"], utc=True, errors="coerce")
    needs_local = frame["target_timestamp_local"].isna()
    if needs_local.any():
        frame.loc[needs_local, "target_timestamp_local"] = frame.loc[needs_local, "target_timestamp_utc"]
    frame["target_timestamp_local"] = frame["target_timestamp_local"].dt.tz_convert(timezone)
    frame["target_date_local"] = frame["target_timestamp_local"].dt.date
    frame["delivery_start_local_date"] = pd.to_datetime(frame["delivery_start_local_date"], errors="coerce").dt.date
    frame["lead_day"] = pd.to_numeric(frame["lead_day"], errors="coerce").astype("Int64")
    frame["lead_day_label"] = frame["lead_day_label"].astype(str)
    frame["horizon_index"] = pd.to_numeric(frame["horizon_index"], errors="coerce").astype("Int64")
    frame["lead_quarter_index"] = pd.to_numeric(frame["lead_quarter_index"], errors="coerce").astype("Int64")
    frame["quarter_of_day"] = pd.to_numeric(frame["quarter_of_day"], errors="coerce").astype("Int64")
    frame["hour_of_day"] = pd.to_numeric(frame["hour_of_day"], errors="coerce").astype("Int64")
    frame["quarter_in_hour"] = pd.to_numeric(frame["quarter_in_hour"], errors="coerce").astype("Int64")
    frame["y_true"] = pd.to_numeric(frame["y_true"], errors="coerce")
    frame["is_observed_target"] = frame["is_observed_target"].fillna(False).astype(bool)
    return frame.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)


def _load_hourly_anchor_predictions(path: Path, *, timezone: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"LEAR_STRICT hourly anchor file not found: {path}")
    anchors = pd.read_csv(path, low_memory=False)
    required = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred", "dataset_split"}
    missing = sorted(required - set(anchors.columns))
    if missing:
        raise ValueError(f"LEAR_STRICT anchor file missing required columns: {missing}")

    anchors = anchors.copy()
    anchors["forecast_origin_utc"] = pd.to_datetime(anchors["forecast_origin_utc"], utc=True, errors="coerce")
    anchors["target_timestamp_utc"] = pd.to_datetime(anchors["target_timestamp_utc"], utc=True, errors="coerce")
    anchors["lead_day"] = pd.to_numeric(anchors["lead_day"], errors="coerce").astype("Int64")
    anchors["y_pred"] = pd.to_numeric(anchors["y_pred"], errors="coerce")
    anchors["dataset_split"] = anchors["dataset_split"].astype(str)
    anchors = anchors.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred"]).copy()
    anchors = anchors.rename(columns={"target_timestamp_utc": "hour_start_utc", "y_pred": "hourly_anchor_price_eur_per_mwh"})
    anchors["hour_start_local"] = anchors["hour_start_utc"].dt.tz_convert(timezone)
    anchors["delivery_local_date"] = anchors["hour_start_local"].dt.date
    anchors["local_hour_of_day"] = anchors["hour_start_local"].dt.hour.astype(int)
    anchors["lead_day_label"] = anchors["lead_day"].map(lambda v: "D" if v == 0 else f"D+{int(v)}")
    return anchors.sort_values(["dataset_split", "forecast_origin_utc", "hour_start_utc"]).reset_index(drop=True)


def _subset_origins(frame: pd.DataFrame, max_origins: int | None) -> pd.DataFrame:
    if max_origins is None:
        return frame
    if max_origins <= 0:
        raise ValueError("--max-origins must be positive.")
    origin_schedule = (
        frame[["dataset_split", "forecast_origin_utc"]]
        .drop_duplicates()
        .sort_values(["dataset_split", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    selected = origin_schedule.head(int(max_origins))
    return frame.merge(selected, on=["dataset_split", "forecast_origin_utc"], how="inner")


def _build_modeling_table(
    *,
    target_template: pd.DataFrame,
    hourly_anchors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = _enrich_hourly_anchor_frame(hourly_anchors.copy())
    hourly["horizon_index"] = hourly.get("horizon_index", pd.NA)
    expanded = _expand_hourly_to_quarters(
        hourly,
        source_type="lear_strict_hourly_anchor",
        shape_method="mean_shape_deviation",
        scenario_variant="observed_market_deterministic",
    )
    expanded = expanded.rename(columns={"timestamp_utc": "target_timestamp_utc", "quarter_index": "quarter_index_anchor"})
    expanded["target_timestamp_utc"] = pd.to_datetime(expanded["target_timestamp_utc"], utc=True, errors="coerce")
    expanded["forecast_origin_utc"] = pd.to_datetime(expanded["forecast_origin_utc"], utc=True, errors="coerce")
    expanded["lead_day"] = pd.to_numeric(expanded["lead_day"], errors="coerce").astype("Int64")
    expanded["dataset_split"] = expanded["dataset_split"].astype(str)

    model_table = expanded.merge(
        target_template[
            [
                "dataset_split",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "forecast_origin_local",
                "delivery_start_local_date",
                "target_timestamp_local",
                "target_date_local",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "lead_quarter_index",
                "quarter_of_day",
                "hour_of_day",
                "quarter_in_hour",
                "y_true",
                "is_observed_target",
                "expected_normal_target_count_per_origin",
                "actual_target_count_per_origin",
                "observed_target_count_per_origin",
                "target_count_status",
                "availability_status",
            ]
        ],
        on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"],
        how="inner",
        suffixes=("", "_target"),
    )
    model_table["quarter_index"] = pd.to_numeric(model_table["quarter_index_anchor"], errors="coerce").astype("Int64")
    model_table["hourly_backbone_forecast_eur_per_mwh"] = pd.to_numeric(model_table["hourly_anchor_price_eur_per_mwh"], errors="coerce")
    model_table["horizon_index"] = pd.to_numeric(model_table["horizon_index"], errors="coerce").astype("Int64")
    model_table = model_table.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    return model_table, expanded


def _build_coverage_gap_report(target_template: pd.DataFrame, model_table: pd.DataFrame) -> pd.DataFrame:
    keys = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"]
    expected = target_template[keys].drop_duplicates().copy()
    covered = model_table[keys].drop_duplicates().copy()
    merged = expected.merge(covered.assign(has_anchor=True), on=keys, how="left")
    merged["has_anchor"] = merged["has_anchor"].fillna(False).astype(bool)
    missing = merged[~merged["has_anchor"]].copy()
    if missing.empty:
        return pd.DataFrame(columns=keys + ["gap_reason"])
    missing["gap_reason"] = "missing_hourly_anchor_for_target_hour"
    return missing.sort_values(keys).reset_index(drop=True)


def _fit_predict_model3(
    *,
    model_table: pd.DataFrame,
    training_table: pd.DataFrame,
    run_id: str,
    anchor_run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prediction_frames: list[pd.DataFrame] = []
    timing_rows: list[dict[str, Any]] = []

    for forecast_origin_utc, origin_frame in model_table.groupby("forecast_origin_utc", dropna=False):
        origin_ts = pd.Timestamp(forecast_origin_utc)
        ordered = origin_frame.sort_values("target_timestamp_utc").reset_index(drop=True)
        train_rows = training_table[training_table["known_at_utc"] <= origin_ts].copy()
        train_rows = train_rows[pd.to_numeric(train_rows["delta_eur_per_mwh"], errors="coerce").notna()].reset_index(drop=True)

        fit_start = time.perf_counter()
        state = _fit_mean_shape(train_rows) if not train_rows.empty else None
        fit_time = time.perf_counter() - fit_start

        predict_start = time.perf_counter()
        if state is None or ordered.empty:
            predicted = ordered.copy()
            predicted["y_pred"] = np.nan
            predicted["delta_pred_adjusted"] = np.nan
            predicted["predicted_delta_zero_mean_abs"] = np.nan
            prediction_available = False
            unavailable_reason = "no_train_rows_available"
        else:
            delta_pred_raw = _predict_mean_shape(state, ordered)
            predicted = _apply_zero_mean_correction_to_eval_frame(ordered, delta_pred_raw)
            prediction_available = True
            unavailable_reason = ""
        predict_time = time.perf_counter() - predict_start

        predicted["run_id"] = run_id
        predicted["source_run_id"] = run_id
        predicted["model_id"] = MODEL_ID
        predicted["model"] = MODEL_ID
        predicted["model_family"] = MODEL_FAMILY
        predicted["feature_set_id"] = FEATURE_SET_ID
        predicted["fs_layer"] = FEATURE_SET_ID
        predicted["fs_level"] = FEATURE_SET_ID
        predicted["candidate_role"] = "candidate_equal_priority"
        predicted["horizon_day"] = predicted["lead_day"]
        predicted["actual_price_eur_per_mwh"] = pd.to_numeric(predicted["y_true"], errors="coerce")
        predicted["forecast_price_eur_per_mwh"] = pd.to_numeric(predicted["y_pred"], errors="coerce")
        predicted["hourly_anchor_candidate_key"] = "lear_strict"
        predicted["hourly_anchor_candidate_label"] = "LEAR_STRICT anchor export"
        predicted["hourly_anchor_role"] = "hourly_level_model_selected_on_three_way_overlap"
        predicted["source_type"] = "model3_lear_strict_hourly_anchor"
        predicted["source_model_name"] = SOURCE_MODEL_NAME
        predicted["fit_time_sec"] = float(fit_time)
        predicted["predict_time_sec"] = float(predict_time)
        predicted["prediction_available"] = bool(prediction_available)
        predicted["unavailable_reason"] = unavailable_reason
        predicted["anchor_run_id"] = anchor_run_id
        prediction_frames.append(predicted)

        timing_rows.append(
            {
                "forecast_origin_utc": origin_ts,
                "dataset_split": str(ordered["dataset_split"].iloc[0]) if not ordered.empty else None,
                "train_rows": int(train_rows.shape[0]),
                "fit_time_sec": float(fit_time),
                "predict_time_sec": float(predict_time),
                "prediction_available": bool(prediction_available),
                "unavailable_reason": unavailable_reason,
            }
        )

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        .sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
        if prediction_frames
        else pd.DataFrame()
    )
    timing = pd.DataFrame(timing_rows).sort_values(["dataset_split", "forecast_origin_utc"]).reset_index(drop=True) if timing_rows else pd.DataFrame()
    return predictions, timing


def _normalize_predictions_for_export(predictions: pd.DataFrame, *, business_timezone: str) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()
    out = predictions.copy()
    out["forecast_origin_utc"] = pd.to_datetime(out["forecast_origin_utc"], utc=True, errors="coerce")
    out["target_timestamp_utc"] = pd.to_datetime(out["target_timestamp_utc"], utc=True, errors="coerce")
    out["target_timestamp_local"] = pd.to_datetime(out["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(business_timezone)
    out["delivery_local_date"] = out["target_timestamp_local"].dt.date
    out["lead_day"] = pd.to_numeric(out["lead_day"], errors="coerce").astype("Int64")
    out["lead_day_label"] = out["lead_day"].map(lambda v: "D" if v == 0 else f"D+{int(v)}" if pd.notna(v) else None)
    out["quarter_index"] = pd.to_numeric(out["quarter_index"], errors="coerce").astype("Int64")
    out["horizon_index"] = pd.to_numeric(out["horizon_index"], errors="coerce").astype("Int64")
    iso = out["target_timestamp_local"].dt.isocalendar()
    out["frozen_week_id"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    out["dataset_split"] = out["dataset_split"].astype(str)
    out["is_observed_target"] = out["is_observed_target"].fillna(False).astype(bool)
    out["y_true"] = pd.to_numeric(out["y_true"], errors="coerce")
    out["y_pred"] = pd.to_numeric(out["y_pred"], errors="coerce")
    out["actual_price_eur_per_mwh"] = pd.to_numeric(out["actual_price_eur_per_mwh"], errors="coerce")
    out["forecast_price_eur_per_mwh"] = pd.to_numeric(out["forecast_price_eur_per_mwh"], errors="coerce")
    return out


def _support_tables(
    *,
    target_template: pd.DataFrame,
    model_table: pd.DataFrame,
    predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    expected = target_template[["dataset_split", "lead_day", "target_timestamp_utc"]].groupby(
        ["dataset_split", "lead_day"], dropna=False
    ).size().reset_index(name="expected_rows")
    anchored = model_table[["dataset_split", "lead_day", "target_timestamp_utc"]].groupby(
        ["dataset_split", "lead_day"], dropna=False
    ).size().reset_index(name="anchor_rows")
    predicted = predictions[predictions["y_pred"].notna()][["dataset_split", "lead_day", "target_timestamp_utc"]].groupby(
        ["dataset_split", "lead_day"], dropna=False
    ).size().reset_index(name="predicted_rows")

    by_split_lead = expected.merge(anchored, on=["dataset_split", "lead_day"], how="left").merge(
        predicted, on=["dataset_split", "lead_day"], how="left"
    )
    by_split_lead[["anchor_rows", "predicted_rows"]] = by_split_lead[["anchor_rows", "predicted_rows"]].fillna(0).astype(int)
    by_split_lead["anchor_coverage_pct"] = np.where(
        by_split_lead["expected_rows"] > 0,
        by_split_lead["anchor_rows"] / by_split_lead["expected_rows"] * 100.0,
        np.nan,
    )
    by_split_lead["prediction_coverage_pct"] = np.where(
        by_split_lead["expected_rows"] > 0,
        by_split_lead["predicted_rows"] / by_split_lead["expected_rows"] * 100.0,
        np.nan,
    )
    by_split_lead = by_split_lead.sort_values(["dataset_split", "lead_day"]).reset_index(drop=True)

    by_split = (
        by_split_lead.groupby("dataset_split", as_index=False)[["expected_rows", "anchor_rows", "predicted_rows"]]
        .sum()
        .sort_values("dataset_split")
        .reset_index(drop=True)
    )
    by_split["anchor_coverage_pct"] = np.where(by_split["expected_rows"] > 0, by_split["anchor_rows"] / by_split["expected_rows"] * 100.0, np.nan)
    by_split["prediction_coverage_pct"] = np.where(
        by_split["expected_rows"] > 0, by_split["predicted_rows"] / by_split["expected_rows"] * 100.0, np.nan
    )
    return by_split, by_split_lead


def _zero_mean_validation(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    grouped = (
        predictions.groupby(["dataset_split", "forecast_origin_utc", "hour_start_utc"], dropna=False)
        .agg(
            n_quarters=("target_timestamp_utc", "size"),
            mean_pred_qh=("y_pred", "mean"),
            anchor_hourly=("hourly_backbone_forecast_eur_per_mwh", "first"),
        )
        .reset_index()
    )
    grouped["abs_mean_minus_anchor"] = (pd.to_numeric(grouped["mean_pred_qh"], errors="coerce") - pd.to_numeric(grouped["anchor_hourly"], errors="coerce")).abs()
    grouped["zero_mean_pass"] = grouped["abs_mean_minus_anchor"] <= 1e-8
    return grouped.sort_values(["dataset_split", "forecast_origin_utc", "hour_start_utc"]).reset_index(drop=True)


def _write_model3_methodology_note(path: Path) -> None:
    note = [
        "# QH Model 3 Methodology Note",
        "",
        "- Model id: `qh-fs1__mean_shape__hourly_anchor__lear_strict`",
        "- Construction: `p_hat_qh = p_hat_hourly(LEAR_STRICT) + delta_hat_qh`.",
        "- Deviation model: mean-shape deviation fitted on observed quarter-hour deltas available at each forecast origin.",
        "- Leakage guard: per-origin training rows satisfy `known_at_utc <= forecast_origin_utc` via canonical observed frame known_at convention.",
        "- Zero-mean correction: per-hour quarter predictions are centered so the hourly mean equals the LEAR_STRICT hourly anchor.",
        "- Scoring policy: observed-target-only (`y_true` remains NaN on non-observed rows).",
        "",
        "This run preserves LEAR_STRICT anchor values; only quarter-hour intra-hour deviations are added.",
    ]
    path.write_text("\n".join(note) + "\n", encoding="utf-8")


def run_qh_model3_lear_strict(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    output_tag: str = "",
    check_only: bool = False,
    max_origins: int | None = None,
    observed_run_id: str | None = None,
    anchor_run_id: str | None = None,
) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    paths = _build_run_paths(resolved, output_tag=output_tag)
    t0 = time.perf_counter()

    target_path = _resolve_observed_target_grid_path(resolved, observed_run_id=observed_run_id)
    anchor_path = _resolve_lear_strict_anchor_path(resolved, anchor_run_id=anchor_run_id)
    target_template = _load_target_template(target_path, timezone=resolved.business_timezone)
    hourly_anchor = _load_hourly_anchor_predictions(anchor_path, timezone=resolved.business_timezone)

    target_template = _subset_origins(target_template, max_origins=max_origins)
    hourly_anchor = _subset_origins(hourly_anchor, max_origins=max_origins)

    # Keep only quarter-hour rows that belong to supported anchored hours.
    model_table, expanded_hourly = _build_modeling_table(target_template=target_template, hourly_anchors=hourly_anchor)
    gap_report = _build_coverage_gap_report(target_template, model_table)

    check_summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "mode": "check_only" if check_only else "run",
        "target_grid_path": str(target_path),
        "anchor_predictions_path": str(anchor_path),
        "target_rows": int(target_template.shape[0]),
        "hourly_anchor_rows": int(hourly_anchor.shape[0]),
        "expanded_hourly_rows": int(expanded_hourly.shape[0]),
        "aligned_qh_rows": int(model_table.shape[0]),
        "coverage_pct": float(model_table.shape[0] / target_template.shape[0] * 100.0) if not target_template.empty else 0.0,
        "missing_qh_rows": int(gap_report.shape[0]),
        "max_origins": max_origins,
        "anchor_run_id": str(anchor_run_id or DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID),
        "model_id": MODEL_ID,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }

    if check_only:
        (paths.run_dir / "run_summary.json").write_text(json.dumps(check_summary, indent=2), encoding="utf-8")
        gap_report.to_csv(paths.run_dir / "coverage_gap_report.csv", index=False)
        _write_model3_methodology_note(paths.run_dir / "model3_methodology_note.md")
        return paths.run_dir

    canonical_quarterhour_frame, _, _ = load_and_build_canonical_quarterhour_frame(resolved)
    training_table = _build_observed_hourly_training_table(canonical_quarterhour_frame)
    predictions, timing = _fit_predict_model3(
        model_table=model_table,
        training_table=training_table,
        run_id=paths.run_id,
        anchor_run_id=str(anchor_run_id or DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID),
    )
    predictions = _normalize_predictions_for_export(predictions, business_timezone=resolved.business_timezone)

    expected_key_cols = ["forecast_origin_utc", "target_timestamp_utc", "lead_day", "model_id"]
    duplicate_count = int(predictions.duplicated(subset=expected_key_cols).sum()) if not predictions.empty else 0
    non_null_pred = int(predictions["y_pred"].notna().sum()) if not predictions.empty else 0
    zero_mean = _zero_mean_validation(predictions[predictions["y_pred"].notna()].copy())
    support_by_split, support_by_split_lead = _support_tables(
        target_template=target_template,
        model_table=model_table,
        predictions=predictions,
    )

    predictions.to_csv(paths.run_dir / "predictions_long.csv", index=False)
    try:
        predictions.to_parquet(paths.run_dir / "predictions_long.parquet", index=False)
    except Exception:
        pass
    support_by_split.to_csv(paths.run_dir / "support_by_split.csv", index=False)
    support_by_split_lead.to_csv(paths.run_dir / "support_by_lead_day.csv", index=False)
    zero_mean.to_csv(paths.run_dir / "zero_mean_validation.csv", index=False)
    gap_report.to_csv(paths.run_dir / "coverage_gap_report.csv", index=False)
    timing.to_csv(paths.run_dir / "origin_timing.csv", index=False)
    _write_model3_methodology_note(paths.run_dir / "model3_methodology_note.md")

    elapsed = time.perf_counter() - t0
    run_summary = {
        **check_summary,
        "status": "completed",
        "n_predictions_rows": int(predictions.shape[0]),
        "n_predictions_non_null": non_null_pred,
        "duplicate_key_count": duplicate_count,
        "zero_mean_rows": int(zero_mean.shape[0]),
        "zero_mean_pass_rows": int(zero_mean["zero_mean_pass"].sum()) if not zero_mean.empty else 0,
        "zero_mean_pass_pct": float(zero_mean["zero_mean_pass"].mean() * 100.0) if not zero_mean.empty else np.nan,
        "runtime_seconds_total": float(elapsed),
        "observed_target_rows_scored": int(predictions["y_true"].notna().sum()),
        "prediction_rows_scored": int((predictions["y_true"].notna() & predictions["y_pred"].notna()).sum()),
        "model_logic_changed_from_lear_strict": False,
        "notes": [
            "Model 3 keeps LEAR_STRICT hourly anchors fixed and adds mean-shape quarter-hour deviations.",
            "Zero-mean per-hour correction enforces hourly-anchor preservation.",
            "Observed-target-only policy is preserved for scoring fields.",
        ],
    }
    (paths.run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return paths.run_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QH_MODEL_3 using LEAR_STRICT hourly anchor + zero-mean mean-shape deviation.")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--max-origins", type=int, default=None)
    parser.add_argument("--output-tag", type=str, default="")
    parser.add_argument("--observed-run-id", type=str, default=DEFAULT_OBSERVED_RUN_ID)
    parser.add_argument("--anchor-run-id", type=str, default=DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = run_qh_model3_lear_strict(
        QuarterHourDAExtensionConfig(),
        output_tag=args.output_tag,
        check_only=bool(args.check_only),
        max_origins=args.max_origins,
        observed_run_id=args.observed_run_id,
        anchor_run_id=args.anchor_run_id,
    )
    print(f"QH_MODEL_3 run completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
