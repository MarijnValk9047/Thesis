from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .bidding_backtest import run_real_scenario_bidding_dry_run
from .plant_parameters import HydrogenConfig
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .selected_week_smoke import (
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    _label_for_artifact,
    _validation_row,
)
from .selected_week_suite import _valid_daily_registry_for_artifact
from .validation_cvar_expanded_sweep import (
    DEFAULT_WEEK_IDS,
    _aggregate_perfect_foresight_metrics,
    _build_general_validation_checks,
    _load_and_validate_phase_d2_weeks,
    _perfect_foresight_daily_row,
    _run_perfect_foresight_badarinath_style_comparison,
)
from .selected_week_policy import run_selected_week_input_preflight
from .validation_cvar_sweep import (
    _aggregate_benchmark_metrics,
    _aggregate_weekly_metrics,
    _benchmark_daily_row,
    _build_cvar_validation_checks,
    _build_daily_metric_row,
    _build_phase_d_config,
    _build_solver_log_manifest,
    _scenario_coverage_by_day,
)

try:
    from visual_style import MODEL_COLORS, apply_visual_style
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR FS3 pruned candidate": "#3A7D7C",
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


DEFAULT_ALPHA = 0.95
DEFAULT_FINE_GAMMAS = (0.0, 0.001, 0.0025, 0.005, 0.01, 0.015, 0.02, 0.025, 0.05)
DEFAULT_ARTIFACT_ID = "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate"
BID_IDENTITY_TOLERANCE_MW = 1e-9
TAIL_TOLERANCE_EUR = 1e-9


@dataclass(frozen=True)
class PhaseD3FineGammaResult:
    run_dir: Path
    notebook_path: Path
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    fine_gamma_aggregated: pd.DataFrame
    bid_difference_by_gamma: pd.DataFrame
    tail_scenario_diagnostics: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame


def _normalized_gamma_tag(gamma: float) -> str:
    return str(float(gamma)).replace("-", "m").replace(".", "p")


def _slugify_model_label(label: str) -> str:
    return str(label).lower().replace(" ", "_")


def _base_group_keys() -> list[str]:
    return ["artifact_id", "model_label", "week_id", "week_label", "regime_label", "delivery_day", "forecast_origin_utc"]


def _merge_on_gamma_keys() -> list[str]:
    return _base_group_keys() + ["cvar_alpha", "cvar_gamma"]


def _build_suite_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_weeks: pd.DataFrame,
    support_days: pd.DataFrame,
    artifact_id: str,
    daily_metrics: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
    perfect_foresight_included: bool,
    gamma_values: list[float],
    cvar_alpha: float,
    scenario_settlement_results: pd.DataFrame,
) -> pd.DataFrame:
    checks = existing_checks.copy()
    rows: list[dict[str, Any]] = []
    observed_artifacts = sorted(daily_metrics["artifact_id"].astype(str).unique().tolist())
    rows.append(
        _validation_row(
            check_name="selected_weeks_exact_validation_cvar_set",
            status="pass" if selected_weeks["regime_label"].astype(str).tolist() == list(DEFAULT_WEEK_IDS) else "fail",
            details=f"regime_labels={selected_weeks['regime_label'].astype(str).tolist()}",
        )
    )
    rows.append(
        _validation_row(
            check_name="only_lear_fs3_artifact_run",
            status="pass" if observed_artifacts == [str(artifact_id)] else "fail",
            details=f"observed_artifacts={observed_artifacts}",
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_inside_common_validation_support",
            status="pass" if support_days["period_type"].astype(str).eq("validation").all() and support_days["common_complete_support"].astype(bool).all() else "fail",
            details=f"selected_day_count={int(support_days.shape[0])}",
        )
    )
    rows.append(
        _validation_row(
            check_name="no_selected_test_days_used",
            status="pass" if ~support_days["period_type"].astype(str).eq("test").any() else "fail",
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
            check_name="scenario_probability_values_unchanged_across_gamma",
            status="pass"
            if scenario_settlement_results.groupby(["delivery_day", "forecast_origin_utc", "scenario_id"])["scenario_probability"].nunique().max() == 1
            else "fail",
            details="per day/scenario probability unique count across gamma",
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
            status="pass" if int(benchmark_daily.shape[0]) == 21 else "fail",
            details=f"benchmark_daily_rows={int(benchmark_daily.shape[0])}",
        )
    )
    if perfect_foresight_included:
        rows.append(
            _validation_row(
                check_name="perfect_foresight_same_actual_prices_and_days",
                status="pass" if int(perfect_foresight_daily.shape[0]) == 21 else "fail",
                details=f"perfect_foresight_daily_rows={int(perfect_foresight_daily.shape[0])}",
            )
        )
    rows.append(
        _validation_row(
            check_name="cvar_alpha_exactly_0p95",
            status="pass" if abs(float(cvar_alpha) - 0.95) <= 1e-12 and daily_metrics["cvar_alpha"].astype(float).eq(0.95).all() else "fail",
            details=f"unique_alpha={sorted(daily_metrics['cvar_alpha'].astype(float).unique().tolist())}",
        )
    )
    rows.append(
        _validation_row(
            check_name="gamma_grid_exactly_requested",
            status="pass" if sorted(daily_metrics["cvar_gamma"].astype(float).unique().tolist()) == sorted([float(v) for v in gamma_values]) else "fail",
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
    rows.append(_validation_row(check_name="no_mfrr_used", status="pass", details="phase D3 runner does not invoke mFRR modules"))
    rows.append(
        _validation_row(
            check_name="actual_redispatch_timeseries_present",
            status="pass" if not actual_redispatch_timeseries.empty else "fail",
            details=f"rows={int(actual_redispatch_timeseries.shape[0])}",
        )
    )
    appended = pd.DataFrame(rows)
    return pd.concat([checks, appended], ignore_index=True)


def _scenario_quantile(series: pd.Series, quantile: float) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    return float(values.quantile(quantile))


def _compute_bid_difference_by_gamma(
    submitted_bids: pd.DataFrame,
    *,
    gamma_values: list[float],
    timestep_hours: float,
) -> pd.DataFrame:
    if submitted_bids.empty:
        return pd.DataFrame()
    frame = submitted_bids.copy()
    frame["cvar_gamma"] = pd.to_numeric(frame["cvar_gamma"], errors="coerce")
    gamma_order = [float(value) for value in gamma_values]
    prev_gamma_map: dict[float, float | None] = {gamma_order[idx]: (gamma_order[idx - 1] if idx > 0 else None) for idx in range(len(gamma_order))}
    index_cols = ["delivery_start_utc", "bid_block", "bid_price_eur_per_mwh"]
    rows: list[dict[str, Any]] = []
    grouping_cols = _base_group_keys() + ["cvar_alpha"]
    for key_values, group in frame.groupby(grouping_cols, sort=False):
        key_dict = dict(zip(grouping_cols, key_values, strict=True))
        gamma_groups = {
            float(gamma): gamma_frame.set_index(index_cols)["bid_quantity_mw"].astype(float).sort_index()
            for gamma, gamma_frame in group.groupby("cvar_gamma", sort=False)
        }
        gamma_zero = gamma_groups[0.0]
        for gamma in gamma_order:
            current = gamma_groups[gamma]
            merged_vs_zero = pd.concat(
                [
                    gamma_zero.rename("gamma0"),
                    current.rename("current"),
                ],
                axis=1,
            ).fillna(0.0)
            diff_vs_zero = merged_vs_zero["current"] - merged_vs_zero["gamma0"]
            prev_gamma = prev_gamma_map[gamma]
            if prev_gamma is None:
                diff_vs_prev = diff_vs_zero.copy()
                prev_series = gamma_zero
            else:
                prev_series = gamma_groups[prev_gamma]
                merged_vs_prev = pd.concat(
                    [
                        prev_series.rename("previous"),
                        current.rename("current"),
                    ],
                    axis=1,
                ).fillna(0.0)
                diff_vs_prev = merged_vs_prev["current"] - merged_vs_prev["previous"]
            rows.append(
                {
                    **key_dict,
                    "cvar_gamma": float(gamma),
                    "max_abs_bid_quantity_difference_mw_vs_gamma0": float(diff_vs_zero.abs().max()),
                    "total_abs_bid_quantity_difference_mwh_vs_gamma0": float(diff_vs_zero.abs().sum() * float(timestep_hours)),
                    "max_abs_bid_quantity_difference_mw_vs_previous_gamma": float(diff_vs_prev.abs().max()),
                    "total_abs_bid_quantity_difference_mwh_vs_previous_gamma": float(diff_vs_prev.abs().sum() * float(timestep_hours)),
                    "identical_to_gamma0_within_tolerance": bool(diff_vs_zero.abs().max() <= BID_IDENTITY_TOLERANCE_MW),
                    "identical_to_previous_gamma_within_tolerance": bool(diff_vs_prev.abs().max() <= BID_IDENTITY_TOLERANCE_MW),
                    "previous_gamma": pd.NA if prev_gamma is None else float(prev_gamma),
                }
            )
    return pd.DataFrame(rows).sort_values(["week_label", "delivery_day", "cvar_gamma"]).reset_index(drop=True)


def _compute_tail_scenario_diagnostics(
    scenario_settlement_results: pd.DataFrame,
    *,
    gamma_values: list[float],
) -> pd.DataFrame:
    if scenario_settlement_results.empty:
        return pd.DataFrame()
    frame = scenario_settlement_results.copy()
    frame["cvar_gamma"] = pd.to_numeric(frame["cvar_gamma"], errors="coerce")
    gamma_order = [float(value) for value in gamma_values]
    prev_gamma_map: dict[float, float | None] = {gamma_order[idx]: (gamma_order[idx - 1] if idx > 0 else None) for idx in range(len(gamma_order))}
    rows: list[dict[str, Any]] = []
    records_by_key: dict[tuple[str, str, str, float], dict[str, Any]] = {}
    group_cols = _base_group_keys() + ["cvar_alpha", "cvar_gamma"]
    for group_key, group in frame.groupby(group_cols, sort=False):
        key_dict = dict(zip(group_cols, group_key, strict=True))
        profits = pd.to_numeric(group["adjusted_profit_eur"], errors="coerce")
        worst_profit = float(profits.min())
        worst_mask = profits <= worst_profit + TAIL_TOLERANCE_EUR
        worst_scenarios = sorted(group.loc[worst_mask, "scenario_id"].astype(str).unique().tolist())
        worst_prob_mass = float(pd.to_numeric(group.loc[worst_mask, "scenario_probability"], errors="coerce").sum())
        tail_mask = pd.to_numeric(group["loss_minus_zeta_eur"], errors="coerce") >= -TAIL_TOLERANCE_EUR
        tail_ids = sorted(group.loc[tail_mask, "scenario_id"].astype(str).unique().tolist())
        tail_prob_mass = float(pd.to_numeric(group.loc[tail_mask, "scenario_probability"], errors="coerce").sum())
        record = {
            **key_dict,
            "number_of_unique_scenario_profits": int(np.unique(np.round(profits.to_numpy(), 6)).size),
            "tail_diag_worst_scenario_profit": worst_profit,
            "worst_scenario_probability_mass": worst_prob_mass,
            "cvar_tail_probability_mass": tail_prob_mass,
            "number_of_tail_scenarios": int(len(tail_ids)),
            "tail_scenario_ids": "|".join(tail_ids),
            "worst_scenario_ids": "|".join(worst_scenarios),
        }
        rows.append(record)
        records_by_key[
            (
                str(key_dict["week_id"]),
                str(key_dict["delivery_day"]),
                str(key_dict["forecast_origin_utc"]),
                float(key_dict["cvar_alpha"]),
                float(key_dict["cvar_gamma"]),
            )
        ] = record

    diagnostics = pd.DataFrame(rows).sort_values(["week_label", "delivery_day", "cvar_gamma"]).reset_index(drop=True)
    previous_changes: list[bool] = []
    previous_worst_changes: list[bool] = []
    previous_gamma_values: list[float | pd._libs.missing.NAType] = []
    for row in diagnostics.to_dict(orient="records"):
        current_gamma = float(row["cvar_gamma"])
        previous_gamma = prev_gamma_map[current_gamma]
        previous_gamma_values.append(pd.NA if previous_gamma is None else float(previous_gamma))
        if previous_gamma is None:
            previous_changes.append(False)
            previous_worst_changes.append(False)
            continue
        previous_record = records_by_key[
            (
                str(row["week_id"]),
                str(row["delivery_day"]),
                str(row["forecast_origin_utc"]),
                float(row["cvar_alpha"]),
                float(previous_gamma),
            )
        ]
        previous_changes.append(str(previous_record["tail_scenario_ids"]) != str(row["tail_scenario_ids"]))
        previous_worst_changes.append(str(previous_record["worst_scenario_ids"]) != str(row["worst_scenario_ids"]))
    diagnostics["previous_gamma"] = previous_gamma_values
    diagnostics["whether_tail_scenarios_change_vs_previous_gamma"] = previous_changes
    diagnostics["whether_worst_scenario_changes_vs_previous_gamma"] = previous_worst_changes
    return diagnostics


def _build_fine_gamma_weekly(
    weekly_metrics: pd.DataFrame,
    bid_difference_by_gamma: pd.DataFrame,
    tail_scenario_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    bid_weekly = (
        bid_difference_by_gamma.groupby(["artifact_id", "model_label", "week_id", "week_label", "regime_label", "cvar_gamma"], as_index=False)
        .agg(
            max_abs_bid_quantity_difference_mw_vs_gamma0=("max_abs_bid_quantity_difference_mw_vs_gamma0", "max"),
            total_abs_bid_quantity_difference_mwh_vs_gamma0=("total_abs_bid_quantity_difference_mwh_vs_gamma0", "sum"),
            max_abs_bid_quantity_difference_mw_vs_previous_gamma=("max_abs_bid_quantity_difference_mw_vs_previous_gamma", "max"),
            total_abs_bid_quantity_difference_mwh_vs_previous_gamma=("total_abs_bid_quantity_difference_mwh_vs_previous_gamma", "sum"),
            identical_to_gamma0_within_tolerance=("identical_to_gamma0_within_tolerance", "all"),
            identical_to_previous_gamma_within_tolerance=("identical_to_previous_gamma_within_tolerance", "all"),
        )
    )
    tail_weekly = (
        tail_scenario_diagnostics.groupby(["artifact_id", "model_label", "week_id", "week_label", "regime_label", "cvar_gamma"], as_index=False)
        .agg(
            worst_scenario_probability_mass=("worst_scenario_probability_mass", "max"),
            mean_cvar_tail_probability_mass=("cvar_tail_probability_mass", "mean"),
            max_cvar_tail_probability_mass=("cvar_tail_probability_mass", "max"),
            mean_number_of_tail_scenarios=("number_of_tail_scenarios", "mean"),
            max_number_of_tail_scenarios=("number_of_tail_scenarios", "max"),
            days_with_tail_set_change_vs_previous_gamma=("whether_tail_scenarios_change_vs_previous_gamma", "sum"),
            days_with_worst_scenario_change_vs_previous_gamma=("whether_worst_scenario_changes_vs_previous_gamma", "sum"),
        )
    )
    merged = weekly_metrics.merge(
        bid_weekly,
        on=["artifact_id", "model_label", "week_id", "week_label", "regime_label", "cvar_gamma"],
        how="left",
    ).merge(
        tail_weekly,
        on=["artifact_id", "model_label", "week_id", "week_label", "regime_label", "cvar_gamma"],
        how="left",
    )
    return merged.sort_values(["week_label", "cvar_gamma"]).reset_index(drop=True)


def _build_fine_gamma_aggregated(cvar_fine_gamma_weekly: pd.DataFrame) -> pd.DataFrame:
    aggregated = (
        cvar_fine_gamma_weekly.groupby(["artifact_id", "model_label", "cvar_alpha", "cvar_gamma"], as_index=False)
        .agg(
            validation_week_count=("week_id", "nunique"),
            mean_realised_adjusted_profit=("realised_adjusted_profit", "mean"),
            worst_week_realised_adjusted_profit=("realised_adjusted_profit", "min"),
            mean_expected_adjusted_profit=("expected_adjusted_profit", "mean"),
            mean_cvar_tail_profit=("cvar_tail_profit", "mean"),
            worst_scenario_profit=("worst_scenario_profit", "min"),
            mean_clearing_ratio=("clearing_ratio", "mean"),
            mean_rejected_energy=("rejected_energy_mwh", "mean"),
            mean_shortfall=("shortfall_kg", "mean"),
            mean_unused_cleared_energy=("unused_cleared_energy_mwh", "mean"),
            mean_high_bid_share=("high_bid_share", "mean"),
            mean_value_captured_vs_perfect_foresight=("value_captured_vs_perfect_foresight", "mean"),
            mean_solve_time_seconds=("solve_time_seconds", "mean"),
            max_abs_bid_quantity_difference_mw_vs_gamma0=("max_abs_bid_quantity_difference_mw_vs_gamma0", "max"),
            total_abs_bid_quantity_difference_mwh_vs_gamma0=("total_abs_bid_quantity_difference_mwh_vs_gamma0", "sum"),
            mean_total_abs_bid_quantity_difference_mwh_vs_gamma0=("total_abs_bid_quantity_difference_mwh_vs_gamma0", "mean"),
            identical_to_gamma0_all_weeks=("identical_to_gamma0_within_tolerance", "all"),
            mean_cvar_tail_probability_mass=("mean_cvar_tail_probability_mass", "mean"),
            days_with_tail_set_change_vs_previous_gamma=("days_with_tail_set_change_vs_previous_gamma", "sum"),
            days_with_worst_scenario_change_vs_previous_gamma=("days_with_worst_scenario_change_vs_previous_gamma", "sum"),
        )
    )
    return aggregated.sort_values("cvar_gamma").reset_index(drop=True)


def _build_daily_gamma_sensitivity_matrix(cvar_fine_gamma_daily: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "artifact_id",
        "model_label",
        "week_id",
        "week_label",
        "regime_label",
        "delivery_day",
        "cvar_gamma",
        "realised_adjusted_profit",
        "expected_adjusted_profit",
        "cvar_tail_profit",
        "worst_scenario_profit",
        "clearing_ratio",
        "rejected_energy_mwh",
        "shortfall_kg",
        "high_bid_share",
        "weighted_average_bid_price",
        "max_abs_bid_quantity_difference_mw_vs_gamma0",
        "total_abs_bid_quantity_difference_mwh_vs_gamma0",
    ]
    return cvar_fine_gamma_daily[cols].sort_values(["week_label", "delivery_day", "cvar_gamma"]).reset_index(drop=True)


def _plot_single_metric_by_gamma(
    aggregated: pd.DataFrame,
    metric: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if aggregated.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    color = MODEL_COLORS.get("LEAR FS3 pruned candidate", "#3A7D7C")
    ax.plot(aggregated["cvar_gamma"], pd.to_numeric(aggregated[metric], errors="coerce"), marker="o", linewidth=1.8, color=color)
    for _, row in aggregated.iterrows():
        ax.annotate(f"{float(row['cvar_gamma']):g}", (float(row["cvar_gamma"]), float(row[metric])), fontsize=7, textcoords="offset points", xytext=(0, 6), ha="center")
    ax.set_title(title)
    ax.set_xlabel("Gamma")
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_fine_gamma_risk_return_frontier(cvar_fine_gamma_weekly: pd.DataFrame, output_path: Path) -> None:
    if cvar_fine_gamma_weekly.empty:
        return
    apply_visual_style()
    week_colors = {
        "high_price": "#7F3C8D",
        "typical_summer": "#11A579",
        "winter_proxy": "#F2B701",
        "high_volatility": "#3969AC",
    }
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    for regime_label, group in cvar_fine_gamma_weekly.groupby("regime_label", sort=False):
        group = group.sort_values("cvar_gamma")
        ax.plot(
            pd.to_numeric(group["cvar_tail_profit"], errors="coerce"),
            pd.to_numeric(group["realised_adjusted_profit"], errors="coerce"),
            marker="o",
            linewidth=1.6,
            color=week_colors.get(str(regime_label), "#666666"),
            label=str(regime_label),
        )
        for _, row in group.iterrows():
            ax.annotate(f"{float(row['cvar_gamma']):g}", (float(row["cvar_tail_profit"]), float(row["realised_adjusted_profit"])), fontsize=7)
    ax.set_xlabel("CVaR tail profit (-CVaR loss)")
    ax.set_ylabel("Realised adjusted profit (EUR)")
    ax.set_title("LEAR FS3 fine-gamma validation risk-return frontier")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_daily_heatmap(
    matrix: pd.DataFrame,
    *,
    metric: str,
    title: str,
    output_path: Path,
) -> None:
    if matrix.empty:
        return
    apply_visual_style()
    frame = matrix.copy()
    frame["row_label"] = frame["week_label"].astype(str) + " | " + frame["delivery_day"].astype(str)
    pivot = frame.pivot(index="row_label", columns="cvar_gamma", values=metric).sort_index()
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.36 * pivot.shape[0] + 1.8)))
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto", cmap="viridis")
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index.tolist())
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels([f"{float(value):g}" for value in pivot.columns.tolist()], rotation=45, ha="right")
    ax.set_xlabel("Gamma")
    ax.set_title(title)
    cbar = fig.colorbar(im, ax=ax)
    cbar.ax.set_ylabel(metric, rotation=90)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_figures(
    *,
    run_dir: Path,
    aggregated: pd.DataFrame,
    cvar_fine_gamma_weekly: pd.DataFrame,
    daily_gamma_sensitivity_matrix: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_realised_adjusted_profit",
        ylabel="Mean realised adjusted profit (EUR)",
        title="LEAR FS3 fine-gamma mean realised profit",
        output_path=figures_dir / "fig_fine_gamma_realised_profit.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_cvar_tail_profit",
        ylabel="Mean CVaR tail profit (EUR)",
        title="LEAR FS3 fine-gamma mean CVaR tail profit",
        output_path=figures_dir / "fig_fine_gamma_cvar_tail_profit.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="worst_scenario_profit",
        ylabel="Worst scenario profit (EUR)",
        title="LEAR FS3 fine-gamma worst scenario profit",
        output_path=figures_dir / "fig_fine_gamma_worst_scenario_profit.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_clearing_ratio",
        ylabel="Mean clearing ratio",
        title="LEAR FS3 fine-gamma mean clearing ratio",
        output_path=figures_dir / "fig_fine_gamma_clearing_ratio.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_rejected_energy",
        ylabel="Mean rejected energy (MWh)",
        title="LEAR FS3 fine-gamma mean rejected energy",
        output_path=figures_dir / "fig_fine_gamma_rejected_energy.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_shortfall",
        ylabel="Mean shortfall (kg)",
        title="LEAR FS3 fine-gamma mean shortfall",
        output_path=figures_dir / "fig_fine_gamma_shortfall.png",
    )
    _plot_single_metric_by_gamma(
        aggregated,
        metric="mean_total_abs_bid_quantity_difference_mwh_vs_gamma0",
        ylabel="Mean absolute bid difference vs gamma 0 (MWh)",
        title="LEAR FS3 fine-gamma bid difference vs gamma 0",
        output_path=figures_dir / "fig_fine_gamma_bid_difference_vs_gamma0.png",
    )
    _plot_fine_gamma_risk_return_frontier(
        cvar_fine_gamma_weekly,
        figures_dir / "fig_fine_gamma_risk_return_frontier.png",
    )
    _plot_daily_heatmap(
        daily_gamma_sensitivity_matrix,
        metric="realised_adjusted_profit",
        title="Daily realised adjusted profit by gamma",
        output_path=figures_dir / "fig_daily_gamma_heatmap_realised_profit.png",
    )
    _plot_daily_heatmap(
        daily_gamma_sensitivity_matrix,
        metric="total_abs_bid_quantity_difference_mwh_vs_gamma0",
        title="Daily bid difference vs gamma 0 by gamma",
        output_path=figures_dir / "fig_daily_gamma_heatmap_bid_difference.png",
    )


def _summarise_plateau(aggregated: pd.DataFrame) -> dict[str, str]:
    if aggregated.empty:
        return {
            "operational_plateau_gamma": "undetermined",
            "first_material_tail_improvement_gamma": "undetermined",
            "conservative_tail_plateau_gamma": "undetermined",
        }
    frame = aggregated.sort_values("cvar_gamma").reset_index(drop=True)
    positive = frame.loc[frame["cvar_gamma"].astype(float) > 0.0].copy()
    if positive.empty:
        return {
            "operational_plateau_gamma": "0",
            "first_material_tail_improvement_gamma": "0",
            "conservative_tail_plateau_gamma": "0",
        }
    baseline_tail = float(frame.loc[frame["cvar_gamma"].astype(float).abs() <= 1e-12, "mean_cvar_tail_profit"].iloc[0])
    max_tail = float(frame["mean_cvar_tail_profit"].max())
    max_tail_gain = max_tail - baseline_tail
    best_positive_profit = float(positive["mean_realised_adjusted_profit"].max())
    max_bid_diff = float(positive["mean_total_abs_bid_quantity_difference_mwh_vs_gamma0"].max())

    operational_plateau_gamma = float(positive["cvar_gamma"].iloc[-1])
    for _, row in positive.iterrows():
        profit_close = float(row["mean_realised_adjusted_profit"]) >= best_positive_profit - 250.0
        bid_change_arrived = float(row["mean_total_abs_bid_quantity_difference_mwh_vs_gamma0"]) >= 0.95 * max_bid_diff
        if profit_close and bid_change_arrived:
            operational_plateau_gamma = float(row["cvar_gamma"])
            break

    first_material_tail_gamma = float(positive["cvar_gamma"].iloc[-1])
    conservative_tail_plateau_gamma = float(positive["cvar_gamma"].iloc[-1])
    if max_tail_gain <= 1e-9:
        first_material_tail_gamma = 0.0
        conservative_tail_plateau_gamma = 0.0
    else:
        material_threshold = baseline_tail + 0.10 * max_tail_gain
        conservative_threshold = baseline_tail + 0.95 * max_tail_gain
        for _, row in positive.iterrows():
            if float(row["mean_cvar_tail_profit"]) >= material_threshold:
                first_material_tail_gamma = float(row["cvar_gamma"])
                break
        for _, row in positive.iterrows():
            if float(row["mean_cvar_tail_profit"]) >= conservative_threshold:
                conservative_tail_plateau_gamma = float(row["cvar_gamma"])
                break
    return {
        "operational_plateau_gamma": f"{operational_plateau_gamma:g}",
        "first_material_tail_improvement_gamma": f"{first_material_tail_gamma:g}",
        "conservative_tail_plateau_gamma": f"{conservative_tail_plateau_gamma:g}",
    }


def _write_readme(
    *,
    run_dir: Path,
    selected_weeks: pd.DataFrame,
    artifact_id: str,
    cvar_alpha: float,
    gamma_values: list[float],
    aggregated: pd.DataFrame,
    validation_checks: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
) -> None:
    hard_fail_count = int(
        validation_checks.loc[
            (validation_checks["severity"].astype(str) == "hard_fail")
            & (validation_checks["status"].astype(str) != "pass")
        ].shape[0]
    )
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) != "pass"].shape[0])
    plateau_summary = _summarise_plateau(aggregated)
    top_rows = aggregated[
        [
            "cvar_gamma",
            "mean_realised_adjusted_profit",
            "mean_expected_adjusted_profit",
            "mean_cvar_tail_profit",
            "worst_scenario_profit",
            "mean_total_abs_bid_quantity_difference_mwh_vs_gamma0",
            "identical_to_gamma0_all_weeks",
        ]
    ].round(3)
    lines = [
        "# README_fine_gamma_diagnostic",
        "",
        "- scope: validation-only fine-gamma diagnostic on common partial support",
        f"- artifact: `{artifact_id}`",
        "- model: `LEAR FS3 pruned candidate`",
        f"- selected validation weeks: {selected_weeks['week_label'].astype(str).tolist()}",
        f"- alpha: {float(cvar_alpha):.2f}",
        f"- gamma grid: {[float(value) for value in gamma_values]}",
        "- no test weeks used",
        "- no scenario or probability changes applied",
        "- perfect foresight is an oracle upper bound only",
        "",
        "## Purpose",
        "",
        "Determine whether LEAR FS3 responds materially below gamma = 0.05, and whether the apparent plateau comes from identical bids, small bid changes with no operational effect, tail-scenario degeneracy, or weekly aggregation masking day-level movement.",
        "",
        "## Aggregated Response",
        "",
        top_rows.to_string(index=False),
        "",
        f"- operational plateau gamma: {plateau_summary['operational_plateau_gamma']}",
        f"- first material tail-improvement gamma: {plateau_summary['first_material_tail_improvement_gamma']}",
        f"- conservative tail-plateau gamma: {plateau_summary['conservative_tail_plateau_gamma']}",
        f"- hard validation failures: {hard_fail_count}",
        f"- CVaR validation failures: {cvar_fail_count}",
        "",
        "## Methodological Warnings",
        "",
        "- validation-only fine-gamma diagnostic, not final test reporting",
        "- no selected test week was used",
        "- results remain conditional on the existing scenario undercoverage",
        "- no MILP formulation change was introduced in this phase",
    ]
    save_text(run_dir, "README_fine_gamma_diagnostic.md", "\n".join(lines))


def _finalize_outputs(
    *,
    run_dir: Path,
    selected_weeks: pd.DataFrame,
    support_days: pd.DataFrame,
    artifact_id: str,
    gamma_values: list[float],
    cvar_alpha: float,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    submitted_bids: pd.DataFrame,
    scenario_clearing: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    actual_settlement_results: pd.DataFrame,
    validation_checks_existing: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
) -> PhaseD3FineGammaResult:
    bid_difference_by_gamma = _compute_bid_difference_by_gamma(
        submitted_bids,
        gamma_values=gamma_values,
        timestep_hours=1.0,
    )
    tail_scenario_diagnostics = _compute_tail_scenario_diagnostics(
        scenario_settlement_results,
        gamma_values=gamma_values,
    )
    cvar_fine_gamma_daily = (
        daily_metrics.merge(bid_difference_by_gamma, on=_merge_on_gamma_keys(), how="left").merge(
            tail_scenario_diagnostics,
            on=_merge_on_gamma_keys(),
            how="left",
        )
    ).sort_values(["week_label", "delivery_day", "cvar_gamma"]).reset_index(drop=True)
    cvar_fine_gamma_weekly = _build_fine_gamma_weekly(weekly_metrics, bid_difference_by_gamma, tail_scenario_diagnostics)
    cvar_fine_gamma_aggregated = _build_fine_gamma_aggregated(cvar_fine_gamma_weekly)
    daily_gamma_sensitivity_matrix = _build_daily_gamma_sensitivity_matrix(cvar_fine_gamma_daily)

    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        scenario_settlement_results=scenario_settlement_results,
        gamma_values=gamma_values,
        cvar_alpha=float(cvar_alpha),
    )
    validation_checks_all_runs = _build_suite_validation_checks(
        existing_checks=validation_checks_existing,
        selected_weeks=selected_weeks,
        support_days=support_days,
        artifact_id=artifact_id,
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        perfect_foresight_daily=perfect_foresight_daily,
        perfect_foresight_included=not perfect_foresight_daily.empty,
        gamma_values=gamma_values,
        cvar_alpha=float(cvar_alpha),
        scenario_settlement_results=scenario_settlement_results,
    )

    save_frame_csv(run_dir, "cvar_fine_gamma_daily.csv", cvar_fine_gamma_daily)
    save_frame_csv(run_dir, "cvar_fine_gamma_weekly.csv", cvar_fine_gamma_weekly)
    save_frame_csv(run_dir, "cvar_fine_gamma_aggregated.csv", cvar_fine_gamma_aggregated)
    save_frame_csv(run_dir, "bid_difference_by_gamma.csv", bid_difference_by_gamma)
    save_frame_csv(run_dir, "tail_scenario_diagnostics.csv", tail_scenario_diagnostics)
    save_frame_csv(run_dir, "daily_gamma_sensitivity_matrix.csv", daily_gamma_sensitivity_matrix)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)

    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)
    save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
    save_frame_parquet(run_dir, "submitted_bids.parquet", submitted_bids)
    save_frame_parquet(run_dir, "scenario_clearing.parquet", scenario_clearing)
    save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
    save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "selected_weeks_manifest_table.csv", selected_weeks)
    save_frame_csv(notebook_inputs_dir, "support_days.csv", support_days)
    save_frame_csv(notebook_inputs_dir, "cvar_fine_gamma_daily.csv", cvar_fine_gamma_daily)
    save_frame_csv(notebook_inputs_dir, "cvar_fine_gamma_weekly.csv", cvar_fine_gamma_weekly)
    save_frame_csv(notebook_inputs_dir, "cvar_fine_gamma_aggregated.csv", cvar_fine_gamma_aggregated)
    save_frame_csv(notebook_inputs_dir, "bid_difference_by_gamma.csv", bid_difference_by_gamma)
    save_frame_csv(notebook_inputs_dir, "tail_scenario_diagnostics.csv", tail_scenario_diagnostics)
    save_frame_csv(notebook_inputs_dir, "daily_gamma_sensitivity_matrix.csv", daily_gamma_sensitivity_matrix)
    save_frame_csv(notebook_inputs_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(notebook_inputs_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)

    _create_figures(
        run_dir=run_dir,
        aggregated=cvar_fine_gamma_aggregated,
        cvar_fine_gamma_weekly=cvar_fine_gamma_weekly,
        daily_gamma_sensitivity_matrix=daily_gamma_sensitivity_matrix,
    )
    _write_readme(
        run_dir=run_dir,
        selected_weeks=selected_weeks,
        artifact_id=artifact_id,
        cvar_alpha=float(cvar_alpha),
        gamma_values=gamma_values,
        aggregated=cvar_fine_gamma_aggregated,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )

    hard_fail_count = int(
        validation_checks_all_runs.loc[
            (validation_checks_all_runs["severity"].astype(str) == "hard_fail")
            & (validation_checks_all_runs["status"].astype(str) != "pass")
        ].shape[0]
    )
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) != "pass"].shape[0])
    if hard_fail_count > 0 or cvar_fail_count > 0:
        raise RuntimeError(
            f"Phase D3 completed but validation failed (hard_fail_count={hard_fail_count}, cvar_fail_count={cvar_fail_count}); see run folder {run_dir}."
        )

    notebook_path = Path("scripts/Data/03_Hydrogen_Test_Case/notebooks/12_fine_gamma_lear_fs3_diagnostic.ipynb")
    return PhaseD3FineGammaResult(
        run_dir=run_dir,
        notebook_path=notebook_path,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        fine_gamma_aggregated=cvar_fine_gamma_aggregated,
        bid_difference_by_gamma=bid_difference_by_gamma,
        tail_scenario_diagnostics=tail_scenario_diagnostics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )


def run_validation_cvar_fine_gamma_diagnostic(
    *,
    config: HydrogenConfig | str | Path,
    week_ids: list[str] | tuple[str, ...] = DEFAULT_WEEK_IDS,
    artifact_id: str = DEFAULT_ARTIFACT_ID,
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_FINE_GAMMAS,
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_d3_lear_fs3_fine_gamma_validation_diagnostic",
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
) -> PhaseD3FineGammaResult:
    gamma_list = [float(value) for value in gamma_values]
    if gamma_list != list(DEFAULT_FINE_GAMMAS):
        raise ValueError(
            "Phase D3 requires gamma grid exactly [0, 0.001, 0.0025, 0.005, 0.01, 0.015, 0.02, 0.025, 0.05], "
            f"got {gamma_list}."
        )
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase D3 requires alpha 0.95, got {cvar_alpha}.")
    if str(artifact_id) != DEFAULT_ARTIFACT_ID:
        raise ValueError(f"Phase D3 requires artifact {DEFAULT_ARTIFACT_ID!r}, got {artifact_id!r}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase D3 requires the price-insensitive benchmark to be included.")

    selected_weeks, support_days = _load_and_validate_phase_d2_weeks(
        week_registry_path=Path(week_registry_path),
        support_csv_path=Path(support_csv_path),
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        week_ids=week_ids,
    )

    suite_config = _build_phase_d_config(
        config,
        artifact_ids=[str(artifact_id)],
        output_root=output_root,
        experiment_name=str(run_slug),
    )
    run_id, run_dir = create_run_folder(suite_config)
    save_config_resolved(run_dir, suite_config)
    input_paths = [suite_config.config_path, suite_config.models.scenario_catalog, Path(week_registry_path), Path(support_csv_path)]
    if selected_weeks_yaml_path is not None:
        input_paths.append(Path(selected_weeks_yaml_path))
    save_inputs_manifest(run_dir, input_paths)
    preflight = run_selected_week_input_preflight(
        config=suite_config,
        artifact_ids=[str(artifact_id)],
        requested_identifiers=[str(value) for value in week_ids],
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        expected_split="validation",
        cache_root=run_dir / "cache",
        output_policy_name="minimal",
    )
    save_frame_csv(run_dir, "selected_week_input_preflight.csv", preflight.audit_rows)
    save_frame_csv(run_dir, "selected_week_input_runtime_profile.csv", preflight.runtime_profile)
    if not preflight.audit_rows.empty and not preflight.audit_rows["status"].astype(str).eq("pass").all():
        raise RuntimeError(
            "Phase D3 selected-week input preflight failed before optimisation; "
            f"see {run_dir / 'selected_week_input_preflight.csv'}."
        )

    save_json(
        run_dir,
        "selected_weeks_manifest.json",
        {
            "selected_weeks": selected_weeks[["week_id", "week_label", "delivery_start_date", "delivery_end_date", "regime_label", "methodological_use", "support_status"]].to_dict(orient="records"),
            "selected_delivery_days": support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist(),
            "support_label": "validation-only fine-gamma diagnostics on common partial support",
        },
    )
    save_json(
        run_dir,
        "cvar_settings_manifest.json",
        {
            "alpha": float(cvar_alpha),
            "gamma_values": gamma_list,
            "gamma_zero_label": "risk_neutral",
            "objective_convention": "maximize_expected_adjusted_profit_minus_gamma_times_cvar_loss",
            "loss_convention": "loss = - adjusted_profit",
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

    week_row_lookup = {str(row["week_label"]): pd.Series(row) for row in selected_weeks.to_dict(orient="records")}
    delivery_to_week = {
        pd.Timestamp(row["delivery_date"]).strftime("%Y-%m-%d"): {
            "week_id": str(row["week_id"]),
            "week_label": str(row["week_label"]),
            "regime_label": str(row["regime_label"]),
        }
        for row in support_days.to_dict(orient="records")
    }
    selected_delivery_days = set(delivery_to_week.keys())

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
    benchmark_cache: dict[str, pd.Series] = {}
    perfect_foresight_profit_by_day: dict[str, pd.Series] = {}

    selected_daily, _, spec, catalog_entry, manifest = _valid_daily_registry_for_artifact(
        config=suite_config,
        artifact_id=str(artifact_id),
    )
    selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(selected_delivery_days)].copy()
    if int(selected_daily.shape[0]) != len(selected_delivery_days):
        raise ValueError(f"Artifact {artifact_id!r} produced {int(selected_daily.shape[0])} validation days for Phase D3; expected {len(selected_delivery_days)}.")
    selected_daily = selected_daily.sort_values("delivery_day").reset_index(drop=True)
    model_label = _label_for_artifact(str(artifact_id))
    validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
    thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
    reconstruction_used = bool(manifest.get("forecast_origin_reconstruction_used", manifest.get("forecast_origin_reconstructed", False)))

    for day_record in selected_daily.to_dict(orient="records"):
        delivery_day = str(day_record["delivery_day"])
        week_meta = delivery_to_week[delivery_day]
        week_row = week_row_lookup[str(week_meta["week_label"])].copy()
        benchmark_key = delivery_day
        for gamma in gamma_list:
            risk_mode = "risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar"
            include_benchmark = include_price_insensitive_benchmark and benchmark_key not in benchmark_cache
            result = run_real_scenario_bidding_dry_run(
                config=day_run_config,
                artifact_id=str(artifact_id),
                forecast_origin_utc=str(pd.Timestamp(day_record["forecast_origin_utc"]).isoformat()),
                max_origins=1,
                output_root=day_output_root,
                strategy_name="stochastic_bid_risk_neutral" if risk_mode == "risk_neutral" else "stochastic_bid_cvar",
                dry_run_label=f"{week_meta['week_label']}_gamma_{_normalized_gamma_tag(gamma)}",
                include_price_insensitive_comparison=include_benchmark,
                risk_measure=risk_mode,
                cvar_alpha=float(cvar_alpha),
                cvar_gamma=float(gamma),
                write_outputs=True,
            )
            if not result.benchmark_comparison.empty:
                benchmark_row = result.benchmark_comparison.iloc[0].copy()
                benchmark_cache[benchmark_key] = benchmark_row
                benchmark_daily_rows.append(
                    _benchmark_daily_row(
                        benchmark_row=benchmark_row,
                        artifact_id=str(artifact_id),
                        model_label=model_label,
                        week_id=str(week_meta["week_id"]),
                        week_label=str(week_meta["week_label"]),
                        delivery_day=delivery_day,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        run_id=run_id,
                    )
                )
            else:
                benchmark_row = benchmark_cache.get(benchmark_key)

            if include_perfect_foresight_benchmark and delivery_day not in perfect_foresight_profit_by_day:
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
                perfect_foresight_profit_by_day[delivery_day] = pf_row
                perfect_foresight_daily_rows.append(
                    _perfect_foresight_daily_row(
                        pf_row=pf_row,
                        week_id=str(week_meta["week_id"]),
                        week_label=str(week_meta["week_label"]),
                        regime_label=str(week_meta["regime_label"]),
                        delivery_day=delivery_day,
                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                        run_id=run_id,
                    )
                )
            pf_row = perfect_foresight_profit_by_day.get(delivery_day)

            metric_row = _build_daily_metric_row(
                result=result,
                artifact_id=str(artifact_id),
                model_label=model_label,
                validation_mode=validation_mode,
                thesis_grade=thesis_grade,
                forecast_origin_reconstruction_used=reconstruction_used,
                week_row=week_row,
                day_row=pd.Series(day_record),
                cvar_alpha=float(cvar_alpha),
                cvar_gamma=float(gamma),
                benchmark_row=benchmark_row,
            )
            metric_row["regime_label"] = str(week_meta["regime_label"])
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
                    artifact_id=str(artifact_id),
                    model_label=model_label,
                    week_id=str(week_meta["week_id"]),
                    week_label=str(week_meta["week_label"]),
                    regime_label=str(week_meta["regime_label"]),
                    delivery_day=delivery_day,
                    forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                    cvar_alpha=float(cvar_alpha),
                    cvar_gamma=float(gamma),
                    risk_mode=str(risk_mode),
                )
            )
            metadata = {
                "artifact_id": str(artifact_id),
                "model_label": model_label,
                "week_id": str(week_meta["week_id"]),
                "week_label": str(week_meta["week_label"]),
                "regime_label": str(week_meta["regime_label"]),
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

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["week_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase D3 produced no daily metrics.")
    daily_metrics["run_id"] = str(run_id)
    daily_metrics["period_type"] = "validation"

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_checks_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["week_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["week_label", "delivery_day"]).reset_index(drop=True)
    perfect_foresight_daily = pd.DataFrame(perfect_foresight_daily_rows).sort_values(["week_label", "delivery_day"]).reset_index(drop=True)
    scenario_frame = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    coverage = _scenario_coverage_by_day(scenario_frame)
    daily_metrics = daily_metrics.merge(
        coverage,
        on=["artifact_id", "model_label", "delivery_day", "cvar_gamma"],
        how="left",
    )

    weekly_parts: list[pd.DataFrame] = []
    benchmark_metrics_parts: list[pd.DataFrame] = []
    for _, week_row in selected_weeks.iterrows():
        week_id = str(week_row["week_id"])
        week_daily = daily_metrics.loc[daily_metrics["week_id"].astype(str).eq(week_id)].copy()
        week_weekly = _aggregate_weekly_metrics(week_daily, selected_week=pd.Series(week_row)).copy()
        week_weekly["regime_label"] = str(week_row["regime_label"])
        weekly_parts.append(week_weekly)
        bench_subset = benchmark_daily.loc[benchmark_daily["week_id"].astype(str).eq(week_id)].copy()
        if not bench_subset.empty:
            bench_week = _aggregate_benchmark_metrics(bench_subset, selected_week=pd.Series(week_row)).copy()
            bench_week["regime_label"] = str(week_row["regime_label"])
            benchmark_metrics_parts.append(bench_week)
    weekly_metrics = pd.concat(weekly_parts, ignore_index=True).sort_values(["week_label", "cvar_gamma"]).reset_index(drop=True)
    benchmark_metrics = pd.concat(benchmark_metrics_parts, ignore_index=True) if benchmark_metrics_parts else pd.DataFrame()
    perfect_foresight_metrics = _aggregate_perfect_foresight_metrics(perfect_foresight_daily)

    if not perfect_foresight_metrics.empty:
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
        weekly_metrics["regret_vs_perfect_foresight"] = pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce") - pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")
    else:
        weekly_metrics["perfect_foresight_profit"] = pd.NA
        weekly_metrics["value_captured_vs_perfect_foresight"] = pd.NA
        weekly_metrics["regret_vs_perfect_foresight"] = pd.NA
    weekly_metrics["cvar_tail_profit"] = -pd.to_numeric(weekly_metrics["cvar_loss"], errors="coerce")

    scenario_manifest = {
        "phase": "D3",
        "support_label": "validation-only fine-gamma diagnostics on common partial support",
        "artifacts": scenario_manifest_rows,
    }
    save_json(run_dir, "scenario_manifest.json", scenario_manifest)
    save_frame_csv(run_dir, "solver_log_manifest.csv", _build_solver_log_manifest(day_run_dirs))
    save_frame_csv(run_dir, "day_run_dirs.csv", day_run_dirs)

    result = _finalize_outputs(
        run_dir=run_dir,
        selected_weeks=selected_weeks,
        support_days=support_days,
        artifact_id=str(artifact_id),
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        submitted_bids=submitted_bids,
        scenario_clearing=scenario_clearing,
        scenario_settlement_results=scenario_settlement_results,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        actual_settlement_results=actual_settlement_results,
        validation_checks_existing=validation_checks_existing,
        benchmark_daily=benchmark_daily,
        perfect_foresight_daily=perfect_foresight_daily,
    )
    return result
