from __future__ import annotations

from math import erf, sqrt
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


LOCAL_TZ = "Europe/Amsterdam"


def _point_block(group: pd.DataFrame) -> dict[str, float]:
    actual = group["actual_price"].astype(float).to_numpy()
    predicted = group["point_forecast"].astype(float).to_numpy()
    error = predicted - actual
    absolute = np.abs(error)
    daily: list[dict[str, float]] = []
    work = group.copy()
    work["delivery_day"] = work["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ).dt.date
    for _, day in work.groupby("delivery_day"):
        y = day["actual_price"].astype(float)
        p = day["point_forecast"].astype(float)
        count = min(6, len(day))
        bottom_y = set(y.nsmallest(count).index)
        bottom_p = set(p.nsmallest(count).index)
        top_y = set(y.nlargest(count).index)
        top_p = set(p.nlargest(count).index)
        tail_idx = top_y | bottom_y
        daily.append(
            {
                "spearman": float(y.corr(p, method="spearman")),
                "bottom6": len(bottom_y & bottom_p) / count,
                "top6": len(top_y & top_p) / count,
                "tail_mae": float((p.loc[list(tail_idx)] - y.loc[list(tail_idx)]).abs().mean()),
                "spread_error": float(abs((p.max() - p.min()) - (y.max() - y.min()))),
            }
        )
    daily_frame = pd.DataFrame(daily)
    return {
        "mae": float(absolute.mean()),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(error.mean()),
        "p90_absolute_error": float(np.quantile(absolute, 0.90)),
        "p95_absolute_error": float(np.quantile(absolute, 0.95)),
        "daily_spearman": float(daily_frame["spearman"].mean()),
        "top6_hit_rate": float(daily_frame["top6"].mean()),
        "bottom6_hit_rate": float(daily_frame["bottom6"].mean()),
        "tail_mae": float(daily_frame["tail_mae"].mean()),
        "high_low_spread_error": float(daily_frame["spread_error"].mean()),
        "origin_count": int(group["forecast_origin_utc"].nunique()),
        "timestamp_count": int(len(group)),
        "coverage_pct": 100.0,
    }


def _point_rows(frame: pd.DataFrame, model_id: str, naive_denominators: dict[tuple[str, str], float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    slices: list[tuple[str, str, str, pd.DataFrame]] = [("overall", "ALL", "0", frame)]
    local_month = frame["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m")
    for month in sorted(local_month.unique()):
        slices.append(("month", month, "0", frame.loc[local_month.eq(month)]))
    for reporting_level, month, lead_day, group in slices:
        metrics = _point_block(group)
        denom = naive_denominators.get((reporting_level, month), np.nan)
        metrics["rmae_vs_official_naive_previous_week"] = metrics["mae"] / denom if denom > 0 else np.nan
        rows.append(
            {
                "model_comparison_id": model_id,
                "reporting_level": reporting_level,
                "month": month,
                "lead_day": lead_day,
                **metrics,
            }
        )
    return rows


def _dm_hac(differences: np.ndarray, lag: int = 7) -> dict[str, float]:
    d = np.asarray(differences, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    centered = d - d.mean()
    variance = float(np.dot(centered, centered) / n)
    for k in range(1, min(lag, n - 1) + 1):
        covariance = float(np.dot(centered[k:], centered[:-k]) / n)
        variance += 2.0 * (1.0 - k / (lag + 1.0)) * covariance
    standard_error = sqrt(max(variance, 0.0) / n) if n else np.nan
    statistic = float(d.mean() / standard_error) if standard_error > 0 else np.nan
    p_value = float(2.0 * (1.0 - 0.5 * (1.0 + erf(abs(statistic) / sqrt(2.0))))) if np.isfinite(statistic) else np.nan
    return {"mean_loss_difference": float(d.mean()), "dm_hac_statistic": statistic, "p_value_two_sided": p_value, "days": n, "hac_lag_days": lag}


def build_hourly_donly_point_metrics(forecast_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    d_point = pd.read_parquet(forecast_root / "optimisation_inputs/hourly_donly_point_forecasts.parquet")
    d4_point = pd.read_parquet(forecast_root / "optimisation_inputs/hourly_point_forecasts.parquet")
    actual = pd.read_parquet(forecast_root / "evaluation_actuals.parquet")
    for frame in (d_point, d4_point, actual):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="raise")
    actual = actual.loc[actual["granularity"].eq("hourly") & actual["lead_day"].eq(0)]
    d4_point = d4_point.loc[d4_point["lead_day"].eq(0)]

    def scored(point: pd.DataFrame) -> pd.DataFrame:
        return point.merge(
            actual[["forecast_origin_utc", "target_timestamp_utc", "actual_price"]],
            on=["forecast_origin_utc", "target_timestamp_utc"],
            how="inner",
            validate="one_to_one",
        )

    d_scored, d4_scored = scored(d_point), scored(d4_point)
    if len(d_scored) != 116 * 24 or len(d4_scored) != len(d_scored):
        raise ValueError("H-D and H-D4 lead-D point forecasts do not have exact common support.")
    existing = pd.read_csv(forecast_root / "point_forecast_metrics.csv")
    reference = existing.loc[existing["model_comparison_id"].eq("hourly_lear_vs_aggregated_qh_truth")].copy()
    denominators: dict[tuple[str, str], float] = {}
    for row in reference.itertuples():
        if float(row.rmae_vs_official_naive_previous_week) > 0:
            denominators[(str(row.reporting_level), str(row.month))] = float(row.mae) / float(row.rmae_vs_official_naive_previous_week)
    rows = _point_rows(d_scored, "H-D_frozen_strict_lear_vs_hourly_truth", denominators)
    rows.extend(_point_rows(d4_scored, "H-D4_lead_D_vs_hourly_truth", denominators))

    joined = d_scored.rename(columns={"point_forecast": "H-D"}).merge(
        d4_scored[["forecast_origin_utc", "target_timestamp_utc", "point_forecast"]].rename(columns={"point_forecast": "H-D4"}),
        on=["forecast_origin_utc", "target_timestamp_utc"],
        validate="one_to_one",
    )
    joined["delivery_day"] = joined["target_timestamp_utc"].dt.tz_convert(LOCAL_TZ).dt.date
    daily = joined.groupby("delivery_day").apply(
        lambda group: pd.Series(
            {
                "H-D_absolute_error": (group["H-D"] - group["actual_price"]).abs().mean(),
                "H-D4_absolute_error": (group["H-D4"] - group["actual_price"]).abs().mean(),
            }
        ),
        include_groups=False,
    ).reset_index()
    daily["loss_difference_H-D_minus_H-D4"] = daily["H-D_absolute_error"] - daily["H-D4_absolute_error"]
    dm = pd.DataFrame([_dm_hac(daily["loss_difference_H-D_minus_H-D4"].to_numpy(), lag=7)])
    dm.insert(0, "comparison", "H-D_vs_H-D4_on_common_lead-D_days")
    return pd.DataFrame(rows), dm


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cumulative = np.cumsum(w) / np.sum(w)
    return float(np.interp(quantile, cumulative, v))


def _crps(values: np.ndarray, weights: np.ndarray, actual: float) -> float:
    first = float(np.sum(weights * np.abs(values - actual)))
    second = float(0.5 * np.sum(weights[:, None] * weights[None, :] * np.abs(values[:, None] - values[None, :])))
    return first - second


def build_hourly_donly_scenario_metrics(forecast_root: Path) -> pd.DataFrame:
    actual = pd.read_parquet(forecast_root / "evaluation_actuals.parquet")
    actual = actual.loc[actual["granularity"].eq("hourly") & actual["lead_day"].eq(0)].copy()
    actual["forecast_origin_utc"] = pd.to_datetime(actual["forecast_origin_utc"], utc=True)
    actual["target_timestamp_utc"] = pd.to_datetime(actual["target_timestamp_utc"], utc=True)
    rows: list[dict[str, Any]] = []
    canonical = pd.read_csv(forecast_root / "scenario_metrics_summary.csv")
    for set_size in (30, 10):
        scenarios = pd.read_parquet(forecast_root / f"optimisation_inputs/hourly_donly_scenarios_{set_size}.parquet")
        scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True)
        scenarios["target_timestamp_utc"] = pd.to_datetime(scenarios["target_timestamp_utc"], utc=True)
        merged = scenarios.merge(
            actual[["forecast_origin_utc", "target_timestamp_utc", "actual_price"]],
            on=["forecast_origin_utc", "target_timestamp_utc"],
            validate="many_to_one",
        )
        timestamp_rows: list[dict[str, float]] = []
        energy_scores: list[float] = []
        effective_sizes: list[float] = []
        for origin, origin_group in merged.groupby("forecast_origin_utc"):
            meta = origin_group[["scenario_id", "scenario_probability"]].drop_duplicates().sort_values("scenario_id")
            weights = meta["scenario_probability"].astype(float).to_numpy()
            weights = weights / weights.sum()
            effective_sizes.append(float(1.0 / np.sum(weights**2)))
            path = origin_group.pivot(index="scenario_id", columns="target_timestamp_utc", values="scenario_price").loc[meta["scenario_id"]]
            truth = origin_group[["target_timestamp_utc", "actual_price"]].drop_duplicates().set_index("target_timestamp_utc").loc[path.columns, "actual_price"].to_numpy()
            values = path.to_numpy(dtype=float)
            energy_first = float(np.sum(weights * np.linalg.norm(values - truth[None, :], axis=1)))
            pairwise = np.linalg.norm(values[:, None, :] - values[None, :, :], axis=2)
            energy_scores.append(energy_first - 0.5 * float(np.sum(weights[:, None] * weights[None, :] * pairwise)))
            for column_index in range(values.shape[1]):
                vector = values[:, column_index]
                y = float(truth[column_index])
                q10, q90 = _weighted_quantile(vector, weights, 0.10), _weighted_quantile(vector, weights, 0.90)
                q05, q95 = _weighted_quantile(vector, weights, 0.05), _weighted_quantile(vector, weights, 0.95)
                q50 = _weighted_quantile(vector, weights, 0.50)
                timestamp_rows.append(
                    {
                        "coverage_p10_p90": float(q10 <= y <= q90),
                        "coverage_p05_p95": float(q05 <= y <= q95),
                        "average_width_p10_p90": q90 - q10,
                        "average_width_p05_p95": q95 - q05,
                        "p50_bias": q50 - y,
                        "high_tail_miss_rate": float(y > q95),
                        "low_tail_miss_rate": float(y < q05),
                        "min_max_containment": float(vector.min() <= y <= vector.max()),
                        "crps": _crps(vector, weights, y),
                    }
                )
        timestamp = pd.DataFrame(timestamp_rows)
        scenario_set_label = "reduced_30" if set_size == 30 else "nested_10"
        inherited_tail = canonical.loc[
            canonical["granularity"].eq("hourly")
            & canonical["scenario_set"].eq(scenario_set_label)
            & pd.to_numeric(canonical["lead_day"], errors="coerce").eq(0),
            "protected_tail_weight",
        ]
        if len(inherited_tail) != 1:
            raise ValueError(f"Could not resolve inherited protected-tail weight for H-D set {set_size}.")
        rows.append(
            {
                "configuration": "H-D",
                "granularity": "hourly",
                "scenario_set_size": set_size,
                **{column: float(timestamp[column].mean()) for column in timestamp.columns},
                "energy_score": float(np.mean(energy_scores)),
                "effective_scenario_size": float(np.mean(effective_sizes)),
                "protected_tail_weight": float(inherited_tail.iloc[0]),
                "protected_tail_weight_lineage": "inherited_exactly_from_H-D4_lead_D_innovation_set",
                "origin_count": int(merged["forecast_origin_utc"].nunique()),
                "timestamp_count": int(merged[["forecast_origin_utc", "target_timestamp_utc"]].drop_duplicates().shape[0]),
            }
        )
    return pd.DataFrame(rows)


def create_thesis_figures(
    *, aggregate: pd.DataFrame, effects: pd.DataFrame, solver: pd.DataFrame, output_dir: Path
) -> list[Path]:
    import matplotlib.pyplot as plt

    repository_root = Path(__file__).resolve().parents[4]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    try:
        from visual_style import COLORS, METRIC_COLORS, STRATEGY_COLORS, apply_visual_style, save_figure
    except ImportError as exc:  # pragma: no cover - environment/path contract
        raise RuntimeError("Project visual_style.py must be importable before thesis figures are created.") from exc

    apply_visual_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    primary = aggregate.loc[
        aggregate["episode_id"].eq("primary")
        & aggregate["configuration"].isin(["H-D", "H-D4", "QH-D4"])
        & aggregate["policy"].isin(["price_insensitive", "stochastic_30", "true_pf"])
    ].copy()
    pivot = primary.pivot(index="configuration", columns="policy", values="realised_adjusted_profit_eur") / 1e6
    pivot = pivot.reindex(["H-D", "H-D4", "QH-D4"])
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    policies = ["price_insensitive", "stochastic_30", "true_pf"]
    colors = [STRATEGY_COLORS["price_insensitive"], STRATEGY_COLORS["risk_neutral"], STRATEGY_COLORS["perfect_foresight"]]
    width = 0.24
    x = np.arange(len(pivot.index))
    for offset, policy, color in zip((-width, 0.0, width), policies, colors):
        bars = ax.bar(x + offset, pivot[policy], width=width, label=policy.replace("_", " ").title(), color=color)
        ax.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    ax.set_xticks(x, pivot.index)
    ax.set_ylabel("Realised adjusted profit (EUR million)")
    ax.set_title("Forecast strategy value within configuration-matched bounds")
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.legend(handles, legend_labels, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.055))
    fig.subplots_adjust(bottom=0.24)
    fig.text(
        0.01,
        0.01,
        "Primary episode: 6 Apr-19 Jul 2026, 105 common-support days; 30 scenarios; realised D settlement. PF is an upper bound. Scenario undercoverage applies.",
        fontsize=8,
    )
    stem = output_dir / "headline_profit_vs_benchmarks"
    save_figure(fig, stem)
    plt.close(fig)
    outputs.extend([stem.with_suffix(".png"), stem.with_suffix(".pdf")])

    effect_plot = effects.loc[
        effects["policy"].eq("stochastic_30")
        & effects["block_length_days"].eq(7)
        & effects["effect"].isin(["horizon_value", "granularity_value"])
    ].copy()
    labels = {"horizon_value": "Horizon: H-D4 - H-D", "granularity_value": "Granularity: QH-D4 - H-D4"}
    effect_plot["label"] = effect_plot["effect"].map(labels)
    y = np.arange(len(effect_plot))
    means = effect_plot["mean_daily_effect_eur"].to_numpy()
    low = means - effect_plot["ci95_low_eur_per_day"].to_numpy()
    high = effect_plot["ci95_high_eur_per_day"].to_numpy() - means
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.errorbar(means, y, xerr=np.vstack([low, high]), fmt="o", capsize=4, color=COLORS["main_model"])
    ax.axvline(0.0, color=COLORS["benchmark"], linewidth=1)
    ax.set_yticks(y, effect_plot["label"])
    ax.set_xlabel("Mean paired daily profit difference (EUR/day), 95% MBB CI")
    ax.set_title("Incremental horizon and quarter-hour value")
    fig.subplots_adjust(bottom=0.24, left=0.25)
    fig.text(
        0.01,
        0.01,
        "Primary 105-day episode; stochastic 30; circular moving-block bootstrap, 10,000 draws, seven-day blocks; realised D settlement.",
        fontsize=8,
    )
    stem = output_dir / "paired_incremental_value_ci"
    save_figure(fig, stem)
    plt.close(fig)
    outputs.extend([stem.with_suffix(".png"), stem.with_suffix(".pdf")])

    runtime = solver.loc[
        solver["episode_id"].eq("primary")
        & solver["stage"].eq("bidding")
        & solver["configuration"].isin(["H-D", "H-D4", "QH-D4"])
        & solver["policy"].isin(["stochastic_30", "stochastic_10"])
    ].groupby(["configuration", "policy"], as_index=False)["runtime_seconds"].sum()
    runtime_pivot = runtime.pivot(index="configuration", columns="policy", values="runtime_seconds").reindex(["H-D", "H-D4", "QH-D4"])
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    x = np.arange(len(runtime_pivot.index))
    for offset, policy, color in ((-0.18, "stochastic_30", METRIC_COLORS["runtime"]), (0.18, "stochastic_10", COLORS["third_model"])):
        bars = ax.bar(x + offset, runtime_pivot[policy] / 60.0, width=0.36, label=policy.replace("stochastic_", "") + " scenarios", color=color)
        ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8)
    ax.set_xticks(x, runtime_pivot.index)
    ax.set_ylabel("Total bidding runtime (minutes)")
    ax.set_title("Computational effect of nested scenario reduction")
    ax.legend()
    fig.subplots_adjust(bottom=0.18)
    fig.text(
        0.01,
        0.01,
        "Primary episode: 105 common-support days; same physics, quota, bid ladder and risk-neutral objective. Solver plus model build/postprocessing.",
        fontsize=8,
    )
    stem = output_dir / "scenario_count_runtime"
    save_figure(fig, stem)
    plt.close(fig)
    outputs.extend([stem.with_suffix(".png"), stem.with_suffix(".pdf")])
    return outputs
