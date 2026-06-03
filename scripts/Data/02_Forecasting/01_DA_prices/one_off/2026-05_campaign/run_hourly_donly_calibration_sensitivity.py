from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
GENERATOR_SCRIPT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_hourly_scenario_generation_with_lear_strict.py"
OUTPUT_ROOT = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "scenario_evaluation"
BASELINE_V1_RUN = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "notebook_artifacts" / "01_da_price_scenario_generation_hourly_with_lear_strict" / "20260512_134855"
OLD_PREFIX_RUN = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "notebook_artifacts" / "01_da_price_scenario_generation_hourly_with_lear_strict" / "20260511_212611"


@dataclass(frozen=True)
class GridConfig:
    reduced_scenarios: int
    protected_tail_share: float
    residual_scale_factor: float

    @property
    def config_id(self) -> str:
        return (
            f"nfinal_{self.reduced_scenarios}"
            f"__tail_{str(self.protected_tail_share).replace('.', 'p')}"
            f"__scale_{str(self.residual_scale_factor).replace('.', 'p')}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run hourly D-only tail-aware calibration sensitivity.")
    parser.add_argument(
        "--resume-dir",
        type=Path,
        default=None,
        help="Optional existing calibration output directory to resume.",
    )
    return parser.parse_args()


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if values.size == 0:
        return np.nan
    if values.size == 1:
        return float(values[0])
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    if cumulative[-1] <= 0.0:
        return np.nan
    cumulative = cumulative / cumulative[-1]
    return float(np.interp(float(quantile), cumulative, sorted_values))


def _parse_run_dir_from_stdout(stdout: str) -> Path:
    match = re.search(r"\{[\s\S]*\}", stdout)
    if not match:
        raise RuntimeError(f"Could not parse run_dir from generator output:\n{stdout[-1500:]}")
    payload = json.loads(match.group(0))
    run_dir = Path(str(payload.get("run_dir", "")).strip())
    if not run_dir.is_absolute():
        run_dir = (REPO_ROOT / run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Parsed run_dir does not exist: {run_dir}")
    return run_dir


def _period_quantiles(prices: pd.DataFrame, *, weighted: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "delivery_day", "period_timestamp"]
    for keys, group in prices.groupby(group_cols, dropna=False):
        candidate_key, candidate_label, dataset_split, delivery_day, period_timestamp = keys
        vals = pd.to_numeric(group["scenario_price"], errors="coerce").dropna()
        if vals.empty:
            continue
        y = pd.to_numeric(group["actual_price"], errors="coerce")
        if weighted:
            if "probability" in group.columns:
                probs = pd.to_numeric(group["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            else:
                probs = np.zeros(vals.shape[0], dtype=float)
            val_arr = vals.to_numpy(dtype=float)
            if probs.size != val_arr.size or probs.sum() <= 0.0:
                probs = np.ones_like(val_arr, dtype=float)
            p05 = _weighted_quantile(val_arr, probs, 0.05)
            p50 = _weighted_quantile(val_arr, probs, 0.50)
            p95 = _weighted_quantile(val_arr, probs, 0.95)
        else:
            p05 = float(vals.quantile(0.05))
            p50 = float(vals.quantile(0.50))
            p95 = float(vals.quantile(0.95))
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "dataset_split": str(dataset_split),
                "delivery_day": str(delivery_day),
                "period_timestamp": pd.Timestamp(period_timestamp),
                "y_true": float(y.dropna().iloc[0]) if y.notna().any() else np.nan,
                "p05": p05,
                "p50": p50,
                "p95": p95,
                "scenario_min": float(vals.min()),
                "scenario_max": float(vals.max()),
                "width": float(p95 - p05),
            }
        )
    return pd.DataFrame(rows)


def _metric_summary(q: pd.DataFrame) -> pd.DataFrame:
    if q.empty:
        return pd.DataFrame()
    work = q.copy()
    work["inside"] = (work["y_true"] >= work["p05"]) & (work["y_true"] <= work["p95"])
    work["outside_spread"] = (work["y_true"] < work["scenario_min"]) | (work["y_true"] > work["scenario_max"])
    work["high_tail_miss"] = work["y_true"] > work["p95"]
    work["low_tail_miss"] = work["y_true"] < work["p05"]
    work["p50_bias"] = work["p50"] - work["y_true"]
    out = (
        work.groupby(["candidate_key", "candidate_label", "dataset_split"], dropna=False)
        .agg(
            coverage_p05_p95=("inside", "mean"),
            outside_spread_frequency=("outside_spread", "mean"),
            p50_bias=("p50_bias", "mean"),
            average_interval_width=("width", "mean"),
            high_tail_miss_rate=("high_tail_miss", "mean"),
            low_tail_miss_rate=("low_tail_miss", "mean"),
            n_points=("inside", "size"),
        )
        .reset_index()
    )
    return out


def _decomposition(q: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if q.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    work = q.copy()
    local = pd.to_datetime(work["period_timestamp"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
    work["month"] = local.dt.month.astype("Int64")
    work["hour"] = local.dt.hour.astype("Int64")
    work["inside"] = (work["y_true"] >= work["p05"]) & (work["y_true"] <= work["p95"])
    work["outside_spread"] = (work["y_true"] < work["scenario_min"]) | (work["y_true"] > work["scenario_max"])
    work["high_tail_miss"] = work["y_true"] > work["p95"]
    work["low_tail_miss"] = work["y_true"] < work["p05"]
    work["p50_bias"] = work["p50"] - work["y_true"]
    work["width"] = work["p95"] - work["p05"]
    work["q10"] = work.groupby(["candidate_key", "dataset_split"], dropna=False)["y_true"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").quantile(0.10)
    )
    work["q90"] = work.groupby(["candidate_key", "dataset_split"], dropna=False)["y_true"].transform(
        lambda s: pd.to_numeric(s, errors="coerce").quantile(0.90)
    )
    work["price_regime"] = np.select(
        [
            work["y_true"] < 0.0,
            work["y_true"] <= work["q10"],
            work["y_true"] >= work["q90"],
        ],
        ["negative", "low", "high"],
        default="mid",
    )
    agg = {
        "coverage_p05_p95": ("inside", "mean"),
        "outside_spread_frequency": ("outside_spread", "mean"),
        "high_tail_miss_rate": ("high_tail_miss", "mean"),
        "low_tail_miss_rate": ("low_tail_miss", "mean"),
        "p50_bias": ("p50_bias", "mean"),
        "average_interval_width": ("width", "mean"),
        "n_points": ("inside", "size"),
    }
    by_month = work.groupby(["candidate_key", "candidate_label", "dataset_split", "month"], dropna=False).agg(**agg).reset_index()
    by_hour = work.groupby(["candidate_key", "candidate_label", "dataset_split", "hour"], dropna=False).agg(**agg).reset_index()
    by_regime = work.groupby(["candidate_key", "candidate_label", "dataset_split", "price_regime"], dropna=False).agg(**agg).reset_index()
    return by_month, by_hour, by_regime


def _daily_shape_coverage(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    daily = (
        prices.groupby(["candidate_key", "candidate_label", "dataset_split", "delivery_day", "scenario_id"], dropna=False)
        .agg(
            probability=("probability", "first"),
            actual_mean=("actual_price", "mean"),
            actual_max=("actual_price", "max"),
            actual_min=("actual_price", "min"),
            actual_spread=("actual_price", lambda s: float(pd.Series(s).max() - pd.Series(s).min())),
            scenario_mean=("scenario_price", "mean"),
            scenario_max=("scenario_price", "max"),
            scenario_min=("scenario_price", "min"),
            scenario_spread=("scenario_price", lambda s: float(pd.Series(s).max() - pd.Series(s).min())),
            actual_ramp=("actual_price", lambda s: float(pd.Series(s).astype(float).diff().abs().max()) if len(s) > 1 else 0.0),
            scenario_ramp=("scenario_price", lambda s: float(pd.Series(s).astype(float).diff().abs().max()) if len(s) > 1 else 0.0),
        )
        .reset_index()
    )
    specs = [
        ("mean", "actual_mean", "scenario_mean"),
        ("max", "actual_max", "scenario_max"),
        ("min", "actual_min", "scenario_min"),
        ("spread", "actual_spread", "scenario_spread"),
        ("ramp", "actual_ramp", "scenario_ramp"),
    ]
    rows: list[dict[str, Any]] = []
    for keys, grp in daily.groupby(["candidate_key", "candidate_label", "dataset_split"], dropna=False):
        candidate_key, candidate_label, dataset_split = keys
        row: dict[str, Any] = {
            "candidate_key": str(candidate_key),
            "candidate_label": str(candidate_label),
            "dataset_split": str(dataset_split),
        }
        for metric_name, actual_col, scen_col in specs:
            cover_flags = []
            for _, per_day in grp.groupby("delivery_day", dropna=False):
                vals = pd.to_numeric(per_day[scen_col], errors="coerce").to_numpy(dtype=float)
                probs = pd.to_numeric(per_day["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                actual_values = pd.to_numeric(per_day[actual_col], errors="coerce").dropna()
                if vals.size == 0 or actual_values.empty:
                    continue
                if probs.sum() <= 0.0:
                    probs = np.ones_like(vals, dtype=float)
                low = _weighted_quantile(vals, probs, 0.05)
                high = _weighted_quantile(vals, probs, 0.95)
                actual_val = float(actual_values.iloc[0])
                cover_flags.append(float(low <= actual_val <= high))
            row[f"daily_{metric_name}_coverage_p05_p95"] = float(np.mean(cover_flags)) if cover_flags else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _cvar_tail_cardinality(prices: pd.DataFrame, alpha: float = 0.95) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    per_scenario_day = (
        prices.groupby(["candidate_key", "candidate_label", "dataset_split", "delivery_day", "scenario_id"], dropna=False)
        .agg(
            scenario_daily_mean=("scenario_price", "mean"),
            probability=("probability", "first"),
        )
        .reset_index()
    )
    rows: list[dict[str, Any]] = []
    tail_mass = max(1.0 - float(alpha), 0.0)
    for keys, grp in per_scenario_day.groupby(["candidate_key", "candidate_label", "dataset_split", "delivery_day"], dropna=False):
        candidate_key, candidate_label, dataset_split, delivery_day = keys
        ordered = grp.sort_values(["scenario_daily_mean", "scenario_id"], ascending=[False, True]).copy()
        probs = pd.to_numeric(ordered["probability"], errors="coerce").fillna(0.0)
        if probs.sum() > 0.0:
            probs = probs / probs.sum()
        else:
            probs = pd.Series(np.repeat(1.0 / max(len(ordered), 1), len(ordered)), index=ordered.index)
        ordered["prob_norm"] = probs
        ordered["cum_prob"] = probs.cumsum()
        tail = ordered[ordered["cum_prob"] <= tail_mass].copy()
        if tail.empty and not ordered.empty:
            tail = ordered.head(1).copy()
        rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "dataset_split": str(dataset_split),
                "delivery_day": str(delivery_day),
                "cvar_tail_cardinality": int(tail["scenario_id"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def _run_generator_for_config(cfg: GridConfig) -> Path:
    cmd = [
        sys.executable,
        str(GENERATOR_SCRIPT),
        "--horizon-mode",
        "D_ONLY",
        "--n-raw",
        "400",
        "--n-final",
        str(cfg.reduced_scenarios),
        "--protected-tail-share",
        f"{cfg.protected_tail_share:.2f}",
        "--residual-scale-factor",
        f"{cfg.residual_scale_factor:.2f}",
        "--target-split-mode",
        "validation_only",
        "--random-seed",
        "42",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Generator failed ({cfg.config_id})\nSTDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-4000:]}"
        )
    return _parse_run_dir_from_stdout(proc.stdout)


def _analyse_run(run_dir: Path, cfg: GridConfig, per_config_dir: Path) -> dict[str, Any]:
    prices = pd.read_csv(run_dir / "scenario_prices_long.csv", low_memory=False)
    metadata = pd.read_csv(run_dir / "scenario_metadata.csv", low_memory=False)
    run_summary = json.loads((run_dir / "scenario_generation_run_summary.json").read_text(encoding="utf-8"))
    run_config = json.loads((run_dir / "scenario_generation_config.json").read_text(encoding="utf-8"))

    prices = prices[prices["dataset_split"].astype(str) == "validation"].copy()
    metadata = metadata[metadata["dataset_split"].astype(str) == "validation"].copy()

    weighted_q = _period_quantiles(prices, weighted=True)
    unweighted_q = _period_quantiles(prices, weighted=False)
    weighted_summary = _metric_summary(weighted_q)
    unweighted_summary = _metric_summary(unweighted_q)
    by_month, by_hour, by_regime = _decomposition(weighted_q)
    daily_shape = _daily_shape_coverage(prices)
    cvar_cardinality = _cvar_tail_cardinality(prices, alpha=0.95)

    # Tail/protection diagnostics.
    protected_summary = pd.DataFrame()
    if not metadata.empty:
        key_cols = ["candidate_key", "candidate_label", "dataset_split", "delivery_day"]
        if "reduced_scenario_probability" not in metadata.columns:
            metadata["reduced_scenario_probability"] = pd.to_numeric(metadata.get("probability"), errors="coerce")
        protected_summary = (
            metadata.groupby(key_cols, dropna=False)
            .apply(
                lambda grp: pd.Series(
                    {
                        "protected_tail_count": int(grp["tail_protection_flag"].fillna(False).sum()) if "tail_protection_flag" in grp.columns else 0,
                        "protected_tail_probability_mass": float(
                            pd.to_numeric(
                                grp.loc[grp.get("tail_protection_flag", pd.Series(dtype=bool)).fillna(False), "reduced_scenario_probability"],
                                errors="coerce",
                            )
                            .fillna(0.0)
                            .sum()
                        )
                        if {"tail_protection_flag", "reduced_scenario_probability"}.issubset(set(grp.columns))
                        else np.nan,
                        "protected_tail_categories": ",".join(
                            sorted(
                                {
                                    token.strip()
                                    for value in grp.get("tail_categories", pd.Series(dtype=str)).dropna().astype(str).tolist()
                                    for token in value.split(",")
                                    if token.strip()
                                }
                            )
                        ),
                    }
                )
            )
            .reset_index()
        )

    prob_fail_count = 0
    if not metadata.empty:
        prob_col = "reduced_scenario_probability" if "reduced_scenario_probability" in metadata.columns else "probability"
        prob_sums = (
            metadata.groupby(["candidate_key", "dataset_split", "delivery_day"], dropna=False)[prob_col]
            .sum(min_count=1)
            .reset_index(name="prob_sum")
        )
        prob_fail_count = int((prob_sums["prob_sum"].sub(1.0).abs() > 1e-6).sum())

    weighted_summary.to_csv(per_config_dir / "weighted_summary_by_candidate.csv", index=False)
    unweighted_summary.to_csv(per_config_dir / "unweighted_summary_by_candidate.csv", index=False)
    by_month.to_csv(per_config_dir / "weighted_decomposition_by_month.csv", index=False)
    by_hour.to_csv(per_config_dir / "weighted_decomposition_by_hour.csv", index=False)
    by_regime.to_csv(per_config_dir / "weighted_decomposition_by_regime.csv", index=False)
    daily_shape.to_csv(per_config_dir / "weighted_daily_shape_coverage.csv", index=False)
    cvar_cardinality.to_csv(per_config_dir / "cvar_tail_cardinality_by_day.csv", index=False)
    protected_summary.to_csv(per_config_dir / "protected_tail_summary_by_day.csv", index=False)

    weighted_means = weighted_summary.mean(numeric_only=True).to_dict()
    unweighted_means = unweighted_summary.mean(numeric_only=True).to_dict()
    daily_shape_means = daily_shape.mean(numeric_only=True).to_dict() if not daily_shape.empty else {}
    cvar_avg = float(pd.to_numeric(cvar_cardinality["cvar_tail_cardinality"], errors="coerce").mean()) if not cvar_cardinality.empty else np.nan
    cvar_min = float(pd.to_numeric(cvar_cardinality["cvar_tail_cardinality"], errors="coerce").min()) if not cvar_cardinality.empty else np.nan
    protected_count_mean = (
        float(pd.to_numeric(protected_summary["protected_tail_count"], errors="coerce").mean())
        if not protected_summary.empty
        else np.nan
    )
    protected_mass_mean = (
        float(pd.to_numeric(protected_summary["protected_tail_probability_mass"], errors="coerce").mean())
        if not protected_summary.empty
        else np.nan
    )
    protected_categories = sorted(
        {
            token.strip()
            for value in protected_summary.get("protected_tail_categories", pd.Series(dtype=str)).dropna().astype(str).tolist()
            for token in value.split(",")
            if token.strip()
        }
    )

    row: dict[str, Any] = {
        "config_id": cfg.config_id,
        "run_dir": str(run_dir),
        "reduced_scenarios": int(cfg.reduced_scenarios),
        "protected_tail_share": float(cfg.protected_tail_share),
        "residual_scale_factor": float(cfg.residual_scale_factor),
        "weighted_coverage_p05_p95_mean": float(weighted_means.get("coverage_p05_p95", np.nan)),
        "unweighted_coverage_p05_p95_mean": float(unweighted_means.get("coverage_p05_p95", np.nan)),
        "outside_spread_frequency_mean": float(weighted_means.get("outside_spread_frequency", np.nan)),
        "p50_bias_mean": float(weighted_means.get("p50_bias", np.nan)),
        "average_interval_width_mean": float(weighted_means.get("average_interval_width", np.nan)),
        "high_tail_miss_rate_mean": float(weighted_means.get("high_tail_miss_rate", np.nan)),
        "low_tail_miss_rate_mean": float(weighted_means.get("low_tail_miss_rate", np.nan)),
        "daily_mean_coverage_p05_p95_mean": float(daily_shape_means.get("daily_mean_coverage_p05_p95", np.nan)),
        "daily_max_coverage_p05_p95_mean": float(daily_shape_means.get("daily_max_coverage_p05_p95", np.nan)),
        "daily_min_coverage_p05_p95_mean": float(daily_shape_means.get("daily_min_coverage_p05_p95", np.nan)),
        "daily_spread_coverage_p05_p95_mean": float(daily_shape_means.get("daily_spread_coverage_p05_p95", np.nan)),
        "daily_ramp_coverage_p05_p95_mean": float(daily_shape_means.get("daily_ramp_coverage_p05_p95", np.nan)),
        "protected_tail_count_mean": protected_count_mean,
        "protected_tail_probability_mass_mean": protected_mass_mean,
        "protected_tail_categories": ",".join(protected_categories),
        "cvar_tail_cardinality_avg": cvar_avg,
        "cvar_tail_cardinality_min": cvar_min,
        "cvar_tail_cardinality_flag": "warn_fewer_than_2_tail_scenarios" if pd.notna(cvar_avg) and cvar_avg < 2.0 else "pass",
        "probability_sum_fail_groups": int(prob_fail_count),
        "causal_source_filter_violations": int(run_summary.get("causal_source_filter_violations", 0)),
        "selection_split_used": str(run_summary.get("selection_split_used", "missing")),
        "test_used_for_selection": str(run_summary.get("test_used_for_selection", "missing")),
        "calibration_policy": str(run_summary.get("calibration_policy", run_config.get("calibration_policy", "missing"))),
        "calibration_splits_used": ",".join([str(x) for x in run_summary.get("calibration_splits_used", run_config.get("calibration_splits_used", []))]),
        "random_seed_method": str(run_summary.get("random_seed_method", "missing")),
        "probability_policy": str(run_summary.get("probability_policy", "missing")),
        "raw_snapshot_rows_period_quantiles": int(run_summary.get("raw_period_quantiles_rows", 0)),
        "raw_snapshot_rows_validation_summary": int(run_summary.get("raw_validation_summary_rows", 0)),
        "raw_snapshot_rows_daily_shape": int(run_summary.get("raw_daily_shape_summary_rows", 0)),
        "raw_snapshot_rows_tail_score": int(run_summary.get("raw_tail_score_summary_rows", 0)),
    }
    row["methodology_compliance_pass"] = bool(
        str(row["selection_split_used"]) == "validation"
        and str(row["test_used_for_selection"]).lower() == "false"
        and str(row["calibration_policy"]) == "validation_only"
        and int(row["causal_source_filter_violations"]) == 0
        and int(row["probability_sum_fail_groups"]) == 0
    )
    return row


def _compute_baseline_metrics(run_dir: Path) -> dict[str, float]:
    prices = pd.read_csv(run_dir / "scenario_prices_long.csv", low_memory=False)
    prices = prices[prices["dataset_split"].astype(str) == "validation"].copy()
    wq = _period_quantiles(prices, weighted=True)
    ws = _metric_summary(wq)
    mean = ws.mean(numeric_only=True).to_dict()
    return {
        "coverage": float(mean.get("coverage_p05_p95", np.nan)),
        "outside_spread": float(mean.get("outside_spread_frequency", np.nan)),
        "p50_bias": float(mean.get("p50_bias", np.nan)),
        "width": float(mean.get("average_interval_width", np.nan)),
        "high_tail_miss": float(mean.get("high_tail_miss_rate", np.nan)),
        "low_tail_miss": float(mean.get("low_tail_miss_rate", np.nan)),
    }


def _select_best_config(summary: pd.DataFrame, baseline: dict[str, float]) -> pd.Series:
    valid = summary[summary["methodology_compliance_pass"].fillna(False)].copy()
    if valid.empty:
        valid = summary.copy()
    cov_target = 0.875
    valid["coverage_distance"] = (pd.to_numeric(valid["weighted_coverage_p05_p95_mean"], errors="coerce") - cov_target).abs()
    valid["coverage_in_target_band"] = (
        (pd.to_numeric(valid["weighted_coverage_p05_p95_mean"], errors="coerce") >= 0.85)
        & (pd.to_numeric(valid["weighted_coverage_p05_p95_mean"], errors="coerce") <= 0.90)
    )
    valid["high_tail_not_worse_than_v1"] = (
        pd.to_numeric(valid["high_tail_miss_rate_mean"], errors="coerce") <= float(baseline.get("high_tail_miss", np.nan)) + 0.01
    )
    valid["width_ratio_vs_v1"] = pd.to_numeric(valid["average_interval_width_mean"], errors="coerce") / max(float(baseline.get("width", 1.0)), 1e-6)
    valid["low_tail_delta_vs_v1"] = pd.to_numeric(valid["low_tail_miss_rate_mean"], errors="coerce") - float(
        baseline.get("low_tail_miss", np.nan)
    )
    valid["selection_score"] = (
        2.0 * valid["coverage_in_target_band"].astype(float)
        + 1.0 * valid["high_tail_not_worse_than_v1"].astype(float)
        - 3.0 * valid["coverage_distance"]
        - 0.25 * (valid["width_ratio_vs_v1"] - 1.0).clip(lower=0.0)
        - 0.50 * valid["low_tail_delta_vs_v1"].clip(lower=0.0)
        + 0.10 * pd.to_numeric(valid["cvar_tail_cardinality_avg"], errors="coerce").fillna(0.0).clip(upper=4.0)
    )
    ordered = valid.sort_values(
        ["selection_score", "coverage_in_target_band", "high_tail_not_worse_than_v1", "weighted_coverage_p05_p95_mean"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
    return ordered.iloc[0]


def _run_final_selected(best: pd.Series) -> Path:
    cmd = [
        sys.executable,
        str(GENERATOR_SCRIPT),
        "--horizon-mode",
        "D_ONLY",
        "--n-raw",
        "400",
        "--n-final",
        str(int(best["reduced_scenarios"])),
        "--protected-tail-share",
        f"{float(best['protected_tail_share']):.2f}",
        "--residual-scale-factor",
        f"{float(best['residual_scale_factor']):.2f}",
        "--target-split-mode",
        "validation_and_test",
        "--random-seed",
        "42",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Selected full run failed\nSTDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-4000:]}")
    return _parse_run_dir_from_stdout(proc.stdout)


def main() -> int:
    args = _parse_args()
    if args.resume_dir:
        out_dir = args.resume_dir
        if not out_dir.is_absolute():
            out_dir = (REPO_ROOT / out_dir).resolve()
        if not out_dir.exists():
            raise FileNotFoundError(f"--resume-dir does not exist: {out_dir}")
        run_id = out_dir.name
        configs_dir = out_dir / "configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_hourly_donly_calibration_sensitivity")
        out_dir = OUTPUT_ROOT / run_id
        configs_dir = out_dir / "configs"
        out_dir.mkdir(parents=True, exist_ok=False)
        configs_dir.mkdir(parents=True, exist_ok=False)

    grid = [
        GridConfig(reduced_scenarios=nf, protected_tail_share=pts, residual_scale_factor=rsf)
        for nf, pts, rsf in itertools.product([50, 75], [0.10, 0.15, 0.20], [1.00, 1.10, 1.20, 1.30])
    ]

    baseline_metrics = _compute_baseline_metrics(BASELINE_V1_RUN)
    old_prefix_metrics = _compute_baseline_metrics(OLD_PREFIX_RUN) if OLD_PREFIX_RUN.exists() else {}

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for cfg in grid:
        per_cfg_dir = configs_dir / cfg.config_id
        per_cfg_dir.mkdir(parents=True, exist_ok=True)
        try:
            summary_row_path = per_cfg_dir / "config_summary_row.json"
            run_dir_path = per_cfg_dir / "run_dir.txt"

            if summary_row_path.exists():
                row = json.loads(summary_row_path.read_text(encoding="utf-8"))
                rows.append(row)
                continue

            if run_dir_path.exists():
                run_dir = Path(run_dir_path.read_text(encoding="utf-8").strip())
                if not run_dir.is_absolute():
                    run_dir = (REPO_ROOT / run_dir).resolve()
                if not run_dir.exists():
                    raise FileNotFoundError(f"Stored run_dir not found for {cfg.config_id}: {run_dir}")
            else:
                run_dir = _run_generator_for_config(cfg)
                run_dir_path.write_text(str(run_dir), encoding="utf-8")

            row = _analyse_run(run_dir, cfg, per_cfg_dir)
            rows.append(row)
            summary_row_path.write_text(json.dumps(row, indent=2), encoding="utf-8")
        except Exception as exc:
            failures.append({"config_id": cfg.config_id, "error": str(exc)})
            (per_cfg_dir / "failure.txt").write_text(str(exc), encoding="utf-8")

    summary = pd.DataFrame(rows).sort_values("config_id").reset_index(drop=True)
    if summary.empty:
        raise RuntimeError("All calibration configurations failed.")

    best = _select_best_config(summary, baseline_metrics)
    selected_full_run_dir = _run_final_selected(best)
    selected_metrics = _compute_baseline_metrics(selected_full_run_dir)

    # External comparison table for notebook 29.
    comparison_rows = []
    if old_prefix_metrics:
        comparison_rows.append({"run_label": "old_prefix_pre_fix", **old_prefix_metrics})
    comparison_rows.append({"run_label": "tail_aware_v1_20260512_134855", **baseline_metrics})
    comparison_rows.append({"run_label": "selected_calibrated_full_run", **selected_metrics})
    comparison = pd.DataFrame(comparison_rows)

    # Select top-N summary for quick reading.
    leaderboard = summary.sort_values(
        ["methodology_compliance_pass", "weighted_coverage_p05_p95_mean", "high_tail_miss_rate_mean"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    summary.to_csv(out_dir / "calibration_sensitivity_summary.csv", index=False)
    leaderboard.to_csv(out_dir / "calibration_sensitivity_leaderboard.csv", index=False)
    comparison.to_csv(out_dir / "calibration_reference_runs_comparison.csv", index=False)
    pd.DataFrame(failures).to_csv(out_dir / "calibration_failures.csv", index=False)

    payload = {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "baseline_v1_run_dir": str(BASELINE_V1_RUN),
        "old_prefix_run_dir": str(OLD_PREFIX_RUN) if OLD_PREFIX_RUN.exists() else None,
        "n_configurations_total": len(grid),
        "n_configurations_succeeded": int(summary.shape[0]),
        "n_configurations_failed": int(len(failures)),
        "selected_configuration": {
            "config_id": str(best["config_id"]),
            "reduced_scenarios": int(best["reduced_scenarios"]),
            "protected_tail_share": float(best["protected_tail_share"]),
            "residual_scale_factor": float(best["residual_scale_factor"]),
            "validation_metrics": {
                "weighted_coverage_p05_p95_mean": float(best["weighted_coverage_p05_p95_mean"]),
                "outside_spread_frequency_mean": float(best["outside_spread_frequency_mean"]),
                "p50_bias_mean": float(best["p50_bias_mean"]),
                "average_interval_width_mean": float(best["average_interval_width_mean"]),
                "high_tail_miss_rate_mean": float(best["high_tail_miss_rate_mean"]),
                "low_tail_miss_rate_mean": float(best["low_tail_miss_rate_mean"]),
                "protected_tail_probability_mass_mean": float(best["protected_tail_probability_mass_mean"]),
                "cvar_tail_cardinality_avg": float(best["cvar_tail_cardinality_avg"]),
            },
        },
        "selected_full_run_dir": str(selected_full_run_dir),
        "summary_files": {
            "calibration_sensitivity_summary": str(out_dir / "calibration_sensitivity_summary.csv"),
            "calibration_sensitivity_leaderboard": str(out_dir / "calibration_sensitivity_leaderboard.csv"),
            "calibration_reference_runs_comparison": str(out_dir / "calibration_reference_runs_comparison.csv"),
            "calibration_failures": str(out_dir / "calibration_failures.csv"),
        },
    }
    (out_dir / "calibration_run_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
