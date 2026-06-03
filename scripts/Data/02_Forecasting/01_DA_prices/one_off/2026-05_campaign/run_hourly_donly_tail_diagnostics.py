from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


RUN_DIR = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/"
    "01_da_price_scenario_generation_hourly_with_lear_strict/20260512_134855"
)
OLD_RUN_DIR = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/"
    "01_da_price_scenario_generation_hourly_with_lear_strict/20260511_212611"
)


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


def _raw_artifacts_exist(run_dir: Path) -> dict[str, Any]:
    expected = [
        "raw_scenario_prices.csv",
        "raw_scenario_prices.parquet",
        "raw_scenarios.csv",
        "scenario_raw_prices_long.csv",
        "scenario_raw_metadata.csv",
    ]
    found = [name for name in expected if (run_dir / name).exists()]
    return {"found": bool(found), "files": found, "expected_checked": expected}


def _period_quantiles(prices: pd.DataFrame, weighted: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "delivery_day", "period_timestamp"]
    for keys, group in prices.groupby(group_cols, dropna=False):
        candidate_key, candidate_label, dataset_split, delivery_day, period_timestamp = keys
        vals = pd.to_numeric(group["scenario_price"], errors="coerce").dropna()
        if vals.empty:
            continue
        y = pd.to_numeric(group["actual_price"], errors="coerce")
        if weighted:
            w = pd.to_numeric(group["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            if w.sum() <= 0:
                w = np.ones_like(w, dtype=float)
            p05 = _weighted_quantile(vals.to_numpy(dtype=float), w, 0.05)
            p50 = _weighted_quantile(vals.to_numpy(dtype=float), w, 0.50)
            p95 = _weighted_quantile(vals.to_numpy(dtype=float), w, 0.95)
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
                "scenario_count": int(group["scenario_id"].nunique()),
                "unique_price_count": int(vals.nunique()),
            }
        )
    return pd.DataFrame(rows)


def _metric_summary(q: pd.DataFrame, label: str) -> pd.DataFrame:
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
            zero_or_constant_price_period_rate=("unique_price_count", lambda s: float((pd.Series(s) <= 1).mean())),
            mean_scenario_count=("scenario_count", "mean"),
        )
        .reset_index()
    )
    out["quantile_mode"] = label
    return out


def _decomposition(q: pd.DataFrame, label: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    work["q10"] = work.groupby(["candidate_key", "dataset_split"], dropna=False)["y_true"].transform(lambda s: pd.to_numeric(s, errors="coerce").quantile(0.10))
    work["q90"] = work.groupby(["candidate_key", "dataset_split"], dropna=False)["y_true"].transform(lambda s: pd.to_numeric(s, errors="coerce").quantile(0.90))
    work["price_regime"] = np.select(
        [
            work["y_true"] < 0.0,
            work["y_true"] <= work["q10"],
            work["y_true"] >= work["q90"],
        ],
        ["negative", "low", "high"],
        default="mid",
    )
    agg_cols = {
        "coverage_p05_p95": ("inside", "mean"),
        "outside_spread_frequency": ("outside_spread", "mean"),
        "above_p95_share": ("high_tail_miss", "mean"),
        "below_p05_share": ("low_tail_miss", "mean"),
        "p50_bias": ("p50_bias", "mean"),
        "average_interval_width": ("width", "mean"),
    }
    by_month = work.groupby(["candidate_key", "dataset_split", "month"], dropna=False).agg(**agg_cols).reset_index()
    by_hour = work.groupby(["candidate_key", "dataset_split", "hour"], dropna=False).agg(**agg_cols).reset_index()
    by_regime = work.groupby(["candidate_key", "dataset_split", "price_regime"], dropna=False).agg(**agg_cols).reset_index()
    by_month["quantile_mode"] = label
    by_hour["quantile_mode"] = label
    by_regime["quantile_mode"] = label
    return by_month, by_hour, by_regime


def _old_vs_new_weighted_summary(new_weighted: pd.DataFrame) -> pd.DataFrame:
    old_path = OLD_RUN_DIR / "scenario_validation_summary.csv"
    if not old_path.exists():
        return pd.DataFrame()
    old = pd.read_csv(old_path, low_memory=False)
    if "selected_as_default_variant" in old.columns:
        selected = old[old["selected_as_default_variant"].fillna(False).astype(bool)].copy()
        if not selected.empty:
            old = selected
    old = old[
        ["candidate_key", "candidate_label", "dataset_split", "p05_p95_coverage", "high_tail_miss_rate", "low_tail_miss_rate", "average_p05_p95_width"]
    ].copy()
    old = old.rename(
        columns={
            "p05_p95_coverage": "coverage_old",
            "high_tail_miss_rate": "high_tail_miss_old",
            "low_tail_miss_rate": "low_tail_miss_old",
            "average_p05_p95_width": "width_old",
        }
    )
    new = new_weighted.rename(
        columns={
            "coverage_p05_p95": "coverage_new",
            "high_tail_miss_rate": "high_tail_miss_new",
            "low_tail_miss_rate": "low_tail_miss_new",
            "average_interval_width": "width_new",
        }
    )
    merged = old.merge(new, on=["candidate_key", "candidate_label", "dataset_split"], how="inner")
    merged["coverage_delta_new_minus_old"] = merged["coverage_new"] - merged["coverage_old"]
    merged["width_delta_new_minus_old"] = merged["width_new"] - merged["width_old"]
    return merged.sort_values(["candidate_key", "dataset_split"]).reset_index(drop=True)


def main() -> int:
    if not RUN_DIR.exists():
        raise FileNotFoundError(f"Run dir not found: {RUN_DIR}")
    out_root = Path("data/02_Forecasting/01_DA_prices/scenario_evaluation")
    run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_hourly_tail_diagnostics")
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    files_inspected = [
        str(RUN_DIR / name)
        for name in [
            "scenario_generation_config.json",
            "scenario_generation_run_summary.json",
            "scenario_prices_long.csv",
            "scenario_metadata.csv",
            "scenario_reduction_summary.csv",
            "scenario_period_quantiles.csv",
            "scenario_validation_summary.csv",
        ]
    ]

    raw_status = _raw_artifacts_exist(RUN_DIR)
    prices = pd.read_csv(RUN_DIR / "scenario_prices_long.csv", low_memory=False)
    metadata = pd.read_csv(RUN_DIR / "scenario_metadata.csv", low_memory=False)
    config = json.loads((RUN_DIR / "scenario_generation_config.json").read_text(encoding="utf-8"))
    summary = json.loads((RUN_DIR / "scenario_generation_run_summary.json").read_text(encoding="utf-8"))

    weighted_q = _period_quantiles(prices, weighted=True)
    unweighted_q = _period_quantiles(prices, weighted=False)

    weighted_summary = _metric_summary(weighted_q, label="weighted")
    unweighted_summary = _metric_summary(unweighted_q, label="unweighted")
    summary_compare = weighted_summary.merge(
        unweighted_summary,
        on=["candidate_key", "candidate_label", "dataset_split"],
        how="outer",
        suffixes=("_weighted", "_unweighted"),
    )
    for metric in [
        "coverage_p05_p95",
        "outside_spread_frequency",
        "p50_bias",
        "average_interval_width",
        "high_tail_miss_rate",
        "low_tail_miss_rate",
        "zero_or_constant_price_period_rate",
    ]:
        summary_compare[f"{metric}_delta_weighted_minus_unweighted"] = (
            pd.to_numeric(summary_compare.get(f"{metric}_weighted"), errors="coerce")
            - pd.to_numeric(summary_compare.get(f"{metric}_unweighted"), errors="coerce")
        )

    month_w, hour_w, regime_w = _decomposition(weighted_q, label="weighted")
    month_u, hour_u, regime_u = _decomposition(unweighted_q, label="unweighted")
    month_cmp = month_w.merge(month_u, on=["candidate_key", "dataset_split", "month"], suffixes=("_weighted", "_unweighted"), how="outer")
    hour_cmp = hour_w.merge(hour_u, on=["candidate_key", "dataset_split", "hour"], suffixes=("_weighted", "_unweighted"), how="outer")
    regime_cmp = regime_w.merge(regime_u, on=["candidate_key", "dataset_split", "price_regime"], suffixes=("_weighted", "_unweighted"), how="outer")

    old_vs_new = _old_vs_new_weighted_summary(weighted_summary)

    reduction = pd.read_csv(RUN_DIR / "scenario_reduction_summary.csv", low_memory=False)
    reduction_agg = (
        reduction.groupby(["candidate_key", "dataset_split"], dropna=False)
        .agg(
            raw_scenario_count=("raw_scenario_count", "mean"),
            reduced_scenario_count=("final_scenario_count", "mean"),
            protected_tail_count=("protected_tail_count", "mean"),
            protected_tail_probability_mass=("protected_tail_probability_mass", "mean"),
        )
        .reset_index()
    )
    probability_policy = str(summary.get("probability_policy") or config.get("probability_policy") or "missing")

    weighted_source = "run_scenario_period_quantiles_weighted" if (RUN_DIR / "scenario_period_quantiles.csv").exists() else "recomputed_weighted"
    notebook_quantile_mode = "unweighted"

    weighted_summary.to_csv(out_dir / "weighted_summary.csv", index=False)
    unweighted_summary.to_csv(out_dir / "unweighted_summary.csv", index=False)
    summary_compare.to_csv(out_dir / "weighted_vs_unweighted_summary.csv", index=False)
    month_cmp.to_csv(out_dir / "decomposition_by_month_weighted_vs_unweighted.csv", index=False)
    hour_cmp.to_csv(out_dir / "decomposition_by_hour_weighted_vs_unweighted.csv", index=False)
    regime_cmp.to_csv(out_dir / "decomposition_by_regime_weighted_vs_unweighted.csv", index=False)
    reduction_agg.to_csv(out_dir / "reduction_profile_summary.csv", index=False)
    old_vs_new.to_csv(out_dir / "old_vs_new_weighted_summary.csv", index=False)

    likely_causes: list[str] = []
    if not raw_status["found"]:
        likely_causes.append("raw_vs_reduced_not_directly_observable_raw_artifacts_missing")
    if not summary_compare.empty:
        large_weight_gap = bool((summary_compare["coverage_p05_p95_delta_weighted_minus_unweighted"].abs() > 0.01).any())
        if large_weight_gap:
            likely_causes.append("weighted_unweighted_quantile_mismatch_in_notebook_diagnostics")
        const_rate = pd.to_numeric(summary_compare["zero_or_constant_price_period_rate_weighted"], errors="coerce")
        if const_rate.notna().any() and float(const_rate.mean()) > 0.20:
            likely_causes.append("scenario_under_dispersion_many_periods_with_low_cross_scenario_diversity")
    if not old_vs_new.empty:
        if (old_vs_new["coverage_delta_new_minus_old"] < -0.02).any():
            likely_causes.append("new_run_coverage_loss_vs_old_is_material")
        if (old_vs_new["width_delta_new_minus_old"] < 0).any():
            likely_causes.append("narrower_intervals_for_some_models_contributing_to_undercoverage")
    if probability_policy == "empirical_cluster_mass":
        likely_causes.append("tail_protection_probability_mass_is_small_relative_to_tail_share")

    report_payload = {
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_run_dir": str(RUN_DIR),
        "files_inspected": files_inspected,
        "raw_artifacts": raw_status,
        "probability_policy": probability_policy,
        "notebook29_quantile_mode_detected": notebook_quantile_mode,
        "weighted_quantile_source": weighted_source,
        "likely_causes": likely_causes,
        "recommended_next_action": (
            "run targeted calibration sensitivity (reduced_scenarios/protected_tail_share/residual_scale) "
            "with weighted diagnostics as primary decision metric"
        ),
        "full_calibration_sensitivity_still_necessary": True,
    }
    (out_dir / "diagnostic_report.json").write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    md_lines = [
        "# Hourly D-Only Tail-Aware Diagnostics",
        "",
        f"- Input run: `{RUN_DIR}`",
        f"- Raw artifacts retained: `{raw_status['found']}`",
        f"- Probability policy: `{probability_policy}`",
        f"- Notebook 29 quantiles: `{notebook_quantile_mode}`",
        "",
        "## Key Findings",
    ]
    if likely_causes:
        md_lines.extend([f"- {item}" for item in likely_causes])
    else:
        md_lines.append("- no_single_dominant_cause_detected")
    md_lines.extend(
        [
            "",
            "## Outputs",
            f"- `weighted_summary.csv`",
            f"- `unweighted_summary.csv`",
            f"- `weighted_vs_unweighted_summary.csv`",
            f"- `decomposition_by_month_weighted_vs_unweighted.csv`",
            f"- `decomposition_by_hour_weighted_vs_unweighted.csv`",
            f"- `decomposition_by_regime_weighted_vs_unweighted.csv`",
            f"- `reduction_profile_summary.csv`",
            f"- `old_vs_new_weighted_summary.csv`",
            f"- `diagnostic_report.json`",
        ]
    )
    (out_dir / "diagnostic_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(json.dumps({"output_dir": str(out_dir), "raw_artifacts_found": raw_status["found"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
