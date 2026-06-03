from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .model3_lear_strict import find_latest_qh_model3_run, model3_output_root
from .phase2_7_hourly_parity import phase27_output_root
from .reporting_metrics import (
    compute_high_low_spread_error_metrics,
    compute_rank_correlation_metrics,
    compute_tail_mae_metrics,
    compute_topk_hit_rate_metrics,
)


RUN_LABEL = "qh_three_model_comparison"
SCOPE_EXISTING_TWO = "EXISTING_TWO_MODEL_SUPPORT"
SCOPE_STRICT_THREE = "STRICT_THREE_MODEL_QH_OVERLAP"
MODEL_TWO_IDS = [
    "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted",
    "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate",
]
MODEL_THREE_ID = "qh-fs1__mean_shape__hourly_anchor__lear_strict"


@dataclass(frozen=True)
class ComparisonPaths:
    run_id: str
    run_dir: Path


def comparison_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)


def _bundle_paths(config: QuarterHourDAExtensionConfig) -> ComparisonPaths:
    run_id = _timestamped_run_id()
    run_dir = comparison_output_root(config) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return ComparisonPaths(run_id=run_id, run_dir=run_dir)


def _find_latest_run(root: Path) -> Path:
    if not root.exists():
        raise FileNotFoundError(f"Run root not found: {root}")
    runs = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    if not runs:
        raise FileNotFoundError(f"No completed runs found under: {root}")
    return runs[-1]


def _normalize_timestamp_columns(frame: pd.DataFrame, *, business_timezone: str) -> pd.DataFrame:
    out = frame.copy()
    out["forecast_origin_utc"] = pd.to_datetime(out["forecast_origin_utc"], utc=True, errors="coerce")
    out["target_timestamp_utc"] = pd.to_datetime(out["target_timestamp_utc"], utc=True, errors="coerce")
    out["target_timestamp_local"] = out["target_timestamp_utc"].dt.tz_convert(business_timezone)
    out["target_local_date"] = out["target_timestamp_local"].dt.date
    out["lead_day"] = pd.to_numeric(out["lead_day"], errors="coerce").astype("Int64")
    out["dataset_split"] = out["dataset_split"].astype(str)
    out["y_true"] = pd.to_numeric(out["y_true"], errors="coerce")
    out["y_pred"] = pd.to_numeric(out["y_pred"], errors="coerce")
    return out


def _load_existing_two_predictions(config: QuarterHourDAExtensionConfig, phase27_run_id: str | None) -> tuple[pd.DataFrame, Path]:
    if phase27_run_id:
        run_dir = phase27_output_root(config) / str(phase27_run_id)
    else:
        run_dir = _find_latest_run(phase27_output_root(config))
    path = run_dir / "predictions_long.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing phase2.7 parity predictions file: {path}")
    frame = pd.read_csv(path, low_memory=False)
    frame = frame[frame["model"].astype(str).isin(MODEL_TWO_IDS)].copy()
    if frame.empty:
        raise ValueError("No rows found for the expected two existing QH model IDs in phase2.7 parity predictions.")
    frame["model_id"] = frame["model"].astype(str)
    frame["model_family"] = frame["model_family"].astype(str)
    frame["feature_set_id"] = frame.get("feature_set_id", pd.Series("QH-FS1", index=frame.index)).astype(str)
    frame["fs_level"] = frame.get("fs_level", frame.get("feature_set_id", pd.Series("QH-FS1", index=frame.index))).astype(str)
    frame["y_true"] = pd.to_numeric(frame.get("y_true", frame.get("actual_price_eur_per_mwh")), errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame.get("y_pred", frame.get("forecast_price_eur_per_mwh")), errors="coerce")
    keep = [
        "model_id",
        "model_family",
        "feature_set_id",
        "fs_level",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "y_true",
        "y_pred",
    ]
    for col in keep:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = _normalize_timestamp_columns(frame[keep], business_timezone=config.business_timezone)
    return frame, run_dir


def _load_model3_predictions(config: QuarterHourDAExtensionConfig, model3_run_id: str | None) -> tuple[pd.DataFrame, Path]:
    if model3_run_id:
        run_dir = model3_output_root(config) / str(model3_run_id)
    else:
        latest = find_latest_qh_model3_run(config)
        if latest is None:
            raise FileNotFoundError("No QH model3 run with run_summary.json was found.")
        run_dir = latest
    path = run_dir / "predictions_long.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing QH model3 predictions file: {path}")
    frame = pd.read_csv(path, low_memory=False)
    frame["model_id"] = frame.get("model_id", frame.get("model", MODEL_THREE_ID)).astype(str)
    frame["model_family"] = frame.get("model_family", pd.Series("mean_shape", index=frame.index)).astype(str)
    frame["feature_set_id"] = frame.get("feature_set_id", pd.Series("QH-FS1", index=frame.index)).astype(str)
    frame["fs_level"] = frame.get("fs_level", pd.Series("QH-FS1", index=frame.index)).astype(str)
    frame["lead_day_label"] = frame.get("lead_day_label", pd.Series(pd.NA, index=frame.index))
    frame["horizon_index"] = frame.get("horizon_index", pd.Series(pd.NA, index=frame.index))
    frame["y_true"] = pd.to_numeric(frame.get("y_true", frame.get("actual_price_eur_per_mwh")), errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame.get("y_pred", frame.get("forecast_price_eur_per_mwh")), errors="coerce")
    keep = [
        "model_id",
        "model_family",
        "feature_set_id",
        "fs_level",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "y_true",
        "y_pred",
    ]
    for col in keep:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[frame["model_id"].astype(str) == MODEL_THREE_ID].copy()
    if frame.empty:
        raise ValueError(f"No rows found for model3 id '{MODEL_THREE_ID}' in {path}.")
    frame = _normalize_timestamp_columns(frame[keep], business_timezone=config.business_timezone)
    return frame, run_dir


def _safe_rmse(errors: pd.Series) -> float:
    valid = pd.to_numeric(errors, errors="coerce").dropna()
    if valid.empty:
        return np.nan
    return float(np.sqrt(np.mean(np.square(valid))))


def _metric_block(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame[frame["y_true"].notna() & frame["y_pred"].notna()].copy()
    if valid.empty:
        return {
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "median_ae": np.nan,
            "p90_ae": np.nan,
            "p95_ae": np.nan,
            "observations_scored": 0,
            "coverage_pct": 0.0,
        }
    err = valid["y_pred"] - valid["y_true"]
    ae = err.abs()
    return {
        "mae": float(ae.mean()),
        "rmse": _safe_rmse(err),
        "bias": float(err.mean()),
        "median_ae": float(ae.median()),
        "p90_ae": float(ae.quantile(0.90)),
        "p95_ae": float(ae.quantile(0.95)),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / frame.shape[0] * 100.0) if frame.shape[0] > 0 else 0.0,
    }


def _scope_support_keys(predictions: pd.DataFrame, model_ids: list[str]) -> pd.DataFrame:
    key_cols = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"]
    part = predictions[predictions["model_id"].astype(str).isin(model_ids)].copy()
    part = part[part["y_true"].notna() & part["y_pred"].notna()].copy()
    counts = (
        part.groupby(key_cols, dropna=False)["model_id"]
        .nunique()
        .reset_index(name="model_count")
    )
    keep_keys = counts[counts["model_count"].eq(len(model_ids))][key_cols].copy()
    return keep_keys


def _subset_to_scope(predictions: pd.DataFrame, *, model_ids: list[str], scope_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = _scope_support_keys(predictions, model_ids=model_ids)
    scoped = predictions[predictions["model_id"].astype(str).isin(model_ids)].copy()
    scoped = scoped.merge(keys, on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"], how="inner")
    scoped["comparison_scope"] = scope_name
    return scoped, keys


def _support_tables(keys: pd.DataFrame, *, scope_name: str, business_timezone: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if keys.empty:
        empty = pd.DataFrame(
            [
                {
                    "comparison_scope": scope_name,
                    "dataset_split": "all",
                    "lead_day": "all",
                    "n_quarters": 0,
                    "n_origins": 0,
                    "n_complete_local_days": 0,
                    "start_target_utc": pd.NaT,
                    "end_target_utc": pd.NaT,
                }
            ]
        )
        return empty, empty.copy(), empty.copy()
    table = keys.copy()
    table["target_timestamp_local"] = pd.to_datetime(table["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(business_timezone)
    table["target_local_date"] = table["target_timestamp_local"].dt.date

    by_split_lead = (
        table.groupby(["dataset_split", "lead_day"], dropna=False)
        .agg(
            n_quarters=("target_timestamp_utc", "size"),
            n_origins=("forecast_origin_utc", "nunique"),
            start_target_utc=("target_timestamp_utc", "min"),
            end_target_utc=("target_timestamp_utc", "max"),
        )
        .reset_index()
    )
    day_counts = (
        table.groupby(["dataset_split", "lead_day", "target_local_date"], dropna=False)["target_timestamp_utc"]
        .nunique()
        .reset_index(name="quarters_in_day")
    )
    complete = (
        day_counts.groupby(["dataset_split", "lead_day"], dropna=False)["quarters_in_day"]
        .apply(lambda s: int((pd.to_numeric(s, errors="coerce") == 96).sum()))
        .reset_index(name="n_complete_local_days")
    )
    by_split_lead = by_split_lead.merge(complete, on=["dataset_split", "lead_day"], how="left")
    by_split_lead["n_complete_local_days"] = by_split_lead["n_complete_local_days"].fillna(0).astype(int)
    by_split_lead["comparison_scope"] = scope_name

    by_split = (
        by_split_lead.groupby(["comparison_scope", "dataset_split"], dropna=False)
        .agg(
            n_quarters=("n_quarters", "sum"),
            n_origins=("n_origins", "sum"),
            n_complete_local_days=("n_complete_local_days", "sum"),
            start_target_utc=("start_target_utc", "min"),
            end_target_utc=("end_target_utc", "max"),
        )
        .reset_index()
    )
    overall = (
        by_split_lead.groupby("comparison_scope", dropna=False)
        .agg(
            n_quarters=("n_quarters", "sum"),
            n_origins=("n_origins", "sum"),
            n_complete_local_days=("n_complete_local_days", "sum"),
            start_target_utc=("start_target_utc", "min"),
            end_target_utc=("end_target_utc", "max"),
        )
        .reset_index()
    )
    return overall, by_split, by_split_lead


def _conventional_metrics(scoped: pd.DataFrame, *, scope_name: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in scoped.groupby(["model_id", "model_family", "feature_set_id", "dataset_split", "lead_day"], dropna=False):
        row = dict(zip(["model_id", "model_family", "feature_set_id", "dataset_split", "lead_day"], keys, strict=True))
        row["comparison_scope"] = scope_name
        row.update(_metric_block(group))
        row["n_origins"] = int(group["forecast_origin_utc"].nunique())
        row["n_quarters"] = int(group.shape[0])
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["comparison_scope", "dataset_split", "lead_day", "model_id"]).reset_index(drop=True) if rows else pd.DataFrame()


def _duration_regret(scoped: pd.DataFrame, *, L_values: tuple[int, ...] = (4, 8, 16)) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in scoped.groupby(["model_id", "dataset_split", "lead_day", "target_local_date"], dropna=False):
        model_id, split_name, lead_day, local_date = keys
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").reset_index(drop=True)
        n = int(valid.shape[0])
        if n == 0:
            continue
        true_values = valid["y_true"].to_numpy(dtype=float)
        pred_values = valid["y_pred"].to_numpy(dtype=float)
        for L in L_values:
            L_int = int(L)
            if n < L_int:
                continue
            true_roll = np.convolve(true_values, np.ones(L_int, dtype=float), mode="valid")
            pred_roll = np.convolve(pred_values, np.ones(L_int, dtype=float), mode="valid")
            idx_true_low = int(np.argmin(true_roll))
            idx_pred_low = int(np.argmin(pred_roll))
            idx_true_high = int(np.argmax(true_roll))
            idx_pred_high = int(np.argmax(pred_roll))
            rows.append(
                {
                    "model_id": model_id,
                    "dataset_split": split_name,
                    "lead_day": lead_day,
                    "target_local_date": local_date,
                    "L": L_int,
                    "low_window_regret": float(true_roll[idx_pred_low] - true_roll[idx_true_low]),
                    "high_window_regret": float(true_roll[idx_true_high] - true_roll[idx_pred_high]),
                }
            )
    return pd.DataFrame(rows)


def _operational_metrics(scoped: pd.DataFrame, *, scope_name: str, include_operational: bool) -> pd.DataFrame:
    if scoped.empty:
        return pd.DataFrame()
    if not include_operational:
        return pd.DataFrame()

    report_frame = scoped.copy()
    report_frame["model"] = report_frame["model_id"]
    report_frame["fs_level"] = report_frame["feature_set_id"]
    report_frame["is_observed_target"] = report_frame["y_true"].notna()

    topk_daily, topk_summary = compute_topk_hit_rate_metrics(report_frame)
    spearman_daily, spearman_summary = compute_rank_correlation_metrics(report_frame)
    tail_daily, tail_summary = compute_tail_mae_metrics(report_frame)
    spread_daily, spread_summary = compute_high_low_spread_error_metrics(report_frame)
    duration_daily = _duration_regret(report_frame)

    merge_cols = ["model", "dataset_split", "lead_day"]
    rows = topk_summary.rename(columns={"model": "model_id"}).copy()
    rows = rows.rename(
        columns={
            "mean_top4_high_hit_rate": "top4_hit",
            "mean_top8_high_hit_rate": "top8_hit",
            "mean_top16_high_hit_rate": "top16_hit",
            "mean_top4_low_hit_rate": "bottom4_hit",
            "mean_top8_low_hit_rate": "bottom8_hit",
            "mean_top16_low_hit_rate": "bottom16_hit",
        }
    )
    keep_top = ["model_id", "dataset_split", "lead_day", "top4_hit", "top8_hit", "top16_hit", "bottom4_hit", "bottom8_hit", "bottom16_hit"]
    rows = rows[keep_top] if not rows.empty else pd.DataFrame(columns=keep_top)

    spearman_summary = spearman_summary.rename(columns={"model": "model_id", "mean_spearman_rank_corr": "spearman_daily_mean"})
    if not spearman_daily.empty:
        sp_med = (
            spearman_daily.groupby(["model", "dataset_split", "lead_day"], dropna=False)["spearman_rank_corr"]
            .median()
            .reset_index(name="spearman_daily_median")
            .rename(columns={"model": "model_id"})
        )
    else:
        sp_med = pd.DataFrame(columns=["model_id", "dataset_split", "lead_day", "spearman_daily_median"])
    rows = rows.merge(
        spearman_summary[["model_id", "dataset_split", "lead_day", "spearman_daily_mean"]],
        on=["model_id", "dataset_split", "lead_day"],
        how="left",
    ).merge(
        sp_med[["model_id", "dataset_split", "lead_day", "spearman_daily_median"]],
        on=["model_id", "dataset_split", "lead_day"],
        how="left",
    )

    tail_summary = tail_summary.rename(
        columns={
            "model": "model_id",
            "mean_tail_mae_top_10pct": "tail_mae_top10",
            "mean_tail_mae_bottom_10pct": "tail_mae_bottom10",
            "mean_tail_mae_middle_80pct": "tail_mae_middle80",
        }
    )
    rows = rows.merge(
        tail_summary[["model_id", "dataset_split", "lead_day", "tail_mae_top10", "tail_mae_bottom10", "tail_mae_middle80"]],
        on=["model_id", "dataset_split", "lead_day"],
        how="left",
    )

    spread_summary = spread_summary.rename(
        columns={
            "model": "model_id",
            "mean_top4_spread_error": "spread_error_top4",
            "mean_top8_spread_error": "spread_error_top8",
            "mean_top16_spread_error": "spread_error_top16",
            "mean_abs_top4_spread_error": "abs_spread_error_top4",
            "mean_abs_top8_spread_error": "abs_spread_error_top8",
            "mean_abs_top16_spread_error": "abs_spread_error_top16",
        }
    )
    rows = rows.merge(
        spread_summary[
            [
                "model_id",
                "dataset_split",
                "lead_day",
                "spread_error_top4",
                "spread_error_top8",
                "spread_error_top16",
                "abs_spread_error_top4",
                "abs_spread_error_top8",
                "abs_spread_error_top16",
            ]
        ],
        on=["model_id", "dataset_split", "lead_day"],
        how="left",
    )

    if not duration_daily.empty:
        duration_summary = (
            duration_daily.groupby(["model_id", "dataset_split", "lead_day", "L"], dropna=False)
            .agg(
                mean_low_window_regret=("low_window_regret", "mean"),
                mean_high_window_regret=("high_window_regret", "mean"),
            )
            .reset_index()
        )
        for L in (4, 8, 16):
            low = duration_summary[duration_summary["L"].eq(L)][["model_id", "dataset_split", "lead_day", "mean_low_window_regret"]].rename(
                columns={"mean_low_window_regret": f"regret_low_L{L}"}
            )
            high = duration_summary[duration_summary["L"].eq(L)][["model_id", "dataset_split", "lead_day", "mean_high_window_regret"]].rename(
                columns={"mean_high_window_regret": f"regret_high_L{L}"}
            )
            rows = rows.merge(low, on=["model_id", "dataset_split", "lead_day"], how="left")
            rows = rows.merge(high, on=["model_id", "dataset_split", "lead_day"], how="left")

    rows["comparison_scope"] = scope_name
    return rows.sort_values(["comparison_scope", "dataset_split", "lead_day", "model_id"]).reset_index(drop=True)


def _load_official_naive_payload(config: QuarterHourDAExtensionConfig, phase27_run_dir: Path) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    source_runs_path = phase27_run_dir / "source_runs.json"
    if not source_runs_path.exists():
        return None, pd.DataFrame()
    source_runs = json.loads(source_runs_path.read_text(encoding="utf-8"))
    observed_run_id = str(source_runs.get("observed_run_id", "")).strip()
    if not observed_run_id:
        return None, pd.DataFrame()
    observed_run_dir = config.output_root / "runs" / observed_run_id
    ref_path = observed_run_dir / "official_naive_reference.json"
    pred_path = observed_run_dir / "predictions_long.csv"
    if not ref_path.exists() or not pred_path.exists():
        return None, pd.DataFrame()
    reference = json.loads(ref_path.read_text(encoding="utf-8"))
    model_name = str(reference.get("model", "")).strip()
    pred = pd.read_csv(pred_path, low_memory=False)
    pred = pred[pred["model"].astype(str) == model_name].copy()
    if pred.empty:
        return reference, pd.DataFrame()
    pred["dataset_split"] = pred["dataset_split"].astype(str)
    pred["forecast_origin_utc"] = pd.to_datetime(pred["forecast_origin_utc"], utc=True, errors="coerce")
    pred["target_timestamp_utc"] = pd.to_datetime(pred["target_timestamp_utc"], utc=True, errors="coerce")
    pred["lead_day"] = pd.to_numeric(pred["lead_day"], errors="coerce").astype("Int64")
    pred["y_true"] = pd.to_numeric(pred["y_true"], errors="coerce")
    pred["y_pred"] = pd.to_numeric(pred["y_pred"], errors="coerce")
    return reference, pred[["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]]


def _apply_rmae(
    conventional: pd.DataFrame,
    *,
    scope_keys: dict[str, pd.DataFrame],
    naive_reference: dict[str, Any] | None,
    naive_predictions: pd.DataFrame,
) -> pd.DataFrame:
    if conventional.empty:
        return conventional
    out = conventional.copy()
    out["official_naive_model"] = naive_reference.get("model") if naive_reference else None
    out["rmae"] = np.nan
    if naive_reference is None or naive_predictions.empty:
        return out

    rows: list[dict[str, Any]] = []
    for scope_name, keys in scope_keys.items():
        if keys.empty:
            continue
        denom = naive_predictions.merge(
            keys,
            on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"],
            how="inner",
        )
        for dk, dg in denom.groupby(["dataset_split", "lead_day"], dropna=False):
            split_name, lead_day = dk
            valid = dg[dg["y_true"].notna() & dg["y_pred"].notna()].copy()
            if valid.empty:
                denom_mae = np.nan
            else:
                denom_mae = float((valid["y_pred"] - valid["y_true"]).abs().mean())
            rows.append(
                {
                    "comparison_scope": scope_name,
                    "dataset_split": split_name,
                    "lead_day": lead_day,
                    "official_naive_mae": denom_mae,
                }
            )
    if not rows:
        return out
    denom_table = pd.DataFrame(rows)
    out = out.merge(denom_table, on=["comparison_scope", "dataset_split", "lead_day"], how="left")
    out["rmae"] = out["mae"] / out["official_naive_mae"]
    out.loc[out["official_naive_mae"].isna() | (out["official_naive_mae"] == 0.0), "rmae"] = np.nan
    return out


def _write_interpretation(
    *,
    run_dir: Path,
    support_scope: pd.DataFrame,
    conventional: pd.DataFrame,
    operational: pd.DataFrame,
) -> None:
    lines: list[str] = []
    lines.append("# QH Three-Model Interpretation")
    lines.append("")
    lines.append("- LEAR_STRICT-QH is built from LEAR_STRICT hourly anchors plus zero-mean quarter-hour deviation.")
    lines.append("- LEAR_STRICT hourly anchor coverage became feasible after phase07 NL bridge routing.")
    lines.append("- Hourly LEAR_STRICT selection remains overlap-based (three-way hourly overlap evidence), not full-period dominance.")
    lines.append(f"- Primary comparison scope for ranking: `{SCOPE_STRICT_THREE}`.")
    lines.append("- Scoring uses observed quarter-hour targets only (`y_true` non-null rows).")
    lines.append("")
    if not support_scope.empty:
        s3 = support_scope[support_scope["comparison_scope"].astype(str) == SCOPE_STRICT_THREE]
        if not s3.empty:
            r = s3.iloc[0]
            lines.append(
                f"- `{SCOPE_STRICT_THREE}` support: n_quarters={int(r['n_quarters'])}, n_complete_local_days={int(r['n_complete_local_days'])}."
            )
    lines.append("")
    if not conventional.empty:
        strict_conv = conventional[conventional["comparison_scope"].astype(str) == SCOPE_STRICT_THREE].copy()
        if not strict_conv.empty:
            test_conv = strict_conv[strict_conv["dataset_split"].astype(str) == "test"].copy()
            if not test_conv.empty:
                best = test_conv.sort_values(["mae", "model_id"]).iloc[0]
                lines.append(
                    f"- On strict-three test support, best MAE: `{best['model_id']}` ({float(best['mae']):.3f})."
                )
    if not operational.empty:
        strict_ops = operational[operational["comparison_scope"].astype(str) == SCOPE_STRICT_THREE].copy()
        if not strict_ops.empty:
            test_ops = strict_ops[strict_ops["dataset_split"].astype(str) == "test"].copy()
            if not test_ops.empty and test_ops["top8_hit"].notna().any():
                best_ops = test_ops.sort_values(["top8_hit", "model_id"], ascending=[False, True]).iloc[0]
                lines.append(
                    f"- On strict-three test support, best top-8 high-price hit-rate: `{best_ops['model_id']}` ({float(best_ops['top8_hit']):.3f})."
                )
    lines.append("")
    lines.append("This remains a comparison of feasible mixed-frequency strategies under shared observed-QH support.")
    (run_dir / "qh_three_model_interpretation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_qh_three_model_comparison(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    model3_run_id: str | None = None,
    phase27_run_id: str | None = None,
    include_operational: bool = False,
) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    paths = _bundle_paths(resolved)

    existing_two, phase27_run_dir = _load_existing_two_predictions(resolved, phase27_run_id=phase27_run_id)
    model3, model3_run_dir = _load_model3_predictions(resolved, model3_run_id=model3_run_id)
    combined = pd.concat([existing_two, model3], ignore_index=True)

    two_scope, two_keys = _subset_to_scope(combined, model_ids=MODEL_TWO_IDS, scope_name=SCOPE_EXISTING_TWO)
    three_scope, three_keys = _subset_to_scope(combined, model_ids=MODEL_TWO_IDS + [MODEL_THREE_ID], scope_name=SCOPE_STRICT_THREE)

    scope_keys = {
        SCOPE_EXISTING_TWO: two_keys,
        SCOPE_STRICT_THREE: three_keys,
    }

    scope_support_rows: list[pd.DataFrame] = []
    support_split_rows: list[pd.DataFrame] = []
    support_split_lead_rows: list[pd.DataFrame] = []
    conventional_rows: list[pd.DataFrame] = []
    operational_rows: list[pd.DataFrame] = []
    scope_frames = {
        SCOPE_EXISTING_TWO: two_scope,
        SCOPE_STRICT_THREE: three_scope,
    }
    for scope_name, scope_frame in scope_frames.items():
        support_scope, support_by_split, support_by_split_lead = _support_tables(
            scope_keys[scope_name], scope_name=scope_name, business_timezone=resolved.business_timezone
        )
        scope_support_rows.append(support_scope)
        support_split_rows.append(support_by_split)
        support_split_lead_rows.append(support_by_split_lead)
        conventional_rows.append(_conventional_metrics(scope_frame, scope_name=scope_name))
        operational_rows.append(_operational_metrics(scope_frame, scope_name=scope_name, include_operational=include_operational))

    support_by_scope = pd.concat(scope_support_rows, ignore_index=True) if scope_support_rows else pd.DataFrame()
    support_by_split = pd.concat(support_split_rows, ignore_index=True) if support_split_rows else pd.DataFrame()
    support_by_lead_day = pd.concat(support_split_lead_rows, ignore_index=True) if support_split_lead_rows else pd.DataFrame()
    conventional = pd.concat(conventional_rows, ignore_index=True) if conventional_rows else pd.DataFrame()
    operational = pd.concat(operational_rows, ignore_index=True) if operational_rows else pd.DataFrame()

    naive_reference, naive_pred = _load_official_naive_payload(resolved, phase27_run_dir)
    conventional = _apply_rmae(
        conventional,
        scope_keys=scope_keys,
        naive_reference=naive_reference,
        naive_predictions=naive_pred,
    )

    comparison = conventional.copy()
    if not operational.empty:
        comparison = comparison.merge(
            operational.drop(columns=["model_family", "feature_set_id"], errors="ignore"),
            on=["comparison_scope", "model_id", "dataset_split", "lead_day"],
            how="left",
            suffixes=("", "_op"),
        )
    comparison = comparison.merge(
        support_by_lead_day[
            ["comparison_scope", "dataset_split", "lead_day", "n_quarters", "n_origins", "n_complete_local_days", "start_target_utc", "end_target_utc"]
        ],
        on=["comparison_scope", "dataset_split", "lead_day"],
        how="left",
    )

    conventional.to_csv(paths.run_dir / "conventional_metrics_by_scope.csv", index=False)
    operational.to_csv(paths.run_dir / "operational_metrics_by_scope.csv", index=False)
    support_by_scope.to_csv(paths.run_dir / "support_by_scope.csv", index=False)
    support_by_split.to_csv(paths.run_dir / "support_by_split.csv", index=False)
    support_by_lead_day.to_csv(paths.run_dir / "support_by_lead_day.csv", index=False)
    comparison.to_csv(paths.run_dir / "comparison_table_by_scope.csv", index=False)

    summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "include_operational": bool(include_operational),
        "phase27_run_dir": str(phase27_run_dir),
        "model3_run_dir": str(model3_run_dir),
        "models": MODEL_TWO_IDS + [MODEL_THREE_ID],
        "scopes": [SCOPE_EXISTING_TWO, SCOPE_STRICT_THREE],
        "support": support_by_scope.to_dict(orient="records"),
        "naive_reference": naive_reference,
        "notes": [
            "Main three-model interpretation should use STRICT_THREE_MODEL_QH_OVERLAP.",
            "Observed-target-only scoring is enforced via y_true non-null rows.",
            "Hourly LEAR_STRICT superiority remains overlap-based evidence from the hourly study.",
        ],
    }
    (paths.run_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    _write_interpretation(
        run_dir=paths.run_dir,
        support_scope=support_by_scope,
        conventional=conventional,
        operational=operational,
    )
    return paths.run_dir


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run observed-QH three-model comparison with strict overlap scope.")
    parser.add_argument("--model3-run-id", type=str, default=None)
    parser.add_argument("--phase27-run-id", type=str, default=None)
    parser.add_argument("--include-operational", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = run_qh_three_model_comparison(
        QuarterHourDAExtensionConfig(),
        model3_run_id=args.model3_run_id,
        phase27_run_id=args.phase27_run_id,
        include_operational=bool(args.include_operational),
    )
    print(f"QH three-model comparison completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
