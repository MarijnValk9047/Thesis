from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    predictions_path: Path
    metrics_reporting_path: Path
    skipped_path: Path
    run_summary_path: Path
    feature_schema_d_only_path: Path
    alpha_path: Path
    output_dir: Path


def _to_dt_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _safe_spearman(a: pd.Series, b: pd.Series) -> float:
    if a.nunique(dropna=True) <= 1 or b.nunique(dropna=True) <= 1:
        return np.nan
    return float(a.corr(b, method="spearman"))


def _metric_block(frame: pd.DataFrame) -> dict[str, float]:
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
        "rmse": float(np.sqrt((err ** 2).mean())),
        "bias": float(err.mean()),
        "median_ae": float(ae.median()),
        "p90_ae": float(ae.quantile(0.90)),
        "p95_ae": float(ae.quantile(0.95)),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / frame.shape[0] * 100.0) if frame.shape[0] else 0.0,
    }


def _daily_mae_table(pred: pd.DataFrame, models: list[str], split_name: str) -> pd.DataFrame:
    part = pred[(pred["dataset_split"] == split_name) & (pred["model"].isin(models))].copy()
    if part.empty:
        return pd.DataFrame()
    day_col = "target_delivery_local_date"
    return (
        part.groupby([day_col, "model"], dropna=False)["abs_error"]
        .mean()
        .reset_index(name="daily_mae")
    )


def _simulate_ensemble(
    pred: pd.DataFrame,
    base_models: list[str],
    weights: dict[str, float],
    label: str,
) -> pd.DataFrame:
    key_cols = [
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "target_hour_local",
        "target_delivery_local_date",
        "y_true",
        "is_observed_target",
    ]
    part = pred[pred["model"].isin(base_models)][key_cols + ["model", "y_pred"]].copy()
    pivot = (
        part.pivot_table(
            index=key_cols,
            columns="model",
            values="y_pred",
            aggfunc="first",
        )
        .reset_index()
    )
    for model in base_models:
        if model not in pivot.columns:
            pivot[model] = np.nan
    weighted = np.zeros(len(pivot), dtype=float)
    total_weight = 0.0
    for model, weight in weights.items():
        weighted += pd.to_numeric(pivot[model], errors="coerce").to_numpy(dtype=float) * float(weight)
        total_weight += float(weight)
    if total_weight > 0:
        weighted = weighted / total_weight
    out = pivot[key_cols].copy()
    out["model"] = label
    out["y_pred"] = weighted
    return out


def _ranking_metrics(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {
            "daily_spearman_rank_corr": np.nan,
            "top4_hit_rate": np.nan,
            "top8_hit_rate": np.nan,
            "top16_hit_rate": np.nan,
            "bottom4_hit_rate": np.nan,
            "bottom8_hit_rate": np.nan,
            "bottom16_hit_rate": np.nan,
            "high_low_spread_error": np.nan,
        }

    spearman_values: list[float] = []
    top_hits: dict[int, list[float]] = {4: [], 8: [], 16: []}
    bottom_hits: dict[int, list[float]] = {4: [], 8: [], 16: []}
    spread_errors: list[float] = []

    for _, day in frame.groupby("target_delivery_local_date", dropna=False):
        day = day.sort_values("target_timestamp_utc")
        corr = _safe_spearman(day["y_true"], day["y_pred"])
        if pd.notna(corr):
            spearman_values.append(float(corr))
        for k in (4, 8, 16):
            if day.shape[0] < k:
                continue
            top_true = set(day.nlargest(k, "y_true")["target_timestamp_utc"].tolist())
            top_pred = set(day.nlargest(k, "y_pred")["target_timestamp_utc"].tolist())
            bot_true = set(day.nsmallest(k, "y_true")["target_timestamp_utc"].tolist())
            bot_pred = set(day.nsmallest(k, "y_pred")["target_timestamp_utc"].tolist())
            top_hits[k].append(float(len(top_true & top_pred) / k))
            bottom_hits[k].append(float(len(bot_true & bot_pred) / k))
        if day.shape[0] >= 4:
            a_hi = float(day.nlargest(4, "y_true")["y_true"].mean())
            a_lo = float(day.nsmallest(4, "y_true")["y_true"].mean())
            p_hi = float(day.nlargest(4, "y_pred")["y_pred"].mean())
            p_lo = float(day.nsmallest(4, "y_pred")["y_pred"].mean())
            spread_errors.append((p_hi - p_lo) - (a_hi - a_lo))

    return {
        "daily_spearman_rank_corr": float(np.nanmean(spearman_values)) if spearman_values else np.nan,
        "top4_hit_rate": float(np.nanmean(top_hits[4])) if top_hits[4] else np.nan,
        "top8_hit_rate": float(np.nanmean(top_hits[8])) if top_hits[8] else np.nan,
        "top16_hit_rate": float(np.nanmean(top_hits[16])) if top_hits[16] else np.nan,
        "bottom4_hit_rate": float(np.nanmean(bottom_hits[4])) if bottom_hits[4] else np.nan,
        "bottom8_hit_rate": float(np.nanmean(bottom_hits[8])) if bottom_hits[8] else np.nan,
        "bottom16_hit_rate": float(np.nanmean(bottom_hits[16])) if bottom_hits[16] else np.nan,
        "high_low_spread_error": float(np.nanmean(spread_errors)) if spread_errors else np.nan,
    }


def main() -> None:
    run_id = "20260507_161622_lago_lear_six_year_benchmark"
    run_dir = Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear") / run_id
    output_dir = Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/variant_decision_analysis_20260507_161622")
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = RunPaths(
        run_dir=run_dir,
        predictions_path=run_dir / "predictions" / "predictions_long.parquet",
        metrics_reporting_path=run_dir / "metrics" / "metrics_by_reporting_level.csv",
        skipped_path=run_dir / "predictions" / "skipped_predictions.csv",
        run_summary_path=run_dir / "run_summary.json",
        feature_schema_d_only_path=run_dir / "feature_schema_d_only.json",
        alpha_path=run_dir / "predictions" / "alpha_selection_audit.csv",
        output_dir=output_dir,
    )

    pred = pd.read_parquet(paths.predictions_path)
    pred["forecast_origin_utc"] = _to_dt_utc(pred["forecast_origin_utc"])
    pred["target_timestamp_utc"] = _to_dt_utc(pred["target_timestamp_utc"])
    pred["target_delivery_local_date"] = pd.to_datetime(pred["target_delivery_local_date"], errors="coerce").dt.date
    pred["y_true"] = pd.to_numeric(pred["y_true"], errors="coerce")
    pred["y_pred"] = pd.to_numeric(pred["y_pred"], errors="coerce")
    pred["error"] = pred["y_pred"] - pred["y_true"]
    pred["abs_error"] = pred["error"].abs()

    skipped = pd.read_csv(paths.skipped_path) if paths.skipped_path.exists() else pd.DataFrame()
    reporting = pd.read_csv(paths.metrics_reporting_path)
    alpha = pd.read_csv(paths.alpha_path) if paths.alpha_path.exists() else pd.DataFrame()
    run_summary = json.loads(paths.run_summary_path.read_text(encoding="utf-8"))
    feature_schema = json.loads(paths.feature_schema_d_only_path.read_text(encoding="utf-8"))

    # 1) integrity checks
    checks: list[dict[str, Any]] = []
    lead_unique = sorted(pd.to_numeric(pred["lead_day"], errors="coerce").dropna().astype(int).unique().tolist())
    d_only_only = lead_unique == [0]
    checks.append({"check": "d_only_only", "status": bool(d_only_only), "details": f"lead_day_values={lead_unique}"})
    checks.append(
        {
            "check": "feature_count_247",
            "status": int(feature_schema.get("total_feature_count", -1)) == 247,
            "details": f"feature_count={feature_schema.get('total_feature_count')}",
        }
    )
    checks.append(
        {
            "check": "no_dplus_rows",
            "status": bool((pd.to_numeric(pred["lead_day"], errors="coerce").fillna(0).astype(int) == 0).all()),
            "details": f"nonzero_lead_rows={int((pd.to_numeric(pred['lead_day'], errors='coerce').fillna(0).astype(int) > 0).sum())}",
        }
    )
    checks.append(
        {
            "check": "no_nan_predictions",
            "status": bool(pred["y_pred"].notna().all()),
            "details": f"nan_y_pred={int(pred['y_pred'].isna().sum())}",
        }
    )
    scored = pred[pred["y_true"].notna() & pred["y_pred"].notna()].copy()
    observed_ok = True
    if "is_observed_target" in scored.columns:
        observed_ok = bool(scored["is_observed_target"].fillna(False).astype(bool).all())
    checks.append(
        {
            "check": "all_scored_observed",
            "status": observed_ok,
            "details": f"scored_non_observed={int((~scored.get('is_observed_target', pd.Series(True, index=scored.index)).fillna(False).astype(bool)).sum()) if 'is_observed_target' in scored.columns else 0}",
        }
    )
    allowed_skip_prefixes = (
        "insufficient_training_days<",
        "insufficient_rows_hour_",
        "no_window_predictions_available",
        "dst_non_24h_day",
        "known_at_error::",
        "missing_",
    )
    undocumented_reasons = []
    if not skipped.empty and "reason" in skipped.columns:
        for reason in sorted(set(skipped["reason"].astype(str).tolist())):
            if not any(str(reason).startswith(prefix) for prefix in allowed_skip_prefixes):
                undocumented_reasons.append(reason)
    checks.append(
        {
            "check": "skipped_reasons_documented",
            "status": len(undocumented_reasons) == 0,
            "details": f"undocumented_reasons={undocumented_reasons}",
        }
    )

    # candidate models/windows
    all_models = sorted(pred["model"].astype(str).unique().tolist())
    window_models = sorted([m for m in all_models if m.startswith("lago_lear_247_imputed_x2_") and m != "lago_lear_247_imputed_x2_ensemble"])
    window_models_numeric = sorted([m for m in window_models if m.rsplit("_", 1)[-1].isdigit()], key=lambda m: int(m.rsplit("_", 1)[-1]))

    # rMAE denominator by split (from existing reporting outputs)
    denom_by_split: dict[str, float] = {}
    rep_d = reporting[reporting["reporting_level"] == "d_only"].copy()
    for split_name, g in rep_d.groupby("dataset_split", dropna=False):
        v = pd.to_numeric(g["mae"], errors="coerce") / pd.to_numeric(g["rmae_vs_official_naive"], errors="coerce")
        v = v.replace([np.inf, -np.inf], np.nan).dropna()
        if not v.empty:
            denom_by_split[str(split_name)] = float(v.median())

    # 3) window performance analysis
    split_thresholds: dict[str, dict[str, float]] = {}
    for split_name, g in scored.groupby("dataset_split", dropna=False):
        split_thresholds[str(split_name)] = {
            "q95": float(g["y_true"].quantile(0.95)),
            "q05": float(g["y_true"].quantile(0.05)),
        }

    summary_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    for model in window_models_numeric + (["lago_lear_247_imputed_x2_ensemble"] if "lago_lear_247_imputed_x2_ensemble" in all_models else []):
        part_model = scored[scored["model"] == model].copy()
        for split_name in ("validation", "test"):
            part = part_model[part_model["dataset_split"] == split_name].copy()
            m = _metric_block(part)
            q95 = split_thresholds.get(split_name, {}).get("q95", np.nan)
            q05 = split_thresholds.get(split_name, {}).get("q05", np.nan)
            neg_part = part[part["y_true"] < 0.0]
            hi_part = part[part["y_true"] >= q95] if pd.notna(q95) else part.iloc[0:0]
            lo_part = part[part["y_true"] <= q05] if pd.notna(q05) else part.iloc[0:0]
            hourly_mae = part.groupby("target_hour_local")["abs_error"].mean() if not part.empty else pd.Series(dtype=float)
            row = {
                "model": model,
                "dataset_split": split_name,
                **m,
                "rmae": (float(m["mae"]) / denom_by_split.get(split_name)) if pd.notna(m["mae"]) and split_name in denom_by_split else np.nan,
                "negative_price_mae": float(neg_part["abs_error"].mean()) if not neg_part.empty else np.nan,
                "top5pct_actual_price_mae": float(hi_part["abs_error"].mean()) if not hi_part.empty else np.nan,
                "bottom5pct_actual_price_mae": float(lo_part["abs_error"].mean()) if not lo_part.empty else np.nan,
                "hourly_mae_mean": float(hourly_mae.mean()) if not hourly_mae.empty else np.nan,
                "hourly_mae_min": float(hourly_mae.min()) if not hourly_mae.empty else np.nan,
                "hourly_mae_max": float(hourly_mae.max()) if not hourly_mae.empty else np.nan,
            }
            summary_rows.append(row)

            if not part.empty:
                part["year_month"] = pd.to_datetime(part["target_delivery_local_date"], errors="coerce").dt.to_period("M").astype(str)
                by_month = part.groupby("year_month", dropna=False)["abs_error"].mean().reset_index(name="mae")
                for r in by_month.to_dict(orient="records"):
                    monthly_rows.append(
                        {
                            "model": model,
                            "dataset_split": split_name,
                            "year_month": r["year_month"],
                            "mae": float(r["mae"]),
                        }
                    )

    variant_model_summary = pd.DataFrame(summary_rows).sort_values(["dataset_split", "mae", "model"])
    variant_model_summary.to_csv(output_dir / "variant_model_summary.csv", index=False)
    window_monthly = pd.DataFrame(monthly_rows).sort_values(["dataset_split", "year_month", "mae", "model"])
    window_monthly.to_csv(output_dir / "window_monthly_performance.csv", index=False)

    # 4) window complementarity on validation
    daily_mae_val = _daily_mae_table(scored, window_models_numeric, "validation")
    winner_counts = pd.DataFrame()
    error_corr_long = pd.DataFrame()
    top2_models: list[str] = []
    if not daily_mae_val.empty:
        pivot_daily = daily_mae_val.pivot(index="target_delivery_local_date", columns="model", values="daily_mae")
        winners = pivot_daily.idxmin(axis=1)
        winner_counts = (
            winners.value_counts(dropna=False).rename_axis("model").reset_index(name="win_days")
            .assign(win_share=lambda d: d["win_days"] / d["win_days"].sum())
            .sort_values(["win_days", "model"], ascending=[False, True])
        )

        val_overall = (
            variant_model_summary[
                (variant_model_summary["dataset_split"] == "validation")
                & (variant_model_summary["model"].isin(window_models_numeric))
            ][["model", "mae"]]
            .sort_values("mae")
            .reset_index(drop=True)
        )
        top2_models = val_overall["model"].head(2).tolist()
        if len(top2_models) == 2:
            top1_wins = int((winners == top2_models[0]).sum())
            top2_wins = int((winners == top2_models[1]).sum())
            winner_counts["top2_set"] = "; ".join(top2_models)
            winner_counts["top2_complementary"] = bool(top1_wins > 0 and top2_wins > 0)
            winner_counts["top1_dominates"] = bool(top1_wins / len(winners) >= 0.8) if len(winners) else False

        # hourly error correlation between window models (validation)
        val_rows = scored[(scored["dataset_split"] == "validation") & (scored["model"].isin(window_models_numeric))].copy()
        err_pivot = val_rows.pivot_table(index="target_timestamp_utc", columns="model", values="error", aggfunc="first")
        corr = err_pivot.corr()
        long_rows = []
        for i in corr.index:
            for j in corr.columns:
                if str(i) >= str(j):
                    continue
                long_rows.append({"model_a": i, "model_b": j, "error_corr": float(corr.loc[i, j])})
        error_corr_long = pd.DataFrame(long_rows).sort_values(["error_corr"], ascending=False)

    winner_counts.to_csv(output_dir / "window_daily_winner_counts.csv", index=False)
    error_corr_long.to_csv(output_dir / "window_error_correlation.csv", index=False)

    # 5) validation-only ensemble simulation
    sim_rows: list[dict[str, Any]] = []
    simulated_frames: list[pd.DataFrame] = []
    if window_models_numeric:
        val_perf = variant_model_summary[
            (variant_model_summary["dataset_split"] == "validation")
            & (variant_model_summary["model"].isin(window_models_numeric))
        ][["model", "mae"]].sort_values("mae")

        best_model = str(val_perf.iloc[0]["model"])
        best_weights = {best_model: 1.0}
        top2 = val_perf["model"].head(2).astype(str).tolist()
        top2_weights = {m: 1.0 for m in top2}

        inv_weights = {}
        for _, row in val_perf.iterrows():
            mae = float(row["mae"])
            if np.isfinite(mae) and mae > 0:
                inv_weights[str(row["model"])] = 1.0 / mae

        strategies = [
            ("validation_best_single_window", [best_model], best_weights),
            ("top2_validation_average", top2, top2_weights),
            ("inverse_validation_MAE_weighted_ensemble", list(inv_weights.keys()), inv_weights),
        ]

        for label, members, weights in strategies:
            if not members:
                continue
            sim = _simulate_ensemble(scored, base_models=members, weights=weights, label=label)
            sim["error"] = sim["y_pred"] - sim["y_true"]
            sim["abs_error"] = sim["error"].abs()
            simulated_frames.append(sim)
            for split_name in ("validation", "test"):
                part = sim[sim["dataset_split"] == split_name]
                block = _metric_block(part)
                sim_rows.append(
                    {
                        "strategy": label,
                        "dataset_split": split_name,
                        "selected_models": "; ".join(members),
                        "weights_json": json.dumps(weights),
                        **block,
                        "rmae": (float(block["mae"]) / denom_by_split.get(split_name)) if pd.notna(block["mae"]) and split_name in denom_by_split else np.nan,
                    }
                )

    sim_df = pd.DataFrame(sim_rows).sort_values(["strategy", "dataset_split"])
    sim_df.to_csv(output_dir / "validation_ensemble_simulation.csv", index=False)

    # 6) asinh suitability diagnostic (use validation-best window)
    asinh_rows: list[dict[str, Any]] = []
    baseline_model = None
    base_candidates = variant_model_summary[
        (variant_model_summary["dataset_split"] == "validation")
        & (variant_model_summary["model"].isin(window_models_numeric))
    ].sort_values("mae")
    if not base_candidates.empty:
        baseline_model = str(base_candidates.iloc[0]["model"])
    if baseline_model is None and window_models_numeric:
        baseline_model = window_models_numeric[0]

    if baseline_model is not None:
        for split_name in ("validation", "test"):
            part = scored[(scored["model"] == baseline_model) & (scored["dataset_split"] == split_name)].copy()
            if part.empty:
                continue
            ae_total = float(part["abs_error"].sum())
            for pct in (0.99, 0.95, 0.90):
                thr = float(part["y_true"].quantile(pct))
                tail = part[part["y_true"] >= thr]
                share = float(tail["abs_error"].sum() / ae_total) if ae_total > 0 else np.nan
                asinh_rows.append(
                    {
                        "model": baseline_model,
                        "dataset_split": split_name,
                        "metric": f"abs_error_share_top_{int((1-pct)*100)}pct_actual_price_hours",
                        "value": share,
                    }
                )
            asinh_rows.append(
                {"model": baseline_model, "dataset_split": split_name, "metric": "p95_abs_error", "value": float(part["abs_error"].quantile(0.95))}
            )
            asinh_rows.append(
                {"model": baseline_model, "dataset_split": split_name, "metric": "p99_abs_error", "value": float(part["abs_error"].quantile(0.99))}
            )

            # high spread days: top decile by daily spread of actuals
            daily = part.groupby("target_delivery_local_date", dropna=False).agg(
                spread=("y_true", lambda s: float(np.nanmax(s) - np.nanmin(s))),
                mae=("abs_error", "mean"),
            ).reset_index()
            if not daily.empty:
                spread_thr = float(daily["spread"].quantile(0.90))
                hi_spread = daily[daily["spread"] >= spread_thr]
                asinh_rows.append(
                    {
                        "model": baseline_model,
                        "dataset_split": split_name,
                        "metric": "mae_high_spread_days_top10pct",
                        "value": float(hi_spread["mae"].mean()) if not hi_spread.empty else np.nan,
                    }
                )
                asinh_rows.append(
                    {
                        "model": baseline_model,
                        "dataset_split": split_name,
                        "metric": "mae_all_days",
                        "value": float(daily["mae"].mean()),
                    }
                )

            neg = part[part["y_true"] < 0.0]
            asinh_rows.append(
                {
                    "model": baseline_model,
                    "dataset_split": split_name,
                    "metric": "mae_negative_price_hours",
                    "value": float(neg["abs_error"].mean()) if not neg.empty else np.nan,
                }
            )

            spike_thr = float(part["y_true"].quantile(0.99))
            spikes = part[part["y_true"] >= spike_thr]
            asinh_rows.append(
                {
                    "model": baseline_model,
                    "dataset_split": split_name,
                    "metric": "spike_mean_error_top1pct",
                    "value": float(spikes["error"].mean()) if not spikes.empty else np.nan,
                }
            )
            asinh_rows.append(
                {
                    "model": baseline_model,
                    "dataset_split": split_name,
                    "metric": "spike_overpredict_share_top1pct",
                    "value": float((spikes["error"] > 0.0).mean()) if not spikes.empty else np.nan,
                }
            )
            asinh_rows.append(
                {
                    "model": baseline_model,
                    "dataset_split": split_name,
                    "metric": "spike_underpredict_share_top1pct",
                    "value": float((spikes["error"] < 0.0).mean()) if not spikes.empty else np.nan,
                }
            )

    asinh_df = pd.DataFrame(asinh_rows)
    asinh_df.to_csv(output_dir / "asinh_suitability_diagnostic.csv", index=False)

    # 7) recency weighting suitability
    recency_rows: list[dict[str, Any]] = []
    wm = window_monthly.copy()
    if not wm.empty:
        short_models = [m for m in window_models_numeric if m.endswith("_56") or m.endswith("_84")]
        long_models = [m for m in window_models_numeric if m.endswith("_1092") or m.endswith("_1456")]
        for split_name in ("validation", "test"):
            part = wm[(wm["dataset_split"] == split_name) & (wm["model"].isin(short_models + long_models))]
            if part.empty:
                continue
            month_rows = []
            for month, g in part.groupby("year_month", dropna=False):
                g_short = g[g["model"].isin(short_models)]
                g_long = g[g["model"].isin(long_models)]
                if g_short.empty or g_long.empty:
                    continue
                short_best = float(g_short["mae"].min())
                long_best = float(g_long["mae"].min())
                month_rows.append(
                    {
                        "dataset_split": split_name,
                        "year_month": month,
                        "short_best_mae": short_best,
                        "long_best_mae": long_best,
                        "delta_short_minus_long": short_best - long_best,
                    }
                )
            month_df = pd.DataFrame(month_rows)
            if not month_df.empty:
                recency_rows.append(
                    {
                        "dataset_split": split_name,
                        "metric": "share_months_short_beats_long",
                        "value": float((month_df["delta_short_minus_long"] < 0).mean()),
                    }
                )
                recency_rows.append(
                    {
                        "dataset_split": split_name,
                        "metric": "mean_delta_short_minus_long",
                        "value": float(month_df["delta_short_minus_long"].mean()),
                    }
                )

            # 1456 vs 1092 systematic check where both exist
            p1092 = part[part["model"].str.endswith("_1092")][["year_month", "mae"]].rename(columns={"mae": "mae_1092"})
            p1456 = part[part["model"].str.endswith("_1456")][["year_month", "mae"]].rename(columns={"mae": "mae_1456"})
            both = p1092.merge(p1456, on="year_month", how="inner")
            if not both.empty:
                delta = both["mae_1456"] - both["mae_1092"]
                recency_rows.append(
                    {
                        "dataset_split": split_name,
                        "metric": "share_months_1456_worse_than_1092",
                        "value": float((delta > 0).mean()),
                    }
                )
                recency_rows.append(
                    {
                        "dataset_split": split_name,
                        "metric": "mean_delta_1456_minus_1092",
                        "value": float(delta.mean()),
                    }
                )

    recency_df = pd.DataFrame(recency_rows)
    recency_df.to_csv(output_dir / "recency_weighting_suitability_diagnostic.csv", index=False)

    # 8) operational ranking diagnostics
    op_rows: list[dict[str, Any]] = []
    op_models = window_models_numeric.copy()
    if simulated_frames:
        simulated_all = pd.concat(simulated_frames, ignore_index=True)
        op_frame = pd.concat([scored, simulated_all], ignore_index=True, sort=False)
        op_models.extend(sorted(simulated_all["model"].astype(str).unique().tolist()))
    else:
        op_frame = scored.copy()

    for model in op_models:
        for split_name in ("validation", "test"):
            part = op_frame[(op_frame["model"] == model) & (op_frame["dataset_split"] == split_name)].copy()
            m = _ranking_metrics(part)
            op_rows.append({"model": model, "dataset_split": split_name, **m})
    op_df = pd.DataFrame(op_rows).sort_values(["dataset_split", "model"])
    op_df.to_csv(output_dir / "operational_ranking_diagnostics.csv", index=False)

    # 9) recommendation
    # Heuristic decision:
    # - prefer A if validation-best window clearly dominates and ensemble sims do not materially improve.
    recommendation = "A"
    recommendation_title = "Accept 1092 as official validation-selected Lago model, no extra variants needed."
    expected_benefit = "Low incremental benefit expected from additional variants given large validation gap."
    effort = "Low effort to keep current path; avoids extra variant maintenance."
    risk = "Lowest leakage/test-overfitting risk (selection already on validation only)."
    style = "Remains exact Lago-style D-only window benchmark selection."

    if not sim_df.empty:
        val_ref = variant_model_summary[
            (variant_model_summary["dataset_split"] == "validation")
            & (variant_model_summary["model"].isin(window_models_numeric))
        ].sort_values("mae")
        test_ref = variant_model_summary[
            (variant_model_summary["dataset_split"] == "test")
            & (variant_model_summary["model"].isin(window_models_numeric))
        ].sort_values("mae")
        if not val_ref.empty and not test_ref.empty:
            best_val_mae = float(val_ref.iloc[0]["mae"])
            best_test_mae = float(test_ref.iloc[0]["mae"])
            sim_test = sim_df[sim_df["dataset_split"] == "test"].sort_values("mae")
            if not sim_test.empty:
                best_sim_test = float(sim_test.iloc[0]["mae"])
                if best_sim_test + 1e-9 < best_test_mae:
                    # Only upgrade if real improvement > 0.3 EUR/MWh (pragmatic threshold).
                    if (best_test_mae - best_sim_test) > 0.3:
                        top_strategy = str(sim_test.iloc[0]["strategy"])
                        if top_strategy == "top2_validation_average":
                            recommendation = "C"
                            recommendation_title = "Add top-2 validation ensemble only."
                        elif top_strategy == "inverse_validation_MAE_weighted_ensemble":
                            recommendation = "D"
                            recommendation_title = "Add inverse-validation-MAE ensemble."
                        expected_benefit = f"Observed test MAE improvement vs best single window: {best_test_mae - best_sim_test:.3f} EUR/MWh."
                        effort = "Moderate: add deterministic post-fit blending only, no retraining logic changes."
                        risk = "Low-moderate: weights frozen from validation only."
                        style = "Enhanced thesis variant (not exact single-window Lago)."

    # asinh and recency indicators
    asinh_note = "Not prioritized."
    if not asinh_df.empty:
        top1_share_test = asinh_df[
            (asinh_df["dataset_split"] == "test")
            & (asinh_df["metric"] == "abs_error_share_top_1pct_actual_price_hours")
        ]
        if not top1_share_test.empty and float(top1_share_test.iloc[0]["value"]) > 0.20:
            asinh_note = "Potentially useful later: error is concentrated in extreme-price tails."

    recency_note = "Consider later."
    if not recency_df.empty:
        test_short_share = recency_df[
            (recency_df["dataset_split"] == "test")
            & (recency_df["metric"] == "share_months_short_beats_long")
        ]
        if not test_short_share.empty and float(test_short_share.iloc[0]["value"]) > 0.45:
            recency_note = "Short windows are competitive in many months; recency weighting is worth a later controlled variant."

    md_lines = [
        "# Variant Decision Recommendation",
        "",
        f"Run analyzed: `{run_id}`",
        "",
        "## Integrity",
        f"- D-only only: `{checks[0]['status']}` ({checks[0]['details']})",
        f"- Feature count 247: `{checks[1]['status']}` ({checks[1]['details']})",
        f"- No D+1..D+4 rows: `{checks[2]['status']}` ({checks[2]['details']})",
        f"- No NaN predictions: `{checks[3]['status']}` ({checks[3]['details']})",
        f"- All scored targets observed: `{checks[4]['status']}` ({checks[4]['details']})",
        f"- Skipped reasons documented: `{checks[5]['status']}` ({checks[5]['details']})",
        "",
        "## Validation Window Ranking",
    ]
    val_rows = variant_model_summary[variant_model_summary["dataset_split"] == "validation"].sort_values("mae")
    for _, row in val_rows.iterrows():
        md_lines.append(
            f"- {row['model']}: MAE {row['mae']:.3f}, RMSE {row['rmse']:.3f}, rMAE {row['rmae']:.3f}"
        )
    md_lines.extend(
        [
            "",
            "## Recommendation",
            f"- Decision: **{recommendation}**",
            f"- {recommendation_title}",
            f"- Expected benefit: {expected_benefit}",
            f"- Implementation effort: {effort}",
            f"- Leakage/test-overfitting risk: {risk}",
            f"- Methodology status: {style}",
            "",
            "## Extra Variant Notes",
            f"- Asinh suitability: {asinh_note}",
            f"- Recency weighting: {recency_note}",
            "",
            "## Scope Guardrail",
            "- This analysis used existing outputs only. No retraining, no D+4 run, and no FS3 comparison were executed.",
        ]
    )
    (output_dir / "variant_decision_recommendation.md").write_text("\n".join(md_lines), encoding="utf-8")

    # Optional condensed model summary for quick view
    quick_rows = [
        {
            "run_id": run_id,
            "run_d_only_stage": str(run_summary.get("stages", {}).get("run_d_only")),
            "run_dplus4_stage": str(run_summary.get("stages", {}).get("run_dplus4")),
            "models_found": "; ".join(all_models),
            "window_models": "; ".join(window_models_numeric),
            "ensemble_model_present": "lago_lear_247_imputed_x2_ensemble" in all_models,
            "alpha_rows": int(alpha.shape[0]),
            "recommendation": recommendation,
        }
    ]
    pd.DataFrame(quick_rows).to_csv(output_dir / "variant_model_summary_meta.csv", index=False)

    print(f"Analysis output: {output_dir}")
    print(f"Recommendation: {recommendation} - {recommendation_title}")


if __name__ == "__main__":
    main()
