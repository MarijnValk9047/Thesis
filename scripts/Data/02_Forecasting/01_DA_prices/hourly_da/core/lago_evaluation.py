from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import diebold_mariano_test
from .reporting import reporting_level_specs


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _error_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    scored = predictions.copy()
    scored["y_true"] = _safe_numeric(scored["y_true"])
    scored["y_pred"] = _safe_numeric(scored["y_pred"])
    scored["error"] = scored["y_pred"] - scored["y_true"]
    scored["abs_error"] = scored["error"].abs()
    scored["squared_error"] = scored["error"] ** 2
    denom_smape = (scored["y_true"].abs() + scored["y_pred"].abs()).replace(0.0, np.nan)
    scored["smape_component"] = (2.0 * scored["abs_error"] / denom_smape) * 100.0
    denom_mape = scored["y_true"].abs().replace(0.0, np.nan)
    scored["mape_component"] = (scored["abs_error"] / denom_mape) * 100.0
    return scored


def _metric_row(group: pd.DataFrame) -> dict[str, Any]:
    valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
    if valid.empty:
        return {
            "observations_total": int(group.shape[0]),
            "observations_scored": 0,
            "coverage_pct": 0.0,
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "smape_pct": np.nan,
            "mape_pct": np.nan,
            "median_ae": np.nan,
            "p90_ae": np.nan,
            "p95_ae": np.nan,
        }
    return {
        "observations_total": int(group.shape[0]),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / group.shape[0] * 100.0),
        "mae": float(valid["abs_error"].mean()),
        "rmse": float(math.sqrt(valid["squared_error"].mean())),
        "bias": float(valid["error"].mean()),
        "smape_pct": float(valid["smape_component"].mean(skipna=True)),
        "mape_pct": float(valid["mape_component"].mean(skipna=True)),
        "median_ae": float(valid["abs_error"].median()),
        "p90_ae": float(valid["abs_error"].quantile(0.90)),
        "p95_ae": float(valid["abs_error"].quantile(0.95)),
    }


def _naive_denominator_frame(naive_reporting_metrics: pd.DataFrame) -> pd.DataFrame:
    cols = ["dataset_split", "reporting_level", "mae"]
    if naive_reporting_metrics.empty:
        return pd.DataFrame(columns=["dataset_split", "reporting_level", "naive_mae"])
    return naive_reporting_metrics[cols].rename(columns={"mae": "naive_mae"}).copy()


def _attach_rmae(metrics: pd.DataFrame, naive_denom: pd.DataFrame, join_cols: list[str]) -> pd.DataFrame:
    if metrics.empty:
        return metrics.copy()
    out = metrics.copy()
    if naive_denom.empty:
        out["rmae_vs_official_naive"] = np.nan
        out["rmae"] = np.nan
        return out
    merged = out.merge(naive_denom, on=join_cols, how="left")
    merged["rmae_vs_official_naive"] = merged["mae"] / merged["naive_mae"]
    merged.loc[merged["naive_mae"].isna(), "rmae_vs_official_naive"] = np.nan
    merged.loc[merged["naive_mae"] == 0.0, "rmae_vs_official_naive"] = np.nan
    merged["rmae"] = merged["rmae_vs_official_naive"]
    return merged.drop(columns=["naive_mae"])


def summarize_metrics_overall(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["model", "model_family", "fs_level", "feature_variant", "dataset_split"]
    for keys, group in scored.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "mae", "model"]).reset_index(drop=True)


def summarize_metrics_by_lead_day(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = [
        "model",
        "model_family",
        "fs_level",
        "feature_variant",
        "dataset_split",
        "lead_day",
        "lead_day_label",
    ]
    for keys, group in scored.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "lead_day", "mae", "model"]).reset_index(drop=True)


def summarize_metrics_by_reporting_level(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["model", "model_family", "fs_level", "feature_variant", "dataset_split"]
    for spec in reporting_level_specs():
        part = scored[scored["lead_day"].isin(spec.lead_days)].copy()
        if part.empty:
            continue
        report_cols = spec.to_columns()
        for keys, group in part.groupby(group_cols, dropna=False):
            row = dict(zip(group_cols, keys, strict=True))
            row.update(_metric_row(group))
            row.update(report_cols)
            row["origins"] = int(group["forecast_origin_utc"].nunique())
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["dataset_split", "reporting_level_sort_order", "mae", "model"])
        .reset_index(drop=True)
    )


def compute_selected_week_metrics(
    scored: pd.DataFrame,
    selected_weeks: pd.DataFrame,
) -> pd.DataFrame:
    if scored.empty or selected_weeks.empty:
        return pd.DataFrame()
    work = scored.copy()
    work["target_delivery_local_date"] = pd.to_datetime(work["target_delivery_local_date"], errors="coerce").dt.date
    rows: list[dict[str, Any]] = []
    group_cols = ["model", "model_family", "fs_level", "feature_variant", "dataset_split", "category", "iso_week_id"]
    for week in selected_weeks.to_dict(orient="records"):
        start_day = pd.Timestamp(week["week_start_local_date"]).date()
        end_day = pd.Timestamp(week["week_end_local_date"]).date()
        part = work[
            (work["target_delivery_local_date"] >= start_day)
            & (work["target_delivery_local_date"] <= end_day)
        ].copy()
        if part.empty:
            continue
        for keys, group in part.groupby(["model", "model_family", "fs_level", "feature_variant", "dataset_split"], dropna=False):
            row = dict(zip(["model", "model_family", "fs_level", "feature_variant", "dataset_split"], keys, strict=True))
            row["category"] = str(week["category"])
            row["iso_week_id"] = str(week["iso_week_id"])
            row["week_start_local_date"] = week["week_start_local_date"]
            row["week_end_local_date"] = week["week_end_local_date"]
            row.update(_metric_row(group))
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["category", "dataset_split", "mae", "model"]).reset_index(drop=True)


def compute_price_regime_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for split_name, split_group in scored.groupby("dataset_split", dropna=False):
        valid = split_group[split_group["y_true"].notna() & split_group["y_pred"].notna()].copy()
        if valid.empty:
            continue
        q30 = float(valid["y_true"].quantile(0.30))
        q70 = float(valid["y_true"].quantile(0.70))
        q90 = float(valid["y_true"].quantile(0.90))
        valid["price_regime"] = "mid"
        valid.loc[valid["y_true"] < 0.0, "price_regime"] = "negative"
        valid.loc[(valid["y_true"] >= 0.0) & (valid["y_true"] < q30), "price_regime"] = "low"
        valid.loc[(valid["y_true"] >= q70) & (valid["y_true"] < q90), "price_regime"] = "high"
        valid.loc[valid["y_true"] >= q90, "price_regime"] = "extreme"
        group_cols = ["model", "model_family", "fs_level", "feature_variant", "dataset_split", "price_regime"]
        for keys, group in valid.groupby(group_cols, dropna=False):
            row = dict(zip(group_cols, keys, strict=True))
            row.update(_metric_row(group))
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["dataset_split", "price_regime", "mae", "model"]).reset_index(drop=True)


def compute_operational_diagnostics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    work = scored.copy()
    work["target_delivery_local_date"] = pd.to_datetime(work["target_delivery_local_date"], errors="coerce").dt.date

    rows: list[dict[str, Any]] = []
    for keys, group in work.groupby(["model", "model_family", "fs_level", "feature_variant", "dataset_split"], dropna=False):
        model, model_family, fs_level, feature_variant, split_name = keys
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
        if valid.empty:
            continue

        daily_spearman_values: list[float] = []
        spread_errors: list[float] = []
        top_hit: dict[int, list[float]] = {4: [], 8: [], 16: []}
        bottom_hit: dict[int, list[float]] = {4: [], 8: [], 16: []}
        for _, day_group in valid.groupby("target_delivery_local_date", dropna=False):
            day_group = day_group.sort_values("target_timestamp_utc")
            if day_group["y_true"].nunique(dropna=True) > 1 and day_group["y_pred"].nunique(dropna=True) > 1:
                corr = day_group["y_true"].corr(day_group["y_pred"], method="spearman")
                if pd.notna(corr):
                    daily_spearman_values.append(float(corr))

            for k in (4, 8, 16):
                if day_group.shape[0] < k:
                    continue
                actual_top = set(day_group.sort_values("y_true", ascending=False).head(k)["target_timestamp_utc"].tolist())
                pred_top = set(day_group.sort_values("y_pred", ascending=False).head(k)["target_timestamp_utc"].tolist())
                actual_bottom = set(day_group.sort_values("y_true", ascending=True).head(k)["target_timestamp_utc"].tolist())
                pred_bottom = set(day_group.sort_values("y_pred", ascending=True).head(k)["target_timestamp_utc"].tolist())
                top_hit[k].append(float(len(actual_top & pred_top) / k))
                bottom_hit[k].append(float(len(actual_bottom & pred_bottom) / k))

            k_spread = 4 if day_group.shape[0] >= 4 else None
            if k_spread is not None:
                top_actual = float(day_group.sort_values("y_true", ascending=False).head(k_spread)["y_true"].mean())
                bottom_actual = float(day_group.sort_values("y_true", ascending=True).head(k_spread)["y_true"].mean())
                top_pred = float(day_group.sort_values("y_pred", ascending=False).head(k_spread)["y_pred"].mean())
                bottom_pred = float(day_group.sort_values("y_pred", ascending=True).head(k_spread)["y_pred"].mean())
                spread_errors.append((top_pred - bottom_pred) - (top_actual - bottom_actual))

        abs_error = valid["abs_error"]
        q10 = float(valid["y_true"].quantile(0.10))
        q90 = float(valid["y_true"].quantile(0.90))
        top_mask = valid["y_true"] >= q90
        bottom_mask = valid["y_true"] <= q10
        middle_mask = ~top_mask & ~bottom_mask
        negative_mask = valid["y_true"] < 0.0
        neg_sign_accuracy = np.nan
        if negative_mask.any():
            neg_sign_accuracy = float((valid.loc[negative_mask, "y_pred"] < 0.0).mean())

        rows.append(
            {
                "model": model,
                "model_family": model_family,
                "fs_level": fs_level,
                "feature_variant": feature_variant,
                "dataset_split": split_name,
                "mean_spearman_corr": float(np.nanmean(daily_spearman_values)) if daily_spearman_values else np.nan,
                "top4_high_price_hit_rate": float(np.nanmean(top_hit[4])) if top_hit[4] else np.nan,
                "top8_high_price_hit_rate": float(np.nanmean(top_hit[8])) if top_hit[8] else np.nan,
                "top16_high_price_hit_rate": float(np.nanmean(top_hit[16])) if top_hit[16] else np.nan,
                "bottom4_low_price_hit_rate": float(np.nanmean(bottom_hit[4])) if bottom_hit[4] else np.nan,
                "bottom8_low_price_hit_rate": float(np.nanmean(bottom_hit[8])) if bottom_hit[8] else np.nan,
                "bottom16_low_price_hit_rate": float(np.nanmean(bottom_hit[16])) if bottom_hit[16] else np.nan,
                "top_decile_tail_mae": float(abs_error[top_mask].mean()) if top_mask.any() else np.nan,
                "bottom_decile_tail_mae": float(abs_error[bottom_mask].mean()) if bottom_mask.any() else np.nan,
                "middle_80pct_mae": float(abs_error[middle_mask].mean()) if middle_mask.any() else np.nan,
                "high_low_spread_error": float(np.nanmean(spread_errors)) if spread_errors else np.nan,
                "negative_price_sign_accuracy": neg_sign_accuracy,
            }
        )
    return pd.DataFrame(rows).sort_values(["dataset_split", "model"]).reset_index(drop=True)


def compute_dm_tests(
    scored_predictions: pd.DataFrame,
    *,
    benchmark_model: str,
    challenger_models: list[str],
    loss: str = "absolute",
    hac_lag: int = 24,
) -> pd.DataFrame:
    if scored_predictions.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    base_cols = ["dataset_split", "target_timestamp_utc", "y_true", "y_pred", "lead_day"]
    benchmark = scored_predictions[scored_predictions["model"] == benchmark_model][base_cols].rename(columns={"y_pred": "y_pred_benchmark"})
    if benchmark.empty:
        return pd.DataFrame()
    for challenger in challenger_models:
        other = scored_predictions[scored_predictions["model"] == challenger][base_cols].rename(columns={"y_pred": "y_pred_challenger"})
        merged = benchmark.merge(other, on=["dataset_split", "target_timestamp_utc", "lead_day", "y_true"], how="inner")
        if merged.empty:
            continue
        for split_name, split_group in merged.groupby("dataset_split", dropna=False):
            overall = diebold_mariano_test(
                actual=split_group["y_true"],
                forecast_a=split_group["y_pred_challenger"],
                forecast_b=split_group["y_pred_benchmark"],
                loss=loss,
                hac_lag=hac_lag,
            )
            overall.update(
                {
                    "dataset_split": split_name,
                    "benchmark_model": benchmark_model,
                    "challenger_model": challenger,
                    "lead_day": "overall",
                }
            )
            rows.append(overall)
            for lead_day, lead_group in split_group.groupby("lead_day", dropna=False):
                part = diebold_mariano_test(
                    actual=lead_group["y_true"],
                    forecast_a=lead_group["y_pred_challenger"],
                    forecast_b=lead_group["y_pred_benchmark"],
                    loss=loss,
                    hac_lag=hac_lag,
                )
                part.update(
                    {
                        "dataset_split": split_name,
                        "benchmark_model": benchmark_model,
                        "challenger_model": challenger,
                        "lead_day": int(lead_day),
                    }
                )
                rows.append(part)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["dataset_split", "challenger_model", "lead_day"]).reset_index(drop=True)


def evaluate_lago_predictions(
    predictions: pd.DataFrame,
    *,
    naive_reference_reporting: pd.DataFrame | None = None,
    selected_weeks: pd.DataFrame | None = None,
    external_aligned_predictions: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    if predictions.empty:
        empty = pd.DataFrame()
        return {
            "metrics_overall": empty,
            "metrics_by_lead_day": empty,
            "metrics_by_reporting_level": empty,
            "metrics_by_selected_week": empty,
            "metrics_by_price_regime": empty,
            "operational_diagnostics": empty,
            "dm_tests": empty,
        }

    scored = _error_frame(predictions)
    if external_aligned_predictions is not None and not external_aligned_predictions.empty:
        ext = _error_frame(external_aligned_predictions)
        scored_for_dm = pd.concat([scored, ext], ignore_index=True)
    else:
        scored_for_dm = scored

    overall = summarize_metrics_overall(scored)
    by_lead = summarize_metrics_by_lead_day(scored)
    by_reporting = summarize_metrics_by_reporting_level(scored)

    if naive_reference_reporting is not None and not naive_reference_reporting.empty:
        denom = _naive_denominator_frame(naive_reference_reporting)
        by_reporting = _attach_rmae(by_reporting, denom, join_cols=["dataset_split", "reporting_level"])
        overall = _attach_rmae(
            overall,
            by_reporting[by_reporting["reporting_level"] == "stitched_all_horizon"][["dataset_split", "rmae_vs_official_naive", "mae"]]
            .rename(columns={"mae": "naive_mae"}),
            join_cols=["dataset_split"],
        )
        by_lead["rmae_vs_official_naive"] = np.nan
        by_lead["rmae"] = np.nan
    else:
        for frame in (overall, by_lead, by_reporting):
            frame["rmae_vs_official_naive"] = np.nan
            frame["rmae"] = np.nan

    weeks = selected_weeks if selected_weeks is not None else pd.DataFrame()
    by_week = compute_selected_week_metrics(scored, weeks)
    regime = compute_price_regime_metrics(scored)
    ops = compute_operational_diagnostics(scored)

    model_names = sorted(scored_for_dm["model"].astype(str).unique().tolist())
    benchmark_model = "lago_lear_d_exact_available_x2_ensemble" if "lago_lear_d_exact_available_x2_ensemble" in model_names else model_names[0]
    challengers = [name for name in model_names if name != benchmark_model]
    dm = compute_dm_tests(scored_for_dm, benchmark_model=benchmark_model, challenger_models=challengers)

    return {
        "metrics_overall": overall,
        "metrics_by_lead_day": by_lead,
        "metrics_by_reporting_level": by_reporting,
        "metrics_by_selected_week": by_week,
        "metrics_by_price_regime": regime,
        "operational_diagnostics": ops,
        "dm_tests": dm,
    }


def write_evaluation_artifacts(output_dir: Path, evaluation_tables: dict[str, pd.DataFrame]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    name_map = {
        "metrics_overall": "metrics_overall.csv",
        "metrics_by_lead_day": "metrics_by_lead_day.csv",
        "metrics_by_reporting_level": "metrics_by_reporting_level.csv",
        "metrics_by_selected_week": "metrics_by_selected_week.csv",
        "metrics_by_price_regime": "metrics_by_price_regime.csv",
        "operational_diagnostics": "operational_diagnostics.csv",
        "dm_tests": "dm_tests.csv",
    }
    for key, filename in name_map.items():
        frame = evaluation_tables.get(key, pd.DataFrame())
        frame.to_csv(output_dir / filename, index=False)
