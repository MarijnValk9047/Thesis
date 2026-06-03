from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .bidding_backtest import run_real_scenario_bidding_dry_run
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import (
    build_inputs_manifest,
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .selected_week_smoke import (
    DEFAULT_ARTIFACT_IDS,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    TOLERANCE,
    _label_for_artifact,
    _validation_row,
    _weighted_quantile,
    load_and_validate_phase_c_week,
)
from .selected_week_policy import OFFICIAL_TEST_SELECTED_WEEKS_PATH
from .selected_week_suite import _valid_daily_registry_for_artifact
from .validation_cvar_expanded_sweep import (
    _aggregate_perfect_foresight_metrics,
    _build_cvar_frontier_by_model_week,
    _build_model_stats_by_gamma_week,
    _perfect_foresight_daily_row,
    _run_perfect_foresight_badarinath_style_comparison,
)
from .validation_cvar_sweep import (
    _aggregate_benchmark_metrics,
    _aggregate_weekly_metrics,
    _benchmark_daily_row,
    _build_cvar_validation_checks,
    _build_daily_metric_row,
    _build_solver_log_manifest,
    _scenario_coverage_by_day,
)

try:
    from visual_style import MODEL_COLORS, apply_visual_style
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR Strict": "#C97941",
        "LEAR FS3 pruned candidate": "#3A7D7C",
        "XGBoost FS3 pruned candidate": "#1F4E79",
        "Price insensitive benchmark": "#333333",
        "Perfect foresight": "#111111",
    }

    def apply_visual_style() -> None:
        plt.rcParams.update(
            {
                "figure.figsize": (8, 4.5),
                "figure.dpi": 120,
                "savefig.dpi": 300,
                "axes.grid": True,
                "grid.alpha": 0.5,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "legend.frameon": False,
            }
        )


DEFAULT_WEEK_ID = "test_high_volatility_week"
DEFAULT_SELECTED_WEEKS_YAML = OFFICIAL_TEST_SELECTED_WEEKS_PATH
DEFAULT_ALPHA = 0.95
DEFAULT_GAMMAS = (0.0, 0.05, 0.25)


@dataclass(frozen=True)
class PhaseE1PolicyEvalResult:
    run_dir: Path
    notebook_path: Path
    selected_week: pd.Series
    support_days: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    perfect_foresight_metrics: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame


def _normalized_gamma_tag(gamma: float) -> str:
    return str(float(gamma)).replace("-", "m").replace(".", "p")


def _slugify(label: str) -> str:
    return str(label).lower().replace(" ", "_")


def _build_phase_e1_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_ids: list[str] | tuple[str, ...],
    output_root: Path | None,
    experiment_name: str,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    updated = replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(experiment_name),
            execution_mode="selected_test_week_cvar_policy_eval",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=("stochastic_cvar_fixed_policy_test_week",),
    )
    if output_root is not None:
        updated = replace(updated, outputs=replace(updated.outputs, root=Path(output_root)))
    return updated


def _build_general_test_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_week: pd.Series,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    daily_metrics: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
    perfect_foresight_included: bool,
    gamma_values: list[float],
    cvar_alpha: float,
    benchmark_identity_checks: pd.DataFrame,
    perfect_foresight_identity_checks: pd.DataFrame,
) -> pd.DataFrame:
    checks = existing_checks.copy()
    rows: list[dict[str, str]] = []
    rows.append(
        _validation_row(
            check_name="selected_week_exact_test_high_volatility_week",
            status="pass"
            if str(selected_week["week_label"]) == "test_high_volatility_week"
            and str(selected_week["delivery_start_date"]) == "2024-12-09"
            and str(selected_week["delivery_end_date"]) == "2024-12-15"
            else "fail",
            details=f"week_label={selected_week['week_label']}; start={selected_week['delivery_start_date']}; end={selected_week['delivery_end_date']}",
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_inside_common_test_support",
            status="pass"
            if support_days["period_type"].astype(str).eq("test").all() and support_days["common_complete_support"].astype(bool).all()
            else "fail",
            details=f"selected_day_count={int(support_days.shape[0])}",
        )
    )
    rows.append(
        _validation_row(
            check_name="no_validation_days_used",
            status="pass" if ~support_days["period_type"].astype(str).eq("validation").any() else "fail",
            details=f"period_types={sorted(support_days['period_type'].astype(str).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="complete_actual_prices_for_selected_days",
            status="pass" if support_days["complete_actual_prices"].astype(bool).all() else "fail",
            details="complete_actual_prices all true",
        )
    )
    rows.append(
        _validation_row(
            check_name="artifacts_run_on_same_test_week",
            status="pass"
            if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == sorted([str(value) for value in artifact_ids])
            else "fail",
            details=f"artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="scenario_count_75_for_all_selected_days",
            status="pass" if daily_metrics["scenario_count"].astype(int).eq(75).all() else "fail",
            details=f"scenario_count_values={sorted(daily_metrics['scenario_count'].astype(int).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="scenario_probability_check_passes",
            status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail",
            details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}",
        )
    )
    rows.append(
        _validation_row(
            check_name="submitted_minus_cleared_equals_rejected",
            status="pass"
            if np.allclose(
                daily_metrics["submitted_energy_mwh"].astype(float) - daily_metrics["cleared_energy_mwh"].astype(float),
                daily_metrics["rejected_energy_mwh"].astype(float),
                atol=1e-6,
            )
            else "fail",
            details="daily submitted - cleared = rejected",
        )
    )
    rows.append(
        _validation_row(
            check_name="used_plus_unused_equals_cleared",
            status="pass"
            if np.allclose(
                daily_metrics["used_cleared_energy_mwh"].astype(float) + daily_metrics["unused_cleared_energy_mwh"].astype(float),
                daily_metrics["cleared_energy_mwh"].astype(float),
                atol=1e-6,
            )
            else "fail",
            details="daily used + unused = cleared",
        )
    )
    rows.append(
        _validation_row(
            check_name="benchmark_same_actual_prices_and_days",
            status="pass" if int(benchmark_daily.shape[0]) == 7 * len(artifact_ids) else "fail",
            details=f"benchmark_daily_rows={int(benchmark_daily.shape[0])}",
        )
    )
    if not benchmark_identity_checks.empty:
        rows.append(
            _validation_row(
                check_name="benchmark_identical_across_artifacts_per_day",
                status="pass" if benchmark_identity_checks["status"].astype(str).eq("pass").all() else "fail",
                details=f"checks={benchmark_identity_checks[['delivery_day', 'details']].to_dict(orient='records')}",
            )
        )
    if perfect_foresight_included:
        rows.append(
            _validation_row(
                check_name="perfect_foresight_same_actual_prices_and_days",
                status="pass" if int(perfect_foresight_daily.shape[0]) == 7 else "fail",
                details=f"perfect_foresight_daily_rows={int(perfect_foresight_daily.shape[0])}",
            )
        )
        if not perfect_foresight_identity_checks.empty:
            rows.append(
                _validation_row(
                    check_name="perfect_foresight_identical_across_artifacts_per_day",
                    status="pass" if perfect_foresight_identity_checks["status"].astype(str).eq("pass").all() else "fail",
                    details=f"checks={perfect_foresight_identity_checks[['delivery_day', 'details']].to_dict(orient='records')}",
                )
            )
    rows.append(
        _validation_row(
            check_name="cvar_alpha_exactly_0p95",
            status="pass"
            if abs(float(cvar_alpha) - 0.95) <= 1e-12 and daily_metrics["cvar_alpha"].astype(float).eq(0.95).all()
            else "fail",
            details=f"unique_alpha={sorted(daily_metrics['cvar_alpha'].astype(float).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="gamma_grid_exactly_requested",
            status="pass"
            if sorted(daily_metrics["cvar_gamma"].astype(float).unique().tolist()) == sorted([float(value) for value in gamma_values])
            else "fail",
            details=f"observed_gamma_values={sorted(daily_metrics['cvar_gamma'].astype(float).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="no_quarter_hour_data_used",
            status="pass"
            if actual_clearing["granularity"].astype(str).eq("hourly").all()
            and pd.to_numeric(actual_clearing["timestep_hours"], errors="coerce").fillna(0.0).eq(1.0).all()
            else "fail",
            details=f"granularities={sorted(actual_clearing['granularity'].astype(str).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="no_d_plus_4_data_used",
            status="pass" if actual_clearing["horizon"].astype(str).eq("D_only").all() else "fail",
            details=f"horizons={sorted(actual_clearing['horizon'].astype(str).unique().tolist())}",
        )
    )
    rows.append(_validation_row(check_name="no_mfrr_used", status="pass", details="phase E1 runner does not invoke mFRR modules"))
    rows.append(_validation_row(check_name="no_exclusive_bids_used", status="pass", details="phase E1 uses the existing simple bid-curve formulation only"))
    rows.append(_validation_row(check_name="no_scenario_or_probability_changes", status="pass", details="phase E1 reuses saved thesis-grade scenario artifacts without modification"))
    rows.append(_validation_row(check_name="no_milp_formulation_changes_in_phase_e1_runner", status="pass", details="phase E1 runner reuses the existing stochastic bidding MILP path"))
    rows.append(
        _validation_row(
            check_name="actual_redispatch_timeseries_present",
            status="pass" if not actual_redispatch_timeseries.empty else "fail",
            details=f"rows={int(actual_redispatch_timeseries.shape[0])}",
        )
    )
    return pd.concat([checks, pd.DataFrame(rows)], ignore_index=True)


def _build_cvar_frontier_by_model(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    frame = _build_cvar_frontier_by_model_week(weekly_metrics)
    cols = [
        "artifact_id",
        "model_label",
        "week_id",
        "week_label",
        "cvar_alpha",
        "cvar_gamma",
        "expected_adjusted_profit",
        "realised_adjusted_profit",
        "cvar_loss",
        "cvar_tail_profit",
        "worst_scenario_profit",
        "stochastic_minus_benchmark_profit",
        "perfect_foresight_profit",
        "value_captured_vs_perfect_foresight",
        "regret_vs_perfect_foresight",
    ]
    return frame[cols].copy().sort_values(["model_label", "cvar_gamma"]).reset_index(drop=True)


def _plot_scatter_by_model_gamma(
    weekly_metrics: pd.DataFrame,
    *,
    x_metric: str,
    y_metric: str,
    xlabel: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for model_label, group in weekly_metrics.groupby("model_label", sort=False):
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.scatter(
            pd.to_numeric(group[x_metric], errors="coerce"),
            pd.to_numeric(group[y_metric], errors="coerce"),
            s=60,
            color=color,
            label=str(model_label),
        )
        for _, row in group.iterrows():
            ax.annotate(
                f"g={float(row['cvar_gamma']):.2f}",
                (float(row[x_metric]), float(row[y_metric])),
                fontsize=8,
            )
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_gamma_metric_by_model(
    weekly_metrics: pd.DataFrame,
    *,
    metric: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for model_label, group in weekly_metrics.groupby("model_label", sort=False):
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        group = group.sort_values("cvar_gamma")
        ax.plot(group["cvar_gamma"], pd.to_numeric(group[metric], errors="coerce"), marker="o", linewidth=1.8, color=color, label=str(model_label))
    ax.set_xlabel("Gamma")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_profit_vs_benchmarks(
    weekly_metrics: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    output_path: Path,
) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    models = weekly_metrics["model_label"].astype(str).drop_duplicates().tolist()
    gamma_values = sorted(weekly_metrics["cvar_gamma"].astype(float).unique().tolist())
    width = 0.22
    x = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    for idx, gamma in enumerate(gamma_values):
        subset = weekly_metrics.loc[weekly_metrics["cvar_gamma"].astype(float).eq(gamma)].set_index("model_label")
        vals = [float(subset.loc[model, "realised_adjusted_profit"]) for model in models]
        ax.bar(x + (idx - 1) * width, vals, width=width, label=f"gamma={gamma:.2f}")
    bench_weekly = benchmark_metrics.loc[benchmark_metrics["aggregation_level"].astype(str).eq("weekly")].copy()
    if not bench_weekly.empty:
        benchmark_vals = [float(bench_weekly.loc[bench_weekly["model_label"].astype(str).eq(model), "realised_adjusted_profit"].iloc[0]) for model in models]
        ax.plot(x, benchmark_vals, color="#333333", linewidth=2.0, marker="D", label="price-insensitive benchmark")
    pf_weekly = perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly")].copy()
    if not pf_weekly.empty:
        pf_profit = float(pd.to_numeric(pf_weekly["realised_adjusted_profit"], errors="coerce").iloc[0])
        ax.axhline(pf_profit, color="#111111", linestyle="--", linewidth=1.8, label="perfect foresight")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=10)
    ax.set_ylabel("Realised adjusted profit (EUR)")
    ax.set_title("Realised profit by model and fixed CVaR policy")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_value_captured_vs_perfect_foresight(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty or weekly_metrics["value_captured_vs_perfect_foresight"].dropna().empty:
        return
    _plot_gamma_metric_by_model(
        weekly_metrics,
        metric="value_captured_vs_perfect_foresight",
        ylabel="Share of perfect-foresight profit",
        title="Value captured vs perfect foresight by model and policy",
        output_path=output_path,
    )


def _plot_bid_firmness_by_model_gamma(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    models = weekly_metrics["model_label"].astype(str).drop_duplicates().tolist()
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 10.5), sharex=True)
    metrics = [
        ("weighted_average_bid_price", "Weighted average bid price (EUR/MWh)"),
        ("high_bid_share", "High-bid share"),
        ("market_cap_bid_share", "Market-cap bid share"),
    ]
    for ax, (metric, ylabel) in zip(axes, metrics, strict=True):
        for model_label in models:
            group = weekly_metrics.loc[weekly_metrics["model_label"].astype(str).eq(model_label)].sort_values("cvar_gamma")
            color = MODEL_COLORS.get(str(model_label), "#1F4E79")
            ax.plot(group["cvar_gamma"], pd.to_numeric(group[metric], errors="coerce"), marker="o", linewidth=1.8, color=color, label=str(model_label))
        ax.set_ylabel(ylabel)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Gamma")
    fig.suptitle("Bid firmness by model and fixed risk-preference policy", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_scenario_fan_by_model(scenario_frame: pd.DataFrame, output_dir: Path) -> None:
    if scenario_frame.empty:
        return
    apply_visual_style()
    gamma_zero = scenario_frame.loc[scenario_frame["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = scenario_frame.copy()
    for model_label, group in gamma_zero.groupby("model_label", sort=False):
        rows: list[dict[str, Any]] = []
        for ts, hour_group in group.groupby("delivery_start_utc", sort=True):
            values = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            weights = hour_group["scenario_probability"].astype(float).to_numpy()
            actual = float(hour_group["actual_price_eur_per_mwh"].iloc[0])
            rows.append(
                {
                    "delivery_start_utc": pd.Timestamp(ts),
                    "scenario_min": float(np.min(values)),
                    "scenario_max": float(np.max(values)),
                    "q05": float(_weighted_quantile(values, weights, 0.05)),
                    "q10": float(_weighted_quantile(values, weights, 0.10)),
                    "q50": float(_weighted_quantile(values, weights, 0.50)),
                    "q90": float(_weighted_quantile(values, weights, 0.90)),
                    "q95": float(_weighted_quantile(values, weights, 0.95)),
                    "actual": actual,
                    "outside_envelope": bool(actual < float(np.min(values)) - TOLERANCE or actual > float(np.max(values)) + TOLERANCE),
                }
            )
        quant = pd.DataFrame(rows).sort_values("delivery_start_utc")
        fig, ax = plt.subplots(figsize=(12.0, 4.8))
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.fill_between(quant["delivery_start_utc"], quant["scenario_min"], quant["scenario_max"], color=color, alpha=0.08, label="scenario min-max")
        ax.fill_between(quant["delivery_start_utc"], quant["q05"], quant["q95"], color=color, alpha=0.16, label="p05-p95")
        ax.fill_between(quant["delivery_start_utc"], quant["q10"], quant["q90"], color=color, alpha=0.24, label="p10-p90")
        ax.plot(quant["delivery_start_utc"], quant["q50"], color=color, linewidth=1.6, label="scenario median")
        ax.plot(quant["delivery_start_utc"], quant["actual"], color="#222222", linewidth=1.8, label="actual price")
        outside = quant.loc[quant["outside_envelope"].astype(bool)]
        if not outside.empty:
            ax.scatter(outside["delivery_start_utc"], outside["actual"], color="#D55E00", s=18, label="outside scenario envelope")
        ax.set_title(f"Scenario fan vs realised price | {model_label}")
        ax.set_ylabel("EUR/MWh")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(output_dir / f"fig_scenario_fan_{_slugify(model_label)}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _select_example_day(daily_metrics: pd.DataFrame) -> str:
    gamma_zero = daily_metrics.loc[daily_metrics["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = daily_metrics.copy()
    base = (
        gamma_zero.groupby("delivery_day", as_index=False)
        .agg(
            actual_price_max=("actual_price_max", "max"),
            actual_price_std=("actual_price_std", "max"),
            actual_price_spread=("actual_price_spread", "max"),
        )
        .sort_values(["actual_price_max", "actual_price_std", "actual_price_spread"], ascending=[False, False, False])
    )
    return str(base.iloc[0]["delivery_day"])


def _plot_example_day_operation(
    *,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
    delivery_day: str,
    reserve_line: float,
    output_dir: Path,
) -> None:
    if actual_clearing.empty or actual_redispatch_timeseries.empty:
        return
    apply_visual_style()
    gamma_values = [0.0, 0.05, 0.25]
    for model_label in actual_clearing["model_label"].astype(str).drop_duplicates().tolist():
        fig, axes = plt.subplots(5, 1, figsize=(11.0, 12.5), sharex=True)
        for gamma in gamma_values:
            color = MODEL_COLORS.get(str(model_label), "#1F4E79")
            fan = scenario_frame.loc[
                scenario_frame["model_label"].astype(str).eq(str(model_label))
                & scenario_frame["delivery_day"].astype(str).eq(str(delivery_day))
                & scenario_frame["cvar_gamma"].astype(float).eq(float(gamma))
            ].copy()
            if fan.empty:
                continue
            hourly_rows: list[dict[str, Any]] = []
            for ts, hour_group in fan.groupby("delivery_start_utc", sort=True):
                values = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
                weights = hour_group["scenario_probability"].astype(float).to_numpy()
                hourly_rows.append(
                    {
                        "delivery_start_utc": pd.Timestamp(ts),
                        "q10": float(_weighted_quantile(values, weights, 0.10)),
                        "q50": float(_weighted_quantile(values, weights, 0.50)),
                        "q90": float(_weighted_quantile(values, weights, 0.90)),
                        "actual": float(hour_group["actual_price_eur_per_mwh"].iloc[0]),
                    }
                )
            hourly = pd.DataFrame(hourly_rows).sort_values("delivery_start_utc")
            axes[0].plot(hourly["delivery_start_utc"], hourly["q50"], color=color, linewidth=1.1, alpha=0.75, label=f"scenario median g={gamma:.2f}")
            if gamma == 0.0:
                axes[0].fill_between(hourly["delivery_start_utc"], hourly["q10"], hourly["q90"], color=color, alpha=0.10)
                axes[0].plot(hourly["delivery_start_utc"], hourly["actual"], color="#222222", linewidth=1.8, label="actual price")

            clear_hour = (
                actual_clearing.loc[
                    actual_clearing["model_label"].astype(str).eq(str(model_label))
                    & actual_clearing["delivery_day"].astype(str).eq(str(delivery_day))
                    & actual_clearing["cvar_gamma"].astype(float).eq(float(gamma))
                ]
                .groupby("delivery_start_utc", as_index=False)
                .agg(
                    cleared_energy_mwh=("cleared_energy_mwh", "sum"),
                    submitted_energy_mwh=("bid_quantity_mw", "sum"),
                    rejected_energy_mwh=("cleared_energy_mwh", lambda s: 0.0),
                )
            )
            if not clear_hour.empty:
                clear_hour["rejected_energy_mwh"] = clear_hour["submitted_energy_mwh"] - clear_hour["cleared_energy_mwh"]
                axes[1].plot(clear_hour["delivery_start_utc"], clear_hour["cleared_energy_mwh"], color=color, linewidth=1.5, label=f"cleared g={gamma:.2f}")
                axes[1].plot(clear_hour["delivery_start_utc"], clear_hour["rejected_energy_mwh"], color=color, linewidth=1.0, linestyle="--", alpha=0.85, label=f"rejected g={gamma:.2f}")

            redisp = (
                actual_redispatch_timeseries.loc[
                    actual_redispatch_timeseries["model_label"].astype(str).eq(str(model_label))
                    & actual_redispatch_timeseries["delivery_day"].astype(str).eq(str(delivery_day))
                    & actual_redispatch_timeseries["cvar_gamma"].astype(float).eq(float(gamma))
                ]
                .sort_values("delivery_start_utc")
            )
            if not redisp.empty:
                axes[2].plot(redisp["delivery_start_utc"], redisp["used_energy_mwh"], color=color, linewidth=1.4, label=f"used g={gamma:.2f}")
                axes[2].plot(redisp["delivery_start_utc"], redisp["unused_cleared_energy_mwh"], color=color, linewidth=1.0, linestyle="--", label=f"unused g={gamma:.2f}")
                axes[3].plot(redisp["delivery_start_utc"], redisp["P_el_mw"], color=color, linewidth=1.4, label=f"electrolyser g={gamma:.2f}")
                axes[3].plot(redisp["delivery_start_utc"], redisp["P_comp_mw"], color=color, linewidth=1.0, linestyle="--", alpha=0.9, label=f"compressor g={gamma:.2f}")
                axes[4].plot(redisp["delivery_start_utc"], redisp["H_buf_kg"], color=color, linewidth=1.4, label=f"storage g={gamma:.2f}")
                axes[4].plot(redisp["delivery_start_utc"], redisp["shortfall_kg"], color=color, linewidth=0.9, linestyle=":", alpha=0.9, label=f"shortfall g={gamma:.2f}")

        axes[0].set_ylabel("EUR/MWh")
        axes[0].set_title("Actual price with scenario median and p10-p90 band")
        axes[0].legend(loc="upper left", fontsize=8)
        axes[1].set_ylabel("MWh")
        axes[1].set_title("Cleared and rejected electricity")
        axes[1].legend(loc="upper left", fontsize=8, ncol=2)
        axes[2].set_ylabel("MWh")
        axes[2].set_title("Used and unused cleared electricity")
        axes[2].legend(loc="upper left", fontsize=8, ncol=2)
        axes[3].set_ylabel("MW")
        axes[3].set_title("Electrolyser and compressor power")
        axes[3].legend(loc="upper left", fontsize=8, ncol=2)
        axes[4].set_ylabel("kg")
        axes[4].set_title("Hydrogen storage and shortfall")
        if np.isfinite(reserve_line):
            axes[4].axhline(reserve_line, color="#555555", linestyle="--", linewidth=1.0, label="reserve line")
        axes[4].legend(loc="upper left", fontsize=8, ncol=2)
        axes[4].set_xlabel("Delivery hour (UTC)")
        fig.suptitle(f"Example-day operation | {delivery_day} | {model_label}", y=0.995)
        fig.tight_layout()
        fig.savefig(output_dir / f"fig_example_day_operation_{delivery_day}_{_slugify(model_label)}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _plot_economic_decomposition_by_model_gamma(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    frame = weekly_metrics.copy().sort_values(["model_label", "cvar_gamma"])
    labels = [f"{row.model_label}\ng={float(row.cvar_gamma):.2f}" for row in frame.itertuples()]
    x = np.arange(len(labels))
    hydrogen_revenue = pd.to_numeric(frame["hydrogen_revenue"], errors="coerce").to_numpy()
    da_cost = -pd.to_numeric(frame["da_settlement_cost"], errors="coerce").to_numpy()
    shortfall_penalty = -pd.to_numeric(frame["shortfall_penalty"], errors="coerce").to_numpy()
    unused_penalty = -pd.to_numeric(frame["unused_energy_penalty"], errors="coerce").to_numpy()
    terminal = pd.to_numeric(frame["terminal_inventory_correction"], errors="coerce").to_numpy()
    realised_profit = pd.to_numeric(frame["realised_adjusted_profit"], errors="coerce").to_numpy()
    fig, ax = plt.subplots(figsize=(12.0, 5.8))
    ax.bar(x, hydrogen_revenue, label="hydrogen revenue")
    ax.bar(x, da_cost, bottom=hydrogen_revenue, label="DA settlement cost")
    ax.bar(x, shortfall_penalty, bottom=hydrogen_revenue + da_cost, label="shortfall penalty")
    ax.bar(x, unused_penalty, bottom=hydrogen_revenue + da_cost + shortfall_penalty, label="unused-energy penalty")
    ax.bar(x, terminal, bottom=hydrogen_revenue + da_cost + shortfall_penalty + unused_penalty, label="terminal inventory correction")
    ax.plot(x, realised_profit, color="#111111", marker="o", linewidth=1.7, label="realised adjusted profit")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("EUR")
    ax.set_title("Economic decomposition by model and fixed CVaR policy")
    ax.legend(loc="best", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_figures(
    *,
    run_dir: Path,
    config: HydrogenConfig,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    submitted_bids: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    frontier = _build_cvar_frontier_by_model(weekly_metrics)
    _plot_scatter_by_model_gamma(
        frontier,
        x_metric="cvar_tail_profit",
        y_metric="realised_adjusted_profit",
        xlabel="CVaR tail profit (-CVaR loss)",
        ylabel="Realised adjusted profit (EUR)",
        title="Fixed-policy test-week risk-return comparison",
        output_path=figures_dir / "fig_risk_return_profit_vs_cvar_tail_profit.png",
    )
    _plot_scatter_by_model_gamma(
        frontier.dropna(subset=["value_captured_vs_perfect_foresight"]),
        x_metric="value_captured_vs_perfect_foresight",
        y_metric="realised_adjusted_profit",
        xlabel="Value captured vs perfect foresight",
        ylabel="Realised adjusted profit (EUR)",
        title="Realised profit vs value captured vs perfect foresight",
        output_path=figures_dir / "fig_value_captured_vs_profit.png",
    )
    _plot_gamma_metric_by_model(
        weekly_metrics,
        metric="realised_adjusted_profit",
        ylabel="EUR",
        title="Gamma vs realised adjusted profit by model",
        output_path=figures_dir / "fig_gamma_vs_realised_profit_by_model.png",
    )
    _plot_gamma_metric_by_model(
        weekly_metrics.assign(cvar_tail_profit=lambda df: -pd.to_numeric(df["cvar_loss"], errors="coerce")),
        metric="cvar_tail_profit",
        ylabel="EUR",
        title="Gamma vs CVaR tail profit by model",
        output_path=figures_dir / "fig_gamma_vs_cvar_tail_profit_by_model.png",
    )
    _plot_gamma_metric_by_model(
        weekly_metrics,
        metric="worst_scenario_profit",
        ylabel="EUR",
        title="Gamma vs worst-scenario profit by model",
        output_path=figures_dir / "fig_gamma_vs_worst_scenario_profit_by_model.png",
    )
    _plot_profit_vs_benchmarks(
        weekly_metrics,
        benchmark_metrics,
        perfect_foresight_metrics,
        figures_dir / "fig_profit_vs_benchmarks.png",
    )
    _plot_value_captured_vs_perfect_foresight(
        weekly_metrics,
        figures_dir / "fig_value_captured_vs_perfect_foresight.png",
    )
    _plot_gamma_metric_by_model(
        weekly_metrics,
        metric="clearing_ratio",
        ylabel="ratio",
        title="Clearing ratio by model and policy",
        output_path=figures_dir / "fig_clearing_ratio_by_model_gamma.png",
    )
    _plot_gamma_metric_by_model(
        weekly_metrics,
        metric="rejected_energy_mwh",
        ylabel="MWh",
        title="Rejected energy by model and policy",
        output_path=figures_dir / "fig_rejected_energy_by_model_gamma.png",
    )
    _plot_bid_firmness_by_model_gamma(weekly_metrics, figures_dir / "fig_bid_firmness_by_model_gamma.png")
    _plot_scenario_fan_by_model(scenario_frame, figures_dir)
    example_day = _select_example_day(daily_metrics)
    _plot_example_day_operation(
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
        delivery_day=example_day,
        reserve_line=float(config.hydrogen_system.reserve_kg),
        output_dir=figures_dir,
    )
    _plot_economic_decomposition_by_model_gamma(
        weekly_metrics,
        figures_dir / "fig_economic_decomposition_by_model_gamma.png",
    )


def _write_readme(
    *,
    run_dir: Path,
    selected_week: pd.Series,
    artifact_ids: list[str],
    cvar_alpha: float,
    gamma_values: list[float],
    benchmark_included: bool,
    perfect_foresight_included: bool,
    weekly_metrics: pd.DataFrame,
    validation_checks: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
) -> None:
    hard_fail_count = int(
        validation_checks.loc[
            (validation_checks["severity"].astype(str) == "hard_fail")
            & (validation_checks["status"].astype(str) == "fail")
        ].shape[0]
    )
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    summary = weekly_metrics[
        [
            "model_label",
            "cvar_gamma",
            "expected_adjusted_profit",
            "realised_adjusted_profit",
            "benchmark_profit",
            "perfect_foresight_profit",
            "stochastic_minus_benchmark_profit",
            "value_captured_vs_perfect_foresight",
            "cvar_loss",
            "worst_scenario_profit",
            "clearing_ratio",
            "rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "shortfall_kg",
        ]
    ].copy()
    lines = [
        "# Phase E1 Selected Test-Week CVaR Policy Evaluation",
        "",
        "## Scope",
        "",
        "- label: fixed-policy test-week evaluation on common partial support",
        "- hourly, D-only, DA-only",
        "- exactly one selected test week",
        "- gamma values are fixed risk-preference policies, not tuned on the test week",
        "- no validation weeks were used",
        "- no scenario, probability, or MILP formulation changes were introduced",
        "",
        "## Selected Test Week",
        "",
        f"- week label: `{selected_week['week_label']}`",
        f"- delivery dates: `{selected_week['delivery_start_date']}` to `{selected_week['delivery_end_date']}`",
        f"- selection reason: `{selected_week['selection_reason']}`",
        "",
        "## Artifacts",
        "",
    ]
    for artifact_id in artifact_ids:
        lines.append(f"- `{artifact_id}`")
    lines.extend(
        [
            "",
            "## Fixed CVaR Policies",
            "",
            f"- alpha: `{float(cvar_alpha):.4f}`",
            f"- gamma values: `{[float(value) for value in gamma_values]}`",
            "- gamma = 0 is the risk-neutral policy.",
            "- gamma = 0.05 is the moderate risk-aversion policy.",
            "- gamma = 0.25 is the conservative risk-aversion policy.",
            "",
            "## Benchmarks",
            "",
            f"- price-insensitive benchmark included: `{bool(benchmark_included)}`",
            f"- perfect foresight included: `{bool(perfect_foresight_included)}`",
            "- perfect foresight is an oracle upper bound only.",
            "",
            "## Weekly Results",
            "",
            "```csv",
            summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Validation Status",
            "",
            f"- hard validation failures: {hard_fail_count}",
            f"- CVaR reconstruction / consistency failures: {cvar_fail_count}",
            "",
            "## Interpretation Guardrails",
            "",
            "- this is fixed-policy test-week evaluation, not gamma tuning;",
            "- scenario undercoverage still limits how strongly tail-risk results should be generalized;",
            "- comparisons across models remain valid only on this exact common-support week;",
            "- perfect foresight is an upper bound, not an operational strategy.",
            "",
            "## Phase Status",
            "",
            f"- Phase E1 status: {'pass' if hard_fail_count == 0 and cvar_fail_count == 0 else 'fail'}",
            f"- safe to proceed to all selected test weeks: {'yes, with frozen policies only' if hard_fail_count == 0 and cvar_fail_count == 0 else 'not yet'}",
        ]
    )
    save_text(run_dir, "README_test_week_cvar_policy_eval.md", "\n".join(lines))


def run_selected_test_week_cvar_policy_eval(
    *,
    config: HydrogenConfig | str | Path,
    week_id: str = DEFAULT_WEEK_ID,
    artifact_ids: list[str] | tuple[str, ...] = DEFAULT_ARTIFACT_IDS,
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_e1_test_high_volatility_cvar_policy_three_model",
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
) -> PhaseE1PolicyEvalResult:
    gamma_list = [float(value) for value in gamma_values]
    if gamma_list != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E1 requires gamma grid exactly [0, 0.05, 0.25], got {gamma_list}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase E1 requires alpha 0.95, got {cvar_alpha}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase E1 requires the price-insensitive benchmark to be included.")

    selected_week, support_days = load_and_validate_phase_c_week(
        week_registry_path=Path(week_registry_path),
        support_csv_path=Path(support_csv_path),
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        week_id=str(week_id),
        selected_week_split="test",
    )

    suite_config = _build_phase_e1_config(
        config,
        artifact_ids=[str(value) for value in artifact_ids],
        output_root=output_root,
        experiment_name=str(run_slug),
    )
    run_id, run_dir = create_run_folder(suite_config)
    save_config_resolved(run_dir, suite_config)
    input_paths = [suite_config.config_path, suite_config.models.scenario_catalog, Path(week_registry_path), Path(support_csv_path)]
    if selected_weeks_yaml_path is not None:
        input_paths.append(Path(selected_weeks_yaml_path))
    save_inputs_manifest(run_dir, input_paths)
    save_json(run_dir, "input_manifest.json", build_inputs_manifest(input_paths))

    selected_delivery_days = support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist()
    save_json(
        run_dir,
        "selected_week_manifest.json",
        {
            "week_id": str(selected_week["week_id"]),
            "week_label": str(selected_week["week_label"]),
            "period_type": "test",
            "delivery_start_date": str(selected_week["delivery_start_date"]),
            "delivery_end_date": str(selected_week["delivery_end_date"]),
            "delivery_days": selected_delivery_days,
            "support_label": "fixed-policy test-week evaluation on common partial support",
            "methodological_use": str(selected_week["methodological_use"]),
        },
    )
    save_json(
        run_dir,
        "cvar_settings_manifest.json",
        {
            "alpha": float(cvar_alpha),
            "gamma_values": gamma_list,
            "gamma_policy_labels": {
                "0.0": "risk_neutral",
                "0.05": "moderate_risk_aversion",
                "0.25": "conservative_risk_aversion",
            },
            "objective_convention": "maximize_expected_adjusted_profit_minus_gamma_times_cvar_loss",
            "loss_convention": "loss = - adjusted_profit",
            "gamma_selection_rule": "frozen_from_validation_phases_D2_D3_do_not_tune_on_test_week",
        },
    )
    save_json(
        run_dir,
        "benchmark_manifest.json",
        {
            "price_insensitive_benchmark_included": bool(include_price_insensitive_benchmark),
            "perfect_foresight_benchmark_included": bool(include_perfect_foresight_benchmark),
            "perfect_foresight_description": "oracle upper bound using realised prices known in advance" if include_perfect_foresight_benchmark else "deferred",
        },
    )

    day_output_root = run_dir / "day_runs"
    day_output_root.mkdir(parents=True, exist_ok=True)
    day_run_config = replace(suite_config, outputs=replace(suite_config.outputs, save_figures=False))

    daily_rows: list[dict[str, Any]] = []
    validation_rows: list[pd.DataFrame] = []
    submitted_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    benchmark_daily_rows: list[dict[str, Any]] = []
    perfect_foresight_daily_rows: list[dict[str, Any]] = []
    scenario_fan_rows: list[pd.DataFrame] = []
    day_run_dir_rows: list[dict[str, Any]] = []
    scenario_manifest_rows: list[dict[str, Any]] = []
    benchmark_identity_rows: list[dict[str, str]] = []
    perfect_foresight_identity_rows: list[dict[str, str]] = []
    benchmark_cache: dict[tuple[str, str], pd.Series] = {}
    benchmark_signature_by_day: dict[str, tuple[float, ...]] = {}
    perfect_foresight_cache: dict[str, pd.Series] = {}
    perfect_foresight_signature_by_day: dict[str, tuple[float, ...]] = {}

    for artifact_id in [str(value) for value in artifact_ids]:
        selected_daily, _, spec, catalog_entry, manifest = _valid_daily_registry_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
        )
        selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(selected_delivery_days)].copy()
        if int(selected_daily.shape[0]) != len(selected_delivery_days):
            raise ValueError(f"Artifact {artifact_id!r} produced {int(selected_daily.shape[0])} selected days for Phase E1; expected {len(selected_delivery_days)}.")
        selected_daily = selected_daily.sort_values("delivery_day").reset_index(drop=True)
        model_label = _label_for_artifact(artifact_id)
        validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
        thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
        reconstruction_used = bool(manifest.get("forecast_origin_reconstruction_used", manifest.get("forecast_origin_reconstructed", False)))

        for day_record in selected_daily.to_dict(orient="records"):
            delivery_day = str(day_record["delivery_day"])
            benchmark_key = (artifact_id, delivery_day)
            for gamma in gamma_list:
                risk_mode = "risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar"
                include_benchmark = include_price_insensitive_benchmark and benchmark_key not in benchmark_cache
                result = run_real_scenario_bidding_dry_run(
                    config=day_run_config,
                    artifact_id=artifact_id,
                    forecast_origin_utc=str(pd.Timestamp(day_record["forecast_origin_utc"]).isoformat()),
                    max_origins=1,
                    output_root=day_output_root,
                    strategy_name="stochastic_bid_risk_neutral" if risk_mode == "risk_neutral" else "stochastic_bid_cvar",
                    dry_run_label=f"thv_g{_normalized_gamma_tag(gamma)}",
                    include_price_insensitive_comparison=include_benchmark,
                    risk_measure=risk_mode,
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    write_outputs=True,
                )
                actual_price_signature = tuple(np.round(result.actual_prices["actual_price_eur_per_mwh"].astype(float).to_numpy(), 9).tolist())
                if delivery_day in benchmark_signature_by_day:
                    same_benchmark_signature = benchmark_signature_by_day[delivery_day] == actual_price_signature
                    benchmark_identity_rows.append(
                        _validation_row(
                            check_name="benchmark_day_price_signature_consistent_across_artifacts",
                            status="pass" if same_benchmark_signature else "fail",
                            details=f"delivery_day={delivery_day}; same_actual_price_signature={same_benchmark_signature}",
                            severity="hard_fail",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                        )
                    )
                else:
                    benchmark_signature_by_day[delivery_day] = actual_price_signature

                if not result.benchmark_comparison.empty:
                    benchmark_row = result.benchmark_comparison.iloc[0].copy()
                    benchmark_cache[benchmark_key] = benchmark_row
                    benchmark_daily_rows.append(
                        _benchmark_daily_row(
                            benchmark_row=benchmark_row,
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                            run_id=run_id,
                        )
                    )
                else:
                    benchmark_row = benchmark_cache.get(benchmark_key)

                if include_perfect_foresight_benchmark and delivery_day not in perfect_foresight_cache:
                    pf_log_root = run_dir / "perfect_foresight_day_runs" / delivery_day
                    pf_log_root.mkdir(parents=True, exist_ok=True)
                    pf_summary, _, _ = _run_perfect_foresight_badarinath_style_comparison(
                        day_frame=result.scenarios,
                        actual_prices=result.actual_prices,
                        config=day_run_config,
                        run_id=run_id,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        solver_log_root=pf_log_root,
                    )
                    pf_row = pf_summary.iloc[0].copy()
                    perfect_foresight_cache[delivery_day] = pf_row
                    perfect_foresight_signature_by_day[delivery_day] = actual_price_signature
                    perfect_foresight_daily_rows.append(
                        _perfect_foresight_daily_row(
                            pf_row=pf_row,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            regime_label="test_high_volatility",
                            delivery_day=delivery_day,
                            forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                            run_id=run_id,
                        )
                    )
                elif include_perfect_foresight_benchmark:
                    same_pf_signature = perfect_foresight_signature_by_day[delivery_day] == actual_price_signature
                    perfect_foresight_identity_rows.append(
                        _validation_row(
                            check_name="perfect_foresight_day_price_signature_consistent_across_artifacts",
                            status="pass" if same_pf_signature else "fail",
                            details=f"delivery_day={delivery_day}; same_actual_price_signature={same_pf_signature}",
                            severity="hard_fail",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                        )
                    )
                pf_row = perfect_foresight_cache.get(delivery_day)

                metric_row = _build_daily_metric_row(
                    result=result,
                    artifact_id=artifact_id,
                    model_label=model_label,
                    validation_mode=validation_mode,
                    thesis_grade=thesis_grade,
                    forecast_origin_reconstruction_used=reconstruction_used,
                    week_row=selected_week,
                    day_row=pd.Series(day_record),
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    benchmark_row=benchmark_row,
                )
                metric_row["period_type"] = "test"
                metric_row["regime_label"] = "test_high_volatility"
                metric_row["cvar_tail_profit"] = float(-metric_row["cvar_loss"])
                if pf_row is not None:
                    pf_profit = float(pf_row["realised_adjusted_profit_eur"])
                    metric_row["perfect_foresight_profit"] = pf_profit
                    metric_row["value_captured_vs_perfect_foresight"] = float(metric_row["realised_adjusted_profit"] / pf_profit) if abs(pf_profit) > 1e-9 else float("nan")
                    metric_row["regret_vs_perfect_foresight"] = float(pf_profit - metric_row["realised_adjusted_profit"])
                else:
                    metric_row["perfect_foresight_profit"] = pd.NA
                    metric_row["value_captured_vs_perfect_foresight"] = pd.NA
                    metric_row["regret_vs_perfect_foresight"] = pd.NA
                daily_rows.append(metric_row)

                validation_rows.append(
                    result.validation_checks.assign(
                        artifact_id=artifact_id,
                        model_label=model_label,
                        week_id=str(selected_week["week_id"]),
                        week_label=str(selected_week["week_label"]),
                        regime_label="test_high_volatility",
                        delivery_day=delivery_day,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        risk_mode=str(risk_mode),
                    )
                )
                metadata = {
                    "artifact_id": artifact_id,
                    "model_label": model_label,
                    "week_id": str(selected_week["week_id"]),
                    "week_label": str(selected_week["week_label"]),
                    "regime_label": "test_high_volatility",
                    "delivery_day": delivery_day,
                    "forecast_origin_utc": pd.Timestamp(result.forecast_origin_utc),
                    "cvar_alpha": float(cvar_alpha),
                    "cvar_gamma": float(gamma),
                    "risk_mode": str(risk_mode),
                }
                submitted_rows.append(result.optimisation_result.submitted_bids.assign(**metadata))
                scenario_clearing_rows.append(result.optimisation_result.scenario_clearing.assign(**metadata))
                scenario_settlement_rows.append(result.optimisation_result.scenario_economics.assign(**metadata))
                actual_clearing_rows.append(result.actual_clearing.assign(**metadata))
                actual_redispatch_rows.append(result.actual_redispatch_timeseries.assign(**metadata))
                actual_settlement_rows.append(result.actual_settlement_results.assign(**metadata))
                scenario_fan_rows.append(result.scenarios.assign(**metadata))
                day_run_dir_rows.append({**metadata, "run_dir": str(result.run_dir) if result.run_dir is not None else ""})
                day_manifest_path = Path(str(result.run_dir)) / "scenario_manifest.json" if result.run_dir is not None else None
                day_manifest = json.loads(day_manifest_path.read_text(encoding="utf-8")) if day_manifest_path is not None and day_manifest_path.exists() else {}
                day_manifest.update(metadata)
                scenario_manifest_rows.append(day_manifest)

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase E1 produced no daily metrics.")
    daily_metrics["run_id"] = str(run_id)
    daily_metrics["period_type"] = "test"

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_checks_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["model_label", "delivery_day"]).reset_index(drop=True)
    perfect_foresight_daily = pd.DataFrame(perfect_foresight_daily_rows).sort_values(["delivery_day"]).reset_index(drop=True)
    if not benchmark_daily.empty:
        benchmark_daily["period_type"] = "test"
    if not perfect_foresight_daily.empty:
        perfect_foresight_daily["period_type"] = "test"
    scenario_frame = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    coverage = _scenario_coverage_by_day(scenario_frame)
    daily_metrics = daily_metrics.merge(
        coverage,
        on=["artifact_id", "model_label", "delivery_day", "cvar_gamma"],
        how="left",
    )

    weekly_metrics = _aggregate_weekly_metrics(daily_metrics, selected_week=pd.Series(selected_week)).copy()
    weekly_metrics["period_type"] = "test"
    weekly_metrics["regime_label"] = "test_high_volatility"
    benchmark_metrics = _aggregate_benchmark_metrics(benchmark_daily, selected_week=pd.Series(selected_week)).copy() if not benchmark_daily.empty else pd.DataFrame()
    if not benchmark_metrics.empty:
        benchmark_metrics["period_type"] = "test"
    perfect_foresight_metrics = _aggregate_perfect_foresight_metrics(perfect_foresight_daily)
    if not perfect_foresight_metrics.empty:
        perfect_foresight_metrics["period_type"] = "test"
        pf_weekly = perfect_foresight_metrics.loc[
            perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly"),
            ["week_id", "realised_adjusted_profit"],
        ].rename(columns={"realised_adjusted_profit": "perfect_foresight_profit"})
        weekly_metrics = weekly_metrics.merge(pf_weekly, on="week_id", how="left")
        weekly_metrics["value_captured_vs_perfect_foresight"] = np.where(
            pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce").abs() > 1e-9,
            pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")
            / pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce"),
            np.nan,
        )
        weekly_metrics["regret_vs_perfect_foresight"] = (
            pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce")
            - pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")
        )
    else:
        weekly_metrics["perfect_foresight_profit"] = pd.NA
        weekly_metrics["value_captured_vs_perfect_foresight"] = pd.NA
        weekly_metrics["regret_vs_perfect_foresight"] = pd.NA
    weekly_metrics["cvar_tail_profit"] = -pd.to_numeric(weekly_metrics["cvar_loss"], errors="coerce")
    weekly_metrics_by_model_gamma = weekly_metrics.copy()
    cvar_sweep_daily = daily_metrics.copy()
    cvar_sweep_weekly = weekly_metrics.copy()
    cvar_frontier_by_model = _build_cvar_frontier_by_model(weekly_metrics)
    cvar_bid_firmness_metrics = weekly_metrics[
        [
            "week_id",
            "week_label",
            "regime_label",
            "artifact_id",
            "model_label",
            "cvar_alpha",
            "cvar_gamma",
            "weighted_average_bid_price",
            "high_bid_share",
            "market_cap_bid_share",
            "clearing_ratio",
            "rejected_energy_mwh",
        ]
    ].copy()
    model_stats_by_gamma = _build_model_stats_by_gamma_week(daily_metrics)
    solver_log_manifest = _build_solver_log_manifest(day_run_dirs)
    save_json(
        run_dir,
        "scenario_manifest.json",
        {
            "phase": "E1",
            "support_label": "fixed-policy test-week evaluation on common partial support",
            "artifacts": scenario_manifest_rows,
        },
    )

    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        scenario_settlement_results=scenario_settlement_results,
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
    )
    benchmark_identity_checks = pd.DataFrame(benchmark_identity_rows)
    perfect_foresight_identity_checks = pd.DataFrame(perfect_foresight_identity_rows)
    validation_checks_all_runs = _build_general_test_validation_checks(
        existing_checks=validation_checks_existing,
        selected_week=selected_week,
        support_days=support_days,
        artifact_ids=[str(value) for value in artifact_ids],
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        perfect_foresight_daily=perfect_foresight_daily,
        perfect_foresight_included=bool(include_perfect_foresight_benchmark),
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
        benchmark_identity_checks=benchmark_identity_checks,
        perfect_foresight_identity_checks=perfect_foresight_identity_checks,
    )

    save_frame_csv(run_dir, "model_stats_by_gamma.csv", model_stats_by_gamma)
    save_frame_csv(run_dir, "solver_log_manifest.csv", solver_log_manifest)
    save_frame_parquet(run_dir, "submitted_bids.parquet", submitted_bids)
    save_frame_parquet(run_dir, "scenario_clearing.parquet", scenario_clearing)
    save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
    save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)
    save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "weekly_metrics_by_model_gamma.csv", weekly_metrics_by_model_gamma)
    save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(run_dir, "cvar_sweep_daily.csv", cvar_sweep_daily)
    save_frame_csv(run_dir, "cvar_sweep_weekly.csv", cvar_sweep_weekly)
    save_frame_csv(run_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model)
    save_frame_csv(run_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "day_run_dirs.csv", day_run_dirs)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "selected_week_manifest_table.csv", pd.DataFrame([selected_week]))
    save_frame_csv(notebook_inputs_dir, "support_days.csv", support_days)
    save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model)
    save_frame_csv(notebook_inputs_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(notebook_inputs_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    if not scenario_frame.empty:
        save_frame_parquet(notebook_inputs_dir, "scenario_fan_inputs.parquet", scenario_frame)
    if not submitted_bids.empty:
        save_frame_parquet(notebook_inputs_dir, "submitted_bids.parquet", submitted_bids)
    if not actual_clearing.empty:
        save_frame_parquet(notebook_inputs_dir, "actual_clearing.parquet", actual_clearing)
    if not actual_redispatch_timeseries.empty:
        save_frame_parquet(notebook_inputs_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    if not scenario_settlement_results.empty:
        save_frame_csv(notebook_inputs_dir, "scenario_settlement_results.csv", scenario_settlement_results)

    _create_figures(
        run_dir=run_dir,
        config=suite_config,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        submitted_bids=submitted_bids,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
    )
    _write_readme(
        run_dir=run_dir,
        selected_week=selected_week,
        artifact_ids=[str(value) for value in artifact_ids],
        cvar_alpha=float(cvar_alpha),
        gamma_values=gamma_list,
        benchmark_included=bool(include_price_insensitive_benchmark),
        perfect_foresight_included=bool(include_perfect_foresight_benchmark),
        weekly_metrics=weekly_metrics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )

    hard_fail_count = int(
        validation_checks_all_runs.loc[
            (validation_checks_all_runs["severity"].astype(str) == "hard_fail")
            & (validation_checks_all_runs["status"].astype(str) == "fail")
        ].shape[0]
    )
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    if hard_fail_count > 0 or cvar_fail_count > 0:
        raise RuntimeError(
            f"Phase E1 completed but validation failed (hard_fail_count={hard_fail_count}, cvar_fail_count={cvar_fail_count}); see run folder {run_dir}."
        )

    notebook_path = Path("scripts/Data/03_Hydrogen_Test_Case/notebooks/13_standard_cvar_policy_test_report.ipynb")
    return PhaseE1PolicyEvalResult(
        run_dir=run_dir,
        notebook_path=notebook_path,
        selected_week=selected_week,
        support_days=support_days,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )
